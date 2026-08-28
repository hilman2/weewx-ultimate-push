#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""A small web interface, on a port of its own.

What it is for. Placing a field is a decision only the person who installed the
sensor can make, and today the whole workflow is: read a log line, paste a line into
weewx.conf, restart, wait for the next upload, read the log again. That is a poor loop
for something with an irreversible failure mode, because the one thing you want to
know before deciding, whether the column already holds somebody else's readings, is
the one thing the log line cannot tell you.

So this shows the decision with everything needed to make it, and writes the answer
where it takes effect on the next upload.

## What it is served by

`weewx.listener`, the same one the readings arrive on, on a second port. That is worth
knowing because it fixes three things:

    Every reply is a 200.  The core listener hardcodes it, and this driver does not
    get to change a file that has to stay identical to the core's. So the API says
    whether a request worked in the body, not in the status.

    There are no response headers of ours.  No cookies, so no sessions. The token
    goes in the query string on the first request and in a header after that.

    It is a second listener rather than a secret path on the first.  The data port
    cannot demand a token, because most of this hardware cannot send one, so an
    interface that can change the field map does not belong on it.

## What protects it

A token, checked here rather than by the listener, and a doorman that stops answering
an address that keeps getting it wrong.

The listener would check a token itself, before any of this runs, which sounds better
and is not: its check happens before anything of ours, so a wrong one would be
answered and forgotten and there would be nothing to count. Counting is the part that
makes a short token sound. So the check is here, `transport.same_secret` does the
comparison in constant time, and `Doorman` keeps the tally.

What that is worth, plainly:

    It is HTTP.  The token is in the URL on the first request, so it is in the browser
    history and in the logs of anything between. On a network you trust that is a
    bounded exposure. Across the internet it is not acceptable without a reverse proxy
    terminating TLS.

    Ten random characters is about sixty bits.  With the doorman allowing ten wrong
    ones every five minutes, working through that would take longer than the sun has
    left. A token somebody thought up rather than generated is a different sum, and
    the doorman is what makes even that impractical from outside.

    Cross-site requests fail, but by accident rather than by design.  The API takes
    JSON with a token header, which a browser will not send cross-origin without a
    preflight, and the core listener answers no OPTIONS. So a page on another site
    cannot drive this one. Worth having, not worth leaning on.

    Anybody who has the token can change the field map.  There are no roles here.

This is a weather station. The point is not to withstand a determined attacker with
your address; it is that a stray scanner, a curious guest and a typo all come to
nothing, and that you can see it happened.
"""

import collections
import json
import logging
import threading
import time
import urllib.parse

from . import columns, protocols, transport

log = logging.getLogger(__name__)

# Paths the interface answers on. Anything else gets the page, so that a bookmark to
# a path this version no longer has still lands somewhere useful.
API = '/api/'

JSON = 'application/json'
HTML = 'text/html; charset=utf-8'

# The shortest token the driver will start with. Ten random characters is about sixty
# bits, which no amount of guessing gets through, and the doorman below is what covers
# a token somebody thought up instead of generating.
SHORTEST_TOKEN = 10

# How many wrong tokens an address may present before it stops being answered, and
# over what span. Generous enough that a mistyped bookmark is not a lockout, small
# enough that guessing is pointless.
TRIES = 10
WINDOW = 300
# The most addresses to keep a tally for. Past this the quietest is forgotten, so that
# somebody spraying from a new address each time cannot grow this without limit.
REMEMBER = 512


class Doorman:
    """Counts wrong tokens per address, and stops answering one that keeps trying.

    Not a lockout with an escalating penalty, and not a delay: a delay holds a thread,
    and a thread is a thing worth more than the attacker's time. An address over the
    limit simply gets nothing back until its tries fall out of the window.

    A right token clears that address's tally, so the one person who mistyped it four
    times and then got it right is not left waiting.
    """

    def __init__(self, token, tries=TRIES, window=WINDOW, remember=REMEMBER):
        self.token = token
        self.tries = tries
        self.window = window
        self.remember = remember
        self.lock = threading.Lock()
        # address -> deque of the times it got the token wrong recently. This is the
        # tally that decides, and a right token clears it.
        self.wrong = collections.OrderedDict()
        # address -> [how many times in all, when last]. This is the record that is
        # shown, and a right token does not clear it.
        #
        # They have to be two things. Clearing the tally on success is what stops the
        # person who mistyped it four times from being one try from a lockout; but if
        # that also cleared the record, the record could never be read, because
        # reading it means getting the token right first.
        self.knocking = collections.OrderedDict()
        self.refused = 0

    def check(self, client, presented, now=None):
        """'ok', 'wrong' or 'blocked' for one attempt."""
        now = time.time() if now is None else now
        with self.lock:
            recent = self._recent(client, now)
            if len(recent) >= self.tries:
                self.refused += 1
                return 'blocked'
        # Compared outside the lock, and in constant time, so that neither the tally
        # nor the clock says anything about how much of the token was right.
        if presented and transport.same_secret(presented, self.token):
            with self.lock:
                self.wrong.pop(client, None)
            return 'ok'
        with self.lock:
            recent = self._recent(client, now)
            recent.append(now)
            self.wrong[client] = recent
            self.wrong.move_to_end(client)
            self._note(client, now)
            self.refused += 1
            if len(recent) == self.tries:
                log.warning("%s has presented a wrong token %d times. It gets no "
                            "answer from the web interface for the next %d seconds.",
                            client, self.tries, self.window)
        return 'wrong'

    def _recent(self, client, now):
        """This address's wrong tokens inside the window. Caller holds the lock."""
        recent = self.wrong.get(client) or collections.deque()
        while recent and now - recent[0] > self.window:
            recent.popleft()
        return recent

    def _note(self, client, now):
        """Add to the record that is shown. Caller holds the lock.

        Bounded the same way the tally is, and by the same reasoning: somebody
        knocking from a new address every time must not be able to make this grow.
        The one still trying is the one kept.
        """
        seen = self.knocking.get(client) or [0, now]
        seen[0] += 1
        seen[1] = now
        self.knocking[client] = seen
        self.knocking.move_to_end(client)
        while len(self.knocking) > self.remember:
            self.knocking.popitem(last=False)
        while len(self.wrong) > self.remember:
            self.wrong.popitem(last=False)

    def state(self, now=None):
        """What to show on the page, so that somebody knocking is visible.

        Takes the clock the same way check() does, so that a test can say when
        without waiting for it.
        """
        now = time.time() if now is None else now
        with self.lock:
            addresses = [
                {'client': client,
                 'wrong': count,
                 'last': last,
                 'blocked': len(self._recent(client, now)) >= self.tries}
                for client, (count, last) in self.knocking.items()
            ]
            refused = self.refused
        return {'refused': refused,
                'clients': sorted(addresses, key=lambda a: -a['last'])[:20],
                'tries': self.tries, 'window': self.window}


class Site:
    """Answers the requests that reach the admin listener.

    Talks to the driver through a small set of methods and does not reach past them:
    `web_overview`, `web_station`, `web_accept`, `web_set_field`, `web_forget` and
    `web_columns`. Everything that needs a lock takes it there, on the driver's side,
    because that is where the state is.
    """

    def __init__(self, driver, doorman):
        self.driver = driver
        self.doorman = doorman

    def answer(self, request):
        """(body, content type) for one request. Never raises."""
        try:
            standing = self.doorman.check(request.client_address,
                                          _presented(request))
            if standing == 'blocked':
                # The black hole. No explanation, no hint that the address is known,
                # and nothing that costs us more than a dictionary lookup.
                return '', 'text/plain'
            if standing == 'wrong':
                if _wants_html(request):
                    return REFUSED_PAGE, HTML
                return _json({'ok': False, 'error': "Wrong token."})
            return self._route(request)
        except Exception as e:
            log.error("The web interface could not answer %s: %s",
                      getattr(request, 'path', '?'), e, exc_info=True)
            return _json({'ok': False, 'error': str(e)})

    def _route(self, request):
        path = (request.path or '/').rstrip('/') or '/'
        if not path.startswith(API.rstrip('/')):
            from .page import PAGE
            return PAGE, HTML

        route = path[len(API.rstrip('/')):].lstrip('/')
        query = dict(urllib.parse.parse_qsl(request.query or ''))

        if request.method == 'GET':
            return self._get(route, query)
        if request.method == 'POST':
            return self._post(route, _body(request))
        return _json({'ok': False, 'error': "%s is not a method this answers to."
                                            % request.method})

    # ---- reading -------------------------------------------------------------

    def _get(self, route, query):
        if route == 'state':
            return _json(self.driver.web_overview())
        if route == 'setup':
            return _json(self.driver.web_setup())
        if route == 'candidates':
            return _json(self.driver.web_candidates())
        if route == 'station':
            found = self.driver.web_station(query.get('ident', ''))
            if found is None:
                return _json({'ok': False, 'error': "No station by that name."})
            return _json(found)
        if route == 'raw':
            return _json({'ok': True,
                          'uploads': self.driver.activity.recent(
                              query.get('ident', ''), transport.redact)})
        if route == 'waiting':
            return _json({'ok': True,
                          'stations': self.driver.activity.unknown_stations(
                              transport.redact)})
        if route == 'columns':
            return _json(self.driver.web_columns(
                query.get('ident', ''), refresh=query.get('refresh') == 'yes'))
        if route == 'catalog':
            return _json(_catalog_of(query.get('protocol', '')))
        return _json({'ok': False, 'error': "No such route: %s" % route})

    # ---- writing -------------------------------------------------------------

    def _post(self, route, body):
        if route == 'create':
            ok, answer = self.driver.web_create(body.get('protocol', ''),
                                                body.get('name', ''))
            return _json({'ok': ok, 'station': answer} if ok
                         else {'ok': False, 'message': answer})
        if route == 'accept':
            ok, message = self.driver.web_accept(
                body.get('ident', ''), body.get('name'), body.get('infer_unknown'))
            return _json({'ok': ok, 'message': message})
        if route == 'field':
            ok, message = self.driver.web_set_field(
                body.get('ident', ''), body.get('raw', ''), body.get('field', ''))
            return _json({'ok': ok, 'message': message})
        if route == 'role':
            ok, message = self.driver.web_role(body.get('ident', ''),
                                               body.get('role', ''))
            return _json({'ok': ok, 'message': message})
        if route == 'forget':
            ok, message = self.driver.web_forget(body.get('ident', ''))
            return _json({'ok': ok, 'message': message})
        return _json({'ok': False, 'error': "No such route: %s" % route})


def _presented(request):
    """The token this request carries, from wherever it put it.

    A browser can only manage the query string on the first request, so the page is
    opened with one there and its own calls send the header afterwards.
    """
    headers = getattr(request, 'headers', None) or {}
    token = headers.get('x-auth-token', '')
    if not token:
        authorization = headers.get('authorization', '')
        if authorization.startswith('Bearer '):
            token = authorization[len('Bearer '):].strip()
    if not token:
        token = dict(urllib.parse.parse_qsl(request.query or '')).get('token', '')
    return token


def _wants_html(request):
    """Whether a person is looking at this, rather than the page's own script."""
    return not (request.path or '').startswith(API.rstrip('/'))


REFUSED_PAGE = ("<!doctype html><meta charset=utf-8>"
                "<title>weewx-ultimate-push</title>"
                "<body style=\"font:15px system-ui;margin:3rem;max-width:32rem\">"
                "<h1 style=\"font-size:1rem\">Wrong token.</h1>"
                "<p>The address for this page ends in <code>?token=</code> and then "
                "the token from the driver section of weewx.conf.</p>"
                "<p style=\"color:#777\">After a few wrong ones this address stops "
                "being answered for a while.</p>")


def _body(request):
    """The JSON a POST carried, or {}."""
    try:
        decoded = json.loads(request.text or '{}')
    except ValueError:
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _json(payload):
    return json.dumps(payload, default=str), JSON


def _catalog_of(name):
    """Every raw name a protocol knows, for the box that offers completions."""
    protocol = protocols.by_name(name)
    if protocol is None:
        return {'ok': False, 'error': "No protocol called '%s'." % name}
    dialect = protocol.dialect({})
    return {'ok': True, 'protocol': name,
            'fields': sorted(set(dialect.fields.values()))}


def schema_fields():
    """The columns the standard schema has, or an empty set without WeeWX."""
    try:
        return columns.schema_fields()
    except Exception:
        return set()


def uptime(since):
    return max(0, int(time.time() - since))


def lan_address():
    """This machine's address on the network it would reach out on.

    A UDP socket is pointed at an address in the documentation range and the kernel is
    then asked which of our addresses it picked. Nothing is sent and nothing has to
    exist at the other end: connect() on a datagram socket only chooses a route.

    Better than asking for the hostname, which on a Debian machine usually answers
    127.0.1.1, and better than making somebody run `ip addr` to find out where their
    own weather station is.
    """
    import socket
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(('192.0.2.1', 9))
        return probe.getsockname()[0]
    except OSError:
        return None
    finally:
        probe.close()


def url(address, port, token):
    """The address to open, as somebody would type it.

    Printed at startup so that nobody has to work out which of their addresses the
    driver ended up on. A listener bound to every interface reports itself as '*',
    which is true and useless.
    """
    host = address if address and address not in ('0.0.0.0', '::', '*') else None
    return 'http://%s:%d/?token=%s' % (host or lan_address() or 'this-machine',
                                       port, token)
