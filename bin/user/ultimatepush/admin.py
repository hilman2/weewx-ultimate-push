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

    The token check is the listener's.  It runs before anything here, in constant
    time, and answers a bad one with a real 403. That is why this is a second
    listener rather than a secret path on the first: a token on the data port would
    lock out the hardware, which mostly cannot send one.

## What protects it

The token, and where the socket is bound. Nothing else, and it is worth being plain
about what that is worth:

    It is HTTP.  The token is in the URL on the first request, so it is in the browser
    history and in the logs of anything between. On a LAN that is a real exposure to
    anybody already on the LAN. Across the internet it is not acceptable without a
    reverse proxy terminating TLS.

    Cross-site requests fail, but by accident rather than by design.  The API takes
    JSON with a token header, which a browser will not send cross-origin without a
    preflight, and the core listener answers no OPTIONS. So a page on another site
    cannot drive this one. That is worth having and is not something to lean on.

    Anybody who has the token can change the field map.  There are no roles here.
"""

import json
import logging
import time
import urllib.parse

from . import VERSION, columns, protocols, transport

log = logging.getLogger(__name__)

# Paths the interface answers on. Anything else gets the page, so that a bookmark to
# a path this version no longer has still lands somewhere useful.
API = '/api/'

JSON = 'application/json'
HTML = 'text/html; charset=utf-8'


class Site:
    """Answers the requests that reach the admin listener.

    Talks to the driver through a small set of methods and does not reach past them:
    `web_overview`, `web_station`, `web_accept`, `web_set_field`, `web_forget` and
    `web_columns`. Everything that needs a lock takes it there, on the driver's side,
    because that is where the state is.
    """

    def __init__(self, driver):
        self.driver = driver

    def answer(self, request):
        """(body, content type) for one request. Never raises."""
        try:
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
        if route == 'accept':
            ok, message = self.driver.web_accept(
                body.get('ident', ''), body.get('name'), body.get('infer_unknown'))
            return _json({'ok': ok, 'message': message})
        if route == 'field':
            ok, message = self.driver.web_set_field(
                body.get('ident', ''), body.get('raw', ''), body.get('field', ''))
            return _json({'ok': ok, 'message': message})
        if route == 'forget':
            ok, message = self.driver.web_forget(body.get('ident', ''))
            return _json({'ok': ok, 'message': message})
        return _json({'ok': False, 'error': "No such route: %s" % route})


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
