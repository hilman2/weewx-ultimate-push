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

    # Posted rather than waited for: until the main station has been heard, an extra
    # one is held back, so this upload yields no packet at all.
    post(driver, extra['path'], payload('hp2561ae_pro'))
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


def test_two_stations_cannot_share_a_column_even_by_hand(driver, payload):
    """A field named by hand decides where a reading goes. It does not decide that a
    column may hold two sensors: the column belongs to whoever filled it first, and
    the second station's reading is dropped rather than written over it."""
    _, main = driver.web_create('ecowitt', 'garden')
    _, other = driver.web_create('ecowitt', 'roof')
    driver.web_set_field('path:' + main['path'], 'tempf', 'outTemp')
    driver.web_set_field('path:' + other['path'], 'tempf', 'outTemp')
    driver._reload()

    first = send(driver, main['path'], payload('hp2561ae_pro'))
    second = send(driver, other['path'], payload('hp2561ae_pro'))
    send(driver, other['path'], payload('hp2561ae_pro'))

    assert first['outTemp'] == 59.7
    assert 'outTemp' not in second
    assert driver.owners.owner('outTemp') == 'path:' + main['path']


def test_and_the_page_says_whose_reading_went_nowhere(driver, payload):
    """Somebody whose second console is not recording its temperature finds that out
    here, rather than a month later in an empty graph."""
    _, main = driver.web_create('ecowitt', 'garden')
    _, other = driver.web_create('ecowitt', 'roof')
    driver.web_set_field('path:' + other['path'], 'tempf', 'outTemp')
    driver._reload()

    send(driver, main['path'], payload('hp2561ae_pro'))
    send(driver, other['path'], payload('hp2561ae_pro'))
    send(driver, other['path'], payload('hp2561ae_pro'))
    sharing = [s for s in driver.web_setup()['steps'] if s['id'] == 'sharing'][0]

    assert sharing['done'] is False
    wanted = {f['field']: f for f in sharing['fields']}
    assert 'outTemp' in wanted
    assert wanted['outTemp']['stations'] == ['roof']
    assert wanted['outTemp']['owner'] == 'garden'


def test_a_second_station_never_starts_sharing_in_the_first_place(driver, payload):
    """It is an extra sensor from the moment it is set up. There is nothing to
    notice and settle afterwards, because the sharing never begins."""
    _, main = driver.web_create('ecowitt', 'garden')
    _, other = driver.web_create('ecowitt', 'roof')
    assert driver.web_stations['path:' + other['path']].role == 'extra'

    send(driver, main['path'], payload('hp2561ae_pro'))
    # Twice: what a station is not writing is recorded against the station, and the
    # first upload is the one that creates it.
    send(driver, other['path'], payload('hp2561ae_pro'))
    send(driver, other['path'], payload('hp2561ae_pro'))

    sharing = [s for s in driver.web_setup()['steps'] if s['id'] == 'sharing'][0]
    assert sharing['done'] is True
    assert 'dropped' in sharing['detail']


# ---------------------------------------------------------------- one main station


def test_the_second_station_is_an_extra_sensor_without_being_asked(driver):
    """Nobody sets up a second console meaning to have two of them take turns in
    outTemp. The first station is the station; everything after it is a sensor."""
    driver.web_create('ecowitt', 'garden')
    ok, made = driver.web_create('ecowitt', 'roof')

    assert ok is True
    assert made['role'] == 'extra'
    assert made['channel'] == 1


def test_a_second_main_station_is_refused_until_somebody_means_it(driver):
    """Making another station the main one moves the readings of the one that was
    into other columns from that moment. That is not a click to take back, so it
    takes saying so twice: the interface explains it, and this asks to be forced."""
    _, first = driver.web_create('ecowitt', 'garden')

    ok, message = driver.web_create('ecowitt', 'roof', role='main')
    assert ok is False
    assert 'garden' in message

    ok, made = driver.web_create('ecowitt', 'roof', role='main', force=True)
    assert ok is True
    assert made['role'] == 'main'
    was = driver.web_stations['path:' + first['path']]
    assert was.role == 'extra'
    assert was.channel == 1


def test_two_main_stations_still_cannot_both_write(driver, payload):
    """The interface never makes two. A settings file somebody edited can, and a
    warning at startup does not stop anything: what stops it is that the columns the
    main station fills are not written by anybody else, whatever their role says."""
    _, first = driver.web_create('ecowitt', 'garden')
    _, second = driver.web_create('ecowitt', 'roof')
    driver.overrides.set_station('path:' + second['path'], role='main')
    driver._reload()
    assert driver.web_stations['path:' + second['path']].role == 'main'

    send(driver, first['path'], payload('hp2561ae_pro'))
    post(driver, second['path'], payload('hp2561ae_pro'))
    post(driver, second['path'], payload('hp2561ae_pro'))
    again = send(driver, first['path'], payload('hp2561ae_pro'))

    assert again['outTemp'] == 59.7
    row = driver.activity.one('path:' + second['path'])
    assert 'outTemp' not in row['written']
    assert 'outTemp' in row['dropped_fields']


def test_the_first_station_in_the_file_is_the_one_that_writes(driver, payload):
    """Two of them, and the pick cannot wander between restarts or the archive would
    hold a swap nobody made. It is the order they are declared in."""
    _, first = driver.web_create('ecowitt', 'garden')
    _, second = driver.web_create('ecowitt', 'roof')
    driver.overrides.set_station('path:' + second['path'], role='main')
    driver._reload()

    assert driver.the_main_station() is driver.web_stations['path:' + first['path']]


def test_a_console_this_driver_adopted_counts_as_the_main_one(driver, payload):
    """It was never given the role. It has it, and it fills the columns, so a station
    set up afterwards is a sensor beside it rather than a second one of it."""
    send(driver, '/', payload('hp2561ae_pro'))

    _, made = driver.web_create('ecowitt', 'roof')

    assert made['role'] == 'extra'


def test_making_a_second_station_the_main_one_moves_the_first(driver, payload):
    """There is one main station. Making another one main has to move the one that
    was, or both would be writing the same columns again."""
    _, first = driver.web_create('ecowitt', 'garden')
    _, second = driver.web_create('ecowitt', 'roof')

    driver.web_role('path:' + second['path'], 'main', force=True)

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


# ---------------------------------------------------------------- by hand


def test_a_station_written_by_hand_can_do_everything_the_interface_can(tmp_path,
                                                                       payload):
    """Nothing here is only reachable by clicking. A role, a channel and a path work
    the same written into weewx.conf."""
    made = UltimatePushDriver(
        port=0, address='127.0.0.1', report_file='',
        console_file=str(tmp_path / 'c.txt'), override_file=str(tmp_path / 'w.conf'),
        stations={
            'garden': {'passkey': 'AAAA', 'path': '/one/report'},
            'roof': {'passkey': 'BBBB', 'path': '/two/report',
                     'role': 'extra', 'channel': '4'},
        })
    try:
        send(made, '/one/report', 'PASSKEY=AAAA&stationtype=GW2000A&tempf=59.7'
                                  '&humidity=91&baromrelin=29.92')
        second = send(made, '/two/report',
                      'PASSKEY=BBBB&stationtype=GW2000A&tempf=61.0&humidity=80'
                      '&baromrelin=29.99')
    finally:
        made.closePort()

    assert second['station'] == 'roof'
    assert second['extraTemp4'] == 61.0
    assert second['extraHumid4'] == 80.0
    assert 'barometer' not in second


def test_a_role_that_is_not_a_role_is_refused_at_startup(tmp_path):
    with pytest.raises(ValueError) as caught:
        UltimatePushDriver(port=0, address='127.0.0.1', report_file='',
                           console_file=str(tmp_path / 'c.txt'),
                           stations={'garden': {'passkey': 'AAAA',
                                                'role': 'chief'}})

    assert 'chief' in str(caught.value)


def test_two_main_stations_are_said_out_loud(tmp_path, caplog):
    """The driver drops the second one's readings rather than mix the columns, but a
    configuration that asks for that is worth saying at startup."""
    import logging

    with caplog.at_level(logging.WARNING):
        made = UltimatePushDriver(
            port=0, address='127.0.0.1', report_file='',
            console_file=str(tmp_path / 'c.txt'),
            stations={'garden': {'passkey': 'AAAA'},
                      'roof': {'passkey': 'BBBB'}})
        made.closePort()

    assert 'set up as the main one' in caplog.text
    assert 'garden' in caplog.text and 'roof' in caplog.text


# ------------------------------------------------------- after a restart


def test_an_extra_station_waits_for_the_main_one_after_a_restart(tmp_path, payload):
    """What the main station fills is learned from its uploads, so at startup it is
    not yet known. If the extra station uploads first, nothing would hold its wind and
    pressure back and they would land in the main station's columns for an interval.

    One interval of two sensors in one column is the failure this whole mechanism
    exists to prevent, and it would happen at every restart.
    """
    def build():
        return UltimatePushDriver(
            port=0, address='127.0.0.1', report_file='',
            console_file=str(tmp_path / 'consoles.txt'),
            override_file=str(tmp_path / 'web.conf'))

    made = build()
    _, garden = made.web_create('ecowitt', 'garden')
    _, roof = made.web_create('ecowitt', 'roof')
    made.web_role('path:' + roof['path'], roles.EXTRA)
    made.closePort()

    made = build()
    try:
        # The extra station is first out of the gate, which is a coin toss.
        post(made, roof['path'], payload('hp2561ae_pro'))
        packets = made.genLoopPackets()
        post(made, garden['path'], payload('hp2561ae_pro'))

        first = next(packets)
        assert first['station'] == 'garden'
        assert first['barometer'] is not None

        # And once the main station has been heard, the extra one is let through
        # with its temperature moved and the rest dropped, as always.
        after = send(made, roof['path'], payload('hp2561ae_pro'))
        assert after['station'] == 'roof'
        assert 'barometer' not in after
        assert after['extraTemp1'] is not None
    finally:
        made.closePort()


def test_an_extra_station_is_not_held_back_when_there_is_no_main_one(tmp_path, payload):
    """Otherwise it would wait for something that is never coming."""
    made = UltimatePushDriver(
        port=0, address='127.0.0.1', report_file='',
        console_file=str(tmp_path / 'consoles.txt'),
        override_file=str(tmp_path / 'web.conf'))
    try:
        _, roof = made.web_create('ecowitt', 'roof')
        made.web_role('path:' + roof['path'], roles.EXTRA)
        made.said_apart.clear()

        packet = send(made, roof['path'], payload('hp2561ae_pro'))

        assert packet['extraTemp1'] is not None
        assert packet['barometer'] is not None
    finally:
        made.closePort()


# ---------------------------------------------------------------- changing one


def test_a_station_set_up_here_can_be_renamed(driver):
    _, made = driver.web_create('ecowitt', 'garedn')
    ident = 'path:' + made['path']

    ok, _ = driver.web_edit(ident, name='garden')

    assert ok is True
    assert driver.web_stations[ident].name == 'garden'
    # The path is the identity and the secret. Renaming does not touch it, or the
    # console would have to be set up again over a typo.
    assert driver.web_stations[ident].path == made['path']


def test_two_stations_cannot_be_given_the_same_name(driver):
    driver.web_create('ecowitt', 'garden')
    _, roof = driver.web_create('ecowitt', 'roof')

    ok, message = driver.web_edit('path:' + roof['path'], name='garden')

    assert ok is False
    assert 'already' in message


def test_a_channel_can_be_picked_rather_than_handed_out(driver):
    driver.web_create('ecowitt', 'garden')
    _, roof = driver.web_create('ecowitt', 'roof')

    ok, _ = driver.web_edit('path:' + roof['path'], channel=5)

    assert ok is True
    assert driver.web_stations['path:' + roof['path']].channel == 5


def test_a_channel_another_station_has_is_refused(driver):
    driver.web_create('ecowitt', 'garden')
    driver.web_create('ecowitt', 'roof')
    _, shed = driver.web_create('ecowitt', 'shed')

    ok, message = driver.web_edit('path:' + shed['path'], channel=1)

    assert ok is False
    assert 'roof' in message


def test_a_channel_the_schema_has_no_column_for_is_refused(driver):
    driver.web_create('ecowitt', 'garden')
    _, roof = driver.web_create('ecowitt', 'roof')

    ok, message = driver.web_edit('path:' + roof['path'], channel=9)

    assert ok is False
    assert '8' in message


def test_the_main_station_keeps_no_channel(driver):
    """It has no use for one, and one left behind reads like it still means
    something."""
    driver.web_create('ecowitt', 'garden')
    _, roof = driver.web_create('ecowitt', 'roof')
    ident = 'path:' + roof['path']

    driver.web_edit(ident, role='main', force=True)

    assert driver.web_stations[ident].channel is None
    assert 'channel' not in driver.overrides.station(ident)


def test_a_station_weewx_conf_names_is_not_edited_here(tmp_path):
    """One owner per setting. That file is the station's declaration."""
    made = UltimatePushDriver(
        port=0, address='127.0.0.1', report_file='',
        console_file=str(tmp_path / 'c.txt'), override_file=str(tmp_path / 'w.conf'),
        stations={'garden': {'passkey': 'A' * 32}})
    try:
        ok, message = made.web_edit('A' * 32, name='roof')
    finally:
        made.closePort()

    assert ok is False
    assert 'weewx.conf' in message


def test_a_station_can_be_taken_out_again(driver, payload):
    """And the driver stops answering to it. A station nobody set up is a station
    this driver does not know, and being turned away is the honest answer."""
    _, made = driver.web_create('ecowitt', 'garden')
    ident = 'path:' + made['path']
    send(driver, made['path'], payload('hp2561ae_pro'))

    ok, _ = driver.web_forget(ident)

    assert ok is True
    assert ident not in driver.web_stations
    assert ident not in driver.known
    assert post(driver, made['path'], payload('hp2561ae_pro')) == 404


def test_taking_the_main_station_out_leaves_the_extra_one_writing(driver, payload):
    """Held back for a main station that is never coming would be held back for
    ever."""
    _, garden = driver.web_create('ecowitt', 'garden')
    _, roof = driver.web_create('ecowitt', 'roof')

    driver.web_forget('path:' + garden['path'])
    packet = send(driver, roof['path'], payload('hp2561ae_pro'))

    assert packet['extraTemp1'] is not None


def test_the_drivers_own_path_stays_open_once_another_has_a_secret_one(driver,
                                                                      payload):
    """The console that was here first posts to '/', because that is what the setup
    page told somebody to type. Setting up a second station with a path of its own
    must not turn the first one away: it would go quiet for a reason nobody would
    look for on a page about the second station."""
    send(driver, '/', payload('hp2561ae_pro'))
    _, roof = driver.web_create('ecowitt', 'roof')
    send(driver, roof['path'], payload('hp2561ae_pro'))

    assert post(driver, '/', payload('hp2561ae_pro')) == 200
    # And a path nobody was given is still refused.
    assert post(driver, '/somewhere/else', payload('hp2561ae_pro')) == 404


# ------------------------------------------------- columns that already hold data


def an_archive(tmp_path, filled=None):
    """A real WeeWX database, with readings in the columns named.

    A column with history in it is the one thing a mock cannot stand in for: the
    whole question is what the archive table actually holds.
    """
    import configobj
    import weewx.manager

    config = configobj.ConfigObj({
        'WEEWX_ROOT': str(tmp_path),
        'DatabaseTypes': {'SQLite': {'driver': 'weedb.sqlite',
                                     'SQLITE_ROOT': str(tmp_path)}},
        'Databases': {'archive_sqlite': {'database_type': 'SQLite',
                                         'database_name': 'test.sdb'}},
        'DataBindings': {'wx_binding': {
            'database': 'archive_sqlite',
            'table_name': 'archive',
            'manager': 'weewx.manager.DaySummaryManager',
            'schema': 'schemas.wview_extended.schema'}},
    })
    config.filename = str(tmp_path / 'weewx.conf')
    config.write()
    with weewx.manager.open_manager_with_config(config, 'wx_binding',
                                                initialize=True) as manager:
        when = 1700000000
        for n in range(3):
            record = {'dateTime': when + n * 300, 'usUnits': 1, 'interval': 5}
            record.update(filled or {})
            manager.addRecord(record)
    return config


def with_archive(tmp_path, config):
    return UltimatePushDriver(
        port=0, address='127.0.0.1', report_file='',
        console_file=str(tmp_path / 'consoles.txt'),
        override_file=str(tmp_path / 'web.conf'),
        config_dict=config)


def test_a_channel_whose_columns_hold_readings_is_not_handed_out(tmp_path):
    """extraTemp1 with a year of an old sensor in it is not a free channel. Writing
    a new sensor into it makes one column out of two, which is the thing none of
    this is allowed to produce."""
    config = an_archive(tmp_path, {'extraTemp1': 41.0, 'extraHumid1': 55.0})
    made = with_archive(tmp_path, config)
    try:
        # An Ecowitt console fills extraTemp1 from a channel sensor of its own, so
        # the main station is asked about that column too. Said yes to, here.
        made.web_create('ecowitt', 'garden', force=True)
        ok, roof = made.web_create('ecowitt', 'roof')

        assert ok is True, roof
        assert roof['channel'] == 2
    finally:
        made.closePort()


def test_a_station_will_not_write_into_a_column_that_holds_readings(tmp_path):
    """Not without being asked. Those readings came from somewhere, and carrying on
    in them is right for the same station in the same place and ruins the series for
    anything else."""
    config = an_archive(tmp_path, {'outTemp': 50.0, 'barometer': 29.9})
    made = with_archive(tmp_path, config)
    try:
        ok, message = made.web_create('ecowitt', 'garden')

        assert ok is False
        assert 'already holds 3 reading(s)' in message
        assert 'outTemp' in message or 'barometer' in message
        assert '1 other column' in message
    finally:
        made.closePort()


def test_and_goes_ahead_once_somebody_says_it_is_the_same_station(tmp_path):
    config = an_archive(tmp_path, {'outTemp': 50.0, 'barometer': 29.9})
    made = with_archive(tmp_path, config)
    try:
        ok, station = made.web_create('ecowitt', 'garden', force=True)

        assert ok is True
        assert station['role'] == 'main'
    finally:
        made.closePort()


def test_what_it_would_land_on_can_be_asked_before_it_is_done(tmp_path):
    """So that the page can say which columns, how much is in them and how old it
    is, rather than 'are you sure'."""
    config = an_archive(tmp_path, {'outTemp': 50.0, 'extraTemp1': 41.0})
    made = with_archive(tmp_path, config)
    try:
        answer = made.web_before('ecowitt', role='main')

        assert answer['checked'] is True
        assert answer['role'] == 'main'
        found = {c['field']: c for c in answer['columns']}
        assert found['outTemp']['count'] == 3
        assert found['outTemp']['last'].startswith('20')
        # The channel it would be given avoids the one that has history.
        assert made.web_before('ecowitt', role='extra')['channel'] == 2
    finally:
        made.closePort()


def test_nothing_to_read_is_not_the_same_as_nothing_in_the_way(driver):
    """An installation with no database says so, rather than reporting all clear."""
    answer = driver.web_before('ecowitt', role='main')

    assert answer['checked'] is False
    assert answer['columns'] == []


# ---------------------------------------------------- one column, one owner


def test_two_extra_sensors_do_not_share_a_column(driver, payload):
    """The case roles alone never covered.

    The main station is an Ambient console, which has no soil moisture reading. So
    nothing of the two Ecowitt consoles beside it is kept out of that column by the
    role, and before there was a register both of them wrote it, in turn, every few
    seconds.
    """
    _, main = driver.web_create('ambient', 'greenhouse')
    _, roof = driver.web_create('ecowitt', 'roof')
    _, shed = driver.web_create('ecowitt', 'shed')
    send(driver, main['path'], payload('ambient/ambweather_v4'))

    first = send(driver, roof['path'], payload('hp2561ae_pro'))
    second = send(driver, shed['path'], payload('hp2561ae_pro'))

    assert first['soilMoist1'] is not None
    assert 'soilMoist1' not in second
    assert driver.owners.owner('soilMoist1') == 'path:' + roof['path']


def test_a_column_the_main_station_does_not_fill_is_not_wasted(driver, payload):
    """An extra sensor keeps what nobody else has. Dropping everything the main
    station does not write would throw away readings for no reason."""
    _, main = driver.web_create('ecowitt', 'garden')
    _, roof = driver.web_create('ecowitt', 'roof')
    send(driver, main['path'], payload('hp2561ae_pro'))

    packet = send(driver, roof['path'], payload('hp2561ae_pro'))

    # outTemp is the main station's and is moved aside, as always.
    assert 'outTemp' not in packet
    assert packet['extraTemp1'] == 59.7


def test_who_owns_what_survives_a_restart(tmp_path, payload):
    """The whole reason it is written down. Learning it again would mean holding
    every extra station back until the main one is heard, once per restart, and a
    station that went quiet for a week would come back to find its columns taken."""
    def build():
        return UltimatePushDriver(
            port=0, address='127.0.0.1', report_file='',
            console_file=str(tmp_path / 'consoles.txt'),
            override_file=str(tmp_path / 'web.conf'))

    made = build()
    _, garden = made.web_create('ecowitt', 'garden')
    _, roof = made.web_create('ecowitt', 'roof')
    send(made, garden['path'], payload('hp2561ae_pro'))
    send(made, roof['path'], payload('hp2561ae_pro'))
    made.closePort()

    made = build()
    try:
        assert made.owners.owner('outTemp') == 'path:' + garden['path']
        assert made.owners.owner('extraTemp1') == 'path:' + roof['path']

        # And the extra station is not held back this time: what the main station
        # fills is known before it has said anything.
        packet = send(made, roof['path'], payload('hp2561ae_pro'))
        assert packet['extraTemp1'] == 59.7
    finally:
        made.closePort()


def test_a_station_that_changes_channel_gives_its_columns_back(driver, payload):
    """It writes extraTemp3 from then on. Holding extraTemp1 as well would keep that
    channel out of everybody's reach for good."""
    _, main = driver.web_create('ecowitt', 'garden')
    _, roof = driver.web_create('ecowitt', 'roof')
    send(driver, main['path'], payload('hp2561ae_pro'))
    send(driver, roof['path'], payload('hp2561ae_pro'))
    ident = 'path:' + roof['path']
    assert driver.owners.owner('extraTemp1') == ident

    driver.web_edit(ident, role='extra', channel=3)

    assert driver.owners.owner('extraTemp1') is None
    packet = send(driver, roof['path'], payload('hp2561ae_pro'))
    assert packet['extraTemp3'] == 59.7


def test_a_station_that_is_taken_out_gives_its_columns_back(driver, payload):
    _, main = driver.web_create('ecowitt', 'garden')
    _, roof = driver.web_create('ecowitt', 'roof')
    send(driver, main['path'], payload('hp2561ae_pro'))
    send(driver, roof['path'], payload('hp2561ae_pro'))

    driver.web_forget('path:' + roof['path'])

    assert driver.owners.owner('extraTemp1') is None
    assert driver.owners.owner('outTemp') == 'path:' + main['path']
