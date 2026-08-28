#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""Test which columns a station turns out to need."""

import pytest

from ultimatepush import columns
from helpers import mapper_for

SCHEMA = {'dateTime', 'usUnits', 'interval', 'outTemp', 'soilTemp1', 'soilTemp2'}


def test_only_what_is_missing():
    packet = {'dateTime': 1, 'usUnits': 1, 'outTemp': 59.7,
              'soilTemp1': 66.2, 'soilTemp9': 61.5}

    assert columns.missing(packet, {}, known=SCHEMA) == [('soilTemp9', 'REAL')]


def test_counted_things_are_integers():
    packet = {'lightning_num': 0.0, 'lightning_time': 1787604643.0, 'vpd': 0.047}
    groups = {'lightning_num': 'group_count', 'lightning_time': 'group_time',
              'vpd': 'group_pressure'}

    assert columns.missing(packet, groups, known=SCHEMA) == [
        ('lightning_num', 'INTEGER'),
        ('lightning_time', 'INTEGER'),
        ('vpd', 'REAL'),
    ]


def test_a_real_station_needs_a_manageable_number(payload):
    """The point of doing this from a payload: a dozen columns, not four hundred."""
    mapper = mapper_for()
    packet, _ = mapper.to_packet(payload('hp2561ae_pro'))
    wanted = columns.missing(packet, mapper.wanted_groups(), known=SCHEMA)

    assert len(wanted) < 40


def test_commands_are_ready_to_paste():
    lines = columns.commands([('soilTemp9', 'REAL')], config='/etc/weewx/weewx.conf')

    assert lines == ['weectl database add-column soilTemp9 --type REAL '
                     '--config=/etc/weewx/weewx.conf -y']


def test_the_standard_schema_is_what_we_compare_against():
    pytest.importorskip('weewx', reason="WeeWX is not installed")

    fields = columns.schema_fields()
    assert 'outTemp' in fields
    assert 'soilTemp4' in fields
    assert 'soilTemp9' not in fields


def test_occupied_needs_a_database():
    """Without one, the check says so rather than pretending everything is free."""
    pytest.importorskip('weewx', reason="WeeWX is not installed")

    with pytest.raises(Exception):
        columns.occupied('/nonexistent/weewx.conf')


# ---------------------------------------------------- past the end of the schema


def test_numbered_families_are_found_and_the_odd_ones_are_not():
    """extraTemp1..8 is a family. appTemp1, co2 and pm2_5 are one field each that
    happens to end in a digit, and offering appTemp2 would be an invention."""
    found = columns.families(columns.schema_fields())

    assert found['extraTemp'] == 8
    assert found['soilMoist'] == 4
    assert 'appTemp' not in found
    assert 'co' not in found
    assert 'pm2_' not in found


def test_a_family_is_offered_past_where_the_schema_stops():
    """The schema has eight extra temperatures. A gateway with three WN34 probes and
    two indoor sensors passes that on a normal afternoon, and the way people deal
    with it today is to write extraTemp9 into a file by hand."""
    pytest.importorskip('weewx', reason="WeeWX is not installed")
    groups, _ungrouped = columns.by_group()

    warm = groups['group_temperature']
    assert 'extraTemp9' in warm
    assert 'extraTemp16' in warm
    assert 'extraTemp17' not in warm

    # And in the order somebody reads them, not the order a string sort gives.
    assert warm.index('extraTemp9') < warm.index('extraTemp10')


def test_what_is_offered_carries_its_unit_group():
    """Otherwise a report would not know how to format extraTemp9, and picking it
    would be a worse answer than not offering it."""
    pytest.importorskip('weewx', reason="WeeWX is not installed")
    import weewx.units
    columns.by_group()

    assert weewx.units.obs_group_dict.get('extraTemp12') == 'group_temperature'


# ---------------------------------------------------- the database itself


def a_database(tmp_path):
    """A real WeeWX database, because a column is not added to a mock."""
    pytest.importorskip('weewx', reason="WeeWX is not installed")
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
    return config.filename


def test_existing_reads_the_table_rather_than_the_schema(tmp_path):
    """A database made by an older WeeWX has fewer columns than the schema says, and
    telling somebody a column is ready when it is not sends them looking for a fault
    in the wrong place."""
    where = a_database(tmp_path)

    have = columns.existing(where)

    assert 'outTemp' in have
    assert 'extraTemp8' in have
    assert 'extraTemp9' not in have


def test_a_column_can_be_added_and_says_so(tmp_path):
    """The same ALTER TABLE weectl runs, without leaving the page for a terminal."""
    where = a_database(tmp_path)

    ok, message = columns.add(where, 'extraTemp9')

    assert ok, message
    assert 'extraTemp9' in columns.existing(where)


def test_adding_a_column_twice_is_not_an_error(tmp_path):
    """Two people with the page open, or one who clicked twice."""
    where = a_database(tmp_path)
    columns.add(where, 'extraTemp9')

    ok, message = columns.add(where, 'extraTemp9')

    assert ok
    assert 'already' in message


def test_a_column_type_is_one_of_two(tmp_path):
    """Anything else would be somebody putting SQL through this."""
    where = a_database(tmp_path)

    ok, message = columns.add(where, 'nonsense', 'TEXT; DROP TABLE archive')

    assert ok is False
    assert 'REAL or INTEGER' in message
    assert 'nonsense' not in columns.existing(where)


def test_a_name_no_column_could_have_is_refused(tmp_path):
    where = a_database(tmp_path)

    ok, _message = columns.add(where, '')

    assert ok is False
