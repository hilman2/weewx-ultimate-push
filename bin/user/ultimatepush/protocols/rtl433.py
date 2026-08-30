#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""Cheap radio sensors, by way of rtl_433.

A twenty-five euro USB stick and rtl_433 will hear every sensor within a few
hundred metres that talks on 433, 868 or 915 MHz: outdoor thermometers, soil
probes, pool thermometers, rain gauges. rtl_433 does the radio and the decoding,
which is the whole of the difficulty, and hands over named JSON. This reads it.

    rtl_433 -C si -F syslog:127.0.0.1:1433

That sends one datagram per message, framed the way syslog frames things, with the
JSON on the end. Nothing has to be started or supervised by this driver: rtl_433 is
its own service and talks to a socket, the same arrangement a WeatherFlow hub uses.

**One receiver, many stations.** Every message says which sensor it came from, and
each of those is a station here, with its own role, its own channel and its own
columns. The ones that are yours are let in and the rest are refused, which matters
more than it sounds: a receiver also hears the neighbours' sensors, the tyre
pressure sensors of cars going past, and doorbells.

**Units come out of the name.** rtl_433's own rule is `<Type>_<Unit>`, so
`temperature_F` and `temperature_C` are the same reading in two units and it says
so. They are converted here, from the suffix, before anything is placed. `-C si`
asks rtl_433 to do most of it first, which is worth doing and not required.
"""

import logging

from . import METRICWX, Protocol
from .. import catalogs

log = logging.getLogger(__name__)

_catalog = catalogs.rtl433

# Where rtl_433 is told to send. Nothing official: 514 is syslog's own and taking it
# would mean this driver had to run as root, so this is 433 with a 1 in front of it,
# which is what the examples in the wild use.
DEFAULT_PORT = 1433

# What each suffix means, and what it takes to get to the unit METRICWX keeps that
# reading in. A pair of (the suffix it becomes, a function of the value).
#
# Longest first: '_in_h' has to be tried before '_in', or a rain rate becomes a rain
# total in the wrong unit and nothing says so.
CONVERSIONS = (
    ('_in_h', '_mm_h', lambda v: v * 25.4),
    ('_mi_h', '_m_s', lambda v: v * 0.44704),
    ('_km_h', '_m_s', lambda v: v / 3.6),
    ('_inHg', '_hPa', lambda v: v * 33.863886),
    ('_PSI', '_hPa', lambda v: v * 68.947573),
    ('_psi', '_hPa', lambda v: v * 68.947573),
    ('_kPa', '_hPa', lambda v: v * 10.0),
    ('_klx', '_lux', lambda v: v * 1000.0),
    ('_in', '_mm', lambda v: v * 25.4),
    ('_F', '_C', lambda v: (v - 32.0) * 5.0 / 9.0),
)


class Rtl433(Protocol):
    """One message from rtl_433, as it puts it on a UDP socket."""

    name = 'rtl433'
    label = 'rtl_433'
    hardware = (
        'Any 433, 868 or 915 MHz sensor rtl_433 decodes, heard with an RTL-SDR '
        'stick: outdoor thermometers, soil probes, rain gauges, pool sensors'
    )

    datagram = True
    default_port = DEFAULT_PORT
    reached = 'broadcast'

    # A stick hears over the air and over the fence. Nothing it hears is taken for
    # this installation's own, so every sensor waits to be let in.
    overhears = True

    # What tells one sensor from the next. Built rather than picked: a receiver
    # hears many sensors and no single field names one of them. See station_of.
    identity = ('model',)
    secret_kind = None

    # Everything is converted before it is placed, so the catalog is one system.
    units = METRICWX
    fields = _catalog.FIELDS
    groups = _catalog.GROUPS
    metadata = _catalog.METADATA

    # Nearly every one of these gauges sends the total since its battery went in,
    # which is what this column is for and what StdDelta has to difference.
    rain_counter = 'dayRain'

    notes = (
        "rtl_433 is a separate program and is not part of this driver. Install it "
        "with your package manager, then have it send here.",
        "Run it with `-C si`, which asks it to convert what it can itself, and "
        "`-F syslog:127.0.0.1:%d`, which is how it sends." % DEFAULT_PORT,
        "One stick hears every sensor in range, including your neighbours'. Each "
        "one shows here as a station waiting to be let in, and only the ones you "
        "let in are recorded.",
        "Many of these sensors pick a new id when their batteries are changed. When "
        "that happens the station stops recording and a new one appears; the web "
        "interface can move the old station onto the new id and keep its columns.",
    )

    @classmethod
    def claims(cls, request, raw):
        """A message with a model name and a decoder number.

        `model` alone is not enough: other JSON has one. `protocol` is rtl_433's own
        decoder number and is on every message it sends, so the two together are as
        good as a signature.
        """
        if not raw.get('model'):
            return 0
        if 'protocol' in raw or 'mic' in raw or 'mod' in raw:
            return 5
        # An older rtl_433, or one told to leave those out. Claimed, because a model
        # and a time and nothing else is still more likely this than anything else
        # here, but claimed less strongly.
        return 2

    @classmethod
    def readings(cls, request, raw):
        """Convert every reading to the unit this catalog is written in.

        rtl_433 fixes the unit in the field name, so this is arithmetic rather than
        knowledge about any device: `temperature_F` is the same reading as
        `temperature_C` and the suffix says which. Doing it here rather than with a
        per-field scale is what lets the catalog hold one name per reading instead
        of one per name and unit, and it is also the only place an offset can be
        applied, which Fahrenheit needs and a scale cannot give.
        """
        named = {}
        for key, value in raw.items():
            name, number = cls._converted(key, value)
            named[name] = number
        if 'battery_ok' in named:
            # rtl_433 sends 1 for a good battery. This column means the opposite: it
            # is a fault flag, and WeeWX reports on it as one.
            named['battery_ok'] = cls._flipped(named['battery_ok'])
        return named

    @classmethod
    def _converted(cls, key, value):
        """One reading, in the unit this catalog is written in.

        Args:
            key (str): The name rtl_433 used.
            value (float | int | str): The value it sent.

        Returns:
            tuple: (the name to place it under, the value). Both unchanged when the
            name carries no unit, or the value is not a number.
        """
        for suffix, becomes, how in CONVERSIONS:
            if not key.endswith(suffix):
                continue
            try:
                number = float(value)
            except (TypeError, ValueError):
                # A reading sent as text. Left alone rather than dropped: the raw
                # uploads page should show what arrived.
                return key, value
            return key[: -len(suffix)] + becomes, how(number)
        return key, value

    @classmethod
    def _flipped(cls, value):
        """A battery flag, the way round WeeWX means it.

        Args:
            value (float | int | str): What rtl_433 sent, where 1 means the battery
                is good.

        Returns:
            int | float | str: The flag inverted, or the value unchanged when it is
            not one.
        """
        try:
            return 0 if float(value) else 1
        except (TypeError, ValueError):
            return value

    @classmethod
    def station_of(cls, raw):
        """Which sensor sent this, as one name.

        No single field names a sensor. `model` says what kind it is, `id` which one
        of that kind, and `channel` which of the two or three switches on its back.
        A receiver hears several of the same model, so all three are needed, and a
        sensor that sends only some of them is still told apart from the others by
        what it does send.

        The id is not always the same tomorrow. Many of these sensors pick a new one
        when their batteries are changed, and rtl_433's own documentation says so.
        That is why the interface can move a station onto a new identity.
        """
        model = str(raw.get('model', '')).strip()
        if not model:
            return ''
        parts = [model]
        for field in ('id', 'channel'):
            value = raw.get(field)
            if value is not None and str(value).strip() != '':
                parts.append(str(value).strip())
        return '/'.join(parts)
