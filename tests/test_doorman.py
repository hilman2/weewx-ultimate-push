#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""The doorman on the web interface.

A weather station is not a bank, and the token is short enough to type. What makes
that sound is not the token's length but that an address which keeps getting it wrong
stops being answered.

The clock is passed in rather than waited for. A test that slept for its window would
take five minutes and would still only prove that sleeping works.
"""

from ultimatepush.admin import Doorman

TOKEN = 'a-good-token'
HERE = '192.168.1.20'
THERE = '192.168.1.99'


def test_the_right_token_is_let_through():
    door = Doorman(TOKEN)

    assert door.check(HERE, TOKEN) == 'ok'


def test_a_wrong_one_is_told_so():
    door = Doorman(TOKEN)

    assert door.check(HERE, 'nope') == 'wrong'
    assert door.check(HERE, '') == 'wrong'
    assert door.check(HERE, None) == 'wrong'


def test_a_near_miss_is_no_better_than_a_wild_guess():
    """Compared in constant time, so neither the answer nor how long it took says how
    much of the token was right."""
    door = Doorman(TOKEN)

    assert door.check(HERE, TOKEN[:-1]) == 'wrong'
    assert door.check(HERE, TOKEN + 'x') == 'wrong'


def test_an_address_that_keeps_trying_stops_being_answered():
    door = Doorman(TOKEN, tries=3, window=300)

    assert [door.check(THERE, 'nope', now=100) for _ in range(3)] == [
        'wrong',
        'wrong',
        'wrong',
    ]
    assert door.check(THERE, 'nope', now=100) == 'blocked'


def test_a_blocked_address_is_blocked_even_with_the_right_token():
    """The black hole does not check. Checking would tell somebody who is guessing
    that they had got it, and it would cost us the comparison every time."""
    door = Doorman(TOKEN, tries=2)
    door.check(THERE, 'nope', now=100)
    door.check(THERE, 'nope', now=100)

    assert door.check(THERE, TOKEN, now=100) == 'blocked'


def test_one_address_getting_it_wrong_does_not_shut_out_another():
    """Otherwise anybody on the network could lock everybody else out."""
    door = Doorman(TOKEN, tries=2)
    door.check(THERE, 'nope', now=100)
    door.check(THERE, 'nope', now=100)

    assert door.check(THERE, TOKEN, now=100) == 'blocked'
    assert door.check(HERE, TOKEN, now=100) == 'ok'


def test_the_window_slides():
    """A block is not a punishment that has to be served out. The tries fall out of
    the window and the address is answered again."""
    door = Doorman(TOKEN, tries=2, window=300)
    door.check(THERE, 'nope', now=100)
    door.check(THERE, 'nope', now=100)
    assert door.check(THERE, TOKEN, now=200) == 'blocked'

    assert door.check(THERE, TOKEN, now=500) == 'ok'


def test_getting_it_right_clears_the_tally_that_decides():
    """Somebody who mistyped it three times and then pasted it properly should not
    then be a few tries away from being shut out."""
    door = Doorman(TOKEN, tries=4)
    for _ in range(3):
        door.check(HERE, 'nope', now=100)

    assert door.check(HERE, TOKEN, now=100) == 'ok'
    assert [door.check(HERE, 'nope', now=100) for _ in range(3)] == [
        'wrong',
        'wrong',
        'wrong',
    ]
    assert door.check(HERE, TOKEN, now=100) == 'ok'


def test_it_does_not_grow_without_limit():
    """Somebody spraying from a new address every time must not be able to make this
    remember all of them."""
    door = Doorman(TOKEN, tries=3, remember=8)
    for n in range(50):
        door.check('10.0.0.%d' % n, 'nope', now=100)

    assert len(door.wrong) <= 8


def test_the_quietest_address_is_the_one_forgotten():
    """The one still trying is the one worth remembering."""
    door = Doorman(TOKEN, tries=99, remember=3)
    for address in ('a', 'b', 'c'):
        door.check(address, 'nope', now=100)
    door.check('a', 'nope', now=101)  # 'a' is trying again
    door.check('d', 'nope', now=102)  # and 'd' turns up

    assert 'a' in door.wrong
    assert 'b' not in door.wrong


def test_it_says_what_has_been_knocking():
    """So that somebody looking at the page can see it, rather than only the log."""
    door = Doorman(TOKEN, tries=2)
    door.check(THERE, 'nope', now=100)
    door.check(THERE, 'nope', now=100)
    door.check(HERE, TOKEN, now=100)
    state = door.state(now=100)

    assert state['refused'] == 2
    assert state['tries'] == 2
    assert [c['client'] for c in state['clients']] == [THERE]
    assert state['clients'][0]['blocked'] is True


def test_getting_it_right_does_not_clear_the_record_that_is_shown():
    """Two different things. Clearing the deciding tally on success is what keeps a
    mistyped bookmark from becoming a lockout. Clearing the record as well would make
    the record unreadable, because reading it means getting the token right first.
    """
    door = Doorman(TOKEN)
    door.check(HERE, 'nope', now=100)
    door.check(HERE, TOKEN, now=100)
    shown = door.state(now=100)['clients']

    assert [c['client'] for c in shown] == [HERE]
    assert shown[0]['wrong'] == 1
    assert shown[0]['blocked'] is False
    # And the tally that decides is empty, so it is nowhere near a block.
    assert not door._recent(HERE, 100)


def test_the_record_does_not_grow_without_limit_either():
    door = Doorman(TOKEN, remember=8)
    for n in range(50):
        door.check('10.0.0.%d' % n, 'nope', now=100)

    assert len(door.knocking) <= 8
