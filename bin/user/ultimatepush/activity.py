#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""What each station has been doing lately.

Everything on this page is otherwise reachable only by turning on `log_raw` and
reading the journal, which means waiting for the next upload with a grep running. The
driver has the uploads in hand, so it keeps the last few and what it made of them.

Deliberately small and deliberately bounded. A ring per station, a ring for the
uploads nobody claimed, and a few counters. Nothing is written to disk: this is what
happened since the driver started, and after a restart there is nothing to show
because nothing has happened yet.

Read from the web server's thread while the driver's loop is writing, so every read
returns a snapshot taken under a lock rather than a live view of a dict somebody else
is changing.
"""

import collections
import threading
import time
from typing import Any, Deque, Dict

# How many uploads to keep per station. Enough to see a pattern, few enough that
# nobody has to think about the memory.
KEEP = 20

# The longest payload worth storing, in characters. Real uploads are a kilobyte. A
# listener will accept sixty-four, and there is no reason to hold that in memory
# twenty times over for whoever sent it.
LONGEST = 8192


class Upload:
    """One arrival, and what came of it.

    Args:
        at (float): When it arrived.
        client (str): The address it came from.
        path (str): The path it was sent to.
        method (str): GET or POST.
        text (str): The body, kept only as far as LONGEST.
        ident (str): Whatever named the station, or '' when nothing did. Kept
            here rather than dug out of the payload again, because which field
            that is depends on the protocol.
        protocol (str): The protocol that claimed it.
        dialect (str): The catalog it was read with.
        packet (dict): The loop packet it became, or None.
        readings (iterable): A few readings in plain sight, for an upload
            nobody has claimed yet.
        note (str): Why it was refused, for one that was.
    """

    __slots__ = (
        'at',
        'client',
        'path',
        'method',
        'ident',
        'protocol',
        'dialect',
        'text',
        'packet',
        'readings',
        'note',
    )

    def __init__(
        self,
        at,
        client,
        path,
        method,
        text,
        ident='',
        protocol=None,
        dialect=None,
        packet=None,
        readings=(),
        note='',
    ):
        self.at = at
        self.client = client
        self.path = path
        self.method = method
        # Whatever named the station, or '' when nothing did. Kept here rather than
        # dug out of the payload again, because which field that is depends on the
        # protocol and the protocol is the thing that may have been in doubt.
        self.ident = ident
        self.protocol = protocol
        self.dialect = dialect
        self.text = text[:LONGEST]
        self.packet = packet
        # A few readings in plain sight, for an upload nobody has claimed yet.
        # Whoever decides whether to let it in has to be able to tell their own
        # new console from somebody else's, and an address cannot do that.
        self.readings = list(readings)
        self.note = note

    def as_dict(self, redact):
        """For the web interface. `redact` is passed in so this module needs no
        opinion about what a secret is; transport has that.

        Args:
            redact (callable): Given the upload text, returns it with anything that
                names the station replaced.

        Returns:
            dict: The upload as plain data, safe to hand to another thread and safe
            to show somebody.
        """
        return {
            'at': self.at,
            'client': self.client,
            'path': self.path,
            'method': self.method,
            'ident': self.ident,
            'protocol': self.protocol,
            'dialect': self.dialect,
            'text': redact(self.text),
            'packet': self.packet,
            'readings': self.readings,
            'note': self.note,
        }


class Station:
    """The running total for one station.

    Args:
        ident (str): The station's identity.
    """

    def __init__(self, ident):
        self.ident = ident
        self.name = None
        self.protocol = None
        self.dialect = None
        self.first_seen = None
        self.last_seen = None
        self.uploads = 0
        self.packets = 0
        self.dropped = 0
        self.recent = collections.deque(maxlen=KEEP)  # type: Deque[Upload]
        # Raw field -> what the mapper decided, for the field page.
        self.fields = {}
        self.guesses = {}
        self.undecided = {}
        # The WeeWX fields the last upload actually reached, as opposed to the ones
        # this station's catalog could fill. The difference is what a role moved out
        # of the way and what was dropped rather than written over another station's.
        #
        # The last upload rather than all of them, because the question it answers is
        # whether two stations are sharing a column now. A station whose role changed
        # this morning wrote outTemp before that, and it is not writing it any more.
        self.written = set()
        # How many readings were dropped for that reason, from the last upload.
        self.dropped_fields = []
        # The raw names this station has actually sent. The catalog has five hundred
        # and a station sends forty, and a page listing the catalog would bury the
        # forty that matter. Kept as a union rather than the last upload, because a
        # sensor whose battery died last week is still one of this station's fields.
        self.raw_seen = set()


class Log:
    """Every station's activity, and the uploads that belonged to none of them.

    Args:
        keep (int): How many uploads to keep per station, and how many
            unclaimed ones to keep in all.
    """

    def __init__(self, keep=KEEP):
        self.lock = threading.Lock()
        self.stations = {}
        self.unclaimed = collections.deque(maxlen=keep)  # type: Deque[Upload]
        self.started = time.time()
        self.keep = keep

    # ---- writing, from the driver's loop -------------------------------------

    def arrived(self, ident, upload):
        """Record an upload that belongs to a station this driver answers to.

        Args:
            ident (str): The station's identity.
            upload (Upload): What arrived, and what became of it.
        """
        with self.lock:
            station = self.stations.get(ident)
            if station is None:
                station = self.stations[ident] = Station(ident)
                station.first_seen = upload.at
            station.last_seen = upload.at
            station.uploads += 1
            station.protocol = upload.protocol or station.protocol
            station.dialect = upload.dialect or station.dialect
            if upload.packet:
                station.packets += 1
                station.written = set(upload.packet)
            else:
                station.dropped += 1
            station.recent.append(upload)

    def refused(self, upload):
        """Record an upload from a station this driver does not answer to.

        This is what somebody looks at when a console they have just set up is not
        appearing.

        Args:
            upload (Upload): What arrived, and why it was refused.
        """
        with self.lock:
            self.unclaimed.append(upload)

    def kept_apart(self, ident, fields):
        """Record readings a station is not writing because another station has them.

        Args:
            ident (str): The station whose readings were dropped.
            fields (iterable): The WeeWX fields it did not get to write.
        """
        with self.lock:
            station = self.stations.get(ident)
            if station is not None:
                station.dropped_fields = sorted(fields)

    def named(self, ident, name):
        """Give a station a name, for showing rather than for identifying it.

        Args:
            ident (str): The station's identity.
            name (str): What to call it.
        """
        with self.lock:
            station = self.stations.get(ident)
            if station is not None:
                station.name = name

    def mapping(self, ident, raw_names, fields, guesses, undecided):
        """What the mapper knows, after an upload.

        Copied rather than referenced: the mapper keeps changing these and the web
        server reads them from another thread.

        Args:
            ident (str): The station's identity.
            raw_names (iterable): The raw names this upload carried, less the ones
                that identify the device rather than measure anything.
            fields (dict): Raw name to WeeWX field, as the mapper has it now.
            guesses (dict): What the mapper worked out for itself, and how.
            undecided (dict): Fields it would not place without being told.
        """
        with self.lock:
            station = self.stations.get(ident)
            if station is None:
                return
            station.raw_seen.update(raw_names)
            station.fields = dict(fields)
            station.guesses = {
                raw: (g.field, g.group, g.why, g.certain) for raw, g in guesses.items()
            }
            station.undecided = dict(undecided)

    # ---- reading, from the web server's thread --------------------------------

    def snapshot(self):
        """Every station, as plain data. Safe to hand to another thread."""
        with self.lock:
            return [self._station_dict(s) for s in self.stations.values()]

    def one(self, ident):
        """One station, as plain data.

        Args:
            ident (str): The station's identity.

        Returns:
            dict | None: What is known about it, or None if it has never uploaded.
        """
        with self.lock:
            station = self.stations.get(ident)
            return self._station_dict(station) if station else None

    def _station_dict(self, station):
        """One station as plain data. The caller holds the lock.

        Args:
            station (Station): The running total for one station.

        Returns:
            dict: A copy, safe to hand to another thread.
        """
        return {
            'ident': station.ident,
            'name': station.name,
            'protocol': station.protocol,
            'dialect': station.dialect,
            'first_seen': station.first_seen,
            'last_seen': station.last_seen,
            'uploads': station.uploads,
            'packets': station.packets,
            'dropped': station.dropped,
            'raw_seen': sorted(station.raw_seen),
            'written': sorted(station.written),
            'dropped_fields': list(station.dropped_fields),
            'fields': dict(station.fields),
            'guesses': dict(station.guesses),
            'undecided': dict(station.undecided),
        }

    def recent(self, ident, redact, limit=KEEP):
        """The last few uploads from one station, redacted.

        Args:
            ident (str): The station's identity.
            redact (callable): Given the upload text, returns it with anything that
                names the station replaced.
            limit (int): How many to return, newest last.

        Returns:
            list: The uploads as plain data. Empty if the station is not known.
        """
        with self.lock:
            station = self.stations.get(ident)
            if station is None:
                return []
            uploads = list(station.recent)[-limit:]
        return [u.as_dict(redact) for u in reversed(uploads)]

    def waiting(self, redact, limit=KEEP):
        """Uploads nobody claimed, newest first.

        A console that is being refused shows up here with its readings, which is
        what somebody needs in order to decide whether to let it in.

        Args:
            redact (callable): Given the upload text, returns it redacted.
            limit (int): How many to return.

        Returns:
            list: The uploads as plain data, newest first.
        """
        with self.lock:
            uploads = list(self.unclaimed)[-limit:]
        return [u.as_dict(redact) for u in reversed(uploads)]

    def unknown_stations(self, redact):
        """The refused uploads, grouped by whatever named the station.

        One row per console rather than one per upload, because a console that is
        being refused sends one every sixteen seconds and the list is otherwise all
        the same console.

        Args:
            redact (callable): Given the upload text, returns it redacted.

        Returns:
            list: One entry per console, each with what named it, how many uploads
            have been refused, when the last one arrived, and a sample of readings.
        """
        seen = {}  # type: Dict[str, Dict[str, Any]]
        for upload in self.waiting(redact, limit=self.keep):
            ident = upload['ident'] or '(unnamed)'
            row = seen.setdefault(
                ident,
                {
                    'ident': ident,
                    'protocol': upload['protocol'],
                    'client': upload['client'],
                    'uploads': 0,
                    'last_seen': upload['at'],
                    'sample': upload,
                },
            )
            row['uploads'] += 1
        return list(seen.values())
