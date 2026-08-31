#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""An Ambient Weather station read back from ambientweather.net.

Everything here runs against the shipped fake, on a port the machine chose, so
there is no account and no network beyond the loopback. The fake is
`simulate.ambient_handler`, which is the same object `--fake-ambient-cloud` runs.

Three things are checked over and over. That the two keys never reach anything that
prints, because they are somebody's account and a URL is printed by the log, the
page of raw uploads and `repr`. That an account holding two stations does not
silently record one of them, because both look alike and the wrong one is a garden
somewhere else. And that Ambient's own `feelsLike` and `dewPoint` stay out, because
WeeWX computes both and a station whose dew point came from two different sums is
worse than one whose dew point came from either.
"""

import json
import socketserver
import threading
import time

import pytest

from ultimatepush import polling, simulate
from ultimatepush.protocols.ambient_cloud import AmbientCloud

APPLICATION_KEY, API_KEY = simulate.AMBIENT_KEYS
GARDEN = simulate.AMBIENT_STATIONS[0]
SHED = simulate.AMBIENT_STATIONS[1]


class Account:
    """The shipped fake, on a port of its own, keeping every URL it was asked.

    Its clock is stopped at the moment it started, so that a test can assert the
    reading rather than a range around it.

    Args:
        keys (tuple): The (application key, API key) pair it insists on.
    """

    def __init__(self, keys=simulate.AMBIENT_KEYS):
        self.asked = []
        self.pinned = time.time()
        pinned = self.pinned
        base = simulate.ambient_handler(keys, clock=lambda: pinned)
        counting = self

        class Handler(base):
            """The fake, with a note of every request kept beside it."""

            def do_GET(self):
                counting.asked.append(self.path)
                base.do_GET(self)

            def log_message(self, *args):
                """Quiet. The test says what happened, not the server."""

        self.server = socketserver.TCPServer(('127.0.0.1', 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self):
        return 'http://127.0.0.1:%d' % self.port

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)


@pytest.fixture
def account():
    """An account with two stations on it, at one moment."""
    made = Account()
    yield made
    made.close()


def source_for(account, **extra):
    """A source pointed at the fake.

    Args:
        account (Account): The fake.
        **extra (str): Anything else to put in the block, as configobj hands it
            over.

    Returns:
        polling.Source: The source.
    """
    block = {
        'url': account.url,
        'protocol': 'ambient_cloud',
        'application_key': APPLICATION_KEY,
        'api_key': API_KEY,
    }
    block.update(extra)
    return polling.source_for('garten', block)


def read(source):
    """One reading, as the driver would take it.

    Args:
        source (polling.Source): What to ask.

    Returns:
        dict: What was in lastData, decoded.
    """
    body, _ = AmbientCloud.fetch(source, polling.ask)
    return json.loads(body.decode('utf-8'))


# ---- the keys, which are somebody's account ---------------------------------


def test_the_keys_are_not_in_the_url_the_source_keeps(account):
    source = source_for(account)
    assert APPLICATION_KEY not in source.url
    assert API_KEY not in source.url
    assert APPLICATION_KEY not in repr(source)
    assert API_KEY not in repr(source)


def test_the_keys_are_on_the_request_all_the_same(account):
    read(source_for(account, mac=GARDEN['mac']))
    asked = account.asked[-1]
    assert 'applicationKey=' + APPLICATION_KEY in asked
    assert 'apiKey=' + API_KEY in asked


def test_a_source_with_no_keys_sends_none(account):
    source = polling.source_for(
        'garten', {'url': account.url, 'protocol': 'ambient_cloud'}
    )
    assert source.query == {}


def test_wrong_keys_say_so_rather_than_saying_unreachable(account):
    source = source_for(account, api_key='not-the-key')
    with pytest.raises(ValueError) as raised:
        read(source)
    said = str(raised.value)
    assert 'refused' in said
    assert 'application_key' in said and 'api_key' in said


def test_what_it_says_about_wrong_keys_does_not_repeat_them(account):
    source = source_for(account, api_key='not-the-key')
    with pytest.raises(ValueError) as raised:
        read(source)
    assert APPLICATION_KEY not in str(raised.value)


# ---- which station -----------------------------------------------------------


def test_an_account_with_two_stations_will_not_guess(account):
    with pytest.raises(ValueError) as raised:
        read(source_for(account))
    said = str(raised.value)
    assert "'mac'" in said
    assert GARDEN['mac'] in said and SHED['mac'] in said
    assert GARDEN['name'] in said


def test_the_mac_picks_the_station(account):
    garden = read(source_for(account, mac=GARDEN['mac']))
    shed = read(source_for(account, mac=SHED['mac']))
    assert garden['macAddress'] == GARDEN['mac']
    assert shed['macAddress'] == SHED['mac']
    assert garden['tempf'] != shed['tempf']


def test_the_mac_is_read_whatever_its_case(account):
    reading = read(source_for(account, mac=GARDEN['mac'].lower()))
    assert reading['macAddress'] == GARDEN['mac']


def test_a_mac_no_station_has_says_which_it_found(account):
    with pytest.raises(ValueError) as raised:
        read(source_for(account, mac='00:00:00:00:00:00'))
    said = str(raised.value)
    assert GARDEN['mac'] in said and SHED['mac'] in said


def test_one_station_needs_no_mac():
    only = simulate.AMBIENT_STATIONS[:1]
    chosen = AmbientCloud._chosen(
        polling.Source('garten', 'http://example.invalid'),
        [{'macAddress': one['mac'], 'lastData': {}} for one in only],
    )
    assert chosen['macAddress'] == GARDEN['mac']


def test_an_empty_account_says_to_add_the_console():
    with pytest.raises(ValueError) as raised:
        AmbientCloud._chosen(polling.Source('garten', 'http://example.invalid'), [])
    assert 'awnet' in str(raised.value)


# ---- what a reading is, and what it is not -----------------------------------


def test_the_readings_arrive_under_the_names_the_console_posts(account):
    reading = read(source_for(account, mac=GARDEN['mac']))
    for name in ('tempf', 'humidity', 'baromrelin', 'windspeedmph', 'soilhum1'):
        assert name in reading


def test_the_catalog_is_the_one_the_pushing_protocol_uses():
    from ultimatepush.protocols.ambient import Ambient

    assert AmbientCloud.fields is Ambient.fields
    assert AmbientCloud.groups is Ambient.groups
    assert AmbientCloud.units == Ambient.units


def test_every_reading_the_fake_sends_is_one_the_catalog_places(account):
    reading = read(source_for(account, mac=GARDEN['mac']))
    unplaced = [
        name
        for name in reading
        if name not in AmbientCloud.fields and name not in AmbientCloud.metadata
    ]
    assert unplaced == []


def test_ambients_own_arithmetic_is_not_a_reading():
    # WeeWX has StdWXCalculate for both. Two sources for one column is how a
    # database ends up with a dew point that disagrees with its own temperature.
    assert 'feelsLike' in AmbientCloud.metadata
    assert 'dewPoint' in AmbientCloud.metadata
    assert 'feelsLike' not in AmbientCloud.fields
    assert 'dewPoint' not in AmbientCloud.fields


def test_the_station_is_named_by_its_mac(account):
    reading = read(source_for(account, mac=GARDEN['mac']))
    assert AmbientCloud.station_of(reading) == GARDEN['mac']


def test_nothing_claims_this_protocol_by_recognising_it():
    # It is asked for by name. A protocol that claimed an arriving upload here
    # would be claiming somebody else's, because nothing arrives on its own.
    assert AmbientCloud.claims(None, {'tempf': '59.9'}) == 0


# ---- the timestamp, which arrives in a shape nothing else sends ---------------


def test_the_millisecond_stamp_becomes_one_the_driver_reads(account):
    from ultimatepush import transport

    reading = read(source_for(account, mac=GARDEN['mac']))
    assert transport.device_time(reading) == pytest.approx(
        account.pinned - account.pinned % 60, abs=1
    )


def test_a_stamp_that_is_not_a_number_leaves_the_clock_to_the_driver():
    made = AmbientCloud._reading({'macAddress': 'x', 'lastData': {'dateutc': 'now'}})
    assert 'dateutc' not in made


def test_a_number_in_dateutc_does_not_reach_strptime():
    # It cannot after _reading, but device_time is shared with everything else and
    # a JSON upload from anywhere may carry one. strptime raises TypeError for it,
    # which is not the error the caller was catching.
    from ultimatepush import transport

    assert transport.device_time({'dateutc': 1515436500000}) is None


# ---- the address, which is the same for everybody ----------------------------


def test_a_block_needs_no_address():
    source = polling.source_for(
        'garten',
        {
            'protocol': 'ambient_cloud',
            'application_key': APPLICATION_KEY,
            'api_key': API_KEY,
        },
    )
    assert source.url == 'https://api.ambientweather.net'


def test_an_address_still_wins_where_one_is_given(account):
    assert source_for(account).url == account.url
