#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""Sources this driver asks, beside the ones that push and the ones it drives.

Some hardware has nowhere to type a server address into. A PurpleAir sensor runs a
small web server and answers whoever asks; so does a Davis AirLink, a Netatmo relay,
and most of what is sold as "with a local API". None of it can be pointed at
anything, so none of it can push, and a driver that only listens never sees it.

What is here is the asking, and nothing else. Once an answer is in hand it is handed
to the rest of the driver as though the hardware had pushed it: the same request
object the HTTP listener builds, and after that the same detection, the same catalog,
the same field map, the same column ownership and the same page of raw uploads. That
is the point of doing it this way rather than writing a second, parallel path. A
protocol gets to be polled by saying `fetched = True`, and everything else it already
had keeps working.

Nearly all of it is HTTP, because nearly everything with a local API has a small
web server on it. An Ecowitt gateway does not: it answers a binary protocol on a
socket of its own, and a body decoded as text would no longer be the bytes that
arrived. So a protocol may bring its own way of fetching and the rest of this is
unchanged; see protocols.Protocol.fetcher.

Shaped like a listener on purpose: `get`, `close`, `closed` and a `port`. The driver
merges its sources with server.Fan, which asks nothing of them beyond those four, so
this needed no change there at all. Same trick as hardware.Host.

    [UltimatePush]
        [[polling]]
            [[[air]]]
                address = 1.2.3.4
                protocol = purpleair
                interval = 60

One thread per source. A sensor that has been unplugged then holds up only itself,
and the thread is cheap next to the sixty seconds it spends asleep.
"""

import logging
import queue
import threading
import urllib.error
import urllib.parse
import urllib.request
from typing import List, TYPE_CHECKING

from . import protocols

# For the docstring types only. The request class comes from whichever listener this
# installation has, and nothing here needs the name at run time.
if TYPE_CHECKING:
    import weewx.listener

log = logging.getLogger(__name__)

# How often to ask, when nobody says. Air quality moves over minutes, not seconds,
# and a sensor on a battery-backed board is happier being left alone.
DEFAULT_INTERVAL = 60.0
# The shortest anybody may ask for. Below this it is a denial of service against
# somebody's own sensor.
SHORTEST_INTERVAL = 5.0
# How long to wait for an answer. Longer than any local device needs, short enough
# that a source which has gone away is noticed within one interval.
DEFAULT_TIMEOUT = 10.0
# Largest answer to read. A PurpleAir sends about four kilobytes.
MAX_BODY = 262144

# How long to wait after a failure before asking again, and the ceiling that wait
# doubles towards. A sensor rebooting is back within the first wait; one that has
# been taken down for the winter is asked for every five minutes rather than every
# ten seconds. Same numbers as a hosted driver, for the same reason.
FIRST_WAIT = 10.0
LONGEST_WAIT = 300.0

# How many answers may wait to be picked up before the oldest is dropped. Small: an
# answer nobody has collected in several intervals is a reading nobody wants.
QUEUE_SIZE = 10


class Source:
    """One thing to ask, and how often.

    Args:
        name (str): What to call it, in the log and on the page.
        url (str): What to ask for.
        interval (float): Seconds between one answer and the next question.
        timeout (float): Seconds to wait for an answer.
        path (str): What to put in the request handed on, which is where the log
            and the page of raw uploads say the reading came from.
        fetcher (Callable[[Any], Tuple[bytes, Dict[str, str]]] | None): How to go and
            ask, for hardware that does not answer over HTTP. Called as
            ``fetcher(source)``, returning (the body, the headers). HTTP when
            there is none, which is what a sensor with a web server on it wants.
    """

    __slots__ = (
        'name',
        'url',
        'interval',
        'timeout',
        'path',
        'host',
        'stopped',
        'fetcher',
    )

    def __init__(
        self,
        name,
        url,
        interval=DEFAULT_INTERVAL,
        timeout=DEFAULT_TIMEOUT,
        path='',
        fetcher=None,
    ):
        self.name = name
        self.url = url
        self.interval = max(SHORTEST_INTERVAL, float(interval))
        self.timeout = float(timeout)
        self.path = path or ('/poll/' + name)
        self.host = _host_of(url)
        self.fetcher = fetcher
        # Set when this one source is taken out while the others carry on. Its
        # thread is asleep for most of an interval and notices on its next turn.
        self.stopped = threading.Event()

    def __repr__(self):
        return "Source(%s, %s, every %gs)" % (self.name, self.url, self.interval)


class Poller:
    """Every source this driver asks, behind one listener-shaped object.

    Args:
        sources (list[Source]): What to ask. An empty list is a programming error:
            the caller builds this only when there is something to ask.
    """

    def __init__(self, sources):
        self.sources = list(sources)
        self.queue = queue.Queue(maxsize=QUEUE_SIZE)  # type: queue.Queue
        self.closed = threading.Event()
        self.dropped = 0
        self.threads = []  # type: List[threading.Thread]
        for source in self.sources:
            thread = threading.Thread(
                target=self._ask_forever,
                args=(source,),
                name='poll-' + source.name,
                daemon=True,
            )
            self.threads.append(thread)
            thread.start()

    # A poller holds no socket. The driver prints the ports it listens on, and this
    # has to say plainly that it has none rather than be left out of that list.
    port = None

    def get(self, timeout=None):
        """The next answer, or None if none came in time.

        Args:
            timeout (float | None): Seconds to wait. None waits until something
                arrives or the poller is closed.

        Returns:
            weewx.listener.Request | None: The answer, shaped as an upload.
        """
        if timeout is None:
            while not self.closed.is_set():
                got = self.get(timeout=1.0)
                if got is not None:
                    return got
            return None
        try:
            return self.queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def close(self):
        """Stop asking, and wait for the threads to notice."""
        self.closed.set()
        # Each source too, because a thread asleep between two questions waits on
        # its own event. One flag would do for shutting down and one for taking a
        # single source out; setting both here is what makes the sleep interruptible
        # in either case.
        for source in self.sources:
            source.stopped.set()
        for thread in self.threads:
            # One interval longer than a request can take, so that a thread waiting
            # on an answer is given the chance to come back on its own.
            thread.join(DEFAULT_TIMEOUT + 2.0)

    def adopt(self, source):
        """Start asking one more source, without a restart.

        Args:
            source (Source): What to ask.
        """
        self.sources.append(source)
        thread = threading.Thread(
            target=self._ask_forever,
            args=(source,),
            name='poll-' + source.name,
            daemon=True,
        )
        self.threads.append(thread)
        thread.start()

    def dismiss(self, name):
        """Stop asking one source.

        Its thread is left to notice on its own rather than waited for: it is asleep
        for most of an interval, and the page must not wait that long. Nothing it
        delivers after this is kept, because the station has gone with it.

        Args:
            name (str): The source's name.

        Returns:
            bool: Whether there was one to stop.
        """
        for source in list(self.sources):
            if source.name == name:
                self.sources.remove(source)
                source.stopped.set()
                return True
        return False

    def _ask_forever(self, source):
        """Ask one source over and over until the poller is closed.

        Runs on its own thread. Nothing here raises: a source that cannot be reached
        is a state to sit in rather than an error to propagate, because the hardware
        being unplugged is the ordinary case.

        Args:
            source (Source): What to ask.
        """
        wait = FIRST_WAIT
        failing = False
        while not self.closed.is_set() and not source.stopped.is_set():
            try:
                body, headers = _fetch(source)
            except Exception as e:
                if not failing:
                    # Once, and then quiet. A sensor that is away for a week must not
                    # write a line a minute into somebody's log.
                    log.warning(
                        "Cannot reach '%s' at %s: %s. Still trying, quietly.",
                        source.name,
                        source.url,
                        e,
                    )
                    failing = True
                source.stopped.wait(wait)
                wait = min(LONGEST_WAIT, wait * 2)
                continue
            if failing:
                log.info("'%s' is answering again.", source.name)
                failing = False
            wait = FIRST_WAIT
            self._deliver(source, body, headers)
            source.stopped.wait(source.interval)

    def _deliver(self, source, body, headers):
        """Put one answer where the driver will pick it up.

        Args:
            source (Source): Who answered.
            body (bytes): What it said.
            headers (dict): The response headers, with lowercased keys.
        """
        request = _request_class()('GET', source.path, '', body, headers, source.host)
        try:
            self.queue.put_nowait(request)
        except queue.Full:
            # The oldest goes, not the newest: the point of asking again is to have
            # the current reading, and a queue full of stale ones is worth less than
            # one fresh one.
            self.dropped += 1
            try:
                self.queue.get_nowait()
                self.queue.put_nowait(request)
            except (queue.Empty, queue.Full):
                pass


def _request_class():
    """The class an upload is handed over in, from whichever listener is installed.

    Imported at first use rather than at the top of this module. Everything else
    here is asking over HTTP and needs no WeeWX at all, and importing the listener
    would drag it in: `user.listener` imports weewx, and so does the core copy. That
    made this module unimportable on a machine without WeeWX, and the tests that
    exercise the asking on its own could not even be collected.

    Returns:
        type: The Request class.
    """
    try:  # WeeWX 5.6 and later
        from weewx.listener import Request
    except ImportError:  # the copy this driver carries for older WeeWX
        from user.listener import Request

    return Request


def _fetch(source):
    """Ask one source and read its answer, however this one has to be asked.

    Args:
        source (Source): What to ask.

    Returns:
        tuple: (the body as bytes, the headers as a dict with lowercased keys).

    Raises:
        Exception: Whatever the asking raised. The caller sits in the failure rather
            than passing it on.
    """
    if source.fetcher is not None:
        return source.fetcher(source)
    return _over_http(source)


def _over_http(source):
    """Ask one source over HTTP, which is how anything with a web server answers.

    Args:
        source (Source): What to ask.

    Returns:
        tuple: (the body as bytes, the headers as a dict with lowercased keys).

    Raises:
        Exception: Whatever urllib raised.
    """
    asking = urllib.request.Request(
        source.url, headers={'User-Agent': 'weewx-ultimate-push'}
    )
    answer = urllib.request.urlopen(asking, timeout=source.timeout)
    try:
        # Read one byte past the limit, so that an answer at exactly the limit is
        # not silently the truncated one.
        body = answer.read(MAX_BODY + 1)
        if len(body) > MAX_BODY:
            raise ValueError(
                "the answer is longer than %d bytes, which is not a reading" % MAX_BODY
            )
        headers = {}
        for name, value in getattr(answer, 'headers', {}).items():
            headers[name.lower()] = value
        return body, headers
    finally:
        answer.close()


def _host_of(url):
    """Where an answer came from, for the log and the page of raw uploads.

    Args:
        url (str): The URL being asked.

    Returns:
        str: The host part, or the whole URL if it has none to speak of.
    """
    try:
        # A source that is not asked over HTTP is written down as a host and a port
        # with no scheme in front of it, and urlsplit reads that as a path. Two
        # slashes make it read the same string as the authority it is.
        written = url if '://' in url else '//' + url
        return urllib.parse.urlsplit(written).hostname or url
    except Exception:
        return url


def build(section, keep_empty=False):
    """The poller this configuration wants, or None if it wants none.

    Args:
        section (dict | None): The `[[polling]]` subsection, one block per source.
        keep_empty (bool): Whether to build one with nothing in it. The interface
            needs somewhere to put a source added while WeeWX is running, and a
            poller with no sources is a queue and no threads.

    Returns:
        Poller | None: The poller, or None when nothing is configured and none was
        asked for.

    Raises:
        ValueError: If a source names no address, or names a protocol that is not
            one this driver has.
    """
    if not section:
        return Poller([]) if keep_empty else None
    sources = []
    for name in sorted(section):
        block = section[name]
        if not hasattr(block, 'get'):
            # A stray scalar under [[polling]], e.g. a setting somebody meant to put
            # one level up. Saying which one is worth more than ignoring it.
            raise ValueError(
                "'%s' under [[polling]] is a setting, not a source. Every source is "
                "its own block." % name
            )
        sources.append(_source_from(name, block))
    if not sources:
        return Poller([]) if keep_empty else None
    log.info(
        "Asking %s.",
        ', '.join('%s every %gs' % (one.name, one.interval) for one in sources),
    )
    return Poller(sources)


def source_for(name, block):
    """One source, for a caller that has a block and no file.

    Args:
        name (str): What to call it.
        block (dict): What to ask and how often.

    Returns:
        Source: The source.

    Raises:
        ValueError: If there is no address, or the protocol named is not one of ours.
    """
    return _source_from(name, block)


def _source_from(name, block):
    """One source out of its block.

    Args:
        name (str): The block's name.
        block (dict): What is in it.

    Returns:
        Source: The source.

    Raises:
        ValueError: If there is no address, or the protocol named is not one of ours.
    """
    url = str(block.get('url', '')).strip()
    protocol_name = str(block.get('protocol', '')).strip()
    protocol = None
    if protocol_name:
        protocol = protocols.by_name(protocol_name)
        if protocol is None:
            raise ValueError(
                "'%s' asks for the '%s' protocol, which this driver does not have. "
                "It has: %s." % (name, protocol_name, ', '.join(protocols.names()))
            )
    if not url:
        address = str(block.get('address', '')).strip()
        if not address:
            raise ValueError(
                "'%s' under [[polling]] needs either a 'url' or an 'address'." % name
            )
        if protocol is None:
            raise ValueError(
                "'%s' gives an address rather than a url, so it also has to say "
                "which 'protocol' to ask for." % name
            )
        url = _url_for(address, protocol)
    return Source(
        name,
        url,
        interval=block.get('interval', DEFAULT_INTERVAL),
        timeout=block.get('timeout', DEFAULT_TIMEOUT),
        path=path_for(name, block),
        fetcher=protocol.fetcher if protocol is not None else None,
    )


def _url_for(address, protocol):
    """The URL to ask, from an address and the protocol that knows what to ask for.

    Somebody with a PurpleAir knows its address and has no reason to know that the
    answer is at `/json`. The protocol knows, so the address is enough.

    Args:
        address (str): What was typed in: a hostname, an address, or a whole URL.
        protocol (type): The protocol class, for its fetch_path and whether it is
            asked over HTTP at all.

    Returns:
        str: Where to ask.
    """
    address = address.rstrip('/')
    if '://' not in address and protocol.fetcher is None:
        # Only for the ones that are asked over HTTP. An Ecowitt gateway is a host
        # and a port and nothing else, and writing http:// in front of it would put
        # an address into the log that sends somebody to a browser.
        address = 'http://' + address
    path = protocol.fetch_path or ''
    if path.startswith(':') and _has_port(address):
        # A port rather than a path, which is what a protocol that is not asked over
        # HTTP has instead. It is a default and a well known one, so it is the part
        # of an address most likely to have been typed in already, and appending it
        # to an address that has one would ask on neither.
        path = ''
    # Not appended twice, for somebody who typed the whole of it either way.
    return address if path and address.endswith(path) else address + path


def _has_port(address):
    """Whether an address already says which port to ask on.

    Args:
        address (str): What was typed in.

    Returns:
        bool: Whether there is a port on the end of it.
    """
    return ':' in address.rsplit('/', 1)[-1]


# What a source's block may say about the station it is, as opposed to about the
# asking. The same keys a block under [[stations]] takes, so that one block does
# both and there is nothing to keep in step.
ABOUT_THE_STATION = ('role', 'channel', 'field_map_extensions', 'infer_unknown')

# What it may say about the asking.
ABOUT_THE_ASKING = ('url', 'address', 'protocol', 'interval', 'timeout', 'path')


def stations(section):
    """The stations the polled sources are, ready to be set up.

    A source that is asked needs nothing identified. The driver knows which sensor
    answered because it knows which address it asked, so there is no console to
    recognise, nothing to learn on a first upload and nothing to adopt. The block
    that says what to ask is therefore also the whole of the station, and this turns
    one into the other.

    The path is this driver's own and cannot arrive over HTTP as anything but a
    request nobody made: what makes the station is having asked for it.

    Args:
        section (dict | None): The `[[polling]]` subsection.

    Returns:
        dict: Block name to the station settings for it, in the shape
        `[[stations]]` uses.
    """
    made = {}
    for name in sorted(section or {}):
        block = section[name]
        if not hasattr(block, 'get'):
            continue
        settings = {key: block[key] for key in ABOUT_THE_STATION if key in block}
        settings['path'] = path_for(name, block)
        made[name] = settings
    return made


def path_for(name, block):
    """Where a polled source's answers are said to have arrived.

    Args:
        name (str): The block's name.
        block (dict): What is in it.

    Returns:
        str: The path, which is the source's own unless it says otherwise.
    """
    given = str(block.get('path', '')).strip()
    return given or ('/poll/' + name)


def named(section):
    """The protocol names the sources under [[polling]] ask for.

    Read before the poller is built, because a protocol has to be switched on before
    a source that wants it can be checked against the list.

    Args:
        section (dict | None): The `[[polling]]` subsection.

    Returns:
        list[str]: The names, without repeats, in the order they appear.
    """
    found = []
    for name in sorted(section or {}):
        block = section[name]
        if not hasattr(block, 'get'):
            continue
        wanted = str(block.get('protocol', '')).strip()
        if wanted and wanted not in found:
            found.append(wanted)
    return found
