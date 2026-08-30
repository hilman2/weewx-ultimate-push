#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""Which database columns a station actually needs.

A reading only survives the archive interval if the table has a column for it. The
standard schema has 113 of them, and Ecowitt hardware can fill four times that, so
something has to give.

Two ways to handle it. Ship a schema with every field anyone might own, which is what
the alternatives do, and carry four hundred columns for the twelve sensors in the
garden. Or look at what the hardware actually sends and add those.

This does the second. It needs a payload, not a catalog, which is why it lives next to
the listener rather than in the installer.
"""

from typing import Dict, List, Set

# Types by unit group, for the columns we have to create. REAL for anything measured,
# INTEGER for anything counted.
COUNTED = frozenset(
    [
        'group_count',
        'group_time',
        'group_boolean',
        'group_data',
    ]
)

# How far a numbered family is offered past what the schema ships. The schema stops
# at eight extra temperatures because that was enough when it was written; a gateway
# with three WN34 probes, two indoor sensors and a soil array runs out in an
# afternoon. The ones past the end have no column yet, which the interface says, and
# it offers to make one. That is the whole point of offering them.
UPTO = 16


def schema_fields():
    """The fields WeeWX's standard schema already has. Needs WeeWX importable."""
    from weewx.schemas.wview_extended import table

    return {name for name, _type in table}


def families(names, least=2):
    """The numbered families in a set of field names, as {base: highest}.

    extraTemp1 to extraTemp8 is a family. appTemp1, co2 and pm2_5 are not, which is
    what `least` is for. A family is a series hardware can have more of than the
    schema does.

    Args:
        names (iterable): WeeWX field names.
        least (int): How many members a series needs before it counts as a family.

    Returns:
        dict: The base name of each family, to the highest number found in it.
    """
    import re

    found = {}  # type: Dict[str, Set[int]]
    for name in names:
        match = re.match(r'^(.*?[A-Za-z_])([0-9]+)$', name)
        if match:
            found.setdefault(match.group(1), set()).add(int(match.group(2)))
    return {
        base: max(numbers)
        for base, numbers in found.items()
        if len(numbers) >= least and numbers == set(range(1, max(numbers) + 1))
    }


def by_group(upto=UPTO):
    """Fields grouped by what they measure, for the selector that asks where a
    reading should go.

    Offering a wind speed as a place to put a temperature is noise, and worse than
    noise: somebody will pick it. So the answer is grouped, and the group that suits
    the reading is offered first.

    Numbered families run past the end of the schema, as far as `upto`. The schema
    has eight extra temperatures; hardware that sends a ninth is ordinary. Without
    this the box simply has no answer for it, and the way people deal with that today
    is to write extraTemp9 into a configuration file by hand.

    Args:
        upto (int): How far to run a numbered family past the end of the schema.

    Returns:
        tuple: (groups, ungrouped), where `groups` is unit group to field names and
        `ungrouped` is the fields WeeWX knows no group for. A few of its own columns
        are in the second list, forecast among them, and those are still perfectly
        good places to put something.
    """
    import weewx.units

    known = {
        name
        for name in schema_fields()
        if name not in ('dateTime', 'usUnits', 'interval')
    }
    everything = set(known)
    for base, highest in families(known).items():
        group = weewx.units.obs_group_dict.get(base + '1')
        for number in range(highest + 1, max(upto, highest) + 1):
            name = '%s%d' % (base, number)
            everything.add(name)
            if group:
                weewx.units.obs_group_dict.setdefault(name, group)

    groups = {}  # type: Dict[str, List[str]]
    ungrouped = []
    for name in sorted(everything, key=in_family_order):
        group = weewx.units.obs_group_dict.get(name)
        if group:
            groups.setdefault(group, []).append(name)
        else:
            ungrouped.append(name)
    return groups, ungrouped


def in_family_order(name):
    """A sort key that puts extraTemp9 after extraTemp8 rather than extraTemp10.

    Args:
        name (str): A WeeWX field name.

    Returns:
        tuple: The name with any trailing number removed, and that number, so that
        sorting is by family and then numerically within it.
    """
    import re

    match = re.match(r'^(.*?[A-Za-z_])([0-9]+)$', name)
    if match:
        return (match.group(1), int(match.group(2)))
    return (name, 0)


def missing(packet, groups, known=None):
    """Return the columns a packet needs and the database does not have.

    Args:
        packet (dict): A loop packet, i.e. what the driver produced.
        groups (dict): WeeWX field -> unit group, for choosing a column type.
        known (set | None): Fields the database already has. Defaults to the standard schema.

    Returns:
        list: (field, sql_type) pairs, sorted, without the bookkeeping fields.
    """
    if known is None:
        known = schema_fields()
    wanted = []
    for field in sorted(packet):
        if field in ('dateTime', 'usUnits', 'interval') or field in known:
            continue
        sql_type = 'INTEGER' if groups.get(field) in COUNTED else 'REAL'
        wanted.append((field, sql_type))
    return wanted


def commands(wanted, config='/etc/weewx/weewx.conf'):
    """Render columns as the weectl commands that create them.

    Args:
        wanted (list): (field, sql_type) pairs, as returned by `missing`.
        config (str): The path to weewx.conf, for the --config argument.

    Returns:
        list: One command line per column.
    """
    return [
        "weectl database add-column %s --type %s --config=%s -y" % (field, sql, config)
        for field, sql in wanted
    ]


def existing(config_path, binding='wx_binding'):
    """The columns the archive table actually has.

    Not the same thing as the schema. The schema says what a fresh database would be
    given; this says what is in front of us. A database made by an older WeeWX, or
    with a schema of somebody's own, has just as much right to exist, and telling
    somebody a column is ready when it is not is worse than saying nothing.

    Args:
        config_path (str): The path to weewx.conf.
        binding (str): The data binding to read.

    Returns:
        set: The column names the archive table has.
    """
    with _manager(config_path, binding) as manager:
        return set(manager.sqlkeys)


def add(config_path, field, sql_type='REAL', binding='wx_binding'):
    """Add one column to the archive table, and say what happened.

    One ALTER TABLE, which is what weectl database add-column does and no more. On
    SQLite that changes the table definition and not its rows, so it costs the same
    on a database of ten records and one of ten million.

    There is deliberately no way here to take a column away. Dropping one in SQLite
    means rebuilding the table around it, and a mistake there is not a mistake
    anybody recovers from without a backup.

    Args:
        config_path (str): The path to weewx.conf.
        field (str): The column to add.
        sql_type (str): REAL or INTEGER. Anything else is refused.
        binding (str): The data binding to write to.

    Returns:
        tuple: (ok, message), where the message is fit to show somebody whether or
        not it worked.
    """
    field = str(field or '').strip()
    if not field:
        return False, "No column named."
    if sql_type not in ('REAL', 'INTEGER'):
        return False, "A column is REAL or INTEGER, not '%s'." % sql_type
    try:
        with _manager(config_path, binding) as manager:
            if field in manager.sqlkeys:
                return True, "The database already has a column '%s'." % field
            manager.add_column(field, sql_type)
    except Exception as e:  # pylint: disable=broad-except
        return False, "The database would not take it: %s" % e
    return True, "Added the column '%s' as %s." % (field, sql_type)


def _manager(config_path, binding):
    """A WeeWX database manager, opened from a configuration file.

    Args:
        config_path (str): The path to weewx.conf.
        binding (str): The data binding to open.

    Returns:
        A manager, to be used as a context manager.
    """
    import weecfg
    import weewx.manager

    _, config_dict = weecfg.read_config(config_path)
    return weewx.manager.open_manager_with_config(config_dict, binding)


def occupied(config_path, binding='wx_binding'):
    """Which archive columns already hold data, and how much.

    This is what stands between a driver change and a ruined series. If a field this
    driver writes to already has history, that history came from somewhere else, and
    the two are about to be mixed in one column.

    One pass over the table, so it takes a moment on a large database.

    Args:
        config_path (str): The path to weewx.conf.
        binding (str): The data binding to read.

    Returns:
        dict: Each column that holds data, to (number of rows, timestamp of the most
        recent one). Columns that hold nothing are left out.
    """
    with _manager(config_path, binding) as manager:
        fields = [
            f for f in manager.sqlkeys if f not in ('dateTime', 'usUnits', 'interval')
        ]
        counts = ', '.join(
            'COUNT(%s), MAX(CASE WHEN %s IS NOT NULL THEN dateTime END)' % (f, f)
            for f in fields
        )
        row = manager.getSql("SELECT %s FROM %s" % (counts, manager.table_name))

    used = {}
    for index, field in enumerate(fields):
        count, last = row[index * 2], row[index * 2 + 1]
        if count:
            used[field] = (count, last)
    return used
