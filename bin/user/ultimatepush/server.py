#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""Listening for more than one protocol at once.

The socket, the thread, the queue and the shutdown belong to weewx.listener and are
not reimplemented here. Two things it does not provide are needed once a driver
answers to several kinds of hardware, and both are small:

    **An answer that depends on the request.**  weewx.listener already takes a
    callable for the response body, but the content type is set once for the whole
    listener. An Ecowitt gateway wants JSON and a Weather Underground client wants
    plain text, on the same port, in the same second. So the content type follows the
    body, kept per thread because the server handles requests in several.

    **More than one listener behind one iterator.**  A driver's genLoopPackets
    iterates one thing. A station with a WeatherFlow hub broadcasting on UDP and an
    Ecowitt gateway posting over HTTP needs two, and a request from either has to
    reach the same loop. Fan does that, and keeps checking that both are still alive:
    an iterator blocked on a listener whose thread has died would wait for good.

Neither touches weewx.listener, which matters: on WeeWX 5.6 and later this driver uses
the core's copy, which it cannot change, and on anything older it uses the bundled one,
which has to stay byte for byte the same as the core's for the shim test to pass.
"""

import logging
import threading

log = logging.getLogger(__name__)

# How long to wait on one listener before looking at the next. Short enough that a
# datagram is not held up behind a quiet HTTP port, long enough not to spin.
TURN = 0.2


def http_listener(base, answer, queue=True, **options):
    """Return an HTTP listener whose answer decides its own content type.

    Args:
        base (type): The HTTPListener class to build on, from weewx.listener or from
            the bundled copy. Passed in rather than imported so that this module does
            not have to know which one the driver found.
        answer (callable): Given a Request, returns (body, content_type).
        queue (bool): Whether a request should also be handed to whoever is iterating.
            False for the web interface, where the answer is the whole point and a
            request nobody drains would fill the queue and start dropping the oldest
            with a warning each time.
        **options: Passed through to the base class.

    Returns:
        type: A listener class, ready to be instantiated with the usual listener
        options.
    """

    class Server(base):
        """An HTTPListener that lets each answer choose its own content type."""

        def __init__(self, **kwargs):
            self._answer = answer
            self._queue = queue
            self._per_request = threading.local()
            self._default_content_type = 'text/plain'
            super().__init__(**kwargs)

        def put(self, request):
            """Hand a request on to whoever is iterating, where anybody is.

            Args:
                request: The request the base class has just answered.
            """
            # The base class calls this after the answer has gone out. A listener
            # that exists to answer has nothing to hand on.
            if self._queue:
                super().put(request)

        def get_response(self, request):
            """The body to send back, remembering the content type it wants.

            Args:
                request: The request to answer.

            Returns:
                The body, as the base class expects it.
            """
            body, content_type = self._answer(request)
            # Read back by the handler immediately after this returns, on this same
            # thread. Per thread rather than per listener, because the server is a
            # ThreadingHTTPServer and two devices can be mid-upload at once.
            self._per_request.content_type = content_type
            return body

        @property
        def content_type(self):
            return getattr(self._per_request, 'content_type',
                           self._default_content_type)

        @content_type.setter
        def content_type(self, value):
            """Set the content type to fall back on.

            Args:
                value (str): The content type. The base class sets this in its
                    constructor, and it is kept as the answer for a response that
                    named none of its own.
            """
            # The base class sets this in its constructor. Keep it as the fallback
            # for a response nobody claimed.
            self._default_content_type = value

    return Server(**options)


class Fan:
    """Several listeners behind one iterator.

    Takes a turn on each in order. A listener that has stopped raises out of its own
    get(), which is what the driver needs to hear: nothing restarts a listener, and an
    iterator waiting on a dead one waits for good.

    Args:
        listeners (iterable): The listeners to take turns on. None entries are
            ignored, so that a caller can pass an optional listener without checking
            first.

    Raises:
        ValueError: If no listener is left, because a driver with none would wait for
            ever.
    """

    def __init__(self, listeners):
        self.listeners = [listener for listener in listeners if listener is not None]
        if not self.listeners:
            raise ValueError("A driver with no listener would wait for ever")

    def __iter__(self):
        return self

    def __next__(self):
        if len(self.listeners) == 1:
            # The common case, and the one where a timeout would only add latency.
            request = self.listeners[0].get()
            if request is None:
                raise StopIteration
            return request
        while True:
            for listener in self.listeners:
                if listener.closed.is_set():
                    raise StopIteration
                request = listener.get(timeout=TURN)
                if request is not None:
                    return request

    def close(self):
        for listener in self.listeners:
            try:
                listener.close()
            except Exception as e:
                # A listener that will not shut down must not stop the others from
                # doing so, or the port stays held after WeeWX has gone.
                log.error("Cannot stop a listener: %s", e)

    @property
    def ports(self):
        return [getattr(listener, 'port', None) for listener in self.listeners]

    @property
    def port(self):
        """The first listener's port.

        The HTTP one when there is one, because that is the order they are built in,
        and that is what somebody asking a driver which port it is on means.
        """
        return self.listeners[0].port
