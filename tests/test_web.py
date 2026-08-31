#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""The web interface.

Two halves, tested differently. What it shows is checked through the driver, from a
captured upload, because that is the only way to know the numbers on the page are the
ones the driver actually has. What it refuses is checked over a socket, because a
token is only worth what it is worth against a real request.

The doorman has its own file. Here it is only checked that the door is wired to it.
"""

import http.client
import json
import time
import urllib.parse
import os
import re

import pytest

weewx = pytest.importorskip('weewx', reason="WeeWX is not installed")

from ultimatepush import overrides  # noqa: E402
from ultimatepush.driver import UltimatePushDriver  # noqa: E402

TOKEN = 'a-token-long-enough-to-pass'
PASSKEY = '0000000000000000000000000000AAAA'


@pytest.fixture
def station(tmp_path):
    """A driver with the interface on, and nothing of anybody else's on disk."""
    made = UltimatePushDriver(
        port=0,
        address='127.0.0.1',
        passkey=PASSKEY,
        report_file='',
        console_file=str(tmp_path / 'consoles.txt'),
        override_file=str(tmp_path / 'web.conf'),
        web={'enable': 'true', 'port': 0, 'address': '127.0.0.1', 'token': TOKEN},
    )
    yield made
    made.closePort()


def upload(driver, body, path='/data/report/'):
    connection = http.client.HTTPConnection(
        '127.0.0.1', driver.listener.ports[0], timeout=5
    )
    try:
        connection.request('POST', path, body)
        return connection.getresponse().read()
    finally:
        connection.close()


def web(driver, path, body=None, token=TOKEN):
    """(status, content type, parsed body) from the admin listener."""
    connection = http.client.HTTPConnection(
        '127.0.0.1', driver.listener.ports[1], timeout=5
    )
    try:
        headers = {'X-Auth-Token': token} if token else {}
        if body is None:
            connection.request('GET', path, headers=headers)
        else:
            headers['Content-Type'] = 'application/json'
            connection.request('POST', path, json.dumps(body), headers)
        response = connection.getresponse()
        raw = response.read()
        try:
            parsed = json.loads(raw)
        except ValueError:
            parsed = raw
        return response.status, response.getheader('Content-Type'), parsed
    finally:
        connection.close()


def send(driver, payload):
    """One upload, all the way through to a packet."""
    upload(driver, payload)
    return next(driver.genLoopPackets())


# ---------------------------------------------------------------- the door


def test_it_is_off_unless_asked_for(tmp_path):
    """A port that can change the field map does not open because somebody upgraded."""
    made = UltimatePushDriver(
        port=0,
        address='127.0.0.1',
        passkey=PASSKEY,
        console_file=str(tmp_path / 'c.txt'),
        report_file='',
    )
    try:
        assert len(made.listener.ports) == 1
    finally:
        made.closePort()


def test_it_refuses_to_start_without_a_token(tmp_path):
    """The token is the only thing between the field map and the rest of the
    network, so a missing one is a refusal rather than a warning."""
    with pytest.raises(ValueError) as caught:
        UltimatePushDriver(
            port=0,
            address='127.0.0.1',
            passkey=PASSKEY,
            console_file=str(tmp_path / 'c.txt'),
            report_file='',
            web={'enable': 'true', 'port': 0, 'token': 'short'},
        )

    assert 'token' in str(caught.value)


def test_ten_characters_is_enough(tmp_path):
    """A weather station, not a bank. Ten random characters is about sixty bits, and
    the doorman is what covers a token somebody thought up instead."""
    made = UltimatePushDriver(
        port=0,
        address='127.0.0.1',
        passkey=PASSKEY,
        report_file='',
        console_file=str(tmp_path / 'c.txt'),
        override_file=str(tmp_path / 'w.conf'),
        web={
            'enable': 'true',
            'port': 0,
            'address': '127.0.0.1',
            'token': 'abcde12345',
        },
    )
    try:
        # Two sockets: the one hardware uploads to and the one the interface is on.
        # The third listener is where a hosted driver would go and has no port; see
        # hardware.Host.
        assert len([port for port in made.listener.ports if port]) == 2
    finally:
        made.closePort()


def test_no_token_gets_nothing_useful(station):
    _, _, answer = web(station, '/api/state', token=None)

    assert answer['ok'] is False
    assert 'token' in answer['error'].lower()


def test_a_wrong_token_is_told_so_and_nothing_else(station, payload):
    """Not what is behind the door, and not how close the guess was."""
    send(station, payload('hp2561ae_pro'))
    _, _, answer = web(station, '/api/state', token='a-token-long-enough')

    assert answer['ok'] is False
    assert 'stations' not in answer


def test_a_person_who_mistypes_it_is_told_where_to_look(station):
    """A browser gets a page rather than a line of JSON."""
    status, content_type, body = web(station, '/', token='wrong-but-long')

    assert status == 200
    assert content_type.startswith('text/html')
    assert b'token' in body


def test_an_address_that_keeps_guessing_stops_being_answered(tmp_path):
    """The black hole. Three wrong ones here, then nothing, right token or not."""
    made = UltimatePushDriver(
        port=0,
        address='127.0.0.1',
        passkey=PASSKEY,
        report_file='',
        console_file=str(tmp_path / 'c.txt'),
        override_file=str(tmp_path / 'w.conf'),
        web={
            'enable': 'true',
            'port': 0,
            'address': '127.0.0.1',
            'token': TOKEN,
            'tries': 3,
            'window': 300,
        },
    )
    try:
        for _ in range(3):
            assert web(made, '/api/state', token='wrong-but-long')[2]['ok'] is False
        # Now nothing comes back at all, and the right token does not help.
        assert web(made, '/api/state', token='wrong-but-long')[2] == b''
        assert web(made, '/api/state', token=TOKEN)[2] == b''
    finally:
        made.closePort()


def test_the_knocking_is_visible_on_the_page(station):
    """Rather than only in the log, which is the thing nobody is reading."""
    web(station, '/api/state', token='wrong-but-long')
    web(station, '/api/state', token='wrong-but-long')
    _, _, state = web(station, '/api/state')

    assert state['door']['refused'] == 2
    assert state['door']['clients'][0]['client'] == '127.0.0.1'
    assert state['door']['clients'][0]['wrong'] == 2


def test_getting_it_right_does_not_hide_that_it_was_wrong_before(station):
    """The record has to survive the successful request, or it could never be read:
    reading it means getting the token right first."""
    web(station, '/api/state', token='wrong-but-long')
    _, _, state = web(station, '/api/state')

    assert state['door']['clients'][0]['wrong'] == 1
    assert state['door']['clients'][0]['blocked'] is False


def test_the_admin_port_is_not_a_data_port(station, payload):
    """Its requests answer and stop. A request queued there would be read as a
    reading, and would push a real one out of the queue."""
    listener = station.listener.listeners[1]
    web(station, '/api/state')

    assert listener.queue.empty()


def test_the_data_port_is_not_an_admin_port(station):
    """The interface is on its own port precisely so that the token can be required.
    Requiring it on the data port would lock out hardware that cannot send one."""
    answer = upload(station, 'PASSKEY=%s&stationtype=GW2000A&tempf=1' % PASSKEY)

    assert answer == b'{"errcode":"0","errmsg":"ok"}'


# ---------------------------------------------------------------- what it shows


def test_the_page_is_one_file(station):
    status, content_type, body = web(station, '/')

    assert status == 200
    assert content_type.startswith('text/html')
    assert body.lstrip().startswith(b'<!doctype')
    # Nothing to fetch. The listener answers one request per connection and closes
    # it, and a driver has no business shipping an asset pipeline.
    #
    # The SVG namespace is the one address in the page and is not a fetch: it names
    # what the icon is, browsers never resolve it, and an SVG without it does not
    # parse. So it is taken out before looking, rather than the check being dropped.
    body = body.replace(b"'http://www.w3.org/2000/svg'", b'')
    for outside in (b'http://', b'https://', b'.css"', b'.js"'):
        assert outside not in body


def test_the_overview_says_what_is_running(station, payload):
    send(station, payload('hp2561ae_pro'))
    _, _, state = web(station, '/api/state')

    assert state['ok'] is True
    assert len(state['ports']) == 2
    assert 'ecowitt' in state['protocols']
    assert len(state['stations']) == 1
    assert state['stations'][0]['ident'] == PASSKEY
    assert state['stations'][0]['protocol'] == 'ecowitt'
    assert state['stations'][0]['uploads'] == 1


def test_the_field_list_is_what_this_station_sends(station, payload):
    """Not the catalog. An HP2561 sends forty fields and the Ecowitt catalog has five
    hundred; a page listing the catalog would bury the forty that matter."""
    send(station, payload('hp2561ae_pro'))
    _, _, detail = web(station, '/api/station?ident=' + PASSKEY)

    assert 30 < len(detail['fields']) < 60
    raw = {row['raw'] for row in detail['fields']}
    assert 'tempf' in raw
    assert 'soilmoisture17' not in raw


def test_what_names_the_device_is_not_offered_as_a_reading(station, payload):
    """A page that offered to place PASSKEY would be offering a mistake."""
    send(station, payload('hp2561ae_pro'))
    _, _, detail = web(station, '/api/station?ident=' + PASSKEY)
    raw = {row['raw'] for row in detail['fields']}

    for name in ('PASSKEY', 'stationtype', 'dateutc', 'freq', 'model'):
        assert name not in raw


def test_a_row_carries_the_decision_and_not_just_the_name(station, payload):
    """The point of the page: what arrived, where it goes, and whether there is
    anywhere for it to go."""
    send(station, payload('hp2561ae_pro'))
    _, _, detail = web(station, '/api/station?ident=' + PASSKEY)
    rows = {row['raw']: row for row in detail['fields']}

    assert rows['tempf']['field'] == 'outTemp'
    assert rows['tempf']['value'] == 59.7
    assert rows['tempf']['column'] is True
    # A contested one is shown with nothing in the field, and why.
    assert rows['tf_ch1']['field'] == ''
    assert 'disagree' in rows['tf_ch1']['why']


def test_the_raw_uploads_are_safe_to_paste(station, payload):
    send(station, payload('hp2561ae_pro'))
    _, _, kept = web(station, '/api/raw?ident=' + PASSKEY)

    assert len(kept['uploads']) == 1
    assert 'PASSKEY=X' in kept['uploads'][0]['text']
    assert PASSKEY not in kept['uploads'][0]['text']
    assert 'tempf=59.7' in kept['uploads'][0]['text']


def test_a_refused_station_is_visible_with_its_readings(station):
    """Otherwise the only way to find out why a new console is not appearing is to
    turn on log_raw and wait for the next upload with a grep running."""
    upload(station, 'PASSKEY=%s&stationtype=GW2000A&tempf=61.0' % ('B' * 32))
    station._packet_from(_last_request(station))
    _, _, state = web(station, '/api/state')

    assert len(state['waiting']) == 1
    assert state['waiting'][0]['ident'] == 'B' * 32
    assert 'tempf=61.0' in state['waiting'][0]['sample']['text']


def _last_request(driver):
    return driver.listener.listeners[0].get(timeout=5)


def test_the_columns_page_says_what_to_run(station, payload):
    send(station, payload('hp2561ae_pro'))
    _, _, cols = web(station, '/api/columns?ident=' + PASSKEY)

    assert cols['ok'] is True
    assert cols['missing']
    assert any('weectl database add-column' in c for c in cols['commands'])
    # The history check is a pass over the archive table, so it waits to be asked.
    assert cols['occupied_checked'] is False


# ---------------------------------------------------------------- what it changes


def test_placing_a_field_takes_effect_on_the_next_upload(station, payload):
    """Without a restart. That is the whole reason the settings do not live in
    weewx.conf, which WeeWX only reads when it starts."""
    send(station, payload('hp2561ae_pro'))
    _, _, answer = web(
        station, '/api/field', {'ident': PASSKEY, 'raw': 'tf_ch1', 'field': 'soilTemp5'}
    )
    assert answer['ok'] is True

    packet = send(station, payload('hp2561ae_pro'))
    assert packet['soilTemp5'] == 66.2


def test_a_placement_survives_in_a_file_of_the_drivers_own(station, payload, tmp_path):
    send(station, payload('hp2561ae_pro'))
    web(
        station, '/api/field', {'ident': PASSKEY, 'raw': 'tf_ch1', 'field': 'soilTemp5'}
    )

    written = (tmp_path / 'web.conf').read_text(encoding='utf-8')
    assert 'tf_ch1 = soilTemp5' in written
    assert PASSKEY in written
    # And it is read back the way it was written.
    store = overrides.Store(str(tmp_path / 'web.conf'))
    store.read()
    assert store.extensions_for(PASSKEY) == {'tf_ch1': 'soilTemp5'}


def test_the_interface_can_change_a_placement_weewx_conf_made(tmp_path, payload):
    """The interface is meant to replace the terminal and the editor, so a placement
    made in the driver's own [[field_map_extensions]] has to be changeable here.
    Otherwise the one thing somebody most wants to fix is the one thing they cannot.

    The row says where the placement came from, so the change is made knowingly.
    """
    made = UltimatePushDriver(
        port=0,
        address='127.0.0.1',
        passkey=PASSKEY,
        report_file='',
        console_file=str(tmp_path / 'consoles.txt'),
        override_file=str(tmp_path / 'web.conf'),
        field_map_extensions={'tf_ch2': 'extraTemp10'},
        web={'enable': 'true', 'port': 0, 'address': '127.0.0.1', 'token': TOKEN},
    )
    try:
        answer = made.web_set_field(PASSKEY, 'tf_ch2', 'extraTemp12')
        assert answer['ok'], answer['message']
        station = made.web_stations.get(PASSKEY) or made.default_station

        assert station.extensions['tf_ch2'] == 'extraTemp12'
    finally:
        made.closePort()


def test_a_station_named_in_weewx_conf_still_keeps_its_field_map(tmp_path):
    """A station declared under [[stations]] is a different matter. Its field map is
    part of that declaration, and half of it living somewhere else is how a
    configuration becomes impossible to read."""
    made = UltimatePushDriver(
        port=0,
        address='127.0.0.1',
        report_file='',
        console_file=str(tmp_path / 'consoles.txt'),
        override_file=str(tmp_path / 'web.conf'),
        stations={
            'garden': {
                'passkey': PASSKEY,
                'field_map_extensions': {'tf_ch2': 'extraTemp10'},
            }
        },
        web={'enable': 'true', 'port': 0, 'address': '127.0.0.1', 'token': TOKEN},
    )
    try:
        answer = made.web_set_field(PASSKEY, 'tf_ch2', 'extraTemp12')
    finally:
        made.closePort()

    assert answer['ok'] is False
    assert 'weewx.conf' in answer['message']


def test_a_refused_station_can_be_let_in(station):
    """And records from its next upload, without a restart.

    As an extra sensor, because this driver already has a main station: the console
    it was configured with. Letting a second one write outTemp is the mixture the
    refusal was protecting in the first place, so being let in cannot mean that.
    """
    other = 'C' * 32
    upload(station, 'PASSKEY=%s&stationtype=GW2000A&tempf=61.0' % other)
    station._packet_from(_last_request(station))

    _, _, answer = web(station, '/api/accept', {'ident': other, 'name': 'roof'})
    assert answer['ok'] is True
    assert 'channel 1' in answer['message']

    # The main station first. Until it has been heard, nothing is known about the
    # columns it fills, and the extra one is held back rather than guessed about.
    send(station, 'PASSKEY=%s&stationtype=GW2000A&tempf=59.0' % PASSKEY)
    packet = send(station, 'PASSKEY=%s&stationtype=GW2000A&tempf=61.0' % other)

    assert packet['extraTemp1'] == 61.0
    assert 'outTemp' not in packet
    assert packet['station'] == 'roof'


def test_the_stations_route_lists_what_can_be_changed(station, payload):
    """Every station, whether or not it has ever uploaded. The tab is a list to find
    one in, and one that only showed the ones that had uploaded would leave somebody
    who just set a station up looking at nothing."""
    send(station, payload('hp2561ae_pro'))
    _, _, answer = web(station, '/api/create', {'protocol': 'ecowitt', 'name': 'roof'})
    assert answer['ok'] is True

    _, _, found = web(station, '/api/stations')

    assert found['ok'] is True
    names = {s['name']: s for s in found['stations']}
    assert 'roof' in names
    assert names['roof']['heard'] is False
    assert names['roof']['role'] == 'extra'
    # The console settings, with this station's own path in them, so that the tab can
    # show them again long after the checklist has stopped.
    assert dict(names['roof']['settings']['settings'])['Path'] == names['roof']['path']
    assert sum(1 for s in found['stations'] if s['is_main']) == 1


def test_the_edit_route_changes_a_station(station):
    _, _, made = web(station, '/api/create', {'protocol': 'ecowitt', 'name': 'roof'})
    ident = 'path:' + made['station']['path']

    _, _, answer = web(
        station,
        '/api/edit',
        {'ident': ident, 'name': 'the_roof', 'role': 'extra', 'channel': 3},
    )

    assert answer['ok'] is True
    assert station.web_stations[ident].name == 'the_roof'
    assert station.web_stations[ident].channel == 3


def test_the_edit_route_will_not_hand_over_the_main_station_by_accident(
    station, payload
):
    """The interface says what it costs and asks again. Something posting straight at
    the route has said neither, so the route says no."""
    send(station, payload('hp2561ae_pro'))
    _, _, made = web(station, '/api/create', {'protocol': 'ecowitt', 'name': 'roof'})
    ident = 'path:' + made['station']['path']

    _, _, refused = web(station, '/api/edit', {'ident': ident, 'role': 'main'})
    assert refused['ok'] is False

    _, _, agreed = web(
        station, '/api/edit', {'ident': ident, 'role': 'main', 'force': True}
    )
    assert agreed['ok'] is True
    assert station.web_stations[ident].role == 'main'


def test_a_name_that_would_not_survive_a_config_file_is_refused(station):
    _, _, answer = web(
        station, '/api/accept', {'ident': 'D' * 32, 'name': 'roof]\n[Station'}
    )

    assert answer['ok'] is False


def test_a_field_name_no_column_could_have_is_refused(station, payload):
    send(station, payload('hp2561ae_pro'))
    _, _, answer = web(
        station,
        '/api/field',
        {'ident': PASSKEY, 'raw': 'tf_ch1', 'field': 'drop table;--'},
    )

    assert answer['ok'] is False


def test_clearing_a_field_puts_it_back_where_it_was(station, payload):
    send(station, payload('hp2561ae_pro'))
    web(
        station, '/api/field', {'ident': PASSKEY, 'raw': 'tf_ch1', 'field': 'soilTemp5'}
    )
    assert send(station, payload('hp2561ae_pro')).get('soilTemp5') == 66.2

    web(station, '/api/field', {'ident': PASSKEY, 'raw': 'tf_ch1', 'field': ''})
    packet = send(station, payload('hp2561ae_pro'))

    assert 'soilTemp5' not in packet


# ---------------------------------------------------------------- the awkward parts


def test_a_broken_settings_file_does_not_stop_the_readings(tmp_path, payload):
    """The weather matters more than the settings. The log says what to fix."""
    (tmp_path / 'web.conf').write_text('[stations\n  broken = ', encoding='utf-8')
    made = UltimatePushDriver(
        port=0,
        address='127.0.0.1',
        passkey=PASSKEY,
        report_file='',
        console_file=str(tmp_path / 'consoles.txt'),
        override_file=str(tmp_path / 'web.conf'),
    )
    try:
        packet = send(made, payload('hp2561ae_pro'))
    finally:
        made.closePort()

    assert packet['outTemp'] == 59.7


def test_an_unknown_route_answers_rather_than_hanging(station):
    status, _, answer = web(station, '/api/nonesuch')

    assert status == 200
    assert answer['ok'] is False


def test_nonsense_in_a_post_is_survivable(station):
    connection = http.client.HTTPConnection(
        '127.0.0.1', station.listener.ports[1], timeout=5
    )
    try:
        connection.request(
            'POST', '/api/field', 'not json at all', {'X-Auth-Token': TOKEN}
        )
        assert connection.getresponse().status == 200
    finally:
        connection.close()


def test_the_page_asks_for_the_api_relative_to_itself(station):
    """Behind a reverse proxy it is served under whatever path the proxy chose. An
    absolute /api/ would land on whatever else that host serves from the root."""
    _, _, body = web(station, '/')

    assert b"fetch(BASE + 'api/'" in body
    assert b"fetch('/api/" not in body
    assert b'location.pathname' in body


# ---------------------------------------------------------------- finding it


def test_the_driver_says_where_the_interface_is(station, caplog):
    """A listener bound to every interface reports itself as '*', which is true and
    useless. Somebody should not have to run `ip addr` to find their own station."""
    from ultimatepush import admin

    address = admin.url('', 8080, TOKEN)

    assert address.startswith('http://')
    assert address.endswith(':8080/?token=' + TOKEN)
    assert '*' not in address
    assert '0.0.0.0' not in address


def test_an_address_that_was_asked_for_is_the_one_reported():
    from ultimatepush import admin

    assert admin.url('localhost', 8080, 'x') == 'http://localhost:8080/?token=x'
    assert admin.url('192.168.1.50', 80, 'x') == 'http://192.168.1.50:80/?token=x'


def test_the_url_can_be_asked_for_again(tmp_path, capsys):
    """It is in the log at startup, and a log is a poor place to keep something you
    want to open next week."""
    from ultimatepush.__main__ import main

    conf = tmp_path / 'weewx.conf'
    conf.write_text(
        "[UltimatePush]\n    [[web]]\n        enable = true\n"
        "        port = 8080\n        token = kJ7mQx2vRt9w\n",
        encoding='utf-8',
    )

    assert main(['--url', '--config', str(conf)]) == 0
    assert 'kJ7mQx2vRt9w' in capsys.readouterr().out


def test_it_says_so_when_there_is_nowhere_to_go(tmp_path, capsys):
    from ultimatepush.__main__ import main

    conf = tmp_path / 'weewx.conf'
    conf.write_text(
        "[UltimatePush]\n    [[web]]\n        enable = false\n", encoding='utf-8'
    )

    assert main(['--url', '--config', str(conf)]) == 1
    assert 'switched off' in capsys.readouterr().out


def test_the_installer_leaves_it_ready_to_open():
    """Two commands, not five. Placing a field is the one thing about this hardware
    that cannot be undone once it is wrong, and it should not sit behind a setup."""
    import pytest

    pytest.importorskip('weecfg', reason="WeeWX is not installed")
    import importlib.util
    import os
    import sys

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    spec = importlib.util.spec_from_file_location(
        'up_install', os.path.join(root, 'install.py')
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules['up_install'] = module
    spec.loader.exec_module(module)
    web = module.loader()['config']['UltimatePush']['web']

    assert web['enable'] == 'true'
    assert len(web['token']) >= 10
    # A different one on every installation, and never the one in this repository.
    assert web['token'] != module.loader()['config']['UltimatePush']['web']['token']


# ---------------------------------------------------- what is knocking


STRANGER = (
    'PASSKEY=%s&stationtype=GW2000A&tempf=61.0&humidity=88&'
    'windspeedmph=3.4&baromrelin=29.91&dailyrainin=0.02' % ('B' * 32)
)


def test_a_refused_upload_shows_the_readings_it_sent(station, payload):
    """The card asks somebody to let this into their database, or to turn their own
    new console away. An address and a protocol name cannot tell those two apart.
    Sixty-one degrees and eighty-eight per cent can."""
    upload(station, STRANGER)
    station._packet_from(_last_request(station))

    waiting = station.web_overview()['waiting']
    assert len(waiting) == 1
    readings = waiting[0]['sample']['readings']
    assert readings

    placed = {row['field']: row['value'] for row in readings if row['field']}
    assert placed['outTemp'] == '61.0'  # exactly as it arrived
    assert placed['outHumidity'] == '88'

    # Ordered by what a person can check against a thermometer or a window, rather
    # than alphabetically, where the temperature is somewhere past the middle.
    assert readings[0]['field'] == 'outTemp'

    # The raw name is kept beside it, because it carries its own unit: tempf is
    # Fahrenheit whatever this driver would have made of it.
    assert readings[0]['raw'] == 'tempf'


def test_a_refused_upload_does_not_show_what_names_the_console(station):
    """The readings belong on the page. The PASSKEY does not: anybody who has seen
    one upload can repeat it, and this page gets pasted into issues."""
    upload(station, STRANGER)
    station._packet_from(_last_request(station))

    sample = station.web_overview()['waiting'][0]['sample']

    assert not any(row['raw'] == 'PASSKEY' for row in sample['readings'])
    assert not any('B' * 32 in str(row['value']) for row in sample['readings'])
    assert 'B' * 32 not in sample['text']


def test_an_upload_no_protocol_recognised_still_shows_what_arrived(station):
    """The case where somebody has the wrong hardware entirely. There is no catalog
    to place the names with, so they are shown as they arrived."""
    upload(station, 'wind=3&temperature=17&whatever=1')
    station._packet_from(_last_request(station))

    waiting = station.web_overview()['waiting']
    if waiting:  # a protocol may yet claim it; if not, show it
        readings = waiting[0]['sample']['readings']
        assert {row['raw'] for row in readings} >= {'temperature', 'whatever'}


# ---------------------------------------------------- the page itself


BACKSLASH = chr(92)
NEWLINE = chr(10)


def _string_left_open(script):
    """The line number of the first single-quoted string a line does not close.

    This does not parse JavaScript. It looks for the one mistake that has actually
    happened, and it looks only at single quotes: the page writes its strings with
    those, and leaves double quotes for the HTML inside them and the odd regular
    expression, neither of which this needs an opinion about.
    """
    without_comments = re.sub(r'/\*.*?\*/', '', script, flags=re.S)
    for number, line in enumerate(without_comments.split(NEWLINE), 1):
        inside, escaped, was = False, False, ''
        for char in line:
            if escaped:
                escaped = False
            elif inside and char == BACKSLASH:
                escaped = True
            elif char == "'":
                inside = not inside
            elif not inside and char == '/' and was == '/':
                break  # the rest of the line is a comment
            was = char
        if inside:
            return number
    return None


def _assigned_but_never_declared(script):
    """Names the script assigns to at the top of a line without ever declaring.

    This does not parse JavaScript either. It looks for the one mistake that has
    happened: renaming a variable and missing one of the places that writes it. The
    page runs under 'use strict', where assigning to a name nothing declared is a
    ReferenceError, and a ReferenceError in a click handler means the button does
    nothing at all and the console is the only place that says so.

    Only assignments that start a line are looked at, which is what a statement
    looks like here, and only plain names: a property or an index belongs to
    something that was declared elsewhere.

    Args:
        script (str): The page's script.

    Returns:
        set[str]: The names, empty when every one of them was declared.
    """
    without_comments = re.sub(r'/\*.*?\*/', '', script, flags=re.S)
    declared = set(
        re.findall(r'\b(?:var|let|const)\s+([A-Za-z_$][\w$]*)', without_comments)
    )
    # 'var a = 1, b = 2' declares both, and the pattern above sees only the first.
    for run in re.findall(r'\b(?:var|let|const)\s+([^;\n]+)', without_comments):
        for part in run.split(','):
            name = part.split('=')[0].strip()
            if re.match(r'^[A-Za-z_$][\w$]*$', name):
                declared.add(name)
    # Whatever a function takes is declared by taking it.
    for names in re.findall(r'function\s*[\w$]*\s*\(([^)]*)\)', without_comments):
        for part in names.split(','):
            name = part.strip()
            if name:
                declared.add(name)
    assigned = set(
        re.findall(r'^\s*([A-Za-z_$][\w$]*)\s*=[^=]', without_comments, flags=re.M)
    )
    return assigned - declared - {'window', 'location', 'document'}


def test_the_page_declares_everything_it_writes_to():
    """A name nothing declared is a ReferenceError under 'use strict'.

    That shipped once, while the Hardware tab was folded into the Stations tab: a
    variable was renamed and one of the two places that wrote it was missed. Nothing
    else here would have caught it. Every test asks the driver for its answers, and
    the driver's answers were right the whole time.
    """
    from ultimatepush import page

    script = page.PAGE.split('<script>')[1].split('</script>')[0]
    loose = _assigned_but_never_declared(script)

    assert not loose, (
        "the page assigns to %s, which nothing declares. Under 'use strict' that "
        "is a ReferenceError, and whatever was being done stops silently."
        % ', '.join(sorted(loose))
    )


def test_the_page_is_javascript_a_browser_can_parse():
    """A newline escape written with one backslash in the Python source reaches the
    page as a real newline. Inside a JavaScript string literal that is a syntax error,
    the whole script fails to parse, and the page draws its frame and then stops. It
    looks exactly like the server hanging, and the server is fine.

    That shipped once, in 0.10.0, in a prompt about naming a field of your own.
    Nothing else here would have caught it: every test asks the driver for its
    answers, and the driver's answers were right the whole time.
    """
    from ultimatepush import page

    script = page.PAGE.split('<script>')[1].split('</script>')[0]
    line = _string_left_open(script)

    assert line is None, (
        "line %d of the page's script leaves a string open, which a browser reads as "
        "a syntax error, and then the whole page stops working: %s"
        % (line or 0, script.split(NEWLINE)[(line or 1) - 1].strip())
    )


def test_the_open_string_check_would_notice():
    """Because a check that cannot fail is not a check."""
    assert _string_left_open("var a = 'fine';" + NEWLINE + "var b = 'broken") == 2
    assert _string_left_open("var a = 'it" + BACKSLASH + "'s fine';") is None
    assert _string_left_open("var a = 'a real " + BACKSLASH + "n escape';") is None
    assert _string_left_open('a.replace(/"/g, ' + "'&quot;');") is None
    assert _string_left_open("/* somebody" + "'" + "s comment */") is None
    assert _string_left_open("var a = 1;  // and somebody" + "'" + "s note") is None


def test_the_page_calls_only_functions_it_defines():
    """A block of the script was replaced wholesale once, and a function that lived
    inside it went with it. Nothing noticed until somebody clicked the tab that used
    it: the console says `drawRaw is not defined` and the tab says Loading for ever,
    which reads like the server not answering.

    Only the page's own draw and load names are checked. Everything else in there is
    the browser's, and this is not the place to keep a list of what a browser has.
    """
    from ultimatepush import page

    script = page.PAGE.split('<script>')[1].split('</script>')[0]
    defined = set(re.findall(r'function\s+([A-Za-z_$][\w$]*)\s*\(', script))
    called = set(re.findall(r'\b((?:draw|load)[A-Z][\w$]*)\s*\(', script))

    assert called <= defined, "called but never defined: %s" % sorted(called - defined)


def test_every_tab_has_something_to_draw():
    """A tab button with no renderer behind it is a button that does nothing."""
    from ultimatepush import page

    script = page.PAGE.split('<script>')[1].split('</script>')[0]
    dispatcher = script[script.index('function draw() {') :]
    dispatcher = dispatcher[: dispatcher.index(NEWLINE + '}')]

    for tab in sorted(set(re.findall(r'data-tab="([a-z]+)"', page.PAGE))):
        renderer = 'draw' + tab.capitalize()
        assert renderer in dispatcher, "the %s tab draws nothing" % tab
        assert 'function %s(' % renderer in script, "%s does not exist" % renderer


def test_the_before_route_takes_a_channel_out_of_a_query_string(station):
    """It arrives as text, because a query string has nothing else to offer."""
    _, _, answer = web(station, '/api/before?protocol=ecowitt&role=extra&channel=3')

    assert answer['ok'] is True
    assert answer['channel'] == 3


def test_a_station_can_give_up_the_columns_it_fills(station, payload):
    """For a sensor that was taken down. Its column is held until somebody says
    otherwise, which is right while a console is offline for a week and wrong once
    it is gone."""
    send(station, payload('hp2561ae_pro'))

    _, _, found = web(station, '/api/stations')
    mine = found['stations'][0]
    assert 'outTemp' in mine['columns']

    _, _, answer = web(station, '/api/release', {'ident': mine['ident']})

    assert answer['ok'] is True
    assert 'outTemp' in answer['message']
    assert station.owners.owner('outTemp') is None


def test_a_station_that_has_been_let_in_stops_waiting(station):
    """It was refused an hour ago and is not waiting for anything now. Leaving it
    under 'waiting to be let in' reads as the button not having worked."""
    other = 'C' * 32
    upload(station, 'PASSKEY=%s&stationtype=GW2000A&tempf=61.0' % other)
    station._packet_from(_last_request(station))
    assert [w['ident'] for w in station.web_waiting()] == [other]

    web(station, '/api/accept', {'ident': other, 'name': 'roof'})

    assert station.web_waiting() == []
    _, _, state = web(station, '/api/state')
    assert state['waiting'] == []


# ---- hosted hardware, over the API ------------------------------------------


def test_hardware_can_be_set_up_over_the_api(station, tmp_path):
    """The routes the Hardware tab uses, end to end over HTTP.

    A driver made on the spot, because the point here is the routing and the JSON,
    not the hardware. What it stands in for is a Vantage on a serial port.
    """
    import sys
    import types

    module = types.ModuleType('fake.web')

    class Fake:
        @property
        def hardware_name(self):
            return 'Fake'

        def genLoopPackets(self):
            while True:
                yield {'dateTime': int(time.time()), 'usUnits': 1, 'outTemp': 7.0}
                time.sleep(0.05)

        def closePort(self):
            pass

    module.loader = lambda config, engine: Fake()
    sys.modules['fake.web'] = module
    try:
        _, _, listed = web(station, '/api/ways')
        assert listed['ok'] and listed['can_fetch']
        assert any(one['name'] == 'Vantage' for one in listed['ways'])

        _, _, added = web(
            station,
            '/api/hardware/add',
            {'station_type': 'Wired', 'options': {'driver': 'fake.web'}},
        )
        assert added['ok'], added.get('message')

        _, _, again = web(station, '/api/stations')
        wired = [one for one in again['stations'] if one['station_type']]
        assert [one['station_type'] for one in wired] == ['Wired']
        assert wired[0]['running']

        _, _, renamed = web(
            station,
            '/api/hardware/edit',
            {'station_type': 'Wired', 'name': 'The-Vantage'},
        )
        assert renamed['ok'], renamed.get('message')

        _, _, gone = web(station, '/api/hardware/remove', {'station_type': 'Wired'})
        assert gone['ok'], gone.get('message')
        _, _, empty = web(station, '/api/stations')
        assert [one for one in empty['stations'] if one['station_type']] == []
    finally:
        sys.modules.pop('fake.web', None)


def test_hardware_routes_need_the_token(station):
    _, _, answer = web(station, '/api/ways', token='a-token-long-enough')

    assert answer['ok'] is False
    assert 'token' in answer['error'].lower()


# ---- a Weather Underground console can be told what to call itself -----------

WU_PATH = '/weatherstation/updateweatherstation.php'


@pytest.fixture
def empty(tmp_path):
    """A driver with the interface on and no console named anywhere.

    Without a `passkey` there is no station yet, so the first one set up is the main
    one. The `station` fixture has one, which makes every station after it an extra
    sensor, and an extra sensor is held back until the main one has been heard. That
    rule is right and is tested elsewhere; here it would only get in the way.
    """
    made = UltimatePushDriver(
        port=0,
        address='127.0.0.1',
        report_file='',
        console_file=str(tmp_path / 'consoles.txt'),
        override_file=str(tmp_path / 'web.conf'),
        web={'enable': 'true', 'port': 0, 'address': '127.0.0.1', 'token': TOKEN},
    )
    yield made
    made.closePort()


def wu_upload(driver, ident, password, temp='59.9'):
    """One Weather Underground upload, as a console sends it.

    Args:
        driver (UltimatePushDriver): The driver to send to.
        ident (str): The ID the console is set to.
        password (str): The PASSWORD it is set to.
        temp (str): An outdoor temperature, so the packet has a reading in it.

    Returns:
        bytes: Whatever the driver answered.
    """
    query = urllib.parse.urlencode(
        {
            'ID': ident,
            'PASSWORD': password,
            'dateutc': 'now',
            'tempf': temp,
            'humidity': '61',
        }
    )
    connection = http.client.HTTPConnection(
        '127.0.0.1', driver.listener.ports[0], timeout=5
    )
    try:
        connection.request('GET', WU_PATH + '?' + query)
        return connection.getresponse().read()
    finally:
        connection.close()


def test_a_wunderground_station_is_given_its_id_and_password(empty):
    """It carries both and both are anybody's to choose, so this driver chooses.

    Before this, the settings said 'anything you like' for each and the console had
    to be heard and adopted, which is the one step this driver otherwise avoids:
    letting something unknown into the database.
    """
    _, _, made = web(
        empty, '/api/create', {'protocol': 'wunderground', 'name': 'Fine-Offset'}
    )

    assert made['ok'], made.get('message')
    settings = dict(made['station']['settings']['settings'])
    assert settings['ID'] == made['station']['ident']
    assert settings['ID'] != 'anything you like'
    assert settings['PASSWORD'] and settings['PASSWORD'] != 'anything you like'
    assert settings['ID'] != settings['PASSWORD']


def test_it_is_known_from_its_first_upload(empty):
    """No adopting. The ID it was given is the ID it sends."""
    _, _, made = web(
        empty, '/api/create', {'protocol': 'wunderground', 'name': 'Fine-Offset'}
    )
    settings = dict(made['station']['settings']['settings'])

    wu_upload(empty, settings['ID'], settings['PASSWORD'])
    packet = next(empty.genLoopPackets())

    assert packet['station'] == 'Fine-Offset'
    assert packet['outTemp'] == 59.9
    _, _, waiting = web(empty, '/api/waiting')
    assert waiting['stations'] == [], "it should not be waiting to be let in"


def test_the_wrong_password_is_refused(empty):
    """The password is this station's, not the driver's.

    Two consoles told apart by an ID would otherwise be able to use each other's,
    because an ID is readable by anybody who can watch the network.
    """
    _, _, made = web(
        empty, '/api/create', {'protocol': 'wunderground', 'name': 'Fine-Offset'}
    )
    settings = dict(made['station']['settings']['settings'])

    wu_upload(empty, settings['ID'], 'not-the-password')

    _, _, refused = web(empty, '/api/state')
    assert not refused['stations'], "an upload with the wrong password was kept"


def test_two_of_them_get_different_credentials(empty):
    _, _, one = web(empty, '/api/create', {'protocol': 'wunderground', 'name': 'North'})
    _, _, two = web(
        empty,
        '/api/create',
        {'protocol': 'wunderground', 'name': 'South', 'role': 'extra'},
    )
    first = dict(one['station']['settings']['settings'])
    second = dict(two['station']['settings']['settings'])

    assert first['ID'] != second['ID']
    assert first['PASSWORD'] != second['PASSWORD']


def test_hardware_that_can_be_told_nothing_is_still_adopted(empty):
    """Acurite has its server name in firmware and no ID of its own to set.

    There is nothing to hand it, so it is heard first and confirmed afterwards,
    which is what web_accept is for.
    """
    _, _, made = web(
        empty, '/api/create', {'protocol': 'acurite', 'name': 'The-bridge'}
    )

    assert not made['ok']
    assert 'nothing to set up in advance' in made['message']


# ---- the icon ----------------------------------------------------------------


def test_the_page_carries_its_own_icon(station):
    """In the page, like everything else here.

    A page that declares an icon is not asked for /favicon.ico, which is the point:
    that request arrives without a token.
    """
    _, _, body = web(station, '/')

    assert b'<link rel="icon" href="data:image/svg+xml,' in body
    # The policy is default-src 'none', so an inline image needs saying.
    assert b'img-src data:' in body


def test_asking_for_favicon_ico_is_not_counted_against_the_address(station):
    """A browser working from a bookmark has no token to send.

    Ten of those in five minutes would stop the address being answered at all, and
    the person would find an interface that had gone silent for no reason they
    could see.
    """
    for _ in range(12):
        status, content_type, _ = web(station, '/favicon.ico', token=None)
        assert status == 200
        assert content_type.startswith('image/')

    # Still answering, and still asking for the token.
    _, _, answer = web(station, '/api/state')
    assert answer['ok'] is True
