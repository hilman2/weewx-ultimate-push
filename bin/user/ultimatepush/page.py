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
      content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'">
<title>weewx-ultimate-push</title>
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
var setup = null, picked = null, watching = null, candidates = null;

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
    drawStations();
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

function drawStations() {
  var box = document.getElementById('stations');
  if (!state.stations.length) {
    box.innerHTML = '<div class="dim" style="font-size:13px">Nothing has uploaded yet.</div>';
  } else {
    box.innerHTML = state.stations.map(function (s) {
      return '<div class="card' + (s.ident === chosen ? ' on' : '') +
        '" data-ident="' + esc(s.ident) + '">' +
        '<div class="id">' + esc(s.name || s.ident) + '</div>' +
        '<div class="sub">' + esc(s.protocol || '?') +
        (s.dialect && s.dialect !== s.protocol ? ' \\u00b7 ' + esc(s.dialect) : '') +
        (s.role === 'extra' ? ' \\u00b7 extra ' + (s.channel || '?')
                            : ' \\u00b7 the station') +
        ' \\u00b7 ' + s.field_count + ' fields \\u00b7 ' + ago(s.last_seen) +
        '</div>' +
        (s.undecided_count ? '<div class="sub warn">' + s.undecided_count +
          ' waiting for a placement</div>' : '') +
        '</div>';
    }).join('');
  }
  var waiting = document.getElementById('waiting');
  if (!state.waiting.length) {
    waiting.innerHTML = '<div class="dim" style="font-size:13px">Nothing refused.</div>';
  } else {
    waiting.innerHTML = state.waiting.map(function (w) {
      return '<div class="card"><div class="id">' + esc(w.ident) + '</div>' +
        '<div class="sub">' + esc(w.protocol || '?') + ' from ' + esc(w.client) +
        ' \\u00b7 ' + w.uploads + ' seen</div>' +
        '<div class="row" style="margin-top:8px">' +
        '<input type="text" placeholder="name it" data-name="' + esc(w.ident) + '">' +
        '<button class="act" data-accept="' + esc(w.ident) + '">Let in</button></div>' +
        '</div>';
    }).join('');
  }
}

function loadCandidates() {
  /* The same answer for every row, so it is asked for once. */
  if (candidates) return Promise.resolve(candidates);
  return api('candidates').then(function (c) { candidates = c; return c; });
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
    /* Something arrived while we were waiting. Show it. */
    if (was && was !== s.next) { drawStations(); draw(); }
    if (then) then();
  });
}

function drawSetup(box) {
  if (!setup) { box.innerHTML = '<p class="dim">Loading.</p>'; return; }
  box.innerHTML = '<div class="setup">' +
    (setup.done
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
  if (s.id === 'hardware') return html + hardwareBody(s);
  if (s.id === 'refused') {
    return html + s.stations.map(function (w) {
      return '<div class="row" style="margin-bottom:6px">' +
        '<span class="mono">' + esc(w.ident) + '</span>' +
        '<span class="dim">' + esc(w.protocol || '?') + ' from ' + esc(w.client) +
        '</span><input type="text" placeholder="name it" data-name="' +
        esc(w.ident) + '"><button class="act" data-accept="' + esc(w.ident) +
        '">Let in</button></div>';
    }).join('');
  }
  if (s.id === 'placements') {
    return html + '<button class="act" data-goto="fields">Place them</button>';
  }
  if (s.id === 'sharing') {
    return html + '<table><thead><tr><th>Column</th><th>Wanted by</th></tr></thead>' +
      '<tbody>' + s.fields.map(function (f) {
        return '<tr><td class="mono">' + esc(f.field) + '</td><td>' +
          esc(f.stations.join(', ')) + '</td></tr>';
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

function createBox(protocols) {
  /* Only hardware whose upload path is yours to choose can be set up in advance.
     The rest has to be heard first, and says so. */
  var canBeNamed = protocols.filter(function (p) { return p.can_create; });
  if (!canBeNamed.length) return '';
  return '<div class="add">' +
    '<input type="text" id="newname" placeholder="name this station">' +
    '<select id="newproto">' + canBeNamed.map(function (p) {
      return '<option value="' + esc(p.name) + '"' +
        (p.name === picked ? ' selected' : '') + '>' + esc(p.label) + '</option>';
    }).join('') + '</select>' +
    '<button class="act" id="create">Set it up</button></div>' +
    '<p class="dim" style="margin-top:8px">Naming it here gives it an upload path of ' +
    'its own. That path is how the driver knows which station an upload is from, and ' +
    'it is a secret: a PASSKEY can be read off anybody\u2019s upload and repeated.</p>';
}

function hardwareBody(s) {
  if (!s.protocols) return '';
  if (!picked) picked = s.protocols[0].name;
  var one = s.protocols.filter(function (p) { return p.name === picked; })[0]
            || s.protocols[0];
  return '<div class="pick">' + s.protocols.map(function (p) {
      return '<button data-pick="' + esc(p.name) + '"' +
        (p.name === picked ? ' class="on"' : '') + '>' + esc(p.label) + '</button>';
    }).join('') + '</div>' +
    '<p class="dim">' + esc(one.hardware) + '</p>' +
    (one.settings.length
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
    }).join('') +
    '<p class="waiting"><b>Waiting for the first upload.</b> This page notices by ' +
    'itself, so you can leave it open.</p>' +
    createBox(s.protocols);
}

function watch() {
  /* While anything is outstanding, look more often than the fifteen seconds the
     rest of the page settles for. Somebody is standing at their console. */
  if (watching) return;
  watching = setInterval(function () {
    if (setup && setup.done) { clearInterval(watching); watching = null; return; }
    loadSetup();
    if (tab === 'setup') drawSetup(document.getElementById('body'));
  }, 5000);
}

/* ---------------------------------------------------------------- a station */

function choose(ident) {
  chosen = ident;
  drawStations();
  draw();
}

function draw() {
  var box = document.getElementById('body');
  if (tab === 'setup') return drawSetup(box);
  if (!chosen) {
    box.innerHTML = '<p class="dim">Pick a station.</p>';
    return;
  }
  box.innerHTML = '<p class="dim">Loading.</p>';
  if (tab === 'fields') return drawFields(box);
  if (tab === 'raw') return drawRaw(box);
  return drawColumns(box);
}

function show(which) {
  tab = which;
  document.querySelectorAll('.tabs button').forEach(function (b) {
    b.classList.toggle('on', b.dataset.tab === tab);
  });
  draw();
}

function chooser(f) {
  /* Where this reading could go. The ones that measure the same thing first: a wind
     speed offered as a home for a temperature is worse than no suggestion, because
     somebody will pick it. */
  var fits = (candidates.groups[f.group] || []).slice();
  var others = [];
  Object.keys(candidates.groups).forEach(function (g) {
    if (g !== f.group) others = others.concat(candidates.groups[g]);
  });
  others = others.concat(candidates.ungrouped).sort();

  function option(name) {
    var who = candidates.used[name];
    var mine = who && who.length === 1 && detail && who[0] ===
               (detail.name || detail.ident);
    var note = who && !mine ? ' \u2014 ' + who.join(', ') : '';
    return '<option value="' + esc(name) + '"' +
      (name === f.field ? ' selected' : '') + '>' + esc(name) + esc(note) + '</option>';
  }

  var here = f.field && fits.indexOf(f.field) < 0 && others.indexOf(f.field) < 0
    ? '<option value="' + esc(f.field) + '" selected>' + esc(f.field) +
      ' \u2014 not in the schema</option>'
    : '';

  return '<select data-raw="' + esc(f.raw) + '">' +
    '<option value=""' + (f.field ? '' : ' selected') + '>\u2014 not written</option>' +
    here +
    (fits.length ? '<optgroup label="Measures the same thing">' +
      fits.map(option).join('') + '</optgroup>' : '') +
    '<optgroup label="Everything else">' + others.map(option).join('') + '</optgroup>' +
    '<option value="__new__">\u2014 a field of my own \u2014</option>' +
    '</select>';
}

function roleBox() {
  /* Only worth asking about once there is a second station. With one, there is
     nothing to decide and the question would be noise. */
  if (!state || state.stations.length < 2 || !detail) return '';
  var role = detail.role || 'main';
  return '<div class="note" style="border-left-color:var(--line)">' +
    '<b>' + esc(detail.name || detail.ident) + '</b> is ' +
    (role === 'main'
      ? 'the station: its readings go where they belong.'
      : 'an extra sensor on channel ' + (detail.channel || '?') + ': its temperature '
        + 'and humidity are moved there, and what has nowhere to go is dropped rather '
        + 'than written over the main station\u2019s.') +
    '<div class="add"><button class="act" data-role="' +
    (role === 'main' ? 'extra' : 'main') + '">Make it ' +
    (role === 'main' ? 'an extra sensor' : 'the station') + '</button></div></div>';
}

function drawFields(box) {
  Promise.all([api('station?ident=' + encodeURIComponent(chosen)),
               loadCandidates()]).then(function (both) {
    var d = both[0];
    if (!d.ok) { box.innerHTML = '<p class="bad">' + esc(d.error) + '</p>'; return; }
    detail = d;
    var rows = d.fields.map(function (f) {
      var where = f.reserved
        ? '<span class="dim">set in weewx.conf</span>'
        : chooser(f);
      var status = f.field
        ? (f.column
            ? (f.history
                ? '<span class="warn">column holds ' + f.history + ' earlier values</span>'
                : '<span class="ok">column ready</span>')
            : '<span class="bad">no column</span><div class="newcol dim">needs ' +
              '<code>weectl database add-column ' + esc(f.field) + '</code></div>')
        : '<span class="dim">not written</span>';
      return '<tr><td class="mono">' + esc(f.raw) + '</td>' +
        '<td class="mono">' + (f.value === null ? '<span class="dim">no reading</span>'
                                                : esc(f.value)) + '</td>' +
        '<td>' + where + '</td>' +
        '<td class="dim">' + esc(f.group || '') + '</td>' +
        '<td>' + status + '</td>' +
        '<td class="dim">' + esc(f.why || '') + '</td></tr>';
    }).join('');
    box.innerHTML = roleBox() +
      (d.undecided.length ? '<div class="note"><b>' + d.undecided.length +
        ' field(s) are not being written</b> because where they go is your call and not ' +
        'the hardware\\u2019s. Two sensors in one column cannot be separated afterwards, ' +
        'so nothing is guessed. Fill in a field below and it takes effect on the next ' +
        'upload.</div>' : '') +
      '<table><thead><tr><th>Raw field</th><th>Last value</th><th>WeeWX field</th>' +
      '<th>Group</th><th>Column</th><th>How</th></tr></thead><tbody>' + rows +
      '</tbody></table>';
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
        'Back up the database first: adding a column rewrites the table.</p>' +
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

/* ---------------------------------------------------------------- events */

document.addEventListener('click', function (e) {
  var t = e.target;
  if (t.dataset.tab) { show(t.dataset.tab); return; }
  if (t.dataset.pick) {
    picked = t.dataset.pick;
    drawSetup(document.getElementById('body'));
    return;
  }
  if (t.dataset.role) {
    api('role', { ident: chosen, role: t.dataset.role }).then(function (r) {
      flash(r.ok ? 'Changed. It takes effect on the next upload.' : r.message, !r.ok);
      candidates = null;
      if (r.ok) { loadState(); loadSetup(); draw(); }
    });
    return;
  }
  if (t.id === 'addstation') { show('setup'); return; }
  if (t.id === 'create') {
    var name = (document.getElementById('newname').value || '').trim();
    var proto = document.getElementById('newproto').value;
    if (!name) { flash('Give it a name first.', true); return; }
    api('create', { protocol: proto, name: name }).then(function (r) {
      if (!r.ok) { flash(r.message, true); return; }
      flash('Set up. Put the path below into the console.');
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

document.addEventListener('change', function (e) {
  var raw = e.target.dataset.raw;
  if (!raw) return;
  var field = e.target.value;
  if (field === '__new__') {
    field = (window.prompt('A field of your own. Letters, digits and underscores.\n' +
      'It will need a column: the command appears once it is set.', '') || '').trim();
    if (!field) { draw(); return; }
  }
  api('field', { ident: chosen, raw: raw, field: field }).then(function (r) {
    flash(r.ok ? "'" + raw + "' takes effect on the next upload." : r.message, !r.ok);
    /* The choice changes who owns what, so the suggestions are asked for again. */
    candidates = null;
    if (r.ok) { draw(); loadSetup(); }
  });
});

loadState().then(function () { return loadSetup(); }).then(function () {
  document.querySelectorAll('.tabs button').forEach(function (b) {
    b.classList.toggle('on', b.dataset.tab === tab);
  });
  if (!chosen && state.stations.length) chosen = state.stations[0].ident;
  drawStations();
  draw();
});
setInterval(function () { loadState(); loadSetup(); }, 15000);
</script>
</body>
</html>
"""
