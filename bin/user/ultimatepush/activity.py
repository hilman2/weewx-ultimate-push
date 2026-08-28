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

# How many uploads to keep per station. Enough to see a pattern, few enough that
# nobody has to think about the memory.
KEEP = 20

# The longest payload worth storing, in characters. Real uploads are a kilobyte. A
# listener will accept sixty-four, and there is no reason to hold that in memory
# twenty times over for whoever sent it.
LONGEST = 8192


class Upload:
    """One arrival, and what came of it."""

    __slots__ = ('at', 'client', 'path', 'method', 'ident', 'protocol', 'dialect',
                 'text', 'packet', 'note')

    def __init__(self, at, client, path, method, text, ident='', protocol=None,
                 dialect=None, packet=None, note=''):
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
        self.note = note

    def as_dict(self, redact):
        """For the web interface. `redact` is passed in so this module needs no
        opinion about what a secret is; transport has that."""
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
            'note': self.note,
        }


class Station:
    """The running total for one station."""

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
        self.recent = collections.deque(maxlen=KEEP)
        # Raw field -> what the mapper decided, for the field page.
        self.fields = {}
        self.guesses = {}
        self.undecided = {}
        # The raw names this station has actually sent. The catalog has five hundred
        # and a station sends forty, and a page listing the catalog would bury the
        # forty that matter. Kept as a union rather than the last upload, because a
        # sensor whose battery died last week is still one of this station's fields.
        self.raw_seen = set()


class Log:
    """Every station's activity, and the uploads that belonged to none of them."""

    def __init__(self, keep=KEEP):
        self.lock = threading.Lock()
        self.stations = {}
        self.unclaimed = collections.deque(maxlen=keep)
        self.started = time.time()
        self.keep = keep

    # ---- writing, from the driver's loop -------------------------------------

    def arrived(self, ident, upload):
        """An upload that belongs to a station this driver answers to."""
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
            else:
                station.dropped += 1
            station.recent.append(upload)

    def refused(self, upload):
        """An upload from a station this driver does not answer to, or from nothing
        it recognised. This is what somebody looks at when a console they just set up
        is not appearing."""
        with self.lock:
            self.unclaimed.append(upload)

    def named(self, ident, name):
        with self.lock:
            station = self.stations.get(ident)
            if station is not None:
                station.name = name

    def mapping(self, ident, raw_names, fields, guesses, undecided):
        """What the mapper knows, after an upload.

        Copied rather than referenced: the mapper keeps changing these and the web
        server reads them from another thread.
        """
        with self.lock:
            station = self.stations.get(ident)
            if station is None:
                return
            station.raw_seen.update(raw_names)
            station.fields = dict(fields)
            station.guesses = {raw: (g.field, g.group, g.why, g.certain)
                               for raw, g in guesses.items()}
            station.undecided = dict(undecided)

    # ---- reading, from the web server's thread --------------------------------

    def snapshot(self):
        """Every station, as plain data. Safe to hand to another thread."""
        with self.lock:
            return [self._station_dict(s) for s in self.stations.values()]

    def one(self, ident):
        with self.lock:
            station = self.stations.get(ident)
            return self._station_dict(station) if station else None

    def _station_dict(self, station):
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
            'fields': dict(station.fields),
            'guesses': dict(station.guesses),
            'undecided': dict(station.undecided),
        }

    def recent(self, ident, redact, limit=KEEP):
        """The last few uploads from one station, redacted."""
        with self.lock:
            station = self.stations.get(ident)
            if station is None:
                return []
            uploads = list(station.recent)[-limit:]
        return [u.as_dict(redact) for u in reversed(uploads)]

    def waiting(self, redact, limit=KEEP):
        """Uploads nobody claimed, newest first. A console that is being refused
        shows up here with its readings, which is what somebody needs in order to
        decide whether to let it in."""
        with self.lock:
            uploads = list(self.unclaimed)[-limit:]
        return [u.as_dict(redact) for u in reversed(uploads)]

    def unknown_stations(self, redact):
        """The refused uploads, grouped by whatever named the station.

        One row per console rather than one per upload, because a console that is
        being refused sends one every sixteen seconds and the list is otherwise all
        the same console.
        """
        seen = {}
        for upload in self.waiting(redact, limit=self.keep):
            ident = upload['ident'] or '(unnamed)'
            row = seen.setdefault(ident, {
                'ident': ident,
                'protocol': upload['protocol'],
                'client': upload['client'],
                'uploads': 0,
                'last_seen': upload['at'],
                'sample': upload,
            })
            row['uploads'] += 1
        return list(seen.values())
