#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""What the setup page says is still in the way.

It is a checklist rather than a wizard, and that is the thing worth testing: the
answer comes from what is true, not from a step number somebody might be halfway
through. So each test puts the driver in a state and asks what it says, in any order,
including backwards.
"""

import http.client
import json
import os

import pytest

pytest.importorskip('weewx', reason="WeeWX is not installed")

from ultimatepush import checklist                      # noqa: E402
from ultimatepush.driver import UltimatePushDriver      # noqa: E402

TOKEN = 'a-token-long-enough-to-pass'
PASSKEY = '0000000000000000000000000000AAAA'
PLACED = {'tf_ch1': 'extraTemp9', 'tf_ch2': 'extraTemp10',
          'tf_batt1': 'wn34_ch1_batt', 'tf_batt2': 'wn34_ch2_batt',
          'soil_ec_temp1': 'soilTemp1', 'lightning_time': 'lightning_time'}


@pytest.fixture
def station(tmp_path):
    made = UltimatePushDriver(
        port=0, address='127.0.0.1', report_file='',
        console_file=str(tmp_path / 'consoles.txt'),
        override_file=str(tmp_path / 'web.conf'))
    yield made
    made.closePort()


def upload(driver, body, path='/'):
    connection = http.client.HTTPConnection('127.0.0.1', driver.listener.ports[0],
                                            timeout=5)
    try:
        connection.request('POST', path, body)
        connection.getresponse().read()
    finally:
        connection.close()


def send(driver, body):
    upload(driver, body)
    return next(driver.genLoopPackets())


def step(driver, ident):
    return [s for s in driver.web_setup()['steps'] if s['id'] == ident][0]


# ---------------------------------------------------------------- fresh


def test_a_fresh_install_is_told_to_point_its_hardware_here(station):
    """The commonest place to be stuck, and the one the page could say least about:
    it showed an empty list of stations and nothing else."""
    setup = station.web_setup()

    assert setup['done'] is False
    assert setup['next'] == 'hardware'


def test_it_says_what_to_type_and_where_this_machine_is(station):
    """Not 'point your console at this server'. The address and the port."""
    hardware = step(station, 'hardware')
    ecowitt = [p for p in hardware['protocols'] if p['name'] == 'ecowitt'][0]
    settings = dict(ecowitt['settings'])

    assert settings['Protocol Type'] == 'Ecowitt'
    assert settings['Port'] == str(station.listener.ports[0])
    assert settings['Server IP / Hostname'] not in ('', '*', '0.0.0.0')
    assert settings['Path'] == '/'


def test_the_port_it_names_is_the_one_the_readings_arrive_on(station):
    """Not the web interface's. They are two listeners and it would be easy to name
    the wrong one, and impossible for the person typing it in to tell."""
    hardware = step(station, 'hardware')
    ecowitt = [p for p in hardware['protocols'] if p['name'] == 'ecowitt'][0]

    assert dict(ecowitt['settings'])['Port'] == str(station.data_port())


def test_a_thing_to_type_is_never_a_sentence(station):
    """The page lays the settings out as a table. A sentence in that table reads as a
    field to fill in, which is how somebody ends up typing 'In the WSView Plus app'
    into a server field."""
    for protocol in step(station, 'hardware')['protocols']:
        for label, value in protocol['settings']:
            assert len(label) < 26, (protocol['name'], label)
            assert '.' not in label
            assert len(value) < 40, (protocol['name'], value)


def test_hardware_that_cannot_be_pointed_anywhere_says_so(station):
    """An Acurite bridge has no server field. Offering a table of settings would be
    inviting somebody to look for one that is not there."""
    acurite = [p for p in step(station, 'hardware')['protocols']
               if p['name'] == 'acurite'][0]

    assert acurite['settings'] == []
    assert any('myacurite' in note for note in acurite['notes'])


# ---------------------------------------------------------------- it advances


def test_it_moves_on_by_itself_when_the_first_upload_arrives(station, payload):
    assert station.web_setup()['next'] == 'hardware'

    send(station, payload('hp2561ae_pro'))

    assert step(station, 'hardware')['done'] is True
    assert station.web_setup()['next'] == 'placements'


def test_it_names_the_fields_that_are_waiting(station, payload):
    send(station, payload('hp2561ae_pro'))
    placements = step(station, 'placements')

    assert placements['done'] is False
    assert {f['raw'] for f in placements['fields']} >= {'tf_ch1', 'tf_ch2'}


def test_placing_them_settles_that_step(station, payload):
    send(station, payload('hp2561ae_pro'))
    for raw, field in PLACED.items():
        station.web_set_field(PASSKEY, raw, field)
    send(station, payload('hp2561ae_pro'))

    assert step(station, 'placements')['done'] is True


def test_a_console_being_turned_away_comes_back_to_the_top(station, payload):
    """Backwards, which a wizard with a step number would not manage. Everything was
    done, then a second console appeared."""
    send(station, payload('hp2561ae_pro'))
    for raw, field in PLACED.items():
        station.web_set_field(PASSKEY, raw, field)
    send(station, payload('hp2561ae_pro'))

    upload(station, 'PASSKEY=%s&stationtype=GW2000A&tempf=61.0' % ('B' * 32))
    station._packet_from(station.listener.listeners[0].get(timeout=5))

    refused = step(station, 'refused')
    assert refused['done'] is False
    assert refused['stations'][0]['ident'] == 'B' * 32
    assert station.web_setup()['next'] == 'refused'


def test_letting_it_in_settles_that_too(station, payload):
    """The first console this driver ever hears is adopted, so a second one is
    needed before anything is refused at all."""
    send(station, payload('hp2561ae_pro'))

    other = 'C' * 32
    upload(station, 'PASSKEY=%s&stationtype=GW2000A&tempf=61.0' % other)
    station._packet_from(station.listener.listeners[0].get(timeout=5))
    assert step(station, 'refused')['done'] is False

    station.web_accept(other, 'roof')

    assert step(station, 'refused')['done'] is True


# ---------------------------------------------------------------- location


def test_a_station_left_at_the_north_pole_is_told_so(tmp_path):
    """Sunrise, sunset and every solar figure come from this, and nothing else in
    WeeWX says out loud that it was never set."""
    made = UltimatePushDriver(
        port=0, address='127.0.0.1', report_file='',
        console_file=str(tmp_path / 'c.txt'), override_file=str(tmp_path / 'w.conf'),
        config_dict={'Station': {'location': "Santa's Workshop",
                                 'latitude': '0.0', 'longitude': '0.0'}})
    try:
        location = [s for s in made.web_setup()['steps'] if s['id'] == 'location'][0]
    finally:
        made.closePort()

    assert location['done'] is False
    assert set(location['unset']) == {'location', 'latitude', 'longitude'}
    assert '[Station]' in location['block']


def test_a_station_that_knows_where_it_is_passes(tmp_path):
    made = UltimatePushDriver(
        port=0, address='127.0.0.1', report_file='',
        console_file=str(tmp_path / 'c.txt'), override_file=str(tmp_path / 'w.conf'),
        config_dict={'Station': {'location': 'Kirchdorf an der Amper',
                                 'latitude': '48.4596', 'longitude': '11.6539'}})
    try:
        location = [s for s in made.web_setup()['steps'] if s['id'] == 'location'][0]
    finally:
        made.closePort()

    assert location['done'] is True
    assert 'Kirchdorf' in location['detail']


def test_without_a_configuration_the_location_is_not_claimed_to_be_wrong(station):
    """A driver built without one, which is a test or a diagnostic run. Saying the
    station is at the north pole would be inventing a fault."""
    location = step(station, 'location')

    assert location['done'] is True
    assert location['optional'] is True


# ---------------------------------------------------------------- the whole thing


def test_it_reaches_done(tmp_path, payload):
    """With everything answered, it stops asking and stays as a health page."""
    made = UltimatePushDriver(
        port=0, address='127.0.0.1', report_file='',
        console_file=str(tmp_path / 'c.txt'), override_file=str(tmp_path / 'w.conf'),
        config_dict={'Station': {'location': 'Kirchdorf', 'latitude': '48.4',
                                 'longitude': '11.6'}})
    try:
        send(made, payload('hp2561ae_pro'))
        for raw, field in PLACED.items():
            made.web_set_field(PASSKEY, raw, field)
        send(made, payload('hp2561ae_pro'))
        # The columns step is the only one left, and it needs a database to settle.
        # Pretend the schema has everything this station sends.
        made.web_columns = lambda ident, refresh=False: {'ok': True, 'missing': []}

        setup = made.web_setup()
    finally:
        made.closePort()

    assert setup['done'] is True
    assert setup['next'] is None
    assert all(s['done'] for s in setup['steps'])


def test_every_step_says_something_a_person_can_act_on():
    """A checklist entry with no title is a checklist entry nobody can use."""
    for name in ('hardware', 'refused', 'placements', 'columns', 'location'):
        assert name in {s['id'] for s in checklist.steps(_Nothing())}


class _Nothing:
    """A driver that has heard nothing, for checking the shape of the answer."""

    enabled = []
    activity = type('L', (), {'snapshot': lambda self: [],
                              'unknown_stations': lambda self, r: []})()
    web_stations = {}
    overrides = type('O', (), {'stations': lambda self: {}})()

    def web_waiting(self):
        return []

    def web_address(self):
        return '192.168.1.50'

    def data_port(self):
        return 8000

    def data_path(self):
        return '/'

    def station_location(self):
        return None

    def web_columns(self, ident, refresh=False):
        return {'ok': True, 'missing': []}


# ------------------------------------------- a station set up and not yet heard


def test_a_station_set_up_here_is_shown_its_own_path(station):
    """The path is the whole point of setting one up: it is how the driver knows
    which station an upload is from, and it is a secret. The page used to show the
    driver's general path instead, which is the one thing that cannot work."""
    ok, made = station.web_create('ecowitt', 'garden')
    assert ok, made

    hardware = step(station, 'hardware')

    assert hardware['done'] is False
    assert [w['name'] for w in hardware['created']] == ['garden']
    settings = dict(hardware['created'][0]['settings']['settings'])
    assert settings['Path'] == made['path']
    assert settings['Path'] != station.data_path()


def test_the_path_survives_closing_the_page(station):
    """It comes from the driver on every load rather than being held in the browser.
    Somebody who set a station up, closed the tab and came back would otherwise have
    made a secret nothing will ever show them again."""
    _ok, made = station.web_create('ecowitt', 'garden')

    again = step(station, 'hardware')

    assert dict(again['created'][0]['settings']['settings'])['Path'] == made['path']


def test_once_it_has_uploaded_it_stops_being_something_to_do(station, payload):
    _ok, made = station.web_create('ecowitt', 'garden')
    upload(station, payload('hp2561ae_pro'), path=made['path'])
    next(station.genLoopPackets())

    hardware = step(station, 'hardware')

    assert hardware['created'] == []
    assert hardware['done'] is True


def test_the_protocols_are_there_even_when_the_step_is_finished(station, payload):
    """Setting up a second station is the same job as setting up the first, and the
    page needs the same material for it. Without this the Add a station button led to
    a page with nothing on it."""
    send(station, payload('hp2561ae_pro'))

    hardware = step(station, 'hardware')

    assert hardware['done'] is True
    assert [p['name'] for p in hardware['protocols']]
    assert any(p['can_create'] for p in hardware['protocols'])
