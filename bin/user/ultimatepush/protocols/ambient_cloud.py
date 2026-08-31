#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""An Ambient Weather station, read back from ambientweather.net.

The same hardware as protocols/ambient.py and the same vocabulary, asked instead of
received. `lastData` in Ambient's API holds the names their consoles POST: `tempf`,
`humidity`, `baromrelin`, `soilhum1`, `battout`. So this shares that catalog, and a
station moved from one to the other keeps its columns.

Worth doing for the consoles that cannot be pointed anywhere. The awnet app offers
one custom server and older models offer none, so a station whose slot is already
taken, or which never had one, has no way to reach a driver on its own network. This
reaches it the other way round.

It is also the only way to read a station that is not on your network at all: a
second home, a relative's garden, a club's field.

Two keys, both made at ambientweather.net/account. The application key identifies
the program and the API key identifies the account, and neither goes in the URL this
driver keeps. See Protocol.query_for.
"""

import json
import time
import urllib.error

from .. import catalogs
from . import US, Protocol

_catalog = catalogs.ambient

# Where the account lives, with the scheme spelled out. A fetch_host without one
# gets http:// put in front of it, which is the right guess for a sensor on somebody's
# own network and the wrong one for an account key crossing the internet.
HOST = 'https://api.ambientweather.net'
DEVICES = '/v1/devices'

# What the account is refused with, as opposed to being unreachable. Worth its own
# message: a wrong key is a thing somebody can fix, and 'cannot reach' sends them to
# look at their network instead.
REFUSED = (401, 403)

# Names in lastData that are not readings. `date` and `dateutc` are when, not what,
# and the other two are Ambient's own arithmetic: WeeWX has StdWXCalculate for both
# and would rather do it from the readings than take somebody else's answer.
NOT_READINGS = frozenset(['date', 'dateutc', 'feelsLike', 'dewPoint', 'lastRain'])


class AmbientCloud(Protocol):
    """One Ambient Weather station, read from the account it uploads to."""

    name = 'ambient_cloud'
    label = 'Ambient Weather (ambientweather.net)'
    hardware = (
        'Any Ambient console on an ambientweather.net account, including the ones '
        "with no 'Custom' upload to point at a driver"
    )

    # Asked, never received. Nothing arrives on its own and there is no socket.
    fetched = True
    reached = 'fetch'
    fetch_host = HOST
    # Empty rather than DEVICES: the answer is a list of every station on the
    # account and one of them has to be picked out, which fetch() does.
    fetch_path = ''
    fetch_settings = (
        ('application_key', 'the-application-key-from-your-account-page'),
        ('api_key', 'the-api-key-from-your-account-page'),
    )

    # The station, out of however many the account holds. Read once, at setup.
    identity = ('macAddress',)
    secret_kind = None

    units = US
    fields = _catalog.FIELDS
    groups = _catalog.GROUPS
    channels = _catalog.CHANNELS
    contested = _catalog.CONTESTED
    contested_with = _catalog.CONTESTED_WITH
    placement_unknown = _catalog.PLACEMENT_UNKNOWN
    metadata = frozenset(NOT_READINGS | {'macAddress', 'stationtype', 'model', 'tz'})

    notes = (
        "Two keys, both from the account page at ambientweather.net. The "
        "application key names the program and the API key names the account. "
        "Neither is typed into the console and neither is your password.",
        "An account with one station needs nothing else. An account with several "
        "needs 'mac' as well, and a block without one says which stations it "
        "found so that you can copy the right address out of the message.",
        "Ambient caps a key at one request a second. Sixty seconds between "
        "readings, which is this driver's default, is well inside that, and is "
        "also as often as their servers have anything new.",
    )

    @classmethod
    def query_for(cls, settings):
        """The two keys, on every request this source makes.

        Ambient takes them no other way: there is no header form of this. They are
        returned here rather than written into the source's URL so that the log
        line naming an address that could not be reached cannot carry them.

        Args:
            settings (dict): The source's block.

        Returns:
            dict: applicationKey and apiKey, leaving out either one that was not
            given. Saying which is missing is Ambient's job, and it says so with a
            401 that this turns into a sentence.
        """
        given = {
            'applicationKey': str(settings.get('application_key', '')).strip(),
            'apiKey': str(settings.get('api_key', '')).strip(),
        }
        return {name: value for name, value in given.items() if value}

    @classmethod
    def fetch(cls, source, ask):
        """One station's latest readings, out of the account's list of stations.

        Args:
            source (Source): What to ask. See polling.Source.
            ask (callable): `ask(source, url)`, which makes one request and returns
                (body, headers). See polling.ask.

        Returns:
            tuple: (the station's lastData as JSON bytes, the headers as a dict).

        Raises:
            ValueError: If the keys were refused, if the account holds no station,
                or if it holds several and the block did not say which.
        """
        try:
            body, headers = ask(source, source.url + DEVICES)
        except urllib.error.HTTPError as e:
            if e.code in REFUSED:
                raise ValueError(
                    "ambientweather.net refused the keys (HTTP %d). Check "
                    "'application_key' and 'api_key' against your account page."
                    % e.code
                )
            raise
        devices = json.loads(body.decode('utf-8'))
        chosen = cls._chosen(source, devices if isinstance(devices, list) else [])
        return json.dumps(cls._reading(chosen)).encode('utf-8'), headers

    @classmethod
    def _chosen(cls, source, devices):
        """The one station this source is for.

        Args:
            source (Source): Whose block says which, in 'mac'.
            devices (list): What the account answered with.

        Returns:
            dict: The station's entry, with its macAddress, info and lastData.

        Raises:
            ValueError: If there is no such station, or several and no 'mac'.
        """
        found = [one for one in devices if isinstance(one, dict)]
        wanted = str(source.settings.get('mac', '')).strip().lower()
        if wanted:
            for one in found:
                if str(one.get('macAddress', '')).strip().lower() == wanted:
                    return one
            raise ValueError(
                "no station on this account has the MAC address '%s'. It has: %s."
                % (source.settings.get('mac'), cls._listed(found))
            )
        if not found:
            raise ValueError(
                "this account has no station on it. Add the console in the awnet "
                "app first."
            )
        if len(found) > 1:
            raise ValueError(
                "this account has %d stations on it, so the block has to say which "
                "with a 'mac' line. It has: %s." % (len(found), cls._listed(found))
            )
        return found[0]

    @classmethod
    def _listed(cls, devices):
        """The account's stations, for a message somebody has to act on.

        Args:
            devices (list[dict]): The entries the account answered with.

        Returns:
            str: Each one's MAC address and the name it was given, so that the line
            to add can be copied straight out of the log.
        """
        said = []
        for one in devices:
            info = one.get('info') or {}
            name = str(info.get('name') or '').strip()
            mac = str(one.get('macAddress') or '?')
            said.append("%s (%s)" % (mac, name) if name else mac)
        return ', '.join(said) or 'none'

    @classmethod
    def _reading(cls, device):
        """One station's entry, as the rest of this driver expects an upload.

        Two things change. The MAC address moves in, because that is what names the
        station and it sits outside lastData; and the timestamp is rewritten, because
        Ambient counts milliseconds where a console writes a date.

        Args:
            device (dict): One entry from the account's list.

        Returns:
            dict: The reading, flat, in the names protocols/ambient.py already knows.
        """
        reading = {}
        last = device.get('lastData')
        if isinstance(last, dict):
            reading.update(last)
        reading['macAddress'] = device.get('macAddress', '')
        stamp = _seconds(reading.get('dateutc'))
        if stamp is None:
            reading.pop('dateutc', None)
        else:
            reading['dateutc'] = time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(stamp))
        return reading

    @classmethod
    def claims(cls, request, raw):
        """Never. This is asked for by name, so nothing has to be recognised.

        Args:
            request (weewx.listener.Request): The upload.
            raw (dict): What was in it.

        Returns:
            int: Zero. A source says `protocol = ambient_cloud` and that settles it.
        """
        return 0

    @classmethod
    def station_of(cls, raw):
        """Which station this reading is from.

        Args:
            raw (dict): The reading.

        Returns:
            str: Its MAC address, which is what the account calls it.
        """
        return str(raw.get('macAddress', '')).strip()


def _seconds(stamp):
    """Ambient's millisecond timestamp, as seconds.

    Args:
        stamp (int | float | str | None): What was in `dateutc`.

    Returns:
        float | None: Seconds since the epoch, or None if it was not a number. The
        driver then stamps the reading with its own clock, which for something asked
        once a minute is right to within the interval.
    """
    try:
        return float(stamp) / 1000.0
    except (TypeError, ValueError):
        return None
