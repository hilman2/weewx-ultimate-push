#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""The web interface.

Two halves, tested differently. What it shows is checked through the driver, from a
captured upload, because that is the only way to know the numbers on the page are the
ones the driver actually has. What it refuses is checked over a socket, because the
refusing is done by the listener before anything here runs, and a test that called the
Python would not exercise the thing that protects it.
"""

import http.client
import json
import os

import pytest

weewx = pytest.importorskip('weewx', reason="WeeWX is not installed")

from ultimatepush import overrides                       # noqa: E402
from ultimatepush.driver import UltimatePushDriver       # noqa: E402

TOKEN = 'a-token-long-enough-to-pass'
PASSKEY = '0000000000000000000000000000AAAA'


@pytest.fixture
def station(tmp_path):
    """A driver with the interface on, and nothing of anybody else's on disk."""
    made = UltimatePushDriver(
        port=0, address='127.0.0.1', passkey=PASSKEY, report_file='',
        console_file=str(tmp_path / 'consoles.txt'),
        override_file=str(tmp_path / 'web.conf'),
        web={'enable': 'true', 'port': 0, 'address': '127.0.0.1', 'token': TOKEN})
    yield made
    made.closePort()


def upload(driver, body, path='/data/report/'):
    connection = http.client.HTTPConnection('127.0.0.1', driver.listener.ports[0],
                                            timeout=5)
    try:
        connection.request('POST', path, body)
        return connection.getresponse().read()
    finally:
        connection.close()


def web(driver, path, body=None, token=TOKEN):
    """(status, content type, parsed body) from the admin listener."""
    connection = http.client.HTTPConnection('127.0.0.1', driver.listener.ports[1],
                                            timeout=5)
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
    made = UltimatePushDriver(port=0, address='127.0.0.1', passkey=PASSKEY,
                              console_file=str(tmp_path / 'c.txt'), report_file='')
    try:
        assert len(made.listener.ports) == 1
    finally:
        made.closePort()


def test_it_refuses_to_start_without_a_token(tmp_path):
    """The token is the only thing between the field map and the rest of the
    network, so a missing one is a refusal rather than a warning."""
    with pytest.raises(ValueError) as caught:
        UltimatePushDriver(port=0, address='127.0.0.1', passkey=PASSKEY,
                           console_file=str(tmp_path / 'c.txt'), report_file='',
                           web={'enable': 'true', 'port': 0, 'token': 'short'})

    assert 'token' in str(caught.value)


def test_a_missing_token_gets_a_real_403(station):
    """Checked by the listener, before anything in the interface runs."""
    assert web(station, '/', token=None)[0] == 403
    assert web(station, '/api/state', token=None)[0] == 403


def test_a_wrong_token_gets_a_403(station):
    assert web(station, '/api/state', token='a-token-long-enough-to-fai')[0] == 403


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
    _, _, answer = web(station, '/api/field',
                       {'ident': PASSKEY, 'raw': 'tf_ch1', 'field': 'soilTemp5'})
    assert answer['ok'] is True

    packet = send(station, payload('hp2561ae_pro'))
    assert packet['soilTemp5'] == 66.2


def test_a_placement_survives_in_a_file_of_the_drivers_own(station, payload, tmp_path):
    send(station, payload('hp2561ae_pro'))
    web(station, '/api/field', {'ident': PASSKEY, 'raw': 'tf_ch1',
                                'field': 'soilTemp5'})

    written = (tmp_path / 'web.conf').read_text(encoding='utf-8')
    assert 'tf_ch1 = soilTemp5' in written
    assert PASSKEY in written
    # And it is read back the way it was written.
    store = overrides.Store(str(tmp_path / 'web.conf'))
    store.read()
    assert store.extensions_for(PASSKEY) == {'tf_ch1': 'soilTemp5'}


def test_weewx_conf_wins_and_says_so(tmp_path, payload):
    """One owner per setting. Two files with an answer each would mean one of them is
    quietly ignored, and which one would depend on the order they were read in."""
    made = UltimatePushDriver(
        port=0, address='127.0.0.1', passkey=PASSKEY, report_file='',
        console_file=str(tmp_path / 'consoles.txt'),
        override_file=str(tmp_path / 'web.conf'),
        field_map_extensions={'tf_ch2': 'extraTemp10'},
        web={'enable': 'true', 'port': 0, 'address': '127.0.0.1', 'token': TOKEN})
    try:
        ok, message = made.web_set_field(PASSKEY, 'tf_ch2', 'soilTemp9')
    finally:
        made.closePort()

    assert ok is False
    assert 'weewx.conf' in message
    assert not os.path.exists(str(tmp_path / 'web.conf'))


def test_a_refused_station_can_be_let_in(station):
    """And records from its next upload, without a restart."""
    other = 'C' * 32
    upload(station, 'PASSKEY=%s&stationtype=GW2000A&tempf=61.0' % other)
    station._packet_from(_last_request(station))

    _, _, answer = web(station, '/api/accept', {'ident': other, 'name': 'roof'})
    assert answer['ok'] is True

    packet = send(station, 'PASSKEY=%s&stationtype=GW2000A&tempf=61.0' % other)
    assert packet['outTemp'] == 61.0
    assert packet['station'] == 'roof'


def test_a_name_that_would_not_survive_a_config_file_is_refused(station):
    _, _, answer = web(station, '/api/accept',
                       {'ident': 'D' * 32, 'name': 'roof]\n[Station'})

    assert answer['ok'] is False


def test_a_field_name_no_column_could_have_is_refused(station, payload):
    send(station, payload('hp2561ae_pro'))
    _, _, answer = web(station, '/api/field',
                       {'ident': PASSKEY, 'raw': 'tf_ch1', 'field': 'drop table;--'})

    assert answer['ok'] is False


def test_clearing_a_field_puts_it_back_where_it_was(station, payload):
    send(station, payload('hp2561ae_pro'))
    web(station, '/api/field', {'ident': PASSKEY, 'raw': 'tf_ch1',
                                'field': 'soilTemp5'})
    assert send(station, payload('hp2561ae_pro')).get('soilTemp5') == 66.2

    web(station, '/api/field', {'ident': PASSKEY, 'raw': 'tf_ch1', 'field': ''})
    packet = send(station, payload('hp2561ae_pro'))

    assert 'soilTemp5' not in packet


# ---------------------------------------------------------------- the awkward parts


def test_a_broken_settings_file_does_not_stop_the_readings(tmp_path, payload):
    """The weather matters more than the settings. The log says what to fix."""
    (tmp_path / 'web.conf').write_text('[stations\n  broken = ', encoding='utf-8')
    made = UltimatePushDriver(
        port=0, address='127.0.0.1', passkey=PASSKEY, report_file='',
        console_file=str(tmp_path / 'consoles.txt'),
        override_file=str(tmp_path / 'web.conf'))
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
    connection = http.client.HTTPConnection('127.0.0.1', station.listener.ports[1],
                                            timeout=5)
    try:
        connection.request('POST', '/api/field', 'not json at all',
                           {'X-Auth-Token': TOKEN})
        assert connection.getresponse().status == 200
    finally:
        connection.close()
