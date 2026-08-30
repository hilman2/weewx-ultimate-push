#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""What the tests need in order to say what they mean.

A mapper needs a dialect, and most tests do not care which one: they are about
inference, or about a captured payload, and the dialect is scaffolding. These build
the one they meant.

Wire is here for a different reason: a driver that reads a console over a cable
cannot be opened without one, so it gets a pseudo terminal instead.
"""

import os
import select
import threading
import tty

from ultimatepush import protocols, transport
from ultimatepush.mapping import Mapper
from ultimatepush.protocols import Dialect


def mapper_for(
    fields=None,
    groups=None,
    channels=None,
    contested=None,
    placement_unknown=None,
    dialect=None,
    protocol='ecowitt',
    **kwargs,
):
    """A Mapper for a test.

    With no catalog given, it reads the named protocol's own, which is what the
    captured payloads in fixtures/ are. With one given, it builds a dialect out of
    exactly that, so a test about inference does not have to be rewritten every time
    the real catalog gains a sensor.
    """
    if dialect is None:
        if (
            fields is None
            and groups is None
            and channels is None
            and contested is None
            and placement_unknown is None
        ):
            dialect = protocols.by_name(protocol).dialect({})
        else:
            dialect = Dialect(
                'test',
                fields or {},
                groups,
                channels,
                contested,
                contested_with='another driver',
                placement_unknown=placement_unknown,
                prefix='test_',
            )
    return Mapper(dialect, **kwargs)


def read(protocol, text, **kwargs):
    """Read a captured payload the way the driver would, without a driver.

    Returns (packet, dialect, guesses). The protocol is named rather than detected,
    because a test about a catalog should fail on the catalog rather than on
    detection; detection has its own tests.
    """
    protocol = protocols.by_name(protocol) if isinstance(protocol, str) else protocol
    raw = transport.parse(text)
    dialect = protocol.dialect(raw)
    mapper = mapper_for(dialect=dialect, **kwargs)
    mapper.settle(protocol.settled_contested(raw))
    packet, guesses = mapper.to_packet(protocol.readings(FakeRequest(text), raw))
    return packet, dialect, guesses


def dialect_for(protocol, raw=None):
    """The dialect a protocol would read this payload with."""
    return protocols.by_name(protocol).dialect(raw or {})


class FakeRequest:
    """What a listener hands a driver, with only the parts a protocol looks at."""

    def __init__(
        self, text='', path='/data/report/', method='POST', client_address='10.0.0.5'
    ):
        self.text = text
        self.path = path
        self.method = method
        self.query = text if method == 'GET' else ''
        self.body = text.encode('utf-8') if method != 'GET' else b''
        self.headers = {}
        self.client_address = client_address


class Wire:
    """A serial port with nothing on the end of it but a test.

    A driver that reads a console over a cable can be opened against a pseudo
    terminal, which is a real serial device as far as pyserial is concerned. The
    driver opens one end and the test holds the other, so a cable driver can be run
    through the host, and answered, without a cable.

    This is the only way any of it can be exercised. There is no serial port in a
    container and there is no console on the end of one anywhere in this suite, and
    a driver that has only ever been imported has not been shown to work.

    Args:
        answers (dict | None): What to reply to each command the driver sends, as
            bytes to bytes. A driver that sends nothing and only listens needs none
            of this; give it `speaks` instead.
        speaks (bytes | None): A line to send over and over, for a driver that does
            not ask for anything.
        every (float): Seconds between lines, for a driver that does not ask.
    """

    def __init__(self, answers=None, speaks=None, every=0.2):
        self.answers = answers or {}
        self.speaks = speaks
        self.every = every
        self.asked = []
        self.master, self.slave = os.openpty()
        # Raw, or the terminal line discipline rewrites what goes past: it echoes
        # what the driver writes back at it, and turns \n into \r\n. Both would be
        # read as readings.
        tty.setraw(self.master)
        tty.setraw(self.slave)
        self.name = os.ttyname(self.slave)
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self._talk, daemon=True)
        self.thread.start()

    def _talk(self):
        """Answer what the driver asks, or talk regardless. On its own thread."""
        while not self.stopped.is_set():
            if self.speaks is not None:
                try:
                    os.write(self.master, self.speaks)
                except OSError:
                    return
                self.stopped.wait(self.every)
                continue
            ready, _, _ = select.select([self.master], [], [], 0.2)
            if not ready:
                continue
            try:
                asked = os.read(self.master, 256)
            except OSError:
                return
            if not asked:
                return
            self.asked.append(asked)
            for wanted, said in self.answers.items():
                if wanted in asked:
                    try:
                        os.write(self.master, said)
                    except OSError:
                        return
                    break

    def close(self):
        """Let go of both ends."""
        self.stopped.set()
        self.thread.join(5)
        for handle in (self.master, self.slave):
            try:
                os.close(handle)
            except OSError:
                pass
