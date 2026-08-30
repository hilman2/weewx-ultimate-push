#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""Hosting drivers WeeWX does not ship.

The stock drivers are written to one house style, and a host that only ever met
those has not been tested against much. The five here were each written by somebody
else, years apart: one has no configuration editor at all, one ships an editor with
every option commented out, one is reached over the network rather than over a wire,
two do not touch the hardware but run a program that does, and one needs a library
WeeWX does not. Each broke something that looked settled.

They are fetched into the image at a stated commit rather than vendored, so nothing
here ships in a release. Without that image this whole file skips, which is why the
ordinary suite does not need the network.

    docker compose -f tests/docker/compose.yml run --rm external
"""

import calendar
import json
import os
import socket
import sys
import threading
import time

import pytest

weewx = pytest.importorskip('weewx', reason="WeeWX is not installed")

WHERE = os.environ.get('EXTERNAL_DRIVERS', '')
pytestmark = pytest.mark.skipif(
    not WHERE or not os.path.isdir(os.path.join(WHERE, 'user')),
    reason="the drivers WeeWX does not ship are only in the 'external' image",
)

# A WeeWX installation keeps every extension in one `user` package, so that is where
# these have to appear for the host to find them the way it finds a real one.
# conftest.py has already made that package out of bin/user; this adds the second
# place to look, which is what an installation would have done by copying the files
# in beside ours.
if WHERE and 'user' in sys.modules:
    _extra = os.path.join(WHERE, 'user')
    if _extra not in sys.modules['user'].__path__:
        sys.modules['user'].__path__.append(_extra)

from ultimatepush import hardware  # noqa: E402  (after the path is complete)

# What each one is, and what it offers beyond loop packets. Written down rather
# than asked, so that a driver that changes what it can do says so here.
EXTERNAL = {
    'user.MQTTSubscribe': {
        'name': 'MQTTSubscribeDriver',
        'connects': hardware.BY_NETWORK,
        'offers': ('genArchiveRecords', 'archive_interval'),
    },
    # The Ecowitt gateway API, on port 45000, which is the pull side of the hardware
    # this driver already reads over HTTP. Its editor names two options and no
    # address, on purpose: it finds the gateway by broadcasting for it.
    'user.gw1000': {
        'name': 'GW1000',
        'connects': hardware.BY_NOTHING,
        'offers': (),
    },
    'user.rtldavis': {
        'name': 'Rtldavis',
        'connects': hardware.BY_COMMAND,
        'offers': (),
    },
    'user.sdr': {
        'name': 'SDR',
        'connects': hardware.BY_COMMAND,
        'offers': (),
    },
    'user.weatherflowudp': {
        'name': 'WeatherFlowUDP',
        'connects': hardware.BY_BROADCAST,
        'offers': (),
    },
}

ASKED_FOR = (
    'genArchiveRecords',
    'genStartupRecords',
    'archive_interval',
    'getTime',
    'setTime',
)

# One real datagram from a Tempest, as the hub puts it on the wire. The positions
# after the timestamp are the observation, and the seventh of them is the air
# temperature.
TEMPEST = {
    "serial_number": "ST-00000512",
    "type": "obs_st",
    "hub_sn": "HB-000abcde",
    "obs": [
        [
            1588948614,
            0.18,
            0.22,
            0.27,
            144,
            6,
            1017.57,
            22.37,
            50.26,
            328,
            0.03,
            3,
            0.000000,
            0,
            0,
            0,
            2.410,
            1,
        ]
    ],
    "firmware_revision": 129,
}


def offered_by(module):
    """What a driver class offers the host beyond loop packets.

    Args:
        module (types.ModuleType): The driver module.

    Returns:
        tuple: The names from ASKED_FOR that its driver class implements.
    """
    import weewx.drivers

    for value in vars(module).values():
        if (
            isinstance(value, type)
            and issubclass(value, weewx.drivers.AbstractDevice)
            and value is not weewx.drivers.AbstractDevice
            and hasattr(value, 'genLoopPackets')
        ):
            return tuple(part for part in ASKED_FOR if hardware.implements(value, part))
    raise AssertionError("no driver class in %s" % module.__name__)


def found():
    """Every driver the host offers, by module name.

    Returns:
        dict: Module name to what available() said about it.
    """
    return {one['module']: one for one in hardware.available()}


@pytest.mark.parametrize('module_name', sorted(EXTERNAL))
def test_a_driver_from_elsewhere_is_offered_like_any_other(module_name):
    """It is in the list, named, and with nothing wrong with it."""
    import importlib

    one = found().get(module_name)
    assert one is not None, "%s is not offered at all" % module_name
    assert one['problem'] is None, one['problem']
    assert one['name'] == EXTERNAL[module_name]['name']
    assert offered_by(importlib.import_module(module_name)) == (
        EXTERNAL[module_name]['offers']
    )


@pytest.mark.parametrize('module_name', sorted(EXTERNAL))
def test_how_a_driver_from_elsewhere_is_reached(module_name):
    """The three of them are reached three ways, and none is a serial cable.

    This decides what its page tells somebody to go and find, so getting it wrong
    sends a person with an MQTT broker to look in /dev/serial/by-id/.
    """
    assert found()[module_name]['connects'] == EXTERNAL[module_name]['connects']


def test_an_editor_that_names_nothing_falls_through_to_the_constructor():
    """weewx-sdr ships a stanza with every option commented out.

    That is a reasonable thing to write into somebody's configuration file and it
    leaves a form with one row on it. The constructor still holds the list, and one
    of the options is the command line that makes the driver work at all.
    """
    import importlib

    module = importlib.import_module('user.sdr')
    assert hasattr(module, 'confeditor_loader'), "this test is about having one"
    fields = hardware.template_for(module)['fields']
    assert 'cmd' in fields
    # The real default, which is written beside the class rather than in the call.
    assert fields['cmd']['value'].startswith('rtl_433')
    assert 'ld_library_path' in fields
    # A default that is a block stays out: it cannot be a box on a form.
    assert 'deltas' not in fields
    assert 'sensor_map' not in fields


def test_a_driver_with_no_editor_still_describes_itself():
    """The one that ships no template for a configuration file.

    WeeWX drivers carry a `confeditor_loader`, and a form is built from it. This one
    does not, so there is nothing to build from but the constructor, which names
    every option it reads and the default it falls back on.
    """
    import importlib

    module = importlib.import_module('user.weatherflowudp')
    assert not hasattr(
        module, 'confeditor_loader'
    ), "this driver has gained an editor, so it no longer tests the fallback"
    fields = hardware.template_for(module)['fields']
    assert set(fields) == {
        'driver',
        'udp_address',
        'udp_port',
        'udp_timeout',
        'share_socket',
        'log_raw_packets',
    }
    assert fields['udp_port']['value'] == '50222'
    assert fields['udp_address']['value'] == '<broadcast>'
    # Nothing says what they mean: that was in a README, not beside the option.
    assert not any(one['help'] for one in fields.values())


def test_a_sensor_map_is_not_offered_as_a_setting():
    """Its one subsection stays out of the form, and the page has to say so.

    `sensor_map` is a block rather than a value, and this driver records nothing at
    all without one. A form that showed it as a box would invite a line that cannot
    work, so it is left out and the page carries the block instead.
    """
    import importlib

    fields = hardware.template_for(importlib.import_module('user.weatherflowudp'))
    assert 'sensor_map' not in fields['fields']


def test_an_extension_that_is_not_hardware_is_not_offered():
    """weewx-purple is a service, and it needs a library the image does not have.

    Before, the import failure was reported before anything asked whether the module
    was a driver, so somebody who had installed it saw 'purple' among their consoles
    with a Python error where the settings should be.
    """
    assert 'user.purple' not in found()
    assert os.path.exists(
        os.path.join(WHERE, 'user', 'purple.py')
    ), "the file is not there, so this test would pass for the wrong reason"


# ---- one of them, end to end ------------------------------------------------


def a_free_port():
    """A UDP port nothing is on, for a driver that has to be sent to.

    Returns:
        int: The port. Freed before it is returned, so this is a guess that is
        almost always right rather than a reservation.
    """
    held = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        held.bind(('127.0.0.1', 0))
        return held.getsockname()[1]
    finally:
        held.close()


def keep_sending(port, message, stop):
    """Send a datagram over and over until told to stop.

    The driver binds its socket inside genLoopPackets, on its own thread, so there
    is no moment a test can wait for. Sending until something arrives is the honest
    way to say "once it is listening".

    Args:
        port (int): Where to send.
        message (bytes): What to send.
        stop (threading.Event): Set when the test has what it wanted.
    """
    out = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        while not stop.is_set():
            out.sendto(message, ('127.0.0.1', port))
            stop.wait(0.2)
    finally:
        out.close()


def test_a_hub_on_the_network_is_read_through_the_host():
    """The whole way through, with a real datagram and somebody else's driver.

    Nothing is faked: the real module, the real loader, a real UDP socket, and a
    packet out of the far end of the host.
    """
    port = a_free_port()
    config = {
        'WeatherFlowUDP': {
            'driver': 'user.weatherflowudp',
            'udp_address': '127.0.0.1',
            'udp_port': str(port),
            'udp_timeout': '2',
            # Named the way this driver names a reading: the field, the serial
            # number with its dashes turned into underscores, and the message
            # type. Nothing records at all without this block.
            'sensor_map': {
                'outTemp': 'air_temperature.ST_00000512.obs_st',
                'windSpeed': 'wind_avg.ST_00000512.obs_st',
            },
        },
        'StdArchive': {'archive_interval': '300'},
    }
    host = hardware.build({'station_types': 'WeatherFlowUDP'}, config, None)
    assert host is not None
    stop = threading.Event()
    sender = threading.Thread(
        target=keep_sending,
        args=(port, json.dumps(TEMPEST).encode('utf-8'), stop),
        daemon=True,
    )
    try:
        host.start_loop()
        sender.start()
        packet = host.get(timeout=20)
        assert packet is not None, "nothing came out of the hosted driver"
        assert packet['source'] == 'WeatherFlowUDP'
        assert packet['outTemp'] == pytest.approx(22.37)
        assert packet['windSpeed'] == pytest.approx(0.22)
        assert packet['usUnits'] == weewx.METRICWX
    finally:
        stop.set()
        host.close()
        sender.join(5)


def test_the_same_datagram_read_two_ways_says_the_same_thing():
    """Our reading of a Tempest against one written by somebody who never saw it.

    Both walk the same array of numbers and both have to know what each position
    means. They were written years apart from the same published description, so
    where they disagree, one of them is wrong. The names differ and the values must
    not.
    """
    from ultimatepush import transport
    from ultimatepush.protocols.weatherflow import WeatherFlow
    import importlib

    theirs_module = importlib.import_module('user.weatherflowudp')
    ours = WeatherFlow.readings(None, dict(TEMPEST))
    theirs = theirs_module.parseUDPPacket(dict(TEMPEST))

    # What each calls the same position. Everything the other names too.
    same = {
        'wind_lull': 'wind_lull',
        'wind_avg': 'wind_avg',
        'wind_gust': 'wind_gust',
        'wind_direction': 'wind_direction',
        'station_pressure': 'station_pressure',
        'air_temperature': 'air_temperature',
        'relative_humidity': 'relative_humidity',
        'illuminance': 'illuminance',
        'uv': 'uv',
        'solar_radiation': 'solar_radiation',
        'rain_amount': 'rain_accumulated',
        'lightning_avg_distance': 'lightning_strike_avg_distance',
        'lightning_count': 'lightning_strike_count',
        'st_battery': 'battery',
    }
    serial = TEMPEST['serial_number'].replace('-', '_')
    for mine, yours in same.items():
        assert mine in ours, "we do not read %s at all" % mine
        theirs_key = '%s.%s.obs_st' % (yours, serial)
        assert theirs_key in theirs, "they do not read %s at all" % yours
        assert ours[mine] == pytest.approx(
            theirs[theirs_key]
        ), "%s and %s are not the same position" % (mine, yours)
    stamped = calendar.timegm(
        time.strptime(ours['dateutc'], transport.DEVICE_TIME_FORMAT)
    )
    assert stamped == theirs['time_epoch']


# ---- the one that needs something to talk to --------------------------------


BROKER = os.environ.get('MQTT_BROKER', '')


@pytest.mark.skipif(not BROKER, reason="no broker: run the 'external' service")
def test_a_broker_is_a_station_like_any_other():
    """Readings that reach this machine over MQTT, through a hosted driver.

    This is the shape Vince Skahan described: a console on one WeeWX, republished
    over MQTT, read by another. Worth having, and worth knowing that an Ecowitt
    console can push straight into this driver instead, with neither the broker nor
    the second WeeWX in the way.
    """
    mqtt = pytest.importorskip('paho.mqtt.client')
    import configobj

    topic = 'weather/loop'
    # A ConfigObj rather than a dict, because that is what WeeWX hands a driver and
    # this one reads `.sections` off what it is given.
    config = configobj.ConfigObj(
        {
            'MQTTSubscribeDriver': {
                'driver': 'user.MQTTSubscribe',
                'host': BROKER,
                'port': '1883',
                'topics': {topic: {'message': {'type': 'json'}}},
            },
            'StdArchive': {'archive_interval': '300'},
        }
    )
    host = hardware.build({'station_types': 'MQTTSubscribeDriver'}, config, None)
    assert host is not None

    stop = threading.Event()

    def keep_publishing():
        """Publish until the test has a packet, for the same reason as the UDP one."""
        try:
            out = mqtt.Client()
        except TypeError:
            # paho 2 wants to be told which callback API is meant.
            out = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1)
        out.connect(BROKER, 1883, 10)
        out.loop_start()
        try:
            while not stop.is_set():
                out.publish(
                    topic,
                    json.dumps({'outTemp': 21.5, 'outHumidity': 63.0, 'usUnits': 17}),
                )
                stop.wait(0.5)
        finally:
            out.loop_stop()
            out.disconnect()

    publisher = threading.Thread(target=keep_publishing, daemon=True)
    try:
        host.start_loop()
        publisher.start()
        packet = host.get(timeout=30)
        assert packet is not None, "nothing came out of the broker"
        assert packet['source'] == 'MQTTSubscribeDriver'
        assert packet['outTemp'] == pytest.approx(21.5)
    finally:
        stop.set()
        host.close()
        publisher.join(5)


# ---- the one that cannot run here -------------------------------------------


def test_a_driver_whose_program_is_missing_is_left_out_rather_than_fatal():
    """rtldavis runs a radio receiver this machine does not have.

    It is still worth hosting: what is being checked is the promise that one station
    that cannot be opened does not take the others with it. The program named below
    does not exist, which is exactly what somebody sees who has installed the driver
    and not yet built it.
    """
    config = {
        'Rtldavis': {
            'driver': 'user.rtldavis',
            'cmd': '/nowhere/rtldavis',
            'transceiver_frequency': 'EU',
        },
        'Simulator': {
            'driver': 'weewx.drivers.simulator',
            'loop_interval': '1',
            'mode': 'simulator',
        },
        'StdArchive': {'archive_interval': '300'},
    }
    host = hardware.build({'station_types': 'Simulator, Rtldavis'}, config, None)
    assert host is not None
    try:
        host.start_loop()
        # The one that can run still runs. That is the whole promise.
        seen = []
        until = time.time() + 20
        while time.time() < until and not seen:
            packet = host.get(timeout=5)
            if packet is not None:
                seen.append(packet)
        assert seen, "the station that could be opened produced nothing"
        assert seen[0]['source'] == 'Simulator'
    finally:
        host.close()
