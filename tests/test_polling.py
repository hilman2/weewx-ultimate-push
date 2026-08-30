#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""Sources this driver asks rather than waits for.

Everything here runs against a web server started in the test, on a port the
machine chose, so there is no hardware and no network beyond the loopback.

The thing being checked over and over is that a polled source is not a new kind of
station. It is a station that happens to be asked, and after the answer is in hand
nothing downstream knows the difference.
"""

import http.server
import json
import logging
import socketserver
import threading
import time

import pytest

from ultimatepush import polling, simulate

# What the shipped simulator answers with, at one fixed moment. The same thing the
# driver is pointed at by somebody trying this without a sensor, so that what is
# tested and what is shipped cannot drift apart.
AT = 1788118495.0
ANSWER = simulate.purpleair_answer(AT)


class Sensor:
    """A web server that answers like a sensor on the network.

    Args:
        body (bytes): What to answer with.
        status (int): The status to answer with.
    """

    def __init__(self, body, status=200):
        self.asked = 0
        sensor = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                sensor.asked += 1
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                """Quiet. The test says what happened, not the server."""

        self.server = socketserver.TCPServer(('127.0.0.1', 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self):
        return 'http://127.0.0.1:%d/json' % self.port

    @property
    def address(self):
        return '127.0.0.1:%d' % self.port

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)


@pytest.fixture
def sensor():
    """A sensor answering with one PurpleAir reading."""
    made = Sensor(json.dumps(ANSWER).encode('utf-8'))
    yield made
    made.close()


@pytest.fixture
def pollers():
    """Build pollers and close them, however the test ends."""
    made = []

    def _build(section):
        poller = polling.build(section)
        if poller is not None:
            made.append(poller)
        return poller

    yield _build
    for poller in made:
        poller.close()


# ---- what a source is -------------------------------------------------------


def test_a_source_is_asked_and_the_answer_arrives(sensor, pollers):
    poller = pollers({'air': {'url': sensor.url, 'interval': '5'}})
    request = poller.get(timeout=10)
    assert request is not None, "nothing came back"
    assert request.path == '/poll/air'
    assert json.loads(request.text)['SensorId'] == ANSWER['SensorId']
    assert request.client_address == '127.0.0.1'


def test_a_poller_holds_no_socket(sensor, pollers):
    """It is shaped like a listener and is not one. The driver prints its ports."""
    assert pollers({'air': {'url': sensor.url}}).port is None


def test_nothing_configured_asks_nothing():
    assert polling.build(None) is None
    assert polling.build({}) is None


def test_an_address_is_enough_when_the_protocol_says_what_to_ask_for(sensor, pollers):
    """Somebody with a PurpleAir knows its address and not that it answers /json."""
    poller = pollers(
        {'air': {'address': sensor.address, 'protocol': 'purpleair', 'interval': '5'}}
    )
    assert poller.sources[0].url == 'http://%s/json' % sensor.address
    assert poller.get(timeout=10) is not None


def test_an_address_with_no_protocol_is_refused():
    with pytest.raises(ValueError) as raised:
        polling.build({'air': {'address': '1.2.3.4'}})
    assert 'protocol' in str(raised.value)


def test_a_source_with_no_address_at_all_is_refused():
    with pytest.raises(ValueError) as raised:
        polling.build({'air': {'interval': '60'}})
    assert "'url'" in str(raised.value)


def test_a_protocol_this_driver_does_not_have_is_refused():
    with pytest.raises(ValueError) as raised:
        polling.build({'air': {'address': '1.2.3.4', 'protocol': 'nonesuch'}})
    assert 'nonesuch' in str(raised.value)
    # The message lists what there is, because the usual cause is a typo.
    assert 'purpleair' in str(raised.value)


def test_a_setting_where_a_source_belongs_is_said_so():
    """A line one level too high, which configobj hands over as a scalar."""
    with pytest.raises(ValueError) as raised:
        polling.build({'interval': '60'})
    assert 'interval' in str(raised.value)


def test_asking_faster_than_this_is_not_allowed(sensor, pollers):
    """A source is somebody's own sensor on their own network, not a load test."""
    poller = pollers({'air': {'url': sensor.url, 'interval': '0.1'}})
    assert poller.sources[0].interval == polling.SHORTEST_INTERVAL


# ---- when it does not answer ------------------------------------------------


def test_a_source_that_cannot_be_reached_says_so_once(pollers, caplog):
    """Once, not once a minute. A sensor away for a week must not fill the log."""
    with caplog.at_level(logging.WARNING):
        poller = pollers(
            # Port 1 on the loopback, where nothing listens and the refusal is
            # immediate, so this test waits for nothing.
            {'air': {'url': 'http://127.0.0.1:1/json', 'interval': '5', 'timeout': '2'}}
        )
        assert poller.get(timeout=2) is None
        time.sleep(0.5)
    complaints = [one for one in caplog.records if 'Cannot reach' in one.getMessage()]
    assert len(complaints) == 1, [one.getMessage() for one in complaints]
    assert 'air' in complaints[0].getMessage()


def test_one_source_that_is_away_does_not_hold_up_another(pollers, sensor):
    """One thread each, so the sensor that is there is still read every interval."""
    poller = pollers(
        {
            'air': {'url': sensor.url, 'interval': '5'},
            'gone': {
                'url': 'http://127.0.0.1:1/json',
                'interval': '5',
                'timeout': '2',
            },
        }
    )
    request = poller.get(timeout=10)
    assert request is not None
    assert request.path == '/poll/air'


def test_an_answer_too_large_to_be_a_reading_is_refused(pollers, caplog):
    """A URL that turns out to be somebody's website, rather than a sensor."""
    big = Sensor(b'x' * (polling.MAX_BODY + 10))
    try:
        with caplog.at_level(logging.WARNING):
            poller = pollers({'air': {'url': big.url, 'interval': '5'}})
            assert poller.get(timeout=5) is None
    finally:
        big.close()
    assert any('Cannot reach' in one.getMessage() for one in caplog.records)


# ---- a source is a station --------------------------------------------------


def test_a_polled_source_is_a_finished_station():
    """Nothing to adopt. The driver knows what answered because it asked.

    So the block that says what to ask is the whole of the station, and the role and
    the channel go in it rather than in a second block somewhere else.
    """
    made = polling.stations(
        {
            'air': {
                'address': '1.2.3.4',
                'protocol': 'purpleair',
                'role': 'extra',
                'channel': '3',
            }
        }
    )
    assert made == {'air': {'role': 'extra', 'channel': '3', 'path': '/poll/air'}}


def test_what_a_source_says_about_asking_stays_out_of_the_station():
    """The two halves of one block do not leak into each other."""
    made = polling.stations({'air': {'url': 'http://1.2.3.4/json', 'interval': '30'}})
    assert made == {'air': {'path': '/poll/air'}}


def test_the_protocols_a_source_asks_for_are_named():
    assert polling.named(
        {
            'air': {'protocol': 'purpleair'},
            'more': {'protocol': 'purpleair'},
            'plain': {'url': 'http://1.2.3.4/'},
        }
    ) == ['purpleair']


# ---- through the whole driver -----------------------------------------------


def test_a_polled_sensor_records_without_anything_being_adopted(sensor, tmp_path):
    """One block of configuration, and a loop packet comes out of the far end.

    The station exists from the first line of the configuration file rather than
    from the first answer, which is the whole difference between this and a console
    that has to be met on the network.
    """
    pytest.importorskip('weewx', reason="WeeWX is not installed")
    from ultimatepush.driver import UltimatePushDriver

    driver = UltimatePushDriver(
        port=0,
        address='127.0.0.1',
        weewx_root=str(tmp_path),
        polling={
            'air': {
                'url': sensor.url,
                'protocol': 'purpleair',
                'interval': '5',
                'role': 'extra',
                'channel': '3',
            }
        },
    )
    try:
        assert [one.name for one in driver.stations.values()] == ['air']
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
        assert packet['station'] == 'air'
        # An extra station's temperature and humidity go to its channel, which is
        # what keeps a thermometer inside a warm plastic box out of outTemp.
        assert packet['extraTemp3'] == pytest.approx(ANSWER['current_temp_f'])
        assert packet['extraHumid3'] == pytest.approx(ANSWER['current_humidity'])
        # Readings nothing else sends arrive as themselves.
        assert packet['pm2_5'] == pytest.approx(ANSWER['pm2_5_atm'])
        assert packet['pm10_0'] == pytest.approx(ANSWER['pm10_0_atm'])
        # Millibars, in a catalog read as US, where pressure is inches of mercury.
        assert packet['pressure'] == pytest.approx(
            ANSWER['pressure'] * 0.02953, abs=0.01
        )
    finally:
        driver.closePort()


def test_naming_a_protocol_under_polling_switches_it_on(sensor, tmp_path):
    """Writing it in two places would only make somewhere for the two to disagree."""
    pytest.importorskip('weewx', reason="WeeWX is not installed")
    from ultimatepush.driver import UltimatePushDriver

    driver = UltimatePushDriver(
        port=0,
        address='127.0.0.1',
        weewx_root=str(tmp_path),
        polling={'air': {'url': sensor.url, 'protocol': 'purpleair'}},
    )
    try:
        assert 'purpleair' in [one.name for one in driver.enabled]
    finally:
        driver.closePort()


def test_a_name_used_by_both_a_station_and_a_source_is_refused(tmp_path):
    """Two blocks describing one station, and no way to say which wins."""
    pytest.importorskip('weewx', reason="WeeWX is not installed")
    from ultimatepush.driver import UltimatePushDriver

    with pytest.raises(ValueError) as raised:
        UltimatePushDriver(
            port=0,
            address='127.0.0.1',
            weewx_root=str(tmp_path),
            stations={'air': {'path': '/somewhere'}},
            polling={'air': {'url': 'http://1.2.3.4/json'}},
        )
    assert 'air' in str(raised.value)


# ---- setting one up from the page -------------------------------------------


@pytest.fixture
def interface(tmp_path):
    """A driver with the web interface on, which is what can add a source."""
    pytest.importorskip('weewx', reason="WeeWX is not installed")
    from ultimatepush.driver import UltimatePushDriver

    made = []

    def _build(**stanzas):
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
            **stanzas,
        )
        made.append(driver)
        return driver

    yield _build
    for driver in made:
        driver.closePort()


def test_a_source_added_from_the_page_is_asked_before_it_is_saved(sensor, interface):
    """A wrong address is a message on the page, not an entry to take out again."""
    driver = interface()
    ok, message = driver.web_add_polled(
        'purpleair', address=sensor.address, interval='30', role='extra', name='air'
    )
    assert ok, message
    assert 'air' in driver.asking
    assert [one.name for one in driver.stations.values()] == ['air']
    # A channel was picked, because a station whose temperature has nowhere to go
    # records no temperature.
    station = list(driver.stations.values())[0]
    assert station.role == 'extra' and station.channel


def test_a_source_that_is_asked_and_starts_answering_needs_no_restart(
    sensor, interface
):
    driver = interface()
    ok, message = driver.web_add_polled(
        'purpleair', address=sensor.address, interval='5', name='air'
    )
    assert ok, message
    got = []

    def pull():
        for packet in driver.genLoopPackets():
            got.append(packet)
            return

    reader = threading.Thread(target=pull, daemon=True)
    reader.start()
    reader.join(20)
    assert got, "the source was set up and nothing came out of the driver"
    assert got[0]['station'] == 'air'


def test_an_address_with_nothing_at_it_is_refused(interface):
    driver = interface()
    ok, message = driver.web_add_polled('purpleair', address='127.0.0.1:1')
    assert not ok
    assert 'Nothing has been saved' in message
    assert not driver.asking


def test_something_that_is_not_the_hardware_asked_for_is_refused(interface):
    """The address of the router, or of another weather station on the network."""
    other = Sensor(json.dumps({'PASSKEY': 'ABC', 'tempf': '71.0'}).encode('utf-8'))
    driver = interface()
    try:
        ok, message = driver.web_add_polled('purpleair', address=other.address)
    finally:
        other.close()
    assert not ok
    assert 'not a PurpleAir' in message
    assert not driver.asking


def test_a_protocol_that_is_waited_for_cannot_be_polled(interface):
    driver = interface()
    ok, message = driver.web_add_polled('ecowitt', address='1.2.3.4')
    assert not ok
    assert 'goes and asks' in message


def test_taking_a_source_out_takes_its_station_with_it(sensor, interface):
    driver = interface()
    assert driver.web_add_polled('purpleair', address=sensor.address, name='air')[0]
    ok, message = driver.web_remove_polled('air')
    assert ok, message
    assert 'air' not in driver.asking
    assert not [one for one in driver.stations.values() if one.name == 'air']
    assert not driver.overrides.polled()


def test_a_source_that_is_not_there_cannot_be_taken_out(interface):
    ok, message = interface().web_remove_polled('nowhere')
    assert not ok
    assert 'nowhere' in message


def test_a_source_set_up_here_is_still_there_after_a_restart(sensor, interface):
    """It is written to the settings file, because this driver does not write
    weewx.conf. A restart reads it back and asks again."""
    first = interface()
    assert first.web_add_polled('purpleair', address=sensor.address, name='air')[0]
    again = interface()
    assert 'air' in again.asking
    assert [one.name for one in again.stations.values()] == ['air']


# ---- the sensor that is not there -------------------------------------------


def test_the_simulator_answers_something_the_driver_recognises():
    """Otherwise it is a fixture that proves nothing about the real path."""
    from ultimatepush.protocols.purpleair import PurpleAir

    assert PurpleAir.claims(None, simulate.purpleair_answer(AT)) == 5


def test_the_simulator_sends_the_types_the_hardware_sends():
    """The temperatures are integers on a real sensor, and a reader may check."""
    answer = simulate.purpleair_answer(AT)
    for name in ('current_temp_f', 'current_humidity', 'current_dewpoint_f'):
        assert isinstance(answer[name], int), name
    assert isinstance(answer['pressure'], float)


def test_the_simulator_moves():
    """A flat line tells nobody whether their graphs are working."""
    first = simulate.purpleair_answer(AT)
    later = simulate.purpleair_answer(AT + 300.0)
    assert first['pm2_5_atm'] != later['pm2_5_atm']
    assert first['current_temp_f'] != later['current_temp_f']
    # And the same moment twice is the same answer, or no test could use it.
    assert simulate.purpleair_answer(AT)['pm2_5_atm'] == first['pm2_5_atm']


def test_the_simulator_stays_within_reason():
    """Readings a person would believe, at every moment of a day."""
    for step in range(0, 86400, 137):
        answer = simulate.purpleair_answer(AT + step)
        assert 50 <= answer['current_temp_f'] <= 95
        assert 0 <= answer['current_humidity'] <= 100
        assert 0 <= answer['pm2_5_atm'] <= 60
        assert 0 <= answer['pm2.5_aqi'] <= 200
