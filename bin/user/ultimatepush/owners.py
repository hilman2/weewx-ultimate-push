#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""Which station owns which archive column.

A column takes one answer. Two stations writing one column take turns every few
seconds, and afterwards nothing can tell the two apart: not a report, not an
aggregate, not somebody reading the table by hand. Every other rule in this driver
exists to keep that from happening, and this is the one that finishes the job.

Roles are not enough on their own. A role moves an extra station's temperature and
humidity out of the way and drops what has nowhere to go, but "nowhere to go" is
measured against the main station. Three identical consoles set up as extra sensors
all send `soilmoisture1`, the main station is an Ambient console that has no such
reading, and so all three write `soilMoist1` -- in turn, every few seconds, for as
long as they are running.

So: whoever fills a column first owns it, and everybody else is turned away from it.

The main station outranks that. Otherwise which console owns `outTemp` would be
decided by which one happened to upload first after a restart, which is a coin toss
deciding where the readings of a weather station go.

Ownership is kept in the settings file rather than in memory. Learning it again after
every restart would mean holding every extra station back until the main one has been
heard -- an interval of readings lost per station per restart -- and a station that
went quiet for a week would come back to find its columns taken.
"""

import logging

log = logging.getLogger(__name__)

# Not readings. They say when and in what units, and every station sends them.
NOT_A_READING = ('dateTime', 'usUnits', 'interval', 'station')


class Register:
    """Column -> the identity of the station that fills it.

    Held by the driver, read and written from the thread that handles uploads and
    from the one that serves the web interface, so every method is short and the
    store underneath does its own locking.

    Args:
        owned (dict): Column name to station identity, as read from the settings
            file. Empty for an installation that has not recorded any yet.
    """

    def __init__(self, owned=None):
        self.owned = dict(owned or {})

    def owner(self, field):
        """Which station fills one column.

        Args:
            field (str): A WeeWX field name, such as `outTemp`.

        Returns:
            str | None: The station's identity, or None if the column is free.
        """
        return self.owned.get(field)

    def owns(self, ident):
        """Every column one station fills.

        Args:
            ident (str): A station identity.

        Returns:
            list: The column names, sorted, so that the answer is the same every time
            somebody looks at it.
        """
        return sorted(f for f, who in self.owned.items() if who == ident)

    def claim(self, field, ident, is_main=False):
        """Ask for one column on behalf of a station.

        Nobody loses a column except to the main station, and the main station never
        loses one at all.

        Args:
            field (str): The WeeWX field the station is about to fill.
            ident (str): The station asking for it.
            is_main (bool): Whether this is the one main station, which outranks an
                existing claim.

        Returns:
            tuple: (allowed, lost), where `allowed` says whether the station may
            write the column, and `lost` is the identity that has just been turned
            out of it, or None. The second value is there so that a column changing
            hands can be said once rather than discovered in the data.
        """
        held = self.owned.get(field)
        if held == ident:
            return True, None
        if held is None:
            self.owned[field] = ident
            return True, None
        if not is_main:
            return False, None
        self.owned[field] = ident
        return True, held

    def release(self, field):
        """Give up one column, so that the next station to fill it may have it.

        Args:
            field (str): The column to release.

        Returns:
            str | None: The identity that held it, or None if nobody did.
        """
        return self.owned.pop(field, None)

    def release_all(self, ident):
        """Give up everything one station held.

        Args:
            ident (str): The station.

        Returns:
            list: The columns it gave up, for saying so afterwards.
        """
        gone = self.owns(ident)
        for field in gone:
            del self.owned[field]
        return gone

    def rename(self, was, now):
        """Follow a station whose identity changed, so that it keeps what it had.

        Args:
            was (str): The identity it had.
            now (str): The identity it has.
        """
        for field, who in list(self.owned.items()):
            if who == was:
                self.owned[field] = now


def readings(packet):
    """The fields of a packet that are readings, and so can be owned.

    Args:
        packet (dict): A loop packet.

    Returns:
        list: The field names that measure something, leaving out the ones every
        station sends: the time, the units and the station's own name.
    """
    return [field for field in packet if field not in NOT_A_READING]
