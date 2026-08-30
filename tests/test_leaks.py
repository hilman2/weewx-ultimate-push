#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""Whether a connection ever gets left behind.

`ThreadingHTTPServer` makes a thread per request. That is fine when a request ends,
and it is a slow disaster when one does not: a station uploading every eight seconds
would add a thread and two file descriptors each time, and a few hours later the
process cannot open anything at all. `OSError: [Errno 24] Too many open files` is what
that looks like, and by then it takes down whatever else the process was doing.

What stops it here is the listener answering HTTP/1.0. There is no keep-alive, the
connection is closed after every response, and the thread ends with it. That is one
line in a file this driver does not own, so it is worth a test that would notice if it
ever changed.

Linux only, because it counts what is in /proc. WeeWX is a Unix program.
"""

import http.client
import os
import socket
import threading
import time

import pytest

pytest.importorskip('weewx', reason="WeeWX is not installed")
pytest.mark.skipif(not os.path.isdir('/proc/self/fd'), reason="needs /proc")

from ultimatepush.driver import UltimatePushDriver  # noqa: E402

BODY = 'PASSKEY=AAAA&stationtype=GW2000A_V3.1.5&tempf=59.7&humidity=91'


def descriptors():
    return len(os.listdir('/proc/self/fd'))


def settle(seconds=1.0):
    """Give the server's threads a moment to finish and be reaped."""
    time.sleep(seconds)


@pytest.fixture
def driver(tmp_path):
    if not os.path.isdir('/proc/self/fd'):
        pytest.skip("needs /proc")
    made = UltimatePushDriver(
        port=0,
        address='127.0.0.1',
        report_file='',
        socket_timeout=2,
        console_file=str(tmp_path / 'c.txt'),
        override_file=str(tmp_path / 'w.conf'),
    )
    yield made
    made.closePort()


def upload(port, read=True):
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
    try:
        connection.request('POST', '/', BODY)
        if read:
            connection.getresponse().read()
    finally:
        connection.close()


def test_an_upload_leaves_nothing_behind(driver):
    """The one that matters. A console uploads every eight seconds for years."""
    port = driver.listener.ports[0]
    for _ in range(5):
        upload(port)
    settle()
    threads, files = threading.active_count(), descriptors()

    for _ in range(100):
        upload(port)
    settle()

    assert threading.active_count() == threads
    assert descriptors() == files


def test_a_client_that_never_reads_the_answer_leaves_nothing_behind(driver):
    """Which is what a console does when it gives up mid-upload, and what anything
    behind a flaky network does regularly."""
    port = driver.listener.ports[0]
    upload(port)
    settle()
    threads, files = threading.active_count(), descriptors()

    for _ in range(30):
        upload(port, read=False)
    settle(1.5)

    assert threading.active_count() == threads
    assert descriptors() == files


def test_a_connection_that_is_opened_and_never_used_is_let_go(driver):
    """Otherwise anybody who can reach the port could hold every thread the process
    has by opening sockets and saying nothing."""
    port = driver.listener.ports[0]
    settle()
    threads = threading.active_count()

    quiet = socket.create_connection(('127.0.0.1', port))
    try:
        settle(0.3)
        assert threading.active_count() > threads  # it is being held
        # socket_timeout is 2 seconds for this driver.
        settle(3.0)
        assert threading.active_count() == threads  # and then let go
    finally:
        quiet.close()


def test_the_answer_closes_the_connection(driver):
    """HTTP/1.0, so there is no keep-alive and the handler thread ends. This is the
    whole reason the tests above pass, and it lives in a file this driver does not
    own: weewx.listener, bundled here until the core carries it."""
    connection = http.client.HTTPConnection(
        '127.0.0.1', driver.listener.ports[0], timeout=5
    )
    try:
        connection.request('POST', '/', BODY)
        response = connection.getresponse()
        response.read()

        assert response.version == 10
    finally:
        connection.close()


def test_the_web_interface_leaves_nothing_behind(tmp_path):
    """It is polled every few seconds for as long as somebody has the page open."""
    if not os.path.isdir('/proc/self/fd'):
        pytest.skip("needs /proc")
    token = 'a-token-long-enough'
    made = UltimatePushDriver(
        port=0,
        address='127.0.0.1',
        report_file='',
        socket_timeout=2,
        console_file=str(tmp_path / 'c.txt'),
        override_file=str(tmp_path / 'w.conf'),
        web={'enable': 'true', 'port': 0, 'address': '127.0.0.1', 'token': token},
    )
    try:
        port = made.listener.ports[1]

        def ask():
            connection = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
            try:
                connection.request('GET', '/api/state', headers={'X-Auth-Token': token})
                connection.getresponse().read()
            finally:
                connection.close()

        for _ in range(5):
            ask()
        settle()
        threads, files = threading.active_count(), descriptors()

        for _ in range(100):
            ask()
        settle()

        assert threading.active_count() == threads
        assert descriptors() == files
    finally:
        made.closePort()


def test_shutting_down_takes_the_threads_with_it(tmp_path):
    """A driver that left its server thread running would keep the port and stop
    WeeWX from restarting cleanly."""
    settle()
    before = threading.active_count()
    made = UltimatePushDriver(
        port=0,
        address='127.0.0.1',
        report_file='',
        console_file=str(tmp_path / 'c.txt'),
        override_file=str(tmp_path / 'w.conf'),
    )
    upload(made.listener.ports[0])
    made.closePort()
    settle()

    assert threading.active_count() == before
