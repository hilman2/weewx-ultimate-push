#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""Several stations on one driver.

One station needs none of this, and the first test says so: nothing about the simple
case changed. Everything else here is about the second station, where the question is
unavoidable. Both send `outTemp`, and there is one `outTemp`.

Left alone they would take turns writing it every few seconds, and the column would
hold a mixture nothing afterwards can separate. That is the failure this driver refuses
everywhere else, so these tests are about refusing it here.
"""

import http.client

import pytest

pytest.importorskip('weewx', reason="WeeWX is not installed")

from ultimatepush import roles                          # noqa: E402
from ultimatepush.driver import UltimatePushDriver      # noqa: E402


@pytest.fixture
def driver(tmp_path):
    made = UltimatePushDriver(
        port=0, address='127.0.0.1', report_file='',
        console_file=str(tmp_path / 'consoles.txt'),
        override_file=str(tmp_path / 'web.conf'))
    yield made
    made.closePort()


def post(driver, path, body):
    connection = http.client.HTTPConnection('127.0.0.1', driver.listener.ports[0],
                                            timeout=5)
    try:
        connection.request('POST', path, body)
        response = connection.getresponse()
        status = response.status
        response.read()
        return status
    finally:
        connection.close()


def send(driver, path, body):
    post(driver, path, body)
    return next(driver.genLoopPackets())


# ---------------------------------------------------------------- one station


def test_one_station_needs_none_of_this(driver, payload):
    """The simple case has to stay the simple case. Nothing is asked, nothing is
    moved, and the readings go where they belong."""
    packet = send(driver, '/', payload('hp2561ae_pro'))

    assert packet['outTemp'] == 59.7
    assert packet['barometer'] == 29.920
    assert 'extraTemp1' not in packet


# ---------------------------------------------------------------- a path of its own


def test_a_station_can_be_set_up_before_it_ever_uploads(driver):
    """Naming it gives it a path. From the first upload the driver knows which
    station that is, and nobody has adopted anything."""
    ok, made = driver.web_create('ecowitt', 'garden')

    assert ok is True
    assert made['name'] == 'garden'
    assert made['path'].endswith('/report')
    assert dict(made['settings']['settings'])['Path'] == made['path']


def test_the_path_says_which_station_it_is(driver, payload):
    _, made = driver.web_create('ecowitt', 'garden')

    packet = send(driver, made['path'], payload('hp2561ae_pro'))

    assert packet['station'] == 'garden'


def test_hardware_that_cannot_be_given_a_path_is_not_set_up_this_way(driver):
    """A hub broadcasts and a bridge has its path in its firmware. Offering to make
    one would be offering something that cannot be typed in anywhere."""
    for name in ('weatherflow', 'acurite', 'lacrosse'):
        ok, message = driver.web_create(name, 'somewhere')
        assert ok is False
        assert 'adopt' in message or 'cannot be told' in message


def test_every_path_works_until_one_has_been_proven(driver, payload):
    """Somebody who set a station up here but has not finished typing it into the
    console must not have their existing uploads start bouncing."""
    driver.web_create('ecowitt', 'garden')

    assert post(driver, '/', payload('hp2561ae_pro')) == 200


def test_once_a_path_has_worked_the_others_are_refused(driver, payload):
    _, made = driver.web_create('ecowitt', 'garden')
    send(driver, made['path'], payload('hp2561ae_pro'))

    assert post(driver, '/somewhere/else', payload('hp2561ae_pro')) == 404


def test_a_path_burned_into_firmware_is_always_answered(driver, payload):
    """Weather Underground hardware cannot be told to use another. Before this, a
    driver with a secret path and a WU console could not both exist."""
    _, made = driver.web_create('ecowitt', 'garden')
    send(driver, made['path'], payload('hp2561ae_pro'))

    assert post(driver, '/weatherstation/updateweatherstation.php',
                'ID=x&PASSWORD=y&tempf=61.0') == 200


# ---------------------------------------------------------------- roles


def test_an_extra_station_is_moved_out_of_the_way(driver, payload):
    _, main = driver.web_create('ecowitt', 'garden')
    _, extra = driver.web_create('ecowitt', 'roof')
    driver.overrides.set_station('path:' + extra['path'], role='extra', channel=3)
    driver._reload()

    send(driver, main['path'], payload('hp2561ae_pro'))
    second = send(driver, extra['path'], payload('hp2561ae_pro'))

    assert second['extraTemp3'] == 59.7
    assert second['extraHumid3'] == 91.0
    assert 'outTemp' not in second


def test_the_main_station_is_untouched_by_a_second_one(driver, payload):
    _, main = driver.web_create('ecowitt', 'garden')
    _, extra = driver.web_create('ecowitt', 'roof')
    driver.overrides.set_station('path:' + extra['path'], role='extra', channel=3)
    driver._reload()

    send(driver, extra['path'], payload('hp2561ae_pro'))
    first = send(driver, main['path'], payload('hp2561ae_pro'))

    assert first['outTemp'] == 59.7
    assert first['barometer'] == 29.920


def test_what_has_nowhere_to_go_is_dropped_not_written_over(driver, payload):
    """The standard schema has extraTemp and extraHumid and nothing of the sort for
    wind, rain or pressure. A second station's are not written into the first one's."""
    _, main = driver.web_create('ecowitt', 'garden')
    _, extra = driver.web_create('ecowitt', 'roof')
    driver.overrides.set_station('path:' + extra['path'], role='extra', channel=3)
    driver._reload()

    send(driver, main['path'], payload('hp2561ae_pro'))
    second = send(driver, extra['path'], payload('hp2561ae_pro'))

    for field in ('barometer', 'pressure', 'windSpeed', 'windGust', 'dayRain',
                  'rainRate', 'inTemp'):
        assert field not in second, field


def test_it_says_so_once_rather_than_thirty_times(driver, payload, caplog):
    """A second weather station has thirty readings with nowhere to go, and thirty
    copies of one sentence is not a log anybody reads."""
    import logging

    _, main = driver.web_create('ecowitt', 'garden')
    _, extra = driver.web_create('ecowitt', 'roof')
    driver.overrides.set_station('path:' + extra['path'], role='extra', channel=3)
    driver._reload()
    send(driver, main['path'], payload('hp2561ae_pro'))

    with caplog.at_level(logging.WARNING):
        send(driver, extra['path'], payload('hp2561ae_pro'))
        send(driver, extra['path'], payload('hp2561ae_pro'))

    said = [r for r in caplog.records if 'are not being written' in r.getMessage()]
    assert len(said) == 1
    assert 'barometer' in said[0].getMessage()


def test_naming_a_field_by_hand_outranks_the_role(driver, payload):
    """The role is a default. Naming it is a decision, and decisions win."""
    _, main = driver.web_create('ecowitt', 'garden')
    _, extra = driver.web_create('ecowitt', 'roof')
    ident = 'path:' + extra['path']
    driver.overrides.set_station(ident, role='extra', channel=3)
    driver.web_set_field(ident, 'baromrelin', 'altimeter')
    driver._reload()

    send(driver, main['path'], payload('hp2561ae_pro'))
    second = send(driver, extra['path'], payload('hp2561ae_pro'))

    assert second['altimeter'] == 29.920


# ---------------------------------------------------------------- the tables


def test_a_reading_with_nowhere_to_go_is_reported_as_such():
    assert roles.shifted('outTemp', 3) == 'extraTemp3'
    assert roles.shifted('outHumidity', 3) == 'extraHumid3'
    assert roles.shifted('barometer', 3) is None


def test_the_next_free_channel():
    assert roles.next_channel(set()) == 1
    assert roles.next_channel({1, 2, 4}) == 3
    assert roles.next_channel(set(range(1, 9))) is None


def test_collisions_name_everybody_involved():
    found = roles.collisions({'garden': {'outTemp', 'barometer'},
                              'roof': {'outTemp', 'windSpeed'},
                              'shed': {'outTemp'}})

    assert found == {'outTemp': ['garden', 'roof', 'shed']}


def test_two_stations_sharing_a_column_are_reported(driver, payload):
    """Nothing else in WeeWX would say so. The last upload of each would simply take
    turns writing it, every few seconds, for as long as both are running."""
    _, main = driver.web_create('ecowitt', 'garden')
    _, other = driver.web_create('ecowitt', 'roof')

    send(driver, main['path'], payload('hp2561ae_pro'))
    send(driver, other['path'], payload('hp2561ae_pro'))
    sharing = [s for s in driver.web_setup()['steps'] if s['id'] == 'sharing'][0]

    assert sharing['done'] is False
    fields = {f['field'] for f in sharing['fields']}
    assert 'outTemp' in fields
    assert 'barometer' in fields


def test_a_role_settles_it_in_one_go(driver, payload):
    _, main = driver.web_create('ecowitt', 'garden')
    _, other = driver.web_create('ecowitt', 'roof')
    send(driver, main['path'], payload('hp2561ae_pro'))
    send(driver, other['path'], payload('hp2561ae_pro'))

    ok, _ = driver.web_role('path:' + other['path'], 'extra')
    assert ok is True
    send(driver, main['path'], payload('hp2561ae_pro'))
    send(driver, other['path'], payload('hp2561ae_pro'))

    sharing = [s for s in driver.web_setup()['steps'] if s['id'] == 'sharing'][0]
    assert sharing['done'] is True
    assert 'dropped' in sharing['detail']


def test_making_a_second_station_the_main_one_moves_the_first(driver, payload):
    """There is one main station. Making another one main has to move the one that
    was, or both would be writing the same columns again."""
    _, first = driver.web_create('ecowitt', 'garden')
    _, second = driver.web_create('ecowitt', 'roof')
    driver.web_role('path:' + second['path'], 'extra')

    driver.web_role('path:' + second['path'], 'main')

    assert driver.web_stations['path:' + second['path']].role == 'main'
    was = driver.web_stations['path:' + first['path']]
    assert was.role == 'extra'
    assert was.channel is not None


def test_a_channel_is_never_handed_out_twice(driver):
    made = []
    for n in range(3):
        _, station = driver.web_create('ecowitt', 'shed%d' % n)
        made.append('path:' + station['path'])
    for ident in made[1:]:
        driver.web_role(ident, 'extra')

    channels = [driver.web_stations[i].channel for i in made[1:]]
    assert len(set(channels)) == len(channels)
    assert None not in channels
