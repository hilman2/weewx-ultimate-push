#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""Which station owns which column.

A role moves an extra station's temperature and humidity aside and drops what has
nowhere to go, but "nowhere to go" was measured against the main station alone. Three
identical consoles set up as extra sensors all send the same soil moisture, and if the
main station is a console that has no such reading, all three used to write it.

These are about the rule that finishes the job: one column, one owner.
"""

import pytest

pytest.importorskip('weewx', reason="WeeWX is not installed")

from ultimatepush import owners                         # noqa: E402


def test_a_column_goes_to_whoever_fills_it_first():
    register = owners.Register()

    assert register.claim('soilMoist1', 'garden') == (True, None)
    assert register.claim('soilMoist1', 'roof') == (False, None)
    assert register.owner('soilMoist1') == 'garden'


def test_asking_twice_is_not_a_conflict():
    """Every upload asks for every column it fills. The second one is not news."""
    register = owners.Register({'outTemp': 'garden'})

    assert register.claim('outTemp', 'garden') == (True, None)


def test_the_main_station_outranks_whoever_had_it():
    """Otherwise which console owns outTemp is settled by whichever one happened to
    upload first after a restart."""
    register = owners.Register({'outTemp': 'roof'})

    allowed, lost = register.claim('outTemp', 'garden', is_main=True)

    assert allowed is True
    assert lost == 'roof'
    assert register.owner('outTemp') == 'garden'


def test_and_never_the_other_way_round():
    register = owners.Register({'outTemp': 'garden'})
    register.claim('outTemp', 'garden', is_main=True)

    assert register.claim('outTemp', 'roof', is_main=False) == (False, None)


def test_what_a_station_holds_can_be_said_and_given_up():
    register = owners.Register({'extraTemp1': 'roof', 'extraHumid1': 'roof',
                                'outTemp': 'garden'})

    assert register.owns('roof') == ['extraHumid1', 'extraTemp1']

    assert register.release_all('roof') == ['extraHumid1', 'extraTemp1']
    assert register.owns('roof') == []
    assert register.owner('outTemp') == 'garden'


def test_the_things_that_are_not_readings_are_not_owned():
    """Every station sends the time and the units. Owning those would mean the first
    station to upload owning every packet."""
    kept = owners.readings({'dateTime': 1, 'usUnits': 1, 'station': 'garden',
                            'interval': 5, 'outTemp': 59.7})

    assert kept == ['outTemp']
