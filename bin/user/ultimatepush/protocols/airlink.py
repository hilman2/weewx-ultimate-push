#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""Davis AirLink air quality sensors, which are asked rather than pointed.

An AirLink has nowhere to type a server address into. It runs a small web server on
the local network and answers whoever asks, so this driver goes and asks, on a
schedule, and treats the answer as though it had been pushed.

What it answers is not flat. Davis wraps every local API answer the same way:

    {"data": {"did": "001D0A100123", "ts": 1788121515,
              "conditions": [{"lsid": 405284, "data_structure_type": 6,
                              "temp": 71.6, "hum": 44.2, "pm_2p5": 7.2, ...}]},
     "error": null}

The readings are the first entry of `conditions`. Everything above that says which
device answered and when, so it is unwrapped here and the rest of the driver sees
one flat set of names, the same as every other protocol.

The same wrapper is what a WeatherLink Live uses for a Vantage, so unwrapping it
here is the part that would be worth keeping if that ever became a second protocol.
"""

import logging

from . import Protocol
from .. import catalogs

log = logging.getLogger(__name__)

_catalog = catalogs.airlink

# What to ask for, appended to the address somebody types in. Davis fixes this: it
# is the same on every device that speaks the local API.
DEFAULT_PATH = '/v1/current_conditions'

# The shape of a reading, as Davis numbers its shapes. An AirLink sends 6; the 5 an
# early firmware sent is the same thing with the ten micron readings named
# differently, and those names are in the catalog too.
STRUCTURES = (5, 6)


class AirLink(Protocol):
    """A Davis AirLink's own local API."""

    name = 'airlink'
    label = 'Davis AirLink'
    hardware = 'Davis AirLink air quality sensors'

    fetched = True
    reached = 'fetch'
    fetch_path = DEFAULT_PATH

    # The device id Davis prints on the back, which is what it calls itself. Read
    # out of the wrapper rather than out of the readings; see station_of.
    identity = ('did',)
    secret_kind = None

    # It measures no rain, so there is no counter for StdDelta to difference.
    rain_counter = None

    fields = _catalog.FIELDS
    groups = _catalog.GROUPS
    metadata = _catalog.METADATA

    notes = (
        "An AirLink has nowhere to type a server address into. It is asked rather "
        "than pointed, so what this driver needs is its address on your network.",
        "Give it a fixed address in your router. One whose address moves stops "
        "being found, and the log is the only place that says so.",
        "Its thermometer is inside the housing and reads above the air outside, "
        "though by less than a PurpleAir's. Set the station up as an extra one and "
        "that reading goes to a column of its own.",
    )

    @classmethod
    def claims(cls, request, raw):
        """A Davis local API answer carrying a reading of the shape an AirLink sends.

        Nothing else here wraps its readings this way, and the shape number rules
        out the other things that speak this API, such as a WeatherLink Live.
        """
        first = cls._conditions(raw)
        if first is None:
            return 0
        if first.get('data_structure_type') in STRUCTURES:
            return 5
        # Davis, and not an AirLink. Not claimed: reading a Vantage's conditions
        # with this catalog would place a handful of names and drop the rest.
        return 0

    @classmethod
    def readings(cls, request, raw):
        """Unwrap the answer, so that the rest of the driver sees one flat set.

        What is above the readings names the device and says when it answered, and
        the id is what the page shows.

        Nothing is stamped from the device's own clock, though it sends two of them.
        `last_report_time` is seconds since boot on some firmware rather than an
        epoch, which weewx-airlink found the hard way and works around; a reading
        stamped from that would land in 1970 or in the future depending on which
        firmware answered. The driver's own clock is within one interval of the
        reading here, because it just asked, so it is the better of the two.
        """
        first = cls._conditions(raw)
        if first is None:
            return {}
        named = dict(first)
        held = raw.get('data') or {}
        for key in ('did', 'name', 'ts'):
            if key in held:
                named.setdefault(key, held[key])
        return named

    @classmethod
    def station_of(cls, raw):
        """The device id, which Davis prints on the back of the case.

        Taken from the wrapper, because that is where Davis puts it, and this is
        given the answer as it arrived rather than after unwrapping.
        """
        held = raw.get('data') or {}
        value = held.get('did') or ''
        return str(value).strip()

    @classmethod
    def _conditions(cls, raw):
        """The first entry of the conditions list, or None if there is not one.

        Args:
            raw (dict): The answer, as it arrived.

        Returns:
            dict: The readings, or None when this is not a Davis local API answer.
        """
        held = raw.get('data')
        if not isinstance(held, dict):
            return None
        conditions = held.get('conditions')
        if not isinstance(conditions, list) or not conditions:
            return None
        first = conditions[0]
        return first if isinstance(first, dict) else None
