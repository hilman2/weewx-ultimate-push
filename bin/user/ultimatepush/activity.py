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

# How many refused stations to keep a tally of. One console being refused is the
# ordinary case and needs one. A radio receiver hears every sensor for a few hundred
# metres, including cars going past, so this has to be large enough that the sensors
# somebody actually owns are still in the list when they look, and bounded so that a
# busy road does not grow it for ever. The least recently heard goes first.
KEEP_REFUSED = 200

# How long a station stays on the list after it was last heard.
#
# Two days, because that covers a console somebody unplugged over a weekend and does
# not cover a car that drove past on Tuesday. Nothing is remembered about the ones
# that go: they are dropped, and one that transmits again comes straight back, with
# its count starting over. That is the right count either way, because a sensor that
# went quiet for two days and returned is news again.
FORGET_REFUSED = 48 * 3600.0

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
        # One entry per station being refused, rather than per upload. The deque
        # above holds the last few uploads whatever they are, which is the right
        # thing for a console and useless for a radio: twenty uploads spread over
        # thirty talkers means the one somebody is looking for has already gone.
        self.refusals = collections.OrderedDict()  # type: collections.OrderedDict
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
            ident = upload.ident or '(unnamed)'
            row = self.refusals.pop(ident, None)
            if row is None:
                row = {
                    'ident': ident,
                    'protocol': upload.protocol,
                    'client': upload.client,
                    'uploads': 0,
                    'first_seen': upload.at,
                    'last_seen': upload.at,
                    'sample': upload,
                }
            row['uploads'] += 1
            row['last_seen'] = upload.at
            row['protocol'] = upload.protocol or row['protocol']
            row['client'] = upload.client or row['client']
            row['sample'] = upload
            # Back to the end, so that the one dropped when the list is full is the
            # one nothing has been heard from for longest.
            self.refusals[ident] = row
            self._forget_quiet(upload.at)
            while len(self.refusals) > KEEP_REFUSED:
                self.refusals.popitem(last=False)

    def _forget_quiet(self, now):
        """Drop the stations nothing has been heard from for two days.

        Cheap because the list is in the order things were last heard: whatever has
        gone quiet is at the front, so this stops at the first one that has not.

        Called with the lock held.

        Args:
            now (float): The time to measure from, which is when the upload that
                prompted this arrived.
        """
        cutoff = now - FORGET_REFUSED
        while self.refusals:
            ident, row = next(iter(self.refusals.items()))
            if row['last_seen'] >= cutoff:
                return
            del self.refusals[ident]

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

    def rename(self, was, now):
        """Carry what is known about a station over to a new identity.

        Args:
            was (str): The identity it had.
            now (str): The identity it has.

        Returns:
            bool: Whether there was anything to carry over.
        """
        station = self.stations.pop(was, None)
        if station is None:
            return False
        station.ident = now
        self.stations[now] = station
        return True

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
        """Every station being refused, the one heard most often first.

        One row per station rather than one per upload, and counted as they arrive
        rather than read back out of the last few, because the last few are no help
        where a radio is hearing thirty things at once.

        The order is the useful one. Something heard fifty times is close by and
        transmitting on a schedule, which is what a sensor somebody owns does. A car
        going past is heard once.

        Anything nothing has been heard from for two days is left out and dropped.
        A console that was unplugged over a weekend is still there; the car that
        drove past on Tuesday is not. Nothing about the ones that go is remembered,
        so one that transmits again comes straight back.

        Args:
            redact (callable): Given the upload text, returns it redacted.

        Returns:
            list: One entry per station, each with what named it, how many uploads
            have been refused, when the first and last arrived, and a sample of
            readings. Most often heard first.
        """
        with self.lock:
            # Swept here as well as when an upload arrives, so that a list read
            # after a quiet night is right even though nothing has arrived to
            # prompt a sweep.
            self._forget_quiet(time.time())
            rows = list(self.refusals.values())
        made = []
        for row in rows:
            made.append(dict(row, sample=row['sample'].as_dict(redact)))
        made.sort(key=lambda row: (-row['uploads'], row['ident']))
        return made

    def stop_refusing(self, ident):
        """Forget the tally for one station, so it starts again from nothing.

        Called when a station is let in, and when somebody says it is not theirs.

        Args:
            ident (str): The station's identity.

        Returns:
            bool: Whether there was a tally to forget.
        """
        with self.lock:
            return self.refusals.pop(ident, None) is not None
