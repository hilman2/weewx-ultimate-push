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

# What a fresh weewx.conf says before anybody has said where the station is. Somebody
# who leaves these has a station at the north pole, and every sunrise on every page
# is wrong.
UNSET_LOCATION = ('Santa\'s Workshop', 'My Little Town, Oregon', '')
UNSET_COORDINATE = (0.0, 90.0, -90.0)


def steps(driver):
    """Every step, in the order somebody meets them. Each is a dict for the page."""
    found = driver.activity.snapshot()
    # The activity log keeps what was refused, which is history. Whether a console is
    # still being refused is a question about now, and the answer is whether the
    # driver has since been told to accept it. Without this, letting a station in
    # would leave the step outstanding until twenty more refusals had pushed the old
    # ones out of the ring.
    waiting = [w for w in driver.activity.unknown_stations(_nothing)
               if w['ident'] not in driver.known]
    return [
        _hardware(driver, found),
        _refused(driver, waiting),
        _placements(driver, found),
        _columns(driver, found),
        _location(driver),
    ]


def summary(driver):
    """The steps, and whether anything is left."""
    listed = steps(driver)
    outstanding = [s for s in listed if not s['done'] and not s['optional']]
    return {
        'ok': True,
        'done': not outstanding,
        'next': outstanding[0]['id'] if outstanding else None,
        'steps': listed,
    }


def _nothing(text):
    """A redaction that redacts nothing. The counts here never reach the page."""
    return text


def _step(ident, title, done, detail='', optional=False, **extra):
    step = {'id': ident, 'title': title, 'done': done, 'detail': detail,
            'optional': optional}
    step.update(extra)
    return step


# ---------------------------------------------------------------- the steps


def _hardware(driver, found):
    """Nothing has ever uploaded. The commonest place to be stuck, and the one the
    page could say least about until now: it showed an empty list."""
    from . import admin
    if found:
        return _step('hardware', 'Your hardware is uploading', True,
                     "%d station(s) have been heard from." % len(found))

    address = driver.web_address()
    port = driver.data_port()
    return _step(
        'hardware', 'Point your hardware at this machine', False,
        "Nothing has uploaded yet. Set this in whichever app your console uses, "
        "then leave this page open: it notices by itself.",
        protocols=[_pointing(protocol, address, port, driver.data_path())
                   for protocol in driver.enabled])


def _pointing(protocol, address, port, path):
    """One protocol's instructions, with this driver's address filled in.

    The settings and the sentences stay apart. The page lays the first out as a table
    to copy from, and a sentence in that table would read as a field to fill in.
    """
    fill = {'address': address, 'port': port, 'path': path}
    return {
        'name': protocol.name,
        'label': protocol.label,
        'hardware': protocol.hardware,
        'settings': [[label, value % fill] for label, value in protocol.settings],
        'notes': [note % fill for note in protocol.notes],
    }


def _refused(driver, waiting):
    """Something is uploading and being turned away. Either it is theirs and should
    be let in, or somebody else's and the refusal is the point."""
    if not waiting:
        return _step('refused', 'Nothing is being turned away', True)
    return _step(
        'refused',
        '%d station(s) are being refused' % len(waiting), False,
        "This driver answers to the consoles it knows. A second one numbering its "
        "channels from one would otherwise write into the same columns, and "
        "afterwards neither could be recovered. Let it in if it is yours.",
        stations=[{'ident': w['ident'], 'protocol': w['protocol'],
                   'client': w['client'], 'uploads': w['uploads']}
                  for w in waiting])


def _placements(driver, found):
    """Fields nobody but the user can place. The reason this interface exists."""
    pending = []
    for row in found:
        seen = set(row.get('raw_seen', ()))
        for raw in sorted(seen & set(row.get('undecided', {}))):
            pending.append({'ident': row['ident'], 'raw': raw})
    if not pending:
        return _step('placements', 'Every field has somewhere to go', True)
    return _step(
        'placements', '%d field(s) are waiting for you' % len(pending), False,
        "Drivers disagree about where these belong, and the wrong choice mixes two "
        "sensors into one column for good. Nothing is guessed. The Fields tab has "
        "them, with what each column already holds.",
        fields=pending)


def _columns(driver, found):
    """Readings with nowhere to live. They show up as current conditions and are gone
    at the next archive interval, which looks like the driver losing them."""
    missing = []
    for row in found:
        answer = driver.web_columns(row['ident'])
        if answer.get('ok'):
            missing.extend(answer['missing'])
    if not missing:
        return _step('columns', 'Every reading has a column', True)
    return _step(
        'columns', '%d reading(s) have nowhere to live' % len(missing), False,
        "They appear in reports as current conditions and are gone at the next "
        "archive interval. Adding a column rewrites the table, so back up the "
        "database first. The Database columns tab has the commands.",
        fields=[m['field'] for m in missing])


def _location(driver):
    """Where the station is. Not ours to write, so it is shown to paste."""
    station = driver.station_location()
    if station is None:
        return _step('location', 'Where the station is', True,
                     "Cannot read weewx.conf from here, so this is not checked.",
                     optional=True)

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
        return _step('location', 'The station knows where it is', True,
                     "%s, %s / %s" % (station.get('location'),
                                      station.get('latitude'),
                                      station.get('longitude')))
    return _step(
        'location', 'Tell the station where it is', False,
        "Sunrise, sunset, the almanac and the solar figures are all computed from "
        "this. Left as it comes, your station is at the north pole. It lives in "
        "weewx.conf, which WeeWX is running from and which this driver cannot write, "
        "so it takes an edit and a restart.",
        unset=unset,
        block="[Station]\n"
              "    location = the name of your town\n"
              "    latitude = 48.4596\n"
              "    longitude = 11.6539\n"
              "    altitude = 440, meter")
