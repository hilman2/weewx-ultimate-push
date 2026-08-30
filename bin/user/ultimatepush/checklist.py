#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""What is still in the way of a station that records properly.

Not a wizard. A wizard keeps a step number, and a step number is wrong the moment
somebody closes the tab, points a second console at the port, edits the file by hand,
or comes back next month. This works the other way round: it looks at what is true and
says what is not done yet. That answer is right on the first visit and on the
hundredth, it survives a restart, and once everything is done it keeps working as a
health page rather than becoming a thing to dismiss.

Five things stand between installing this and a station whose readings are all
recorded:

    1. The hardware is not pointing here yet.
    2. Something is uploading that this driver will not accept.
    3. A field arrived whose placement only the user can decide.
    4. A reading has no column to live in.
    5. The station does not know where it is.

The last one is not this driver's to fix. It lives in weewx.conf, which WeeWX is
running from and which under a package installation belongs to root. So it is shown
with the block to paste, like everything else here that needs a restart.

Nothing in this module writes anything. It reads the driver and reports.
"""

from typing import TYPE_CHECKING

# For the docstring types only. checklist is imported by driver, so importing
# it back would be a cycle, and nothing here needs either module at runtime.
if TYPE_CHECKING:
    from . import protocols
    from .driver import UltimatePushDriver

# What a fresh weewx.conf says before anybody has said where the station is. Somebody
# who leaves these has a station at the north pole, and every sunrise on every page
# is wrong.
UNSET_LOCATION = ('Santa\'s Workshop', 'My Little Town, Oregon', '')
UNSET_COORDINATE = (0.0, 90.0, -90.0)


def steps(driver):
    """Every step, in the order somebody meets them.

    Args:
        driver (UltimatePushDriver): The running driver, which is where every
            answer comes from.

    Returns:
        list: One dict per step, ready for the page."""
    found = driver.activity.snapshot()
    # The activity log keeps what was refused, which is history. Whether a console is
    # still being refused is a question about now, and the answer is whether the
    # driver has since been told to accept it.
    waiting = driver.web_waiting()
    return [
        _hardware(driver, found),
        _refused(driver, waiting),
        _placements(driver, found),
        _sharing(driver, found),
        _columns(driver, found),
        _location(driver),
    ]


def summary(driver):
    """The steps, and whether anything is left.

    Args:
        driver (UltimatePushDriver): The running driver.

    Returns:
        dict: The steps, which one is next, and whether everything is done."""
    listed = steps(driver)
    outstanding = [s for s in listed if not s['done'] and not s['optional']]
    return {
        'ok': True,
        'done': not outstanding,
        'next': outstanding[0]['id'] if outstanding else None,
        'steps': listed,
    }


def _nothing(text):
    """A redaction that redacts nothing.

    The counts taken here never reach the page, so there is nothing to hide from.

    Args:
        text (str): An upload body.

    Returns:
        str: The same text.
    """
    return text


def _step(ident, title, done, detail='', optional=False, **extra):
    """One step of the checklist, as the page wants it.

    Args:
        ident (str): The step's identity, which the page dispatches on.
        title (str): One line, saying what is or is not the case.
        done (bool): Whether this step is settled.
        detail (str): What to do about it, where there is something to do.
        optional (bool): Whether an unfinished step still counts as outstanding.
        **extra (Any): Anything the page needs for this step in particular.

    Returns:
        dict: The step.
    """
    step = {
        'id': ident,
        'title': title,
        'done': done,
        'detail': detail,
        'optional': optional,
    }
    step.update(extra)
    return step


# ---------------------------------------------------------------- the steps


def _hardware(driver, found):
    """Nothing has ever uploaded, or something was set up here and has not arrived.

    The commonest place to be stuck, and the one the page could say least about until
    now: it showed an empty list.

    The protocol list is carried whether the step is finished or not, because setting
    up a second station is the same job as setting up the first and the page needs
    the same material for it.

    Args:
        driver (UltimatePushDriver): The running driver.
        found (list): The stations that have uploaded.

    Returns:
        dict: The step.
    """
    address = driver.web_address()
    port = driver.data_port()
    protocols = [
        _pointing(protocol, address, port, driver.data_path())
        for protocol in driver.enabled
    ]
    waiting = _set_up_but_not_heard(driver, found, address, port)

    if waiting:
        return _step(
            'hardware',
            'Put the path into the console',
            False,
            "%d station(s) are set up here and have not uploaded yet. Each one has a "
            "path of its own, on the Stations tab. Leave this page open: it notices "
            "the first upload by itself." % len(waiting),
            protocols=protocols,
            created=waiting,
        )
    if found:
        return _step(
            'hardware',
            'Your hardware is uploading',
            True,
            "%d station(s) have been heard from." % len(found),
            protocols=protocols,
            created=[],
        )

    return _step(
        'hardware',
        'Point your hardware at this machine',
        False,
        "Nothing has uploaded yet. Set this in whichever app your console uses, "
        "then leave this page open: it notices by itself.",
        protocols=protocols,
        created=[],
    )


def _set_up_but_not_heard(driver, found, address, port):
    """Stations made in the interface that have never uploaded, with their own paths.

    Held here rather than in the page, so that the settings survive a reload. Somebody
    who set a station up, closed the tab and came back would otherwise have made a
    secret path that nothing will ever show them again.

    Args:
        driver (UltimatePushDriver): The running driver.
        found (list): The stations that have uploaded.
        address (str): This machine's address, as the console has to be told it.
        port (int): The data port.

    Returns:
        list: One entry per station that is set up and still silent.
    """
    from . import protocols as catalogue

    heard = {row['ident'] for row in found}
    waiting = []
    for ident, station in sorted(driver.web_stations.items()):
        if ident in heard or not station.path:
            continue
        named = driver.overrides.stations().get(ident, {}).get('protocol')
        protocol = catalogue.by_name(named) if named else None
        if protocol is None:
            continue
        waiting.append(
            {
                'name': station.name or ident,
                'path': station.path,
                'settings': _pointing(protocol, address, port, station.path),
            }
        )
    return waiting


def _pointing(protocol, address, port, path, ident=None, password=None):
    """One protocol's instructions, with this driver's address filled in.

    The settings and the sentences stay apart. The page lays the first out as a table
    to copy from, and a sentence in that table would read as a field to fill in.

    Args:
        protocol (type[protocols.Protocol]): The protocol class.
        address (str): This machine's address.
        port (int): The data port.
        path (str): The path this station should upload to.
        ident (str | None): What this station is to call itself, for hardware that
            carries an identity of its own rather than an address. None before one
            has been chosen, and then the table says the field is yours to fill in.
        password (str | None): The secret to go with it, on the same terms.

    Returns:
        dict: What to put into the console, as settings and as sentences.
    """
    # 'anything you like' is the truth before a station has been set up: nothing
    # here cares what is in these fields until it has chosen them.
    fill = {
        'address': address,
        'port': port,
        'path': path,
        'ident': ident or 'anything you like',
        'password': password or 'anything you like',
    }
    return {
        'name': protocol.name,
        'label': protocol.label,
        'hardware': protocol.hardware,
        # Whether a station of this kind can be set up before it has ever uploaded.
        # Hardware this driver can hand something to: a path of its own, or an
        # identity and a password. The rest broadcasts or has its identity burnt in,
        # and has to be heard first.
        'can_create': protocol.secret_kind in ('path', 'password'),
        'settings': [[label, value % fill] for label, value in protocol.settings],
        'notes': [note % fill for note in protocol.notes],
    }


def _refused(driver, waiting):
    """Something is uploading and being turned away.

    Either it is theirs and should be let in, or somebody else's and the refusal is
    the point.

    Args:
        driver (UltimatePushDriver): The running driver.
        waiting (list): The stations being refused.

    Returns:
        dict: The step.
    """
    if not waiting:
        return _step('refused', 'Nothing is being turned away', True)
    return _step(
        'refused',
        '%d station(s) are being refused' % len(waiting),
        False,
        "This driver answers to the consoles it knows. A second one numbering its "
        "channels from one would otherwise write into the same columns, and "
        "afterwards neither could be recovered. Let it in if it is yours.",
        stations=[
            {
                'ident': w['ident'],
                'protocol': w['protocol'],
                'client': w['client'],
                'uploads': w['uploads'],
            }
            for w in waiting
        ],
    )


def _placements(driver, found):
    """Fields nobody but the user can place. The reason this interface exists.

    Args:
        driver (UltimatePushDriver): The running driver.
        found (list): The stations that have uploaded.

    Returns:
        dict: The step.
    """
    pending = []
    for row in found:
        seen = set(row.get('raw_seen', ()))
        for raw in sorted(seen & set(row.get('undecided', {}))):
            pending.append({'ident': row['ident'], 'raw': raw})
    if not pending:
        return _step('placements', 'Every field has somewhere to go', True)
    return _step(
        'placements',
        '%d field(s) are waiting for you' % len(pending),
        False,
        "Drivers disagree about where these belong, and the wrong choice mixes two "
        "sensors into one column for good. Nothing is guessed. The Fields tab has "
        "them, with what each column already holds.",
        fields=pending,
    )


def _sharing(driver, found):
    """Readings that are not being written, because another station has the column.

    Used to be "two stations writing one column", which the driver now stops before
    it starts: a column belongs to whoever filled it first, and the main station
    outranks that. So the thing worth showing is no longer the collision. It is what
    the rule costs -- which readings of which station are going nowhere, and who has
    the column they wanted.

    Somebody whose third console is not recording its soil moisture should find that
    out here rather than a month later in an empty graph.

    Args:
        driver (UltimatePushDriver): The running driver.
        found (list): The stations that have uploaded.

    Returns:
        dict: The step, with one entry per reading that went nowhere.
    """
    if len(found) < 2:
        return _step('sharing', 'Nothing is sharing a column', True)

    main = driver._main_ident()
    turned_away, expected = [], 0
    for row in found:
        named = driver.named_by_hand(row['ident'])
        for field in row.get('dropped_fields', ()):
            owner = driver.owners.owner(field)
            if owner == main and field not in named:
                # An extra sensor's wind and pressure, kept out of the main
                # station's columns. That is the role doing what it is for, and a
                # checklist step that stayed red for it would stay red for ever.
                expected += 1
                continue
            turned_away.append(
                {
                    'field': field,
                    'station': row['name'] or row['ident'],
                    'owner': driver.name_of_owner(field),
                }
            )
    if not turned_away:
        return _step(
            'sharing',
            'Nothing is sharing a column',
            True,
            (
                (
                    "%d stations. None writes where another does, and %d reading(s) are "
                    "dropped to keep it that way." % (len(found), expected)
                )
                if expected
                else "%d stations, and none of them writes where another does."
                % len(found)
            ),
        )
    return _step(
        'sharing',
        '%d reading(s) have nowhere of their own to go' % len(turned_away),
        False,
        "A column takes one answer, so these are dropped rather than written over "
        "somebody else's readings. That is the right outcome when the column really "
        "is the other station's. When it is not, give this one a field of its own on "
        "the Fields tab, and add the column if the database has none.",
        fields=[
            {'field': r['field'], 'stations': [r['station']], 'owner': r['owner']}
            for r in sorted(turned_away, key=lambda r: (r['station'], r['field']))
        ],
    )


def _columns(driver, found):
    """Readings with nowhere to live. They show up as current conditions and are gone
    at the next archive interval, which looks like the driver losing them.

    Args:
        driver (UltimatePushDriver): The running driver.
        found (list): The stations that have uploaded.

    Returns:
        dict: The step.
    """
    missing = []
    for row in found:
        answer = driver.web_columns(row['ident'])
        if answer.get('ok'):
            missing.extend(answer['missing'])
    if not missing:
        return _step('columns', 'Every reading has a column', True)
    return _step(
        'columns',
        '%d reading(s) have nowhere to live' % len(missing),
        False,
        "They appear in reports as current conditions and are gone at the next "
        "archive interval. Adding a column changes the table definition and not "
        "its rows, so it is quick, and there is still no undo without a "
        "database first. The Database columns tab has the commands.",
        fields=[m['field'] for m in missing],
    )


def _location(driver):
    """Where the station is. Not ours to write, so it is shown to paste.

    Args:
        driver (UltimatePushDriver): The running driver.

    Returns:
        dict: The step, with the block to paste into weewx.conf.
    """
    station = driver.station_location()
    if station is None:
        return _step(
            'location',
            'Where the station is',
            True,
            "Cannot read weewx.conf from here, so this is not checked.",
            optional=True,
        )

    unset = []
    if str(station.get('location', '')).strip() in UNSET_LOCATION:
        unset.append('location')
    for key in ('latitude', 'longitude'):
        try:
            if float(station.get(key, 0)) in UNSET_COORDINATE:
                unset.append(key)
        except (TypeError, ValueError):
            unset.append(key)

    if not unset:
        return _step(
            'location',
            'The station knows where it is',
            True,
            "%s, %s / %s"
            % (
                station.get('location'),
                station.get('latitude'),
                station.get('longitude'),
            ),
        )
    return _step(
        'location',
        'Tell the station where it is',
        False,
        "Sunrise, sunset, the almanac and the solar figures are all computed from "
        "this. Left as it comes, your station is at the north pole. It lives in "
        "weewx.conf, which WeeWX is running from and which this driver cannot write, "
        "so it takes an edit and a restart.",
        unset=unset,
        block="[Station]\n"
        "    location = the name of your town\n"
        "    latitude = 48.4596\n"
        "    longitude = 11.6539\n"
        "    altitude = 440, meter",
    )
