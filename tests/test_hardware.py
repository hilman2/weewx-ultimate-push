#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""Hosting other people's drivers.

No real hardware, and none needed: what is being tested is the part this driver
owns, which is when a child is asked for packets, when it is left alone, what
happens when it fails, and which packets reach a child that is also a service.

The children here are modules made on the spot and put in sys.modules, because
that is how the real thing loads a driver: it imports the module the stanza names
and calls its loader, exactly as the WeeWX engine does.
"""

import inspect
import queue
import sys
import threading
import time
import types

import pytest

weewx = pytest.importorskip('weewx', reason="WeeWX is not installed")

from ultimatepush import hardware  # noqa: E402  (after the skip)

# Long enough that a test which expects nothing to be pulled would notice if
# something were, short enough not to be felt.
A_MOMENT = 0.3


class FakeDriver:
    """A driver that yields the packets it was given, then behaves like hardware.

    With `streams`, it keeps producing readings, the way a console that is plugged
    in does. Without it, it blocks waiting for one that never comes, the way a
    console does between readings and for good once it is unplugged. Both states
    matter, and they answer different questions.
    """

    # How often a streaming driver produces a reading. Short, so that a test does
    # not wait; a Vantage does this every two seconds.
    EVERY = 0.02

    def __init__(self, packets=(), fail_after=None, streams=False):
        self.packets = list(packets)
        self.fail_after = fail_after
        self.streams = streams
        self.released = threading.Event()
        self.closed = threading.Event()
        self.pulled = 0
        self.loops = 0

    @property
    def hardware_name(self):
        return 'Fake'

    def genLoopPackets(self):
        self.loops += 1
        for packet in self.packets:
            self.pulled += 1
            if self.fail_after is not None and self.pulled > self.fail_after:
                raise weewx.WeeWxIOError("the cable came out")
            yield dict(packet)
        while self.streams and not self.released.is_set():
            for packet in self.packets or [{'usUnits': 1}]:
                time.sleep(self.EVERY)
                self.pulled += 1
                yield dict(packet, dateTime=self.pulled)
        # Nothing more to send, and nothing coming. Wait, the way a read does.
        self.released.wait()

    def closePort(self):
        self.closed.set()
        # What lets a blocked read go. This is the whole reason closePort has to be
        # called from the thread that wants the driver to stop.
        self.released.set()


class Logger(FakeDriver):
    """A driver with a logger, so that the archive delegation has somewhere to go."""

    @property
    def archive_interval(self):
        return 300

    def genArchiveRecords(self, since_ts):
        yield {'dateTime': since_ts + 300, 'usUnits': 1, 'outTemp': 10.0}

    def getTime(self):
        return 1234567890


class Catcher(FakeDriver):
    """A driver that is also a service, the way the Vantage's is.

    Binds to NEW_LOOP_PACKET and writes into whatever packet it is given. If it is
    given somebody else's, the test that says so fails.
    """

    def __init__(self, engine, packets=()):
        super().__init__(packets)
        self.seen = []
        engine.bind(weewx.NEW_LOOP_PACKET, self.new_loop_packet)

    def new_loop_packet(self, event):
        self.seen.append(dict(event.packet))
        event.packet['windGust'] = 99.0


def install(name, build):
    """Put a driver module in sys.modules, so that a stanza can name it.

    Args:
        name (str): The module name to register, e.g. 'fake.one'.
        build (Callable[[dict, object], object]): Called as ``build(config, engine)``.
            Returns the driver, and stands in for the module's loader.

    Returns:
        types.ModuleType: The module, so a test can reach what it made.
    """
    module = types.ModuleType(name)
    module.loader = build
    sys.modules[name] = module
    return module


@pytest.fixture
def modules():
    """Register fake driver modules, and take them out again afterwards."""
    made = []

    def _install(name, build):
        made.append(name)
        return install(name, build)

    yield _install
    for name in made:
        sys.modules.pop(name, None)


def config_for(**stanzas):
    """A config_dict with one stanza per hosted driver.

    Args:
        **stanzas (dict): Station type to the options that stanza holds.

    Returns:
        dict: A config_dict shaped the way weewx.conf is.
    """
    return dict(stanzas)


# ---- the packets get through ------------------------------------------------


def test_a_child_s_packets_arrive_and_say_where_they_came_from(modules):
    made = {}
    modules(
        'fake.one',
        lambda config, engine: made.setdefault(
            'driver', FakeDriver([{'dateTime': 1, 'usUnits': 1, 'outTemp': 7.0}])
        ),
    )
    host = hardware.build(
        {'station_types': 'One'},
        config_for(One={'driver': 'fake.one'}),
        None,
    )
    try:
        host.start_loop()
        packet = host.get(timeout=2)
        assert packet['outTemp'] == 7.0
        assert packet['source'] == 'One'
    finally:
        host.close()


def test_two_children_share_one_stream(modules):
    modules(
        'fake.one',
        lambda c, e: FakeDriver([{'dateTime': 1, 'usUnits': 1, 'outTemp': 1.0}]),
    )
    modules(
        'fake.two',
        lambda c, e: FakeDriver([{'dateTime': 2, 'usUnits': 1, 'outTemp': 2.0}]),
    )
    host = hardware.build(
        {'station_types': 'One, Two'},
        config_for(One={'driver': 'fake.one'}, Two={'driver': 'fake.two'}),
        None,
    )
    try:
        host.start_loop()
        sources = {host.get(timeout=2)['source'] for _ in range(2)}
        assert sources == {'One', 'Two'}
    finally:
        host.close()


# ---- LOOP and history are exclusive -----------------------------------------


def test_a_stopped_child_is_not_pulled(modules):
    """The rule a serial console depends on.

    A Vantage streaming LOOP packets cannot answer DMPAFT at the same time. So
    between stop_loop and the next start_loop, nothing may be taken from the child
    at all: the engine is about to ask it for archive records over the same port.
    """
    seen = {}
    modules(
        'fake.one',
        lambda c, e: seen.setdefault('driver', FakeDriver(streams=True)),
    )
    host = hardware.build(
        {'station_types': 'One'}, config_for(One={'driver': 'fake.one'}), None
    )
    try:
        host.start_loop()
        host.get(timeout=2)
        host.stop_loop()
        while host.get(timeout=0.05) is not None:
            pass
        settled = seen['driver'].pulled
        time.sleep(A_MOMENT)
        assert seen['driver'].pulled == settled
        assert host.get(timeout=0.2) is None
    finally:
        host.close()


def test_stopping_abandons_the_generator_rather_than_closing_the_driver(modules):
    seen = {}
    modules('fake.one', lambda c, e: seen.setdefault('driver', Logger(streams=True)))
    host = hardware.build(
        {'station_types': 'One'}, config_for(One={'driver': 'fake.one'}), None
    )
    try:
        host.start_loop()
        host.get(timeout=2)
        host.stop_loop()
        # Still open: the engine wants to ask it for archive records next.
        assert not seen['driver'].closed.is_set()
        # Drain what the first generator had already produced, so that the packet
        # below can only have come from the second one.
        while host.get(timeout=0.05) is not None:
            pass
        host.start_loop()
        assert host.get(timeout=2) is not None
        assert seen['driver'].loops == 2
    finally:
        host.close()


def test_the_archive_station_is_waited_for_before_history_is_asked(modules):
    """The wait that makes the exclusion real.

    A child is told to stop between packets, so the message reaches it while it is
    inside a read. Python cannot interrupt that read, so stop_loop has to wait for
    it to return. Without the wait, the engine would issue DMPAFT down a port that
    is still mid-LOOP.
    """
    seen = {}
    modules('fake.one', lambda c, e: seen.setdefault('driver', Logger(streams=True)))
    host = hardware.build(
        {'station_types': 'One'}, config_for(One={'driver': 'fake.one'}), None
    )
    try:
        host.start_loop()
        host.get(timeout=2)
        host.stop_loop()
        # Already settled by the time stop_loop returned, so anything asked of the
        # device now has the port to itself.
        assert host.archive.idle.is_set()
    finally:
        host.close()


def test_a_child_stuck_in_a_read_is_said_so_rather_than_waited_out(modules, caplog):
    """The limit, stated rather than hidden.

    A driver that is blocked in a read cannot be stopped: nothing in Python
    interrupts one. So the wait runs out, and the log says which driver it was and
    what to check, instead of the archive quietly gaining a record nobody can
    account for.
    """
    modules('fake.one', lambda c, e: Logger())
    host = hardware.build(
        {'station_types': 'One'}, config_for(One={'driver': 'fake.one'}), None
    )
    try:
        host.start_loop()
        time.sleep(A_MOMENT)
        host.archive.settle = lambda timeout=None: False
        with caplog.at_level('WARNING'):
            host.stop_loop()
        assert 'still reading' in caplog.text
    finally:
        host.close()


def test_a_child_with_no_logger_is_not_waited_for(modules):
    """Nothing will be asked of it over that port, so nothing has to be exclusive."""
    modules('fake.one', lambda c, e: FakeDriver())
    host = hardware.build(
        {'station_types': 'One'}, config_for(One={'driver': 'fake.one'}), None
    )
    try:
        host.start_loop()
        time.sleep(A_MOMENT)
        began = time.time()
        host.stop_loop()
        assert time.time() - began < hardware.SETTLE / 2
    finally:
        host.close()


# ---- closing --------------------------------------------------------------


def test_closing_a_blocked_child_is_immediate(modules):
    """The child is closed from the calling thread, not through its queue.

    A driver waiting for hardware does not read its command queue, because it is
    inside genLoopPackets. Sending the close through that queue would wait out the
    whole join for exactly the drivers this project is about.
    """
    modules('fake.one', lambda c, e: FakeDriver())
    host = hardware.build(
        {'station_types': 'One'}, config_for(One={'driver': 'fake.one'}), None
    )
    host.start_loop()
    time.sleep(A_MOMENT)
    began = time.time()
    host.close()
    assert time.time() - began < hardware.JOIN / 2


def test_closing_reaches_every_child(modules):
    seen = {}
    modules('fake.one', lambda c, e: seen.setdefault('one', FakeDriver()))
    modules('fake.two', lambda c, e: seen.setdefault('two', FakeDriver()))
    host = hardware.build(
        {'station_types': 'One, Two'},
        config_for(One={'driver': 'fake.one'}, Two={'driver': 'fake.two'}),
        None,
    )
    host.start_loop()
    host.close()
    assert seen['one'].closed.is_set()
    assert seen['two'].closed.is_set()


# ---- a child that fails comes back ------------------------------------------


def test_a_failed_child_is_built_again(modules, monkeypatch):
    monkeypatch.setattr(hardware, 'FIRST_WAIT', 0.1)
    built = []

    def build(config, engine):
        # The first one fails after a packet; the one after it does not.
        driver = FakeDriver(
            [{'dateTime': len(built), 'usUnits': 1, 'outTemp': 1.0}],
            fail_after=0 if not built else None,
        )
        built.append(driver)
        return driver

    modules('fake.one', build)
    host = hardware.build(
        {'station_types': 'One'}, config_for(One={'driver': 'fake.one'}), None
    )
    try:
        host.start_loop()
        deadline = time.time() + 5
        while len(built) < 2 and time.time() < deadline:
            time.sleep(0.05)
        assert len(built) == 2, "the child was never built again"
        # And it is looping again, without anybody asking a second time.
        assert host.get(timeout=2) is not None
    finally:
        host.close()


def test_the_wait_grows_while_a_child_stays_away(modules, monkeypatch):
    monkeypatch.setattr(hardware, 'FIRST_WAIT', 0.05)
    tries = []

    def build(config, engine):
        tries.append(time.time())
        if len(tries) == 1:
            return FakeDriver([{'dateTime': 1, 'usUnits': 1}], fail_after=0)
        raise weewx.WeeWxIOError("still not there")

    modules('fake.one', build)
    host = hardware.build(
        {'station_types': 'One'}, config_for(One={'driver': 'fake.one'}), None
    )
    try:
        host.start_loop()
        deadline = time.time() + 5
        while len(tries) < 4 and time.time() < deadline:
            time.sleep(0.02)
        assert len(tries) >= 4, "it gave up instead of trying again"
        # Each wait is twice the one before, so the last gap is the longest.
        gaps = [b - a for a, b in zip(tries, tries[1:])]
        assert gaps[-1] > gaps[0]
    finally:
        host.close()


def test_a_secondary_child_that_will_not_open_is_left_out(modules):
    def refuse(config, engine):
        raise weewx.WeeWxIOError("no such port")

    modules('fake.one', lambda c, e: Logger())
    modules('fake.two', refuse)
    host = hardware.build(
        {'station_types': 'One, Two'},
        config_for(One={'driver': 'fake.one'}, Two={'driver': 'fake.two'}),
        None,
    )
    try:
        assert [child.station_type for child in host.children] == ['One']
    finally:
        host.close()


def test_an_archive_station_that_will_not_open_stops_the_driver(modules):
    """Fatal on purpose.

    Without the archive station the records would be generated from software while
    its logger quietly filled up. Those records would be wrong rather than missing,
    and nothing afterwards could tell which ones they were.
    """

    def refuse(config, engine):
        raise weewx.WeeWxIOError("no such port")

    modules('fake.one', refuse)
    with pytest.raises(weewx.WeeWxIOError):
        hardware.build(
            {'station_types': 'One'}, config_for(One={'driver': 'fake.one'}), None
        )


# ---- a driver that is also a service ----------------------------------------


def test_a_child_service_sees_only_its_own_packets(modules):
    """The Vantage bug, in one test.

    VantageService binds to NEW_LOOP_PACKET and writes the period's highest gust
    into the packet it is given. Bound to the real engine in a stream that carries
    more than one station, it would raise its own gust from somebody else's wind
    and overwrite a gust that other hardware measured itself.
    """
    caught = {}

    def build_catcher(config, engine):
        caught['driver'] = Catcher(engine, [{'dateTime': 1, 'usUnits': 1}])
        return caught['driver']

    modules('fake.one', build_catcher)
    modules('fake.two', lambda c, e: FakeDriver([{'dateTime': 2, 'usUnits': 1}]))
    host = hardware.build(
        {'station_types': 'One, Two'},
        config_for(One={'driver': 'fake.one'}, Two={'driver': 'fake.two'}),
        None,
    )
    try:
        host.start_loop()
        theirs = {'dateTime': 3, 'usUnits': 1, 'source': 'Two', 'windGust': 4.0}
        host.deliver(theirs)
        assert theirs['windGust'] == 4.0, "the other station's gust was overwritten"
        assert caught['driver'].seen == []

        mine = {'dateTime': 4, 'usUnits': 1, 'source': 'One'}
        host.deliver(mine)
        assert mine['windGust'] == 99.0
        assert len(caught['driver'].seen) == 1
    finally:
        host.close()


def test_a_forwarded_event_reaches_every_child(modules):
    seen = []

    def build(config, engine):
        engine.bind(weewx.END_ARCHIVE_PERIOD, lambda event: seen.append(event))
        return FakeDriver()

    modules('fake.one', build)
    modules('fake.two', build)
    host = hardware.build(
        {'station_types': 'One, Two'},
        config_for(One={'driver': 'fake.one'}, Two={'driver': 'fake.two'}),
        None,
    )
    try:
        host.forward(weewx.Event(weewx.END_ARCHIVE_PERIOD))
        assert len(seen) == 2
    finally:
        host.close()


def test_the_facade_hands_everything_else_to_the_real_engine():
    engine = types.SimpleNamespace(db_binder='the real one')
    facade = hardware.Facade(engine)
    assert facade.db_binder == 'the real one'


# ---- what the archive station answers for -----------------------------------


def test_can_reports_what_a_child_implements(modules):
    modules('fake.one', lambda c, e: Logger())
    host = hardware.build(
        {'station_types': 'One'}, config_for(One={'driver': 'fake.one'}), None
    )
    try:
        child = host.archive
        assert child.can('genArchiveRecords')
        assert child.can('archive_interval')
        assert not child.can('setTime')
        assert not child.can('genStartupRecords')
    finally:
        host.close()


def test_a_delegated_call_is_answered(modules):
    modules('fake.one', lambda c, e: Logger())
    host = hardware.build(
        {'station_types': 'One'}, config_for(One={'driver': 'fake.one'}), None
    )
    try:
        assert host.archive.call('archive_interval') == 300
        assert host.archive.call('getTime') == 1234567890
        records = host.archive.call('genArchiveRecords', 1000)
        # Drained on the child's thread, so a failure part way through arrives here
        # as that failure rather than as a broken iterator.
        assert isinstance(records, list)
        assert records[0]['dateTime'] == 1300
    finally:
        host.close()


def test_what_a_child_raises_arrives_at_the_caller(modules):
    class Cross(FakeDriver):
        def getTime(self):
            raise weewx.WeeWxIOError("the console did not answer")

    modules('fake.one', lambda c, e: Cross())
    host = hardware.build(
        {'station_types': 'One'}, config_for(One={'driver': 'fake.one'}), None
    )
    try:
        with pytest.raises(weewx.WeeWxIOError):
            host.archive.call('getTime')
    finally:
        host.close()


def test_the_archive_station_is_the_first_one_listed(modules):
    modules('fake.one', lambda c, e: Logger())
    modules('fake.two', lambda c, e: Logger())
    host = hardware.build(
        {'station_types': 'Two, One'},
        config_for(One={'driver': 'fake.one'}, Two={'driver': 'fake.two'}),
        None,
    )
    try:
        assert host.archive.station_type == 'Two'
    finally:
        host.close()


# ---- configuration ----------------------------------------------------------


def test_nothing_configured_hosts_nothing():
    assert hardware.build(None, {}, None) is None
    assert hardware.build({}, {}, None) is None


def test_a_stanza_that_is_not_there_is_said_so(modules):
    with pytest.raises(ValueError, match='no \\[One\\] section'):
        hardware.build({'station_types': 'One'}, {}, None)


def test_a_stanza_with_no_driver_is_said_so(modules):
    with pytest.raises(ValueError, match="no 'driver' option"):
        hardware.build({'station_types': 'One'}, config_for(One={'model': 'x'}), None)


def test_the_whole_config_reaches_the_child(modules):
    """Several drivers read more of weewx.conf than their own section.

    The simulator wants [Station] for its start time and ws23xx wants the lot, so
    the config_dict is handed over untouched rather than reshaped.
    """
    got = {}

    def build(config, engine):
        got['config'] = config
        return FakeDriver()

    modules('fake.one', build)
    whole = config_for(One={'driver': 'fake.one'}, Station={'station_type': 'One'})
    host = hardware.build({'station_types': 'One'}, whole, None)
    try:
        assert got['config'] is whole
    finally:
        host.close()


def test_the_host_reports_no_port():
    """A Fan asks its listeners for a port. Hosted hardware has none to give."""
    assert hardware.Host([], queue.Queue()).port is None


# ---- the drivers WeeWX actually ships ---------------------------------------

# What each stock driver can be asked for beyond loop packets, checked against the
# classes themselves rather than trusted. The engine's fallbacks depend on getting
# this right: a driver wrongly credited with genArchiveRecords would have its
# archive records asked for and get NotImplementedError from one thread away, and a
# driver wrongly denied genStartupRecords would silently stop catching up after a
# WeeWX outage.
#
# genStartupRecords and genArchiveRecords are separate on purpose. Four of the
# thirteen can hand over what they logged while WeeWX was down but cannot supply a
# record per archive period.
STOCK = {
    'acurite': (),
    'cc3000': ('genStartupRecords', 'archive_interval', 'getTime', 'setTime'),
    'fousb': ('genArchiveRecords', 'archive_interval'),
    'simulator': ('getTime',),
    'te923': ('genStartupRecords',),
    'ultimeter': (),
    'vantage': ('genArchiveRecords', 'archive_interval', 'getTime', 'setTime'),
    'wmr100': (),
    'wmr300': ('genStartupRecords',),
    'wmr9x8': (),
    'ws1': (),
    'ws23xx': (
        'genArchiveRecords',
        'genStartupRecords',
        'archive_interval',
    ),
    'ws28xx': ('genStartupRecords',),
}

ASKED_FOR = (
    'genArchiveRecords',
    'genStartupRecords',
    'archive_interval',
    'getTime',
    'setTime',
)


def driver_class(module):
    """The class a stock driver's loader builds, without building one.

    Args:
        module (types.ModuleType): A module from weewx.drivers.

    Returns:
        type: The driver class, found by name among the module's classes.
    """
    import weewx.drivers

    for value in vars(module).values():
        if (
            isinstance(value, type)
            and issubclass(value, weewx.drivers.AbstractDevice)
            and value is not weewx.drivers.AbstractDevice
            and hasattr(value, 'genLoopPackets')
        ):
            return value
    raise AssertionError("no driver class in %s" % module.__name__)


@pytest.mark.parametrize('name', sorted(STOCK))
def test_every_stock_driver_is_shaped_the_way_the_host_expects(name):
    """Each one loads, names its stanza, and offers what the table says.

    No hardware: nothing here builds a driver, it only looks at the class. That is
    the same thing `implements` looks at, which is why the delegation can be trusted
    on a machine that has none of this hardware attached.
    """
    module = pytest.importorskip('weewx.drivers.' + name)
    assert callable(module.loader), "a hosted driver is loaded through loader()"
    assert isinstance(module.DRIVER_NAME, str) and module.DRIVER_NAME

    klass = driver_class(module)
    offered = tuple(part for part in ASKED_FOR if hardware.implements(klass, part))
    assert offered == tuple(
        part for part in ASKED_FOR if part in STOCK[name]
    ), "%s offers %s" % (name, offered)


def test_the_vantage_loader_is_the_only_one_that_wants_the_engine():
    """Why the Facade exists at all.

    Every other stock loader ignores the engine it is handed. The Vantage's builds a
    VantageService, which binds to it. If a second driver ever does that, the
    guarantee that a service sees only its own packets is the thing that has to be
    checked next, so this test is here to notice.
    """
    services = []
    for name in sorted(STOCK):
        module = pytest.importorskip('weewx.drivers.' + name)
        source = inspect.getsource(module.loader)
        if 'engine' in source.split('return', 1)[-1]:
            services.append(name)
    assert services == ['vantage']


def test_the_simulator_can_actually_be_hosted():
    """One stock driver end to end, because it is the one that needs no hardware.

    This is the whole loading path with nothing faked: the real module, the real
    loader, the real config_dict, and a packet out of the real driver.
    """
    pytest.importorskip('weewx.drivers.simulator')
    config = {
        'Simulator': {
            'driver': 'weewx.drivers.simulator',
            'loop_interval': '1',
            'mode': 'simulator',
        },
        'StdArchive': {'archive_interval': '300'},
    }
    host = hardware.build({'station_types': 'Simulator'}, config, None)
    assert host is not None
    try:
        host.start_loop()
        packet = host.get(timeout=10)
        assert packet is not None, "the simulator produced nothing"
        assert packet['source'] == 'Simulator'
        assert 'outTemp' in packet
        # The simulator has a clock but no logger, so exactly one of the five is
        # offered and the other four fall back to what weewx.conf says.
        assert host.archive.can('getTime')
        assert not host.archive.can('genArchiveRecords')
    finally:
        host.close()


# ---- one column, one station, hardware included -----------------------------


def hosted_rows(driver):
    """The hosted drivers, as the Stations tab sees them.

    There is no separate list of them any more: a hosted driver is a station, and
    stations come from one place.

    Args:
        driver (ultimatepush.driver.UltimatePushDriver): The driver to ask.

    Returns:
        list[dict]: The rows whose station is a driver this one reads.
    """
    return [
        row for row in driver.web_stations_view()['stations'] if row['station_type']
    ]


def packets_from(driver, count, seconds=10):
    """Take a few loop packets from a driver, then let go of it.

    Args:
        driver (ultimatepush.driver.UltimatePushDriver): The driver to pull from.
        count (int): How many packets to wait for.
        seconds (float): How long to wait for all of them.

    Returns:
        list[dict]: The packets, which may be fewer than asked for if the time ran
        out. A test says what it expected, so a short list fails where it means
        something rather than here.
    """
    got = []
    loop = driver.genLoopPackets()

    def pull():
        for packet in loop:
            got.append(packet)
            if len(got) >= count:
                return

    # On a thread, because a driver that is waiting for hardware waits for good and
    # a test that asked for a packet too many must fail rather than hang.
    reader = threading.Thread(target=pull, daemon=True)
    reader.start()
    reader.join(seconds)
    return list(got)


@pytest.fixture
def hosting(modules, tmp_path):
    """Build a real driver that hosts fake hardware.

    Yields:
        Callable[..., ultimatepush.driver.UltimatePushDriver]: Called as
            ``build(hardware, **stanzas)``, where `hardware` is the [[hardware]]
            subsection and each stanza names a fake driver module.
    """
    from ultimatepush.driver import UltimatePushDriver

    made = []

    def _build(hardware_section, web=False, **stanzas):
        driver = UltimatePushDriver(
            port=0,
            address='127.0.0.1',
            weewx_root=str(tmp_path),
            hardware=hardware_section,
            config_dict=dict(stanzas),
            # Switching the interface on is also what gives the driver somewhere to
            # put a driver added later, so a test about adding one needs it.
            web=(
                {
                    'enable': 'true',
                    'port': 0,
                    'address': '127.0.0.1',
                    'token': 'a-token-long-enough',
                }
                if web
                else None
            ),
        )
        made.append(driver)
        return driver

    yield _build
    for driver in made:
        driver.closePort()


def test_a_hosted_main_station_writes_where_its_readings_belong(modules, hosting):
    modules(
        'fake.one',
        lambda c, e: FakeDriver(
            [{'dateTime': 1, 'usUnits': 1, 'outTemp': 7.0, 'barometer': 1013.0}]
        ),
    )
    driver = hosting(
        {'station_types': 'One', 'One': {'role': 'main', 'name': 'The Vantage'}},
        One={'driver': 'fake.one'},
    )
    got = packets_from(driver, 1)
    assert got, "no packet came out of the driver"
    assert got[0]['outTemp'] == 7.0
    assert got[0]['barometer'] == 1013.0
    # With a space, which weewx.conf allows and the web interface does not. That
    # file is somebody's, and a driver refusing to start over a cosmetic name would
    # be worse than the inconsistency.
    assert got[0]['station'] == 'The Vantage'


def test_a_hosted_extra_station_is_moved_out_of_the_way(modules, hosting):
    """The rule roles.py states, applied to a packet instead of to a field map.

    An upload is shifted by the mapper while the raw names are still there. A hosted
    driver hands over finished WeeWX fields, so the shift happens to the packet.
    Temperature and humidity have somewhere to go. Pressure does not, and is dropped
    rather than written over the main station's.
    """
    # Both keep sending, and the main station has a reading of its own, because an
    # extra station is held back until the main one has been heard once. Which
    # thread gets there first is not fixed, so the extra one has to be able to try
    # again. See driver._hold_back.
    modules(
        'fake.main',
        lambda c, e: FakeDriver([{'usUnits': 1, 'outTemp': 9.0}], streams=True),
    )
    modules(
        'fake.extra',
        lambda c, e: FakeDriver(
            [{'usUnits': 1, 'outTemp': 3.0, 'outHumidity': 55.0, 'barometer': 1013.0}],
            streams=True,
        ),
    )
    driver = hosting(
        {
            'station_types': 'Main, Extra',
            'Main': {'role': 'main'},
            'Extra': {'role': 'extra', 'channel': 3},
        },
        Main={'driver': 'fake.main'},
        Extra={'driver': 'fake.extra'},
    )
    got = packets_from(driver, 12)
    moved = [p for p in got if p.get('source') == 'Extra']
    assert moved, "the extra station's packet never came through"
    assert moved[0]['extraTemp3'] == 3.0
    assert moved[0]['extraHumid3'] == 55.0
    assert 'outTemp' not in moved[0]
    assert 'barometer' not in moved[0], "it was written over the main station's"


def test_an_extra_station_with_no_channel_is_refused(modules, hosting):
    """Nothing sensible to guess.

    A channel picked here would move somebody's readings to a different column on
    the next restart, which is the one thing this driver does not do quietly.
    """
    modules('fake.one', lambda c, e: FakeDriver())
    with pytest.raises(ValueError, match='needs a..channel'):
        hosting(
            {'station_types': 'One', 'One': {'role': 'extra'}},
            One={'driver': 'fake.one'},
        )


def test_a_hosted_station_gets_an_identity_that_survives_a_restart(modules, hosting):
    """owners.py keeps a column with the station that filled it, by identity.

    A console has a PASSKEY to be known by. A driver has nothing, so it is given a
    name built from its stanza, which is the same on the next run.
    """
    modules('fake.one', lambda c, e: FakeDriver())
    driver = hosting(
        {'station_types': 'One', 'One': {'role': 'main'}}, One={'driver': 'fake.one'}
    )
    assert 'driver:One' in driver.stations
    assert driver.stations['driver:One'].station_type == 'One'
    # And it is not a console anyone may upload as.
    assert 'driver:One' not in driver.known


def test_source_is_not_a_column_anybody_can_own(modules, hosting):
    """It names the station rather than measuring anything.

    Without this, the first hosted station to send a packet would claim a column
    called 'source' and every other station would be turned away from it.
    """
    from ultimatepush import owners

    assert 'source' in owners.NOT_A_READING
    assert owners.readings({'dateTime': 1, 'usUnits': 1, 'source': 'One', 'x': 2}) == [
        'x'
    ]


def test_the_interface_shows_a_hosted_station(modules, hosting):
    """A wired station has no upload behind it, and must not read 'never heard from'.

    The stations page is the one thing in this driver that has to be right about
    what is being recorded, so a hosted driver's readings are noted the way an
    upload's are, minus the parts an upload has and this does not.
    """
    modules(
        'fake.one',
        lambda c, e: FakeDriver([{'usUnits': 1, 'outTemp': 7.0}], streams=True),
    )
    driver = hosting(
        {'station_types': 'One', 'One': {'role': 'main', 'name': 'The Vantage'}},
        One={'driver': 'fake.one'},
    )
    assert packets_from(driver, 1), "no packet came out of the driver"

    rows = driver.web_stations_view()['stations']
    mine = [row for row in rows if row['ident'] == 'driver:One']
    assert mine, "the hosted station is not on the stations page"
    assert mine[0]['name'] == 'The Vantage'
    assert mine[0]['heard'] is not None, "it reads as never heard from"

    # And the pages that ask about every station do not fall over on one that has
    # no protocol, no path and no catalog.
    assert driver.web_fields() is not None
    assert driver.web_overview() is not None
    assert driver.web_setup() is not None


# ---- two unit systems, and nothing converting them ---------------------------


def test_two_unit_systems_with_no_converter_are_said_once(modules, hosting, caplog):
    """weewx.accum refuses the second one and the archive record is lost.

    Not something startup can see: which catalog reads an upload is settled per
    upload, so two consoles look the same until both have been heard. A hosted
    driver makes it likelier, because a Vantage reports US whatever the console
    beside it does.
    """
    modules(
        'fake.us',
        lambda c, e: FakeDriver([{'usUnits': 1, 'outTemp': 59.0}], streams=True),
    )
    modules(
        'fake.metric',
        lambda c, e: FakeDriver([{'usUnits': 17, 'outTemp': 15.0}], streams=True),
    )
    driver = hosting(
        {
            'station_types': 'Us, Metric',
            'Us': {'role': 'main', 'name': 'The Vantage'},
            'Metric': {'role': 'extra', 'channel': 2, 'name': 'The gateway'},
        },
        Us={'driver': 'fake.us'},
        Metric={'driver': 'fake.metric'},
    )
    with caplog.at_level('ERROR'):
        packets_from(driver, 12)
    assert 'Unit system mismatch' in caplog.text
    assert 'The Vantage sends US' in caplog.text
    assert 'The gateway sends METRICWX' in caplog.text
    # Once. A message per packet would bury the one that matters.
    assert caplog.text.count('Two unit systems') == 1


def test_a_configured_target_unit_says_nothing(modules, hosting, caplog):
    modules(
        'fake.us',
        lambda c, e: FakeDriver([{'usUnits': 1, 'outTemp': 59.0}], streams=True),
    )
    modules(
        'fake.metric',
        lambda c, e: FakeDriver([{'usUnits': 17, 'outTemp': 15.0}], streams=True),
    )
    driver = hosting(
        {
            'station_types': 'Us, Metric',
            'Us': {'role': 'main'},
            'Metric': {'role': 'extra', 'channel': 2},
        },
        StdConvert={'target_unit': 'METRICWX'},
        Us={'driver': 'fake.us'},
        Metric={'driver': 'fake.metric'},
    )
    with caplog.at_level('ERROR'):
        packets_from(driver, 12)
    assert 'Two unit systems' not in caplog.text


def test_one_unit_system_says_nothing(modules, hosting, caplog):
    modules(
        'fake.us',
        lambda c, e: FakeDriver([{'usUnits': 1, 'outTemp': 59.0}], streams=True),
    )
    driver = hosting(
        {'station_types': 'Us', 'Us': {'role': 'main'}}, Us={'driver': 'fake.us'}
    )
    with caplog.at_level('ERROR'):
        packets_from(driver, 4)
    assert 'Two unit systems' not in caplog.text


# ---- setting a driver up through the web interface ---------------------------


def test_the_drivers_on_this_machine_are_offered(hosting):
    """Including whatever somebody installed, because that is where they look.

    Anything under 'user' that has a loader and a DRIVER_NAME is a driver, which is
    all WeeWX itself asks of one. The form comes from the driver's own configuration
    editor, so it is the one its author wrote.
    """
    driver = hosting(None, web=True)
    answer = driver.web_ways()

    assert answer['ok'] and answer['can_fetch']
    by_name = {one['name']: one for one in answer['ways']}
    assert 'Vantage' in by_name, "the drivers WeeWX ships are not offered"
    assert by_name['Vantage']['hardware'] == 'weewx.drivers.vantage'
    # Straight out of VantageConfEditor, not out of a copy kept here.
    assert by_name['Vantage']['fields']['port']['value'] == '/dev/ttyUSB0'
    assert by_name['Vantage']['problem'] is None


# ---- the form a driver describes of itself -----------------------------------


def test_every_field_carries_what_its_author_says_it_is(hosting):
    """The comment above the option in the driver's own stanza.

    That sentence is the answer to "how do I know what goes in here", and it was
    written by whoever wrote the driver. Keeping a second copy of it here would be
    keeping something that goes out of date silently.
    """
    fields = {one['name']: one for one in hosting(None, web=True).web_ways()['ways']}
    vantage = fields['Vantage']['fields']

    assert 'Connection type: serial or ethernet' in vantage['type']['help']
    assert '/dev/ttyUSB0 is a common USB port name' in vantage['port']['help']
    # A line each, in the order it was written: the Vantage says what the connection
    # type is, then what each of the two means.
    assert len(vantage['type']['help']) == 3
    # The section's own preamble belongs to the section, not to whichever option
    # happens to come first, and a banner between two groups belongs to neither.
    assert not any('This section is for' in line for line in vantage['type']['help'])
    assert vantage['baudrate']['help'] == ['Serial baud rate (usually 19200)']


def test_an_option_with_a_fixed_set_of_values_offers_them(hosting):
    fields = {one['name']: one for one in hosting(None, web=True).web_ways()['ways']}

    vantage = fields['Vantage']['fields']
    assert vantage['type']['kind'] == 'choice'
    assert [one['value'] for one in vantage['type']['choices']] == [
        'serial',
        'ethernet',
    ]
    # A value that means nothing on its own is shown with what it means.
    assert [one['label'] for one in vantage['model_type']['choices']] == [
        '1 — Vantage Pro',
        '2 — Vantage Pro2',
    ]
    assert [
        one['value']
        for one in fields['WS28xx']['fields']['transceiver_frequency']['choices']
    ] == ['US', 'EU']


def test_an_option_that_only_gives_examples_does_not(hosting):
    """The distinction that makes the list worth having.

    'Serial port such as /dev/ttyS0, /dev/ttyUSB0, or /dev/cuaU0' reads exactly like
    'serial or ethernet' and is not a choice at all: it is three examples of a free
    value. A list built from that sentence would offer three ports as though they
    were the only ones this machine could have.
    """
    fields = {one['name']: one for one in hosting(None, web=True).web_ways()['ways']}

    assert fields['CC3000']['fields']['model']['choices'] == []
    assert fields['CC3000']['fields']['model']['kind'] == 'text'
    assert fields['WS23xx']['fields']['port']['choices'] == []


def test_a_serial_port_is_offered_as_a_device_rather_than_explained(hosting):
    """Whichever devices this machine has, not a sentence about naming conventions.

    'Which of these is my station' is answerable from an adapter's name and not from
    an empty box. On a machine with no serial devices, and on one with no /dev at
    all, the list is empty and the field falls back to a box, which the page says.
    """
    answer = hosting(None, web=True).web_ways()
    fields = {one['name']: one for one in answer['ways']}

    assert fields['Vantage']['fields']['port']['kind'] == 'port'
    assert isinstance(answer['ports'], list)
    for port in answer['ports']:
        assert port['value'] and port['label']


def test_the_choices_kept_here_still_match_the_drivers(hosting):
    """The test that makes a copy honest.

    hardware.CHOICES repeats something the drivers only say in prose. So every entry
    is checked against the driver it names: the option still exists, and the
    driver's own default is one of the values offered. A driver that renames an
    option or gains a choice fails here rather than quietly offering the wrong list.
    """
    for module_name, options in hardware.CHOICES.items():
        module = pytest.importorskip(module_name)
        fields = hardware.template_for(module)['fields']
        for key, choices in options.items():
            assert key in fields, "%s has no option '%s' any more" % (module_name, key)
            offered = [one['value'] for one in fields[key]['choices']]
            assert (
                fields[key]['value'] in offered
            ), "%s defaults %s to %r, which is not one of %s" % (
                module_name,
                key,
                fields[key]['value'],
                offered,
            )


def test_a_driver_with_no_configuration_editor_still_offers_its_module(modules):
    """A driver from elsewhere need not carry one, and most of them do.

    Without it there is nothing to describe, but the one thing that has to be in the
    stanza is the module to import, so that is what the form holds.
    """
    module = install('fake.bare', lambda c, e: FakeDriver())
    module.DRIVER_NAME = 'Bare'

    fields = hardware.template_for(module)['fields']

    assert list(fields) == ['driver']
    assert fields['driver']['value'] == 'fake.bare'
    assert fields['driver']['choices'] == []


def test_a_driver_is_opened_before_anything_is_written(modules, hosting):
    """A serial port that is not there should be a message, not an entry to undo."""

    def refuse(config, engine):
        raise weewx.WeeWxIOError("could not open /dev/ttyUSB7")

    modules('fake.absent', refuse)
    driver = hosting(None, web=True)
    ok, message = driver.web_add_hardware(
        'Absent', {'driver': 'fake.absent', 'port': '/dev/ttyUSB7'}
    )

    assert not ok
    assert '/dev/ttyUSB7' in message
    assert 'Nothing has been saved' in message
    assert driver.overrides.hardware() == {}
    assert hosted_rows(driver) == []


def test_a_driver_added_here_starts_without_a_restart(modules, hosting):
    modules(
        'fake.one',
        lambda c, e: FakeDriver([{'usUnits': 1, 'outTemp': 7.0}], streams=True),
    )
    driver = hosting(None, web=True)
    ok, _ = driver.web_add_hardware('One', {'driver': 'fake.one'}, name='The-Vantage')
    assert ok

    hosted = hosted_rows(driver)
    assert [one['station_type'] for one in hosted] == ['One']
    assert hosted[0]['running'] and hosted[0]['archive']
    # Set up here, so it can be changed here; weewx.conf did not declare it.
    assert hosted[0]['editable'] and not hosted[0]['declared']

    got = packets_from(driver, 1)
    assert got, "the driver was set up but nothing came out of it"
    assert got[0]['outTemp'] == 7.0
    assert got[0]['station'] == 'The-Vantage'


def test_a_driver_added_here_is_still_there_after_a_restart(modules, hosting):
    """The whole point of writing it down.

    The second driver is built the way WeeWX builds one at startup, from weewx.conf
    alone. Everything it hosts therefore came out of the settings file, stanza and
    all, which is the path that would quietly not work.
    """
    modules(
        'fake.one',
        lambda c, e: FakeDriver([{'usUnits': 1, 'outTemp': 7.0}], streams=True),
    )
    first = hosting(None, web=True)
    ok, _ = first.web_add_hardware(
        'One', {'driver': 'fake.one', 'port': '/dev/ttyUSB0'}, name='The-Vantage'
    )
    assert ok
    first.closePort()

    again = hosting(None, web=True)
    hosted = hosted_rows(again)
    assert [one['station_type'] for one in hosted] == ['One']
    assert hosted[0]['running']
    assert hosted[0]['options']['port'] == '/dev/ttyUSB0'
    assert 'driver:One' in again.stations
    assert again.stations['driver:One'].name == 'The-Vantage'


def test_an_extra_station_added_here_is_given_a_free_channel(modules, hosting):
    """Safe here and not in weewx.conf.

    The pick is written to the settings file as it is made, so it is the same after
    a restart. A channel guessed at load time would not be.
    """
    modules('fake.one', lambda c, e: FakeDriver())
    modules('fake.two', lambda c, e: FakeDriver())
    driver = hosting(None, web=True)
    driver.web_add_hardware('One', {'driver': 'fake.one'})
    ok, _ = driver.web_add_hardware('Two', {'driver': 'fake.two'}, role='extra')

    assert ok
    assert driver.stations['driver:Two'].channel == 1
    assert driver.overrides.hardware()['Two']['channel'] == '1'


def test_new_settings_that_will_not_open_leave_the_old_driver_running(modules, hosting):
    built = []

    def build(config, engine):
        if config['One'].get('port') == '/dev/nope':
            raise weewx.WeeWxIOError("no such port")
        built.append(1)
        return FakeDriver([{'usUnits': 1, 'outTemp': 7.0}], streams=True)

    modules('fake.one', build)
    driver = hosting(None, web=True)
    assert driver.web_add_hardware('One', {'driver': 'fake.one', 'port': '/dev/ok'})[0]

    ok, message = driver.web_edit_hardware(
        'One', options={'driver': 'fake.one', 'port': '/dev/nope'}
    )
    assert not ok
    assert 'still is' in message
    assert hosted_rows(driver)[0]['running']
    assert driver.overrides.hardware()['One']['options']['port'] == '/dev/ok'
    assert len(built) == 1, "the old driver was replaced anyway"


def test_removing_a_driver_stops_it_and_frees_its_columns(modules, hosting):
    seen = {}
    modules(
        'fake.one',
        lambda c, e: seen.setdefault(
            'driver', FakeDriver([{'usUnits': 1, 'outTemp': 7.0}], streams=True)
        ),
    )
    driver = hosting(None, web=True)
    driver.web_add_hardware('One', {'driver': 'fake.one'})
    packets_from(driver, 1)
    assert driver.owners.owner('outTemp') == 'driver:One'

    ok, _ = driver.web_remove_hardware('One')

    assert ok
    assert seen['driver'].closed.is_set()
    assert hosted_rows(driver) == []
    assert 'driver:One' not in driver.stations
    assert driver.owners.owner('outTemp') is None


def test_the_archive_station_can_be_changed(modules, hosting):
    modules('fake.one', lambda c, e: Logger())
    modules('fake.two', lambda c, e: Logger())
    driver = hosting(None, web=True)
    driver.web_add_hardware('One', {'driver': 'fake.one'})
    driver.web_add_hardware('Two', {'driver': 'fake.two'}, role='extra', channel=2)
    assert driver.hardware.archive.station_type == 'One'

    ok, _ = driver.web_hardware_order(['Two', 'One'])

    assert ok
    assert driver.hardware.archive.station_type == 'Two'
    # The rows are in name order, so which one answers for the archive is a flag on
    # them rather than their position.
    archive = [one['station_type'] for one in hosted_rows(driver) if one['archive']]
    assert archive == ['Two']


def test_a_driver_weewx_conf_names_is_left_alone(modules, hosting):
    """One file has the answer.

    Two files with a stanza each would mean one is quietly ignored, and which one
    would depend on the order they happened to be read in.
    """
    modules('fake.one', lambda c, e: FakeDriver())
    driver = hosting(
        {'station_types': 'One', 'One': {'role': 'main'}},
        web=True,
        One={'driver': 'fake.one'},
    )
    hosted = hosted_rows(driver)
    assert hosted[0]['declared'], "weewx.conf named it, so that file owns it"
    assert not hosted[0]['editable']

    ok, message = driver.web_edit_hardware('One', name='Something else')
    assert not ok and 'weewx.conf' in message

    ok, message = driver.web_remove_hardware('One')
    assert not ok and 'weewx.conf' in message


def test_a_section_weewx_conf_already_has_is_refused(modules, hosting):
    modules('fake.one', lambda c, e: FakeDriver())
    driver = hosting(None, web=True, Vantage={'driver': 'fake.one'})

    ok, message = driver.web_add_hardware('Vantage', {'driver': 'fake.one'})

    assert not ok
    assert 'weewx.conf already has' in message


def test_the_same_driver_is_not_hosted_twice(modules, hosting):
    modules('fake.one', lambda c, e: FakeDriver())
    driver = hosting(None, web=True)
    assert driver.web_add_hardware('One', {'driver': 'fake.one'})[0]

    ok, message = driver.web_add_hardware('One', {'driver': 'fake.one'})

    assert not ok and 'already being hosted' in message


def test_a_stanza_with_no_module_is_refused(modules, hosting):
    driver = hosting(None, web=True)

    ok, message = driver.web_add_hardware('One', {'port': '/dev/ttyUSB0'})

    assert not ok
    assert "'driver' option" in message


def test_a_name_that_would_break_a_section_heading_is_refused(modules, hosting):
    """The same rule a station set up in the interface gets, and for the same reason.

    The name is written to a settings file in the format weewx.conf uses, and it
    goes into the packet as 'station'.
    """
    modules('fake.one', lambda c, e: FakeDriver())
    driver = hosting(None, web=True)

    ok, message = driver.web_add_hardware(
        'One', {'driver': 'fake.one'}, name='The Vantage'
    )

    assert not ok
    assert 'letters, digits, dashes and underscores' in message


# ---- one list, whatever the hardware is --------------------------------------


def test_every_way_in_is_in_one_list(modules, hosting):
    """Protocols and drivers together, because the user has a weather station.

    Which of them this driver polls and which upload to it is this driver's
    business. What somebody setting one up has to decide is what to do next, and
    that is what 'how' says.
    """
    modules('fake.one', lambda c, e: FakeDriver())
    driver = hosting(None, web=True)
    ways = driver.web_ways()['ways']

    kinds = {one['kind'] for one in ways}
    assert kinds == {'protocol', 'driver'}
    assert {one['how'] for one in ways} <= {'point', 'arrives', 'fetch'}
    by_name = {one['name']: one for one in ways}
    assert by_name['ecowitt']['how'] == 'point'
    assert by_name['Vantage']['how'] == 'fetch'
    assert by_name['acurite']['how'] == 'arrives'


def test_weather_underground_is_pointed_here_and_named_here(hosting):
    """Two questions that were run together once, and are now apart.

    A current Fine Offset console has a Server field like any other, so it is
    pointed at this machine in the ordinary way. Its path is fixed in the firmware,
    so this driver cannot give it one. But it carries an ID and a PASSWORD that are
    anybody's to choose, so the driver chooses them, and it is known from its first
    upload without being adopted.
    """
    driver = hosting(None, web=True)
    ways = {one['name']: one for one in driver.web_ways()['ways']}
    wu = ways['wunderground']

    assert wu['how'] == 'point'
    assert dict(wu['settings']).get('Server')
    assert wu['can_create'] is True
    # And the ones that carry nothing to be told still have to be heard first.
    assert ways['acurite']['can_create'] is False
    assert ways['weatherflow']['can_create'] is False


def test_a_protocol_that_is_off_is_listed_rather_than_missing(hosting):
    """A list that claims to be every way in has to hold the ones that are off.

    WeatherFlow costs a second socket, so it is not opened unless it is named.
    Leaving it out means somebody with a Tempest has to know it exists before the
    page can tell them it does.
    """
    driver = hosting(None, web=True)
    ways = {one['name']: one for one in driver.web_ways()['ways']}

    assert 'weatherflow' in ways
    assert ways['weatherflow']['enabled'] is False
    assert ways['weatherflow']['how'] == 'arrives'
    assert ways['ecowitt']['enabled'] is True
    # And its own notes carry the line for switching it on, so the page needs none.
    assert any('protocols = ' in note for note in ways['weatherflow']['notes'])


def test_a_driver_already_set_up_is_not_offered_again(hosting):
    """With a real driver, because the list is built from what is on disk.

    The Simulator is the one WeeWX ships that needs no hardware, so it is the one
    that can actually be set up in a test and then looked for again.
    """
    pytest.importorskip('weewx.drivers.simulator')
    driver = hosting(None, web=True)
    ok, message = driver.web_add_hardware(
        'Simulator', {'driver': 'weewx.drivers.simulator', 'mode': 'simulator'}
    )
    assert ok, message

    ways = {one['name']: one for one in driver.web_ways()['ways']}
    assert ways['Simulator']['taken'] is True
    assert ways['Vantage']['taken'] is False


def test_a_hosted_station_is_managed_where_the_others_are(modules, hosting):
    """No separate place for it. It is a station, and stations are on one tab."""
    modules(
        'fake.one',
        lambda c, e: FakeDriver([{'usUnits': 1, 'outTemp': 7.0}], streams=True),
    )
    driver = hosting(None, web=True)
    driver.web_add_hardware('One', {'driver': 'fake.one', 'port': '/dev/ttyUSB0'})
    packets_from(driver, 1)

    rows = {row['ident']: row for row in driver.web_stations_view()['stations']}
    mine = rows['driver:One']
    assert mine['station_type'] == 'One'
    assert mine['editable'], "it was set up here, so it can be changed here"
    assert mine['options']['port'] == '/dev/ttyUSB0'
    assert mine['protocol'] == '', "it speaks no protocol; it is read"
    assert mine['answers_for'] == []


def test_a_driver_that_takes_one_value_does_not_ask_for_it(hosting):
    """wmr9x8 reads serial and nothing else, and its own code says so.

    `if connection_type == "serial"` and the else raises UnsupportedFeature. A box
    to type in would be inviting somebody to write something that cannot work.
    """
    fields = {one['name']: one for one in hosting(None, web=True).web_ways()['ways']}

    assert fields['WMR9x8']['fields']['type']['kind'] == 'fixed'
    assert [one['value'] for one in fields['WMR9x8']['fields']['type']['choices']] == [
        'serial'
    ]


def test_an_option_that_only_applies_sometimes_says_when(hosting):
    """A Vantage takes a port or a host and never both.

    It says so in its own configuration editor, in an `if`, which is code rather
    than prose and can therefore be read rather than guessed at.
    """
    fields = {one['name']: one for one in hosting(None, web=True).web_ways()['ways']}
    vantage = fields['Vantage']['fields']

    assert vantage['port']['when'] == {'field': 'type', 'values': ['serial']}
    assert vantage['host']['when'] == {'field': 'type', 'values': ['ethernet']}
    assert vantage['baudrate']['when'] is None


def test_an_option_asked_for_either_way_is_not_conditional(hosting):
    """The case that separates a real condition from a different suggestion.

    A WS1 asks for a port whether it is serial, tcp or udp. Only the default it
    offers changes, so the field always applies.
    """
    fields = {one['name']: one for one in hosting(None, web=True).web_ways()['ways']}

    assert fields['WS1']['fields']['port']['when'] is None


def test_the_settings_an_author_ruled_off_are_marked(hosting):
    """A Vantage rules off eleven of its thirteen with a row of hashes.

    That rule is the author saying which ones matter, and it is worth more than any
    guess this could make. The page folds them away.
    """
    fields = {one['name']: one for one in hosting(None, web=True).web_ways()['ways']}
    vantage = fields['Vantage']['fields']

    assert not vantage['type']['rarely']
    assert not vantage['port']['rarely']
    assert vantage['baudrate']['rarely']
    assert vantage['max_tries']['rarely']
    # Nothing to rule off in a stanza that has no such rule.
    assert not fields['Simulator']['fields']['mode']['rarely']


def test_a_driver_with_nothing_to_set_says_so(hosting):
    """The answer to a form that would otherwise be empty.

    A WMR100 is found over USB and offers a name and nothing else. Worked out from
    what the module needs in order to talk to it, not from what its comments say.
    """
    fields = {one['name']: one for one in hosting(None, web=True).web_ways()['ways']}

    assert fields['WMR100']['connects'] == 'usb'
    assert 'found over USB' in fields['WMR100']['about']
    assert fields['Vantage']['connects'] == 'either'
    assert fields['WMR9x8']['connects'] == 'cable'


def test_a_driver_that_will_not_import_is_reported_with_the_reason(tmp_path):
    """A module that is a driver by every test that can be made without running it.

    It has a `loader` and a `DRIVER_NAME`, which is all WeeWX asks of one, and it
    stops at a syntax error. Somebody who installed it should read why it is not in
    their list rather than wonder where it went. Extensions written for Python 2 are
    still on GitHub and still linked from forum posts, so this is the ordinary case
    rather than a strange one.

    Written here rather than pinned to somebody's repository: the behaviour under
    test is this driver's, and a test for it should not need the network or somebody
    else keeping a dead branch alive.
    """
    package = tmp_path / 'user'
    package.mkdir()
    (package / '__init__.py').write_text('')
    (package / 'legacy_thing.py').write_text(
        "DRIVER_NAME = 'LegacyThing'\n"
        "def loader(config_dict, engine):\n"
        "    return None\n"
        "print 'this is Python 2'\n"
    )
    user = sys.modules['user']
    user.__path__.append(str(package))
    try:
        offered = {one['module']: one for one in hardware.available()}
    finally:
        user.__path__.remove(str(package))

    one = offered.get('user.legacy_thing')
    assert one is not None, "a driver that will not import must still be reported"
    assert one['problem'], "no reason given"
    assert 'print' in one['problem'], one['problem']
    assert one['fields'] == {}, "nothing was read out of a module that did not import"


def test_something_that_is_not_a_driver_and_will_not_import_is_left_alone(tmp_path):
    """The other half of the same rule.

    A service, or anything else somebody put in that directory, is not a console. Its
    import failure is worth knowing and not here: a list of consoles with a Python
    error in it is a thing nobody can act on.
    """
    package = tmp_path / 'user'
    package.mkdir()
    (package / '__init__.py').write_text('')
    (package / 'legacy_service.py').write_text("print 'this is Python 2'\n")
    user = sys.modules['user']
    user.__path__.append(str(package))
    try:
        offered = {one['module'] for one in hardware.available()}
    finally:
        user.__path__.remove(str(package))
    assert 'user.legacy_service' not in offered


# ---- a driver on a cable, with no cable --------------------------------------


# One line from a PeetBros console, out of the WS1 driver's own documentation.
# Fifty characters: two of header and forty-eight of hex. The outdoor temperature
# is the fourth field, 0x02EB, in tenths of a degree Fahrenheit.
PEETBROS = b'!!000000BE02EB000027700000023A023A0025005800000000\r\n'


def test_a_stock_driver_on_a_cable_is_hosted_and_read():
    """The whole way through a cable driver, against a pseudo terminal.

    Every other test of a stock driver here looks at the class and stops, because
    there is no console on the end of a wire in a container. A pseudo terminal is a
    real serial device as far as pyserial is concerned, so this one is opened,
    driven and read like the Simulator is, and it is the only cable driver in the
    suite that is.
    """
    pytest.importorskip('serial', reason="pyserial is not installed")
    pytest.importorskip('weewx.drivers.ws1')
    from helpers import Wire

    wire = Wire(speaks=PEETBROS)
    config = {
        'WS1': {'driver': 'weewx.drivers.ws1', 'port': wire.name, 'mode': 'serial'},
        'StdArchive': {'archive_interval': '300'},
    }
    host = hardware.build({'station_types': 'WS1'}, config, None)
    assert host is not None
    try:
        host.start_loop()
        packet = host.get(timeout=20)
        assert packet is not None, "nothing came out of the driver"
        assert packet['source'] == 'WS1'
        # 0x02EB tenths of a degree Fahrenheit.
        assert packet['outTemp'] == pytest.approx(74.7)
        assert packet['usUnits'] == weewx.US
    finally:
        host.close()
        wire.close()


def test_a_stock_driver_that_has_to_be_switched_into_a_mode_is_read():
    """An Ultimeter is told to start talking, and then it talks.

    Two things WS1 does not do: it writes before it reads, and what it writes is a
    mode rather than a question. So the wire has to answer nothing and start
    speaking, which is a third shape of conversation and the one most consoles on a
    cable actually use.
    """
    pytest.importorskip('serial', reason="pyserial is not installed")
    pytest.importorskip('weewx.drivers.ultimeter')
    from helpers import Wire

    wire = Wire(speaks=PEETBROS)
    config = {
        'Ultimeter': {'driver': 'weewx.drivers.ultimeter', 'port': wire.name},
        'StdArchive': {'archive_interval': '300'},
    }
    host = hardware.build({'station_types': 'Ultimeter'}, config, None)
    assert host is not None
    try:
        host.start_loop()
        packet = host.get(timeout=20)
        assert packet is not None, "nothing came out of the driver"
        assert packet['source'] == 'Ultimeter'
        assert packet['outTemp'] == pytest.approx(74.7)
    finally:
        host.close()
        wire.close()
    # It asked to be put into logger mode before it read anything.
    assert any(b'>I' in one for one in wire.asked), wire.asked


def test_a_cable_driver_whose_port_is_not_there_leaves_the_others_alone():
    """A serial port that does not exist, which is the ordinary mistake.

    The station beside it has to keep running. Same promise as the driver whose
    program is missing, and worth its own test because a serial open fails
    differently from a subprocess that will not start.
    """
    pytest.importorskip('serial', reason="pyserial is not installed")
    pytest.importorskip('weewx.drivers.ws1')
    config = {
        'WS1': {
            'driver': 'weewx.drivers.ws1',
            'port': '/dev/nowhere-at-all',
            'mode': 'serial',
        },
        'Simulator': {
            'driver': 'weewx.drivers.simulator',
            'loop_interval': '1',
            'mode': 'simulator',
        },
        'StdArchive': {'archive_interval': '300'},
    }
    host = hardware.build({'station_types': 'Simulator, WS1'}, config, None)
    assert host is not None
    try:
        host.start_loop()
        packet = host.get(timeout=20)
        assert packet is not None, "the station that could be opened produced nothing"
        assert packet['source'] == 'Simulator'
    finally:
        host.close()
