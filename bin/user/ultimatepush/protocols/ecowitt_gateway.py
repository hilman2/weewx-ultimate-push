#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""An Ecowitt gateway read over its own API, rather than waited for over HTTP.

The same hardware this driver already reads two other ways. A GW1000 and its
relatives will upload to a custom server, which is `protocols/ecowitt.py`, and they
will also sit on the network and answer a binary API on TCP port 45000, which is
this. The two are independent: a gateway answers here whether or not its *Customized*
upload is switched on, so somebody can run both and lose nothing.

What that buys is a station that needs nothing set on the console at all. An address
is the whole of it.

**Nothing about the two is shared but the hardware.** The API's field names are its
own; not one of them appears among the 532 in the HTTP catalog. `intemp` against
`tempinf`, `absbaro` against `baromabsin`, `rainday` against `dailyrainin`. So this
has a catalog of its own and the HTTP one is left alone.

The wire format
---------------

Every exchange is one request frame and one response frame:

    ff ff | command | size | payload | checksum

`size` counts from the command byte to the checksum inclusive, so a frame is
`2 + size` bytes long. The checksum is the low byte of the sum over everything the
size counts except itself. Four responses carry that size in two bytes rather than
one, and which four is not something to guess; see TWO_BYTE_SIZE.

Live data is addressed rather than positional: a stream of one address byte followed
by that reading's bytes, where the address says both what the reading is and how many
bytes it occupies. That is the whole reason a table is needed, and the whole reason a
wrong entry in it is silent: every reading after a wrong width is read from the wrong
place and still looks like a number.

Everything here is read out of Ecowitt's *TCP API Interface Communication Protocol*,
V1.7.0 of 2024-05-27. Where the document settles something it is followed and cited;
where it is silent or contradicts itself, the comment says so and says what was done
instead. bidord's weewx-gw1000 was read as a second opinion on the two points the
document does not state, and nothing was taken from it.
"""

import json
import logging
import socket
import struct
from typing import Dict, Set, Tuple, TYPE_CHECKING

from . import METRICWX, Protocol
from .. import catalogs

# For the docstring types only. Importing the poller here at run time would be a
# circle: it is what reaches this module, by way of the registry.
if TYPE_CHECKING:
    from .. import polling

log = logging.getLogger(__name__)

_catalog = catalogs.ecowitt_gateway

# Where a gateway answers. Ecowitt fixes it: the WiFi module runs its TCP server here
# and there is no setting for it.
DEFAULT_PORT = 45000

# Where a gateway answers a broadcast that is looking for it. Not used by the driver,
# which is given an address, and named because discovery is the one thing somebody
# reading this will wonder where to find. See the note under CMD_BROADCAST.
DISCOVERY_PORT = 46000

# The two bytes every frame starts with, in both directions.
HEADER = b'\xff\xff'

# The commands this driver sends. Ecowitt's own names, so that a line here and a line
# of the document can be put beside each other.
#
# The document spells the MAC one CMD_READ_SATION_MAC, which is a typo in the
# document rather than anything to reproduce.
CMD_BROADCAST = 0x12
CMD_READ_STATION_MAC = 0x26
CMD_GW1000_LIVEDATA = 0x27
CMD_READ_SSSS = 0x30
CMD_READ_SENSOR_ID_NEW = 0x3C
CMD_READ_FIRMWARE_VERSION = 0x50
CMD_READ_RAIN = 0x57

# The responses whose size field is two bytes rather than one.
#
# This is the one piece of framing that cannot be worked out from a frame in hand: a
# reader that has the width wrong takes the top half of a length for a payload byte
# and everything after it is nonsense. The document says which, in two places and in
# the same words, "Note: Return data size is 2 Bytes": beside CMD_BROADCAST and
# CMD_GW1000_LIVEDATA in the command list, and in the response table of each of the
# four below. That is how this list is known and it is not inferred from anything.
TWO_BYTE_SIZE = frozenset(
    [CMD_BROADCAST, CMD_GW1000_LIVEDATA, CMD_READ_SENSOR_ID_NEW, CMD_READ_RAIN]
)

# The longest response worth reading. A live-data stream from a gateway carrying
# every sensor it supports is a few hundred bytes; the size field can claim 65535,
# and a driver that believed one would sit reading from something that is not a
# gateway until its timeout.
MOST_BYTES = 8192


# ---- framing ----------------------------------------------------------------


def size_width(command, answering):
    """How many bytes this frame's size field takes.

    Args:
        command (int): The command byte.
        answering (bool): Whether this is a response rather than a request.

    Returns:
        int: One or two.
    """
    return 2 if answering and command in TWO_BYTE_SIZE else 1


def frame(command, payload=b'', answering=False):
    """One frame, ready to send.

    Args:
        command (int): The command byte.
        payload (bytes): What goes between the size and the checksum. Every command
            this driver sends has none.
        answering (bool): Whether this is a response rather than a request. It is
            what decides the width of the size field, and the two directions are not
            the same: a request's size is one byte for every command there is, and
            four responses carry theirs in two. See TWO_BYTE_SIZE.

    Returns:
        bytes: The whole frame, header and checksum included.
    """
    wide = size_width(command, answering)
    # Size counts the command byte, the size field itself, the payload and the
    # checksum.
    counted = (
        struct.pack('>B', command)
        + struct.pack('>H' if wide == 2 else '>B', 1 + wide + len(payload) + 1)
        + payload
    )
    return HEADER + counted + struct.pack('>B', sum(counted) & 0xFF)


def payload_of(command, response, answering=True):
    """What a frame carries, once it has been shown to be an answer to this command.

    Three things are checked, and each of them is a way a reader can be fooled into
    decoding something that is not a reading. The header says this is a frame at all.
    The command byte echoing says it answers what was asked, which is what catches a
    reply arriving out of step after a retry. The checksum says the bytes are the
    ones that were sent.

    Args:
        command (int): The command that was sent.
        response (bytes): Everything read back.
        answering (bool): Whether this is a response rather than a request, which
            is what decides the width of the size field. See frame.

    Returns:
        bytes: The payload, between the size field and the checksum.

    Raises:
        ValueError: If it is not a whole, well-formed answer to that command.
    """
    if not response.startswith(HEADER):
        raise ValueError("no 0xffff header, so this is not a gateway answering")
    wide = size_width(command, answering)
    if len(response) < 3 + wide + 1:
        raise ValueError("only %d bytes, which is shorter than a frame" % len(response))
    if response[2] != command:
        raise ValueError(
            "answered command 0x%02x, and 0x%02x was asked" % (response[2], command)
        )
    size = struct.unpack('>H' if wide == 2 else '>B', response[3 : 3 + wide])[0]
    # A frame is the two header bytes plus everything the size counts.
    if len(response) != 2 + size:
        raise ValueError(
            "says it is %d bytes and %d arrived" % (2 + size, len(response))
        )
    if sum(response[2:-1]) & 0xFF != response[-1]:
        raise ValueError("checksum is wrong, so the bytes are not the ones sent")
    return response[3 + wide : -1]


# ---- the live data table ----------------------------------------------------
#
# One entry per address, and each entry is what that address carries in order:
#
#     (name, struct code, what to divide the raw integer by)
#
# The width comes out of the struct code rather than being written beside it, so the
# table cannot disagree with itself about how long a reading is. That is the mistake
# worth designing out: it is silent, and it moves every reading after it.
#
# A name of None goes with the pad code 'x', for the addresses whose bytes have to be
# stepped over so that the rest of the stream still lines up.
#
# Units are the document's, per address, and they are the same on every device: the
# API answers in Celsius, hPa, millimetres, metres per second and lux whatever the
# console's display is set to. See the note on units in EcowittGateway.

# Signed where a reading can go below zero and unsigned where it cannot, which the
# document states per calibration range: temperature offsets run -100..100 and
# pressure offsets -800..800, both of them x10.
LIVE = {
    0x01: (('intemp', 'h', 10.0),),
    0x02: (('outtemp', 'h', 10.0),),
    0x03: (('dewpoint', 'h', 10.0),),
    0x04: (('windchill', 'h', 10.0),),
    0x05: (('heatindex', 'h', 10.0),),
    0x06: (('inhumi', 'B', 1.0),),
    0x07: (('outhumi', 'B', 1.0),),
    0x08: (('absbaro', 'H', 10.0),),
    0x09: (('relbaro', 'H', 10.0),),
    0x0A: (('winddirection', 'H', 1.0),),
    0x0B: (('windspeed', 'H', 10.0),),
    0x0C: (('gustspeed', 'H', 10.0),),
    0x0D: (('rainevent', 'H', 10.0),),
    0x0E: (('rainrate', 'H', 10.0),),
    # The one reading in the stream that is scaled by a hundred rather than ten. The
    # document says so where it describes the rain command: "the received rain gain
    # is the value magnified by 100 times, and the rain is the value magnified by 10
    # times".
    0x0F: (('rain_gain', 'H', 100.0),),
    0x10: (('rainday', 'H', 10.0),),
    0x11: (('rainweek', 'H', 10.0),),
    0x12: (('rainmonth', 'I', 10.0),),
    0x13: (('rainyear', 'I', 10.0),),
    0x14: (('raintotals', 'I', 10.0),),
    0x15: (('light', 'I', 10.0),),
    0x16: (('uv', 'H', 10.0),),
    0x17: (('uvi', 'B', 1.0),),
    # Six bytes of the gateway's own clock. Stepped over rather than read: the driver
    # stamps the reading with its own clock, which is within one interval of the
    # measurement because it has just asked, and a console whose time is wrong would
    # otherwise put the whole day's readings somewhere else.
    0x18: ((None, '6x', None),),
    0x19: (('daylwindmax', 'H', 10.0),),
    0x1A: (('temp1', 'h', 10.0),),
    0x1B: (('temp2', 'h', 10.0),),
    0x1C: (('temp3', 'h', 10.0),),
    0x1D: (('temp4', 'h', 10.0),),
    0x1E: (('temp5', 'h', 10.0),),
    0x1F: (('temp6', 'h', 10.0),),
    0x20: (('temp7', 'h', 10.0),),
    0x21: (('temp8', 'h', 10.0),),
    0x22: (('humi1', 'B', 1.0),),
    0x23: (('humi2', 'B', 1.0),),
    0x24: (('humi3', 'B', 1.0),),
    0x25: (('humi4', 'B', 1.0),),
    0x26: (('humi5', 'B', 1.0),),
    0x27: (('humi6', 'B', 1.0),),
    0x28: (('humi7', 'B', 1.0),),
    0x29: (('humi8', 'B', 1.0),),
    0x2A: (('pm25_ch1', 'H', 10.0),),
    0x2B: (('soiltemp1', 'h', 10.0),),
    0x2C: (('soilmoisture1', 'B', 1.0),),
    0x2D: (('soiltemp2', 'h', 10.0),),
    0x2E: (('soilmoisture2', 'B', 1.0),),
    0x2F: (('soiltemp3', 'h', 10.0),),
    0x30: (('soilmoisture3', 'B', 1.0),),
    0x31: (('soiltemp4', 'h', 10.0),),
    0x32: (('soilmoisture4', 'B', 1.0),),
    0x33: (('soiltemp5', 'h', 10.0),),
    0x34: (('soilmoisture5', 'B', 1.0),),
    0x35: (('soiltemp6', 'h', 10.0),),
    0x36: (('soilmoisture6', 'B', 1.0),),
    0x37: (('soiltemp7', 'h', 10.0),),
    0x38: (('soilmoisture7', 'B', 1.0),),
    0x39: (('soiltemp8', 'h', 10.0),),
    0x3A: (('soilmoisture8', 'B', 1.0),),
    0x3B: (('soiltemp9', 'h', 10.0),),
    0x3C: (('soilmoisture9', 'B', 1.0),),
    0x3D: (('soiltemp10', 'h', 10.0),),
    0x3E: (('soilmoisture10', 'B', 1.0),),
    0x3F: (('soiltemp11', 'h', 10.0),),
    0x40: (('soilmoisture11', 'B', 1.0),),
    0x41: (('soiltemp12', 'h', 10.0),),
    0x42: (('soilmoisture12', 'B', 1.0),),
    0x43: (('soiltemp13', 'h', 10.0),),
    0x44: (('soilmoisture13', 'B', 1.0),),
    0x45: (('soiltemp14', 'h', 10.0),),
    0x46: (('soilmoisture14', 'B', 1.0),),
    0x47: (('soiltemp15', 'h', 10.0),),
    0x48: (('soilmoisture15', 'B', 1.0),),
    0x49: (('soiltemp16', 'h', 10.0),),
    0x4A: (('soilmoisture16', 'B', 1.0),),
    # Sixteen bytes of packed battery flags, one bit or one nibble per sensor family.
    # Stepped over rather than unpacked: the document marks the structure removed as
    # of GW1000 firmware V1.6.5 and says the battery of each sensor is read singly
    # through CMD_READ_SENSOR_ID_NEW instead, which is where this gets it from. On
    # older firmware that leaves the flags unread rather than read wrongly.
    0x4C: ((None, '16x', None),),
    0x4D: (('pm25_24havg1', 'H', 10.0),),
    0x4E: (('pm25_24havg2', 'H', 10.0),),
    0x4F: (('pm25_24havg3', 'H', 10.0),),
    0x50: (('pm25_24havg4', 'H', 10.0),),
    0x51: (('pm25_ch2', 'H', 10.0),),
    0x52: (('pm25_ch3', 'H', 10.0),),
    0x53: (('pm25_ch4', 'H', 10.0),),
    0x58: (('leak_ch1', 'B', 1.0),),
    0x59: (('leak_ch2', 'B', 1.0),),
    0x5A: (('leak_ch3', 'B', 1.0),),
    0x5B: (('leak_ch4', 'B', 1.0),),
    0x60: (('lightning', 'B', 1.0),),
    0x61: (('lightning_time', 'I', 1.0),),
    0x62: (('lightning_power', 'I', 1.0),),
    # A WN34 sends its own battery voltage beside its temperature, in the same three
    # bytes. 0.02 V per count, which the document states here and again in the sensor
    # list.
    0x63: (('tf_usr1', 'h', 10.0), ('tf_usr1_batt', 'B', 50.0)),
    0x64: (('tf_usr2', 'h', 10.0), ('tf_usr2_batt', 'B', 50.0)),
    0x65: (('tf_usr3', 'h', 10.0), ('tf_usr3_batt', 'B', 50.0)),
    0x66: (('tf_usr4', 'h', 10.0), ('tf_usr4_batt', 'B', 50.0)),
    0x67: (('tf_usr5', 'h', 10.0), ('tf_usr5_batt', 'B', 50.0)),
    0x68: (('tf_usr6', 'h', 10.0), ('tf_usr6_batt', 'B', 50.0)),
    0x69: (('tf_usr7', 'h', 10.0), ('tf_usr7_batt', 'B', 50.0)),
    0x6A: (('tf_usr8', 'h', 10.0), ('tf_usr8_batt', 'B', 50.0)),
    # A WH46 is a WH45 with four more particle readings on the end. The order is the
    # document's and the document says it is not to be changed.
    0x6B: (
        ('tf_co2', 'h', 10.0),
        ('humi_co2', 'B', 1.0),
        ('pm10_co2', 'H', 10.0),
        ('pm10_24h_co2', 'H', 10.0),
        ('pm25_co2', 'H', 10.0),
        ('pm25_24h_co2', 'H', 10.0),
        ('co2', 'H', 1.0),
        ('co2_24h', 'H', 1.0),
        ('co2_batt', 'B', 1.0),
        ('pm1_co2', 'H', 10.0),
        ('pm1_24h_co2', 'H', 10.0),
        ('pm4_co2', 'H', 10.0),
        ('pm4_24h_co2', 'H', 10.0),
    ),
    0x6C: (('heap_free', 'I', 1.0),),
    0x70: (
        ('tf_co2', 'h', 10.0),
        ('humi_co2', 'B', 1.0),
        ('pm10_co2', 'H', 10.0),
        ('pm10_24h_co2', 'H', 10.0),
        ('pm25_co2', 'H', 10.0),
        ('pm25_24h_co2', 'H', 10.0),
        ('co2', 'H', 1.0),
        ('co2_24h', 'H', 1.0),
        ('co2_batt', 'B', 1.0),
    ),
    0x72: (('leaf_wetness_ch1', 'B', 1.0),),
    0x73: (('leaf_wetness_ch2', 'B', 1.0),),
    0x74: (('leaf_wetness_ch3', 'B', 1.0),),
    0x75: (('leaf_wetness_ch4', 'B', 1.0),),
    0x76: (('leaf_wetness_ch5', 'B', 1.0),),
    0x77: (('leaf_wetness_ch6', 'B', 1.0),),
    0x78: (('leaf_wetness_ch7', 'B', 1.0),),
    0x79: (('leaf_wetness_ch8', 'B', 1.0),),
    0x7A: (('rain_priority', 'B', 1.0),),
    0x7B: (('radcompensation', 'B', 1.0),),
    0x80: (('piezo_rainrate', 'H', 10.0),),
    0x81: (('piezo_rainevent', 'H', 10.0),),
    # Two bytes the document marks reserved and not used. Stepped over under its own
    # name, because a reserved address that starts being sent must not shift the
    # readings that follow it.
    0x82: (('piezo_rainhour', 'H', 10.0),),
    0x83: (('piezo_rainday', 'I', 10.0),),
    0x84: (('piezo_rainweek', 'I', 10.0),),
    0x85: (('piezo_rainmonth', 'I', 10.0),),
    0x86: (('piezo_rainyear', 'I', 10.0),),
    # Ten gains, of which the document says the first five are used and the rest are
    # reserved. All ten are read: the reserved five are five more ways for the stream
    # to shift if they are guessed at.
    0x87: tuple(('piezo_gain%d' % n, 'H', 100.0) for n in range(10)),
    0x88: (
        ('rst_rainday_time', 'B', 1.0),
        ('rst_rainweek_time', 'B', 1.0),
        ('rst_rainyear_time', 'B', 1.0),
    ),
}

# The one address whose length is in the stream rather than in the table: a byte
# saying how many bytes of air quality index follow, then that many. Handled apart
# from the table for that reason. The document marks it for Ambient consoles only,
# and it is read anyway, because an address that is skipped is an address that puts
# every reading after it in the wrong place.
ITEM_PM25_AQI = 0x71

# What those pairs are, in the order the document lists them. Anything past the end
# of this list is a reading Ecowitt has added since, and is stepped over rather than
# named.
AQI = (
    'aqi_pm25',
    'aqi_pm25_24h',
    'aqi_pm25_in',
    'aqi_pm25_in_24h',
    'aqi_pm25_aqin',
    'aqi_pm25_24h_aqin',
)

# What CMD_READ_RAIN answers with, which is the same addresses at different widths.
#
# This is the trap in the whole protocol. ITEM_RAINDAY is two bytes in a live-data
# stream and four here; so are RAINWEEK, RAINEVENT's neighbours and the piezo totals.
# The document's two response tables say so plainly and disagree with each other on
# purpose, and a reader that used one table for both would read every gauge on a
# newer console at half its width. So there are two tables.
RAIN = {
    0x0E: (('rainrate', 'H', 10.0),),
    0x0F: (('rain_gain', 'H', 100.0),),
    0x10: (('rainday', 'I', 10.0),),
    0x11: (('rainweek', 'I', 10.0),),
    0x12: (('rainmonth', 'I', 10.0),),
    0x13: (('rainyear', 'I', 10.0),),
    0x0D: (('rainevent', 'H', 10.0),),
    0x80: (('piezo_rainrate', 'H', 10.0),),
    0x81: (('piezo_rainevent', 'H', 10.0),),
    0x83: (('piezo_rainday', 'I', 10.0),),
    0x84: (('piezo_rainweek', 'I', 10.0),),
    0x85: (('piezo_rainmonth', 'I', 10.0),),
    0x86: (('piezo_rainyear', 'I', 10.0),),
    0x7A: (('rain_priority', 'B', 1.0),),
    0x87: tuple(('piezo_gain%d' % n, 'H', 100.0) for n in range(10)),
    0x88: (
        ('rst_rainday_time', 'B', 1.0),
        ('rst_rainweek_time', 'B', 1.0),
        ('rst_rainyear_time', 'B', 1.0),
    ),
}


def shape_format(shapes):
    """The struct format one address's bytes are packed in.

    Args:
        shapes (tuple[tuple]): The (name, struct code, divisor) entries for it.

    Returns:
        str: A big-endian format string.
    """
    return '>' + ''.join(code for _, code, _ in shapes)


def read_stream(data, table):
    """Every reading in an addressed stream, up to the first address not in the table.

    An address says how many bytes its reading takes, so an address nobody knows is
    the end of what can be read: there is no length to step over and everything after
    it would be read from the wrong place. What was read before it is good and is
    kept.

    Args:
        data (bytes): The payload, one address byte and its value at a time.
        table (dict): LIVE or RAIN, whichever this payload is.

    Returns:
        tuple: (the readings as a dict of name to float, the address that stopped it
        or None if it ran to the end).
    """
    out = {}  # type: Dict[str, float]
    at = 0
    while at < len(data):
        address = data[at]
        at += 1
        if address == ITEM_PM25_AQI:
            if at >= len(data):
                return out, address
            wide = data[at]
            at += 1
            if at + wide > len(data):
                return out, address
            for index in range(wide // 2):
                if index < len(AQI):
                    spot = at + index * 2
                    out[AQI[index]] = float(
                        struct.unpack('>H', data[spot : spot + 2])[0]
                    )
            at += wide
            continue
        shapes = table.get(address)
        if shapes is None:
            return out, address
        fmt = shape_format(shapes)
        wide = struct.calcsize(fmt)
        if at + wide > len(data):
            # The stream ran out inside a reading, which means the frame was short or
            # this address is not what the table thinks. Either way there is nothing
            # further to read.
            return out, address
        values = struct.unpack(fmt, data[at : at + wide])
        for (name, _, divide), value in zip(
            [one for one in shapes if one[0] is not None], values
        ):
            out[name] = value / divide if divide != 1.0 else float(value)
        at += wide
    return out, None


def write_stream(readings, table, addresses=None):
    """The bytes a gateway would send for these readings.

    The other half of read_stream, and the reason the fake gateway can be built from
    the same table it is read with rather than from a captured frame.

    Args:
        readings (dict): Name to value, in the units the table decodes to.
        table (dict): LIVE or RAIN.
        addresses (list[int] | None): Which addresses to write, for a caller that
            wants a particular device rather than every one at once. Every address
            whose names are all in hand when nothing is said. Naming them matters
            because a WH45 and a WH46 send the same readings under two addresses,
            and no gateway sends both.

    Returns:
        bytes: An addressed stream.
    """
    out = []
    for address in sorted(table) if addresses is None else sorted(set(addresses)):
        if address == ITEM_PM25_AQI:
            indexes = [readings[name] for name in AQI if name in readings]
            if len(indexes) != len(AQI):
                continue
            out.append(struct.pack('>BB', address, 2 * len(indexes)))
            out.append(
                struct.pack(
                    '>%dH' % len(indexes), *[int(round(one)) for one in indexes]
                )
            )
            continue
        shapes = table.get(address)
        if shapes is None:
            continue
        named = [one for one in shapes if one[0] is not None]
        if named and not all(name in readings for name, _, _ in named):
            continue
        values = []
        for name, _, divide in named:
            values.append(int(round(readings[name] * divide)))
        out.append(struct.pack('>B', address))
        out.append(struct.pack(shape_format(shapes), *values))
    return b''.join(out)


# ---- the sensors a gateway has registered -----------------------------------
#
# CMD_READ_SENSOR_ID_NEW answers with one seven byte record per sensor the gateway
# knows: a type byte, a four byte id, a battery byte and a signal byte.

# What each type byte is, in the order of the document's SENSOR_IDT enum.
#
# The document contradicts itself here. Its enum declares eWH65_SENSOR = 0x00 and
# counts up from there, and the response table beside CMD_READ_SENSOR_ID_NEW labels
# the first record WH65_SENSOR with the description 0x01. The enum is stated twice,
# in the definitions and again in the sensor list, and it is the normative C
# declaration; the table's numbers are one out for every sensor in it. The enum is
# followed. bidord's weewx-gw1000 reads it the same way, which is the second opinion
# that settled it.
SENSORS = (
    ['wh65', 'wh68', 'wh80', 'wh40', 'wh25', 'wh26']
    + ['wh31_ch%d' % n for n in range(1, 9)]
    + ['wh51_ch%d' % n for n in range(1, 9)]
    + ['wh41_ch%d' % n for n in range(1, 5)]
    + ['wh57']
    + ['wh55_ch%d' % n for n in range(1, 5)]
    + ['wh34_ch%d' % n for n in range(1, 9)]
    + ['wh45']
    + ['wh35_ch%d' % n for n in range(1, 9)]
    + ['wh90']
)

# What a battery byte means, which is not the same thing for every sensor. The
# document gives the rule per sensor beside the enum, and there are four of them:
#
#   1.0    a flag, 1 for low and 0 for normal
#   0.02   volts per count
#   0.1    volts per count
#   'level' a level from 0 to 5, where 6 means the sensor is on mains
#
# A level is left as the level it is rather than turned into anything, because it is
# not a voltage and dividing it would make it look like one.
VOLTS_002 = ('wh68', 'wh80', 'wh34', 'wh35', 'wh90')
VOLTS_01 = ('wh40', 'wh51')

# Ids that mean there is no such sensor. The document says writing 0xFFFFFFFF asks
# the gateway to register the transmitter afresh and 0xFFFFFFFE disables it, and a
# gateway reports back whichever it is holding. Neither is a sensor that has anything
# to say.
ABSENT_IDS = (0xFFFFFFFE, 0xFFFFFFFF)

# How long one record is: type, id, battery, signal.
RECORD = struct.Struct('>BIBB')


def battery_of(sensor, raw):
    """One sensor's battery, in whatever that sensor's byte means.

    Args:
        sensor (str): The name from SENSORS, e.g. 'wh34_ch2'.
        raw (int): The battery byte.

    Returns:
        float: Volts for the sensors that send volts, and the flag or level as it
        arrived for the ones that do not.
    """
    family = sensor.split('_')[0]
    if family in VOLTS_002:
        return raw * 0.02
    if family in VOLTS_01:
        return raw * 0.1
    return float(raw)


def read_sensors(data):
    """Battery and signal for every sensor a gateway has registered.

    Args:
        data (bytes): The payload of a CMD_READ_SENSOR_ID_NEW response.

    Returns:
        dict: '<sensor>_batt' and '<sensor>_sig' for each sensor that is present.
    """
    out = {}
    for at in range(0, len(data) - RECORD.size + 1, RECORD.size):
        kind, ident, battery, signal = RECORD.unpack(data[at : at + RECORD.size])
        if kind >= len(SENSORS) or ident in ABSENT_IDS:
            continue
        sensor = SENSORS[kind]
        out[sensor + '_batt'] = battery_of(sensor, battery)
        out[sensor + '_sig'] = float(signal)
    return out


def write_sensors(sensors):
    """The bytes a gateway would send for these sensors.

    Args:
        sensors (dict): Sensor name to (id, battery byte, signal), by the names in
            SENSORS.

    Returns:
        bytes: One record per sensor, in the order SENSORS lists them.
    """
    out = []
    for kind, sensor in enumerate(SENSORS):
        if sensor not in sensors:
            continue
        ident, battery, signal = sensors[sensor]
        out.append(RECORD.pack(kind, ident, battery, signal))
    return b''.join(out)


# ---- the rest of what a gateway will say about itself -----------------------

# What CMD_READ_SSSS answers with: the radio band, which sensor family the console
# was set up for, its clock, and its timezone. Read for the first two, which are
# worth showing beside a station, and for what it does not carry; see the note on
# units in EcowittGateway.
SYSTEM = struct.Struct('>BBIBB')

# The bands, by the number the document gives each.
BANDS = {0: '433MHz', 1: '868MHz', 2: '915MHz', 3: '920MHz'}

# Which outdoor array the console was set up for. Two, and only two.
ARRAYS = {0: 'WH24', 1: 'WH65'}


def read_system(data):
    """What a gateway says about itself, out of a CMD_READ_SSSS response.

    Args:
        data (bytes): The payload.

    Returns:
        dict: 'frequency' and 'sensor_type', or an empty dict if it is too short to
        be one of these.
    """
    if len(data) < SYSTEM.size:
        return {}
    band, array, _, _, _ = SYSTEM.unpack(data[: SYSTEM.size])
    return {
        'frequency': BANDS.get(band, str(band)),
        'sensor_type': ARRAYS.get(array, str(array)),
    }


def read_mac(data):
    """The gateway's MAC, written the way a MAC is written.

    Args:
        data (bytes): The payload of a CMD_READ_STATION_MAC response.

    Returns:
        str: e.g. 'AA:BB:CC:DD:EE:FF', or '' if there are not six bytes.

    """
    if len(data) < 6:
        return ''
    return ':'.join('%02X' % one for one in data[:6])


def read_firmware(data):
    """The firmware string, out of a CMD_READ_FIRMWARE_VERSION response.

    Args:
        data (bytes): The payload, a length byte and then that many characters.

    Returns:
        str: e.g. 'GW1100A_V2.2.4', or '' if there is nothing readable in it.
    """
    if not data:
        return ''
    wide = min(data[0], len(data) - 1)
    return data[1 : 1 + wide].decode('ascii', 'replace').strip()


# ---- asking one --------------------------------------------------------------


def fetch(source):
    """Hold the whole conversation with one gateway, and hand back a reading.

    Several commands make one reading. Live data is one, rain on a console with a
    piezo gauge is another, and battery and signal are a third, so this is where the
    conversation belongs rather than in a fetcher that knows only how to ask once.

    What comes back is JSON, because that is what the rest of the driver reads. The
    binary stops here.

    Called as ``fetch(source)`` by polling.Source, in place of the HTTP fetch.

    Args:
        source (polling.Source): What to ask, for its url and its timeout.

    Returns:
        tuple: (the body as bytes, the headers as a dict with lowercased keys).

    Raises:
        Exception: If the gateway cannot be reached, or answers something that is not
            an answer to what was asked. The poller sits in the failure.
    """
    host, port = address_of(source.url)
    answer = {}
    readings = {}
    connection = socket.create_connection((host, port), timeout=source.timeout)
    try:
        connection.settimeout(source.timeout)
        answer['mac'] = read_mac(_ask(connection, CMD_READ_STATION_MAC))
        answer['firmware'] = read_firmware(_ask(connection, CMD_READ_FIRMWARE_VERSION))
        answer['model'] = answer['firmware'].split('_')[0]
        answer.update(read_system(_ask(connection, CMD_READ_SSSS)))
        readings.update(_stream(connection, CMD_GW1000_LIVEDATA, LIVE))
        readings.update(read_sensors(_ask(connection, CMD_READ_SENSOR_ID_NEW)))
        # Asked last, and only this one may fail. A console whose firmware predates
        # the command says nothing at all rather than refusing, so asking waits out
        # the timeout, and an answer that turned up after that wait would be read as
        # the answer to whatever was asked next. Last means there is no next.
        #
        # It is not a failure either: everything such a console has is in the live
        # data already. A console with a piezo gauge keeps its rain here and nowhere
        # else, which is why what this answers wins where the two overlap.
        try:
            readings.update(_stream(connection, CMD_READ_RAIN, RAIN))
        except (OSError, ValueError) as e:
            log.debug("%s does not answer CMD_READ_RAIN: %s", source.name, e)
    finally:
        connection.close()
    if not answer['mac']:
        raise ValueError("answered on %d without a MAC, so it is not a gateway" % port)
    body = json.dumps({'gateway': answer, 'readings': readings}).encode('utf-8')
    return body, {'content-type': 'application/json'}


def address_of(url):
    """Where the gateway is, out of what was written down.

    A polled source is written as a host and a port rather than as a URL, because
    this is not HTTP and calling it `http://` would send somebody to a browser.

    Args:
        url (str): What the source holds, e.g. '192.168.1.50:45000'.

    Returns:
        tuple: (the host as a str, the port as an int).
    """
    written = url.strip()
    if '://' in written:
        written = written.split('://', 1)[1]
    if ':' in written:
        host, _, port = written.rpartition(':')
        try:
            return host, int(port)
        except ValueError:
            return written, DEFAULT_PORT
    return written, DEFAULT_PORT


def _ask(connection, command):
    """Send one command and read back its payload.

    Args:
        connection (socket.socket): An open connection to the gateway.
        command (int): The command byte.

    Returns:
        bytes: The payload of the answer.

    Raises:
        OSError: If the connection fails or the gateway stops answering.
        ValueError: If what came back is not an answer to this command.
    """
    connection.sendall(frame(command))
    wide = size_width(command, True)
    # The size is the fourth byte, or the fourth and fifth, so that much has to be in
    # hand before there is anything to say how much more to read.
    head = _read_exactly(connection, 3 + wide)
    if not head.startswith(HEADER):
        raise ValueError("no 0xffff header, so this is not a gateway answering")
    size = struct.unpack('>H' if wide == 2 else '>B', head[3:])[0]
    rest = 2 + size - len(head)
    if rest < 1 or 2 + size > MOST_BYTES:
        raise ValueError("claims a frame of %d bytes, which is not one" % (2 + size))
    return payload_of(command, head + _read_exactly(connection, rest))


def _read_exactly(connection, wanted):
    """Read this many bytes, or say the gateway stopped.

    Args:
        connection (socket.socket): The open connection.
        wanted (int): How many bytes.

    Returns:
        bytes: Exactly that many.

    Raises:
        OSError: If the gateway closed the connection first. The socket's own timeout
            is what stops this waiting forever.
    """
    got = b''
    while len(got) < wanted:
        more = connection.recv(wanted - len(got))
        if not more:
            raise OSError("the gateway closed the connection mid-answer")
        got += more
    return got


def _stream(connection, command, table):
    """One addressed stream, read with the table that goes with that command.

    Args:
        connection (socket.socket): The open connection.
        command (int): CMD_GW1000_LIVEDATA or CMD_READ_RAIN.
        table (dict): LIVE or RAIN.

    Returns:
        dict: The readings.
    """
    readings, stopped = read_stream(_ask(connection, command), table)
    if stopped is not None:
        # Said once per address per run of the driver. A gateway that has gained a
        # sensor this driver does not know sends the same unknown address every
        # interval, and a line a minute about it would be worse than the gap.
        _say_unknown(command, stopped)
    return readings


# Addresses already complained about, so that the complaint is made once. Keyed by
# the command too: the same byte means different things in the two streams.
_UNKNOWN = set()  # type: Set[Tuple[int, int]]


def _say_unknown(command, address):
    """Say once that an address is not in the table.

    Args:
        command (int): Which stream it was in.
        address (int): The address byte.
    """
    if (command, address) in _UNKNOWN:
        return
    _UNKNOWN.add((command, address))
    log.warning(
        "An Ecowitt gateway sent 0x%02x, which this driver's table does not have, so "
        "the rest of that reading was not read. Please report it.",
        address,
    )


class EcowittGateway(Protocol):
    """An Ecowitt gateway's own API on TCP port 45000."""

    name = 'ecowitt_gateway'
    label = 'Ecowitt gateway API'
    hardware = (
        'GW1000, GW1100, GW1200, GW2000, GW3000 and the WH2650 and WN1900 consoles, '
        'read over their own API instead of being pointed at a server'
    )

    # Asked rather than waited for, and asked over a socket of its own rather than
    # over HTTP, which is what fetch() is for.
    fetched = True
    reached = 'fetch'
    # Not a path: this is not HTTP. It is what completes an address somebody types,
    # which for this hardware is the port Ecowitt fixed.
    fetch_path = ':%d' % DEFAULT_PORT

    # The gateway's MAC, which it answers with and which nothing has to be typed in
    # for. It is also what the console's own app shows, so the two can be compared.
    identity = ('mac',)
    secret_kind = None

    # Everything the API sends is already in the units this catalog is read as, and
    # there is nothing on the device that can change that.
    #
    # The task this was written from expected the unit setting to come out of
    # CMD_READ_SSSS. It is not there: that command answers the radio band, which
    # outdoor array the console was set up for, its clock, its timezone index and its
    # daylight saving flag, and nothing else. The document states a unit against each
    # address instead, once and for all devices, and they are Celsius, hPa,
    # millimetres, metres per second and lux. That is METRICWX, except for the light
    # reading, which the catalog scales.
    #
    # So the console's display setting changes the console's display and not this.
    units = METRICWX

    fields = _catalog.FIELDS
    groups = _catalog.GROUPS
    scale = _catalog.SCALE
    metadata = _catalog.METADATA

    notes = (
        "Nothing is set on the console. This driver connects to the gateway and "
        "asks, so what it needs is the gateway's address on your network.",
        "Give the gateway a fixed address in your router. One whose address moves "
        "stops being answered, and the log is the only place that says so.",
        "This and the console's *Customized* upload are independent. A gateway "
        "answers here whether or not that upload is switched on, so both can run.",
    )

    @classmethod
    def fetch(cls, source, ask):
        """Hold the whole conversation, and hand back one reading.

        `ask` goes unused: it makes an HTTP request, and this hardware answers a
        binary protocol on a socket. What it is for is being the one way a protocol
        assembles its own answer, whether that means several HTTP requests or a
        conversation on a socket, so that the poller has one thing to call rather
        than one per kind of hardware.

        Args:
            source (polling.Source): Where the gateway is, and how long to wait.
            ask (callable): Unused here. See polling.ask.

        Returns:
            tuple: (the body as bytes, the headers as a dict).
        """
        return fetch(source)

    @classmethod
    def claims(cls, request, raw):
        """What this driver's own gateway fetcher produces, and nothing else.

        Nothing sends this over the network. It is built here, out of several
        answers that are not JSON at all, so a wrapper is what identifies it: an
        upload that happens to carry weather readings cannot be mistaken for one.
        """
        held = raw.get('gateway')
        if not isinstance(held, dict) or not held.get('mac'):
            return 0
        if not isinstance(raw.get('readings'), dict):
            return 0
        return 5

    @classmethod
    def readings(cls, request, raw):
        """Unwrap it, so the rest of the driver sees one flat set of names.

        What is above the readings names the gateway, and comes with them because
        that is what the page shows.
        """
        held = raw.get('readings')
        named = dict(held) if isinstance(held, dict) else {}
        about = raw.get('gateway')
        if isinstance(about, dict):
            for key, value in about.items():
                named.setdefault(key, value)
        return named

    @classmethod
    def station_of(cls, raw):
        """The gateway's MAC, out of the wrapper where the fetcher put it."""
        held = raw.get('gateway') or {}
        return str(held.get('mac') or '').strip()
