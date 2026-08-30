#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""The web interface, as one page.

Everything is in here: no stylesheet to fetch, no script to fetch, no font, no icon.
Partly because a driver has no business shipping an asset pipeline, and partly because
the listener answers one request per connection and closes it, so a page made of eight
files would be eight connections.

The page holds no state of its own worth the name. It asks the API what is true and
draws that, which means a reload after somebody edits the settings file by hand shows
the file rather than what the browser remembered.

The token is read from the query string once and sent as a header afterwards, so it
stays out of the addresses the browser records for the API calls themselves.
"""

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy"
      content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; img-src data:">
<title>weewx-ultimate-push</title>
<!-- The icon is in the page, like everything else here. A page that declares one is
     not asked for /favicon.ico, and that request would arrive without the token and
     be counted against the address by the doorman. An arrow leaving a line: readings
     going up from the console to this machine, which is the whole of what this is. -->
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'><rect width='16' height='16' rx='3.5' fill='%238a4b2a'/><path d='M8 3 11.8 7.2H9.4v3.4H6.6V7.2H4.2z' fill='%23fbfaf8'/><rect x='4.2' y='11.7' width='7.6' height='1.5' rx='.75' fill='%23fbfaf8'/></svg>">
<style>
:root {
  --bg: #fbfaf8; --panel: #fff; --line: #e2ded8; --ink: #24211d;
  --dim: #6d675f; --accent: #8a4b2a; --ok: #2f6b3a; --warn: #8a6a12; --bad: #93301f;
  --code: #f3f0ec;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #17181a; --panel: #1e1f22; --line: #33353a; --ink: #e6e3de;
    --dim: #97938c; --accent: #d99872; --ok: #7fbb8c; --warn: #d7b45c; --bad: #e08d7c;
    --code: #24262a;
  }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--ink);
  font: 15px/1.5 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif; }
code, pre, .mono { font-family: ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace;
  font-size: 13px; }
header { border-bottom: 1px solid var(--line); padding: 14px 20px;
  display: flex; gap: 20px; align-items: baseline; flex-wrap: wrap; }
header h1 { font-size: 16px; margin: 0; font-weight: 600; }
header .meta { color: var(--dim); font-size: 13px; }
main { display: grid; grid-template-columns: 300px 1fr; gap: 0; min-height: calc(100vh - 55px); }
@media (max-width: 800px) { main { grid-template-columns: 1fr; } }
aside { border-right: 1px solid var(--line); padding: 14px; }
@media (max-width: 800px) { aside { border-right: 0; border-bottom: 1px solid var(--line); } }
section { padding: 18px 20px; min-width: 0; }
h2 { font-size: 13px; text-transform: uppercase; letter-spacing: .06em;
  color: var(--dim); margin: 18px 0 8px; font-weight: 600; }
h2:first-child { margin-top: 0; }
.card { background: var(--panel); border: 1px solid var(--line); border-radius: 7px;
  padding: 10px 12px; margin-bottom: 8px; cursor: pointer; }
.card:hover { border-color: var(--accent); }
.card.on { border-color: var(--accent); box-shadow: inset 3px 0 0 var(--accent); }
.card .id { font-weight: 600; word-break: break-all; }
.card .sub { color: var(--dim); font-size: 12px; margin-top: 2px; }
.tabs { display: flex; gap: 2px; border-bottom: 1px solid var(--line); margin-bottom: 16px; }
.tabs button { background: none; border: 0; border-bottom: 2px solid transparent;
  padding: 8px 12px; color: var(--dim); cursor: pointer; font: inherit; }
.tabs button.on { color: var(--ink); border-bottom-color: var(--accent); }
table { border-collapse: collapse; width: 100%; }
th, td { text-align: left; padding: 6px 10px 6px 0; border-bottom: 1px solid var(--line);
  vertical-align: top; }
th { color: var(--dim); font-weight: 600; font-size: 12px; text-transform: uppercase;
  letter-spacing: .04em; }
input[type=text] { background: var(--bg); color: var(--ink); border: 1px solid var(--line);
  border-radius: 5px; padding: 4px 7px; font: inherit; font-size: 13px; width: 100%;
  max-width: 220px; }
input[type=text]:focus { outline: 2px solid var(--accent); outline-offset: -1px; }
button.act { background: var(--panel); color: var(--ink); border: 1px solid var(--line);
  border-radius: 5px; padding: 4px 10px; font: inherit; font-size: 13px; cursor: pointer; }
button.act:hover { border-color: var(--accent); }
pre { background: var(--code); border: 1px solid var(--line); border-radius: 6px;
  padding: 10px; overflow-x: auto; white-space: pre-wrap; word-break: break-all; margin: 0; }
.ok { color: var(--ok); } .warn { color: var(--warn); } .bad { color: var(--bad); }
.dim { color: var(--dim); }
.row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.note { background: var(--panel); border: 1px solid var(--line); border-left: 3px solid var(--warn);
  border-radius: 6px; padding: 10px 12px; margin-bottom: 14px; font-size: 13px; }
.note.bad { border-left-color: var(--bad); }
.upload { margin-bottom: 12px; }
.upload .head { display: flex; justify-content: space-between; gap: 10px;
  font-size: 12px; color: var(--dim); margin-bottom: 4px; }
.setup { max-width: 46rem; }
.step { border: 1px solid var(--line); border-radius: 8px; margin-bottom: 10px;
  background: var(--panel); }
.step > .head { display: flex; gap: 10px; align-items: baseline; padding: 12px 14px; }
.step .mark { font-weight: 700; width: 1.4rem; flex: none; }
.step.done .mark { color: var(--ok); }
.step.todo .mark { color: var(--warn); }
.step.done > .head { color: var(--dim); }
.step .what { font-weight: 600; }
.step .body { padding: 0 14px 14px 38px; }
.step .body p { margin: 0 0 10px; }
.step > .head.shut { cursor: pointer; user-select: none; }
.step > .head.shut:hover .caret { color: var(--accent); }
.step > .head .caret { color: var(--dim); width: 12px; flex: none; }
.pick { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 12px; }
.pick button { background: var(--bg); color: var(--ink); border: 1px solid var(--line);
  border-radius: 6px; padding: 6px 12px; font: inherit; font-size: 13px; cursor: pointer; }
.pick button.on { border-color: var(--accent); background: var(--panel);
  box-shadow: inset 0 -2px 0 var(--accent); }
.settings { border-collapse: collapse; margin-bottom: 10px; }
.settings td { border: 0; padding: 3px 14px 3px 0; }
.settings td:first-child { color: var(--dim); white-space: nowrap; }
.settings td:last-child { font-family: ui-monospace, Menlo, Consolas, monospace;
  font-weight: 600; }
select { background: var(--bg); color: var(--ink); border: 1px solid var(--line);
  border-radius: 5px; padding: 4px 6px; font: inherit; font-size: 13px;
  max-width: 220px; width: 100%; }
select:focus { outline: 2px solid var(--accent); outline-offset: -1px; }
.taken { color: var(--warn); font-size: 12px; }
.newcol { font-size: 12px; margin-top: 4px; }
.newcol code { background: var(--code); padding: 2px 5px; border-radius: 4px; }
.add { display: flex; gap: 6px; margin-top: 10px; flex-wrap: wrap; }
.knock { width: 100%; border-collapse: collapse; margin: 8px 0 2px; font-size: 12px; }
.knock td { padding: 2px 8px 2px 0; border: 0; }
.knock td:nth-child(2) { text-align: right; font-variant-numeric: tabular-nums; }
.knock td:nth-child(3) { color: var(--dim); width: 42%; }
.made { border-left: 3px solid var(--ok); padding-left: 12px; margin: 12px 0 18px; }
.block { margin-bottom: 22px; }
.fold { cursor: pointer; display: flex; gap: 8px; align-items: baseline;
  padding: 7px 0; border-bottom: 1px solid var(--line); user-select: none; }
.fold:hover .caret { color: var(--accent); }
.caret { color: var(--dim); width: 12px; }
.fold .dim { font-size: 12px; }
.agree { display: flex; gap: 8px; align-items: center; margin: 10px 0 4px;
  font-size: 13px; cursor: pointer; }
.agree input { accent-color: var(--accent); }
button.act[disabled] { opacity: .5; cursor: not-allowed; }
button.act[disabled]:hover { border-color: var(--line); }
.waiting { color: var(--dim); font-size: 13px; }
.waiting b { color: var(--warn); }
#flash { position: fixed; right: 16px; bottom: 16px; background: var(--panel);
  border: 1px solid var(--line); border-radius: 7px; padding: 9px 14px; font-size: 13px;
  box-shadow: 0 6px 20px rgba(0,0,0,.13); display: none; max-width: 380px; }
</style>
</head>
<body>
<header>
  <h1>weewx-ultimate-push</h1>
  <span class="meta" id="meta">loading</span>
</header>
<main>
  <aside>
    <div id="door"></div>
    <h2>Stations</h2>
    <div id="stations"></div>
    <div class="add">
      <button class="act" id="addstation">Add a station</button>
    </div>
    <h2>Waiting to be let in</h2>
    <div id="waiting"><div class="dim" style="font-size:13px">Nothing refused.</div></div>
  </aside>
  <section>
    <div class="tabs">
      <button data-tab="setup">Setup</button>
      <button data-tab="stations">Stations</button>
      <button data-tab="fields" class="on">Fields</button>
      <button data-tab="raw">Raw uploads</button>
      <button data-tab="columns">Database columns</button>
    </div>
    <div id="body"><p class="dim">Loading.</p></div>
  </section>
</main>
<div id="flash"></div>
<script>
'use strict';
var TOKEN = new URLSearchParams(location.search).get('token') || '';

/* Where this page is being served from, which is not always the root. Behind a
   reverse proxy it is whatever path the proxy puts it under, and the API has to be
   asked for relative to that, or every call lands on whatever else the proxy serves
   from the root. A trailing file name is dropped and a missing trailing slash added,
   so /secret, /secret/ and /secret/index.html all come to the same thing. */
var BASE = location.pathname.replace(/[^/]*\\.[^/]*$/, '');
if (BASE.charAt(BASE.length - 1) !== '/') BASE += '/';

var chosen = null, tab = 'fields', state = null, detail = null;
var fieldsView = null, folded = {}, adding = false;
var setup = null, picked = null, watching = null, candidates = null;
/* Every station this driver knows, including the ones that have never uploaded.
   Read for the Stations tab, and for the one question the setup form cannot answer
   on its own: whether there is already a main station to be moved aside. */
var stationList = null;
/* A main station about to be taken over, while the page explains what that does.
   Held here rather than in the DOM so that a redraw does not lose the question. */
var pending = null, editing = null, pendingDraw = false, unfolded = {};
/* The options a driver's author ruled off as rarely needing attention start
   folded, which is what ruling them off meant. */
folded.driverrest = true;

function busy() {
  /* Somebody is in the middle of something on this page. A redraw would empty the
     field they are typing a name into, or clear the box they ticked to arm a change
     that cannot be taken back. Whatever the poll found can wait for a tick or two:
     nothing here is news that goes stale. */
  if (pending) return true;
  var focused = document.activeElement;
  if (!focused || (focused.tagName !== 'INPUT' && focused.tagName !== 'SELECT')) {
    return false;
  }
  var body = document.getElementById('body');
  return !!(body && body.contains(focused));
}

function api(route, body) {
  var opts = { headers: { 'X-Auth-Token': TOKEN } };
  if (body) {
    opts.method = 'POST';
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  return fetch(BASE + 'api/' + route, opts).then(function (r) { return r.json(); });
}

function flash(text, bad) {
  var el = document.getElementById('flash');
  el.textContent = text;
  el.style.borderColor = bad ? 'var(--bad)' : 'var(--line)';
  el.style.display = 'block';
  clearTimeout(flash.timer);
  flash.timer = setTimeout(function () { el.style.display = 'none'; }, 4500);
}

function esc(s) {
  return String(s === null || s === undefined ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function ago(t) {
  if (!t) return 'never';
  var s = Math.max(0, Math.round(Date.now() / 1000 - t));
  if (s < 60) return s + 's ago';
  if (s < 3600) return Math.round(s / 60) + 'm ago';
  if (s < 86400) return Math.round(s / 3600) + 'h ago';
  return Math.round(s / 86400) + 'd ago';
}

function copy(text, what) {
  navigator.clipboard.writeText(text).then(
    function () { flash('Copied ' + what + '.'); },
    function () { flash('The browser would not let this page copy.', true); });
}

/* ---------------------------------------------------------------- overview */

function loadState() {
  return api('state').then(function (s) {
    state = s;
    document.getElementById('meta').textContent =
      'version ' + s.version + ' \\u00b7 up ' + Math.round(s.uptime / 60) + ' min' +
      ' \\u00b7 listening on ' + s.ports.join(', ') +
      ' \\u00b7 ' + s.protocols.join(', ');
    drawDoor(s.door);
    drawSidebar();
  });
}

function drawDoor(door) {
  var box = document.getElementById('door');
  if (!door || !door.clients.length) { box.innerHTML = ''; return; }
  box.innerHTML = '<div class="note"><b>' + door.refused +
    ' request(s) with the wrong token.</b> An address that gets it wrong ' +
    door.tries + ' times in ' + door.window + ' seconds stops being answered.<br>' +
    door.clients.map(function (c) {
      return esc(c.client) + ': ' + c.wrong + ' wrong, last ' + ago(c.last) +
        (c.blocked ? ' <b>(blocked)</b>' : '');
    }).join('<br>') + '</div>';
}

function waitingCards() {
  /* Stations that are set up and have not been heard from. They are in no other
     list here, because every other list is built from what has arrived, and a
     station somebody has just set up has not arrived. Leaving them out makes
     setting one up look like it did nothing at all. */
  if (!stationList) return '';
  var heard = {};
  state.stations.forEach(function (s) { heard[s.ident] = true; });
  return stationList.stations.filter(function (s) {
    return !heard[s.ident] && !s.adopted;
  }).map(function (s) {
    return '<div class="card" data-goto="stations">' +
      '<div class="id">' + esc(s.name || s.ident) + '</div>' +
      '<div class="sub">' + esc(s.station_type || s.protocol || 'kind unknown') +
      (s.role === 'extra' ? ' \\u00b7 extra ' + (s.channel || '?')
                          : ' \\u00b7 main station') + '</div>' +
      '<div class="sub warn">' + (s.station_type
        ? 'Nothing read from it yet.'
        : 'Waiting for its first upload.') + '</div></div>';
  }).join('');
}

function movedPicker(ident) {
  /* A cheap radio sensor picks a new number when its batteries are changed, and
     then turns up here looking like a sensor nobody has ever seen. It is not one:
     it already has a name, a role, a channel and columns of its own, and letting it
     in as a second station would leave all of that behind with the old number.

     Only stations this driver set up are offered. One named in weewx.conf is that
     file's to change, and one that is a hosted driver has no identity to move. */
  var mine = (stationList ? stationList.stations : []).filter(function (s) {
    return s.editable && !s.station_type;
  });
  if (!mine.length) return '';
  return '<select>' +
    '<option value="">a sensor that changed its id\u2026</option>' +
    mine.map(function (s) {
      return '<option value="' + esc(s.ident) + '">' + esc(s.name || s.ident) +
        '</option>';
    }).join('') + '</select>' +
    '<button class="act" data-moved="' + esc(ident) + '">Move it here</button>';
}

function drawSidebar() {
  var box = document.getElementById('stations');
  var waiting = waitingCards();
  if (!state.stations.length) {
    box.innerHTML = waiting || '<div class="dim" style="font-size:13px">Nothing has ' +
      'uploaded yet.</div>';
  } else {
    box.innerHTML = waiting + state.stations.map(function (s) {
      return '<div class="card' + (s.ident === chosen ? ' on' : '') +
        '" data-ident="' + esc(s.ident) + '">' +
        '<div class="id">' + esc(s.name || s.ident) + '</div>' +
        '<div class="sub">' + esc(s.protocol || '?') +
        (s.dialect && s.dialect !== s.protocol ? ' \\u00b7 ' + esc(s.dialect) : '') +
        (s.role === 'extra' ? ' \\u00b7 extra ' + (s.channel || '?')
                            : ' \\u00b7 main station') +
        ' \\u00b7 ' + s.field_count + ' fields \\u00b7 ' + ago(s.last_seen) +
        '</div>' +
        (s.undecided_count ? '<div class="sub warn">' + s.undecided_count +
          ' waiting for a placement</div>' : '') +
        (s.held_back ? '<div class="sub warn">Nothing recorded: waiting for the main ' +
          'station, which has not uploaded since this driver started.</div>' : '') +
        '</div>';
    }).join('');
  }
  var waiting = document.getElementById('waiting');
  if (!state.waiting.length) {
    waiting.innerHTML = '<div class="dim" style="font-size:13px">Nothing refused.</div>';
  } else {
    waiting.innerHTML = state.waiting.map(function (w, i) {
      /* The readings, because the decision is whether to let this into your
         database, and an address cannot tell your own new console from a
         stranger's. Nine degrees and ninety per cent can. */
      var sample = w.sample || {};
      var rows = (sample.readings || []).map(function (r) {
        return '<tr><td class="mono">' + esc(r.raw) + '</td><td>' + esc(r.value) +
          '</td><td>' + (r.field ? '\u2192 ' + esc(r.field) : '') + '</td></tr>';
      }).join('');
      return '<div class="card"><div class="id">' + esc(w.ident) + '</div>' +
        '<div class="sub">' + esc(w.protocol || '?') + ' from ' + esc(w.client) +
        ' \u00b7 ' + w.uploads + ' seen \u00b7 ' + ago(w.last_seen) + '</div>' +
        (rows ? '<table class="knock">' + rows + '</table>'
              : '<div class="dim" style="font-size:12px;margin-top:6px">' +
                'Nothing readable in it.</div>') +
        '<div class="row" style="margin-top:8px">' +
        '<input type="text" placeholder="name it" data-name="' + esc(w.ident) + '">' +
        '<button class="act" data-accept="' + esc(w.ident) + '">Let in</button>' +
        '<button class="act" data-knock="' + i + '">All of it</button></div>' +
        '<div id="knockraw' + i + '" style="display:none">' +
        '<div class="row" style="margin-top:8px;justify-content:flex-end">' +
        '<button class="act" data-knockcopy="' + i + '">Copy</button></div>' +
        '<pre id="knocktext' + i + '">' + esc(sample.text || '') + '</pre></div>' +
        '</div>';
    }).join('');
  }
}

function loadCandidates() {
  /* The same answer for every row, so it is asked for once. */
  if (candidates) return Promise.resolve(candidates);
  return api('candidates').then(function (c) { candidates = c; return c; });
}

function loadStations() {
  return api('stations').then(function (d) { stationList = d; return d; });
}

function mainStation() {
  /* The one station whose readings go where they belong, or null while nothing has
     said yet. The whole of what the setup form needs to know before it offers to
     make something else the main one. */
  if (!stationList) return null;
  var found = stationList.stations.filter(function (s) { return s.is_main; });
  return found.length ? found[0] : null;
}

function stationName(s) {
  return s.name || s.ident;
}

function freeChannel() {
  var taken = (stationList && stationList.taken) || [];
  var limit = (stationList && stationList.channels) || 8;
  for (var n = 1; n <= limit; n++) {
    if (taken.indexOf(n) < 0) return n;
  }
  return null;
}

/* ---------------------------------------------------------------- setting up */

function loadSetup(then) {
  return api('setup').then(function (s) {
    var was = setup && setup.next;
    setup = s;
    document.querySelector('[data-tab="setup"]').textContent =
      s.done ? 'Setup' : 'Setup \u00b7 ' + s.steps.filter(function (x) {
        return !x.done && !x.optional; }).length;
    /* The first visit lands on what there is to do, not on an empty field table. */
    if (!s.done && was === undefined) tab = 'setup';
    /* Something arrived while we were waiting. Show it, once the page is not in
       the middle of being used. */
    if (was && was !== s.next) pendingDraw = true;
    if (pendingDraw && !busy()) { pendingDraw = false; drawSidebar(); draw(); }
    if (then) then();
  });
}

function stepFor(id) {
  if (!setup) return null;
  return setup.steps.filter(function (s) { return s.id === id; })[0] || null;
}

function addingBox() {
  /* Setting up another station is not a step in a checklist: the checklist is
     finished, and this is a thing somebody wants to do anyway. So it appears when
     asked for, above the checklist, and goes away on leaving the tab. */
  var hardware = stepFor('hardware');
  if (!adding || !hardware || !hardware.protocols) return '';
  /* While that step is still open the checklist is already showing this, and two
     protocol pickers on one page is worse than none. */
  if (!hardware.done) return '';
  return '<div class="step todo"><div class="head"><span class="mark">\\u25cf</span>' +
    '<span class="what">Set up another station</span></div>' +
    '<div class="body">' + hardwareBody(hardware) + '</div></div>';
}

function drawSetup(box) {
  if (!setup) { box.innerHTML = '<p class="dim">Loading.</p>'; return; }
  box.innerHTML = '<div class="setup">' +
    addingBox() +
    (setup.done && !adding
      ? '<p class="ok">Everything is set up. This page stays here as a check.</p>'
      : '') +
    setup.steps.map(function (s) {
      var open = !s.done && s.id === setup.next;
      return '<div class="step ' + (s.done ? 'done' : 'todo') + '">' +
        '<div class="head"><span class="mark">' + (s.done ? '\u2713' : '\u25cf') +
        '</span><span class="what">' + esc(s.title) + '</span></div>' +
        (open ? '<div class="body">' + stepBody(s) + '</div>' : '') +
        '</div>';
    }).join('') + '</div>';
  if (!setup.done) watch();
}

function stepBody(s) {
  var html = s.detail ? '<p>' + esc(s.detail) + '</p>' : '';
  if (s.id === 'hardware') return html + createdBody(s.created) + hardwareBody(s);
  if (s.id === 'refused') {
    return html + s.stations.map(function (w) {
      return '<div class="row" style="margin-bottom:6px">' +
        '<span class="mono">' + esc(w.ident) + '</span>' +
        '<span class="dim">' + esc(w.protocol || '?') + ' from ' + esc(w.client) +
        '</span><input type="text" placeholder="name it" data-name="' +
        esc(w.ident) + '"><button class="act" data-accept="' + esc(w.ident) +
        '">Let in</button>' + movedPicker(w.ident) +
        '<button class="act" data-notmine="' + esc(w.ident) +
        '">Not mine</button>' +
        (w.uploads > 1 ? '<span class="dim">heard ' + w.uploads + ' times</span>'
                       : '') + '</div>';
    }).join('');
  }
  if (s.id === 'placements') {
    return html + '<button class="act" data-goto="fields">Place them</button>';
  }
  if (s.id === 'sharing') {
    return html + '<table><thead><tr><th>Reading</th><th>Wanted by</th>' +
      '<th>Held by</th></tr></thead>' +
      '<tbody>' + s.fields.map(function (f) {
        return '<tr><td class="mono">' + esc(f.field) + '</td><td>' +
          esc(f.stations.join(', ')) + '</td><td>' +
          (f.owner ? esc(f.owner) : '<span class="dim">nobody</span>') +
          '</td></tr>';
      }).join('') + '</tbody></table>' +
      '<button class="act" data-goto="fields">Give them fields of their own</button>';
  }
  if (s.id === 'columns') {
    return html + '<button class="act" data-goto="columns">Show the commands</button>';
  }
  if (s.id === 'location') {
    return html + '<pre>' + esc(s.block || '') + '</pre>';
  }
  return html;
}

function createBox(one) {
  /* Only hardware whose upload path is yours to choose can be set up in advance.
     The rest has to be heard first, and says so. The protocol is the one picked
     above: naming a station here and picking a kind there are one choice, and two
     places to make it is one too many. */
  if (!one.can_create) {
    /* Three reasons, and saying the wrong one is worse than saying none: a Tempest
       has no upload path at all, and a Weather Underground console has one that
       every console of its kind shares. */
    var why = one.how === 'point'
      ? 'Its path is fixed in the firmware, and every console of its kind uses the ' +
        'same one, so this driver cannot tell them apart until one uploads.'
      : (one.enabled === false
        ? 'Switch it on first.'
        : 'There is nothing to point here and nothing to name: it is recognised ' +
          'from what it sends.');
    return '<p class="dim" style="margin-top:8px">Nothing to name yet. ' + why +
      ' It shows up as something to let in once it has been heard.</p>';
  }
  if (pending && pending.what === 'create') return confirmBox();
  return '<div class="add">' +
    '<input type="text" id="newname" placeholder="name this station">' +
    roleSelect('newrole', mainStation() ? 'extra' : 'main') +
    '<button class="act" id="create" data-proto="' + esc(one.name) +
    '">Set it up</button></div>' +
    '<p class="dim" style="margin-top:8px">The path it gets is how the driver knows ' +
    'which station an upload is from, and it is a secret: a PASSKEY can be read off ' +
    'anybody\\u2019s upload and repeated.</p>' +
    roleNote();
}

function roleSelect(id, chosenRole) {
  /* Two answers, so a picker. The main station's readings go to outTemp and the
     rest, which is what a report reads. Everything else is a sensor beside it, and
     gets a channel of its own. */
  return '<select id="' + id + '">' +
    '<option value="main"' + (chosenRole === 'main' ? ' selected' : '') +
    '>main station</option>' +
    '<option value="extra"' + (chosenRole === 'extra' ? ' selected' : '') +
    '>extra sensor</option></select>';
}

function roleNote() {
  var main = mainStation();
  if (!main) {
    return '<p class="dim">Nothing is the main station yet, so this one is it: its ' +
      'readings go to outTemp, barometer and the rest.</p>';
  }
  var channel = freeChannel();
  return '<p class="dim"><b>' + esc(stationName(main)) + '</b> is the main station. ' +
    'An extra sensor beside it gives its temperature and humidity to ' +
    (channel ? 'extraTemp' + channel + ' and extraHumid' + channel
             : 'a channel of its own') +
    ', and its wind, rain and pressure have nowhere to go and are dropped.</p>';
}

function confirmBox() {
  /* The two things on this page that reach backwards rather than forwards.
     Everything else takes effect from the next upload and can be put back; these
     leave a column holding one sensor before a moment and something else after it,
     and no later click separates them again. So both are said in full, with the
     numbers out of the archive rather than a general warning, and asked for twice. */
  var found = pending.found || {};
  var taking = found.taking_from;
  var columns = found.columns || [];
  var html = '<div class="note bad">';

  if (taking) {
    html += '<p><b>' + esc(pending.name) + '</b> would become the main station, and ' +
      '<b>' + esc(taking.name) + '</b> would stop being it.</p>' +
      '<p>From its next upload, <b>' + esc(taking.name) + '</b> is an extra sensor' +
      (taking.channel
        ? ' on channel ' + taking.channel + ': its temperature and humidity go to ' +
          'extraTemp' + taking.channel + ' and extraHumid' + taking.channel +
          ' instead of outTemp and outHumidity'
        : '') +
      '. Its wind, rain and pressure have nowhere of their own to go, and are not ' +
      'recorded at all from then on.</p>';
  }

  if (columns.length) {
    html += '<p>These columns already hold readings, and this station would write ' +
      'into them:</p><table class="settings"><tbody>' +
      columns.slice(0, 8).map(function (c) {
        return '<tr><td class="mono">' + esc(c.field) + '</td><td>' +
          c.count + ' reading' + (c.count === 1 ? '' : 's') +
          ', last on ' + esc(c.last) + '</td></tr>';
      }).join('') + '</tbody></table>' +
      (columns.length > 8
        ? '<p class="dim">and ' + (columns.length - 8) + ' more.</p>' : '') +
      '<p>Those readings came from somewhere: an older console, another driver, an ' +
      'import. If this is the same weather station in the same place, writing on is ' +
      'exactly right and the series carries on. If it is a different sensor, the ' +
      'column ends up holding two of them, and afterwards nothing can say which ' +
      'reading came from which.</p>';
  } else if (found.checked === false) {
    html += '<p>The archive database could not be read, so whether these columns ' +
      'already hold readings is not known here. It is worth looking before saying ' +
      'yes.</p>';
  }

  html += '<p>What is already in the archive stays exactly where it is. Nothing ' +
    'here rewrites a row, and nothing here can separate two sensors that have ' +
    'shared a column.</p>' +
    '<p><b>Copy your archive database first.</b> For SQLite that is the .sdb file, ' +
    'with WeeWX stopped. For MySQL, a mysqldump.</p>' +
    '<label class="agree"><input type="checkbox" id="agreed"> ' +
    'I have a copy of the archive database.</label>' +
    '<div class="add"><button class="act" id="doconfirm" disabled>' +
    esc(pending.button) + '</button>' +
    '<button class="act" id="noconfirm">Leave it alone</button></div></div>';
  return html;
}

function inTheWay(found) {
  /* Whether there is anything here somebody has to answer for. Both halves reach
     the archive rather than only the settings file, so either one is enough. */
  return !!(found && found.ok &&
            (found.taking_from || (found.columns && found.columns.length)));
}

function askFirst(what) {
  /* What this would land on, from the driver, before anything is written. The page
     could work some of it out on its own and cannot work out the archive, so it asks
     for all of it in one place: two answers to the same question is one too many. */
  var query = 'before?protocol=' + encodeURIComponent(what.protocol || '') +
    '&role=' + encodeURIComponent(what.role || '') +
    (what.channel ? '&channel=' + what.channel : '') +
    (what.ident ? '&ident=' + encodeURIComponent(what.ident) : '');
  return api(query);
}


function settingsTable(one) {
  return (one.settings.length
    ? '<p>Put these in:</p><table class="settings">' +
      one.settings.map(function (kv) {
        return '<tr><td>' + esc(kv[0]) + '</td><td>' + esc(kv[1]) + '</td></tr>';
      }).join('') + '</table>'
    : '') +
    one.notes.map(function (n) {
      /* An indented note is a thing to paste, not a thing to read. */
      return n.indexOf('    ') === 0
        ? '<pre>' + esc(n.replace(/^ {4}/gm, '')) + '</pre>'
        : '<p class="dim">' + esc(n) + '</p>';
    }).join('');
}

function createdBody(made) {
  /* What to type into the console, right here, for a station that has just been
     set up. The Stations tab keeps this for good and is where somebody comes back
     to it a year later; this is the one moment it is also needed on this page,
     because naming a station is what gives it the path, and being told to go and
     look somewhere else for the thing you just asked for reads as nothing having
     happened. */
  if (!made || !made.length) return '';
  return '<div class="made">' + made.map(function (m) {
    return '<p><b>' + esc(m.name) + '</b> is set up and waiting for its first ' +
      'upload. Put this into the console:</p>' +
      (m.settings ? settingsTable(m.settings) : '') +
      '<p class="dim">The path is what tells this station apart from the others, ' +
      'so it is a secret: anybody who can post to it can write into this ' +
      'station’s columns. It is on the Stations tab too, for when the console ' +
      'has to be set up again.</p>';
  }).join('') +
    '<p class="waiting"><b>Waiting for the first upload.</b> This page notices by ' +
    'itself, so you can leave it open.</p>' +
    '<button class="act" data-goto="stations">Show the stations</button>' +
    '</div>';
}

/* What each group of hardware asks of the person setting it up. The order is the
   order somebody meets them: choose an address and type it in, or plug it in and
   fill in the port, or change something on the network and wait. */
var GROUPS = [
  ['point', 'You point it at this machine',
   'Choose an address here and type it into the app that configures the console.'],
  ['fetch', 'This machine reads it',
   'On a cable, on USB, or somewhere on the network. Nothing has to find its way ' +
   'here: the driver goes and gets the readings.'],
  ['arrives', 'It turns up on its own',
   'There is nowhere to type an address. It broadcasts, or its firmware holds ' +
   'the server name and only a DNS entry on your network can move it. Make that ' +
   'change and it appears below, waiting to be let in.']
];

function hardwareBody(s) {
  /* One list, whatever the hardware is. "Polled" and "uploads" is a distinction
     this driver has and its user does not: they have a weather station. What they
     do have to know is what to do next, which is what the groups say. */
  if (!ways) { loadWays(); return '<p class="dim">Loading.</p>'; }
  var one = wayFor(picked) || ways.ways[0];
  if (!one) return '<p class="dim">No hardware this driver can read.</p>';
  picked = wayKey(one);
  return GROUPS.map(function (g) { return groupOfWays(g, one); }).join('') +
    '<p class="dim">' + esc(one.hardware) + '</p>' +
    (one.kind === 'driver' ? fetchBody(one)
      : (one.how === 'fetch' ? askBody(one) : pointBody(one)));
}

function wayKey(one) {
  return one.kind + ':' + one.name;
}

function wayFor(key) {
  if (!ways || !key) return null;
  var found = null;
  ways.ways.forEach(function (one) { if (wayKey(one) === key) found = one; });
  return found;
}

function groupOfWays(group, chosen) {
  var mine = ways.ways.filter(function (one) { return one.how === group[0]; });
  if (!mine.length) return '';
  return '<p class="dim" style="margin-top:10px"><b>' + esc(group[1]) + '</b> ' +
    esc(group[2]) + '</p><div class="pick">' +
    mine.map(function (one) {
      var key = wayKey(one);
      var why = one.problem ? ' \u2014 ' + esc(one.problem)
        : (one.taken ? ' \u2014 already set up'
          : (one.enabled === false ? ' \u2014 not switched on' : ''));
      return '<button data-pick="' + esc(key) + '"' +
        (key === wayKey(chosen) ? ' class="on"' : '') +
        (one.problem || one.taken ? ' disabled' : '') + '>' +
        esc(one.label) + why + '</button>';
    }).join('') + '</div>';
}

function pointBody(one) {
  /* Nothing to put into a console until there is something to put in. Naming the
     station is what makes its path, and showing the address and the port before
     that invites somebody to type those in, reach the path, and use the driver's
     general one instead. Then the console uploads as a stranger and the station
     they made sits there having never been heard from.

     Hardware that cannot be given a path of its own is the other way round: there
     is nothing to name and pointing it here is the whole of it, so its settings
     are what this has to show. */
  var off = one.enabled === false
    ? '<p class="dim">This driver is not listening for it yet. What that takes is ' +
      'below; it needs a restart.</p>'
    : '';
  if (one.can_create) {
    return off +
      '<p class="dim">Name it first. That is what gives it an upload path of its ' +
      'own, and the settings to type into the console appear once it has one.</p>' +
      createBox(one);
  }
  return off + settingsTable(one) +
    (one.enabled === false
      ? ''
      : '<p class="waiting"><b>Waiting for the first upload.</b> This page notices ' +
        'by itself, so you can leave it open.</p>') +
    createBox(one);
}

function fetchBody(one) {
  /* The fields are the driver's own, from its configuration editor, which is what
     weectl station reconfigure asks with. Nothing here keeps a second copy of them. */
  formFields = one.fields;
  return driverForm(
    one.fields, formValues || {}, ways.ports, 'data-hostedopt', one.about
  ) +
    '<table class="settings"><tr><th>role</th><td>' +
    hostedRoleSelect(mainStation() ? 'extra' : 'main') + '</td></tr>' +
    '<tr><th>name</th><td><input data-hostedname value="' + esc(one.name) + '"></td>' +
    '</tr></table>' +
    '<p><button class="act" data-hostedadd="' + esc(one.name) +
    '">Try it and set it up</button></p>' +
    '<p class="dim">The driver is opened before anything is saved. If the port is ' +
    'not there, nothing is written and the reason is shown here.</p>' + roleNote();
}

function askBody(one) {
  /* Hardware with nowhere to type an address into. Nothing is set on it at all, so
     the whole of the form is where to find it and how often to ask. And that is the
     whole of the station too: what answered is what was asked, so there is nothing
     to recognise, nothing to learn and nothing to let in afterwards. */
  return '<table class="settings">' +
    '<tr><th>address</th><td><input data-askaddr placeholder="1.2.3.4" size="24">' +
    '</td></tr>' +
    '<tr><th>asked every</th><td><input data-askevery value="60" size="5"> seconds' +
    '</td></tr>' +
    '<tr><th>role</th><td>' + hostedRoleSelect(mainStation() ? 'extra' : 'main') +
    '</td></tr>' +
    '<tr><th>name</th><td><input data-askname value="' + esc(one.name) + '"></td>' +
    '</tr></table>' +
    (one.notes || []).map(function (note) {
      return '<p class="dim">' + esc(note) + '</p>';
    }).join('') +
    '<p><button class="act" data-askadd="' + esc(one.name) +
    '">Ask it and set it up</button></p>' +
    '<p class="dim">It is asked once before anything is saved. If nothing answers ' +
    'at that address, or something answers that is not a ' + esc(one.label) +
    ', nothing is written and the reason is shown here.</p>' + roleNote();
}

function driverForm(fields, values, ports, attribute, about) {
  /* One row per option, in the order the driver's own stanza has them, because that
     order is somebody's idea of which matter most: a Vantage names the connection
     type and the port first and rules off eleven that rarely need attention. */
  var keys = Object.keys(fields || {});
  if (!keys.length) {
    return '<p class="dim">This driver describes no settings of its own. ' +
      'Whatever it needs goes in its own section, as its documentation says.</p>';
  }
  var now = function (key) {
    var field = fields[key];
    return values && values[key] !== undefined ? values[key] : field.value;
  };
  var applies = function (key) {
    /* A Vantage takes a port or a host and never both, and says so in its own
       configuration editor. Showing the one that does not apply is showing a
       setting that will be ignored. */
    var when = fields[key].when;
    if (!when || !fields[when.field]) return true;
    return when.values.indexOf(now(when.field)) >= 0;
  };
  var row = function (key) {
    var field = fields[key];
    return '<tr><th>' + esc(key) + '</th><td>' +
      driverField(key, field, now(key), ports, attribute) +
      ((field.help || []).length
        ? '<div class="dim" style="font-size:12px;margin-top:2px">' +
          field.help.map(esc).join('<br>') + '</div>'
        : '') +
      '</td></tr>';
  };
  var shown = keys.filter(function (key) {
    return !fields[key].rarely && applies(key);
  });
  var rest = keys.filter(function (key) {
    return fields[key].rarely && applies(key);
  });
  return (about ? '<p class="dim">' + esc(about) + '</p>' : '') +
    '<table class="settings">' + shown.map(row).join('') + '</table>' +
    (rest.length
      ? '<p><button data-fold="driverrest">' +
        (folded.driverrest ? '\u25b8' : '\u25be') + ' ' + rest.length +
        ' settings the driver\u2019s author says rarely need attention</button></p>' +
        (folded.driverrest
          ? ''
          : '<table class="settings">' + rest.map(row).join('') + '</table>')
      : '');
}

function driverField(key, field, value, ports, attribute) {
  /* A list where the driver takes one of a few values, the devices this machine
     actually has where it wants a serial port, and a text box otherwise. Every list
     keeps a way to type something else: the choices are a convenience, and a
     convenience must not be able to refuse a value the driver would have taken.
     And a way back, because stepping out of the list is not a decision anybody
     should have to reload the page to undo. */
  if (typedBy[key]) {
    return '<input ' + attribute + '="' + esc(key) + '" value="' + esc(value) +
      '"> <button data-relist="' + esc(key) + '">choose from the list</button>';
  }
  if (field.kind === 'fixed') {
    /* One value, so there is nothing to choose. A box here would invite somebody
       to type something the driver raises on. */
    return '<b>' + esc(field.choices[0].label) + '</b>' +
      '<input type="hidden" ' + attribute + '="' + esc(key) + '" value="' +
      esc(field.choices[0].value) + '">';
  }
  var options = [];
  if (field.kind === 'choice') {
    options = field.choices;
  } else if (field.kind === 'port') {
    options = (ports || []).map(function (port) {
      return { value: port.value, label: port.label };
    });
    if (!options.length) {
      return '<input ' + attribute + '="' + esc(key) + '" value="' + esc(value) +
        '">' + '<div class="dim" style="font-size:12px">Nothing serial is plugged ' +
        'into this machine, or this is not a machine with /dev. Type the device ' +
        'name.</div>';
    }
  } else {
    return '<input ' + attribute + '="' + esc(key) + '" value="' + esc(value) + '">';
  }
  var known = options.some(function (o) { return o.value === value; });
  return '<select ' + attribute + '="' + esc(key) + '" data-freetext>' +
    options.map(function (o) {
      return '<option value="' + esc(o.value) + '"' +
        (o.value === value ? ' selected' : '') + '>' + esc(o.label) + '</option>';
    }).join('') +
    (known ? '' : '<option value="' + esc(value) + '" selected>' + esc(value) +
      '</option>') +
    '<option value="__other__">something else\u2026</option></select>';
}

function watch() {
  /* While anything is outstanding, look more often than the fifteen seconds the
     rest of the page settles for. Somebody is standing at their console.

     Looking is all it does. Redrawing on every tick would take a half-typed station
     name out of the field somebody is typing it into, and the tick out of the box
     that arms a change nothing can undo. loadSetup redraws when something actually
     changed, and waits until the field is free. */
  if (watching) return;
  watching = setInterval(function () {
    if (setup && setup.done) { clearInterval(watching); watching = null; return; }
    loadSetup();
  }, 5000);
}

/* ---------------------------------------------------------------- a station */

function choose(ident) {
  chosen = ident;
  drawSidebar();
  draw();
}

function draw() {
  var box = document.getElementById('body');
  if (tab === 'setup') return drawSetup(box);
  if (tab === 'stations') return drawStations(box);
  if (tab === 'fields') {
    box.innerHTML = '<p class="dim">Loading.</p>';
    return drawFields(box);
  }
  if (!chosen) {
    box.innerHTML = '<p class="dim">Pick a station.</p>';
    return;
  }
  box.innerHTML = '<p class="dim">Loading.</p>';
  if (tab === 'raw') return drawRaw(box);
  return drawColumns(box);
}

function show(which) {
  if (which !== 'setup') adding = false;
  tab = which;
  document.querySelectorAll('.tabs button').forEach(function (b) {
    b.classList.toggle('on', b.dataset.tab === tab);
  });
  draw();
}

function hasColumn(name) {
  return !candidates || !candidates.present || candidates.present.indexOf(name) >= 0;
}

function holderOf(name) {
  return fieldsView && fieldsView.holders ? fieldsView.holders[name] : null;
}

function heldElsewhere(name, s, f) {
  /* Somebody else's, where somebody else is another station or another reading of
     this one. A column takes one answer. */
  var who = holderOf(name);
  if (!who) return null;
  if (who.ident === s.ident && who.raw === f.raw) return null;
  return who;
}

function noteFor(name, s, f) {
  var who = heldElsewhere(name, s, f);
  if (who) return ' \\u2014 ' + (who.name || who.ident) + '/' + who.raw;
  if (!hasColumn(name)) return ' \\u2014 new column';
  return '';
}

function chooser(f, s) {
  /* Where this reading could go. The ones that measure the same thing first: a wind
     speed offered as a home for a temperature is worse than no suggestion, because
     somebody will pick it.

     Numbered families run past the end of the schema, so extraTemp12 is here even
     though no database has a column for it. That is said in the option, and the
     column is one button away. */
  var fits = (candidates.groups[f.group] || []).slice();
  var others = [];
  Object.keys(candidates.groups).forEach(function (g) {
    if (g !== f.group) others = others.concat(candidates.groups[g]);
  });
  others = others.concat(candidates.ungrouped);

  function option(name) {
    return '<option value="' + esc(name) + '"' +
      (name === f.field ? ' selected' : '') + '>' + esc(name) +
      esc(noteFor(name, s, f)) + '</option>';
  }

  var here = f.field && fits.indexOf(f.field) < 0 && others.indexOf(f.field) < 0
    ? '<option value="' + esc(f.field) + '" selected>' + esc(f.field) +
      esc(noteFor(f.field, s, f)) + '</option>'
    : '';
  var settled = f.field || f.nowhere;

  return '<select data-raw="' + esc(f.raw) + '" data-ident="' + esc(s.ident) + '">' +
    '<option value=""' + (settled ? '' : ' selected') +
    '>\\u2014 wherever the catalog puts it \\u2014</option>' +
    '<option value="-"' + (f.nowhere ? ' selected' : '') +
    '>\\u2014 nowhere \\u2014</option>' +
    here +
    (fits.length ? '<optgroup label="Measures the same thing">' +
      fits.map(option).join('') + '</optgroup>' : '') +
    '<optgroup label="Everything else">' + others.map(option).join('') + '</optgroup>' +
    '<option value="__new__">\\u2014 a field of my own \\u2014</option>' +
    '</select>';
}

function fieldRow(s, f) {
  var where = chooser(f, s) +
    (f.reserved ? '<div class="newcol dim">placed in weewx.conf; a choice here ' +
      'takes precedence</div>' : '');
  var status;
  if (f.nowhere) {
    status = '<span class="dim">nowhere, on purpose</span>';
  } else if (!f.field) {
    status = '<span class="dim">not written</span>';
  } else if (heldElsewhere(f.field, s, f)) {
    var who = heldElsewhere(f.field, s, f);
    status = '<span class="dim">' + esc(who.name || who.ident) +
      ' fills this column</span>';
  } else if (f.column) {
    status = f.history
      ? '<span class="warn">column holds ' + f.history + ' earlier values</span>'
      : '<span class="ok">column ready</span>';
  } else {
    status = '<span class="bad">no column</span>' + (candidates.can_add
      ? '<div class="newcol"><button class="act" data-addcol="' + esc(f.field) +
        '">Create the column</button></div>'
      : '<div class="newcol dim">needs <code>weectl database add-column ' +
        esc(f.field) + '</code></div>');
  }
  return '<tr><td class="mono">' + esc(f.raw) + '</td>' +
    '<td class="mono">' + (f.value === null || f.value === undefined
      ? '<span class="dim">no reading</span>' : esc(f.value)) + '</td>' +
    '<td>' + where + '</td>' +
    '<td class="dim">' + esc(f.group || '') + '</td>' +
    '<td>' + status + '</td>' +
    '<td class="dim">' + esc(f.why || '') + '</td></tr>';
}

function stationFields(s, several) {
  var open = !folded[s.ident];
  var role = s.role === 'extra'
    ? 'extra sensor on channel ' + (s.channel || '?')
    : 'the main station';
  var head = '<div class="fold" data-fold="' + esc(s.ident) + '">' +
    '<span class="caret">' + (open ? '\\u25be' : '\\u25b8') + '</span>' +
    '<b>' + esc(s.name || s.ident) + '</b>' +
    '<span class="dim">' + esc(s.protocol || '?') + ' \\u00b7 ' + role +
    ' \\u00b7 ' + s.rows.length + ' fields</span></div>';
  if (!open) return '<div class="block">' + head + '</div>';

  var swap = '';
  if (several && !s.declared) {
    swap = '<div class="add"><button class="act" data-role="' +
      (s.role === 'main' ? 'extra' : 'main') + '" data-ident="' + esc(s.ident) +
      '">Make it ' + (s.role === 'main' ? 'an extra sensor'
                                            : 'the main station') +
      '</button></div>';
  }
  return '<div class="block">' + head + swap +
    '<table><thead><tr><th>Raw field</th><th>Last value</th><th>WeeWX field</th>' +
    '<th>Group</th><th>Column</th><th>How</th></tr></thead><tbody>' +
    s.rows.map(function (f) { return fieldRow(s, f); }).join('') +
    '</tbody></table></div>';
}

/* ---------------------------------------------------------------- stations */

function drawStations(box) {
  loadStations().then(function (d) {
    if (!d.ok) { box.innerHTML = '<p class="bad">' + esc(d.error || '') + '</p>'; return; }
    box.innerHTML = '<div class="setup">' +
      (pending && pending.what === 'edit' ? confirmBox() : '') +
      d.stations.map(stationCard).join('') +
      '<p class="dim">One station is the main station. Its readings go to ' +
      'outTemp, ' +
      'barometer and the rest, which is what a WeeWX report reads. Every other ' +
      'station is a sensor beside it: temperature and humidity go to a channel of ' +
      'their own, and what has nowhere to go is dropped rather than written over ' +
      'the main station\\u2019s.</p>' +
      '<p class="dim">Changed here, kept in ' + esc(d.settings_file) + '.</p></div>';
  });
}

function stationCard(s) {
  /* Shut, until somebody wants this one. A list of stations is a list to find
     something in, and five consoles' worth of console settings unrolled at
     once is not a list any more. */
  var open = !!unfolded[s.ident];
  var what = s.role === 'extra'
    ? 'extra sensor on channel ' + (s.channel || '?')
    : (s.is_main ? 'the main station' : 'main, and not the one that writes');
  /* A station this driver reads has no protocol and sends no uploads: it is asked,
     and what it has instead of a count is whether it is answering. */
  var wired = !!s.station_type;
  var seen = s.heard
    ? (wired ? 'read ' + ago(s.last_seen)
             : s.uploads + (s.uploads === 1 ? ' upload ' : ' uploads ') +
               '\\u00b7 ' + ago(s.last_seen))
    : (wired ? 'nothing read yet' : 'never heard from');
  return '<div class="step ' + (s.is_main ? 'done' : 'todo') + '">' +
    '<div class="head shut" data-open="' + esc(s.ident) + '">' +
    '<span class="mark">' + (s.is_main ? '\\u2605' : '\\u25cb') +
    '</span><span class="caret">' + (open ? '\\u25be' : '\\u25b8') +
    '</span><span class="what">' + esc(s.name || s.ident) + '</span>' +
    '<span class="dim">' + esc(s.station_type || s.protocol || 'kind unknown') +
    ' \\u00b7 ' + esc(what) + ' \\u00b7 ' + esc(seen) + '</span></div>' +
    (open ? '<div class="body">' + stationBody(s, editing === s.ident) +
            '</div>' : '') +
    '</div>';
}

function stationBody(s, open) {
  /* The console settings, every time. The checklist shows them once and then
     stops, because it is a checklist; a console reset a year later needs them
     again, and this is where somebody would come looking. */
  if (s.station_type) return hostedBody(s) + columnsHeld(s);
  var html = s.settings ? settingsTable(s.settings) : '';
  if (s.path) {
    html += '<p class="dim">The path is what tells this station apart from the ' +
      'others, so it is a secret: anybody who can post to it can write into this ' +
      'station\\u2019s columns.</p>';
  }
  if (s.declared) {
    return html + '<p class="dim">weewx.conf declares this station, so its name, its ' +
      'role and its channel are set there. One owner per setting.</p>';
  }
  if (s.adopted) {
    /* Two states that look the same from here and read very differently. Saying
       "the first console this driver ever heard" about one that has not been heard
       is telling somebody their station is working. */
    return html + '<p class="dim">' + (s.heard
      ? 'The first console this driver ever heard, adopted so that it would record ' +
        'rather than be turned away. It is named in no file, which is why there is ' +
        'nothing here to change: what it wants is a name, and the Setup tab gives ' +
        'it one.'
      : 'weewx.conf names this console with \\u2018passkey\\u2019, and nothing has ' +
        'been heard from it yet. It counts as the main station until something else ' +
        'is, so that a first upload has somewhere to go. There is nothing to change ' +
        'here until it has uploaded: its name is all this driver knows about it.') +
      '</p>';
  }
  html += columnsHeld(s);
  if (!open) {
    return html + '<div class="add"><button class="act" data-edit="' + esc(s.ident) +
      '">Change it</button>' +
      /* Taking out a station that has never been heard from is undoing a typing
         mistake, and it should not be behind a form called "Change it". One that
         has been heard keeps its remove button inside that form, where an accident
         is harder to have. */
      (s.heard ? '' : ' <button class="act" data-forget="' + esc(s.ident) +
        '">Take it out</button>') + '</div>';
  }
  return html + '<div class="add">' +
    '<input type="text" id="editname" value="' + esc(s.name || '') +
    '" placeholder="name this station">' +
    roleSelect('editrole', s.role) +
    channelSelect(s) +
    '<button class="act" id="save" data-ident="' + esc(s.ident) + '">Save</button>' +
    '<button class="act" id="cancel">Cancel</button></div>' +
    '<div class="add" style="margin-top:14px">' +
    '<button class="act" data-forget="' + esc(s.ident) + '">Take it out</button>' +
    '<span class="dim" style="font-size:12px;align-self:center">Its upload path goes ' +
    'with it, and the console using that path is turned away from then on.</span>' +
    '</div>';
}

function columnsHeld(s) {
  /* Which columns are this station's. A column belongs to whoever filled it first,
     so a sensor that has been taken down goes on holding one until somebody says
     otherwise: better than losing it while the console is offline for a week, but
     only if there is a way to say so. */
  if (!s.columns || !s.columns.length) return '';
  return '<p class="dim">Fills ' + s.columns.length + ' column' +
    (s.columns.length === 1 ? '' : 's') + ': <span class="mono">' +
    s.columns.map(esc).join(', ') + '</span>. No other station writes them.' +
    (s.editable
      ? ' <button class="act" data-release="' + esc(s.ident) +
        '">Give them up</button>'
      : '') + '</p>';
}

function channelSelect(s) {
  /* Only the channels nothing else is on, plus the one this station already has.
     A channel two stations share is two sensors in one column, which is the thing
     none of this is allowed to produce. */
  var taken = (stationList && stationList.taken) || [];
  var limit = (stationList && stationList.channels) || 8;
  var out = '<select id="editchannel">';
  for (var n = 1; n <= limit; n++) {
    if (taken.indexOf(n) >= 0 && n !== s.channel) continue;
    out += '<option value="' + n + '"' + (n === s.channel ? ' selected' : '') +
      '>channel ' + n + '</option>';
  }
  return out + '</select>';
}

function drawFields(box) {
  /* Every station at once. The question is not "what does this station send", it is
     "who fills outTemp", and with two stations that answer used to be spread over
     two pages, neither of which could show the collision that matters. */
  Promise.all([api('fields'), loadCandidates()]).then(function (both) {
    var d = both[0];
    if (!d.ok) { box.innerHTML = '<p class="bad">' + esc(d.error) + '</p>'; return; }
    fieldsView = d;
    if (!d.stations.length) {
      box.innerHTML = '<p class="dim">Nothing has uploaded yet.</p>';
      return;
    }
    var several = d.stations.length > 1;
    box.innerHTML = d.stations.map(function (s) {
      return stationFields(s, several);
    }).join('');
  });
}


function drawRaw(box) {
  api('raw?ident=' + encodeURIComponent(chosen)).then(function (d) {
    if (!d.uploads.length) { box.innerHTML = '<p class="dim">Nothing kept yet.</p>'; return; }
    box.innerHTML = '<p class="dim">The last ' + d.uploads.length +
      ' uploads, newest first. Whatever names the station has been replaced, so these ' +
      'are safe to paste into an issue.</p>' +
      d.uploads.map(function (u, i) {
        return '<div class="upload"><div class="head"><span>' + esc(u.method) + ' ' +
          esc(u.path) + ' from ' + esc(u.client) + ' \\u00b7 ' + ago(u.at) +
          (u.protocol ? ' \\u00b7 ' + esc(u.protocol) : '') + '</span>' +
          '<button class="act" data-copy="' + i + '">Copy</button></div>' +
          '<pre id="raw' + i + '">' + esc(u.text) + '</pre></div>';
      }).join('');
  });
}


function drawColumns(box) {
  api('columns?ident=' + encodeURIComponent(chosen)).then(function (d) {
    if (!d.ok) { box.innerHTML = '<p class="bad">' + esc(d.error) + '</p>'; return; }
    var html = '';
    if (!d.missing.length) {
      html += '<p class="ok">Every reading this station sends has a column.</p>';
    } else {
      html += '<p>' + d.missing.length + ' reading(s) have nowhere to live. They show ' +
        'up in reports as current conditions and are gone at the next archive interval. ' +
        'Adding a column changes the table definition and not its rows, so it is ' +
        'quick on any size of database. Taking one away again is not, so it is ' +
        'worth a backup and a moment on the name.</p>' +
        '<div class="row" style="margin-bottom:8px">' +
        '<button class="act" id="copycmds">Copy the commands</button></div>' +
        '<pre id="cmds">' + esc(d.commands.join('\\n')) + '</pre>';
    }
    if (d.occupied_checked) {
      html += '<h2>Columns that already hold readings</h2>' +
        (d.occupied.length
          ? '<table><thead><tr><th>Column</th><th>Values</th><th>Last</th></tr></thead><tbody>' +
            d.occupied.map(function (o) {
              return '<tr><td class="mono">' + esc(o.field) + '</td><td>' + o.count +
                '</td><td class="dim">' + esc(o.last) + '</td></tr>';
            }).join('') + '</tbody></table>'
          : '<p class="dim">None of the columns this station writes to has earlier ' +
            'readings in it.</p>');
    } else {
      html += '<h2>Columns that already hold readings</h2><p class="dim">Not checked. ' +
        'It is one pass over the archive table, which takes a moment on a large ' +
        'database.</p><button class="act" id="checkdb">Check the database</button>';
    }
    box.innerHTML = html;
  });
}

function createStation(body) {
  api('create', body).then(function (r) {
    if (!r.ok) { flash(r.message, true); return; }
    flash(r.station.role === 'main'
      ? 'Set up as the main station. Put the path below into the console.'
      : 'Set up as an extra sensor on channel ' + r.station.channel +
        '. Put the path below into the console.');
    candidates = null;
    loadState();
    loadStations();
    loadSetup(function () { draw(); });
  });
}

function saveStation(ident, body) {
  body.ident = ident;
  api('edit', body).then(function (r) {
    flash(r.ok ? 'Changed. It takes effect on the next upload.' : r.message, !r.ok);
    if (!r.ok) return;
    editing = null;
    candidates = null;
    loadState();
    loadSetup(function () { draw(); });
  });
}

/* -------------------------------------------------------- hosted drivers */

/* What /api/ways last said. Held because the picker is redrawn on every choice, and
   asking again for a list that has not changed would empty the fields somebody is
   typing a serial port into. */
var ways = null;
/* What is in the form now, and what its fields are, so that changing an option
   others depend on can rebuild it without losing what has been typed. */
var formValues = null, formFields = null;
/* Options somebody has stepped out of the list for. Kept rather than done by
   swapping the element, so that stepping back in is possible at all. */
var typedBy = {};

function loadWays() {
  api('ways').then(function (d) {
    if (!d.ok) return;
    ways = d;
    if (tab === 'setup') drawSetup(document.getElementById('body'));
  });
}

function hostedRoleSelect(chosenRole) {
  return '<select data-hostedrole>' +
    '<option value="main"' + (chosenRole === 'main' ? ' selected' : '') +
    '>main station</option>' +
    '<option value="extra"' + (chosenRole === 'extra' ? ' selected' : '') +
    '>extra sensor, on a free channel</option></select>';
}

function hostedBody(one) {
  /* A hosted driver, on the Stations tab, where every other station is managed too.
     What it has instead of an upload path is a serial port, so that is what is
     shown; everything else on the card is the same. */
  var html = '';
  if (one.answers_for.length) {
    html += '<p class="dim">As the archive station it answers for: ' +
      esc(one.answers_for.join(', ')) + '.</p>';
  } else {
    html += '<p class="dim">It sends readings and keeps no records of its own, so ' +
      'the archive is worked out from what arrives.</p>';
  }
  if (!one.editable) {
    return html + '<p class="dim">weewx.conf names this driver, so its settings, ' +
      'its role and its channel are there. One owner per setting.</p>';
  }
  formFields = one.fields;
  html += driverForm(
    one.fields, formValues || one.options, one.ports, 'data-hwopt', ''
  ) +
    '<table class="settings"><tr><th>role</th><td>' +
    hostedRoleSelect(one.role) + '</td></tr></table>' +
    '<p><button data-hwsave="' + esc(one.station_type) + '">Save and reopen</button>' +
    ' <button data-hwarchive="' + esc(one.station_type) +
    '">Make the archive station</button>' +
    ' <button data-hwremove="' + esc(one.station_type) +
    '">Remove this station</button></p>' +
    '<p class="dim">Changed here, kept in the settings file. ' +
    'weectl device reads weewx.conf and will not find a driver set up this way; ' +
    'the block to paste there instead is below.</p>' +
    '<pre id="hwconf' + esc(one.station_type) + '">' + esc(hostedStanza(one)) +
    '</pre><p><button data-hwcopy="' + esc(one.station_type) +
    '">Copy that block</button></p>';
  return html;
}

function hostedStanza(one) {
  /* What weewx.conf would hold for the same thing, for somebody who would rather
     keep it there. Two places, one of which is in force: see the note above it. */
  var lines = ['[' + one.station_type + ']'];
  Object.keys(one.options).sort().forEach(function (key) {
    lines.push('    ' + key + ' = ' + one.options[key]);
  });
  lines.push('');
  lines.push('[UltimatePush]');
  lines.push('    [[hardware]]');
  lines.push('        station_types = ' + one.station_type);
  lines.push('        [[[' + one.station_type + ']]]');
  lines.push('            role = ' + one.role);
  if (one.role === 'extra') lines.push('            channel = ' + (one.channel || 1));
  return lines.join('\\n');
}

function hostedOptions(attribute) {
  var out = {};
  document.querySelectorAll('[' + attribute + ']').forEach(function (input) {
    out[input.getAttribute(attribute)] = input.value;
  });
  return out;
}

function dependsOn(key) {
  /* Whether anything on the form only applies for certain values of this option.
     Redrawing on every field would take the cursor out of whatever is being typed
     in, for nothing. */
  var fields = (formFields || {});
  for (var name in fields) {
    if (fields[name].when && fields[name].when.field === key) return true;
  }
  return false;
}

function hostedRole() {
  var select = document.querySelector('[data-hostedrole]');
  return select ? select.value : 'main';
}

function hostedThen(d) {
  flash(d.ok ? 'Saved.' : d.message || 'That did not work.', !d.ok);
  if (d.ok) adding = false;
  /* A driver that has just been set up is no longer on offer, and it is a station
     now, so both lists are stale. */
  ways = null;
  stationList = null;
  formValues = null;
  typedBy = {};
  loadWays();
  loadSetup();
  draw();
}

/* ---------------------------------------------------------------- events */

document.addEventListener('click', function (e) {
  var t = e.target;
  if (t.dataset.tab) { show(t.dataset.tab); return; }
  if (t.dataset.relist) {
    formValues = hostedOptions(
      document.querySelector('[data-hostedopt]') ? 'data-hostedopt' : 'data-hwopt');
    delete typedBy[t.dataset.relist];
    // Back to whatever the list has, rather than to a value the list does not.
    delete formValues[t.dataset.relist];
    draw();
    return;
  }
  if (t.dataset.notmine) {
    api('ignore', { ident: t.dataset.notmine, yes: true }).then(hostedThen);
    return;
  }
  if (t.dataset.moved) {
    /* The picker is the element just before the button, rather than something
       looked up by identity: an identity is whatever the hardware says it is, and
       a selector built out of one would break on the first sensor with a quote in
       its model name. */
    var picked = t.previousElementSibling;
    if (!picked || !picked.value) {
      flash('Choose which station moved onto this id.', true);
      return;
    }
    api('rebind', { was: picked.value, now: t.dataset.moved }).then(hostedThen);
    return;
  }
  if (t.dataset.askadd) {
    api('polling/add', {
      protocol: t.dataset.askadd,
      address: (document.querySelector('[data-askaddr]') || {}).value || '',
      interval: (document.querySelector('[data-askevery]') || {}).value || '',
      role: hostedRole(),
      name: (document.querySelector('[data-askname]') || {}).value || null
    }).then(hostedThen);
    return;
  }
  if (t.dataset.askremove) {
    api('polling/remove', { name: t.dataset.askremove }).then(hostedThen);
    return;
  }
  if (t.dataset.hostedadd) {
    api('hardware/add', {
      station_type: t.dataset.hostedadd,
      options: hostedOptions('data-hostedopt'),
      role: hostedRole(),
      name: (document.querySelector('[data-hostedname]') || {}).value || null
    }).then(hostedThen);
    return;
  }
  if (t.dataset.hwsave) {
    api('hardware/edit', {
      station_type: t.dataset.hwsave,
      options: hostedOptions('data-hwopt'),
      role: hostedRole()
    }).then(hostedThen);
    return;
  }
  if (t.dataset.hwarchive) {
    var order = [t.dataset.hwarchive];
    (stationList ? stationList.stations : []).forEach(function (one) {
      if (one.station_type && one.station_type !== t.dataset.hwarchive) {
        order.push(one.station_type);
      }
    });
    api('hardware/order', { station_types: order }).then(hostedThen);
    return;
  }
  if (t.dataset.hwremove) {
    api('hardware/remove', { station_type: t.dataset.hwremove }).then(hostedThen);
    return;
  }
  if (t.dataset.hwcopy) {
    copy(document.getElementById('hwconf' + t.dataset.hwcopy).textContent,
         'the block for weewx.conf');
    return;
  }
  if (t.dataset.pick) {
    picked = t.dataset.pick;
    // A different driver is a different form.
    formValues = null;
    typedBy = {};
    drawSetup(document.getElementById('body'));
    return;
  }
  if (t.dataset.fold !== undefined) {
    folded[t.dataset.fold] = !folded[t.dataset.fold];
    draw();
    return;
  }
  if (t.dataset.addcol !== undefined) {
    var wanted = t.dataset.addcol;
    if (!window.confirm('Add the column ' + wanted + ' to the database?\\n\\n' +
        'This is the same change weectl database add-column makes. A column ' +
        'cannot be taken away again without rebuilding the table, so it is worth ' +
        'being sure of the name.')) return;
    t.disabled = true;
    api('add-column', { field: wanted }).then(function (r) {
      flash(r.message, !r.ok);
      candidates = null;
      if (r.ok) { draw(); loadSetup(); } else { t.disabled = false; }
    });
    return;
  }
  if (t.dataset.role) {
    api('role', { ident: t.dataset.ident || chosen, role: t.dataset.role })
      .then(function (r) {
      flash(r.ok ? 'Changed. It takes effect on the next upload.' : r.message, !r.ok);
      candidates = null;
      if (r.ok) { loadState(); loadSetup(); draw(); }
    });
    return;
  }
  if (t.id === 'addstation') { adding = true; show('setup'); return; }
  if (t.id === 'create') {
    var name = (document.getElementById('newname').value || '').trim();
    var proto = t.dataset.proto;
    var role = document.getElementById('newrole').value;
    if (!name) { flash('Give it a name first.', true); return; }
    askFirst({ protocol: proto, role: role }).then(function (found) {
      if (!inTheWay(found)) {
        createStation({ protocol: proto, name: name, role: role });
        return;
      }
      /* Not sent. What this would land on is said in full first, and asked for
         again afterwards. */
      pending = { what: 'create', name: name, protocol: proto, role: role,
                  found: found,
                  button: role === 'main' ? 'Make ' + name + ' the main station'
                                          : 'Set ' + name + ' up anyway' };
      draw();
    });
    return;
  }
  if (t.id === 'agreed') {
    document.getElementById('doconfirm').disabled = !t.checked;
    return;
  }
  if (t.id === 'noconfirm') { pending = null; draw(); return; }
  if (t.id === 'doconfirm') {
    var asked = pending;
    pending = null;
    if (asked.what === 'create') {
      createStation({ protocol: asked.protocol, name: asked.name, role: asked.role,
                      force: true });
    } else {
      saveStation(asked.ident, { name: asked.name, role: asked.role,
                                 channel: asked.channel, force: true });
    }
    return;
  }
  var head = t.closest ? t.closest('[data-open]') : null;
  if (head) {
    /* Taken from whatever inside the head was clicked, so that the name and the
       line under it open the station too rather than only the caret. */
    var which = head.dataset.open;
    unfolded[which] = !unfolded[which];
    if (!unfolded[which] && editing === which) editing = null;
    draw();
    return;
  }
  if (t.dataset.edit) { editing = t.dataset.edit; draw(); return; }
  if (t.id === 'cancel') { editing = null; draw(); return; }
  if (t.id === 'save') {
    var ident = t.dataset.ident;
    var wanted = (document.getElementById('editname').value || '').trim();
    var role = document.getElementById('editrole').value;
    var channelBox = document.getElementById('editchannel');
    var channel = channelBox ? Number(channelBox.value) : null;
    var was = stationList.stations.filter(function (x) { return x.ident === ident; })[0];
    var asking = { name: wanted, role: role,
                   channel: role === 'extra' ? channel : null };
    askFirst({ protocol: was && was.protocol, role: role, channel: asking.channel,
               ident: ident }).then(function (found) {
      if (!inTheWay(found)) { saveStation(ident, asking); return; }
      pending = { what: 'edit', ident: ident, role: role, channel: asking.channel,
                  name: wanted || (was && was.name) || ident, found: found,
                  button: role === 'main'
                    ? 'Make ' + (wanted || ident) + ' the main station'
                    : 'Save it anyway' };
      draw();
    });
    return;
  }
  if (t.dataset.release) {
    var owner = t.dataset.release;
    if (!window.confirm('Give up the columns this station fills?' + '\\n\\n' +
        'The next station to send one of those readings gets that column, and this ' +
        'one is turned away from it. What is already in the archive stays.')) return;
    api('release', { ident: owner }).then(function (r) {
      flash(r.message, !r.ok);
      if (r.ok) { candidates = null; loadState(); loadSetup(function () { draw(); }); }
    });
    return;
  }
  if (t.dataset.forget) {
    var who = t.dataset.forget;
    if (!window.confirm('Take this station out?\\n\\nIts upload path goes with it. ' +
        'The console using that path is turned away from then on, and setting it up ' +
        'again means a new path and typing it into the console again.\\n\\nWhat it ' +
        'has already recorded stays in the archive.')) return;
    api('forget', { ident: who }).then(function (r) {
      flash(r.ok ? 'Taken out.' : r.message, !r.ok);
      if (!r.ok) return;
      editing = null;
      candidates = null;
      loadState();
      loadSetup(function () { draw(); });
    });
    return;
  }
  if (t.dataset.goto) {
    if (!chosen && state && state.stations.length) chosen = state.stations[0].ident;
    show(t.dataset.goto);
    return;
  }
  if (t.dataset.accept) {
    var input = document.querySelector('[data-name="' + t.dataset.accept + '"]');
    api('accept', { ident: t.dataset.accept, name: input ? input.value : '' })
      .then(function (r) {
        flash(r.ok ? 'Let in. It records from its next upload.' : r.message, !r.ok);
        if (r.ok) { loadState(); loadSetup(function () { draw(); }); }
      });
    return;
  }
  if (t.dataset.knock !== undefined) {
    var shown = document.getElementById('knockraw' + t.dataset.knock);
    var open = shown.style.display !== 'none';
    shown.style.display = open ? 'none' : 'block';
    t.textContent = open ? 'All of it' : 'Less';
    return;
  }
  if (t.dataset.knockcopy !== undefined) {
    copy(document.getElementById('knocktext' + t.dataset.knockcopy).textContent,
         'the upload');
    return;
  }
  if (t.dataset.copy !== undefined) {
    copy(document.getElementById('raw' + t.dataset.copy).textContent, 'the upload');
    return;
  }
  if (t.id === 'copycmds') {
    copy(document.getElementById('cmds').textContent, 'the commands');
    return;
  }
  if (t.id === 'checkdb') {
    api('columns?refresh=yes&ident=' + encodeURIComponent(chosen)).then(draw);
    return;
  }
  var card = t.closest ? t.closest('.card[data-ident]') : null;
  if (card) choose(card.dataset.ident);
});

function placeField(ident, raw, field, force) {
  api('field', { ident: ident, raw: raw, field: field, force: !!force })
    .then(function (r) {
      if (!r.ok && r.conflict) {
        /* One column takes one reading. Say who has it and let the person decide,
           rather than quietly letting two sensors take turns in it. */
        if (window.confirm(r.message + '\\n\\nMove it to this one?')) {
          placeField(ident, raw, field, true);
        } else {
          draw();
        }
        return;
      }
      flash(r.ok ? "'" + raw + "' takes effect on the next upload." : r.message, !r.ok);
      /* The choice changes who owns what, so the suggestions are asked for again. */
      candidates = null;
      if (r.ok) { draw(); loadSetup(); }
    });
}

document.addEventListener('change', function (e) {
  var decides = e.target.dataset.hostedopt || e.target.dataset.hwopt;
  if (decides && dependsOn(decides)) {
    /* This option decides whether others apply, and which of them is what the
       driver's own configuration editor says rather than anything decided here.
       What has been typed is carried over, because the form is rebuilt from the
       values in it. */
    formValues = hostedOptions(
      e.target.dataset.hostedopt ? 'data-hostedopt' : 'data-hwopt');
    draw();
    return;
  }
  if (e.target.dataset.freetext !== undefined &&
      e.target.value === '__other__') {
    /* The list could not offer it, so get out of the way rather than make somebody
       find the file. What is in the rest of the form is kept. */
    var which = e.target.dataset.hostedopt || e.target.dataset.hwopt;
    formValues = hostedOptions(
      e.target.dataset.hostedopt ? 'data-hostedopt' : 'data-hwopt');
    formValues[which] = '';
    typedBy[which] = true;
    draw();
    return;
  }

  var raw = e.target.dataset.raw;
  if (!raw) return;
  var field = e.target.value;
  if (field === '__new__') {
    field = (window.prompt('A field of your own. Letters, digits and underscores.\\n' +
      'If the database has no column for it, a button to make one appears in the ' +
      'row.', '') || '').trim();
    if (!field) { draw(); return; }
  }
  placeField(e.target.dataset.ident || chosen, raw, field, false);
});

loadState().then(function () { return loadStations(); })
  .then(function () { return loadSetup(); }).then(function () {
  /* An installation with something still to do opens on the thing still to do. The
     fields of a station that has not uploaded are an empty table, and an empty table
     reads like a fault rather than like a step not taken yet. */
  if (setup && !setup.done) tab = 'setup';
  document.querySelectorAll('.tabs button').forEach(function (b) {
    b.classList.toggle('on', b.dataset.tab === tab);
  });
  if (!chosen && state.stations.length) chosen = state.stations[0].ident;
  drawSidebar();
  draw();
});
setInterval(function () { loadState(); loadStations(); loadSetup(); }, 15000);
</script>
</body>
</html>
"""
