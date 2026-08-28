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

from . import (VERSION, activity, admin, columns, consoles, overrides,
               protocols, report, server, transport)
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

# Options that belong to this driver and must not reach the listener, which would
# reject what it does not recognise.
NOT_FOR_LISTENER = frozenset([
    'driver', 'field_map_extensions', 'infer_unknown', 'model', 'report_file',
    'stations', 'passkey', 'password', 'console_file', 'weewx_root', 'sqlite_root',
    'data_binding', 'config_dict', 'protocols', 'metric_wind', 'max_behind',
    'max_ahead', 'udp_port', 'web',
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

    def __init__(self, name, ident, extensions, infer_unknown, max_behind, max_ahead):
        self.name = name
        self.ident = ident
        self.extensions = extensions
        self.infer_unknown = infer_unknown
        self.max_behind = max_behind
        self.max_ahead = max_ahead
        self.mappers = {}

    def mapper_for(self, dialect):
        """The mapper for this dialect, made the first time it is needed."""
        mapper = self.mappers.get(dialect.name)
        if mapper is None:
            mapper = Mapper(dialect, extensions=self.extensions,
                            infer_unknown=self.infer_unknown,
                            max_behind=self.max_behind, max_ahead=self.max_ahead)
            self.mappers[dialect.name] = mapper
            log.info("Reading %s uploads%s with the '%s' catalog, %d fields.",
                     dialect.name.split('/')[0],
                     " from '%s'" % self.name if self.name else '',
                     dialect.name, len(dialect.fields))
        return mapper


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
        self.config_path = _config_path(stn_dict.get('config_dict'))
        self.occupied = None

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

        self._check_rain_delta(stn_dict.get('config_dict'))

        self.report_file = stn_dict.get('report_file', report.DEFAULT_PATH)
        self.reported = False
        self.unknown_consoles = set()
        self.unclaimed = 0
        self.assumed = False

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
        for ident, options in self.overrides.stations().items():
            if ident in self.stations:
                # weewx.conf names it. Nothing here may change that.
                continue
            extensions = dict(self.conf_extensions)
            extensions.update(options.get('field_map_extensions', {}))
            built[ident] = Station(
                options.get('name') or None, ident, extensions,
                options.get('infer_unknown', self.infer_unknown),
                self.max_behind, self.max_ahead)
        self.web_stations = built
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
            stations[str(ident).strip()] = Station(
                name, str(ident).strip(),
                dict(options.get('field_map_extensions', {})),
                options.get('infer_unknown', self.infer_unknown),
                self.max_behind, self.max_ahead)
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
        if len(token) < 16:
            raise ValueError(
                "The web interface needs 'token' set to at least 16 characters. It "
                "is the only thing between the field map and whoever else is on the "
                "network. Make one with: "
                "python -c \"import secrets; print(secrets.token_urlsafe(24))\"")
        options = {
            'port': to_int(configured.get('port', 8080)),
            'address': configured.get('address', ''),
            'token': token,
            'allowed_hosts': configured.get('allowed_hosts'),
            'trust_proxy': configured.get('trust_proxy', False),
            'queue_size': 1,
        }
        site = admin.Site(self)
        listener = server.http_listener(HTTPListener, site.answer, queue=False,
                                        **options)
        where = options['address'] or '*'
        log.info("The web interface is on http://%s:%d/?token=... . It is plain "
                 "HTTP, so the token travels in clear; bind it to localhost and use "
                 "a tunnel, or put TLS in front, if the network it is on is not one "
                 "you trust.", where, listener.port)
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
                                 "no protocol recognised this")
            return None, None, None, None

        # Which console this is, and whether it presents the right password, are
        # asked of the upload as it arrived. A protocol that unpacks its payload may
        # not carry the name through: WeatherFlow's observations are an array, and the
        # hub's serial is on the message around it rather than in it.
        station = self._station_for(protocol, raw, request.client_address)
        if station is None:
            self._record_refused(request, protocol, protocol.station_of(raw),
                                 "not one of this driver's consoles")
            return None, None, None, None

        if protocol.secret and not self._secret_ok(protocol, raw,
                                                   request.client_address):
            self._record_refused(request, protocol, protocol.station_of(raw),
                                 "wrong %s" % protocol.secret)
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

    # ---- what the web interface reads ---------------------------------------

    def _record(self, request, protocol, dialect, raw, packet, station, mapper):
        """Keep the upload, so that a question about it can be answered later.

        Bounded and in memory only. See activity.py.
        """
        ident = protocol.station_of(raw)
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

    def _record_refused(self, request, protocol, ident, note):
        self.activity.refused(activity.Upload(
            at=time.time(), client=request.client_address,
            path=request.path or '', method=request.method or '',
            text=request.text or '', ident=ident,
            protocol=protocol.name if protocol else None, note=note))

    def web_overview(self):
        """Everything the front page draws."""
        stations = self.activity.snapshot()
        for row in stations:
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
        schema = admin.schema_fields()
        occupied = self.occupied or {}

        # Only what this station has actually sent. The catalog is five hundred
        # names long and the answer to 'where does my reading go' is not helped by
        # four hundred and fifty rows about sensors nobody owns.
        seen = set(found['raw_seen'])
        rows = []
        for raw in sorted(seen):
            field = found['fields'].get(raw, '')
            guess = found['guesses'].get(raw)
            why = ''
            if raw in found['undecided']:
                field = ''
                why = ("drivers disagree: this one says %s, %s says %s"
                       % (found['fields'].get(raw, '?'),
                          _contested_with(station), found['undecided'][raw]))
            elif guess:
                field, why = guess[0], guess[2]
            rows.append({
                'raw': raw,
                'field': field,
                'value': last.get(field),
                'group': groups.get(field, ''),
                'column': bool(field) and field in schema,
                'history': (occupied.get(field) or (0,))[0],
                'reserved': raw in reserved,
                'why': why,
            })
        found['ok'] = True
        found['fields'] = rows
        found['undecided'] = sorted(seen & set(found['undecided']))
        found['guesses'] = sorted(seen & set(found['guesses']))
        return found

    def _station_for_ident(self, ident):
        return (self.stations.get(ident) or self.web_stations.get(ident)
                or self.default_station)

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

    def web_set_field(self, ident, raw, field):
        """Place one raw field for one station."""
        ident = str(ident or '').strip()
        if ident in self.stations:
            return False, ("weewx.conf names this station, so its field map lives "
                           "there. Change it there, or take the station out of "
                           "[[stations]] first.")
        ok, message = self.overrides.set_field(ident, raw, field)
        if not ok:
            return False, message
        self.reload_wanted = True
        return True, message

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
            wanted = columns.missing(packet, groups)
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
    # will not start without a token of at least 16 characters. Make one with:
    #   python -c "import secrets; print(secrets.token_urlsafe(24))"
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

    # The driver to use:
    driver = user.ultimatepush.driver
"""

    def prompt_for_settings(self):
        settings = {}
        settings['port'] = self._prompt("port", '8000')
        return settings
