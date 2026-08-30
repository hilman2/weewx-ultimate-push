#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""Home Assistant, read as a source of weather readings.

Every other protocol here is one make of hardware. This one is a doorway to all of
them. Home Assistant has an integration for very nearly every sensor that exists, and
it publishes them all through one documented REST API with the type and the unit
attached, so what is written here reads an Aqara room thermometer, a sensor inside a
Shelly, a Zigbee soil probe and whatever is sold next, without a line being added.

That is why there is no field table in the catalog for this protocol. Every other one
needs a list saying what each name means and what unit it arrives in; Home Assistant
has done both already:

    {"entity_id": "sensor.balkon_temperatur",
     "state": "-3.9",
     "attributes": {"unit_of_measurement": "°C", "device_class": "temperature"},
     "last_updated": "2026-08-31T09:15:00+00:00"}

So each entity is turned into a reading named after its `device_class`, converted
from its `unit_of_measurement`, and after that it is the ordinary path: the same
field map, the same channels, the same rule about which station owns which column.

**One block is one Home Assistant device, not one Home Assistant.** Home Assistant
already groups entities into devices, and that grouping is what makes roles and
channels work here: the thermometer indoors goes to `extraTemp` and the one outdoors
to `outTemp`, and they do not fight over a column. Two devices means two blocks
against the same Home Assistant, which costs nothing.

**A reading is several requests.** One `GET /api/states/<entity_id>` per entity,
which keeps the answers small and means one broken entity does not spoil the reading
for the others. The poller lets a protocol assemble its own answer for exactly this;
what comes back from here is one body, and nothing downstream knows the difference.

Reading is the whole of it. Nothing is written back to Home Assistant, no service is
called, and the WebSocket API is not used.

Checked against the Home Assistant documentation and source on 31-Aug-2026.
"""

import json
import logging
import time
import urllib.error
import urllib.parse
from typing import Any, Dict, List, TYPE_CHECKING

from . import METRICWX, Protocol
from .. import catalogs

# For the docstring types only. A protocol that assembles its own answer is handed
# the source it is assembling for, and polling imports this package, so naming the
# class at run time would be a circle. Nothing here imports it.
if TYPE_CHECKING:
    from ..polling import Source

log = logging.getLogger(__name__)

_catalog = catalogs.homeassistant

# The three things this asks for. The whole REST surface is `/api/` and a dozen
# paths under it, and there is no device registry among them: the registries live on
# the WebSocket API, which is out of scope. See _device_map for how the devices are
# read without one.
ONE_STATE = '/api/states/'
ALL_STATES = '/api/states'
TEMPLATE = '/api/template'

# What Home Assistant answers when the token is not one of its own. 401 is a token
# it does not know; 403 is one it knows and will not accept for this. Neither is
# worth retrying differently, and neither is a reading.
REFUSED = (401, 403)

# States that are not readings. `unavailable` means Home Assistant cannot reach the
# entity; `unknown` means it has not been told yet. Both arrive as those literal
# strings where a number would be, and neither of them is zero.
ABSENT = ('unavailable', 'unknown')

# How old a reading may be, as multiples of the interval, when nobody says.
#
# A radio sensor with a flat battery keeps returning its last value for ever, and
# Home Assistant reports it as faithfully as it reports a live one. Polling that
# every minute would write one afternoon's temperature into the database sixty times
# an hour as though each were a fresh measurement. Twice the interval is late enough
# that an ordinary missed update is not thrown away, and early enough that a sensor
# which has stopped is noticed within two questions.
STALE_INTERVALS = 2.0

# Largest listing to read, for the one request that asks for every entity at once.
# A large installation has a few thousand of them, which is a megabyte or so; the
# limit a reading is held to is far too small for it.
MAX_LISTING = 8388608

# The micro sign and the Greek letter mu look identical and are different
# characters. Home Assistant writes micrograms with the Greek letter today and wrote
# them with the micro sign for years, so a unit is folded onto one of them before it
# is looked up. Without this a sensor on an older installation converts nothing and
# nothing says why.
MICRO_SIGN = 'µ'
GREEK_MU = 'μ'


class HomeAssistant(Protocol):
    """The entities of one Home Assistant device, read over its REST API."""

    name = 'homeassistant'
    label = 'Home Assistant'
    hardware = (
        'Any sensor Home Assistant can read and this driver cannot: Aqara and '
        'SwitchBot room sensors, Zigbee and Z-Wave soil probes, Shelly and Tado '
        'built-in sensors, anything on Matter or Bluetooth, and every weather '
        'station with an integration of its own'
    )

    # Asked rather than waited for, which is what keeps it out of 'auto': there is
    # no socket to open and nothing arrives on its own.
    fetched = True
    reached = 'fetch'
    # No single thing to ask for. A reading here is one request per entity, so the
    # address is the whole of the URL and fetch() builds the rest.
    fetch_path = ''
    fetch_settings = (
        ('token', 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.a-very-long-token'),
        ('entities', 'sensor.garden_temperature, sensor.garden_humidity'),
    )
    # A Home Assistant has the whole house in it. Which of it is weather is a
    # question only its owner can answer, so the interface offers and they pick.
    discovers = True

    # The device Home Assistant grouped these entities into. Read once, at setup;
    # see station_of and _device_map.
    identity = ('device_id',)
    secret_kind = None

    # Everything is converted before it is placed, so the catalog is one system.
    units = METRICWX
    fields = _catalog.FIELDS
    groups = _catalog.GROUPS
    metadata = _catalog.METADATA

    # An integration that reports rainfall nearly always reports the total so far,
    # which is what this column is for and what StdDelta has to difference. One that
    # reports the amount since the last reading instead needs 'rain' named by hand.
    rain_counter = 'dayRain'

    notes = (
        "Home Assistant has nowhere to type a server address into, and it is not "
        "asked to send anything. This driver asks it, so what is needed is its "
        "address and a token.",
        "The token is a long-lived access token, made in Home Assistant under your "
        "own profile, at the bottom of the Security tab. It grants everything your "
        "user account can do, so treat it the way you would your password.",
        "One block is one Home Assistant device. Several devices means several "
        "blocks against the same address, each with its own role and channel.",
    )

    @classmethod
    def headers_for(cls, settings):
        """The bearer token, on every request this source makes.

        Args:
            settings (dict): The source's block.

        Returns:
            dict: The Authorization header, or nothing when no token was given.
            An empty one is not an error here: saying so is Home Assistant's job,
            and it says so clearly.
        """
        token = str(settings.get('token', '')).strip()
        return {'Authorization': 'Bearer ' + token} if token else {}

    @classmethod
    def fetch(cls, source, ask):
        """One reading, out of one request per entity.

        Args:
            source (Source): What to ask. See polling.Source.
            ask (callable): How to make one request. See polling.ask.

        Returns:
            tuple: (the body as bytes, the headers as a dict).

        Raises:
            ValueError: If the block names no entities, if the token was refused, or
                if not one entity could be read. The poller sits in the failure and
                says so once, which is what stops a wrong token writing a line a
                minute into somebody's log.
        """
        entities = cls.entities_in(source.settings)
        if not entities:
            raise ValueError(
                "'%s' names no entities. A Home Assistant source is the entities of "
                "one device, so there is nothing to ask for." % source.name
            )
        about = cls._device_map(source, ask, entities)
        read = []
        for entity_id in entities:
            state = cls._one_state(source, ask, entity_id)
            if state is not None:
                read.append(state)
        if not read:
            raise ValueError("none of the %d entities answered" % len(entities))
        assembled = {
            # Everything the reading has to be judged against, carried in the body
            # rather than worked out later. A body captured off a real installation
            # then reads the same way a year afterwards, which is how every other
            # protocol here is tested and is worth keeping true of this one.
            'homeassistant': {
                'device': about.get('device', ''),
                'device_id': about.get('device_id', ''),
                'asked': time.time(),
                'stale_after': cls.stale_after(source),
            },
            'entities': read,
        }
        body = json.dumps(assembled).encode('utf-8')
        return body, {'content-type': 'application/json'}

    @classmethod
    def _one_state(cls, source, ask, entity_id):
        """One entity's state, or None when it could not be had.

        One request per entity rather than one for all of them, which is the whole
        reason a sensor with a flat battery does not cost the others their reading.

        Args:
            source (Source): What to ask.
            ask (callable): How to make one request.
            entity_id (str): The entity.

        Returns:
            dict | None: The state as Home Assistant gave it, or None.

        Raises:
            ValueError: If the token was refused. That is not one entity's problem
                and there is no point asking for the rest.
        """
        url = source.url + ONE_STATE + urllib.parse.quote(entity_id)
        try:
            body, _ = ask(source, url)
        except urllib.error.HTTPError as e:
            if e.code in REFUSED:
                raise ValueError(
                    "the token was refused (HTTP %d). Make a new long-lived access "
                    "token in Home Assistant and put it in the 'token' line." % e.code
                )
            cls._trouble(source, entity_id, "Home Assistant answered %d" % e.code)
            return None
        except Exception as e:
            cls._trouble(source, entity_id, str(e))
            return None
        try:
            state = json.loads(body.decode('utf-8'))
        except (UnicodeDecodeError, ValueError) as e:
            cls._trouble(source, entity_id, "the answer was not JSON: %s" % e)
            return None
        if not isinstance(state, dict):
            cls._trouble(source, entity_id, "the answer was not a state")
            return None
        cls._settled(source, entity_id)
        return state

    @classmethod
    def _trouble(cls, source, entity_id, why):
        """Say once that one entity cannot be read, and then stay quiet.

        Same rule as the poller applies to a whole source, and for the same reason:
        an entity somebody renamed a month ago must not write a line a minute.

        Args:
            source (Source): Whose entity it is.
            entity_id (str): The entity.
            why (str): What went wrong.
        """
        failing = source.held.setdefault('failing', set())
        if entity_id in failing:
            return
        failing.add(entity_id)
        log.warning(
            "'%s' cannot read %s: %s. Still asking, quietly. The other entities are "
            "unaffected.",
            source.name,
            entity_id,
            why,
        )

    @classmethod
    def _settled(cls, source, entity_id):
        """Say that an entity is answering again, if it had stopped.

        Args:
            source (Source): Whose entity it is.
            entity_id (str): The entity.
        """
        failing = source.held.setdefault('failing', set())
        if entity_id in failing:
            failing.discard(entity_id)
            log.info("'%s' can read %s again.", source.name, entity_id)

    @classmethod
    def _device_map(cls, source, ask, entities):
        """Which Home Assistant device these entities belong to. Asked once.

        Args:
            source (Source): What to ask. The answer is kept on it, in `held`.
            ask (callable): How to make one request.
            entities (list[str]): The entities to look up.

        Returns:
            dict: With 'device' and 'device_id', either of which is empty when the
            device could not be read. Nothing else depends on them: they name the
            station and no reading passes through them.
        """
        # Asked once per source and then remembered, because the entities of a
        # device do not move. A request a minute for an answer that cannot change
        # is a request a minute somebody else's machine has to serve.
        held = source.held.get('device')
        if held is not None:
            return held
        found = {'device': '', 'device_id': ''}
        # There is no device registry in the REST API; the registries are on the
        # WebSocket API, which this driver does not speak. The template language
        # does have one, and `/api/template` renders a template server-side, so one
        # POST returns the whole map. That is the only reason this endpoint is used.
        asking = json.dumps({'template': _device_template(entities)})
        try:
            body, _ = ask(source, source.url + TEMPLATE, body=asking.encode('utf-8'))
            rendered = json.loads(body.decode('utf-8'))
        except urllib.error.HTTPError as e:
            if e.code in REFUSED:
                # Not a wrong token. `/api/template` is the one endpoint here that
                # needs an administrator's, so a token made for reading is refused
                # by this and by nothing else, and the readings are unaffected.
                # Remembered as empty, because a token does not become an
                # administrator's between one minute and the next.
                log.info(
                    "'%s' may not read the device registry, so its readings are "
                    "recorded without the device's name. That needs an "
                    "administrator's token and nothing else here does.",
                    source.name,
                )
                source.held['device'] = found
            return found
        except Exception:
            # Home Assistant unreachable, or the answer unreadable. Deliberately
            # not remembered: the next question is a new chance, and the entities
            # are about to fail in the same way and say so.
            return found
        for entity_id in entities:
            one = rendered.get(entity_id) if isinstance(rendered, dict) else None
            if not isinstance(one, dict):
                continue
            if one.get('id'):
                found['device_id'] = str(one['id'])
                found['device'] = str(one.get('name') or '')
                break
        source.held['device'] = found
        return found

    @classmethod
    def discover(cls, source, ask):
        """The entities worth reading, grouped by the device they belong to.

        For the web interface, which offers them and lets somebody pick. Nothing is
        recorded by asking: a sensor is read because it was chosen, never because it
        was found.

        Args:
            source (Source): Where Home Assistant is, and the token to use.
            ask (callable): How to make one request.

        Returns:
            list[dict]: One per device, each with 'device', 'device_id' and
            'entities', where an entity is its id, its name, its device class and
            its unit. Devices with a name first, so that the ones Home Assistant
            could group come before the ones it could not.

        Raises:
            ValueError: If the token was refused.
        """
        try:
            body, _ = ask(source, source.url + ALL_STATES, limit=MAX_LISTING)
        except urllib.error.HTTPError as e:
            if e.code in REFUSED:
                raise ValueError("the token was refused (HTTP %d)." % e.code)
            raise
        states = json.loads(body.decode('utf-8'))
        wanted = []
        for state in states if isinstance(states, list) else []:
            if not isinstance(state, dict):
                continue
            attributes = state.get('attributes') or {}
            device_class = str(attributes.get('device_class') or '')
            if device_class not in _catalog.FIELDS:
                continue
            wanted.append(
                {
                    'entity_id': str(state.get('entity_id') or ''),
                    'name': str(attributes.get('friendly_name') or ''),
                    'device_class': device_class,
                    'unit': str(attributes.get('unit_of_measurement') or ''),
                    'state': str(state.get('state') or ''),
                }
            )
        return _by_device(cls._devices_of(source, ask, wanted), wanted)

    @classmethod
    def _devices_of(cls, source, ask, wanted):
        """The device each of these entities belongs to, in one request.

        Args:
            source (Source): What to ask.
            ask (callable): How to make one request.
            wanted (list[dict]): The entities found, each with an 'entity_id'.

        Returns:
            dict: Entity id to {'id': ..., 'name': ...}. Empty when the token may
            not read the registry, which leaves the entities ungrouped rather than
            leaving the caller with nothing.
        """
        ids = [one['entity_id'] for one in wanted]
        if not ids:
            return {}
        asking = json.dumps({'template': _device_template(ids)})
        try:
            body, _ = ask(
                source,
                source.url + TEMPLATE,
                body=asking.encode('utf-8'),
                limit=MAX_LISTING,
            )
            rendered = json.loads(body.decode('utf-8'))
        except Exception:
            return {}
        return rendered if isinstance(rendered, dict) else {}

    @classmethod
    def entities_in(cls, settings):
        """The entities a block names, in the order it names them.

        The order is not decoration. It decides which temperature on a device with
        two of them is the temperature; see readings().

        Args:
            settings (dict): The source's block. `entities` is a comma-separated
                list, which configobj may already have split for us.

        Returns:
            list[str]: The entity ids, without repeats.
        """
        given = settings.get('entities')
        if given is None:
            parts = []
        elif isinstance(given, (list, tuple)):
            parts = [str(one) for one in given]
        else:
            parts = str(given).split(',')
        found = []
        for part in parts:
            entity_id = part.strip()
            if entity_id and entity_id not in found:
                found.append(entity_id)
        return found

    @classmethod
    def stale_after(cls, source):
        """How old a reading of this source may be before it is not a reading.

        Args:
            source (Source): The source, for its interval.

        Returns:
            float: Seconds.
        """
        given = source.settings.get('stale')
        if given not in (None, ''):
            try:
                return max(0.0, float(given))
            except (TypeError, ValueError):
                log.warning(
                    "'%s' has stale = %s, which is not a number of seconds. Using "
                    "%g instead.",
                    source.name,
                    given,
                    STALE_INTERVALS * source.interval,
                )
        return STALE_INTERVALS * source.interval

    @classmethod
    def claims(cls, request, raw):
        """An answer this driver assembled out of Home Assistant states.

        Nothing arrives here on its own, so this is only ever asked about something
        fetch() built. It still has to be told apart from the other two protocols
        that are asked, because the address in a block can be wrong.
        """
        about = raw.get('homeassistant')
        entities = raw.get('entities')
        if not isinstance(about, dict) or not isinstance(entities, list):
            return 0
        if not entities:
            return 0
        for one in entities:
            if not isinstance(one, dict) or not one.get('entity_id'):
                return 0
        return 5

    @classmethod
    def station_of(cls, raw):
        """The Home Assistant device these entities belong to.

        The id rather than the name, because a device can be renamed and a station
        that changed its identity when somebody tidied up their house would stop
        recording. The name when there is no id, which is what a token that may not
        read the device registry leaves behind.
        """
        about = raw.get('homeassistant') or {}
        return str(about.get('device_id') or about.get('device') or '').strip()

    @classmethod
    def readings(cls, request, raw):
        """Turn each entity into one named reading, in the unit WeeWX keeps it in.

        A reading is named after its `device_class`, which is what the catalog is
        written against, and its value is converted from its `unit_of_measurement`.
        An entity reporting `unavailable`, `unknown` or a reading older than this
        source allows produces nothing at all: not a zero, and not a string in a
        packet. The entities beside it are unaffected.
        """
        about = raw.get('homeassistant') or {}
        asked = _number(about.get('asked'))
        stale_after = _number(about.get('stale_after'))
        named = {}
        counted = {}  # type: Dict[str, int]
        for entity in raw.get('entities') or []:
            if not isinstance(entity, dict):
                continue
            attributes = entity.get('attributes') or {}
            device_class = str(attributes.get('device_class') or '').strip()
            if device_class:
                # Which of two temperatures on one device is the temperature is
                # decided by the order the block names them in, and by nothing else.
                # The first fills outTemp; the second is called temperature_2, which
                # the catalog does not place, so it arrives prefixed and waits in the
                # web interface for somebody to give it a column.
                #
                # Every alternative guesses. extraTemp1 would collide with the
                # channel an extra station is already given, and choosing between two
                # thermometers by their names would be this driver deciding which of
                # somebody's rooms is outdoors. The order in the block is the one
                # answer that is theirs.
                #
                # Counted before anything is dropped, so that an outdoor thermometer
                # which is briefly unavailable does not hand outTemp to the one
                # indoors for a minute and take it back afterwards. Two sensors mixed
                # into one column cannot be separated again.
                counted[device_class] = counted.get(device_class, 0) + 1
                name = _named(device_class, counted[device_class])
            else:
                # Nothing says what this measures, so nothing here can place it.
                # Named after the entity instead, so that it shows in the web
                # interface and can be placed by hand rather than quietly dropped.
                name = _object_id(entity.get('entity_id'))
            if not name:
                continue
            value = _reading(entity, asked, stale_after)
            if value is None:
                continue
            wanted = _catalog.UNITS.get(device_class)
            unit = _folded(attributes.get('unit_of_measurement'))
            if wanted is None or unit == wanted:
                named[name] = value
                continue
            how = _catalog.CONVERT.get(wanted, {}).get(unit)
            if how is None:
                # A unit nothing can be done with: Beaufort, or micrograms where the
                # column is parts per million. Kept, under a name that carries the
                # unit, so it shows in the web interface rather than being written
                # into a column labelled something it is not.
                named[_with_unit(name, unit)] = value
                continue
            factor, offset = how
            named[name] = value * factor + offset
        return named


def _named(device_class, seen):
    """What to call the nth reading of one device class.

    Args:
        device_class (str): Home Assistant's own name for what it measures.
        seen (int): How many of this class have been counted, this one included.

    Returns:
        str: The name to place it under.
    """
    return device_class if seen == 1 else '%s_%d' % (device_class, seen)


def _object_id(entity_id):
    """The part of an entity id that names the thing rather than its domain.

    Args:
        entity_id (str | None): e.g. 'sensor.balkon_temperatur'.

    Returns:
        str: e.g. 'balkon_temperatur', or '' when there is nothing to take.
    """
    text = str(entity_id or '').strip()
    return text.split('.', 1)[1] if '.' in text else text


def _with_unit(name, unit):
    """A name that carries the unit its reading is in.

    For the readings nothing can convert. The unit is in the name so that whoever
    places the field can see what they are placing.

    Args:
        name (str): What the reading would have been called.
        unit (str): The unit it arrived in.

    Returns:
        str: e.g. 'ozone_ug_m3'.
    """
    plain = ''.join(
        character if character.isalnum() else '_' for character in unit
    ).strip('_')
    return ('%s_%s' % (name, plain)).strip('_') if plain else name


def _reading(entity, asked, stale_after):
    """The number an entity is reporting, or None when it is not reporting one.

    Args:
        entity (dict): One state, as Home Assistant gave it.
        asked (float | None): When the answer was assembled.
        stale_after (float | None): How old a reading may be.

    Returns:
        float | None: The value, or None for `unavailable`, for `unknown`, for
        anything that is not a number, and for a reading that is too old.
    """
    state = entity.get('state')
    if not isinstance(state, str) or state.strip().lower() in ABSENT:
        return None
    if _too_old(entity.get('last_updated'), asked, stale_after):
        return None
    return _number(state)


def _too_old(last_updated, asked, stale_after):
    """Whether a reading is old enough that it is not a reading.

    A stamp that cannot be read is not treated as old. Home Assistant writes these
    itself and they are always the same shape, so an unreadable one means something
    changed in Home Assistant rather than that the sensor has stopped, and throwing
    away every reading would be the wrong way to find that out.

    Args:
        last_updated (str | None): The stamp, as Home Assistant wrote it.
        asked (float | None): When the answer was assembled.
        stale_after (float | None): How old a reading may be, in seconds.

    Returns:
        bool: Whether to leave it out.
    """
    if not asked or not stale_after:
        return False
    when = _epoch(last_updated)
    if when is None:
        return False
    return (asked - when) > stale_after


def _epoch(stamp):
    """One of Home Assistant's timestamps as seconds since 1970.

    Args:
        stamp (str | None): An ISO 8601 stamp with a time zone on it.

    Returns:
        float | None: The time, or None when it could not be read.
    """
    import datetime

    text = str(stamp or '').strip()
    if not text:
        return None
    # Python 3.7's fromisoformat reads what isoformat writes and nothing else, and
    # 'Z' is the one thing that turns up which it writes differently.
    if text.endswith('Z'):
        text = text[:-1] + '+00:00'
    try:
        when = datetime.datetime.fromisoformat(text)
    except ValueError:
        return None
    if when.tzinfo is None:
        # Home Assistant always sends one. Without it there is nothing to say which
        # clock this is, so it is read as UTC, which is what Home Assistant keeps.
        when = when.replace(tzinfo=datetime.timezone.utc)
    return when.timestamp()


def _number(value):
    """A value as a float, or None when it is not one.

    Args:
        value (str | float | int | None): What arrived.

    Returns:
        float | None: The number.
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _folded(unit):
    """A unit, with the two ways of writing micro folded onto one.

    Args:
        unit (str | None): What `unit_of_measurement` said.

    Returns:
        str: The unit, or '' when there was none.
    """
    return str(unit or '').replace(MICRO_SIGN, GREEK_MU)


def _device_template(entities):
    """A template that answers which device each of these entities belongs to.

    The REST API has no device registry. The template language has one, and
    `/api/template` renders a template server-side, so one POST returns the whole
    map. `device_id` and `device_name` are Home Assistant's own template functions,
    from homeassistant/helpers/template/extensions/devices.py, and `to_json` is its
    own filter, so an entity with no device renders as null rather than as the word
    None.

    Args:
        entities (list[str]): The entity ids to look up.

    Returns:
        str: The template.
    """
    parts = []
    for entity_id in entities:
        quoted = json.dumps(entity_id)
        parts.append(
            '%s: {"id": {{ device_id(%s) | to_json }}, '
            '"name": {{ device_name(%s) | to_json }}}' % (quoted, quoted, quoted)
        )
    return '{' + ', '.join(parts) + '}'


def _by_device(devices, entities):
    """Group the entities found by the device each belongs to.

    Args:
        devices (dict): Entity id to {'id': ..., 'name': ...}, from the template.
        entities (list[dict]): What was found, each with an 'entity_id'.

    Returns:
        list[dict]: One per device, each with 'device', 'device_id' and 'entities'.
        Devices Home Assistant could name come first: those are the ones a block
        should be made of, and the rest are whatever is left.
    """
    found = []  # type: List[Dict[str, Any]]
    where = {}
    for one in entities:
        about = devices.get(one['entity_id'])
        about = about if isinstance(about, dict) else {}
        device_id = str(about.get('id') or '')
        if device_id not in where:
            where[device_id] = len(found)
            found.append(
                {
                    'device': str(about.get('name') or ''),
                    'device_id': device_id,
                    'entities': [],
                }
            )
        found[where[device_id]]['entities'].append(one)
    found.sort(key=lambda group: (not group['device_id'], group['device']))
    return found
