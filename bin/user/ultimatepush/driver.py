#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""The WeeWX end of it.

Deliberately thin. The socket belongs to weewx.listener, the exchange to protocols/,
the field names to catalogs/. What is left here is the part that has to know about
WeeWX: loop packets, unit groups, and shutting down when told to.

What happens to one upload, in order:

    1.  Split into name/value pairs.                        transport.parse
    2.  Decide which protocol sent it.                      protocols.detect
    3.  Check it is a console this driver answers to.       consoles
    4.  Decide which catalog to read it with.               protocol.dialect
    5.  Turn it into a packet.                              mapping.Mapper
    6.  Say what units the numbers are in, and hand it on.

Steps 2 and 4 are separate questions. Weather Underground carries two catalogs on one
endpoint, so knowing the protocol does not tell you the field names.

Configuration:

    [UltimatePush]
        driver = user.ultimatepush.driver
        port = 8000
        # path = /a-secret-of-your-choosing/report
        # protocols = auto
        # infer_unknown = series
        # [[field_map_extensions]]
        #     yearlyrainin = rain_year
"""

import logging
import time

import weewx
import weewx.drivers
import weewx.units

from . import (VERSION, activity, admin, checklist, columns, consoles,
               mapping, overrides, owners, protocols, report, roles, server,
               transport)
from .mapping import Mapper

try:
    # WeeWX 5.6 and later carry the listener.
    from weewx.listener import HTTPListener, UDPListener
    LISTENER_FROM = 'weewx.listener'
except ImportError:
    # Older WeeWX gets the copy that ships with this extension. Byte for byte the same
    # file, checked by a test, and it stops shipping once 5.6 is everywhere.
    from user.listener import HTTPListener, UDPListener
    LISTENER_FROM = 'user.listener, the bundled copy'

log = logging.getLogger(__name__)

DRIVER_NAME = 'UltimatePush'
DRIVER_VERSION = VERSION

# What to answer an upload nobody claimed. A 200 with nothing in it, because a device
# that is retrying is worse than one that thinks it succeeded, and by the time we are
# here the log already says what arrived.
UNCLAIMED_ANSWER = ('', 'text/plain')

# What to show first from an upload nobody has claimed yet. These are the readings a
# person can check against a thermometer or a look out of the window, which is the
# only way to tell your own new console from somebody else's.
TELLING = ('outTemp', 'outHumidity', 'windSpeed', 'windDir', 'barometer', 'dayRain',
           'radiation', 'inTemp', 'inHumidity')
A_HANDFUL = 12

# Options that belong to this driver and must not reach the listener, which would
# reject what it does not recognise.
NOT_FOR_LISTENER = frozenset([
    'driver', 'field_map_extensions', 'infer_unknown', 'model', 'report_file',
    'stations', 'passkey', 'password', 'console_file', 'weewx_root', 'sqlite_root',
    'data_binding', 'config_dict', 'protocols', 'metric_wind', 'max_behind',
    'max_ahead', 'udp_port', 'web', 'path', 'override_file',
])


def loader(config_dict, _engine):
    """Build the driver, as WeeWX asks for it.

    Args:
        config_dict (dict): The whole of weewx.conf.
        _engine: The WeeWX engine, which this driver does not need.

    Returns:
        UltimatePushDriver: The driver.
    """
    options = dict(config_dict[DRIVER_NAME])
    # The console list belongs with the readings it protects, so the driver is given
    # what it needs to reach the database.
    options.setdefault('config_dict', config_dict)
    # Where to keep the list of consoles this driver answers to. Beside weewx.conf,
    # unless the driver section says otherwise.
    options.setdefault('weewx_root', config_dict.get('WEEWX_ROOT'))
    options.setdefault('sqlite_root',
                       config_dict.get('DatabaseTypes', {})
                                  .get('SQLite', {})
                                  .get('SQLITE_ROOT'))
    return UltimatePushDriver(**options)


def confeditor_loader():
    return UltimatePushConfEditor()


class Station:
    """One console, and the mappers it has needed so far.

    A mapper per dialect rather than per station, because a station that switches
    from the Ecowitt protocol to Weather Underground mid-life is a supported thing to
    do, and inference learned from one catalog must not be applied to the other.
    """

    def __init__(self, name, ident, extensions, infer_unknown, max_behind,
                 max_ahead, role=roles.MAIN, channel=None):
        """Set up one station.

        Args:
            name (str): What to call it, or None.
            ident (str): What the console sends to name itself.
            extensions (dict): Raw field to WeeWX field, set by hand.
            infer_unknown (str): What to do with a field the catalog misses.
            max_behind (int): How far behind the console's clock may be.
            max_ahead (int): The same, for a clock that runs fast.
            role (str): MAIN or EXTRA. See roles.py.
            channel (int): Which extra channel it writes to.
        """
        self.name = name
        self.ident = ident
        self.extensions = extensions
        self.infer_unknown = infer_unknown
        self.max_behind = max_behind
        self.max_ahead = max_ahead
        # Which fields this station may fill. See roles.py. One station is always
        # 'main' and nothing here does anything to it.
        self.role = role
        self.channel = channel
        # An upload path of this station's own, where it has one. Set from
        # weewx.conf or made by the web interface.
        self.path = None
        self.mappers = {}

    def mapper_for(self, dialect, announce=True):
        """The mapper for this dialect, made the first time it is needed.

        `announce` is off when a rebuilt station is being given back the catalogs the
        one before it had. That is bookkeeping, not news, and somebody clicking
        through a field map would otherwise get a line of log per click.

        Args:
            dialect (Dialect): The catalog this station's uploads are read with.
            announce (bool): Whether to log that the catalog is in use.

        Returns:
            Mapper: The mapper for that dialect.
        """
        mapper = self.mappers.get(dialect.name)
        if mapper is None:
            # The role moves this station's readings out of the main station's way.
            # A field named by hand outranks it, which is why it goes underneath.
            extensions = roles.extensions_for(self.role, self.channel,
                                              dialect.fields)
            extensions.update(self.extensions)
            mapper = Mapper(dialect, extensions=extensions,
                            infer_unknown=self.infer_unknown,
                            max_behind=self.max_behind, max_ahead=self.max_ahead)
            self.mappers[dialect.name] = mapper
            if announce:
                log.info("Reading %s uploads%s with the '%s' catalog, %d fields.",
                         dialect.name.split('/')[0],
                         " from '%s'" % self.name if self.name else '',
                         dialect.name, len(dialect.fields))
        return mapper


class _NoStation:
    """Stands in for a station that did not exist before, so that taking its
    catalogs over needs no special case."""

    mappers = {}


_NO_STATION = _NoStation()


class UltimatePushDriver(weewx.drivers.AbstractDevice):
    """Receives uploads from hardware that pushes, and turns them into loop packets."""

    def __init__(self, **stn_dict):
        self.model = stn_dict.get('model', 'UltimatePush')
        self.infer_unknown = stn_dict.get('infer_unknown', 'series')
        # How far the console's clock may be out before its own timestamp is dropped.
        # A console on the internet keeps its clock by NTP, so a stamp a few minutes
        # old means the upload was delayed, not that the clock is wrong.
        self.max_behind = int(stn_dict.get('max_behind', transport.MAX_BEHIND))
        self.max_ahead = int(stn_dict.get('max_ahead', transport.MAX_AHEAD))

        self.enabled = self._read_protocols(stn_dict.get('protocols'))
        self._apply_protocol_options(stn_dict)
        log.info("Driver version is %s, listening with %s for %s",
                 DRIVER_VERSION, LISTENER_FROM,
                 ', '.join(p.label for p in self.enabled))
        for protocol in self.enabled:
            if protocol.datagram:
                log.info("%s broadcasts on UDP %d and is answered by nobody, so "
                         "anything on this network can reach it. Restrict it with "
                         "'allowed_hosts' if that matters.",
                         protocol.label, protocol.default_port)

        # One mapping, or one per console. Two consoles both number their channels
        # from one, so without this a WN34 on channel 1 of each would overwrite the
        # other, and afterwards neither could be recovered.
        self.conf_extensions = dict(stn_dict.get('field_map_extensions', {}))
        self.stations = self._read_stations(stn_dict.get('stations'))
        # Stations the web interface recorded. Kept apart from the ones weewx.conf
        # names, so that a field set in weewx.conf can always be seen to be the one
        # in force.
        self.web_stations = {}
        self.default_station = None if self.stations else Station(
            None, None, dict(self.conf_extensions),
            self.infer_unknown, self.max_behind, self.max_ahead)
        self.password = stn_dict.get('password')

        # What the web interface shows, and where what it changes is kept. Both are
        # built whether or not the interface is switched on: the activity log costs a
        # few kilobytes and is what makes a question about last Tuesday answerable,
        # and the settings file is read either way so that turning the interface off
        # does not quietly drop what it wrote.
        self.activity = activity.Log()
        self.overrides = overrides.Store(
            overrides.path_for(stn_dict.get('weewx_root'),
                               stn_dict.get('override_file'),
                               stn_dict.get('sqlite_root')),
            reserved=self._reserved_fields(stn_dict))
        self.overrides.read()
        # Set from the web server's thread, read by the loop. A bool is atomic enough
        # for this: the worst a race costs is that a change lands one upload later
        # than it might have.
        self.reload_wanted = False
        # Secret upload path -> station. Filled by _apply_overrides.
        self.station_paths = {}
        # Whether a station's own path has ever been used. Until one has, every path
        # is accepted: somebody who set a station up in the interface but has not
        # finished typing it into their console must not have their existing uploads
        # start bouncing.
        self.paths_proven = False
        self.config_path = _config_path(stn_dict.get('config_dict'))
        self.occupied = None
        # Whether the archive table has been asked what it already holds. Apart from
        # `occupied` being None, because "not read" and "read, and holds nothing" are
        # different answers and the interface says which one it got.
        self.history_read = False
        # The columns the archive table actually has. Not the schema: a database
        # made by an older WeeWX has fewer, and saying 'column ready' about one
        # that is not there sends somebody looking for a fault in the wrong place.
        self.present = None
        # Read once, for the setup checklist. A station left at the defaults has its
        # sunrise computed for the north pole, and nothing else says so.
        self.station_section = _station_section(stn_dict.get('config_dict'))
        self.listener_path = stn_dict.get('path')
        # Set when the web interface is switched on. See _web_listener.
        self.doorman = None

        # Which consoles to answer to. Anyone who can reach the port can point a
        # console at it, and a second one writing the same channels would mix two
        # sensors into one column. So the driver accepts the ones it knows and
        # refuses the rest.
        self.console_file = consoles.path_for(stn_dict.get('weewx_root'),
                                              stn_dict.get('console_file'),
                                              stn_dict.get('sqlite_root'))
        self.store = consoles.Store(self.console_file, stn_dict.get('config_dict'),
                                    stn_dict.get('data_binding', 'wx_binding'))
        self.configured_passkey = stn_dict.get('passkey')
        self.known = self._known_consoles(self.configured_passkey)
        self._apply_overrides()

        self._check_one_main()
        self._check_rain_delta(stn_dict.get('config_dict'))

        self.report_file = stn_dict.get('report_file', report.DEFAULT_PATH)
        self.reported = False
        self.unknown_consoles = set()
        self.unclaimed = 0
        self.assumed = False
        # What the main station has been seen to fill, so that an extra one can be
        # kept out of it. Learned rather than declared: it is what actually arrives.
        # Which station fills which archive column. See owners.py. Read from the
        # settings file, so a restart does not have to learn it again.
        self.owners = owners.Register(self.overrides.columns())
        self.said_apart = set()

        self.listener = server.Fan(self._listeners(stn_dict))

    @property
    def hardware_name(self):
        return self.model

    # ---- setting up ---------------------------------------------------------

    def _read_protocols(self, configured):
        """Which protocols to listen for.

        'auto', the default, is every protocol that arrives over HTTP. Detection is
        by what an upload contains rather than by which port it came to, so an unused
        one of those costs nothing but a name comparison.

        A protocol that broadcasts is not in 'auto'. It needs a second socket on a
        port of its own, and opening one for hardware nobody has is not a thing to do
        quietly. Name it and the socket opens.

        Naming them is also how you settle a payload that says nothing about itself:
        with one protocol configured there is nothing left to guess.

        Args:
            configured (str): What `protocols` was set to, as a comma-separated list or
                'auto'.

        Returns:
            list: The protocol classes to listen for.
        """
        if not configured or configured == 'auto':
            return protocols.posting()
        if isinstance(configured, str):
            wanted = [name.strip() for name in configured.split(',') if name.strip()]
        else:
            wanted = [str(name).strip() for name in configured]
        chosen = []
        for name in wanted:
            protocol = protocols.by_name(name)
            if protocol is None:
                raise ValueError(
                    "'%s' is not a protocol this driver knows. The choices are %s, "
                    "or 'auto' for all of them."
                    % (name, ', '.join(protocols.names())))
            chosen.append(protocol)
        return chosen

    def _apply_protocol_options(self, stn_dict):
        """Hand a protocol the one or two settings only the user can decide.

        Args:
            stn_dict (dict): The driver section of weewx.conf.
        """
        wind = stn_dict.get('metric_wind')
        if wind:
            from .protocols import wunderground
            if wind not in wunderground.METRIC_WIND_CHOICES:
                raise ValueError("metric_wind must be one of %s, not '%s'"
                                 % (', '.join(wunderground.METRIC_WIND_CHOICES), wind))
            wunderground.WeatherUnderground.metric_wind = wind

    def _check_one_main(self):
        """Say so when two stations both claim the standard fields.

        One station is the station. Two of them take turns writing outTemp every few
        seconds, and afterwards the column holds a mixture nothing can separate. The
        driver drops the second one's readings rather than let that happen, but a
        configuration that asks for it is worth saying out loud at startup.
        """
        everyone = dict(self.stations)
        everyone.update(self.web_stations)
        main = sorted(name for name, station in
                      ((s.name or i, s) for i, s in everyone.items())
                      if station.role == roles.MAIN)
        if len(main) > 1:
            log.warning(
                "%d stations are set up as the main one: %s. One is the station and "
                "the rest are extra sensors, or they write into each other's columns. "
                "Give all but one 'role = extra' and a 'channel', or set it in the "
                "web interface.", len(main), ', '.join(main))

    def _check_rain_delta(self, config_dict):
        """Say so when the rain will not be recorded, before a season of it is lost.

        None of this hardware sends the rain since the last upload. It sends running
        counters, and StdDelta is what turns one into a reading. The installer points
        it at dayRain, which is right for four of the six protocols and wrong for the
        two that have no such counter.

        Nothing here changes the configuration: rewriting somebody's StdWXCalculate
        from a driver would be worse than the problem. It says which line to change,
        once, at startup, which is where somebody is looking when they have just added
        a protocol.

        Args:
            config_dict (dict): The whole of weewx.conf, which is where StdWXCalculate
                lives.
        """
        if not config_dict:
            # Constructed without one, which is a test or a diagnostic run. There is
            # nothing to check and saying so would be noise.
            return
        wanted = {p.rain_counter for p in self.enabled if p.rain_counter}
        if not wanted:
            return
        configured = None
        try:
            configured = config_dict['StdWXCalculate']['Delta']['rain']['input']
        except (KeyError, TypeError):
            pass
        if configured in wanted:
            return
        if configured is None:
            log.warning(
                "Nothing differences the rain counters, so this station will record "
                "no rain. Add this to weewx.conf:\n"
                "    [StdWXCalculate]\n        [[Delta]]\n            [[[rain]]]\n"
                "                input = %s", sorted(wanted)[0])
            return
        log.warning(
            "StdWXCalculate differences '%s' to get the rain, and %s sends %s "
            "instead. Rain from %s will not be recorded until 'input' names a "
            "counter it sends.",
            configured,
            ', '.join(p.label for p in self.enabled if p.rain_counter not in
                      (None, configured)),
            ' or '.join(sorted(wanted - {configured})),
            ' and '.join(p.label for p in self.enabled
                         if p.rain_counter not in (None, configured)))

    def _reserved_fields(self, stn_dict):
        """Raw fields weewx.conf already places, so that nothing else may.

        Keyed by station identity, with None for the driver section's own map, which
        applies to every station. The web interface refuses to touch these: two files
        with an answer each would mean one of them is quietly ignored, and which one
        would depend on the order they happened to be read in.

        Args:
            stn_dict (dict): The driver section of weewx.conf.

        Returns:
            dict: Station identity, or None for the driver's own map, to the set of raw
            field names weewx.conf already places. The web interface refuses to write
            these, so that the two files cannot disagree about one field.
        """
        reserved = {None: set(stn_dict.get('field_map_extensions', {}))}
        for options in (stn_dict.get('stations') or {}).values():
            ident = str(options.get('passkey') or options.get('id') or '').strip()
            if ident:
                reserved[ident] = set(options.get('field_map_extensions', {}))
        return reserved

    def _apply_overrides(self):
        """Build the stations the web interface has recorded, and answer to them.

        Called at startup and again whenever the interface changes something. A
        station that weewx.conf already names is left alone: that file is the one in
        force, and this one does not get to disagree with it.
        """
        built = {}
        # From both files. A path written by hand works exactly like one the
        # interface made, which is the point: nothing here is only reachable by
        # clicking.
        paths = {station.path.rstrip('/'): ident
                 for ident, station in self.stations.items() if station.path}
        for ident, options in self.overrides.stations().items():
            if ident in self.stations:
                # weewx.conf names it. Nothing here may change that.
                continue
            secret = str(options.get('path', '')).strip()
            if secret:
                paths[secret.rstrip('/')] = ident
            extensions = dict(self.conf_extensions)
            extensions.update(options.get('field_map_extensions', {}))
            channel = options.get('channel')
            built[ident] = Station(
                options.get('name') or None, ident, extensions,
                options.get('infer_unknown', self.infer_unknown),
                self.max_behind, self.max_ahead,
                role=options.get('role', roles.MAIN),
                channel=int(channel) if channel else None)
            built[ident].path = secret or None
            # Give the rebuilt station the catalogs the old one had. A mapper is
            # otherwise made on the next upload, and until then nothing could say
            # where a reading now goes, so the page would show the change it had
            # just been asked to make as not having happened.
            for was in self.web_stations.get(ident, _NO_STATION).mappers.values():
                built[ident].mapper_for(was.dialect, announce=False)
        self.web_stations = built
        self.station_paths = paths
        for ident in built:
            self.known.add(ident)

    def _reload(self):
        """Take up what the web interface wrote, without a restart.

        Rebuilding a station drops its mappers, which drops the inference it had
        learned. That is the point: a field map that changed has to be read again
        from the start, or a reading would keep going where it went before.
        """
        self.reload_wanted = False
        self.overrides.read()
        self._apply_overrides()
        # Including who owns which column. Every claim is written as it is made, so
        # the file is the current answer and this cannot lose one.
        self.owners = owners.Register(self.overrides.columns())
        for station in self.web_stations.values():
            for mapper in station.mappers.values():
                self._register_units(mapper.wanted_groups())
        log.info("Took up the settings from %s.", self.overrides.path)

    def _read_stations(self, configured):
        """Return {identity: Station} for an installation with several consoles.

        Args:
            configured (dict): The [[stations]] subsection, or nothing.

        Returns:
            dict: Station identity to Station.

        Raises:
            ValueError: If a station has no identity, or a role that is not one of the
                two, because a configuration that cannot be read is not one to guess at.
        """
        if not configured:
            return {}
        stations = {}
        for name, options in configured.items():
            ident = options.get('passkey') or options.get('id')
            if not ident:
                raise ValueError(
                    "Station '%s' has no 'passkey' or 'id'. It is whichever of the "
                    "two the console sends first in every upload: a PASSKEY for "
                    "Ecowitt and Ambient hardware, an ID for Weather Underground."
                    % name)
            channel = options.get('channel')
            station = Station(
                name, str(ident).strip(),
                dict(options.get('field_map_extensions', {})),
                options.get('infer_unknown', self.infer_unknown),
                self.max_behind, self.max_ahead,
                role=options.get('role', roles.MAIN),
                channel=int(channel) if channel else None)
            if station.role not in roles.ROLES:
                raise ValueError("Station '%s' has role '%s'. It is one of %s."
                                 % (name, station.role, ', '.join(roles.ROLES)))
            station.path = str(options.get('path', '')).strip() or None
            stations[str(ident).strip()] = station
        log.info("Listening for %d consoles: %s",
                 len(stations), ', '.join(sorted(s.name for s in stations.values())))
        return stations

    def _known_consoles(self, passkey):
        """The identities this driver answers to.

        From the driver section, from [[stations]], or from the file where the first
        console ever heard was recorded. Empty means nothing has been heard yet, and
        the next console to upload is adopted.

        Args:
            passkey (str): The identity set in the driver section, where there is one.

        Returns:
            set: The identities this driver answers to. Empty means nothing has
            been heard yet, and the next console to upload is adopted.
        """
        known = set(self.stations)
        known.update(self.overrides.stations())
        if passkey:
            known.add(str(passkey).strip())
        if known:
            return known
        remembered = set(self.store.read())
        if remembered:
            log.info("Answering to %d console(s) on record in the %s",
                     len(remembered), self.store.where)
        return remembered

    def _listeners(self, stn_dict):
        """The listeners this configuration needs.

        One HTTP listener for the protocols that post, and a UDP one only if a
        protocol that broadcasts is enabled. A port is opened for hardware somebody
        actually has, not for hardware they might buy.

        Args:
            stn_dict (dict): The driver section of weewx.conf.

        Returns:
            list: The listeners this configuration needs: one for HTTP, one more for
            WeatherFlow's broadcasts, and one more for the web interface.
        """
        options = {key: value for key, value in stn_dict.items()
                   if key not in NOT_FOR_LISTENER}
        listeners = []

        if any(not protocol.datagram for protocol in self.enabled):
            http = dict(options)
            # The answer is per request now, so the listener's own is never used.
            http.pop('response', None)
            http.pop('content_type', None)
            # Not the configured path but a question, because a station set up while
            # WeeWX is running brings a path of its own with it.
            http['path'] = self.wanted_path
            listeners.append(server.http_listener(HTTPListener, self._answer, **http))

        for protocol in self.enabled:
            if not protocol.datagram:
                continue
            udp = {key: value for key, value in options.items()
                   if key in ('address', 'max_body', 'allowed_hosts', 'log_raw',
                              'queue_size', 'reuse_address')}
            udp['port'] = int(stn_dict.get('udp_port', protocol.default_port))
            listeners.append(UDPListener(**udp))

        web = self._web_listener(stn_dict.get('web'))
        if web is not None:
            listeners.append(web)

        return listeners

    def wanted_path(self, path):
        """Whether an upload to this path is one this driver answers for.

        Handed to the listener as a callable rather than a list, because a station
        can be set up while WeeWX is running and its path has to work from the next
        upload rather than the next restart.

        The driver's own path is always one of them. It is what the setup page tells
        people to type in, and it is how every console that cannot be given a path of
        its own arrives. Closing it because some other station now has a secret path
        would turn away the console that was here first, which is a station going
        quiet for a reason nobody would look for on this page.

        That costs nothing a station's own path was protecting. A path is a secret
        about which station an upload is from; who may upload at all is a separate
        question, and the answer to it is the list of consoles this driver knows.

        Everything else is accepted until a station has actually been heard on its
        own path. A path that has never worked is not yet protecting anything, and
        turning it into a 404 before that would break the console somebody is still
        in the middle of configuring.

        Args:
            path (str): The path the request arrived on.

        Returns:
            bool: Whether to answer it at all. A path that is not wanted gets a
            404 from the listener, before this driver sees the body.
        """
        path = (path or '/').rstrip('/')
        if path in self.station_paths:
            return True
        for protocol in self.enabled:
            if path in [p.rstrip('/') for p in protocol.paths]:
                return True
        if self.listener_path:
            return path == self.listener_path.rstrip('/')
        if path == '':
            return True
        return not self.paths_proven

    def _web_listener(self, configured):
        """The web interface, when it has been switched on and given a token.

        On a port of its own, because the token has to be checked at the listener and
        checking it on the data port would lock out hardware that cannot send one.

        Off unless asked for, and refused without a token, because the alternative is
        an interface that can change the field map sitting open on the network for
        anybody who guesses the port.

        Args:
            configured (dict): The [[web]] subsection, or nothing.

        Returns:
            A listener for the interface, or None when it is switched off.

        Raises:
            ValueError: If the token is missing or shorter than ten characters. An
                interface that can change the field map should not be open because
                somebody left a setting blank.
        """
        if not configured:
            return None
        from weeutil.weeutil import to_bool, to_int
        if not to_bool(configured.get('enable', False)):
            return None
        token = str(configured.get('token', '')).strip()
        if len(token) < admin.SHORTEST_TOKEN:
            raise ValueError(
                "The web interface needs 'token' set to at least %d characters. It "
                "is the only thing between the field map and whoever else is on the "
                "network. Make one with: "
                "python -c \"import secrets; print(secrets.token_urlsafe(12))\""
                % admin.SHORTEST_TOKEN)
        options = {
            'port': to_int(configured.get('port', 8080)),
            'address': configured.get('address', ''),
            'allowed_hosts': configured.get('allowed_hosts'),
            'trust_proxy': configured.get('trust_proxy', False),
            'queue_size': 1,
        }
        # The token is checked in admin.Site, not by the listener. The listener would
        # do it before anything of ours ran, which means a wrong one would be answered
        # and forgotten, and there would be nothing for the doorman to count.
        self.doorman = admin.Doorman(
            token,
            tries=to_int(configured.get('tries', admin.TRIES)),
            window=to_int(configured.get('window', admin.WINDOW)))
        site = admin.Site(self, self.doorman)
        listener = server.http_listener(HTTPListener, site.answer, queue=False,
                                        **options)
        # The whole address, because the alternative is somebody running `ip addr` to
        # find out where their own weather station is. A listener bound to every
        # interface reports itself as '*', which is true and useless.
        log.info("The web interface is at %s",
                 admin.url(options['address'], listener.port, token))
        log.info("That address holds the token, so treat the log the way you treat "
                 "weewx.conf. An address that gets the token wrong %d times in %d "
                 "seconds stops being answered. It is plain HTTP: on a network you "
                 "do not trust, set 'address = localhost' and use a tunnel, or put "
                 "TLS in front.", self.doorman.tries, self.doorman.window)
        return listener

    # ---- answering ----------------------------------------------------------

    def _answer(self, request):
        """What to send back, before the upload is queued.

        The payload is parsed here and again when the packet is built. That is two
        passes over a kilobyte, and it buys the thing that matters: an Ecowitt gateway
        gets its JSON and a Weather Underground client gets 'success', on the same
        port, in the same second. A device that does not get the answer it expects
        treats the upload as failed and retries until it gives up.

        Args:
            request: The upload, as the listener hands it over.

        Returns:
            tuple: (body, content_type), the reply this hardware waits for.
        """
        try:
            raw = transport.parse(request.text)
            protocol = protocols.detect(request, raw, self.enabled)
        except Exception as e:
            log.error("Cannot work out what sent this: %s", e)
            return UNCLAIMED_ANSWER
        if protocol is None:
            return UNCLAIMED_ANSWER
        return protocol.answer, protocol.content_type

    # ---- the loop -----------------------------------------------------------

    def genLoopPackets(self):
        for request in self.listener:
            packet = self._packet_from(request)
            if packet is not None:
                yield packet

    def reading_for(self, request):
        """How this upload would be read: (protocol, station, mapper, readings).

        All four are None when it is not an upload this driver keeps: nothing claimed
        it, it names a console that is not ours, or it presents the wrong password.
        Whichever it was has already been logged.

        Separate from _packet_from because "which mapping applies to this" is a
        question worth being able to ask without building a packet, and because it is
        the whole of what a second protocol changes.

        Args:
            request: The upload, as the listener hands it over.

        Returns:
            tuple: (protocol, station, mapper, readings). All four are None when
            this is not an upload the driver keeps.
        """
        if self.reload_wanted:
            self._reload()

        try:
            raw = transport.parse(request.text)
        except Exception as e:
            log.error("Cannot read a payload from %s: %s", request.client_address, e)
            return None, None, None, None

        protocol = protocols.detect(request, raw, self.enabled)
        if protocol is None:
            protocol = self._assumed()
        if protocol is None:
            self._unclaimed(request)
            self._record_refused(request, None, '',
                                 "no protocol recognised this", raw)
            return None, None, None, None

        # A station whose path is its own needs nothing else: the upload arrived
        # where only that console was told to send, which is a better answer than a
        # PASSKEY anybody can read off somebody else's upload and repeat.
        by_path = self.station_paths.get((request.path or '/').rstrip('/'))
        if by_path is not None:
            self.paths_proven = True
            station = (self.stations.get(by_path) or self.web_stations.get(by_path)
                       or self.default_station)
        else:
            # Which console this is, and whether it presents the right password, are
            # asked of the upload as it arrived. A protocol that unpacks its payload
            # may not carry the name through: WeatherFlow's observations are an array,
            # and the hub's serial is on the message around it rather than in it.
            station = self._station_for(protocol, raw, request.client_address)
        if station is None:
            self._record_refused(request, protocol, protocol.station_of(raw),
                                 "not one of this driver's consoles", raw)
            return None, None, None, None

        if protocol.secret and not self._secret_ok(protocol, raw,
                                                   request.client_address):
            self._record_refused(request, protocol, protocol.station_of(raw),
                                 "wrong %s" % protocol.secret, raw)
            return None, None, None, None

        raw = protocol.readings(request, raw)
        dialect = protocol.dialect(raw)
        mapper = station.mapper_for(dialect)
        mapper.settle(protocol.settled_contested(raw))
        return protocol, station, mapper, raw

    def _packet_from(self, request):
        """Turn one upload into a loop packet, or None if it is not ours to keep.

        Args:
            request: The upload, as the listener hands it over.

        Returns:
            dict: A loop packet, or None when nothing of it is to be kept.
        """
        protocol, station, mapper, raw = self.reading_for(request)
        if mapper is None:
            return None
        dialect = mapper.dialect

        try:
            packet, guesses = mapper.to_packet(raw)
        except Exception as e:
            log.error("Cannot read a %s payload from %s: %s",
                      protocol.name, request.client_address, e)
            return None

        if guesses:
            self._register_units(mapper.wanted_groups())
        else:
            self._register_units(dialect.groups)
        self._maybe_report(request.text, guesses, protocol)

        self._keep_stations_apart(station, packet)

        enough = len(packet) > 1
        self._record(request, protocol, dialect, raw, packet if enough else None,
                     station, mapper)

        if not enough:
            # Nothing but the timestamp. Usually a probe or a health check.
            return None
        packet['usUnits'] = dialect.units
        if station.name:
            packet['station'] = station.name
        return packet

    def _held_back_now(self):
        """Whether an extra station's readings are being held rather than written.

        Only until the main station has been heard once, ever. After that the
        register has its columns on disk and nothing waits again.
        """
        if not self._has_a_main_station():
            return False
        main = self._main_ident()
        return not (main is not None and self.owners.owns(main))

    def _has_a_main_station(self):
        """Whether any station is set up as the main one.

        If none is, there is nothing for an extra one to stay out of and holding it
        back would hold it back for ever. The console this driver adopted counts:
        nobody gave it the role, but it has it, and it fills the columns.
        """
        return bool(self._mains())

    def _keep_stations_apart(self, station, packet):
        """Let this station write only the columns it owns, and claim what is free.

        A column takes one answer. Whoever fills a column first owns it, everybody
        else is turned away from it, and the main station outranks that: otherwise
        which console owns outTemp would be settled by whichever one happened to
        upload first after a restart.

        Roles alone did not cover this. A role moves an extra station's temperature
        and humidity aside and drops what has nowhere to go, but "nowhere to go" was
        measured against the main station only. Three identical consoles set up as
        extra sensors all send soilmoisture1; if the main station is a console that
        has no such reading, all three used to write soilMoist1, in turn, every few
        seconds.

        See owners.py.

        Args:
            station (Station): Whichever station sent this upload.
            packet (dict): The loop packet, changed in place: readings this
                station may not write are taken out of it.
        """
        is_main = station is self.the_main_station()
        ident = station.ident or self._adopted_ident() or ''
        if self._hold_back(station, packet, is_main):
            return

        taken, dropped = [], []
        for field in owners.readings(packet):
            allowed, lost = self.owners.claim(field, ident, is_main)
            if not allowed:
                dropped.append(field)
                continue
            if lost is not None or self.owners.owner(field) == ident:
                if field not in self.overrides.columns():
                    taken.append(field)
            if lost is not None:
                self._said_lost(field, lost, station)

        for field in dropped:
            packet.pop(field, None)
        self.activity.kept_apart(ident, sorted(dropped))
        if taken:
            # Written once, when a column changes hands. New claims happen in the
            # first minutes of a run and then stop, so this is not a write per upload.
            self._remember_columns(taken, ident)
        if dropped:
            self._said_dropped(station, sorted(dropped))

    def _hold_back(self, station, packet, is_main):
        """Whether nothing of this upload may be written yet.

        Only while the register knows nothing about the main station: that is a fresh
        installation, or a settings file from before this driver kept a register. An
        extra station writing then would put its wind and pressure into columns the
        main station is about to claim, and one interval of two sensors in one column
        is what none of this is allowed to produce.

        After the main station's first upload this is over for good, because the
        register is on disk. It used to happen at every restart.

        Args:
            station (Station): The station that has just uploaded.
            packet (dict): The loop packet, emptied when the answer is yes.
            is_main (bool): Whether this is the one main station.

        Returns:
            bool: Whether nothing of this upload may be written yet.
        """
        if is_main or not self._has_a_main_station():
            return False
        main = self._main_ident()
        if main is not None and self.owners.owns(main):
            return False
        packet.clear()
        if 'waiting' not in self.said_apart:
            self.said_apart.add('waiting')
            log.info("Holding back station '%s' until the main station has been "
                     "heard once, so that its readings cannot land in the main "
                     "station's columns. This happens once, not at every restart.",
                     station.name or station.ident)
        return True

    def _remember_columns(self, fields, ident):
        """Write down who fills these columns, so a restart does not ask again.

        Args:
            fields (iterable): The columns just claimed.
            ident (str): The station that claimed them.
        """
        for field in fields:
            ok, message = self.overrides.set_column(field, ident)
            if not ok:
                log.warning("Cannot record who fills %s: %s", field, message)
                return

    def _said_lost(self, field, lost, station):
        """A column the main station has taken from somebody.

        Args:
            field (str): The column that changed hands.
            lost (str): The identity that held it until now.
            station (Station): The main station, which has just taken it.
        """
        was = self.web_stations.get(lost)
        log.warning(
            "%s now holds readings from the main station '%s'. It held '%s' before, "
            "and that station is no longer writing it: two sensors in one column "
            "cannot be told apart afterwards. Give '%s' a field of its own if its "
            "reading matters.",
            field, station.name or station.ident,
            (was.name if was else None) or lost, (was.name if was else None) or lost)

    def _said_dropped(self, station, dropped):
        """One line for the lot, once per station per run.

        A second weather station has thirty readings with nowhere to go, and thirty
        copies of one sentence is not a log anybody reads.

        Args:
            station (Station): The station whose readings were dropped.
            dropped (list): The columns it did not get to write.
        """
        who = station.name or station.ident or 'an adopted console'
        if who in self.said_apart:
            return
        self.said_apart.add(who)
        owned = {f: self.owners.owner(f) for f in dropped}
        others = sorted({self._name_of(i) for i in owned.values() if i})
        if station.role == roles.MAIN and station is not self.the_main_station():
            # Two stations set up as the main one. Only a file written by hand can
            # say that, and naming the columns is more use than repeating the count.
            log.error(
                "Station '%s' is set up as the main station, and so is '%s'. Two of "
                "them write the same columns, and afterwards nothing can tell one "
                "sensor's readings from the other's. %d reading(s) from '%s' are not "
                "being written: %s. Give it 'role = extra' and a 'channel', or a "
                "[[field_map_extensions]] that sends them somewhere of their own.",
                who, self._main_name(), len(dropped), who, ', '.join(dropped))
            return
        log.warning(
            "%d reading(s) from station '%s' are not being written, because %s "
            "already fill(s) those columns and two sensors in one column cannot be "
            "separated afterwards: %s. Give them fields of their own under "
            "[[field_map_extensions]], or take the column away from its owner on the "
            "Fields tab.",
            len(dropped), who, ' and '.join(others) or 'another station',
            ', '.join(dropped))

    def named_by_hand(self, ident):
        """The WeeWX fields somebody has set for this station themselves.

        A field named by hand is a decision. If it turns out not to be written after
        all, that is worth saying out loud, where the same reading dropped because a
        role moved it is only the role doing its job.

        Args:
            ident (str): The station's identity.

        Returns:
            set: The WeeWX fields set for it by hand, in either file.
        """
        station = self.stations.get(ident) or self.web_stations.get(ident)
        named = set(self.overrides.extensions_for(ident).values())
        if station is not None:
            named.update(station.extensions.values())
        return named

    def name_of_owner(self, field):
        """Who fills one column, by name, for saying so on a page.

        Args:
            field (str): A WeeWX field.

        Returns:
            str: The name of the station that fills it, or an empty string.
        """
        ident = self.owners.owner(field)
        return self._name_of(ident) if ident else ''

    def _name_of(self, ident):
        """One station's name, for saying which one.

        Args:
            ident (str): A station identity.

        Returns:
            str: Its name, or the identity itself when it has no name.
        """
        station = self.stations.get(ident) or self.web_stations.get(ident)
        return (station.name if station else None) or ident

    def _main_name(self):
        main = self.the_main_station()
        if main is None:
            return 'nothing'
        return main.name or main.ident or 'the adopted console'

    # ---- what the web interface reads ---------------------------------------

    def _record(self, request, protocol, dialect, raw, packet, station, mapper):
        """Keep the upload, so that a question about it can be answered later.

        Bounded and in memory only. See activity.py.

        Args:
            request: The upload as it arrived.
            protocol: The protocol that claimed it.
            dialect (Dialect): The catalog it was read with.
            raw (dict): The raw name/value pairs.
            packet (dict): The loop packet, or None when nothing was kept.
            station (Station): Which station it belongs to.
            mapper (Mapper): The mapper that read it.
        """
        # Under the station's own identity where it has one, not under whatever the
        # payload happens to say. Two consoles of the same model send the same shape
        # of upload, and a station set up with a path of its own is that station even
        # if a PASSKEY in the body says something else.
        ident = station.ident or protocol.station_of(raw)
        self.activity.arrived(ident, activity.Upload(
            at=time.time(), client=request.client_address,
            path=request.path or '', method=request.method or '',
            text=request.text or '', ident=ident, protocol=protocol.name,
            dialect=dialect.name,
            packet={k: v for k, v in (packet or {}).items() if k != 'dateTime'}))
        if station.name:
            self.activity.named(ident, station.name)
        # Only the readings. PASSKEY, dateutc and the rest name the device
        # rather than measure anything, and a page that offered to place them
        # would be offering a mistake.
        readings = [name for name in raw if name not in dialect.metadata]
        self.activity.mapping(ident, readings, mapper.fields, mapper.seen,
                              mapper.undecided)

    def _record_refused(self, request, protocol, ident, note, raw=None):
        """Keep an upload that was turned away, so the page can show it.

        Args:
            request: The upload as it arrived.
            protocol: The protocol that claimed it, where one did.
            ident (str): Whatever named the station, or an empty string.
            note (str): Why it was refused, for showing on the page.
            raw (dict): The raw name/value pairs, where they could be read.
        """
        self.activity.refused(activity.Upload(
            at=time.time(), client=request.client_address,
            path=request.path or '', method=request.method or '',
            text=request.text or '', ident=ident,
            protocol=protocol.name if protocol else None,
            readings=self._knocking_readings(request, protocol, raw), note=note))

    def _knocking_readings(self, request, protocol, raw):
        """A few of the readings from an upload nobody claimed.

        A card that says only "ecowitt from 192.168.1.51, 12 seen" asks somebody to
        let a stranger into their database or turn their own new console away, and
        gives them nothing to tell the two apart. Nine degrees and ninety per cent
        tells them apart at a glance.

        The raw name is kept beside the WeeWX field, because the raw name is what the
        hardware said and carries its own unit: `tempf` is Fahrenheit whatever this
        driver would have done with it.

        Args:
            request: The upload as it arrived.
            protocol: The protocol that claimed it, where one did.
            raw (dict): The raw name/value pairs.

        Returns:
            list: A few readings in plain sight, so that somebody can tell their
            own new console from a stranger's.
        """
        if not isinstance(raw, dict):
            return []
        dialect, flat = None, raw
        if protocol is not None:
            try:
                flat = protocol.readings(request, raw)
                dialect = protocol.dialect(flat)
            except Exception:                       # pylint: disable=broad-except
                dialect, flat = None, raw
        fields = dialect.fields if dialect else {}
        hide = set(dialect.metadata if dialect else ())
        for secret in (getattr(protocol, 'secret', None),
                       getattr(protocol, 'identity', None)):
            if secret:
                hide.add(secret)
        rank = {name: n for n, name in enumerate(TELLING)}

        def worth_showing_first(item):
            """How interesting a reading is, for choosing what to show.

            Args:
                item (tuple): A (raw name, value) pair.

            Returns:
                tuple: A sort key that puts the readings somebody can recognise their
                own console by ahead of the rest.
            """
            return rank.get(fields.get(item[0]), len(TELLING)), item[0]

        rows = []
        for name, value in sorted(flat.items(), key=worth_showing_first):
            if name in hide or isinstance(value, (dict, list, tuple)):
                continue
            rows.append({'raw': name, 'value': value, 'field': fields.get(name, '')})
            if len(rows) >= A_HANDFUL:
                break
        return rows

    def web_address(self):
        """The address somebody types into their console's app to reach this driver.

        This machine's own, because the answer to "what do I put in the app" is not
        "your address".
        """
        return admin.lan_address() or 'this-machine'

    def data_port(self):
        """The port the readings arrive on, as opposed to the interface's."""
        return self.listener.ports[0] if self.listener.ports else 8000

    def data_path(self):
        """The path to type into the app, or '/' when any will do."""
        return self.listener_path or '/'

    def station_location(self):
        """What weewx.conf says about where the station is, or None if unreadable."""
        return self.station_section

    def web_setup(self):
        """What is still in the way of a station that records properly."""
        return checklist.summary(self)

    def web_overview(self):
        """Everything the front page draws."""
        stations = self.activity.snapshot()
        for row in stations:
            known = self._station_for_ident(row['ident'])
            row['role'] = getattr(known, 'role', roles.MAIN)
            row['channel'] = getattr(known, 'channel', None)
            # Held back because the main station has not been heard since this driver
            # started. Nothing of this station is being recorded, and a row that only
            # said "last seen 4s ago" would look like it was working.
            row['held_back'] = bool(
                known is not None and known.role != roles.MAIN
                and self._held_back_now())
            seen = set(row.get('raw_seen', ()))
            row['field_count'] = len(seen)
            row['undecided_count'] = len(seen & set(row.get('undecided', {})))
            row.pop('fields', None)
            row.pop('guesses', None)
            row.pop('undecided', None)
            row.pop('raw_seen', None)
        return {
            'ok': True,
            'version': DRIVER_VERSION,
            'uptime': admin.uptime(self.activity.started),
            'ports': [port for port in self.listener.ports if port],
            'protocols': [p.name for p in self.enabled],
            'settings_file': self.overrides.path,
            'settings_error': self.overrides.error,
            'door': self.doorman.state() if self.doorman else None,
            'stations': sorted(stations, key=lambda r: r['ident']),
            'waiting': self.web_waiting(),
        }

    def web_waiting(self):
        """The stations being turned away, as of now.

        A station that was refused an hour ago and has since been let in is not
        waiting for anything. Without this it would sit under "waiting to be let in"
        until twenty more refusals had pushed its old uploads out of the ring, which
        reads as the button not having worked.

        Returns:
            list: One entry per console, with what named it and a few readings, so
            that somebody can tell their own new console from a stranger's.
        """
        return [w for w in self.activity.unknown_stations(transport.redact)
                if w['ident'] not in self.known]

    def web_station(self, ident):
        """One station, every raw field it has sent, and where each one stands.

        This is the page the whole interface exists for. A row says what arrived,
        where it goes, whether there is a column for it, and whether that column
        already holds somebody else's readings. The last of those is the one thing a
        log line cannot tell you and the one thing that makes the decision
        irreversible if it is wrong.

        Args:
            ident (str): The station's identity.

        Returns:
            dict: Every raw field it has sent and where each one stands, or None
            when no such station has uploaded.
        """
        found = self.activity.one(ident)
        if found is None:
            return None
        station = self._station_for_ident(ident)
        recent = self.activity.recent(ident, transport.redact, limit=1)
        last = (recent[0].get('packet') or {}) if recent else {}
        reserved = (self.overrides.reserved.get(ident, set())
                    | self.overrides.reserved.get(None, set()))
        groups = {}
        for mapper in (station.mappers.values() if station else []):
            groups.update(mapper.wanted_groups())
        rows = self._field_rows(found, station, last, groups, reserved)
        seen = set(found['raw_seen'])
        found['ok'] = True
        found['role'] = getattr(station, 'role', 'main')
        found['channel'] = getattr(station, 'channel', None)
        found['fields'] = rows
        found['undecided'] = sorted(seen & set(found['undecided']))
        found['guesses'] = sorted(seen & set(found['guesses']))
        return found

    def _field_rows(self, found, station, last, groups, reserved):
        """One row per raw field this station has sent, and where each one stands.

        Only what it has actually sent. The catalog is five hundred names long, and
        the answer to "where does my reading go" is not helped by four hundred and
        fifty rows about sensors nobody owns.

        Args:
            found (dict): What the activity log holds for this station.
            station (Station): The station itself, where the driver has one.
            last (dict): Its most recent packet, for the current value.
            groups (dict): WeeWX field to unit group.
            reserved (set): Raw names weewx.conf places, which the interface may
                not change.

        Returns:
            list: One row per raw field the station has sent.
        """
        present = self.columns_present()
        occupied = self.occupied or {}
        placed = self._placements(station)
        rows = []
        for raw in sorted(found['raw_seen']):
            field = placed.get(raw, found['fields'].get(raw, ''))
            guess = found['guesses'].get(raw)
            why = ''
            if raw in found['undecided']:
                field = ''
                why = ("drivers disagree: this one says %s, %s says %s"
                       % (found['fields'].get(raw, '?'),
                          _contested_with(station), found['undecided'][raw]))
            elif guess:
                field, why = guess[0], guess[2]
            nowhere = field == mapping.NOWHERE
            rows.append({
                'raw': raw,
                'field': '' if nowhere else field,
                'nowhere': nowhere,
                'value': last.get(field),
                'group': (groups.get(field)
                          or weewx.units.obs_group_dict.get(field, '')),
                'column': bool(field) and not nowhere and field in present,
                'history': (occupied.get(field) or (0,))[0],
                'reserved': raw in reserved,
                'why': why,
            })
        return rows

    def history(self, refresh=False):
        """{column: (rows, last timestamp)} for archive columns that already hold data.

        Read the first time somebody asks and kept, because it is a pass over the
        whole table and the answer only changes as slowly as the archive grows. Not
        read in the constructor: WeeWX is waiting on that, and a database with years
        in it would make the driver look like it hangs at startup.

        None when there was no database to read or reading it failed, which is not
        the same as an empty answer: "nothing has history" and "nobody could look"
        lead somewhere different, and the interface says which one it got.

        Args:
            refresh (bool): Read the table again rather than using what is kept.

        Returns:
            dict: Each column that holds data, to (rows, most recent timestamp), or
            None when there was no database to read or reading it failed.
        """
        if refresh:
            self.occupied = None
            self.history_read = False
        if self.occupied is None and not self.history_read:
            # Tried, whatever comes of it. A database that cannot be read would
            # otherwise be tried again on every page load.
            self.history_read = True
            if self.config_path:
                try:
                    self.occupied = columns.occupied(self.config_path)
                except Exception as e:          # pylint: disable=broad-except
                    log.warning("Cannot read what the archive table already holds: "
                                "%s", e)
        return self.occupied

    def columns_present(self, refresh=False):
        """The columns the archive table has, or the schema when it cannot be read.

        Read once and kept, because it changes only when somebody adds one, and this
        is asked on every page load.

        Args:
            refresh (bool): Read the table again rather than using what is kept.

        Returns:
            set: The columns the archive table has, or the standard schema when
            there is no database to ask.
        """
        if self.present is None or refresh:
            self.present = None
            if self.config_path:
                try:
                    self.present = columns.existing(self.config_path)
                except Exception as e:              # pylint: disable=broad-except
                    log.debug("Cannot read the archive table's columns: %s", e)
        if self.present is not None:
            return self.present
        return admin.schema_fields()

    def web_stations_view(self):
        """Every station this driver knows, and what can be changed about each.

        One list rather than three. A station set up here and not yet heard from, a
        station uploading, and a station declared in weewx.conf are all answers to
        the same question, and somebody looking for the one that is main should not
        have to know which of the three it is to find it.
        """
        heard = {row['ident']: row for row in self.activity.snapshot()}
        main = self.the_main_station()
        found = []
        for ident, station in sorted(self.stations.items()):
            found.append(self._station_row(ident, station, heard, main,
                                           declared=True))
        for ident, station in sorted(self.web_stations.items()):
            found.append(self._station_row(ident, station, heard, main,
                                           declared=False))
        adopted = self._adopted_ident()
        if adopted is not None:
            found.append(self._station_row(adopted, self.default_station, heard,
                                           main, declared=False, adopted=True))
        taken = sorted(s['channel'] for s in found
                       if s['role'] == roles.EXTRA and s['channel'])
        return {
            'ok': True,
            'stations': found,
            'channels': roles.CHANNELS,
            'taken': taken,
            'settings_file': self.overrides.path,
        }

    def _station_row(self, ident, station, heard, main, declared, adopted=False):
        """One station, as the interface needs to show and change it.

        Args:
            ident (str): The station's identity.
            station (Station): The station itself.
            heard (dict): Identity to what the activity log holds, for the ones
                that have uploaded.
            main (Station): Whichever station is the main one, for marking it.
            declared (bool): Whether weewx.conf declares it, in which case the
                interface shows it and declines to change it.
            adopted (bool): Whether this is the console adopted as the first one
                ever heard, which is named in no file.

        Returns:
            dict: The station, as the Stations tab needs it.
        """
        row = heard.get(ident) or {}
        named = (self.overrides.station(ident).get('protocol')
                 or row.get('protocol') or '')
        return {
            'ident': ident,
            'name': station.name or row.get('name') or '',
            'protocol': named,
            # What to put into the console, with this station's own path in it. The
            # setup checklist shows this once and then stops, because it is a
            # checklist; a console reset a year later needs it again, and this is
            # where somebody would look for it.
            'settings': self._pointing_at(named, station.path),
            'role': station.role,
            'channel': station.channel,
            'path': station.path or '',
            'declared': declared,
            # A console adopted because it was the first one ever heard. It is named
            # in neither file, so there is nothing here to edit: what it needs is a
            # name, and that is what setting it up gives it.
            'adopted': adopted,
            'editable': not declared and not adopted,
            'is_main': station is main,
            'heard': ident in heard,
            'last_seen': row.get('last_seen'),
            'uploads': row.get('uploads', 0),
            # The archive columns this station fills. A sensor that was taken down
            # goes on holding its column until somebody says otherwise, because the
            # alternative is a station losing its columns while it is offline.
            'columns': self.owners.owns(ident),
        }

    def _pointing_at(self, protocol_name, path):
        """What a console of this kind has to be told, to reach this station.

        Args:
            protocol_name (str): Which protocol the console speaks.
            path (str): This station's own upload path, or nothing for the
                driver's general path.

        Returns:
            dict: What to put into the console, or None for a protocol this driver
            does not have.
        """
        protocol = protocols.by_name(protocol_name) if protocol_name else None
        if protocol is None:
            return None
        return checklist._pointing(protocol, self.web_address(), self.data_port(),
                                   path or self.data_path())

    def web_before(self, protocol_name='', role=None, channel=None, ident=None):
        """What setting a station up this way would land on, before it is done.

        Two things somebody would want to know first, and neither of them is visible
        anywhere else: which station stops being the main one, and which archive
        columns already hold readings that this station would start writing into.

        The second is the one a driver can normally never see. Columns with history
        got it from somewhere: an older console, a different driver, an import. If
        that is the same weather station in the same place, writing on is exactly
        right and the series carries on. If it is not, the column ends up holding two
        sensors, and afterwards nothing can say which reading came from which. That
        is a question with two real answers, so it is asked rather than guessed.

        Args:
            protocol_name (str): Which protocol the station speaks.
            role (str): The role being asked for, or None to take the default.
            channel (int): The channel being asked for, or None to be given one.
            ident (str): The station this is about, for a station that exists.

        Returns:
            dict: Which station would stop being the main one, which columns
            already hold readings, and whether the archive could be read at all.
        """
        used = self.history()
        role = role or (roles.EXTRA if self._mains() else roles.MAIN)
        # A channel arrives from a query string, so it arrives as text.
        try:
            channel = int(channel) if channel else None
        except (TypeError, ValueError):
            channel = None
        if role == roles.EXTRA and not channel:
            channel = self._free_channel(exclude=ident)

        taking_from = None
        if role == roles.MAIN:
            mains = self._mains()
            others = [i for i in mains if i != ident]
            if others:
                station = mains[others[0]]
                taking_from = {
                    'name': station.name or others[0],
                    'channel': self._free_channel(exclude=others[0]),
                    'declared': others[0] in self.stations,
                }

        return {
            'ok': True,
            'role': role,
            'channel': channel,
            'taking_from': taking_from,
            # None when there is no database to read. Not the same as nothing being
            # in the way, and the page says which of the two it is.
            'checked': used is not None,
            'columns': self._columns_with_history(protocol_name, role, channel,
                                                  ident, used or {}),
        }

    def _columns_with_history(self, protocol_name, role, channel, ident, used):
        """Archive columns this station would write into that already hold readings.

        Sorted by how much is in them: a column with four years of temperature is a
        different question from one with three rows in it from a Tuesday somebody was
        testing.

        Args:
            protocol_name (str): Which protocol the station speaks.
            role (str): MAIN or EXTRA.
            channel (int): The channel, for an extra sensor.
            ident (str): The station this is about, where it exists already.
            used (dict): What the archive table holds, from history().

        Returns:
            list: One entry per column, with how many rows it holds and the date
            of the most recent, most-used first.
        """
        if role == roles.EXTRA:
            wanted = set(roles.columns_for(channel)) if channel else set()
        else:
            wanted = self._would_fill(protocol_name, ident)
        found = []
        for field in sorted(wanted & set(used)):
            count, last = used[field]
            found.append({
                'field': field,
                'count': count,
                'last': (time.strftime('%Y-%m-%d', time.localtime(last))
                         if last else '?'),
            })
        return sorted(found, key=lambda r: -r['count'])

    def _would_fill(self, protocol_name, ident):
        """Which WeeWX fields a main station of this kind would fill.

        What it has actually sent, where it has sent anything: a catalog holds five
        hundred names and a console uses forty, and warning about the four hundred
        and sixty a station does not have would bury the ones it does.

        Args:
            protocol_name (str): Which protocol the station speaks.
            ident (str): The station, where it has uploaded before.

        Returns:
            set: The WeeWX fields it would fill as the main station.
        """
        row = self.activity.one(ident) if ident else None
        if row and row.get('raw_seen'):
            station = self._station_for_ident(ident)
            filled = set()
            for mapper in (station.mappers.values() if station else []):
                for raw, field in mapper.fields.items():
                    if raw in row['raw_seen']:
                        filled.add(field)
            if filled:
                return filled
        protocol = protocols.by_name(protocol_name) if protocol_name else None
        if protocol is None:
            return set()
        return set(protocol.dialect({}).fields.values())

    def web_fields(self):
        """Every raw field of every station, and where each one goes.

        One view rather than one per station. The question somebody has is not "what
        does this station send", it is "who fills outTemp", and with two stations
        that answer is spread over two pages, neither of which can show the collision
        that matters.
        """
        stations = []
        for row in sorted(self.activity.snapshot(), key=lambda r: r['ident']):
            ident = row['ident']
            station = self._station_for_ident(ident)
            recent = self.activity.recent(ident, transport.redact, limit=1)
            last = (recent[0].get('packet') or {}) if recent else {}
            reserved = (self.overrides.reserved.get(ident, set())
                        | self.overrides.reserved.get(None, set()))
            groups = {}
            for mapper in (station.mappers.values() if station else []):
                groups.update(mapper.wanted_groups())
            stations.append({
                'ident': ident,
                'name': row.get('name') or '',
                'protocol': row.get('protocol') or '',
                'role': getattr(station, 'role', roles.MAIN),
                'channel': getattr(station, 'channel', None),
                'declared': ident in self.stations,
                'rows': self._field_rows(row, station, last, groups, reserved),
            })
        return {
            'ok': True,
            'stations': stations,
            'holders': self._holders(),
            'settings_file': self.overrides.path,
        }

    def _placements(self, station):
        """Raw field -> WeeWX field, as the station is set up now.

        Not as its last upload turned out. The activity log holds what was written,
        and between somebody changing a placement and the next upload arriving those
        are two different answers. The interface promises the next upload everywhere
        else, so it has to show the next upload here.

        Args:
            station (Station): The station, or None when the driver has no record
                of one.

        Returns:
            dict: Raw field name to WeeWX field, as the station is set up now
            rather than as its last upload turned out.
        """
        placed = {}
        for mapper in (station.mappers.values() if station else []):
            for raw, field in mapper.fields.items():
                # A field two drivers place differently is not written until somebody
                # says which. Until then it holds nothing, and saying otherwise would
                # have the interface offering to take a column away from a reading
                # that never had it.
                placed[raw] = '' if raw in mapper.undecided else field
        return placed

    def _holders(self):
        """Which raw field of which station fills each WeeWX field.

        The register is the answer, not this: a column belongs to whoever filled it
        first and the data path turns everybody else away from it. What is worked out
        here is which raw reading of theirs it was, so that a page can say "outTemp is
        filled by tempf from garden" rather than only naming the station.

        Columns nobody has filled yet are here too, from what a station's map says it
        would write. They are what the interface has to warn about before somebody
        picks one of them twice.
        """
        holders = {}
        rows = {row['ident']: row for row in self.activity.snapshot()}
        for field, ident in self.owners.owned.items():
            row = rows.get(ident) or {}
            holders[field] = {'ident': ident, 'name': self._name_of(ident),
                              'raw': self._raw_behind(ident, field, row)}
        for ident, row in rows.items():
            placed = self._placements(self._station_for_ident(ident))
            for raw in row.get('raw_seen', ()):
                field = placed.get(raw, row['fields'].get(raw))
                if not field or field == mapping.NOWHERE:
                    continue
                holders.setdefault(field, {'ident': ident,
                                           'name': row.get('name') or ident,
                                           'raw': raw})
        return holders

    def _raw_behind(self, ident, field, row):
        """Which reading of this station ends up in that column.

        Args:
            ident (str): The station's identity.
            field (str): The column it fills.
            row (dict): What the activity log holds for it.

        Returns:
            str: The raw reading that ends up in that column, or an empty string.
        """
        placed = self._placements(self._station_for_ident(ident))
        for raw in row.get('raw_seen', ()):
            if placed.get(raw, row.get('fields', {}).get(raw)) == field:
                return raw
        return ''

    def web_add_column(self, field, sql_type=None):
        """Add one archive column, so that nobody has to leave for a terminal.

        The same ALTER TABLE that weectl database add-column runs. What it does not
        do, and neither does weectl, is give the column a daily summary: those tables
        are built from the declared schema when the database is made. Aggregates
        still work, computed from the archive table itself, which is slower and right.

        Args:
            field (str): The column to add.
            sql_type (str): REAL or INTEGER. Worked out from the unit group when
                it is not given.

        Returns:
            dict: Whether it worked, and a message fit to show somebody.
        """
        field = str(field or '').strip()
        if not field:
            return {'ok': False, 'message': "No column named."}
        if not self.config_path:
            return {'ok': False, 'message': (
                "This driver was started without a configuration file, so it cannot "
                "find the database. The command still works: weectl database "
                "add-column %s" % field)}
        if sql_type is None:
            sql_type = self._column_type(field)
        ok, message = columns.add(self.config_path, field, sql_type)
        if ok:
            self.columns_present(refresh=True)
        return {'ok': ok, 'message': message}

    def _column_type(self, field):
        """REAL for anything measured, INTEGER for anything counted.

        Args:
            field (str): A WeeWX field name.

        Returns:
            str: INTEGER for counted things, REAL for measured ones.
        """
        groups = {}
        for station in self._every_station():
            for mapper in station.mappers.values():
                groups.update(mapper.wanted_groups())
        group = groups.get(field) or weewx.units.obs_group_dict.get(field)
        return 'INTEGER' if group in columns.COUNTED else 'REAL'

    def _every_station(self):
        found = list(self.web_stations.values()) + list(self.stations.values())
        if not found and self.default_station is not None:
            found = [self.default_station]
        return found

    def web_candidates(self):
        """Where a reading could be put, and what is already there.

        One call for the whole page rather than one per row: the answer is the same
        for every row and it is a few kilobytes.
        """
        try:
            groups, ungrouped = columns.by_group()
        except Exception as e:
            return {'ok': False, 'error': "Cannot read the schema: %s" % e}
        present = self.columns_present()

        # What each station is already writing, so that the box can say so rather
        # than letting two stations quietly land in one column.
        used = {}
        for row in self.activity.snapshot():
            who = row['name'] or row['ident']
            for raw in row.get('raw_seen', ()):
                field = row['fields'].get(raw)
                if field:
                    used.setdefault(field, []).append(who)

        occupied = self.occupied or {}
        return {
            'ok': True,
            'groups': groups,
            'ungrouped': ungrouped,
            'present': sorted(present),
            'can_add': bool(self.config_path),
            'used': {field: sorted(set(who)) for field, who in used.items()},
            'history': {field: count for field, (count, _last) in occupied.items()},
        }

    def _station_for_ident(self, ident):
        """The station one identity belongs to.

        Args:
            ident (str): A station identity.

        Returns:
            Station: Whichever file names it, or the default station when neither
            does.
        """
        return (self.stations.get(ident) or self.web_stations.get(ident)
                or self.default_station)

    # ---- one main station ----------------------------------------------------
    #
    # Exactly one station is the main one. That is not a preference: two of them
    # write the same columns, every few seconds, and afterwards nothing can separate
    # the mixture. So every way a station comes into being goes through here, rather
    # than each one deciding for itself and the count coming out at two.

    def _mains(self):
        """Every station set up as the main one, as {identity: station}.

        Both files, and the station an installation with neither has. That last one
        is the console this driver adopted the first time it heard one: it is named
        nowhere, it is the main station by default, and leaving it out here would let
        the interface hand out a second main to sit beside it.
        """
        everyone = dict(self.stations)
        everyone.update(self.web_stations)
        found = {ident: station for ident, station in everyone.items()
                 if station.role == roles.MAIN}
        adopted = self._adopted_ident()
        if adopted is not None:
            found[adopted] = self.default_station
        return found

    def _adopted_ident(self):
        """A console this driver answers to that neither file names, if there is one.

        It is read as the default station, which is the main one. Nobody chose that,
        which is exactly why it has to be counted.
        """
        if self.default_station is None:
            return None
        for ident in sorted(self.known):
            if ident not in self.stations and ident not in self.web_stations:
                return ident
        return None

    def _main_ident(self):
        """Which station is the main one, by identity.

        The identity survives _reload, which builds every station object again. That
        makes it the thing to compare when asking whether a change moved the main
        station somewhere else.
        """
        for ident, station in self.stations.items():
            if station.role == roles.MAIN:
                return ident
        for ident, station in self.web_stations.items():
            if station.role == roles.MAIN:
                return ident
        return self._adopted_ident()

    def the_main_station(self):
        """The one station whose readings go where they belong.

        Everything the interface writes keeps the count at one. A configuration
        written by hand can still hold two, and then one of them has to be it. The
        pick is the order the stations are declared in: weewx.conf before the
        settings file, and within each, the order somebody wrote them. The first
        station in the file is the station, which is what anybody reading that file
        would assume, and it does not move about between restarts the way a pick
        based on who uploaded first would.
        """
        for station in self.stations.values():
            if station.role == roles.MAIN:
                return station
        for station in self.web_stations.values():
            if station.role == roles.MAIN:
                return station
        return self.default_station

    def _declared_main(self, besides=None):
        """The name of a main station weewx.conf declares, if there is one.

        Args:
            besides (str): An identity to leave out of the answer.

        Returns:
            str: The name of a main station weewx.conf declares, or None.
        """
        for ident, station in self.stations.items():
            if ident != besides and station.role == roles.MAIN:
                return station.name or ident
        return None

    def _role_for_new(self, ident, role, channel, force, protocol_name=''):
        """What role a station is about to get, and what that costs.

        Returns (ok, role, channel, message). Two things are refused unless `force`
        says somebody has been told and agreed, because both of them reach into the
        archive rather than only into the settings file:

        Taking the main station away from another station. From then on the readings
        of the one that was main land in different columns, and outTemp holds one
        sensor before that moment and another after it.

        Writing into a column that already holds readings. Those came from somewhere
        else, and carrying on in them is right when it is the same weather station in
        the same place and ruins the series when it is not. Only somebody who knows
        which of the two it is can answer that.

        Args:
            ident (str): The station this is for, or None for one being made.
            role (str): The role asked for, or None to take the default.
            channel (int): The channel asked for, or None to be given one.
            force (bool): Whether somebody has been told what it costs and agreed.
            protocol_name (str): Which protocol the station speaks, for working
                out which columns it would fill.

        Returns:
            tuple: (ok, role, channel, message). The message is the reason when
            ok is False, and is fit to show somebody.
        """
        if role is None:
            # Nothing asked for. The first station is the station; every one after
            # that is an extra sensor, because the alternative is two stations
            # writing one column and that is never what somebody meant.
            role = roles.EXTRA if self._mains() else roles.MAIN
        if role not in roles.ROLES:
            return False, None, None, "A role is one of %s." % ', '.join(roles.ROLES)

        ok, role, channel, message = self._role_and_channel(ident, role, channel,
                                                            force)
        if not ok:
            return False, None, None, message
        if force:
            return True, role, channel, None
        if not protocol_name:
            protocol_name = self.overrides.station(ident).get('protocol', '')
        blocked = self._columns_with_history(protocol_name, role, channel, ident,
                                             self.history() or {})
        if blocked:
            # Somewhere to put this is not the driver's to choose. Carrying on in a
            # column that already holds readings is right when it is the same weather
            # station in the same place, and ruins the series when it is not.
            first = blocked[0]
            return False, None, None, (
                "%s already holds %d reading(s), the last on %s%s. A station writing "
                "into it carries that series on, which is right if this is the same "
                "weather station in the same place and mixes two sensors into one "
                "column if it is not."
                % (first['field'], first['count'], first['last'],
                   ' (and %d other column(s))' % (len(blocked) - 1)
                   if len(blocked) > 1 else ''))
        return True, role, channel, None

    def _role_and_channel(self, ident, role, channel, force):
        """Which role and channel this station is asking for, and whether it may.

        Args:
            ident (str): The station this is for.
            role (str): MAIN or EXTRA.
            channel (int): The channel asked for, or None to be given one.
            force (bool): Whether taking the main station from another is agreed.

        Returns:
            tuple: (ok, role, channel, message).
        """
        if role == roles.MAIN:
            declared = self._declared_main(besides=ident)
            if declared is not None:
                return False, None, None, (
                    "weewx.conf declares '%s' as the main station, so the main "
                    "station is set there rather than here." % declared)
            mains = self._mains()
            others = [i for i in mains if i != ident]
            if others and not force:
                # Whichever it is, including the console this driver adopted, which
                # is named in neither file and is the main station all the same.
                station = mains[others[0]]
                return False, None, None, (
                    "'%s' is the main station. Making this one the main station "
                    "moves that one aside, and its readings go to different columns "
                    "from then on." % (station.name or others[0]))
            return True, roles.MAIN, None, None

        if channel is None:
            channel = self._free_channel(exclude=ident)
            if channel is None:
                return False, None, None, (
                    "Every extra channel is taken. The standard schema has eight.")
        else:
            ok, channel, message = self._wanted_channel(ident, channel)
            if not ok:
                return False, None, None, message
        return True, roles.EXTRA, channel, None

    def _wanted_channel(self, ident, channel):
        """Whether a channel somebody picked is free. Returns (ok, channel, why).

        Args:
            ident (str): The station asking, which may already be on it.
            channel (int): The channel it wants.

        Returns:
            tuple: (ok, channel, why), where `why` is the reason it cannot have
            it.
        """
        try:
            channel = int(channel)
        except (TypeError, ValueError):
            return False, None, "A channel is a number from 1 to %d." % roles.CHANNELS
        if not 1 <= channel <= roles.CHANNELS:
            return False, None, ("A channel is a number from 1 to %d. The standard "
                                 "schema has that many extraTemp columns."
                                 % roles.CHANNELS)
        everyone = dict(self.stations)
        everyone.update(self.web_stations)
        for other, station in everyone.items():
            if (other != ident and station.role == roles.EXTRA
                    and station.channel == channel):
                return False, None, ("Channel %d is taken by '%s'."
                                     % (channel, station.name or other))
        return True, channel, None

    def _stand_down_main(self, becoming, force):
        """Move whoever is main aside, so that `becoming` can be it.

        Only ever reached once `_role_for_new` has agreed to it, which is where the
        refusing is done. Returns (ok, message).

        Args:
            becoming (str): The station that is to be the main one.
            force (bool): Whether this was agreed to. Only ever reached once
                _role_for_new has said yes, which is where the refusing is done.

        Returns:
            tuple: (ok, message).
        """
        for ident in list(self._mains()):
            if ident == becoming:
                continue
            if ident in self.stations:
                # weewx.conf declares it. _role_for_new has already refused this.
                continue
            channel = self._free_channel(exclude=ident)
            if channel is None:
                return False, ("There is no free extra channel to move the station "
                               "that is main into. The standard schema has eight.")
            was = self.web_stations.get(ident)
            ok, message = self.overrides.set_station(ident, role=roles.EXTRA,
                                                     channel=channel)
            if not ok:
                return False, message
            # An adopted console has no entry anywhere until now. Writing one is what
            # gives it a role at all, and from here it is a station like any other.
            log.info("Station '%s' is no longer the main one. Its readings go to "
                     "channel %d from the next upload.",
                     (was.name if was else None) or ident, channel)
        return True, None

    def _roles_moved(self):
        """Take up a change to the stations.

        The register is read back from the file rather than kept across the change,
        because whoever changed something may have taken columns away from a station
        in doing it.
        """
        self.reload_wanted = True
        self._reload()
        self.said_apart = set()

    def web_create(self, protocol_name, name, role=None, channel=None, force=False):
        """Set a station up before it has ever uploaded.

        For hardware whose upload path is yours to choose. A path is made here, the
        interface shows it, you type it into the console, and from the first upload
        the driver knows which station that is without anyone having adopted
        anything. The path is the identity and the secret at once, which is better
        than a PASSKEY: that is readable off any upload and can be repeated by
        anybody.

        Hardware that cannot be given a path is not set up this way. It broadcasts,
        or its path is burned into its firmware, and the only way to know it is to
        hear it and confirm. Those are adopted, and web_accept is that.

        With no role asked for, the first station is the station and every one after
        it is an extra sensor. Asking for main when another station already is one is
        refused unless `force`, because it moves that station's readings into other
        columns from then on.

        Args:
            protocol_name (str): Which protocol the console speaks. Only hardware
                whose path is yours to choose can be set up this way.
            name (str): What to call the station.
            role (str): MAIN or EXTRA, or None to take the default.
            channel (int): The channel for an extra sensor, or None.
            force (bool): Whether somebody has been told what it costs and agreed.

        Returns:
            tuple: (ok, answer). On success `answer` holds the new station and the
            settings to put into the console; on failure it is the reason.
        """
        import secrets

        protocol = protocols.by_name(protocol_name)
        if protocol is None:
            return False, "No protocol called '%s'." % protocol_name
        if protocol.secret_kind != 'path':
            return False, ("%s hardware cannot be told which path to use, so there "
                           "is nothing to set up in advance. Point it here and it "
                           "will turn up as something waiting to be let in."
                           % protocol.label)
        clean = overrides._as_name(name)
        if not clean:
            return False, ("A name may hold letters, digits, dashes and underscores.")
        if any(s.name == clean for s in self.web_stations.values()):
            return False, "There is already a station called '%s'." % clean

        path = '/%s/report' % secrets.token_urlsafe(9)
        # The identity is the path until the console says otherwise. The first upload
        # brings a PASSKEY with it and the station is recorded under that instead,
        # because that is what every later upload carries.
        ident = 'path:' + path

        ok, role, channel, message = self._role_for_new(ident, role, channel, force,
                                                        protocol_name)
        if not ok:
            return False, message
        if role == roles.MAIN:
            ok, message = self._stand_down_main(ident, force)
            if not ok:
                return False, message

        ok, message = self.overrides.set_station(
            ident, name=clean, path=path, protocol=protocol_name,
            role=role, channel=channel)
        if not ok:
            return False, message
        self.known.add(ident)
        self._roles_moved()
        log.info("Station '%s' was set up for %s, as %s. Its upload path is %s.",
                 clean, protocol.label,
                 'the main station' if role == roles.MAIN
                 else 'an extra sensor on channel %d' % channel, path)
        return True, {'name': clean, 'protocol': protocol_name, 'path': path,
                      'role': role, 'channel': channel,
                      'address': self.web_address(), 'port': self.data_port(),
                      'settings': checklist._pointing(protocol, self.web_address(),
                                                      self.data_port(), path)}

    def web_accept(self, ident, name=None, infer_unknown=None):
        """Let a station in, and give it a name.

        A station let in while another is already the main one is an extra sensor.
        Anything else would be two consoles writing one column, which is what the
        driver refused this upload for in the first place. Where the eight extra
        channels are all taken it is still let in, and says that nothing of it will
        be recorded until a channel is free: refusing to let it in would be worse,
        because then nothing would explain why.

        Args:
            ident (str): Whatever the console sends to name itself.
            name (str): What to call it.
            infer_unknown (str): This station's own inference setting.

        Returns:
            tuple: (ok, message).
        """
        ident = str(ident or '').strip()
        if not ident:
            return False, "A station with no identity cannot be told from another."
        if ident in self.stations:
            return False, "weewx.conf already names this one. Change it there."

        role, channel, note = roles.MAIN, None, ''
        if [other for other in self._mains() if other != ident]:
            role = roles.EXTRA
            channel = self._free_channel(exclude=ident)
            if channel is None:
                note = (" Every extra channel is taken, so nothing from it is "
                        "recorded until one is free.")
            else:
                note = " It is an extra sensor on channel %d." % channel

        ok, message = self.overrides.set_station(ident, name, infer_unknown,
                                                 role=role, channel=channel)
        if not ok:
            return False, message
        self.known.add(ident)
        self.store.add(ident, "let in through the web interface")
        self._roles_moved()
        log.info("Station '%s' was let in through the web interface.%s", ident, note)
        return True, "Recorded in %s.%s" % (message, note)

    def web_set_field(self, ident, raw, field, force=False):
        """Place one raw field for one station.

        A WeeWX field takes one answer. If another station, or another reading of
        this one, already fills it, this says so and changes nothing: two sensors in
        one column take turns every few seconds and cannot be told apart afterwards.
        `force` is somebody having read that and said yes, and then the reading that
        held the field is placed nowhere instead of being left to fight over it.

        Args:
            ident (str): The station this placement is for.
            raw (str): The raw field name, as the console sends it.
            field (str): The WeeWX field to write it to. Empty removes the
                placement; mapping.NOWHERE records that it goes nowhere on
                purpose.
            force (bool): Whether taking the column from its holder is agreed.

        Returns:
            dict: Whether it worked, and either a message or, for a conflict, who
            holds the column.
        """
        ident = str(ident or '').strip()
        raw = str(raw or '').strip()
        field = str(field or '').strip()
        if ident in self.stations:
            return {'ok': False, 'message': (
                "weewx.conf names this station under [[stations]], so its field map "
                "is part of that declaration and lives there. Change it there, or "
                "take the station out of [[stations]] first.")}

        wanted = field and field != mapping.NOWHERE
        held = self._holders().get(field) if wanted else None
        if held and (held['ident'], held['raw']) != (ident, raw):
            if not force:
                return {'ok': False, 'conflict': True, 'holder': held, 'message': (
                    "%s is already filled by '%s' from station %s. One column takes "
                    "one reading: two of them take turns every few seconds, and "
                    "afterwards nothing can tell them apart."
                    % (field, held['raw'], held['name']))}
            if held['ident'] in self.stations:
                return {'ok': False, 'message': (
                    "%s is filled by '%s' from station %s, which weewx.conf declares "
                    "under [[stations]]. Change it there first."
                    % (field, held['raw'], held['name']))}
            if held['raw']:
                ok, message = self.overrides.set_field(held['ident'], held['raw'],
                                                       mapping.NOWHERE)
                if not ok:
                    return {'ok': False, 'message': message}
            # And the column itself, or this station would go on being turned away
            # from the field somebody has just given it.
            self.overrides.set_column(field, ident)

        ok, message = self.overrides.set_field(ident, raw, field)
        if not ok:
            return {'ok': False, 'message': message}
        self.reload_wanted = True
        self._reload()
        return {'ok': True, 'message': message}

    def web_role(self, ident, role, force=False):
        """Say whether a station is the station, or an extra sensor.

        Args:
            ident (str): The station's identity.
            role (str): MAIN or EXTRA.
            force (bool): Whether taking the main station from another is agreed.

        Returns:
            tuple: (ok, message).
        """
        return self.web_edit(ident, role=role, force=force)

    def web_edit(self, ident, name=None, role=None, channel=None, force=False):
        """Change a station the interface set up: its name, its role, its channel.

        Exactly one station is the main one. Making this one it moves the one that
        was aside, onto a channel of its own, and from that moment its readings are
        in different columns than they were: the archive holds one sensor's outTemp
        before and another's after. That cannot be undone by clicking back, so it is
        refused unless `force` says somebody has been told and agreed.

        A station weewx.conf names is not edited here. That file is its declaration,
        and one owner per setting is the rule the whole settings file rests on.

        Args:
            ident (str): The station's identity.
            name (str): A new name, or None to leave it.
            role (str): MAIN or EXTRA, or None to leave it.
            channel (int): A channel, or None to leave it.
            force (bool): Whether somebody has been told what it costs and agreed.

        Returns:
            tuple: (ok, message).
        """
        ident = str(ident or '').strip()
        if not ident:
            return False, "A station with no identity cannot be told from another."
        if ident in self.stations:
            return False, ("weewx.conf names this station, so its settings live "
                           "there.")
        if ident not in self.web_stations:
            return False, "No station here has that identity."

        was = self.web_stations[ident]
        clean = None
        if name is not None:
            clean = overrides._as_name(name)
            if not clean:
                return False, ("A name may hold letters, digits, dashes and "
                               "underscores.")
            for other, station in self.web_stations.items():
                if other != ident and station.name == clean:
                    return False, "There is already a station called '%s'." % clean

        if role is None and channel is not None:
            # A channel is only a thing an extra sensor has. Somebody moving one is
            # not also asking to change what it is.
            role = was.role
        if role is not None:
            ok, role, channel, message = self._role_for_new(ident, role, channel,
                                                            force)
            if not ok:
                return False, message
            if role == roles.MAIN:
                ok, message = self._stand_down_main(ident, force)
                if not ok:
                    return False, message

        moved = role is not None and (role != was.role or channel != was.channel)
        ok, message = self.overrides.set_station(ident, name=clean, role=role,
                                                 channel=channel)
        if not ok:
            return False, message
        if moved:
            # It writes different columns from here on: an extra sensor on another
            # channel, or a main station that no longer has its readings shifted. The
            # ones it held say nothing about that, so it gives them up and takes what
            # it fills from its next upload.
            gone = self.owners.owns(ident)
            if gone:
                self.overrides.drop_columns(gone)
                log.info("Station '%s' gave up %d column(s) with its role: %s.",
                         clean or was.name or ident, len(gone), ', '.join(gone))
        self._roles_moved()
        if role is not None:
            log.info("Station '%s' is now %s.", clean or was.name or ident,
                     'the main station' if role == roles.MAIN
                     else 'an extra sensor on channel %s' % channel)
        return True, message

    def _free_channel(self, exclude=None):
        """The channel to hand out next, or None if there is none.

        A channel another station is on is taken. So, as far as this can help it, is
        one whose columns already hold readings: they came from somewhere else, and a
        new sensor writing into them makes one column out of two sensors, which is
        the failure this driver exists to refuse. Where every free channel has
        history, one of them has to be used anyway, and then it is somebody's
        decision rather than this function's.

        Args:
            exclude (str): A station whose own channel does not count as taken,
                which is the station being given one.

        Returns:
            int: The channel to hand out, or None when there is none.
        """
        taken = set()
        for ident, station in self.web_stations.items():
            if ident != exclude and station.role == roles.EXTRA and station.channel:
                taken.add(station.channel)
        used = self.history() or {}
        clean = set(taken)
        for channel in range(1, roles.CHANNELS + 1):
            if any(field in used for field in roles.columns_for(channel)):
                clean.add(channel)
        return roles.next_channel(clean) or roles.next_channel(taken)

    def web_release(self, ident, field=''):
        """Give up a column this station holds, so another may fill it.

        For a sensor that was taken down. Its column is held until somebody says
        otherwise, which is right while a console is merely offline for a week and
        wrong once it is gone for good.

        Args:
            ident (str): The station's identity.
            field (str): One column to release, or empty for all of them.

        Returns:
            tuple: (ok, message).
        """
        ident = str(ident or '').strip()
        field = str(field or '').strip()
        held = self.owners.owns(ident)
        if field:
            if field not in held:
                return False, "'%s' does not fill %s." % (self._name_of(ident), field)
            held = [field]
        if not held:
            return False, "That station fills no columns."
        ok, message = self.overrides.drop_columns(held)
        if not ok:
            return False, message
        self._roles_moved()
        log.info("Station '%s' gave up %d column(s): %s. The next station to fill "
                 "one of them has it.", self._name_of(ident), len(held),
                 ', '.join(held))
        return True, ("Given up: %s. The next station to fill one of them has it."
                      % ', '.join(held))

    def web_forget(self, ident):
        """Take a station out again.

        The upload path goes with it, so the console that was told to use it starts
        being turned away rather than quietly recorded as somebody else. That is the
        honest outcome: a station nobody set up is a station this driver does not
        answer to.

        Args:
            ident (str): The station's identity.

        Returns:
            tuple: (ok, message).
        """
        ident = str(ident or '').strip()
        if ident in self.stations:
            return False, ("weewx.conf names this station. Take it out of there and "
                           "restart WeeWX.")
        ok, message = self.overrides.forget_station(ident)
        if not ok:
            return False, message
        # Out of the list of consoles this driver answers to as well, or it would go
        # on being let in under the default station until the next restart. Not out
        # of the console file: that is the record of what has ever been heard here,
        # and a station set up in the interface was never written to it.
        if ident not in self.store.read():
            self.known.discard(ident)
        gone = self.owners.owns(ident)
        if gone:
            self.overrides.drop_columns(gone)
        self._roles_moved()
        log.info("Station '%s' was taken out through the web interface.", ident)
        return True, message

    def web_columns(self, ident, refresh=False):
        """Which columns this station needs, and what is in them already.

        The history check is one pass over the archive table, so it happens when
        somebody asks rather than on every page load.

        Args:
            ident (str): The station's identity.
            refresh (bool): Read the archive table again rather than using what is
                kept.

        Returns:
            dict: Which readings have no column, the commands that would add them,
            and which columns already hold data.
        """
        found = self.activity.one(ident)
        if found is None:
            return {'ok': False, 'error': "No station by that name."}
        recent = self.activity.recent(ident, transport.redact, limit=1)
        packet = (recent[0].get('packet') or {}) if recent else {}
        station = self._station_for_ident(ident)
        groups = {}
        for mapper in (station.mappers.values() if station else []):
            groups.update(mapper.wanted_groups())

        try:
            wanted = columns.missing(packet, groups, known=self.columns_present())
        except Exception as e:
            return {'ok': False, 'error': "Cannot work out the columns: %s" % e}

        used = self.history(refresh=refresh)

        return {
            'ok': True,
            'missing': [{'field': f, 'type': t} for f, t in wanted],
            'commands': columns.commands(wanted, self.config_path or 'weewx.conf'),
            'occupied_checked': used is not None,
            'occupied': [] if not used else sorted(
                ({'field': f, 'count': c,
                  'last': (time.strftime('%Y-%m-%d', time.localtime(seen))
                           if seen else '?')}
                 for f, (c, seen) in used.items() if f in packet),
                key=lambda r: r['field']),
        }

    def _station_for(self, protocol, raw, client):
        """Which console this upload belongs to, or None to leave it alone.

        Args:
            protocol: The protocol that claimed the upload.
            raw (dict): The raw name/value pairs.
            client (str): The address it came from.

        Returns:
            Station: Which console this belongs to, or None to leave it alone.
        """
        ident = protocol.station_of(raw)

        if not self.known:
            self._adopt(ident, client, protocol)

        if ident not in self.known:
            self._refuse(ident, client, protocol)
            return None

        # weewx.conf first, then what the web interface recorded, then the one
        # station an installation with neither has. That order is the whole of the
        # rule that a file somebody edited outranks a button somebody pressed.
        if ident in self.stations:
            return self.stations[ident]
        if ident in self.web_stations:
            return self.web_stations[ident]
        return self.default_station

    def _secret_ok(self, protocol, raw, client):
        """Whether an upload presents the password the driver was configured with.

        Only Weather Underground has one to present. It is the one protocol here
        where the hardware can authenticate itself, so when a password is configured
        it is checked, and when it is not, nothing changes.

        Args:
            protocol: The protocol that claimed the upload.
            raw (dict): The raw name/value pairs.
            client (str): The address it came from.

        Returns:
            bool: Whether the upload may be kept.
        """
        from .protocols import wunderground
        if wunderground.password_ok(raw, self.password):
            return True
        log.warning("An upload from %s carries the wrong %s. Ignoring it.",
                    client, protocol.secret)
        return False

    def _assumed(self):
        """What to read an upload with when nothing in it says.

        Only ever the one protocol the configuration named. Some hardware sends
        readings with nothing that identifies the protocol or the station, and some
        proxies strip what there was; with a single protocol configured there is
        nothing left to get wrong, and the reading is worth keeping.

        With several configured there is. The same name means different things in
        different catalogs, and putting a reading through the wrong one is the
        failure this driver exists to avoid. So it is refused, and the log says that
        naming one protocol is what fixes it.
        """
        if len(self.enabled) != 1:
            return None
        protocol = self.enabled[0]
        if not self.assumed:
            self.assumed = True
            log.info("An upload from this station says neither which protocol it is "
                     "nor which console sent it. Reading it as %s, which is the only "
                     "one this driver is configured for.", protocol.label)
        return protocol

    def _unclaimed(self, request):
        """Say once that something arrived that no protocol recognised.

        Args:
            request: The upload nothing recognised.
        """
        self.unclaimed += 1
        if self.unclaimed > 1:
            return
        log.warning(
            "A request from %s to %s matched none of the protocols this driver is "
            "listening for (%s). Nothing in it says which protocol it is, so reading "
            "it would mean guessing which catalog its field names belong to. If you "
            "know, set 'protocols = <one of them>' and it will be read as that. Turn "
            "on 'log_raw = true' to see what arrived.",
            request.client_address, request.path or '/',
            ', '.join(p.name for p in self.enabled))

    def _adopt(self, ident, client, protocol):
        """Record the first console ever heard, and answer to it from then on.

        Args:
            ident (str): Whatever named the station.
            client (str): The address it came from.
            protocol: The protocol that claimed it.
        """
        self.known.add(ident)
        where = self.store.add(ident, "first console seen, from %s, speaking %s"
                                      % (client, protocol.name))
        log.info("Console '%s' at %s, speaking %s, is now this driver's station, on "
                 "record in the %s. Uploads from any other console are refused until "
                 "it is named under [[stations]].",
                 ident, client, protocol.name, where or 'log only')
        self._suggest_passkey(ident, protocol)

    def _suggest_passkey(self, ident, protocol):
        """Point at the setting that does not depend on a file surviving.

        The file is a convenience. A copied database, a rebuilt machine or a
        directory nobody backed up leaves it behind, and then the next console to
        upload becomes the station. One line in weewx.conf does not have that
        problem, so say so where somebody will see it.

        Args:
            ident (str): The identity just adopted.
            protocol: The protocol that claimed it.
        """
        if self.configured_passkey or self.stations:
            return
        log.info("To keep it independent of anything stored, put it in weewx.conf: "
                 "'passkey = %s' under [%s].", ident, DRIVER_NAME)

    def _refuse(self, ident, client, protocol):
        """Say once that an upload was turned away, and what would let it in.

        Args:
            ident (str): Whatever named the station.
            client (str): The address it came from.
            protocol: The protocol that claimed it.
        """
        if (ident, protocol.name) in self.unknown_consoles:
            return
        self.unknown_consoles.add((ident, protocol.name))
        log.warning(
            "A %s upload from %s names station '%s', which is not one of this "
            "driver's consoles. Ignoring it. If it is yours, add it under "
            "[[stations]] with its own field map: two consoles number their channels "
            "from one, and would otherwise write into the same fields.",
            protocol.name, client, ident or '(unnamed)')

    def _maybe_report(self, payload, guesses, protocol):
        """Write out one upload, the first time something cannot be placed.

        Getting hold of a raw upload otherwise means reconfiguring the console and
        waiting for an interval. The driver has it in hand, so it writes it once and
        says where the file is.

        Args:
            payload (str): The upload as it arrived.
            guesses (dict): What the mapper worked out for itself.
            protocol: The protocol that claimed it.
        """
        if self.reported or not self.report_file:
            return
        waiting = {}
        for mapper in self._mappers():
            waiting.update({raw: field for raw, field in mapper.undecided.items()
                            if raw in mapper.warned})
        if not guesses and not waiting:
            return
        self.reported = True
        path = report.write(payload, guesses, waiting, self.report_file,
                            protocol=protocol.name)
        if path:
            log.info("This station sends fields I cannot place on my own. Everything "
                     "needed to report them is in %s", path)

    def _mappers(self):
        stations = ([self.default_station] if self.default_station is not None
                    else list(self.stations.values()))
        return [mapper for station in stations
                for mapper in station.mappers.values()]

    def closePort(self):
        self.listener.close()

    @staticmethod
    def _register_units(groups):
        """Tell WeeWX what these fields are, so reports can format them.

        Only fields WeeWX does not already know about are touched. Overriding a group
        it ships with would change the meaning of a field for every other driver.

        Args:
            groups (dict): WeeWX field to unit group, for fields WeeWX does not
                already know.
        """
        for field, group in groups.items():
            weewx.units.obs_group_dict.setdefault(field, group)


def _contested_with(station):
    """Who disagrees about a placement, for the sentence that asks.

    Args:
        station (Station): The station whose catalog is in question.

    Returns:
        str: The name of the driver this one disagrees with about where a
        field belongs.
    """
    for mapper in (station.mappers.values() if station else []):
        if mapper.dialect.contested_with:
            return mapper.dialect.contested_with
    return 'another driver'


def _station_section(config_dict):
    """The [Station] section as plain values, or None when there is no config.

    Args:
        config_dict (dict): The whole of weewx.conf.

    Returns:
        dict: The [Station] section, or an empty dict.
    """
    if not config_dict:
        return None
    try:
        return {key: config_dict['Station'][key]
                for key in ('location', 'latitude', 'longitude', 'altitude')
                if key in config_dict['Station']}
    except (KeyError, TypeError):
        return {}


def _config_path(config_dict):
    """Where weewx.conf is, for the add-column commands and the history check.

    Args:
        config_dict (dict): The whole of weewx.conf, as WeeWX passed it.

    Returns:
        str: The path to weewx.conf, or None when it cannot be worked out.
    """
    if not config_dict:
        return None
    return getattr(config_dict, 'filename', None) or config_dict.get('config_path')


class UltimatePushConfEditor(weewx.drivers.AbstractConfEditor):

    @property
    def default_stanza(self):
        return """
[UltimatePush]
    # This section is for weather hardware that uploads to a custom server.

    # The port to listen on. Ports below 1024 need root.
    port = 8000

    # Accept this path only. Most hardware cannot send a token any other way, so a
    # path nobody can guess is the practical way to keep strangers out. Leave it out
    # if you have Weather Underground hardware: it cannot be told to use any path
    # but its own.
    # path = /change-me/report

    # Which protocols to listen for. 'auto' is all of them, and costs nothing,
    # because an upload is recognised by what is in it rather than by which port it
    # came to.
    protocols = auto

    # What to do with a field the driver does not know yet:
    #   off     drop it
    #   series  keep it when it continues a known series, report the rest
    #   all     keep whatever can be named, including from naming rules
    infer_unknown = series

    # Where to leave a report when a station sends something the driver cannot
    # place. Set it empty to switch that off.
    report_file = /var/tmp/weewx-ultimate-push-report.txt

    # A few fields are placed differently by different drivers, and the wrong choice
    # mixes two sensors into one column. Those are not written until you name them
    # below. The log prints both candidate lines the first time each one arrives.

    # Your own mapping, which wins over the built-in one, and over anything the
    # web interface sets.
    [[field_map_extensions]]

    # A small web interface, on a port of its own. Off unless switched on, and it
    # will not start without a token of at least 10 characters. Make one with:
    #   python -c "import secrets; print(secrets.token_urlsafe(12))"
    #
    # An address that gets the token wrong 'tries' times within 'window' seconds
    # stops being answered at all until those tries fall out of the window.
    #
    # It is plain HTTP, so the token travels in clear. On a network you do not
    # trust, set address = localhost and reach it through an SSH tunnel, or put a
    # reverse proxy with TLS in front of it.
    [[web]]
        enable = false
        port = 8080
        # address = localhost
        # token =
        # allowed_hosts =
        # tries = 10
        # window = 300

    # The driver to use:
    driver = user.ultimatepush.driver
"""

    def prompt_for_settings(self):
        settings = {}
        settings['port'] = self._prompt("port", '8000')
        return settings
