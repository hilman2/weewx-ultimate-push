#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""Cheap radio sensors, by way of rtl_433.

No stick and no radio: the messages here are what rtl_433 puts on a socket, sent
over the loopback by the simulator this driver ships.

Two things are being checked over and over. That a unit is read out of the field
name rather than out of any knowledge about a device, which is what keeps this
catalog short. And that nothing overheard becomes a station on its own, which is
what stops next door's thermometer from becoming somebody's main station.
"""

import json
import socket
import threading
import time

import pytest

from ultimatepush import simulate, transport
from ultimatepush.protocols import rtl433
from ultimatepush.protocols.rtl433 import Rtl433

# One message, as it arrives: an RFC 5424 syslog frame with the reading on the end.
# rtl_433 has no other UDP output, so this shape is not optional.
FRAMED = (
    '<165>1 2026-08-30T19:04:12Z pi rtl_433 - - - '
    '{"time":"2026-08-30 19:04:12","protocol":40,"model":"Acurite-Tower",'
    '"id":11524,"channel":"A","battery_ok":1,"temperature_F":71.6,'
    '"humidity":44,"mic":"CHECKSUM"}'
)

AT = 1788121515.0


def read(raw):
    """A message, converted and placed, as the driver would.

    Args:
        raw (dict): What rtl_433 sent.

    Returns:
        dict: The WeeWX fields.
    """
    from ultimatepush.mapping import Mapper

    packet, _ = Mapper(Rtl433.dialect(raw)).to_packet(Rtl433.readings(None, raw))
    return packet


# ---- what arrives -----------------------------------------------------------


def test_a_message_inside_a_syslog_frame_is_read():
    """The frame is stepped over rather than parsed: nothing in it is wanted."""
    raw = transport.parse(FRAMED)
    assert raw['model'] == 'Acurite-Tower'
    assert raw['temperature_F'] == 71.6


def test_a_frame_with_no_reading_in_it_is_not_mistaken_for_one():
    assert transport.parse('<165>1 2026-08-30T19:04:12Z pi rtl_433 - - - ') == {}


def test_a_bare_json_datagram_still_works():
    """A WeatherFlow hub sends one, and it must not be caught by the frame rule."""
    assert transport.parse('{"type":"obs_st","serial_number":"ST-1"}')['type'] == (
        'obs_st'
    )


def test_this_protocol_claims_it():
    from ultimatepush import protocols

    raw = transport.parse(FRAMED)
    assert protocols.detect(None, raw, protocols.registry()) is Rtl433


def test_how_sure_it_is_depends_on_what_arrived():
    """A model and a decoder number together are as good as a signature.

    A model on its own is claimed, but weakly: nothing else this driver reads sends
    one at all, so it is still the best answer, and a protocol that recognises
    itself precisely should outrank it if one ever does.
    """
    assert Rtl433.claims(None, {'model': 'x', 'protocol': 40}) == 5
    # An older rtl_433, or one told to leave the decoder number out.
    assert Rtl433.claims(None, {'model': 'x', 'mic': 'CRC'}) == 5
    assert Rtl433.claims(None, {'model': 'x'}) == 2
    assert Rtl433.claims(None, {'temperature_C': 21.0}) == 0


# ---- one sensor from the next -----------------------------------------------


def test_a_sensor_is_named_by_what_makes_it_that_sensor():
    """No one field names a sensor: a receiver hears several of the same model."""
    assert Rtl433.station_of(transport.parse(FRAMED)) == 'Acurite-Tower/11524/A'


def test_a_sensor_that_sends_less_is_still_told_apart():
    assert Rtl433.station_of({'model': 'Nexus-TH', 'id': 57}) == 'Nexus-TH/57'
    assert Rtl433.station_of({'model': 'Rain-1'}) == 'Rain-1'
    assert Rtl433.station_of({'id': 57}) == ''


def test_a_channel_of_zero_still_counts():
    """Falsy and meaningful. Two sensors differ by exactly this."""
    assert Rtl433.station_of({'model': 'B', 'id': 1, 'channel': 0}) == 'B/1/0'


# ---- units come out of the name ---------------------------------------------


def test_fahrenheit_becomes_celsius():
    """The one conversion a per-field scale cannot do, because it has an offset."""
    assert read({'model': 'x', 'temperature_F': 71.6})['outTemp'] == pytest.approx(22.0)


def test_every_wind_unit_lands_in_metres_per_second():
    assert read({'model': 'x', 'wind_avg_km_h': 18.0})['windSpeed'] == pytest.approx(
        5.0
    )
    assert read({'model': 'x', 'wind_avg_m_s': 5.0})['windSpeed'] == pytest.approx(5.0)
    assert read({'model': 'x', 'wind_avg_mi_h': 10.0})['windSpeed'] == pytest.approx(
        4.4704
    )


def test_every_pressure_unit_lands_in_millibars():
    assert read({'model': 'x', 'pressure_kPa': 101.32})['pressure'] == pytest.approx(
        1013.2
    )
    assert read({'model': 'x', 'pressure_hPa': 1013.2})['pressure'] == pytest.approx(
        1013.2
    )


def test_rain_lands_in_millimetres():
    assert read({'model': 'x', 'rain_in': 2.0})['dayRain'] == pytest.approx(50.8)
    assert read({'model': 'x', 'rain_rate_in_h': 1.0})['rainRate'] == pytest.approx(
        25.4
    )


def test_a_rain_rate_is_not_read_as_a_total():
    """'_in_h' ends with '_in'. Getting the order wrong is silent and wrong."""
    named = Rtl433.readings(None, {'model': 'x', 'rain_rate_in_h': 1.0})
    assert 'rain_rate_mm_h' in named
    assert 'rain_rate_in_mm' not in named


def test_a_reading_sent_as_text_is_left_alone():
    """The raw uploads page has to show what arrived, whatever it was."""
    named = Rtl433.readings(None, {'model': 'x', 'temperature_F': 'n/a'})
    assert named['temperature_F'] == 'n/a'


def test_a_name_with_no_unit_in_it_is_untouched():
    named = Rtl433.readings(None, {'model': 'x', 'humidity': 44})
    assert named == {'model': 'x', 'humidity': 44}


def test_the_battery_flag_is_turned_round():
    """rtl_433 sends 1 for a good battery. This column is a fault flag."""
    assert read({'model': 'x', 'battery_ok': 1})['txBatteryStatus'] == 0
    assert read({'model': 'x', 'battery_ok': 0})['txBatteryStatus'] == 1


def test_what_names_a_sensor_is_not_recorded_as_a_reading():
    """It says which sensor sent the message. It measures nothing."""
    packet = read(transport.parse(FRAMED))
    assert set(packet) == {'dateTime', 'outTemp', 'outHumidity', 'txBatteryStatus'}


# ---- nothing overheard becomes a station ------------------------------------


def test_this_protocol_says_it_overhears():
    """The whole of why a receiver behaves differently from a console."""
    assert Rtl433.overhears is True


def test_everything_else_was_pointed_here():
    """A console had an address typed into it, so its first upload is its owner's."""
    from ultimatepush import protocols

    overhearing = [one.name for one in protocols.registry() if one.overhears]
    assert overhearing == ['rtl433']


def a_free_udp_port():
    """A port nothing is on."""
    held = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        held.bind(('127.0.0.1', 0))
        return held.getsockname()[1]
    finally:
        held.close()


@pytest.fixture
def receiver(tmp_path):
    """A driver listening for rtl_433, with whatever stations the test wants."""
    pytest.importorskip('weewx', reason="WeeWX is not installed")
    from ultimatepush.driver import UltimatePushDriver

    made = []

    def _build(**stanzas):
        driver = UltimatePushDriver(
            port=0,
            address='127.0.0.1',
            weewx_root=str(tmp_path),
            protocols='rtl433',
            udp_port=0,
            **stanzas,
        )
        made.append(driver)
        return driver

    yield _build
    for driver in made:
        driver.closePort()


def keep_sending(port, stop):
    """Send what the receiver would hear, until the test has what it wanted."""
    while not stop.is_set():
        simulate.send_rtl433(port, rounds=1)
        stop.wait(0.3)


def packets_from(driver, port, count, seconds=20):
    """Take a few loop packets while the pretend receiver talks.

    Args:
        driver (ultimatepush.driver.UltimatePushDriver): The driver.
        port (int): Where it is listening.
        count (int): How many packets to wait for.
        seconds (float): How long to wait.

    Returns:
        list[dict]: What came out, which may be fewer than asked for.
    """
    got = []
    stop = threading.Event()
    loop = driver.genLoopPackets()

    def pull():
        for packet in loop:
            got.append(packet)
            if len(got) >= count:
                return

    reader = threading.Thread(target=pull, daemon=True)
    sender = threading.Thread(target=keep_sending, args=(port, stop), daemon=True)
    reader.start()
    sender.start()
    reader.join(seconds)
    stop.set()
    sender.join(5)
    return list(got)


def udp_port_of(driver):
    """Which port the driver's datagram listener ended up on."""
    ports = [port for port in driver.listener.ports if port]
    return ports[-1]


def test_the_first_sensor_heard_does_not_become_the_main_station(receiver, caplog):
    """The point of the whole thing.

    A console was pointed here, so its first upload is its owner's. A receiver was
    pointed at nothing: it hears whatever transmits nearby, and the first thing it
    hears is as likely to be next door's thermometer. Nothing is recorded until
    somebody says which of them are theirs.
    """
    driver = receiver()
    got = packets_from(driver, udp_port_of(driver), 1, seconds=6)
    assert got == [], "something was recorded before anything was let in"
    said = ' '.join(one.getMessage() for one in caplog.records)
    for sensor in ('Acurite-Tower', 'Bresser-6in1', 'Nexus-TH'):
        assert sensor in said, "%s was not offered to be let in" % sensor


def test_the_sensors_that_were_let_in_are_the_ones_recorded(receiver, caplog):
    """Two of the three are this installation's. The third is a neighbour's."""
    driver = receiver(
        stations={
            'garden': {'id': 'Bresser-6in1/8455/0'},
            'shed': {'id': 'Acurite-Tower/11524/A', 'role': 'extra', 'channel': '2'},
        }
    )
    got = packets_from(driver, udp_port_of(driver), 4)
    assert got, "nothing was recorded"
    seen = {packet.get('station') for packet in got}
    assert seen <= {'garden', 'shed'}
    assert 'garden' in seen

    main = [one for one in got if one.get('station') == 'garden']
    assert main, "the main station recorded nothing"
    packet = main[0]
    assert packet['usUnits'] == 17
    for field in ('outTemp', 'outHumidity', 'windSpeed', 'windDir', 'dayRain'):
        assert field in packet, field
    # A rain gauge counts up from the day its battery went in, and that is what
    # StdDelta differences. A believable count, not the unix clock.
    assert 0 < packet['dayRain'] < 10000

    extra = [one for one in got if one.get('station') == 'shed']
    if extra:
        assert 'extraTemp2' in extra[0]
        assert 'outTemp' not in extra[0]

    said = ' '.join(one.getMessage() for one in caplog.records)
    assert 'Nexus-TH' in said, "the neighbour was not mentioned at all"


# ---- what the simulator sends -----------------------------------------------


def test_the_simulator_sends_what_this_protocol_reads():
    """Otherwise it proves nothing about the real path."""
    for message in simulate.rtl433_messages(AT):
        raw = transport.parse(message.decode('utf-8'))
        assert Rtl433.claims(None, raw) == 5
        assert Rtl433.station_of(raw)


def test_the_simulator_hears_somebody_else_too():
    """On purpose. Letting in the ones that are yours is the part worth trying."""
    heard = {
        Rtl433.station_of(transport.parse(one.decode('utf-8')))
        for one in simulate.rtl433_messages(AT)
    }
    assert len(heard) == 3


def test_the_pretend_rain_gauge_only_counts_up():
    """A counter that goes backwards makes StdDelta record a day of rain at once."""
    was = None
    for step in range(0, 86400, 900):
        messages = simulate.rtl433_messages(AT + step)
        gauge = [
            transport.parse(one.decode('utf-8'))
            for one in messages
            if 'rain_mm' in transport.parse(one.decode('utf-8'))
        ][0]
        now = gauge['rain_mm']
        assert 0 < now < 10000, now
        if was is not None:
            assert now >= was
        was = now


def test_the_pretend_sensors_stay_within_reason():
    for step in range(0, 86400, 331):
        for message in simulate.rtl433_messages(AT + step):
            raw = transport.parse(message.decode('utf-8'))
            if 'temperature_C' in raw:
                assert -20 <= raw['temperature_C'] <= 45
            if 'humidity' in raw:
                assert 0 <= raw['humidity'] <= 100
            if 'wind_avg_m_s' in raw:
                assert 0 <= raw['wind_avg_m_s'] <= 40
            if 'wind_dir_deg' in raw:
                assert 0 <= raw['wind_dir_deg'] <= 360


def test_the_port_it_listens_on_is_the_one_it_tells_people_to_use():
    """The note says where to send. A different number there would be a bug."""
    assert Rtl433.default_port == rtl433.DEFAULT_PORT
    assert str(rtl433.DEFAULT_PORT) in ' '.join(Rtl433.notes)


# ---- a sensor that changed its number ---------------------------------------


def test_a_station_can_be_moved_onto_the_id_a_battery_change_gave_it(tmp_path):
    """The whole point: the sensor is the same one and keeps what it had.

    rtl_433's own documentation says an id may be chosen afresh at each power on.
    When that happens the sensor turns up looking new, and letting it in as a second
    station would leave its name, its channel and its columns behind with a number
    nothing will ever send again.
    """
    pytest.importorskip('weewx', reason="WeeWX is not installed")
    from ultimatepush.driver import UltimatePushDriver

    driver = UltimatePushDriver(
        port=0,
        address='127.0.0.1',
        weewx_root=str(tmp_path),
        protocols='rtl433',
        udp_port=0,
        web={
            'enable': 'true',
            'port': 0,
            'address': '127.0.0.1',
            'token': 'a-token-long-enough',
        },
    )
    try:
        was = 'Nexus-TH/57/1'
        now = 'Nexus-TH/198/1'
        # The way one of these comes into being: it was heard, it was refused, and
        # somebody said it was theirs. There is nothing to set up in advance,
        # because the hardware cannot be told what to call itself.
        ok, message = driver.web_accept(was, name='shed')
        assert ok, message
        assert was in driver.web_stations

        driver.owners.claim('outTemp', was, is_main=False)
        driver.overrides.set_column('outTemp', was)

        ok, message = driver.web_rebind(was, now)
        assert ok, message
        assert now in driver.web_stations
        assert was not in driver.web_stations
        # The name went with it.
        assert driver.web_stations[now].name == 'shed'
        # And so did the column, which is the part that cannot be got back.
        assert driver.owners.owner('outTemp') == now
        assert driver.overrides.columns()['outTemp'] == now
    finally:
        driver.closePort()


def test_a_station_cannot_be_moved_onto_one_that_is_already_there(tmp_path):
    pytest.importorskip('weewx', reason="WeeWX is not installed")
    from ultimatepush.driver import UltimatePushDriver

    driver = UltimatePushDriver(
        port=0,
        address='127.0.0.1',
        weewx_root=str(tmp_path),
        protocols='rtl433',
        udp_port=0,
        stations={'garden': {'id': 'Bresser-6in1/8455/0'}},
    )
    try:
        ok, message = driver.web_rebind('Bresser-6in1/8455/0', 'Nexus-TH/57/1')
        assert not ok
        # weewx.conf names it, so that file decides what it is called.
        assert 'weewx.conf' in message

        ok, message = driver.web_rebind('nothing/1', 'Nexus-TH/57/1')
        assert not ok
        assert 'no station' in message

        ok, message = driver.web_rebind('a/1', 'a/1')
        assert not ok
        assert 'same' in message
    finally:
        driver.closePort()


# ---- a receiver hears the neighbours ----------------------------------------


def test_the_waiting_list_survives_thirty_things_talking_at_once(receiver):
    """A console needs a list of the last few uploads. A radio does not.

    Twenty uploads spread over thirty talkers means the sensor somebody is looking
    for has already fallen off the end. The tally is kept per station as uploads
    arrive, so nothing is lost however busy the air is.
    """
    from ultimatepush.activity import Log, Upload

    log = Log()
    for round_ in range(40):
        for which in range(30):
            log.refused(
                Upload(
                    at=1788121515.0 + round_,
                    client='127.0.0.1',
                    method='',
                    path='/',
                    text='',
                    ident='Sensor-%d' % which,
                    protocol='rtl433',
                    dialect='',
                    packet={},
                )
            )
    waiting = log.unknown_stations(lambda text: text)
    assert len(waiting) == 30, "a station fell off the list"
    assert all(row['uploads'] == 40 for row in waiting)


def test_the_one_heard_most_often_is_offered_first(receiver):
    """A sensor of yours transmits on a schedule. A car goes past once."""
    from ultimatepush.activity import Log, Upload

    def heard(ident, times):
        for _ in range(times):
            log.refused(
                Upload(
                    at=1788121515.0,
                    client='127.0.0.1',
                    method='',
                    path='/',
                    text='',
                    ident=ident,
                    protocol='rtl433',
                    dialect='',
                    packet={},
                )
            )

    log = Log()
    heard('Passing-Car/1', 1)
    heard('Mine/57/1', 60)
    heard('NextDoor/12/2', 9)
    assert [row['ident'] for row in log.unknown_stations(lambda t: t)] == [
        'Mine/57/1',
        'NextDoor/12/2',
        'Passing-Car/1',
    ]


def test_a_sensor_that_is_not_mine_stops_being_asked_about(tmp_path):
    """Refused either way. What stops is being asked about it every minute."""
    pytest.importorskip('weewx', reason="WeeWX is not installed")
    from ultimatepush.driver import UltimatePushDriver
    from ultimatepush.activity import Upload

    driver = UltimatePushDriver(
        port=0,
        address='127.0.0.1',
        weewx_root=str(tmp_path),
        protocols='rtl433',
        udp_port=0,
    )
    try:
        for ident in ('Mine/57/1', 'NextDoor/12/2'):
            driver.activity.refused(
                Upload(
                    at=1788121515.0,
                    client='127.0.0.1',
                    method='',
                    path='/',
                    text='',
                    ident=ident,
                    protocol='rtl433',
                    dialect='',
                    packet={},
                )
            )
        assert len(driver.web_waiting()) == 2

        ok, message = driver.web_ignore('NextDoor/12/2')
        assert ok, message
        assert [row['ident'] for row in driver.web_waiting()] == ['Mine/57/1']
        # And it stays said.
        assert driver.overrides.ignored() == ['NextDoor/12/2']

        ok, message = driver.web_ignore('NextDoor/12/2', yes=False)
        assert ok, message
        assert driver.overrides.ignored() == []
    finally:
        driver.closePort()


def test_a_station_of_this_driver_s_own_cannot_be_set_aside(tmp_path):
    """Taking it out is the thing to do, and it says so."""
    pytest.importorskip('weewx', reason="WeeWX is not installed")
    from ultimatepush.driver import UltimatePushDriver

    driver = UltimatePushDriver(
        port=0,
        address='127.0.0.1',
        weewx_root=str(tmp_path),
        protocols='rtl433',
        udp_port=0,
        stations={'garden': {'id': 'Bresser-6in1/8455/0'}},
    )
    try:
        ok, message = driver.web_ignore('Bresser-6in1/8455/0')
        assert not ok
        assert 'Take it out' in message
    finally:
        driver.closePort()
