#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""An Ecowitt gateway read over its own binary API, rather than waited for.

There is no hardware here and there is none anywhere: everything runs against the
shipped fake gateway, on a port the machine chose, over the loopback.

Two things are being checked over and over.

The first is that a frame this code builds is a frame this code accepts, and that
everything which is not one is refused rather than half read. A binary protocol with
no framing check does not fail; it decodes rubbish into numbers.

The second is offsets. Live data is a stream of an address byte and a value, where
the address says how many bytes the value takes, so a table entry with the wrong
width moves every reading after it and each one still looks like a number. The round
trip below is the only thing that catches that, which is why it goes through every
address rather than a chosen few.
"""

import json
import logging
import socket
import struct
import socketserver
import threading
import time

import pytest

from ultimatepush import polling, simulate, transport
from ultimatepush.protocols import ecowitt_gateway as api
from ultimatepush.protocols.ecowitt_gateway import EcowittGateway

# One fixed moment, so that a test can say what a reading should be. The same one the
# other polled protocols' tests use.
AT = 1788118495.0


class Gateway:
    """A socket that answers like an Ecowitt gateway.

    It reads its requests and builds its answers with the shipped simulator rather
    than with a copy of it, so what a person gets from `--fake-gw1000` and what these
    tests pass against cannot come apart.

    Args:
        answer (Callable[[int, float], bytes] | None): Called as
            ``answer(command, seconds)``. Returns the whole response frame. The
            simulator's when nothing is given.
        hang_up (bool): Whether to close the connection without answering at all,
            which is what something that is not a gateway does.
    """

    def __init__(self, answer=None, hang_up=False):
        self.asked = []
        gateway = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                self.request.settimeout(5.0)
                while True:
                    if hang_up:
                        return
                    try:
                        command = simulate.gw1000_request(self.request)
                    except (OSError, ValueError):
                        return
                    if command is None:
                        return
                    gateway.asked.append(command)
                    said = (answer or simulate.gw1000_answer)(command, AT)
                    if said:
                        try:
                            self.request.sendall(said)
                        except OSError:
                            return

        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

        self.server = Server(('127.0.0.1', 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def address(self):
        return '127.0.0.1:%d' % self.port

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)


@pytest.fixture
def gateway():
    """A gateway answering everything, the way the shipped fake does."""
    made = Gateway()
    yield made
    made.close()


def source_for(address, timeout=5.0):
    """A polled source pointed at an address, as the configuration would make one."""
    return polling.source_for(
        'gw',
        {'address': address, 'protocol': 'ecowitt_gateway', 'timeout': str(timeout)},
    )


# ---- framing ----------------------------------------------------------------


@pytest.mark.parametrize(
    'command',
    [
        api.CMD_READ_STATION_MAC,
        api.CMD_READ_FIRMWARE_VERSION,
        api.CMD_READ_SSSS,
        api.CMD_GW1000_LIVEDATA,
        api.CMD_READ_SENSOR_ID_NEW,
        api.CMD_READ_RAIN,
    ],
)
def test_a_frame_this_builds_is_a_frame_this_accepts(command):
    """Both widths of size field, because that is the one thing not in the bytes."""
    built = api.frame(command, b'\x01\x02\x03', answering=True)

    assert api.payload_of(command, built) == b'\x01\x02\x03'


def test_a_request_carries_a_one_byte_size_whatever_the_answer_carries():
    """The two directions differ, and reading one with the other's rule desynchronises.

    A live-data response says its length in two bytes. The request that asked for it
    says its own in one, like every other request.
    """
    asked = api.frame(api.CMD_GW1000_LIVEDATA)

    assert len(asked) == 5
    assert asked[3] == 3
    assert api.payload_of(api.CMD_GW1000_LIVEDATA, asked, answering=False) == b''


def test_a_frame_with_a_wrong_checksum_is_refused():
    built = bytearray(api.frame(api.CMD_READ_STATION_MAC, b'\x01\x02', answering=True))
    built[-1] ^= 0xFF

    with pytest.raises(ValueError) as raised:
        api.payload_of(api.CMD_READ_STATION_MAC, bytes(built))
    assert 'checksum' in str(raised.value)


def test_a_frame_answering_a_different_command_is_refused():
    """What arrives when a reply turns up out of step, after a retry."""
    built = api.frame(api.CMD_READ_SSSS, b'\x01\x02', answering=True)

    with pytest.raises(ValueError) as raised:
        api.payload_of(api.CMD_READ_STATION_MAC, built)
    assert '0x30' in str(raised.value)


def test_a_truncated_frame_is_refused():
    built = api.frame(api.CMD_GW1000_LIVEDATA, b'\x01\x02\x03\x04', answering=True)

    with pytest.raises(ValueError) as raised:
        api.payload_of(api.CMD_GW1000_LIVEDATA, built[:-3])
    assert 'arrived' in str(raised.value)


def test_a_frame_with_no_header_is_refused():
    with pytest.raises(ValueError) as raised:
        api.payload_of(api.CMD_READ_STATION_MAC, b'GET / HTTP/1.1\r\n')
    assert 'header' in str(raised.value)


def test_a_frame_too_short_to_be_one_is_refused():
    with pytest.raises(ValueError):
        api.payload_of(api.CMD_READ_STATION_MAC, b'\xff\xff\x26')


def test_nothing_about_a_bad_frame_waits_for_anything():
    """Each refusal is arithmetic on bytes in hand, so none of them can block.

    Said with a clock rather than left to the suite's timeout, because 'it did not
    hang' is the assertion and a test that only fails after sixty seconds says the
    wrong thing about why.
    """
    started = time.time()
    for bad in (
        b'',
        b'\xff\xff',
        b'\xff\xff\x27\x00',
        b'\x00' * 64,
        api.frame(api.CMD_READ_SSSS, b'\x01', answering=True),
    ):
        with pytest.raises(ValueError):
            api.payload_of(api.CMD_GW1000_LIVEDATA, bad)
    assert time.time() - started < 1.0


# ---- every field, there and back --------------------------------------------


def names_of(table):
    """Every reading name a table can produce."""
    found = set()
    for shapes in table.values():
        for name, _, _ in shapes:
            if name is not None:
                found.add(name)
    return found


def test_every_live_address_survives_the_round_trip():
    """The test that catches a wrong byte offset, which is otherwise silent.

    Every address at once, in one stream, so that a width that is wrong by a byte
    moves everything after it and shows up rather than being read from its own frame
    where nothing follows it.
    """
    sent = simulate.gw1000_readings(AT)
    every = sorted(api.LIVE)

    got, stopped = api.read_stream(api.write_stream(sent, api.LIVE, every), api.LIVE)

    assert stopped is None, "stopped at 0x%02x" % stopped
    wanted = names_of(api.LIVE)
    assert set(got) == wanted
    # Asserted as a number as well as a set, so that an address added to the table
    # with no reading behind it fails here rather than passing quietly.
    assert len(got) == 147
    for name in sorted(wanted):
        assert got[name] == pytest.approx(sent[name]), name


def test_the_air_quality_index_survives_the_round_trip():
    """The one address whose length is in the stream rather than in the table."""
    sent = simulate.gw1000_readings(AT)

    got, stopped = api.read_stream(
        api.write_stream(sent, api.LIVE, [api.ITEM_PM25_AQI]), api.LIVE
    )

    assert stopped is None
    assert set(got) == set(api.AQI)
    for name in api.AQI:
        assert got[name] == pytest.approx(sent[name])


def test_a_reading_after_the_air_quality_index_is_still_in_the_right_place():
    """Its length is a byte in the stream, so getting it wrong moves what follows."""
    sent = simulate.gw1000_readings(AT)

    got, stopped = api.read_stream(
        api.write_stream(sent, api.LIVE, [api.ITEM_PM25_AQI, 0x02, 0x07]), api.LIVE
    )

    assert stopped is None
    assert got['outtemp'] == pytest.approx(sent['outtemp'])
    assert got['outhumi'] == pytest.approx(sent['outhumi'])


def test_every_rain_address_survives_the_round_trip():
    """A second table, because these are the same addresses at different widths.

    ITEM_RAINDAY is two bytes in a live-data stream and four in this one. One table
    for both would read every gauge on a newer console at half its width.
    """
    sent = simulate.gw1000_readings(AT)

    got, stopped = api.read_stream(api.write_stream(sent, api.RAIN), api.RAIN)

    assert stopped is None
    assert set(got) == names_of(api.RAIN)
    assert len(got) == 27
    for name in sorted(got):
        assert got[name] == pytest.approx(sent[name]), name


def test_the_rain_command_is_not_read_with_the_live_table():
    """The trap the two tables exist for, stated as a test rather than as a comment."""
    assert api.LIVE[0x10] != api.RAIN[0x10]
    live = api.shape_format(api.LIVE[0x10])
    rain = api.shape_format(api.RAIN[0x10])

    assert (live, rain) == ('>H', '>I')


def test_every_field_in_the_catalog_is_one_the_decoders_produce():
    """A field added to the catalog with no decoder behind it is a column never filled."""
    made = names_of(api.LIVE) | names_of(api.RAIN) | set(api.AQI)
    made |= {one + '_batt' for one in api.SENSORS}
    made |= {one + '_sig' for one in api.SENSORS}

    orphans = sorted(set(EcowittGateway.fields) - made - EcowittGateway.metadata)

    assert not orphans, "the catalog places what nothing decodes: %s" % ', '.join(
        orphans
    )
    assert len(EcowittGateway.fields) == 203


def test_every_sensor_says_its_battery_and_its_signal():
    """One record per sensor, and every one of them named."""
    sent = simulate.gw1000_sensors()

    got = api.read_sensors(api.write_sensors(sent))

    assert len(api.SENSORS) == 49
    assert len(got) == 2 * len(api.SENSORS)
    for sensor in api.SENSORS:
        assert got[sensor + '_sig'] == 4.0, sensor
        assert got[sensor + '_batt'] == pytest.approx(
            api.battery_of(sensor, sent[sensor][1])
        ), sensor


def test_a_battery_byte_means_what_that_sensor_says_it_means():
    """Four rules, one per family, and the document gives each of them by name."""
    # Hundredths of a volt on a WH34, and 2.9 V is a good battery.
    assert api.battery_of('wh34_ch1', 145) == pytest.approx(2.9)
    # Tenths of a volt on a WH51.
    assert api.battery_of('wh51_ch3', 16) == pytest.approx(1.6)
    # A flag on a WH65, where 1 means low.
    assert api.battery_of('wh65', 1) == 1.0
    # A level from nought to five on a WH41, left as the level it is.
    assert api.battery_of('wh41_ch2', 5) == 5.0


def test_a_sensor_that_is_not_registered_is_not_reported():
    """0xFFFFFFFF asks the gateway to look for one and 0xFFFFFFFE turns it off.

    Neither is a sensor with anything to say, and a battery reading for one that is
    not there would show as a flat line nobody could account for.
    """
    got = api.read_sensors(
        api.write_sensors(
            {
                'wh65': (0x00C0FFEE, 0, 4),
                'wh68': (0xFFFFFFFF, 0, 0),
                'wh80': (0xFFFFFFFE, 0, 0),
            }
        )
    )

    assert sorted(got) == ['wh65_batt', 'wh65_sig']


# ---- the widths, against the document rather than against the table ----------
#
# The round trip above encodes and decodes with one table, so it cannot tell that
# table is wrong: a width that is too narrow round-trips perfectly until a value
# turns up that will not fit in it. What catches a wrong width is a second statement
# of it that did not come from the code.
#
# This is that statement. Every number below was read off Ecowitt's document, out of
# the byte count it prints beside each ITEM_ in its definition list, and none of it
# was derived from anything in the driver.

# Address to the width the document gives it, grouped by the width and written as the
# address bytes themselves, so that a line here and the document's definition list can
# be read against each other.
DOCUMENTED = {
    1: bytes.fromhex(
        '06 07 17 22 23 24 25 26 27 28 29 2C 2E 30 32 34 36 38 3A 3C 3E 40'
        '42 44 46 48 4A 58 59 5A 5B 60 72 73 74 75 76 77 78 79 7A 7B'
    ),
    2: bytes.fromhex(
        '01 02 03 04 05 08 09 0A 0B 0C 0D 0E 0F 10 11 16 19 1A 1B 1C 1D 1E'
        '1F 20 21 2A 2B 2D 2F 31 33 35 37 39 3B 3D 3F 41 43 45 47 49 4D 4E'
        '4F 50 51 52 53 80 81 82'
    ),
    3: bytes.fromhex('63 64 65 66 67 68 69 6A 88'),
    4: bytes.fromhex('12 13 14 15 61 62 6C 83 84 85 86'),
    6: bytes.fromhex('18'),
    16: bytes.fromhex('4C 70'),
    20: bytes.fromhex('87'),
}

# The one address the document gives no byte count for. It says instead that a WH46
# is "ITEM_SENSOR_CO2 + pm1 + pm4", which is the WH45's sixteen bytes and four more
# readings of two, and the response table beside CMD_GW1000_LIVEDATA lists all
# thirteen of them in order.
WH46_IS_DERIVED = 24

# What the document's CMD_READ_RAIN response table gives, which is a different set of
# widths for some of the same addresses. This is the transcription that matters most:
# it is the only place the two tables can be held apart by something outside the code.
DOCUMENTED_RAIN = {
    0x0E: 2,
    0x0F: 2,
    0x0D: 2,
    0x10: 4,
    0x11: 4,
    0x12: 4,
    0x13: 4,
    0x7A: 1,
    0x80: 2,
    0x81: 2,
    0x83: 4,
    0x84: 4,
    0x85: 4,
    0x86: 4,
    0x87: 20,
    0x88: 3,
}


def documented_widths():
    """The document's byte count per address, flattened."""
    return {
        address: width
        for width, addresses in DOCUMENTED.items()
        for address in addresses
    }


def test_every_live_address_is_as_wide_as_the_document_says():
    """The check the round trip cannot make, because it is not the same source.

    A width that is one too narrow moves every reading after it, and encoding and
    decoding with one table hides that: both halves agree, and the numbers still come
    back. Only a second statement of the width catches it, and this is that.
    """
    said = documented_widths()
    said[0x6B] = WH46_IS_DERIVED

    wrong = []
    for address, shapes in sorted(api.LIVE.items()):
        mine = struct.calcsize(api.shape_format(shapes))
        if said.get(address) != mine:
            wrong.append(
                '0x%02X is %d bytes here and %s in the document'
                % (address, mine, said.get(address))
            )

    assert not wrong, '; '.join(wrong)
    # And nothing the document lists is missing, so an address that arrives is one
    # the table can step over rather than one it has to stop at.
    assert sorted(api.LIVE) == sorted(said)


def test_every_rain_address_is_as_wide_as_the_rain_table_says():
    """The other table, against the other page of the document.

    Six of these addresses are in the live-data table at a different width. That is
    the trap this whole second table exists for, and this is the assertion that the
    two were not transcribed from one another.
    """
    wrong = []
    for address, shapes in sorted(api.RAIN.items()):
        mine = struct.calcsize(api.shape_format(shapes))
        if DOCUMENTED_RAIN.get(address) != mine:
            wrong.append(
                '0x%02X is %d bytes here and %s in the document'
                % (address, mine, DOCUMENTED_RAIN.get(address))
            )

    assert not wrong, '; '.join(wrong)
    assert sorted(api.RAIN) == sorted(DOCUMENTED_RAIN)


def test_the_two_tables_really_do_disagree():
    """If they ever came to agree, one of the transcriptions was copied from the other."""
    live = documented_widths()
    differ = {
        address
        for address in DOCUMENTED_RAIN
        if address in live and live[address] != DOCUMENTED_RAIN[address]
    }

    assert differ == {0x10, 0x11}


# ---- reading a whole gateway -------------------------------------------------


def test_asking_a_gateway_gives_one_json_body(gateway):
    """Several commands make one reading, which is why the fetcher holds the whole
    conversation rather than asking once."""
    body, headers = api.fetch(source_for(gateway.address))

    assert headers['content-type'] == 'application/json'
    answer = json.loads(body.decode('utf-8'))
    assert answer['gateway']['mac'] == simulate.GW1000_MAC
    assert answer['gateway']['firmware'] == simulate.GW1000_FIRMWARE
    assert answer['gateway']['model'] == 'GW1000'
    # CMD_READ_SSSS, which carries the band and the array and no unit setting.
    assert answer['gateway']['frequency'] == '868MHz'
    assert answer['gateway']['sensor_type'] == 'WH65'
    sent = simulate.gw1000_readings(AT)
    assert answer['readings']['outtemp'] == pytest.approx(sent['outtemp'])
    assert answer['readings']['wh65_sig'] == 4.0
    # Every command, and the rain one too, because a console with a piezo gauge
    # keeps its rain there and nowhere else.
    assert set(gateway.asked) == {
        api.CMD_READ_STATION_MAC,
        api.CMD_READ_FIRMWARE_VERSION,
        api.CMD_READ_SSSS,
        api.CMD_GW1000_LIVEDATA,
        api.CMD_READ_RAIN,
        api.CMD_READ_SENSOR_ID_NEW,
    }


def test_a_gateway_whose_firmware_has_no_rain_command_is_still_read():
    """Older firmware answers nothing at all to CMD_READ_RAIN.

    That is not a failure. Everything such a console has is in the live data already,
    and a driver that gave up here would record nothing from the hardware that is
    most likely to be running old firmware.
    """

    def answer(command, seconds):
        if command == api.CMD_READ_RAIN:
            return b''
        return simulate.gw1000_answer(command, seconds)

    gateway = Gateway(answer=answer)
    try:
        body, _ = api.fetch(source_for(gateway.address, timeout=2.0))
    finally:
        gateway.close()

    readings = json.loads(body.decode('utf-8'))['readings']
    assert readings['rainday'] == pytest.approx(simulate.gw1000_readings(AT)['rainday'])


def test_the_port_does_not_have_to_be_written_down():
    """Ecowitt fixed it, so an address on its own is the whole of what is needed."""
    plain = polling.source_for(
        'gw', {'address': '1.2.3.4', 'protocol': 'ecowitt_gateway'}
    )
    spelled = polling.source_for(
        'gw', {'address': '1.2.3.4:45000', 'protocol': 'ecowitt_gateway'}
    )

    assert plain.url == spelled.url == '1.2.3.4:45000'
    assert api.address_of(plain.url) == ('1.2.3.4', 45000)
    # And the page and the log get the host on its own, not the host and the port.
    assert plain.host == '1.2.3.4'


def test_the_address_is_not_dressed_up_as_a_url():
    """A gateway is not a web server, and http:// in a log sends somebody to a browser."""
    source = polling.source_for(
        'gw', {'address': '1.2.3.4', 'protocol': 'ecowitt_gateway'}
    )

    assert '://' not in source.url


# ---- not the others ----------------------------------------------------------


def test_a_gateway_answer_is_claimed(gateway):
    body, _ = api.fetch(source_for(gateway.address))

    assert EcowittGateway.claims(None, transport.parse(body.decode('utf-8'))) == 5


def test_an_ecowitt_upload_over_http_is_not_claimed(payload):
    """The same hardware, the other way round, and not one field name in common."""
    raw = transport.parse(payload('hp2561ae_pro'))

    assert EcowittGateway.claims(None, raw) == 0
    # And the HTTP protocol still has its own.
    from ultimatepush.protocols.ecowitt import Ecowitt

    assert Ecowitt.claims(None, raw) > 0


def test_the_other_polled_sensors_are_not_claimed():
    assert EcowittGateway.claims(None, simulate.purpleair_answer(AT)) == 0
    assert EcowittGateway.claims(None, simulate.airlink_answer(AT)) == 0


def test_a_wrapper_without_readings_in_it_is_not_claimed():
    """Anything can carry a 'gateway' key. Only the fetcher builds both halves."""
    assert EcowittGateway.claims(None, {'gateway': {'mac': 'AA'}}) == 0
    assert EcowittGateway.claims(None, {'readings': {'outtemp': 1.0}}) == 0
    assert EcowittGateway.claims(None, {'gateway': {}, 'readings': {}}) == 0


def test_the_gateway_names_itself_by_its_mac(gateway):
    body, _ = api.fetch(source_for(gateway.address))
    raw = transport.parse(body.decode('utf-8'))

    assert EcowittGateway.station_of(raw) == simulate.GW1000_MAC


def test_the_answer_is_unwrapped_into_one_flat_set(gateway):
    body, _ = api.fetch(source_for(gateway.address))
    raw = transport.parse(body.decode('utf-8'))

    named = EcowittGateway.readings(None, raw)

    assert 'readings' not in named and 'gateway' not in named
    assert named['outtemp'] == pytest.approx(simulate.gw1000_readings(AT)['outtemp'])
    # What names the gateway comes with the readings, because that is what the page
    # shows beside them.
    assert named['mac'] == simulate.GW1000_MAC


# ---- a gateway that is not there ---------------------------------------------


def test_a_gateway_that_cannot_be_reached_says_so_once(caplog):
    """Once, not once a minute. A console unplugged for a week must not fill a log."""
    with caplog.at_level(logging.WARNING):
        poller = polling.build(
            # Port 1 on the loopback, where nothing listens and the refusal is
            # immediate, so this test waits for nothing.
            {
                'gw': {
                    'address': '127.0.0.1:1',
                    'protocol': 'ecowitt_gateway',
                    'interval': '5',
                    'timeout': '2',
                }
            }
        )
        try:
            assert poller.get(timeout=2) is None
            time.sleep(0.5)
        finally:
            poller.close()

    complaints = [one for one in caplog.records if 'Cannot reach' in one.getMessage()]
    assert len(complaints) == 1, [one.getMessage() for one in complaints]
    assert 'gw' in complaints[0].getMessage()


def test_a_gateway_that_is_away_does_not_hold_up_another(gateway):
    """One thread each, so the one that is answering is still read every interval."""
    poller = polling.build(
        {
            'gw': {
                'address': gateway.address,
                'protocol': 'ecowitt_gateway',
                'interval': '5',
            },
            'gone': {
                'address': '127.0.0.1:1',
                'protocol': 'ecowitt_gateway',
                'interval': '5',
                'timeout': '2',
            },
        }
    )
    try:
        request = poller.get(timeout=10)
    finally:
        poller.close()

    assert request is not None
    assert request.path == '/poll/gw'


def test_something_that_answers_and_says_nothing_is_a_failure_and_not_a_reading():
    """A port that accepts a connection and then closes it, which a firewall does."""
    gateway = Gateway(hang_up=True)
    try:
        with pytest.raises(OSError):
            api.fetch(source_for(gateway.address, timeout=2.0))
    finally:
        gateway.close()


# ---- a gateway that answers rubbish ------------------------------------------


def test_random_bytes_are_refused_rather_than_decoded():
    """Whatever is at that address is not a gateway. Usually the address moved."""
    gateway = Gateway(answer=lambda command, seconds: b'\x17\x2a\x00\x91\xffnonsense')
    try:
        with pytest.raises(ValueError) as raised:
            api.fetch(source_for(gateway.address, timeout=2.0))
    finally:
        gateway.close()
    assert 'header' in str(raised.value)


def test_a_length_no_gateway_would_send_is_refused_without_waiting():
    """A live-data size field claiming 65535, which no reading is.

    It can say that because that size is two bytes wide. A reader that believed it
    would sit waiting on something that is not a gateway for the whole of its
    timeout, once an interval, for as long as that address stays wrong.
    """

    def answer(command, seconds):
        if command != api.CMD_GW1000_LIVEDATA:
            return simulate.gw1000_answer(command, seconds)
        return b'\xff\xff' + bytes([command]) + b'\xff\xff' + b'\x00' * 8

    started = time.time()
    gateway = Gateway(answer=answer)
    try:
        with pytest.raises(ValueError) as raised:
            api.fetch(source_for(gateway.address, timeout=20.0))
    finally:
        gateway.close()

    assert 'not one' in str(raised.value)
    assert time.time() - started < 10.0


def test_an_address_the_table_does_not_know_keeps_what_came_before_it(caplog):
    """A gateway that has gained a sensor since this table was written.

    What was read before it is good. What is after it cannot be: an address is what
    says how many bytes to step over, so there is no way past one nobody knows.
    """
    sent = simulate.gw1000_readings(AT)
    stream = (
        api.write_stream(sent, api.LIVE, [0x02, 0x07])
        + b'\xf3\x01\x02'
        + api.write_stream(sent, api.LIVE, [0x01])
    )

    got, stopped = api.read_stream(stream, api.LIVE)

    assert stopped == 0xF3
    assert got['outtemp'] == pytest.approx(sent['outtemp'])
    assert got['outhumi'] == pytest.approx(sent['outhumi'])
    assert 'intemp' not in got


def test_an_unknown_address_is_complained_about_once(caplog):
    """It arrives every interval, and a line a minute about it is worse than the gap."""
    sent = simulate.gw1000_readings(AT)

    def answer(command, seconds):
        if command != api.CMD_GW1000_LIVEDATA:
            return simulate.gw1000_answer(command, seconds)
        stream = api.write_stream(sent, api.LIVE, [0x02, 0x07]) + b'\xf4\x00'
        return api.frame(command, stream, answering=True)

    api._UNKNOWN.clear()
    gateway = Gateway(answer=answer)
    try:
        with caplog.at_level(logging.WARNING):
            for _ in range(3):
                body, _ = api.fetch(source_for(gateway.address, timeout=5.0))
    finally:
        gateway.close()
        api._UNKNOWN.clear()

    said = [one for one in caplog.records if '0xf4' in one.getMessage()]
    assert len(said) == 1, [one.getMessage() for one in said]
    # And the rest of the reading is kept.
    readings = json.loads(body.decode('utf-8'))['readings']
    assert readings['outtemp'] == pytest.approx(sent['outtemp'])


def test_rubbish_never_raises_out_of_the_source(caplog):
    """The poller sits in the failure. A gateway answering nonsense is a state to be
    in, not an error to take a station down with."""
    gateway = Gateway(answer=lambda command, seconds: b'not a frame at all')
    poller = polling.build(
        {
            'gw': {
                'address': gateway.address,
                'protocol': 'ecowitt_gateway',
                'interval': '5',
                'timeout': '2',
            }
        }
    )
    try:
        with caplog.at_level(logging.WARNING):
            assert poller.get(timeout=3) is None
    finally:
        poller.close()
        gateway.close()

    assert any('Cannot reach' in one.getMessage() for one in caplog.records)


# ---- through the whole driver ------------------------------------------------


def test_a_gateway_records_through_the_whole_driver(gateway, tmp_path):
    """One block of configuration, and a loop packet out of the far end.

    Nothing is set on the console and nothing is adopted: the driver knows which
    gateway answered because it knows which address it asked.
    """
    pytest.importorskip('weewx', reason="WeeWX is not installed")
    from ultimatepush.driver import UltimatePushDriver

    driver = UltimatePushDriver(
        port=0,
        address='127.0.0.1',
        weewx_root=str(tmp_path),
        polling={
            'gw': {
                'address': gateway.address,
                'protocol': 'ecowitt_gateway',
                'interval': '5',
            }
        },
    )
    try:
        assert [one.name for one in driver.stations.values()] == ['gw']
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
        sent = simulate.gw1000_readings(AT)
        assert packet['station'] == 'gw'
        assert packet['outTemp'] == pytest.approx(sent['outtemp'])
        assert packet['outHumidity'] == pytest.approx(sent['outhumi'])
        assert packet['pressure'] == pytest.approx(sent['absbaro'])
        assert packet['windSpeed'] == pytest.approx(sent['windspeed'])
        assert packet['windDir'] == pytest.approx(sent['winddirection'])
        assert packet['dayRain'] == pytest.approx(sent['rainday'])
        # Celsius, hPa, millimetres and metres per second, which is what the API
        # answers in whatever the console's display is set to.
        assert packet['usUnits'] == 17
    finally:
        driver.closePort()


def test_a_gateway_set_up_from_the_page_is_asked_before_it_is_saved(gateway, tmp_path):
    """A wrong address is a message on the page, not an entry to take out again."""
    pytest.importorskip('weewx', reason="WeeWX is not installed")
    from ultimatepush.driver import UltimatePushDriver

    driver = UltimatePushDriver(
        port=0,
        address='127.0.0.1',
        weewx_root=str(tmp_path),
        web={
            'enable': 'true',
            'port': 0,
            'address': '127.0.0.1',
            'token': 'a-token-long-enough',
        },
    )
    try:
        ok, message = driver.web_add_polled(
            'ecowitt_gateway', address=gateway.address, interval='30', name='gw'
        )
        assert ok, message
        assert 'gw' in driver.asking
    finally:
        driver.closePort()


def test_an_address_with_nothing_at_it_is_refused_from_the_page(tmp_path):
    pytest.importorskip('weewx', reason="WeeWX is not installed")
    from ultimatepush.driver import UltimatePushDriver

    driver = UltimatePushDriver(
        port=0,
        address='127.0.0.1',
        weewx_root=str(tmp_path),
        web={
            'enable': 'true',
            'port': 0,
            'address': '127.0.0.1',
            'token': 'a-token-long-enough',
        },
    )
    try:
        ok, message = driver.web_add_polled('ecowitt_gateway', address='127.0.0.1:1')
    finally:
        driver.closePort()

    assert not ok
    assert 'Nothing has been saved' in message


# ---- the gateway that is not there -------------------------------------------


def test_the_simulator_answers_something_the_driver_recognises(gateway):
    """Otherwise it is a fixture that proves nothing about the real path."""
    body, _ = api.fetch(source_for(gateway.address))

    assert EcowittGateway.claims(None, transport.parse(body.decode('utf-8'))) == 5


def test_the_simulator_moves():
    """A flat line tells nobody whether their graphs are working."""
    first = simulate.gw1000_readings(AT)
    later = simulate.gw1000_readings(AT + 300.0)

    assert first['outtemp'] != later['outtemp']
    assert first['windspeed'] != later['windspeed']
    # And the same moment twice is the same answer, or no test here could use it.
    assert simulate.gw1000_readings(AT)['outtemp'] == first['outtemp']


def test_the_simulator_stays_within_reason():
    """Readings a person would believe, at every moment of a day."""
    for step in range(0, 86400, 337):
        said = simulate.gw1000_readings(AT + step)
        assert -20 <= said['outtemp'] <= 45
        assert 0 <= said['outhumi'] <= 100
        assert 950 <= said['absbaro'] <= 1050
        assert 0 <= said['windspeed'] <= 40
        assert 0 <= said['winddirection'] <= 360
        assert 0 <= said['uvi'] <= 15


def test_the_pretend_rain_gauge_only_counts_up():
    """A counter that goes backwards is rain WeeWX records as a whole day of it."""
    was = simulate.gw1000_readings(AT)['rainday']
    for step in range(600, 86400, 3600):
        now = simulate.gw1000_readings(AT + step)['rainday']
        assert now >= was
        was = now


def test_the_simulator_sends_what_the_hardware_can_send():
    """A gateway carries every reading as an integer and a divisor.

    So it cannot report 21.37 degrees, and a fake that did would be exercising the
    decoders against numbers no gateway produces.
    """
    said = simulate.gw1000_readings(AT)

    for address, shapes in api.LIVE.items():
        for name, _, divide in shapes:
            if name is None:
                continue
            assert said[name] * divide == pytest.approx(
                round(said[name] * divide)
            ), name


def test_the_simulator_speaks_to_a_socket():
    """The whole of what --fake-gw1000 does, over a real connection."""
    gateway = Gateway()
    try:
        connection = socket.create_connection(('127.0.0.1', gateway.port), timeout=5.0)
        try:
            connection.sendall(api.frame(api.CMD_READ_STATION_MAC))
            got = connection.recv(64)
        finally:
            connection.close()
    finally:
        gateway.close()

    assert api.read_mac(api.payload_of(api.CMD_READ_STATION_MAC, got)) == (
        simulate.GW1000_MAC
    )
