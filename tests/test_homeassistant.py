#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""Home Assistant, read as a source of readings.

Everything here runs against the shipped fake, on a port the machine chose, so
there is no Home Assistant and no network beyond the loopback. The fake is
`simulate.homeassistant_handler`, which is the same object `--fake-homeassistant`
runs; a copy of it in this file would be a copy that agrees with the code until the
day it stops.

Two things are checked over and over. That a reading which is not a reading never
becomes a zero, because `unavailable` and a flat battery are the states a real
installation has within a week and both of them look like data. And that a value
arrives in the unit WeeWX keeps its column in, because a wrong factor is otherwise
silent: the graph has the right shape and the wrong numbers.
"""

import json
import logging
import socketserver
import threading
import time

import pytest

from ultimatepush import polling, simulate, transport
from ultimatepush.catalogs import homeassistant as catalog
from ultimatepush.protocols.homeassistant import HomeAssistant

# A moment to build a body at, for the tests that do not go near a server. Any
# moment will do: every reading here is a function of one, so the same number twice
# gives the same answer.
AT = 1788118495.0

OUTDOORS = simulate.HA_DEVICES[0]
INDOORS = simulate.HA_DEVICES[1]
OUTDOOR_ENTITIES = [one['entity_id'] for one in OUTDOORS['entities']]


class Assistant:
    """The shipped fake, on a port of its own, counting what it was asked.

    Its clock is stopped at the moment it started, which is what lets a test assert
    the reading rather than a range around it. Stopped at that moment rather than at
    some moment in 2026, because the driver judges how old a reading is against its
    own clock, and everything a fake stopped a year ago says is stale.

    Args:
        token (str): The token it insists on.
        admin (bool): Whether the token may render templates. `/api/template` needs
            an administrator's token and nothing else here does, so a token made
            for reading is refused there and nowhere else. False is that
            installation.
    """

    def __init__(self, token=simulate.HA_TOKEN, admin=True):
        self.asked = []
        self.pinned = time.time()
        pinned = self.pinned
        base = simulate.homeassistant_handler(token, clock=lambda: pinned)
        counting = self

        class Handler(base):
            """The fake, with a note of every request kept beside it."""

            def do_GET(self):
                counting.asked.append(self.path)
                base.do_GET(self)

            def do_POST(self):
                counting.asked.append(self.path)
                if not admin:
                    self.send_response(401)
                    self.send_header('Content-Length', '0')
                    self.end_headers()
                    return
                base.do_POST(self)

            def log_message(self, *args):
                """Quiet. The test says what happened, not the server."""

        self.server = socketserver.TCPServer(('127.0.0.1', 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def address(self):
        return '127.0.0.1:%d' % self.port

    def counted(self, path):
        """How many times one path was asked for.

        Args:
            path (str): The path, e.g. '/api/template'.

        Returns:
            int: How many.
        """
        return len([one for one in self.asked if one == path])

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)


@pytest.fixture
def assistant():
    """A Home Assistant answering with two devices, at one moment."""
    made = Assistant()
    yield made
    made.close()


def expected(assistant, entities=None):
    """What the fake's outdoor device is reporting, converted, at its moment.

    Read out of the fake rather than written down, so that changing what it reports
    does not mean going through the tests changing numbers to match.

    Args:
        assistant (Assistant): The fake.
        entities (list | None): Which entities. The outdoor device's by default.

    Returns:
        dict: Device class to the value the column should hold.
    """
    wanted = entities if entities is not None else OUTDOOR_ENTITIES
    return HomeAssistant.readings(
        None,
        a_body(
            [simulate.homeassistant_state(one, assistant.pinned) for one in wanted],
            stale_after=600.0,
            asked=assistant.pinned,
        ),
    )


def source_for(assistant, entities=None, **extra):
    """A source pointed at the fake.

    Args:
        assistant (Assistant): The fake.
        entities (list | None): What to read. The outdoor device's, by default.
        **extra: Anything else to put in the block.

    Returns:
        polling.Source: The source.
    """
    block = {
        'protocol': 'homeassistant',
        'address': assistant.address,
        'token': simulate.HA_TOKEN,
        'entities': ', '.join(entities if entities is not None else OUTDOOR_ENTITIES),
        'interval': '30',
    }
    block.update(extra)
    return polling.source_for('balkon', block)


def read(source):
    """Ask once and read the answer the way the driver would.

    Args:
        source (polling.Source): What to ask.

    Returns:
        dict: The named readings.
    """
    body, _ = polling._fetch(source)
    return HomeAssistant.readings(None, transport.parse(body.decode('utf-8')))


def one_entity(device_class, unit, state, last_updated=None):
    """One entity, shaped the way the REST API shapes one.

    Args:
        device_class (str): What Home Assistant says it measures.
        unit (str): What `unit_of_measurement` says.
        state (str): The state, as the string it always is.
        last_updated (str | None): When, or None for the moment the body was
            assembled.

    Returns:
        dict: The state.
    """
    return {
        'entity_id': 'sensor.test_%s' % device_class,
        'state': state,
        'attributes': {'device_class': device_class, 'unit_of_measurement': unit},
        'last_updated': last_updated or _iso(AT),
    }


def a_body(entities, stale_after=600.0, asked=AT):
    """An assembled answer, of the shape fetch() hands back.

    Args:
        entities (list): The states in it.
        stale_after (float): How old a reading may be.
        asked (float): When it was assembled.

    Returns:
        dict: The body.
    """
    return {
        'homeassistant': {
            'device': 'Test',
            'device_id': 'ffffffffffffffffffffffffffffffff',
            'asked': asked,
            'stale_after': stale_after,
        },
        'entities': entities,
    }


def _iso(seconds):
    """A moment, written the way Home Assistant writes one."""
    import datetime

    return datetime.datetime.fromtimestamp(seconds, datetime.timezone.utc).isoformat()


# ---- every unit of every device class ---------------------------------------
#
# The table below is Home Assistant's own DEVICE_CLASS_UNITS, read out of
# homeassistant/components/sensor/const.py on 31-Aug-2026, for the classes this
# driver places. Every unit it allows is here with the number it becomes, so that a
# wrong factor fails rather than producing a graph of the right shape and the wrong
# numbers.
#
# Two of Home Assistant's units are deliberately absent, and there is a test below
# for each: Beaufort, which is a scale of ranges rather than a unit, and parts per
# billion or million where the column is micrograms per cubic metre, which cannot be
# converted without knowing the temperature and the pressure.

CONVERSIONS = [
    # (device class, unit, what arrived, what the column should hold)
    ('temperature', '°C', '21.5', 21.5),
    ('temperature', '°F', '70.7', 21.5),
    ('temperature', 'K', '294.65', 21.5),
    ('humidity', '%', '63.5', 63.5),
    ('moisture', '%', '41.0', 41.0),
    ('battery', '%', '88.0', 88.0),
    ('wind_direction', '°', '247.0', 247.0),
    # Pressure. Home Assistant allows every one of its pressure units for a
    # barometer, and WeeWX keeps this column in millibars, which is a hectopascal
    # under an older name.
    ('atmospheric_pressure', 'hPa', '1013.25', 1013.25),
    ('atmospheric_pressure', 'mbar', '1013.25', 1013.25),
    ('atmospheric_pressure', 'cbar', '101.325', 1013.25),
    ('atmospheric_pressure', 'bar', '1.01325', 1013.25),
    ('atmospheric_pressure', 'kPa', '101.325', 1013.25),
    ('atmospheric_pressure', 'Pa', '101325', 1013.25),
    ('atmospheric_pressure', 'mPa', '101325000', 1013.25),
    ('atmospheric_pressure', 'mmHg', '760', 1013.2502),
    ('atmospheric_pressure', 'inHg', '29.92126', 1013.2497),
    ('atmospheric_pressure', 'psi', '14.69595', 1013.2496),
    ('atmospheric_pressure', 'inH₂O', '406.7823', 1013.2503),
    # The older class, which an integration written before the split still uses.
    ('pressure', 'hPa', '1013.25', 1013.25),
    ('pressure', 'inHg', '29.92126', 1013.2497),
    # Wind, into metres a second.
    ('wind_speed', 'm/s', '5.0', 5.0),
    ('wind_speed', 'km/h', '18.0', 5.0),
    ('wind_speed', 'mph', '10.0', 4.4704),
    ('wind_speed', 'kn', '10.0', 5.1444444),
    ('wind_speed', 'ft/s', '10.0', 3.048),
    ('wind_speed', 'in/s', '100.0', 2.54),
    ('wind_speed', 'm/min', '60.0', 1.0),
    ('wind_speed', 'mm/s', '1000.0', 1.0),
    # Rain, into millimetres.
    ('precipitation', 'mm', '12.5', 12.5),
    ('precipitation', 'cm', '1.25', 12.5),
    ('precipitation', 'in', '0.5', 12.7),
    ('precipitation_intensity', 'mm/h', '3.0', 3.0),
    ('precipitation_intensity', 'mm/d', '48.0', 2.0),
    ('precipitation_intensity', 'in/h', '0.5', 12.7),
    ('precipitation_intensity', 'in/d', '24.0', 25.4),
    # Light.
    ('illuminance', 'lx', '12000', 12000.0),
    ('irradiance', 'W/m²', '800', 800.0),
    ('irradiance', 'BTU/(h⋅ft²)', '100', 315.4591),
    # Air quality.
    ('pm1', 'μg/m³', '4.1', 4.1),
    ('pm25', 'μg/m³', '7.2', 7.2),
    ('pm4', 'μg/m³', '7.8', 7.8),
    ('pm10', 'μg/m³', '8.0', 8.0),
    ('aqi', '', '42', 42.0),
    ('carbon_dioxide', 'ppm', '612', 612.0),
    ('ozone', 'ppm', '0.031', 0.031),
    ('ozone', 'ppb', '31', 0.031),
    ('nitrogen_dioxide', 'μg/m³', '18.4', 18.4),
    ('sulphur_dioxide', 'ppb', '4', 0.004),
    ('sound_pressure', 'dB', '38.2', 38.2),
    ('sound_pressure', 'dBA', '38.2', 38.2),
    # Everything else the list of classes worth reading has.
    ('voltage', 'V', '3.05', 3.05),
    ('voltage', 'mV', '3050', 3.05),
    ('voltage', 'μV', '3050000', 3.05),
    ('voltage', 'kV', '0.00305', 3.05),
    ('voltage', 'MV', '0.00000305', 3.05),
    ('distance', 'km', '4.2', 4.2),
    ('distance', 'm', '4200', 4.2),
    ('distance', 'cm', '420000', 4.2),
    ('distance', 'mm', '4200000', 4.2),
    ('distance', 'mi', '1.0', 1.609344),
    ('distance', 'nmi', '1.0', 1.852),
    ('distance', 'ft', '1000.0', 0.3048),
    ('distance', 'yd', '1000.0', 0.9144),
    ('distance', 'in', '100000.0', 2.54),
]


@pytest.mark.parametrize('device_class,unit,sent,wanted', CONVERSIONS)
def test_every_unit_arrives_in_the_unit_the_column_is_kept_in(
    device_class, unit, sent, wanted
):
    """A wrong factor is silent otherwise, and lives in the database for ever."""
    named = HomeAssistant.readings(None, a_body([one_entity(device_class, unit, sent)]))

    assert named[device_class] == pytest.approx(wanted, rel=1e-6)


def test_every_class_the_catalog_places_is_covered_here():
    """A class added to the catalog without a case here would go unchecked."""
    covered = {one[0] for one in CONVERSIONS}

    assert not set(catalog.FIELDS) - covered


def test_the_micro_sign_and_the_letter_mu_are_the_same_unit():
    """They look identical and are different characters. Home Assistant has used
    both: the micro sign for years and the Greek letter now, so an installation
    that has not been updated converts nothing unless they are folded together."""
    named = HomeAssistant.readings(None, a_body([one_entity('pm25', 'µg/m³', '7.2')]))

    assert named['pm25'] == pytest.approx(7.2)


def test_a_unit_nothing_can_be_done_with_keeps_its_unit_in_its_name():
    """Beaufort is a scale of ranges: force 5 is anything from 8.0 to 10.7 metres a
    second, and picking a number out of that is inventing a reading. Micrograms
    where the column is parts per million needs the temperature and the pressure.

    Neither is dropped. Each arrives under a name that says what it is, so it shows
    in the web interface and can be given a column of its own."""
    named = HomeAssistant.readings(
        None,
        a_body(
            [
                one_entity('wind_speed', 'Beaufort', '5'),
                one_entity('ozone', 'μg/m³', '61.0'),
            ]
        ),
    )

    assert 'wind_speed' not in named
    assert 'ozone' not in named
    assert named['wind_speed_Beaufort'] == pytest.approx(5.0)
    assert named['ozone_μg_m³'] == pytest.approx(61.0)


# ---- readings that are not readings ------------------------------------------


def test_unavailable_and_unknown_are_not_readings():
    """Neither is zero, and neither is a string. A column that took either would
    hold a number nothing measured, and a graph would show it."""
    named = HomeAssistant.readings(
        None,
        a_body(
            [
                one_entity('temperature', '°C', 'unavailable'),
                one_entity('humidity', '%', 'unknown'),
                one_entity('atmospheric_pressure', 'hPa', '1013.2'),
            ]
        ),
    )

    assert 'temperature' not in named
    assert 'humidity' not in named
    # And the one beside them still records, which is the whole point of asking for
    # each entity on its own.
    assert named['atmospheric_pressure'] == pytest.approx(1013.2)


def test_they_are_not_readings_through_the_shipped_fake(assistant):
    """The same thing said against what ships rather than against a fixture.

    The fake has one entity that is unavailable and one that is unknown because a
    real installation has both within a week.
    """
    named = read(source_for(assistant, OUTDOOR_ENTITIES + ['sensor.wohnzimmer_co2']))

    assert 'battery' not in named
    assert 'carbon_dioxide' not in named
    assert named['temperature'] == pytest.approx(expected(assistant)['temperature'])


def test_a_reading_older_than_the_threshold_is_dropped():
    """A radio sensor with a flat battery keeps returning its last value for ever.
    Recorded every minute, one afternoon's temperature would be written sixty times
    an hour as though each were a fresh measurement."""
    named = HomeAssistant.readings(
        None,
        a_body(
            [
                one_entity('temperature', '°C', '21.5', _iso(AT - 3600.0)),
                one_entity('humidity', '%', '63.5', _iso(AT - 100.0)),
            ],
            stale_after=600.0,
        ),
    )

    assert 'temperature' not in named
    # And one inside the threshold is kept, or this would be a test that everything
    # is dropped.
    assert named['humidity'] == pytest.approx(63.5)


def test_the_threshold_is_twice_the_interval_when_nobody_says(assistant):
    source = source_for(assistant, interval='45')

    assert HomeAssistant.stale_after(source) == pytest.approx(90.0)


def test_the_threshold_can_be_set(assistant):
    source = source_for(assistant, interval='45', stale='300')

    assert HomeAssistant.stale_after(source) == pytest.approx(300.0)


def test_a_stale_reading_is_dropped_through_the_shipped_fake(assistant):
    """The fake's light sensor answers an hour late for ever, which is what a
    sensor whose battery has gone does."""
    named = read(source_for(assistant))

    assert 'illuminance' not in named
    # The same entity is a reading again once the threshold is wide enough, which
    # is what says the entity itself is fine and the age is what stopped it.
    assert 'illuminance' in read(source_for(assistant, stale='7200'))


def test_a_stamp_that_cannot_be_read_is_not_treated_as_old():
    """Home Assistant writes these itself and they are always the same shape, so an
    unreadable one means Home Assistant changed rather than that the sensor
    stopped. Throwing away every reading would be the wrong way to find that out."""
    named = HomeAssistant.readings(
        None, a_body([one_entity('temperature', '°C', '21.5', 'the day before')])
    )

    assert named['temperature'] == pytest.approx(21.5)


# ---- two readings of one class on one device ---------------------------------


def test_the_second_temperature_on_a_device_does_not_take_the_first_one_s_column():
    """Two temperatures on one device is the ordinary case: a soil probe on the
    same transmitter, a second wire on a Shelly. The order in the block decides
    which is the temperature, and the second waits to be placed by hand."""
    named = HomeAssistant.readings(
        None,
        a_body(
            [
                one_entity('temperature', '°C', '11.5'),
                one_entity('temperature', '°C', '9.0'),
                one_entity('temperature', '°C', '4.5'),
            ]
        ),
    )

    assert named['temperature'] == pytest.approx(11.5)
    assert named['temperature_2'] == pytest.approx(9.0)
    assert named['temperature_3'] == pytest.approx(4.5)
    # Only the first has a column. The rest are prefixed and shown, because putting
    # them in extraTemp would collide with the channel an extra station is given.
    assert catalog.FIELDS['temperature'] == 'outTemp'
    assert 'temperature_2' not in catalog.FIELDS


def test_which_entity_is_first_is_settled_before_anything_is_dropped():
    """An outdoor thermometer that is briefly unavailable must not hand outTemp to
    the one indoors for a minute and take it back afterwards. That mixes two
    sensors into one column, and afterwards they cannot be separated."""
    named = HomeAssistant.readings(
        None,
        a_body(
            [
                one_entity('temperature', '°C', 'unavailable'),
                one_entity('temperature', '°C', '21.5'),
            ]
        ),
    )

    assert 'temperature' not in named
    assert named['temperature_2'] == pytest.approx(21.5)


def test_the_order_of_the_entities_is_the_order_of_the_block():
    """It is not decoration: it decides which of two temperatures is outTemp."""
    assert HomeAssistant.entities_in(
        {'entities': ' sensor.b , sensor.a ,, sensor.b '}
    ) == ['sensor.b', 'sensor.a']
    # configobj splits a line with commas in it for us, and hands the rest over
    # whole. Both mean the same thing.
    assert HomeAssistant.entities_in({'entities': ['sensor.b', 'sensor.a']}) == [
        'sensor.b',
        'sensor.a',
    ]


def test_an_entity_with_no_device_class_keeps_its_own_name():
    """Nothing says what it measures, so nothing here can place it. Dropping it
    would hide it; under its own name it shows in the web interface."""
    named = HomeAssistant.readings(
        None,
        a_body(
            [
                {
                    'entity_id': 'sensor.regentonne',
                    'state': '42.0',
                    'attributes': {'friendly_name': 'Regentonne'},
                    'last_updated': _iso(AT),
                }
            ]
        ),
    )

    assert named['regentonne'] == pytest.approx(42.0)


# ---- what happens when it goes wrong -----------------------------------------


def test_a_bad_token_is_refused_and_said_once(caplog, monkeypatch):
    """Not once a minute. A Home Assistant somebody has revoked a token on must not
    write a line a minute into their log for the rest of the winter."""
    # The waits between tries, cut short, so that this runs through a good many of
    # them in the second it takes rather than one. Without that it would pass
    # against a driver that says so every single time.
    monkeypatch.setattr(polling, 'FIRST_WAIT', 0.02)
    monkeypatch.setattr(polling, 'LONGEST_WAIT', 0.02)
    assistant = Assistant(token='the-right-one')
    try:
        block = {
            'protocol': 'homeassistant',
            'address': assistant.address,
            'token': 'the-wrong-one',
            'entities': ', '.join(OUTDOOR_ENTITIES),
            'interval': '5',
        }
        with caplog.at_level(logging.INFO):
            poller = polling.build({'balkon': block})
            try:
                # Long enough for a good many tries, so that a driver which said so
                # every time would have said so a good many times.
                time.sleep(1.0)
            finally:
                poller.close()
    finally:
        assistant.close()

    said = [r for r in caplog.records if 'refused' in r.getMessage()]
    assert len(said) == 1, [r.getMessage() for r in said]
    assert 'token' in said[0].getMessage()


def test_one_broken_entity_does_not_spoil_the_others(assistant, caplog):
    """The whole reason for one request per entity rather than one for all."""
    with caplog.at_level(logging.INFO):
        named = read(source_for(assistant, ['sensor.gibt_es_nicht'] + OUTDOOR_ENTITIES))

    wanted = expected(assistant)
    assert named['temperature'] == pytest.approx(wanted['temperature'])
    assert named['humidity'] == pytest.approx(wanted['humidity'])
    said = [r for r in caplog.records if 'sensor.gibt_es_nicht' in r.getMessage()]
    assert said, "nothing said which entity could not be read"


def test_an_entity_that_cannot_be_read_is_said_once(assistant, caplog):
    source = source_for(assistant, ['sensor.gibt_es_nicht'] + OUTDOOR_ENTITIES)
    with caplog.at_level(logging.INFO):
        for _ in range(4):
            read(source)

    said = [r for r in caplog.records if 'sensor.gibt_es_nicht' in r.getMessage()]
    assert len(said) == 1, [r.getMessage() for r in said]


def test_nothing_at_all_answering_is_a_failure_rather_than_an_empty_reading(
    assistant,
):
    """An empty packet every minute would look like a station that is working."""
    with pytest.raises(ValueError):
        read(source_for(assistant, ['sensor.nope', 'sensor.also_nope']))


def test_a_block_that_names_no_entities_is_refused(assistant):
    with pytest.raises(ValueError) as complaint:
        read(source_for(assistant, []))

    assert 'entities' in str(complaint.value)


# ---- the device map ----------------------------------------------------------


def test_the_device_map_is_read_once(assistant):
    """The REST API has no device registry, so this is a template rendered
    server-side. It is asked for at setup and never again: the entities of a device
    do not move, and a request a minute for an answer that cannot change is a
    request a minute somebody else's machine has to serve."""
    source = source_for(assistant)
    read(source)

    assert assistant.counted('/api/template') == 1

    for _ in range(3):
        read(source)

    assert assistant.counted('/api/template') == 1


def test_the_device_is_what_names_the_station(assistant):
    body, _ = polling._fetch(source_for(assistant))
    raw = transport.parse(body.decode('utf-8'))

    assert HomeAssistant.station_of(raw) == OUTDOORS['id']


def test_a_token_that_may_not_read_the_registry_still_records(caplog):
    """`/api/template` needs an administrator's token and nothing else here does.

    A refusal there is not a wrong token and is not an error: the readings are
    unaffected and only the device's name is missing. It is noted once, and the
    template is not asked for again, because a token does not become an
    administrator's between one minute and the next.
    """
    assistant = Assistant(admin=False)
    try:
        source = source_for(assistant)
        with caplog.at_level(logging.INFO):
            named = read(source)
            read(source)
    finally:
        assistant.close()

    assert named['temperature'] == pytest.approx(expected(assistant)['temperature'])
    assert assistant.counted('/api/template') == 1
    said = [r for r in caplog.records if 'device registry' in r.getMessage()]
    assert len(said) == 1, [r.getMessage() for r in said]


def test_a_device_that_could_not_be_read_leaves_the_station_unnamed():
    """Rather than named something made up."""
    assistant = Assistant(admin=False)
    try:
        body, _ = polling._fetch(source_for(assistant))
    finally:
        assistant.close()

    assert HomeAssistant.station_of(transport.parse(body.decode('utf-8'))) == ''


# ---- not the others ----------------------------------------------------------


def test_a_purpleair_answer_is_not_claimed():
    assert HomeAssistant.claims(None, simulate.purpleair_answer(AT)) == 0


def test_an_airlink_answer_is_not_claimed():
    assert HomeAssistant.claims(None, simulate.airlink_answer(AT)) == 0


def test_an_ecowitt_upload_is_not_claimed(payload):
    """A captured one, off real hardware."""
    assert HomeAssistant.claims(None, transport.parse(payload('hp2561ae_pro'))) == 0


def test_an_assembled_answer_is_claimed(assistant):
    body, _ = polling._fetch(source_for(assistant))

    assert HomeAssistant.claims(None, transport.parse(body.decode('utf-8'))) == 5


def test_the_other_polled_protocols_do_not_claim_this_one(assistant):
    """The address in a block can be wrong, and then something answers that is not
    what was asked for."""
    from ultimatepush.protocols.airlink import AirLink
    from ultimatepush.protocols.purpleair import PurpleAir

    body, _ = polling._fetch(source_for(assistant))
    raw = transport.parse(body.decode('utf-8'))

    assert PurpleAir.claims(None, raw) == 0
    assert AirLink.claims(None, raw) == 0


# ---- the token stays out of the log ------------------------------------------


def test_the_token_appears_in_no_log_line(assistant, caplog, tmp_path):
    """A token in a log is a token in a bug report. It grants everything the account
    it was made under can do, so it has to survive a whole setup-and-poll cycle
    without being written anywhere, the failure paths included."""
    secret = simulate.HA_TOKEN
    with caplog.at_level(logging.DEBUG):
        # It works.
        source = source_for(assistant)
        body, _ = polling._fetch(source)
        polling._fetch(source)
        # An entity that is not there.
        read(source_for(assistant, ['sensor.gibt_es_nicht'] + OUTDOOR_ENTITIES))
        # Nothing at all at the address.
        gone = polling.source_for(
            'gone',
            {
                'protocol': 'homeassistant',
                'address': '127.0.0.1:1',
                'token': secret,
                'entities': 'sensor.balkon_temperatur',
            },
        )
        with pytest.raises(Exception):
            polling._fetch(gone)
        # And the source itself, which is what a traceback would print.
        logging.getLogger(__name__).info("the source is %r", source)

    for record in caplog.records:
        assert secret not in record.getMessage(), record.getMessage()
    # Nor in the answer, which is shown on the page of raw uploads.
    assert secret not in body.decode('utf-8')


def test_the_token_is_a_header_and_not_part_of_the_url(assistant):
    """A URL is printed. The log says which address could not be reached and the
    page of raw uploads says where a reading came from, so a token in one would be
    a token in both."""
    source = source_for(assistant)

    assert simulate.HA_TOKEN not in source.url
    assert simulate.HA_TOKEN not in repr(source)
    assert source.headers['Authorization'] == 'Bearer ' + simulate.HA_TOKEN


# ---- what is on offer --------------------------------------------------------


def test_discovery_offers_what_is_there_grouped_by_device(assistant):
    """Nothing is recorded by looking. What comes back is a list to choose from."""
    source = polling.source_for(
        'looking',
        {
            'protocol': 'homeassistant',
            'address': assistant.address,
            'token': simulate.HA_TOKEN,
        },
    )
    found = HomeAssistant.discover(source, polling.ask)

    assert [one['device'] for one in found] == [OUTDOORS['name'], INDOORS['name']]
    assert [one['entity_id'] for one in found[0]['entities']] == OUTDOOR_ENTITIES
    first = found[0]['entities'][0]
    assert first['device_class'] == 'temperature'
    assert first['unit'] == '°C'


def test_discovery_offers_nothing_it_cannot_record(assistant):
    """An entity whose device class this driver has no column for is not offered,
    because offering it would be offering a sensor that records nothing."""
    source = polling.source_for(
        'looking',
        {
            'protocol': 'homeassistant',
            'address': assistant.address,
            'token': simulate.HA_TOKEN,
        },
    )
    found = HomeAssistant.discover(source, polling.ask)

    for group in found:
        for one in group['entities']:
            assert one['device_class'] in catalog.FIELDS


def test_discovery_says_so_when_the_token_is_wrong():
    assistant = Assistant(token='the-right-one')
    try:
        source = polling.source_for(
            'looking',
            {
                'protocol': 'homeassistant',
                'address': assistant.address,
                'token': 'the-wrong-one',
            },
        )
        with pytest.raises(ValueError) as complaint:
            HomeAssistant.discover(source, polling.ask)
    finally:
        assistant.close()

    assert 'refused' in str(complaint.value)


# ---- through the whole driver ------------------------------------------------


def test_a_home_assistant_device_records_through_the_whole_driver(assistant, tmp_path):
    """One block of configuration, and a loop packet out of the far end."""
    pytest.importorskip('weewx', reason="WeeWX is not installed")
    from ultimatepush.driver import UltimatePushDriver

    driver = UltimatePushDriver(
        port=0,
        address='127.0.0.1',
        weewx_root=str(tmp_path),
        polling={
            'balkon': {
                'address': assistant.address,
                'protocol': 'homeassistant',
                'token': simulate.HA_TOKEN,
                'entities': ', '.join(OUTDOOR_ENTITIES),
                'interval': '5',
            }
        },
    )
    try:
        assert [one.name for one in driver.stations.values()] == ['balkon']
        got = []

        def pull():
            for packet in driver.genLoopPackets():
                got.append(packet)
                return

        reader = threading.Thread(target=pull, daemon=True)
        reader.start()
        reader.join(20)
        assert got, "nothing came out of the driver"
        packet = got[0]
        assert packet['station'] == 'balkon'
        # Celsius, millibars and metres a second, which is what METRICWX is and what
        # every reading was converted to on the way in.
        assert packet['usUnits'] == 17
        wanted = expected(assistant)
        assert packet['outTemp'] == pytest.approx(wanted['temperature'])
        assert packet['outHumidity'] == pytest.approx(wanted['humidity'])
        assert packet['pressure'] == pytest.approx(wanted['atmospheric_pressure'])
        # Home Assistant sent kilometres an hour and WeeWX keeps this column in
        # metres a second. A driver that did not convert would be out by 3.6 and
        # would look right.
        assert packet['windSpeed'] == pytest.approx(wanted['wind_speed'])
        # The three that are not readings reached nothing.
        assert 'batteryPercent' not in packet
        assert 'illuminance' not in packet
        # And the second temperature on the device did not take the first one's
        # column, which is what would happen if a catalog placed both.
        assert packet['outTemp'] != pytest.approx(wanted['temperature_2'])
    finally:
        driver.closePort()


def test_naming_home_assistant_under_polling_switches_it_on(assistant, tmp_path):
    pytest.importorskip('weewx', reason="WeeWX is not installed")
    from ultimatepush.driver import UltimatePushDriver

    driver = UltimatePushDriver(
        port=0,
        address='127.0.0.1',
        weewx_root=str(tmp_path),
        polling={
            'balkon': {
                'address': assistant.address,
                'protocol': 'homeassistant',
                'token': simulate.HA_TOKEN,
                'entities': 'sensor.balkon_temperatur',
            }
        },
    )
    try:
        assert 'homeassistant' in [one.name for one in driver.enabled]
    finally:
        driver.closePort()


# ---- setting one up through the web interface --------------------------------


@pytest.fixture
def interface(tmp_path):
    """A driver with the web interface on, which is what can add a source."""
    pytest.importorskip('weewx', reason="WeeWX is not installed")
    from ultimatepush.driver import UltimatePushDriver

    made = []

    def _build():
        driver = UltimatePushDriver(
            port=0,
            address='127.0.0.1',
            weewx_root=str(tmp_path),
            web={'enable': 'true', 'port': '0', 'token': 'x' * 12},
        )
        made.append(driver)
        return driver

    yield _build
    for driver in made:
        driver.closePort()


def test_the_interface_offers_what_is_there_and_records_nothing(assistant, interface):
    """Auto-suggest, then choose. Looking writes nothing at all."""
    driver = interface()
    answer = driver.web_discover_polled(
        'homeassistant', address=assistant.address, token=simulate.HA_TOKEN
    )

    assert answer['ok'], answer.get('message')
    assert [one['device'] for one in answer['found']][0] == OUTDOORS['name']
    assert not driver.asking
    assert not driver.overrides.polled()


def test_a_source_chosen_in_the_interface_is_asked_and_set_up(assistant, interface):
    driver = interface()
    ok, message = driver.web_add_polled(
        'homeassistant',
        address=assistant.address,
        token=simulate.HA_TOKEN,
        entities=OUTDOOR_ENTITIES,
        name='balkon',
    )

    assert ok, message
    assert 'balkon' in driver.asking
    assert [one.name for one in driver.stations.values()] == ['balkon']
    # The token is written where the interface writes its settings, because a
    # driver cannot write weewx.conf and this is a setting like any other.
    assert driver.overrides.polled()['balkon']['token'] == simulate.HA_TOKEN


def test_nothing_chosen_is_refused_rather_than_set_up_reading_nothing(
    assistant, interface
):
    """A source with no entities would answer nothing every minute for ever and
    look like a station that is working."""
    driver = interface()
    ok, message = driver.web_add_polled(
        'homeassistant', address=assistant.address, token=simulate.HA_TOKEN
    )

    assert not ok
    assert 'chosen' in message
    assert not driver.asking


def test_a_wrong_token_is_refused_before_anything_is_saved(assistant, interface):
    driver = interface()
    ok, message = driver.web_add_polled(
        'homeassistant',
        address=assistant.address,
        token='the-wrong-one',
        entities=OUTDOOR_ENTITIES,
    )

    assert not ok
    assert not driver.asking
    assert not driver.overrides.polled()


def test_the_token_is_not_in_what_the_interface_sends_back(assistant, interface):
    """The page shows the raw uploads, and a source's answer is one of them."""
    driver = interface()
    assert driver.web_add_polled(
        'homeassistant',
        address=assistant.address,
        token=simulate.HA_TOKEN,
        entities=OUTDOOR_ENTITIES,
        name='balkon',
    )[0]

    shown = json.dumps(driver.web_ways())
    assert simulate.HA_TOKEN not in shown


# ---- the Home Assistant that is not there ------------------------------------


def test_the_fake_refuses_a_request_with_no_token():
    """The way the real one does. A fake that answered anybody would let a driver
    that forgot the header pass every test here."""
    import urllib.error
    import urllib.request

    assistant = Assistant()
    try:
        with pytest.raises(urllib.error.HTTPError) as refused:
            urllib.request.urlopen(
                'http://%s/api/states/sensor.balkon_temperatur' % assistant.address,
                timeout=5,
            )
    finally:
        assistant.close()

    assert refused.value.code == 401


def test_the_fake_has_the_three_states_that_are_not_readings():
    """They are the reason it exists rather than a fixture. Without them nothing
    here exercises the code that tells a missing reading from a zero."""
    states = [
        simulate.homeassistant_state(entity_id, AT)
        for _, entity in simulate.homeassistant_entities()
        for entity_id in [entity['entity_id']]
    ]
    said = [one['state'] for one in states]

    assert 'unavailable' in said
    assert 'unknown' in said
    behind = [
        one
        for _, one in simulate.homeassistant_entities()
        if one.get('behind', 0.0) >= 3600.0
    ]
    assert behind, "nothing in the fake is answering with an old reading"


def test_the_fake_has_two_devices_one_indoors_and_one_outdoors():
    assert len(simulate.HA_DEVICES) == 2
    assert OUTDOORS['name'] != INDOORS['name']
    assert OUTDOORS['id'] != INDOORS['id']


def test_the_fake_moves():
    """A flat line tells nobody whether their graphs are working."""
    first = simulate.homeassistant_state('sensor.balkon_temperatur', AT)
    later = simulate.homeassistant_state('sensor.balkon_temperatur', AT + 300.0)

    assert first['state'] != later['state']
    # And the same moment twice is the same answer, or no test could use it.
    assert (
        simulate.homeassistant_state('sensor.balkon_temperatur', AT)['state']
        == first['state']
    )


def test_the_fake_stays_within_reason():
    """Readings a person would believe, at every moment of a day."""
    for step in range(0, 86400, 337):
        state = simulate.homeassistant_state('sensor.balkon_temperatur', AT + step)
        assert -10.0 <= float(state['state']) <= 40.0
        wet = simulate.homeassistant_state('sensor.balkon_luftfeuchte', AT + step)
        assert 0.0 <= float(wet['state']) <= 100.0


def test_the_fake_answers_the_template_with_the_device_map():
    """The one endpoint that is not a state. The real one renders the template; this
    answers what rendering it would have produced."""
    from ultimatepush.protocols.homeassistant import _device_template

    template = _device_template(['sensor.balkon_temperatur', 'sensor.nowhere'])
    # Every entity the template asks about is in the answer, including one no
    # device claims, which renders as nulls rather than being left out.
    rendered = simulate.homeassistant_devices(
        ['sensor.balkon_temperatur', 'sensor.nowhere']
    )

    assert 'sensor.balkon_temperatur' in template
    assert rendered['sensor.balkon_temperatur']['id'] == OUTDOORS['id']
    assert rendered['sensor.nowhere']['id'] is None


def test_the_command_line_offers_the_fake(capsys):
    """Beside the other three. It is what the documentation tells somebody to run
    before their sensor arrives, so it has to be there."""
    pytest.importorskip('weewx', reason="WeeWX is not installed")
    from ultimatepush import __main__

    with pytest.raises(SystemExit):
        __main__.main(['--help'])

    assert '--fake-homeassistant' in capsys.readouterr().out
    assert hasattr(simulate, 'serve_homeassistant')
