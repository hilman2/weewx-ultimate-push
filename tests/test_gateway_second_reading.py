#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""The Ecowitt gateway's address table, against somebody else's reading of it.

tests/test_ecowitt_gateway.py holds the widths against Ecowitt's own document, which
catches an address that is the wrong number of bytes wide. It cannot catch an address
that is the right width and the wrong reading: swap two two-byte addresses in the
table and every test still passes, because the fake encodes from the same table the
decoder reads, and both halves are wrong together.

What catches that is somebody else reading the same document. `weewx-gw1000` has
been reading these gateways since 2020, and its `live_data_struct` says, for each
address byte, how many bytes it is and what it holds. It was written years before
this one and from the same published API, so where the two agree the reading is
confirmed twice over, and where they disagree one of them is wrong.

Nothing here translates between the two. The names are spelled differently in about
sixty places, `inhumi` against `inhumid`, `soilmoisture1` against `soilmoist1`, and a
table mapping one to the other would be a third hand-written thing that could itself
be wrong and hide exactly what this is for. So the widths are compared for every
shared address, which needs no names at all, and the names only where both spell them
the same way. That is thirty-five of them, and they are the ones where a swap would
hurt most: `dewpoint`, `windchill` and `heatindex` sit at three consecutive addresses
of the same width.

Read at a stated commit into the external image, like the drivers this hosts. Nothing
of it is shipped.
"""

import os
import re
import struct

import pytest

WHERE = os.environ.get('EXTERNAL_DRIVERS', '')
SECOND = os.path.join(WHERE, 'user', 'gw1000.py') if WHERE else ''
pytestmark = pytest.mark.skipif(
    not SECOND or not os.path.isfile(SECOND),
    reason="the second reading is only in the 'external' image",
)

# One line of their table: b'\x01': ('decode_temp', 2, 'intemp'),
ENTRY = re.compile(r"\s*b'\\x([0-9A-Fa-f]{2})':\s*\('([^']+)',\s*(\d+),\s*'([^']+)'\)")


def second_reading():
    """Their table, as address to (name, width).

    Read out of the source rather than imported, because importing it needs six and
    a working USB stack, and all that is wanted is a table of numbers.

    Returns:
        dict: Address byte to (the name they give it, its width in bytes).
    """
    with open(SECOND, encoding='utf-8', errors='replace') as handle:
        source = handle.read()
    block = re.search(r'live_data_struct = \{(.*?)\n    \}', source, re.S)
    assert block, "their table is not where it was; the pin needs looking at"
    found = {}
    for line in block.group(1).split('\n'):
        entry = ENTRY.match(line)
        if entry:
            found[int(entry.group(1), 16)] = (entry.group(4), int(entry.group(3)))
    return found


def ours():
    """Our table, as address to (the names in it, its width in bytes).

    Returns:
        dict: Address byte to (tuple of names, width in bytes).
    """
    from ultimatepush.protocols import ecowitt_gateway as api

    return {
        address: (
            tuple(name for name, _, _ in shapes),
            struct.calcsize(api.shape_format(shapes)),
        )
        for address, shapes in api.LIVE.items()
    }


def shared():
    """The addresses both tables have.

    Returns:
        tuple: (theirs, ours, the sorted addresses in both).
    """
    theirs = second_reading()
    mine = ours()
    return theirs, mine, sorted(set(theirs) & set(mine))


def test_the_two_tables_overlap_enough_to_be_worth_comparing():
    """A guard on the comparison itself.

    Their file is pinned, and a pin that moves to a version where the table is
    written differently would leave the regular expression matching nothing. Then
    every test below would pass by having nothing to check, which is the worst way
    for a test to pass.
    """
    theirs, mine, both = shared()
    assert len(theirs) >= 100, "only %d of their addresses were read" % len(theirs)
    assert len(both) >= 100, "only %d addresses are in both" % len(both)


def test_every_shared_address_is_the_same_width_in_both():
    """No names, so nothing to translate and nothing to get wrong in between.

    Their width is a plain number beside each address, and ours is what struct makes
    of the shapes. Two people reading one document and arriving at the same hundred
    numbers is a stronger statement than either of them alone.
    """
    theirs, mine, both = shared()
    wrong = [
        '0x%02X is %d bytes here and %d in weewx-gw1000'
        % (address, mine[address][1], theirs[address][1])
        for address in both
        if mine[address][1] != theirs[address][1]
    ]
    assert not wrong, '; '.join(wrong)


def test_the_addresses_both_name_the_same_way_hold_the_same_reading():
    """The check the widths cannot make: what is actually at each address.

    Only where the two spell the name identically, because a translation table would
    be one more hand-written thing standing between the two readings. Thirty-five is
    a third of the table and it is the third that matters: three of them are
    dewpoint, windchill and heatindex, which are consecutive and the same width, so
    a swap among them is exactly the slip that nothing else here would notice.
    """
    theirs, mine, both = shared()
    agreed = [
        address
        for address in both
        if len(mine[address][0]) == 1 and mine[address][0][0] == theirs[address][0]
    ]
    assert len(agreed) >= 30, (
        "only %d addresses are spelled the same way in both, which is too few for "
        "this to be saying anything" % len(agreed)
    )
    # Spot the ones that agree on the name and would have to agree on everything.
    for address in agreed:
        assert (
            mine[address][1] == theirs[address][1]
        ), '0x%02X is called %s in both and is a different width' % (
            address,
            theirs[address][0],
        )


def test_a_name_we_use_is_never_at_a_different_address_in_theirs():
    """The swap, caught from the other side.

    The test above compares address by address and can only speak about the ones
    both spell the same. This asks the opposite question: is any name we use sitting
    at an address where they put something else entirely? Two addresses whose names
    were exchanged fail here even though each of them, on its own, is a name both
    tables know.
    """
    theirs, mine, both = shared()
    theirs_by_name = {name: address for address, (name, _) in theirs.items()}
    wrong = []
    for address in both:
        names, _ = mine[address]
        if len(names) != 1:
            continue
        name = names[0]
        elsewhere = theirs_by_name.get(name)
        if elsewhere is not None and elsewhere != address:
            wrong.append(
                '%s is at 0x%02X here and at 0x%02X in weewx-gw1000'
                % (name, address, elsewhere)
            )
    assert not wrong, '; '.join(wrong)
