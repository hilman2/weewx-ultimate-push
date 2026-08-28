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
    <h2>Stations</h2>
    <div id="stations"></div>
    <h2>Waiting to be let in</h2>
    <div id="waiting"><div class="dim" style="font-size:13px">Nothing refused.</div></div>
  </aside>
  <section>
    <div class="tabs">
      <button data-tab="fields" class="on">Fields</button>
      <button data-tab="raw">Raw uploads</button>
      <button data-tab="columns">Database columns</button>
    </div>
    <div id="body"><p class="dim">Pick a station.</p></div>
  </section>
</main>
<div id="flash"></div>
<script>
'use strict';
var TOKEN = new URLSearchParams(location.search).get('token') || '';
var chosen = null, tab = 'fields', state = null, detail = null;

function api(route, body) {
  var opts = { headers: { 'X-Auth-Token': TOKEN } };
  if (body) {
    opts.method = 'POST';
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  return fetch('/api/' + route, opts).then(function (r) { return r.json(); });
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
    drawStations();
  });
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
        ' \\u00b7 ' + s.field_count + ' fields \\u00b7 ' + s.uploads + ' uploads' +
        ' \\u00b7 ' + ago(s.last_seen) + '</div>' +
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

/* ---------------------------------------------------------------- a station */

function choose(ident) {
  chosen = ident;
  drawStations();
  draw();
}

function draw() {
  var box = document.getElementById('body');
  if (!chosen) { box.innerHTML = '<p class="dim">Pick a station.</p>'; return; }
  box.innerHTML = '<p class="dim">Loading.</p>';
  if (tab === 'fields') return drawFields(box);
  if (tab === 'raw') return drawRaw(box);
  return drawColumns(box);
}

function drawFields(box) {
  api('station?ident=' + encodeURIComponent(chosen)).then(function (d) {
    if (!d.ok) { box.innerHTML = '<p class="bad">' + esc(d.error) + '</p>'; return; }
    detail = d;
    var rows = d.fields.map(function (f) {
      var where = f.reserved
        ? '<span class="dim">set in weewx.conf</span>'
        : '<input type="text" data-raw="' + esc(f.raw) + '" value="' + esc(f.field) + '">';
      var status = f.field
        ? (f.column
            ? (f.history
                ? '<span class="warn">column holds ' + f.history + ' earlier values</span>'
                : '<span class="ok">column ready</span>')
            : '<span class="bad">no column</span>')
        : '<span class="dim">not written</span>';
      return '<tr><td class="mono">' + esc(f.raw) + '</td>' +
        '<td class="mono">' + (f.value === null ? '<span class="dim">no reading</span>'
                                                : esc(f.value)) + '</td>' +
        '<td>' + where + '</td>' +
        '<td class="dim">' + esc(f.group || '') + '</td>' +
        '<td>' + status + '</td>' +
        '<td class="dim">' + esc(f.why || '') + '</td></tr>';
    }).join('');
    box.innerHTML =
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
  if (t.dataset.tab) {
    tab = t.dataset.tab;
    document.querySelectorAll('.tabs button').forEach(function (b) {
      b.classList.toggle('on', b.dataset.tab === tab);
    });
    draw();
    return;
  }
  if (t.dataset.accept) {
    var input = document.querySelector('[data-name="' + t.dataset.accept + '"]');
    api('accept', { ident: t.dataset.accept, name: input ? input.value : '' })
      .then(function (r) {
        flash(r.ok ? 'Let in. It records from its next upload.' : r.message, !r.ok);
        if (r.ok) loadState();
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
  api('field', { ident: chosen, raw: raw, field: e.target.value }).then(function (r) {
    flash(r.ok ? "'" + raw + "' takes effect on the next upload." : r.message, !r.ok);
    if (r.ok) draw();
  });
});

loadState();
setInterval(loadState, 15000);
</script>
</body>
</html>
"""
