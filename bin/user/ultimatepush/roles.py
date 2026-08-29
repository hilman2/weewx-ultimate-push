#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""Which station may fill which WeeWX field.

One station needs none of this. It is the station, its readings go to the fields they
belong in, and nothing here does anything. That case has to stay as simple as it was,
so everything below only comes into play once there is a second one.

With two, the question is unavoidable: they both send `outTemp`, and there is one
`outTemp`. Left alone they would take turns writing it, every few seconds, and the
column would hold a mixture that nothing afterwards can separate. That is the same
failure this driver refuses everywhere else, so it refuses it here too.

The answer is a role.

    main   its readings go where they belong. Exactly one station is this.
    extra  its readings are moved out of the way. Temperature and humidity have
           somewhere to go; the rest does not, and is dropped rather than written
           over the main station's.

Honest about the limit: the standard schema has `extraTemp1` to `extraTemp8` and
`extraHumid1` to `extraHumid8`, and nothing of the sort for wind, rain or pressure. So
a second full weather station contributes its temperature and its humidity, and
anything else it sends needs a column and a mapping of its own. The interface says so
rather than pretending otherwise.

The role is a default, not a cage. A field named by hand outranks it, the way a field
named by hand outranks everything else here.
"""

MAIN = 'main'
EXTRA = 'extra'
ROLES = (MAIN, EXTRA)

# What an extra station's readings become, given its channel. Only the two that have
# somewhere to go. Everything else is dealt with by the rule below.
SHIFT = {
    'outTemp': 'extraTemp%d',
    'outHumidity': 'extraHumid%d',
}

# How many channels the standard schema has for them.
CHANNELS = 8


def shifted(field, channel):
    """Where an extra station's reading goes.

    Args:
        field (str): The WeeWX field the reading would have filled.
        channel (int): The station's channel.

    Returns:
        str: The field it is moved to, or None when there is nowhere for it to go.
        Only temperature and humidity have anywhere; see the module docstring.
    """
    pattern = SHIFT.get(field)
    return pattern % channel if pattern else None


def columns_for(channel):
    """The archive columns one extra channel writes into.

    Args:
        channel (int): A channel from 1 to CHANNELS.

    Returns:
        tuple: The WeeWX field names an extra station on that channel fills.
    """
    return tuple(pattern % channel for pattern in SHIFT.values())


def next_channel(taken):
    """The lowest channel that is free.

    Args:
        taken (set): The channels already in use.

    Returns:
        int: The lowest free channel, or None when all of them are used.
    """
    for channel in range(1, CHANNELS + 1):
        if channel not in taken:
            return channel
    return None


def extensions_for(role, channel, catalog_fields):
    """The field map a role implies.

    Built from the station's own catalog, so that only the raw names this hardware
    actually sends are shifted. Returned as an ordinary extension map, which is what
    the mapper already knows how to take, and which a hand-written one then overrides.

    Args:
        role (str): MAIN or EXTRA.
        channel (int): The station's channel, or None if it has not been given one.
        catalog_fields (dict): Raw field name to WeeWX field, from the catalog the
            station's uploads are read with.

    Returns:
        dict: Raw field name to WeeWX field, for the readings that are moved. Empty
        for the main station, which has nothing moved.
    """
    if role != EXTRA or not channel:
        return {}
    moved = {}
    for raw, field in catalog_fields.items():
        target = shifted(field, channel)
        if target:
            moved[raw] = target
    return moved


def collisions(by_station):
    """WeeWX fields more than one station writes.

    Args:
        by_station (dict): Station name to the set of WeeWX fields it has produced.

    Returns:
        dict: Each field more than one station writes, to the list of stations that
        write it, sorted so that the answer is the same every time somebody looks at
        it.
    """
    owners = {}
    for station, fields in by_station.items():
        for field in fields:
            owners.setdefault(field, set()).add(station)
    return {field: sorted(who) for field, who in sorted(owners.items())
            if len(who) > 1}
