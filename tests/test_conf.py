#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""weewx.conf, shown on the page and written back.

Two things are worth a test here, and they are not the obvious one. Writing a value
is nearly free, because configobj does it. What is not free is that the file survives
it: somebody's comments, somebody's quoting, somebody's `location = "Berlin,
Germany"` which is one string and not two. So most of this is round trips.

The other is what the page is not allowed to say. The interface is HTTP, so a
database password that reaches the browser has been sent in the clear over whatever
is in between, and this driver knows the names those settings go by.

A driver is only needed for the last few, where the point is that a route is wired
to a method. Everything before that is the module on a file in tmp_path.
"""

import json
import os

import pytest

from ultimatepush import conf

configobj = pytest.importorskip('configobj', reason="configobj is not installed")


A_FILE = """\
# What this whole file is for
debug = 0

# Where the station is, and what it is called
[Station]
    # Two words, and one of them has a comma in front of it
    location = "Berlin, Germany"   # as somebody left it
    altitude = 35, meter
    rain_year_start = 1

[StdReport]
    HTML_ROOT = public_html
    [[SeasonsReport]]
        skin = Seasons
    [[Defaults]]
        [[[Units]]]
            [[[[Groups]]]]
                group_temperature = degree_C

[StdRESTful]
    [[Wunderground]]
        station = ISOMEWHERE
        password = hunter2
        api_key = 0123456789
"""


@pytest.fixture
def file_at(tmp_path):
    """weewx.conf, as somebody who has been editing it for a year would leave it."""
    path = tmp_path / 'weewx.conf'
    path.write_text(A_FILE, encoding='utf-8')
    return conf.File(str(path))


def entries_of(view, heading):
    """The settings of one section, by the heading the page shows.

    Args:
        view (dict): What conf.File.view returned.
        heading (str): The heading as the file writes it, '[[Wunderground]]' and
            so on.

    Returns:
        dict: Setting name to the whole row, so that a test can name one row and
        then say what about it.
    """
    for section in view['sections']:
        if section['heading'] == heading:
            return {entry['key']: entry for entry in section['entries']}
    raise AssertionError("No section called %s in %s" % (heading, view))


# ---------------------------------------------------------------- what it shows


def test_the_whole_file_is_there_in_the_order_it_is_written(file_at):
    view = file_at.view()
    assert view['ok']
    assert [s['heading'] for s in view['sections']] == [
        "The top of the file",
        '[Station]',
        '[StdReport]',
        '[[SeasonsReport]]',
        '[[Defaults]]',
        '[[[Units]]]',
        '[[[[Groups]]]]',
        '[StdRESTful]',
        '[[Wunderground]]',
    ]


def test_a_setting_at_the_top_of_the_file_is_in_a_section_like_any_other(file_at):
    assert entries_of(file_at.view(), "The top of the file")['debug']['value'] == '0'


def test_a_section_carries_its_place_so_the_page_can_name_it(file_at):
    found = file_at.view()['sections']
    deep = [s for s in found if s['heading'] == '[[[[Groups]]]]'][0]
    assert deep['path'] == ['StdReport', 'Defaults', 'Units', 'Groups']
    assert deep['depth'] == 4


def test_the_comments_come_through_because_they_are_what_the_file_says(file_at):
    """The comment above a setting is usually the only documentation there is."""
    row = entries_of(file_at.view(), '[Station]')['location']
    assert row['comment'] == "Two words, and one of them has a comma in front of it"
    assert row['inline'] == 'as somebody left it'


def test_a_value_is_shown_as_the_file_writes_it(file_at):
    """Quoted where it has to be, so that what is shown can be typed back in.

    Unquoted, `Berlin, Germany` is two values. The box has to show the quotes or
    saving it unchanged would turn one string into a list.
    """
    rows = entries_of(file_at.view(), '[Station]')
    assert rows['location']['value'] == '"Berlin, Germany"'
    assert rows['altitude']['value'] == '35, meter'


def test_a_setting_whose_name_says_password_is_not_sent_to_the_page(file_at):
    """The one thing this page may not do. See conf.SECRETS."""
    rows = entries_of(file_at.view(), '[[Wunderground]]')
    assert rows['password']['hidden']
    assert rows['password']['value'] == ''
    assert rows['api_key']['hidden']
    assert rows['api_key']['value'] == ''
    # And the station id beside them is not a secret, so it is shown.
    assert rows['station']['value'] == 'ISOMEWHERE'


def test_no_secret_is_anywhere_in_what_the_page_is_sent(file_at):
    """Not in a value, not in a comment, not in something added later.

    Written against the whole payload rather than against the row, because the row
    is only where it would be today.
    """
    assert 'hunter2' not in json.dumps(file_at.view())


def test_what_the_engine_is_running_on_is_marked_when_the_file_has_moved_on(file_at):
    """Otherwise "I changed it and nothing happened" has nothing to look at."""
    view = file_at.view({'Station': {'rain_year_start': '7'}})
    row = entries_of(view, '[Station]')['rain_year_start']
    assert row['differs']
    assert row['running'] == '7'


def test_a_setting_the_engine_agrees_with_is_not_marked(file_at):
    view = file_at.view({'Station': {'rain_year_start': '1'}})
    assert not entries_of(view, '[Station]')['rain_year_start']['differs']


def test_a_running_value_is_never_shown_for_a_secret(file_at):
    """It differs, and saying what it is would be the leak the row exists to avoid."""
    view = file_at.view({'StdRESTful': {'Wunderground': {'password': 'something'}}})
    row = entries_of(view, '[[Wunderground]]')['password']
    assert row['differs']
    assert row['running'] == ''


def test_a_file_that_cannot_be_read_says_so_rather_than_raising(tmp_path):
    broken = tmp_path / 'weewx.conf'
    broken.write_text("[Station\n", encoding='utf-8')
    answer = conf.File(str(broken)).view()
    assert not answer['ok']
    assert 'weewx.conf' in answer['error']


def test_a_driver_started_without_a_file_says_that_instead_of_failing():
    answer = conf.File(None).view()
    assert not answer['ok']
    assert 'without a configuration file' in answer['error']


@pytest.mark.skipif(os.name != 'posix', reason="Needs POSIX file modes")
def test_a_file_this_process_cannot_write_is_still_worth_showing(tmp_path):
    """weewx.conf that is root's, on an installation nobody has changed for this.

    The page is worth having read-only, and it says which it is before anybody
    types into it.
    """
    path = tmp_path / 'weewx.conf'
    path.write_text(A_FILE, encoding='utf-8')
    path.chmod(0o444)
    try:
        view = conf.File(str(path)).view()
        assert view['ok']
        assert not view['writable']
        assert entries_of(view, '[Station]')['altitude']['value'] == '35, meter'
    finally:
        path.chmod(0o644)


# ---------------------------------------------------------------- what it writes


def test_changing_a_value_leaves_everything_else_in_the_file_alone(file_at):
    """The reason this reads and writes the file rather than rebuilding it."""
    ok, message = file_at.set(['Station'], 'rain_year_start', '7')
    assert ok, message
    written = open(file_at.path, encoding='utf-8').read()
    assert 'rain_year_start = 7' in written
    assert '# What this whole file is for' in written
    assert '# Two words, and one of them has a comma in front of it' in written
    assert 'as somebody left it' in written
    assert 'group_temperature = degree_C' in written


def snapshot(node):
    """Every value and every comment of a section, nested, for comparing two reads.

    Not the bytes of the file: the spacing in front of an inline comment is
    configobj's to choose and it writes four spaces where somebody typed three.
    What has to survive a save is the content, which is this.

    Args:
        node (configobj.Section): The section to describe, or the whole file.

    Returns:
        dict: Its scalars, the comments above and beside each of them, and the same
        again for every section inside it.
    """
    return {
        'values': {key: node[key] for key in node.scalars},
        'comments': {key: node.comments.get(key) for key in node},
        'inline': {key: node.inline_comments.get(key) for key in node},
        'sections': {name: snapshot(node[name]) for name in node.sections},
    }


def test_a_value_saved_unchanged_leaves_the_file_saying_the_same_thing(file_at):
    """The round trip that matters most, because it is the one nobody means to do.

    Somebody clicks Save on a row they were only looking at. If the quoting or the
    lists do not survive that, the file has been damaged by a page that reported
    success.
    """
    was = snapshot(configobj.ConfigObj(file_at.path, encoding='utf-8'))
    view = file_at.view()
    for section in view['sections']:
        for entry in section['entries']:
            if entry['single'] and not entry['hidden']:
                ok, message = file_at.set(section['path'], entry['key'], entry['value'])
                assert ok, message
    assert snapshot(configobj.ConfigObj(file_at.path, encoding='utf-8')) == was


def test_a_string_with_a_comma_in_it_stays_one_string(file_at):
    ok, message = file_at.set(['Station'], 'location', '"Hamburg, Germany"')
    assert ok, message
    parsed = configobj.ConfigObj(file_at.path, encoding='utf-8')
    assert parsed['Station']['location'] == 'Hamburg, Germany'


def test_values_separated_by_commas_become_a_list(file_at):
    """Which is what the same text means in the file, so it is what it means here."""
    ok, message = file_at.set(['Station'], 'altitude', '120, foot')
    assert ok, message
    parsed = configobj.ConfigObj(file_at.path, encoding='utf-8')
    assert parsed['Station']['altitude'] == ['120', 'foot']


def test_a_value_that_names_another_setting_is_left_as_the_file_writes_it(file_at):
    """WeeWX reads this file with interpolation on and expands %(WEEWX_ROOT)s. This
    page has to show and write the line, not the expansion, or saving a row nobody
    changed would burn the current value into the file."""
    ok, message = file_at.add(['Station'], 'somewhere', '%(WEEWX_ROOT)s/skins')
    assert ok, message
    assert entries_of(file_at.view(), '[Station]')['somewhere']['value'] == (
        '%(WEEWX_ROOT)s/skins'
    )


def test_a_setting_with_nothing_after_the_equals_shows_an_empty_box(file_at):
    ok, message = file_at.add(['Station'], 'nothing', '')
    assert ok, message
    assert entries_of(file_at.view(), '[Station]')['nothing']['value'] == ''


def test_a_setting_that_is_not_in_the_file_is_refused_rather_than_created(file_at):
    """A typed key that is not there is a typo, and a typo written here is a
    setting that looks set and does nothing."""
    ok, message = file_at.set(['Station'], 'altitud', '35')
    assert not ok
    assert "[Station] has no setting called 'altitud'." == message


def test_adding_one_that_is_already_there_is_refused(file_at):
    ok, message = file_at.add(['Station'], 'altitude', '35')
    assert not ok
    assert 'already has' in message


def test_a_setting_can_be_added_to_a_section_that_has_none(file_at):
    ok, message = file_at.add(
        ['StdReport', 'Defaults', 'Units'], 'unit_system', 'metric'
    )
    assert ok, message
    parsed = configobj.ConfigObj(file_at.path, encoding='utf-8')
    assert parsed['StdReport']['Defaults']['Units']['unit_system'] == 'metric'


def test_a_section_that_is_not_in_the_file_is_named_in_the_refusal(file_at):
    ok, message = file_at.add(['StdReport', 'Nope'], 'skin', 'Mine')
    assert not ok
    assert message == "[[Nope]] is not in the file."


def test_a_value_holding_a_hash_is_refused_rather_than_half_written(file_at):
    """Unquoted, everything after it is a comment, so the value stored would not be
    the value typed and nothing would say so."""
    ok, message = file_at.add(['Station'], 'note', 'red # and more')
    assert not ok
    assert message == conf.WOULD_BE_A_COMMENT
    assert 'note' not in configobj.ConfigObj(file_at.path, encoding='utf-8')['Station']


def test_a_quoted_hash_is_a_value_like_any_other(file_at):
    ok, message = file_at.add(['Station'], 'note', '"red # and more"')
    assert ok, message
    parsed = configobj.ConfigObj(file_at.path, encoding='utf-8')
    assert parsed['Station']['note'] == 'red # and more'


def test_a_name_a_configuration_file_could_not_carry_is_refused(file_at):
    for name in ('', '   ', 'a=b', '[Station]', 'x#y', 'a' * (conf.LONGEST + 1)):
        ok, message = file_at.add(['Station'], name, '1')
        assert not ok, name


def test_a_value_cannot_run_over_more_than_one_line(file_at):
    ok, message = file_at.add(['Station'], 'note', 'one\ntwo')
    assert not ok
    assert 'one line' in message


def test_an_empty_box_does_not_wipe_a_password(file_at):
    """The page sends no value for these, so an empty one is a mistake, not a wish."""
    ok, message = file_at.set(['StdRESTful', 'Wunderground'], 'password', '')
    assert not ok
    assert 'wipe' in message
    parsed = configobj.ConfigObj(file_at.path, encoding='utf-8')
    assert parsed['StdRESTful']['Wunderground']['password'] == 'hunter2'


def test_a_password_can_still_be_changed(file_at):
    ok, message = file_at.set(['StdRESTful', 'Wunderground'], 'password', 'other')
    assert ok, message
    parsed = configobj.ConfigObj(file_at.path, encoding='utf-8')
    assert parsed['StdRESTful']['Wunderground']['password'] == 'other'


def test_a_setting_can_be_taken_out(file_at):
    ok, message = file_at.remove(['Station'], 'rain_year_start')
    assert ok, message
    assert (
        'rain_year_start'
        not in configobj.ConfigObj(file_at.path, encoding='utf-8')['Station']
    )


def test_taking_out_one_that_is_not_there_is_refused(file_at):
    ok, message = file_at.remove(['Station'], 'nope')
    assert not ok
    assert "no setting called 'nope'" in message


def test_a_section_can_be_added_under_one_that_is_there(file_at):
    ok, message = file_at.add_section(['StdReport', 'MyReport'])
    assert ok, message
    parsed = configobj.ConfigObj(file_at.path, encoding='utf-8')
    assert 'MyReport' in parsed['StdReport'].sections


def test_a_section_whose_parent_is_missing_is_refused(file_at):
    """A section nobody reads, and asking for it means the path was typed wrong."""
    ok, message = file_at.add_section(['Nope', 'MyReport'])
    assert not ok
    assert message == "[Nope] is not in the file."


def test_an_empty_section_goes_without_being_asked_twice(file_at):
    file_at.add_section(['StdReport', 'MyReport'])
    ok, message = file_at.remove_section(['StdReport', 'MyReport'])
    assert ok, message


def test_a_section_that_holds_something_has_to_be_said_twice(file_at):
    """Removing [StdReport] takes six reports with it, and the count says so."""
    ok, message = file_at.remove_section(['StdReport'])
    assert not ok
    assert 'holds 3 settings' in message
    ok, message = file_at.remove_section(['StdReport'], force=True)
    assert ok, message
    assert 'StdReport' not in configobj.ConfigObj(file_at.path, encoding='utf-8')


def test_what_the_file_said_before_is_kept_beside_it(file_at):
    file_at.set(['Station'], 'rain_year_start', '7')
    assert open(file_at.path + conf.BACKUP, encoding='utf-8').read() == A_FILE


def test_the_file_is_read_again_before_every_write(file_at):
    """A change made in a terminal between two clicks on the page is carried over.

    Nothing is held between calls, so this is really a test that nothing is.
    """
    file_at.view()
    with open(file_at.path, 'a', encoding='utf-8') as handle:
        handle.write("\n[Whatever]\n    x = 1\n")
    ok, message = file_at.set(['Station'], 'rain_year_start', '7')
    assert ok, message
    parsed = configobj.ConfigObj(file_at.path, encoding='utf-8')
    assert parsed['Whatever']['x'] == '1'
    assert parsed['Station']['rain_year_start'] == '7'


@pytest.mark.skipif(os.name != 'posix', reason="Needs POSIX file modes")
def test_a_file_that_cannot_be_written_says_which_file(tmp_path):
    """Under a package installation this is the answer, and it names the path so
    that whoever has to go and edit it knows where."""
    path = tmp_path / 'weewx.conf'
    path.write_text(A_FILE, encoding='utf-8')
    path.chmod(0o444)
    try:
        ok, message = conf.File(str(path)).set(['Station'], 'rain_year_start', '7')
        assert not ok
        assert str(path) in message
    finally:
        path.chmod(0o644)


@pytest.mark.skipif(os.name != 'posix', reason="Needs POSIX file modes")
def test_a_writable_file_in_a_directory_that_is_not_can_still_be_changed(tmp_path):
    """The package installation, after the one change somebody makes for this.

    /etc/weewx belongs to root and weewx.conf has been given to the weewx user. If a
    writable directory were also required, that change would do nothing, and the
    whole page would be read-only on the commonest installation.
    """
    directory = tmp_path / 'etc'
    directory.mkdir()
    path = directory / 'weewx.conf'
    path.write_text(A_FILE, encoding='utf-8')
    beside = tmp_path / 'lib'
    beside.mkdir()
    directory.chmod(0o555)
    try:
        file_at = conf.File(str(path), backup_to=str(beside))
        assert file_at.view()['writable']
        ok, message = file_at.set(['Station'], 'rain_year_start', '7')
        assert ok, message
        assert 'rain_year_start = 7' in path.read_text(encoding='utf-8')
        # The backup cannot go beside the file, so it goes where the driver's own
        # settings file already is.
        assert file_at.backup_path() == str(beside / ('weewx.conf' + conf.BACKUP))
        assert (beside / ('weewx.conf' + conf.BACKUP)).read_text(
            encoding='utf-8'
        ) == A_FILE
    finally:
        directory.chmod(0o755)


@pytest.mark.skipif(os.name != 'posix', reason="Needs POSIX file modes")
def test_the_mode_the_file_had_is_the_mode_it_keeps(file_at):
    """It is replaced rather than filled, so the mode has to be carried over. A
    weewx.conf that came back world-readable would be a leak this page caused."""
    os.chmod(file_at.path, 0o600)
    ok, message = file_at.set(['Station'], 'rain_year_start', '7')
    assert ok, message
    assert os.stat(file_at.path).st_mode & 0o777 == 0o600


def test_nothing_half_written_is_left_behind(file_at):
    file_at.set(['Station'], 'rain_year_start', '7')
    assert not os.path.exists(file_at.path + '.new')
