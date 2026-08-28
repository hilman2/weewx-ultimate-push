#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""One view of every field, and one owner per column.

The interface used to show fields one station at a time. That is the wrong axis. The
question somebody has is not "what does this station send", it is "who fills
outTemp", and with two stations that answer was spread over two pages, neither of
which could show the collision that matters.

So there is one view, and a WeeWX field takes one answer. Picking one that is taken
says who has it and changes nothing until somebody says yes.
"""

import http.client

import pytest

pytest.importorskip('weewx', reason="WeeWX is not installed")

from ultimatepush import mapping, roles                  # noqa: E402
from ultimatepush.driver import UltimatePushDriver       # noqa: E402


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
        connection.getresponse().read()
    finally:
        connection.close()


def send(driver, path, body):
    post(driver, path, body)
    return next(driver.genLoopPackets())


def two_stations(driver, payload):
    """A main station and an extra one, both having uploaded once."""
    _, garden = driver.web_create('ecowitt', 'garden')
    _, roof = driver.web_create('ecowitt', 'roof')
    driver.web_role('path:' + roof['path'], roles.EXTRA)
    send(driver, garden['path'], payload('hp2561ae_pro'))
    send(driver, roof['path'], payload('hp2561ae_pro'))
    return garden, roof


# ---------------------------------------------------------------- the view


def test_every_station_is_in_one_view(driver, payload):
    two_stations(driver, payload)

    view = driver.web_fields()

    assert view['ok']
    assert sorted(s['name'] for s in view['stations']) == ['garden', 'roof']
    for station in view['stations']:
        assert station['rows']
        assert {'raw', 'field', 'column', 'group'} <= set(station['rows'][0])


def test_the_view_says_who_fills_each_field(driver, payload):
    """This is the whole reason for one view instead of two."""
    two_stations(driver, payload)

    holders = driver.web_fields()['holders']

    assert holders['outTemp']['name'] == 'garden'
    assert holders['outTemp']['raw'] == 'tempf'
    # The extra station's temperature was moved out of the way, so it holds a
    # channel of its own rather than fighting for outTemp.
    assert holders['extraTemp1']['name'] == 'roof'


def test_a_row_knows_whether_the_database_really_has_the_column(driver, payload):
    """Not whether the schema says so. A database made by an older WeeWX has fewer
    columns, and saying 'column ready' about one that is not there sends somebody
    looking for a fault in the wrong place."""
    two_stations(driver, payload)

    rows = [s for s in driver.web_fields()['stations']
            if s['name'] == 'garden'][0]['rows']
    warm = [r for r in rows if r['field'] == 'outTemp'][0]
    rain = [r for r in rows if r['field'] == 'dayRain'][0]

    assert warm['column'] is True          # in the schema
    assert rain['column'] is False         # not in the schema


# ---------------------------------------------------------------- one owner


def test_taking_a_field_somebody_else_has_asks_first(driver, payload):
    """Two sensors in one column take turns every few seconds, and afterwards
    nothing can tell them apart. So the answer is a question, not a change."""
    _garden, roof = two_stations(driver, payload)
    before = driver.web_fields()['holders']['outTemp']

    answer = driver.web_set_field('path:' + roof['path'], 'tempf', 'outTemp')

    assert answer['ok'] is False
    assert answer['conflict'] is True
    assert answer['holder']['name'] == 'garden'
    assert 'garden' in answer['message']
    assert driver.web_fields()['holders']['outTemp'] == before


def test_saying_yes_moves_it_and_leaves_the_old_one_nowhere(driver, payload):
    """Not back to the catalog, which would put it straight back into the column it
    was just taken out of."""
    _garden, roof = two_stations(driver, payload)

    answer = driver.web_set_field('path:' + roof['path'], 'tempf', 'outTemp',
                                  force=True)

    assert answer['ok'], answer['message']
    assert driver.web_fields()['holders']['outTemp']['name'] == 'roof'

    garden_rows = [s for s in driver.web_fields()['stations']
                   if s['name'] == 'garden'][0]['rows']
    warm = [r for r in garden_rows if r['raw'] == 'tempf'][0]
    assert warm['nowhere'] is True
    assert warm['field'] == ''


def test_a_reading_placed_nowhere_is_not_written(driver, payload):
    """The point of the whole exercise. A row that says nowhere has to mean the
    column stays empty, not that the catalog quietly fills it again."""
    garden, _roof = two_stations(driver, payload)

    driver.web_set_field('path:' + garden['path'], 'tempf', mapping.NOWHERE)
    packet = send(driver, garden['path'], payload('hp2561ae_pro'))

    assert 'outTemp' not in packet
    assert packet['barometer'] is not None      # and the rest is untouched


def test_putting_a_field_back_where_it_was_is_not_a_conflict(driver, payload):
    """Otherwise every page would refuse the value it is already showing."""
    garden, _roof = two_stations(driver, payload)

    answer = driver.web_set_field('path:' + garden['path'], 'tempf', 'outTemp')

    assert answer['ok'], answer.get('message')


def test_a_free_field_is_taken_without_asking(driver, payload):
    _garden, roof = two_stations(driver, payload)

    answer = driver.web_set_field('path:' + roof['path'], 'tempf', 'extraTemp12')

    assert answer['ok'], answer['message']
    assert driver.web_fields()['holders']['extraTemp12']['name'] == 'roof'


# ---------------------------------------------------------------- the column


def test_a_column_can_be_made_from_the_page(tmp_path, payload):
    """The reason any of this exists: no terminal, no editor."""
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
                                                initialize=True):
        pass

    made = UltimatePushDriver(
        port=0, address='127.0.0.1', report_file='', config_dict=config,
        console_file=str(tmp_path / 'consoles.txt'),
        override_file=str(tmp_path / 'web.conf'))
    try:
        _, garden = made.web_create('ecowitt', 'garden')
        send(made, garden['path'], payload('hp2561ae_pro'))

        rows = made.web_fields()['stations'][0]['rows']
        rain = [r for r in rows if r['field'] == 'dayRain'][0]
        assert rain['column'] is False

        answer = made.web_add_column('dayRain')
        assert answer['ok'], answer['message']

        rows = made.web_fields()['stations'][0]['rows']

        rain = [r for r in rows if r['field'] == 'dayRain'][0]
        assert rain['column'] is True
    finally:
        made.closePort()


def test_a_counted_thing_gets_an_integer_column(driver, payload):
    """REAL for anything measured, INTEGER for anything counted. Getting that wrong
    is not fatal and it is still wrong."""
    _garden, _roof = two_stations(driver, payload)

    assert driver._column_type('lightning_num') == 'INTEGER'
    assert driver._column_type('outTemp') == 'REAL'


def test_without_a_config_file_it_says_so_rather_than_failing(driver, payload):
    """A driver started from a test or a diagnostic run has no weewx.conf to find
    the database with. The command still works, so it is the answer."""
    two_stations(driver, payload)

    answer = driver.web_add_column('dayRain')

    assert answer['ok'] is False
    assert 'weectl database add-column dayRain' in answer['message']


def test_the_two_tabs_agree_about_what_the_database_has(tmp_path, payload):
    """The Fields tab read the archive table and the Database columns tab read the
    schema, so one said 'column ready' and the other said the same reading had
    nowhere to live. Both about the same column, on the same page."""
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
                                                initialize=True):
        pass

    made = UltimatePushDriver(
        port=0, address='127.0.0.1', report_file='', config_dict=config,
        console_file=str(tmp_path / 'consoles.txt'),
        override_file=str(tmp_path / 'web.conf'))
    try:
        _, garden = made.web_create('ecowitt', 'garden')
        send(made, garden['path'], payload('hp2561ae_pro'))
        ident = made.web_fields()['stations'][0]['ident']

        made.web_add_column('dayRain')

        rows = made.web_fields()['stations'][0]['rows']
        assert [r for r in rows if r['field'] == 'dayRain'][0]['column'] is True
        missing = {row['field'] for row in made.web_columns(ident)['missing']}
        assert 'dayRain' not in missing
    finally:
        made.closePort()
