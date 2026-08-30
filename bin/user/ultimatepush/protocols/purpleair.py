#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""PurpleAir air quality sensors, which are asked rather than listened for.

Every other protocol here waits for hardware to send something. This one does not:
a PurpleAir sensor runs a small web server on the local network and answers anyone
who asks, and it has nowhere to type a server address into. So the driver goes and
asks it, on a schedule, and the answer is treated as though the sensor had pushed it.

That is the whole of the difference. Once the answer is in hand it goes through the
same detection, the same catalog, the same field map and the same column ownership
as an upload from a console, because it is the same shape: one flat JSON object of
names and values.
"""

import logging

from . import Protocol
from .. import catalogs

log = logging.getLogger(__name__)

_catalog = catalogs.purpleair

# What to ask for, appended to the address somebody types in. The sensor answers
# this and nothing else, so there is no reason to make anybody find it out.
DEFAULT_PATH = '/json'

# Readings only this hardware sends. One of them present, together with a serial
# number, is as good as a signature: nothing else on a home network answers with a
# laser particle count.
PARTICLES = ('pm2_5_atm', 'pm2.5_aqi', 'pm1_0_atm', 'pm10_0_atm')


class PurpleAir(Protocol):
    """A PurpleAir sensor's own /json endpoint."""

    name = 'purpleair'
    label = 'PurpleAir'
    hardware = 'PurpleAir PA-II, PA-II-SD and PA-I air quality sensors'

    # Asked rather than waited for, which is what keeps it out of 'auto': there is
    # no socket to open and nothing arrives on its own.
    fetched = True
    reached = 'fetch'
    fetch_path = DEFAULT_PATH

    # The sensor's MAC, which is what it calls itself and what the driver pins a
    # station to. Nothing has to be typed in: the first answer carries it.
    identity = ('SensorId',)
    secret_kind = None

    # It measures no rain, so there is no counter for StdDelta to difference. Left
    # at the default, 'dayRain', it would ask WeeWX to difference a column this
    # station never fills.
    rain_counter = None

    fields = _catalog.FIELDS
    groups = _catalog.GROUPS
    scale = _catalog.SCALE
    metadata = _catalog.METADATA

    notes = (
        "A PurpleAir has nowhere to type a server address into. It is asked rather "
        "than pointed, so what this driver needs is the sensor's address on your "
        "network.",
        "Give it a fixed address in your router. A sensor whose address moves stops "
        "being found, and the log is the only place that says so.",
        "Its thermometer sits inside the housing, next to electronics that are warm, "
        "and reads several degrees above the air outside. Set the station up as an "
        "extra one and that reading goes to a column of its own instead of into "
        "outTemp.",
    )

    @classmethod
    def claims(cls, request, raw):
        """A JSON answer carrying a sensor id and a particle count.

        Nothing else this driver meets sends either, so one of each settles it. The
        id alone is not enough: it is a MAC address, and other hardware has one.
        """
        if not raw.get('SensorId'):
            return 0
        if any(field in raw for field in PARTICLES):
            return 5
        return 0
