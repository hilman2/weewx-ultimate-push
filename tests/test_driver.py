#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""Drive the whole thing: a real upload in, a loop packet out.

Needs WeeWX installed. Everything below this level is tested without it.
"""

import http.client
import os

import pytest

from helpers import FakeRequest

FIXTURE_PASSKEY = '0000000000000000000000000000AAAA'

weewx = pytest.importorskip('weewx', reason="WeeWX is not installed")

from ultimatepush.driver import UltimatePushDriver  # noqa: E402  (after the skip)


# A WN34 channel goes nowhere until somebody says where. These tests say.
PLACED = {'tf_ch1': 'extraTemp9', 'tf_ch2': 'extraTemp10'}


@pytest.fixture
def driver():
    made = UltimatePushDriver(port=0, address='127.0.0.1', passkey=FIXTURE_PASSKEY, field_map_extensions=PLACED)
    yield made
    made.closePort()


def upload(driver, body):
    connection = http.client.HTTPConnection('127.0.0.1', driver.listener.port, timeout=5)
    try:
        connection.request('POST', '/', body)
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


def test_an_upload_becomes_a_loop_packet(driver, payload):
    status, answer = upload(driver, payload('hp2561ae_pro'))

    assert status == 200
    # The gateway counts the upload as failed until it has read this.
    assert answer == b'{"errcode":"0","errmsg":"ok"}'

    packet = next(driver.genLoopPackets())
    assert packet['usUnits'] == weewx.US
    assert packet['outTemp'] == 59.7
    assert packet['extraTemp9'] == 66.2
    assert packet['lightning_distance'] == 1.0
    assert packet['dateTime'] > 0


def test_new_fields_reach_the_unit_system(payload):
    """A new field is no use in a report if WeeWX does not know what it is.

    A seventeenth soil channel is past what Ecowitt publishes, so it takes
    infer_unknown = all. Which is exactly when somebody would set that.
    """
    import weewx.units

    made = UltimatePushDriver(port=0, address='127.0.0.1', passkey=FIXTURE_PASSKEY, infer_unknown='all',
                         field_map_extensions=PLACED)
    try:
        upload(made, 'PASSKEY=%s&soilmoisture17=30&tempf=59.7' % FIXTURE_PASSKEY)
        packet = next(made.genLoopPackets())
    finally:
        made.closePort()

    assert packet['soilMoist17'] == 30.0
    assert weewx.units.obs_group_dict['soilMoist17'] == 'group_percent'


def test_an_empty_upload_yields_no_packet(driver):
    """Probes and health checks are answered, then ignored."""
    upload(driver, 'PASSKEY=%s&' % FIXTURE_PASSKEY)
    upload(driver, 'PASSKEY=%s&tempf=59.7' % FIXTURE_PASSKEY)

    packet = next(driver.genLoopPackets())
    assert packet['outTemp'] == 59.7


def test_the_hardware_name_is_configurable():
    made = UltimatePushDriver(port=0, address='127.0.0.1', passkey=FIXTURE_PASSKEY, model='HP2561AE Pro')
    try:
        assert made.hardware_name == 'HP2561AE Pro'
    finally:
        made.closePort()


def test_the_driver_leaves_a_report(tmp_path, payload):
    """Getting a raw upload should not mean reconfiguring the console."""
    path = str(tmp_path / 'report.txt')
    made = UltimatePushDriver(port=0, address='127.0.0.1', passkey=FIXTURE_PASSKEY, report_file=path)
    try:
        upload(made, payload('hp2561ae_pro'))
        next(made.genLoopPackets())
    finally:
        made.closePort()

    text = open(path, encoding='utf-8').read()
    assert 'PASSKEY=X' in text
    assert 'tempinf=75.4' in text
    assert 'tf_ch1' in text
    assert 'issues/new' in text


def test_the_report_is_written_once(tmp_path, payload):
    path = str(tmp_path / 'report.txt')
    made = UltimatePushDriver(port=0, address='127.0.0.1', passkey=FIXTURE_PASSKEY, report_file=path)
    try:
        upload(made, payload('hp2561ae_pro'))
        next(made.genLoopPackets())
        first = os.path.getmtime(path)
        upload(made, payload('hp2561ae_pro'))
        next(made.genLoopPackets())
    finally:
        made.closePort()

    assert os.path.getmtime(path) == first


def test_reporting_can_be_switched_off(tmp_path, payload):
    path = str(tmp_path / 'report.txt')
    made = UltimatePushDriver(port=0, address='127.0.0.1', passkey=FIXTURE_PASSKEY, report_file='')
    try:
        upload(made, payload('hp2561ae_pro'))
        next(made.genLoopPackets())
    finally:
        made.closePort()

    assert not os.path.exists(path)


def test_a_station_with_nothing_unknown_leaves_no_report(tmp_path):
    path = str(tmp_path / 'report.txt')
    made = UltimatePushDriver(port=0, address='127.0.0.1', passkey=FIXTURE_PASSKEY, report_file=path)
    try:
        upload(made, 'PASSKEY=%s&tempf=59.7&humidity=82' % FIXTURE_PASSKEY)
        next(made.genLoopPackets())
    finally:
        made.closePort()

    assert not os.path.exists(path)


# ------------------------------------------------------- the console's own clock

def test_a_late_upload_keeps_the_time_it_was_taken(payload):
    """A reading held up on the way in still belongs to the minute it was taken.

    Ecowitt consoles with an internet connection set their clock by NTP, so the
    timestamp in the upload is the measurement time even when the upload is late.
    """
    import calendar
    import time

    made = UltimatePushDriver(port=0, address='127.0.0.1', passkey=FIXTURE_PASSKEY,
                         field_map_extensions=PLACED)
    try:
        body = payload('hp2561ae_pro')
        sent = calendar.timegm(time.strptime('2026-08-25 11:06:42',
                                             '%Y-%m-%d %H:%M:%S'))
        _p, _s, mapper, raw = made.reading_for(FakeRequest(body))
        packet, _ = mapper.to_packet(raw, now=sent + 20 * 60)
        assert packet['dateTime'] == sent
    finally:
        made.closePort()


def test_the_clock_window_comes_from_the_configuration(payload):
    """Somebody whose source is slower than an hour says so, and it reaches the map."""
    import calendar
    import time

    made = UltimatePushDriver(port=0, address='127.0.0.1', passkey=FIXTURE_PASSKEY,
                         field_map_extensions=PLACED, max_behind=2 * 86400)
    try:
        body = payload('hp2561ae_pro')
        sent = calendar.timegm(time.strptime('2026-08-25 11:06:42',
                                             '%Y-%m-%d %H:%M:%S'))
        _p, _s, mapper, raw = made.reading_for(FakeRequest(body))
        packet, _ = mapper.to_packet(raw, now=sent + 86400)
        assert packet['dateTime'] == sent
    finally:
        made.closePort()


def test_a_console_whose_clock_is_wrong_falls_back_to_arrival(payload):
    import calendar
    import time

    made = UltimatePushDriver(port=0, address='127.0.0.1', passkey=FIXTURE_PASSKEY,
                         field_map_extensions=PLACED)
    try:
        body = payload('hp2561ae_pro')
        sent = calendar.timegm(time.strptime('2026-08-25 11:06:42',
                                             '%Y-%m-%d %H:%M:%S'))
        arrived = sent + 365 * 86400
        _p, _s, mapper, raw = made.reading_for(FakeRequest(body))
        packet, _ = mapper.to_packet(raw, now=arrived)
        assert packet['dateTime'] == int(arrived)
    finally:
        made.closePort()


# ---------------------------------------------------------------- several protocols


def test_one_port_serves_two_protocols(payload):
    """An Ecowitt gateway and a Weather Underground client, on the same port, in the
    same second. Each has to read the answer its own firmware expects, or it counts
    the upload as failed and eventually stops uploading.
    """
    made = UltimatePushDriver(port=0, address='127.0.0.1', passkey=FIXTURE_PASSKEY,
                              report_file='', field_map_extensions=PLACED)
    try:
        port = made.listener.port
        ecowitt = upload(made, 'PASSKEY=%s&stationtype=GW2000A_V3.1.5&tempf=59.7'
                               '&baromrelin=29.92' % FIXTURE_PASSKEY)
        assert ecowitt == (200, b'{"errcode":"0","errmsg":"ok"}')

        connection = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
        try:
            connection.request(
                'GET', '/weatherstation/updateweatherstation.php?ID=%s&PASSWORD=x'
                       '&tempf=43.3&baromin=29.05&indoortempf=76.5' % FIXTURE_PASSKEY)
            response = connection.getresponse()
            assert (response.status, response.read()) == (200, b'success')
            assert response.getheader('Content-Type') == 'text/plain'
        finally:
            connection.close()

        packets = made.genLoopPackets()
        first, second = next(packets), next(packets)
    finally:
        made.closePort()

    assert first['outTemp'] == 59.7
    assert first['barometer'] == 29.92
    # baromin and indoortempf are in no Ecowitt catalog. Reading the second upload
    # as Ecowitt would have dropped both.
    assert second['outTemp'] == 43.3
    assert second['barometer'] == 29.05
    assert second['inTemp'] == 76.5


def test_a_broadcast_and_a_post_reach_the_same_loop():
    """A WeatherFlow hub on UDP and an Ecowitt gateway on HTTP are two sockets, and
    genLoopPackets iterates one thing."""
    import json
    import socket

    made = UltimatePushDriver(port=0, address='127.0.0.1', udp_port=0,
                              protocols='ecowitt, weatherflow',
                              passkey='HB-00013030', report_file='')
    try:
        assert len(made.listener.ports) == 2
        datagram = json.dumps({
            'serial_number': 'ST-1', 'type': 'obs_st', 'hub_sn': 'HB-00013030',
            'obs': [[1588948614, 0.18, 0.22, 0.27, 144, 6, 1017.57, 22.37, 50.26,
                     328, 0.03, 3, 0.5, 0, 0, 0, 2.41, 1]]})
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.sendto(datagram.encode(), ('127.0.0.1', made.listener.ports[1]))
        finally:
            sock.close()
        packet = next(made.genLoopPackets())
    finally:
        made.closePort()

    assert packet['usUnits'] == weewx.METRICWX
    assert packet['outTemp'] == 22.37
    # Already the amount since the last report, so it is 'rain' and not a counter.
    assert packet['rain'] == 0.5


def test_a_protocol_this_driver_does_not_know_is_refused_at_startup():
    with pytest.raises(ValueError) as caught:
        UltimatePushDriver(port=0, address='127.0.0.1', protocols='davis')

    assert 'davis' in str(caught.value)
    assert 'ecowitt' in str(caught.value)
