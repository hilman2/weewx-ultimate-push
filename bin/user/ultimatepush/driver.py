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
               mapping, overrides, protocols, report, roles, server, transport)
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
        self.owned_by_main = set()
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
        """Hand a protocol the one or two settings only the user can decide."""
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
        for station in self.web_stations.values():
            for mapper in station.mappers.values():
                self._register_units(mapper.wanted_groups())
        log.info("Took up the settings from %s.", self.overrides.path)

    def _read_stations(self, configured):
        """Return {identity: Station} for an installation with several consoles."""
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

        Everything is accepted until a station has actually been heard on its own
        path. A path that has never worked is not yet protecting anything, and
        turning it into a 404 before that would break the console somebody is still
        in the middle of configuring.
        """
        path = (path or '/').rstrip('/')
        if path in self.station_paths:
            return True
        for protocol in self.enabled:
            if path in [p.rstrip('/') for p in protocol.paths]:
                return True
        if self.listener_path:
            return path == self.listener_path.rstrip('/')
        return not self.paths_proven

    def _web_listener(self, configured):
        """The web interface, when it has been switched on and given a token.

        On a port of its own, because the token has to be checked at the listener and
        checking it on the data port would lock out hardware that cannot send one.

        Off unless asked for, and refused without a token, because the alternative is
        an interface that can change the field map sitting open on the network for
        anybody who guesses the port.
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
        """Turn one upload into a loop packet, or None if it is not ours to keep."""
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
        if station.role == roles.MAIN:
            # What the main station fills is what an extra one must keep out of.
            self.owned_by_main.update(f for f in packet
                                      if f not in ('dateTime', 'usUnits', 'station'))
        return packet

    def _has_a_main_station(self):
        """Whether any station is set up as the main one.

        If none is, there is nothing for an extra one to stay out of and holding it
        back would hold it back for ever.
        """
        everyone = list(self.stations.values()) + list(self.web_stations.values())
        return any(s.role == roles.MAIN for s in everyone)

    def _keep_stations_apart(self, station, packet):
        """Stop a station that is not the main one from writing over it.

        The role moves what can be moved. What cannot, a second station's wind or
        rain or pressure, has nowhere to go, and writing it would mean two sensors
        taking turns in one column every few seconds. Nothing afterwards can separate
        that, so it is dropped and said once.

        A field the user named by hand is left alone. Naming it is the decision.
        """
        if station.role == roles.MAIN:
            return
        if not self.owned_by_main:
            # Nothing is known about the main station's columns yet, because it has
            # not uploaded since this driver started. Writing now would put this
            # station's wind and pressure into the main station's columns for an
            # interval, and an interval of two sensors in one column is exactly what
            # none of this is allowed to produce.
            #
            # So it waits. One upload of an extra station is a cheap thing to lose;
            # the alternative is a stretch of readings nobody can separate afterwards,
            # once per restart, for ever.
            if self._has_a_main_station():
                packet.clear()
                if 'waiting' not in self.said_apart:
                    self.said_apart.add('waiting')
                    log.info("Holding back station '%s' until the main station has "
                             "been heard, so that its readings cannot land in the "
                             "main station's columns.",
                             station.name or station.ident)
            return
        wanted = set(station.extensions.values())
        dropped = sorted(set(packet) & self.owned_by_main - wanted)
        self.activity.kept_apart(station.ident or '', dropped)
        if not dropped:
            return
        for field in dropped:
            packet.pop(field, None)
        # One line for the lot. A second weather station has thirty readings with
        # nowhere to go, and thirty copies of the same sentence is not a log anybody
        # reads. Said once per station per run: after that it is not news.
        who = station.name or station.ident
        if who in self.said_apart:
            return
        self.said_apart.add(who)
        log.warning(
            "%d reading(s) from station '%s' are not being written, because the main "
            "station already fills those columns and two sensors in one column "
            "cannot be separated afterwards: %s. Give them fields of their own under "
            "[[field_map_extensions]], or make this the main station.",
            len(dropped), who, ', '.join(dropped))

    # ---- what the web interface reads ---------------------------------------

    def _record(self, request, protocol, dialect, raw, packet, station, mapper):
        """Keep the upload, so that a question about it can be answered later.

        Bounded and in memory only. See activity.py.
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
                and not self.owned_by_main and self._has_a_main_station())
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
            'waiting': self.activity.unknown_stations(transport.redact),
        }

    def web_station(self, ident):
        """One station, every raw field it has sent, and where each one stands.

        This is the page the whole interface exists for. A row says what arrived,
        where it goes, whether there is a column for it, and whether that column
        already holds somebody else's readings. The last of those is the one thing a
        log line cannot tell you and the one thing that makes the decision
        irreversible if it is wrong.
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

    def columns_present(self, refresh=False):
        """The columns the archive table has, or the schema when it cannot be read.

        Read once and kept, because it changes only when somebody adds one, and this
        is asked on every page load.
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

        A column takes one answer. Two stations writing one column take turns every
        few seconds, and afterwards nothing can tell the two apart, so the interface
        has to be able to say who has it before somebody picks it again.
        """
        holders = {}
        for row in self.activity.snapshot():
            ident = row['ident']
            placed = self._placements(self._station_for_ident(ident))
            for raw in row.get('raw_seen', ()):
                field = placed.get(raw, row['fields'].get(raw))
                if not field or field == mapping.NOWHERE:
                    continue
                holders.setdefault(field, {'ident': ident,
                                           'name': row.get('name') or ident,
                                           'raw': raw})
        return holders

    def web_add_column(self, field, sql_type=None):
        """Add one archive column, so that nobody has to leave for a terminal.

        The same ALTER TABLE that weectl database add-column runs. What it does not
        do, and neither does weectl, is give the column a daily summary: those tables
        are built from the declared schema when the database is made. Aggregates
        still work, computed from the archive table itself, which is slower and right.
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
        """REAL for anything measured, INTEGER for anything counted."""
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
        return (self.stations.get(ident) or self.web_stations.get(ident)
                or self.default_station)

    def web_create(self, protocol_name, name):
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
        ok, message = self.overrides.set_station(
            ident, name=clean, path=path, protocol=protocol_name)
        if not ok:
            return False, message
        self.known.add(ident)
        self.reload_wanted = True
        self._reload()
        log.info("Station '%s' was set up for %s. Its upload path is %s.",
                 clean, protocol.label, path)
        return True, {'name': clean, 'protocol': protocol_name, 'path': path,
                      'address': self.web_address(), 'port': self.data_port(),
                      'settings': checklist._pointing(protocol, self.web_address(),
                                                      self.data_port(), path)}

    def web_accept(self, ident, name=None, infer_unknown=None):
        """Let a station in, and give it a name."""
        ident = str(ident or '').strip()
        if not ident:
            return False, "A station with no identity cannot be told from another."
        if ident in self.stations:
            return False, "weewx.conf already names this one. Change it there."
        ok, message = self.overrides.set_station(ident, name, infer_unknown)
        if not ok:
            return False, message
        self.known.add(ident)
        self.store.add(ident, "let in through the web interface")
        self.reload_wanted = True
        log.info("Station '%s' was let in through the web interface.", ident)
        return True, "Recorded in %s." % message

    def web_set_field(self, ident, raw, field, force=False):
        """Place one raw field for one station.

        A WeeWX field takes one answer. If another station, or another reading of
        this one, already fills it, this says so and changes nothing: two sensors in
        one column take turns every few seconds and cannot be told apart afterwards.
        `force` is somebody having read that and said yes, and then the reading that
        held the field is placed nowhere instead of being left to fight over it.
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
            ok, message = self.overrides.set_field(held['ident'], held['raw'],
                                                   mapping.NOWHERE)
            if not ok:
                return {'ok': False, 'message': message}

        ok, message = self.overrides.set_field(ident, raw, field)
        if not ok:
            return {'ok': False, 'message': message}
        self.reload_wanted = True
        self._reload()
        return {'ok': True, 'message': message}

    def web_role(self, ident, role):
        """Say whether a station is the station, or an extra sensor.

        Exactly one is the main one. Making a second station main would leave two
        writing the same columns, which is the thing this is here to stop, so the
        one that was main becomes extra and is told which channel it got.
        """
        ident = str(ident or '').strip()
        if role not in roles.ROLES:
            return False, "A role is one of %s." % ', '.join(roles.ROLES)
        if ident in self.stations:
            return False, "weewx.conf names this station, so its role lives there."

        if role == roles.MAIN:
            for other, station in self.web_stations.items():
                if other != ident and station.role == roles.MAIN:
                    channel = self._free_channel(exclude=other)
                    if channel is None:
                        return False, ("There is no free extra channel to move the "
                                       "station that is main into. The schema has "
                                       "eight.")
                    ok, message = self.overrides.set_station(
                        other, role=roles.EXTRA, channel=channel)
                    if not ok:
                        return False, message
            ok, message = self.overrides.set_station(ident, role=roles.MAIN)
        else:
            channel = self._free_channel(exclude=ident)
            if channel is None:
                return False, ("Every extra channel is taken. The standard schema "
                               "has eight of them.")
            ok, message = self.overrides.set_station(ident, role=roles.EXTRA,
                                                     channel=channel)
        if not ok:
            return False, message
        self.reload_wanted = True
        self._reload()
        # What the main station owns is learned from what it sends, so it has to be
        # learned again once the roles have moved.
        self.owned_by_main = set()
        self.said_apart = set()
        return True, message

    def _free_channel(self, exclude=None):
        taken = set()
        for ident, station in self.web_stations.items():
            if ident != exclude and station.role == roles.EXTRA and station.channel:
                taken.add(station.channel)
        return roles.next_channel(taken)

    def web_forget(self, ident):
        ok, message = self.overrides.forget_station(ident)
        if ok:
            self.reload_wanted = True
        return ok, message

    def web_columns(self, ident, refresh=False):
        """Which columns this station needs, and what is in them already.

        The history check is one pass over the archive table, so it happens when
        somebody asks rather than on every page load.
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

        if refresh and self.config_path:
            try:
                self.occupied = columns.occupied(self.config_path)
            except Exception as e:
                log.warning("The web interface could not read the archive table: %s",
                            e)
                self.occupied = {}
        used = self.occupied

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
        """Which console this upload belongs to, or None to leave it alone."""
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
        """Say once that something arrived that no protocol recognised."""
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
        """Record the first console ever heard, and answer to it from then on."""
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
        """
        if self.configured_passkey or self.stations:
            return
        log.info("To keep it independent of anything stored, put it in weewx.conf: "
                 "'passkey = %s' under [%s].", ident, DRIVER_NAME)

    def _refuse(self, ident, client, protocol):
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
        """
        for field, group in groups.items():
            weewx.units.obs_group_dict.setdefault(field, group)


def _contested_with(station):
    """Who disagrees about a placement, for the sentence that asks."""
    for mapper in (station.mappers.values() if station else []):
        if mapper.dialect.contested_with:
            return mapper.dialect.contested_with
    return 'another driver'


def _station_section(config_dict):
    """The [Station] section as plain values, or None when there is no config."""
    if not config_dict:
        return None
    try:
        return {key: config_dict['Station'][key]
                for key in ('location', 'latitude', 'longitude', 'altitude')
                if key in config_dict['Station']}
    except (KeyError, TypeError):
        return {}


def _config_path(config_dict):
    """Where weewx.conf is, for the add-column commands and the history check."""
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
