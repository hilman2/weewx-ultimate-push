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
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'><rect width='16' height='16' rx='3.5' fill='%231a5fb4'/><path d='M8 3 11.8 7.2H9.4v3.4H6.6V7.2H4.2z' fill='%23ffffff'/><rect x='4.2' y='11.7' width='7.6' height='1.5' rx='.75' fill='%23ffffff'/></svg>">
<style>
:root {
  --bg: #f4f5f7; --panel: #fff; --line: #dcdfe4; --soft: #e9ebef; --sink: #f8f9fa;
  --ink: #14181d; --ink2: #3d454f; --dim: #6b7480;
  --accent: #1a5fb4; --accent-soft: #eaf1fb; --accent-line: #b9d2f0;
  --ok: #1f7a43; --ok-soft: #e9f4ed; --ok-line: #b7ddc6;
  --warn: #8a5a00; --warn-soft: #fbf1de; --warn-line: #e8d09a;
  --bad: #b3261e; --bad-soft: #fbeceb; --bad-line: #eec2be;
  --code: #f1f3f5;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #15171a; --panel: #1c1f23; --line: #333840; --soft: #292d33; --sink: #202429;
    --ink: #e6e8ea; --ink2: #b9bfc7; --dim: #8b939d;
    --accent: #6ba3e8; --accent-soft: #1b2b3f; --accent-line: #2f4a6b;
    --ok: #6cbf84; --ok-soft: #17281c; --ok-line: #2c4a35;
    --warn: #d9b45f; --warn-soft: #2a2312; --warn-line: #4d4021;
    --bad: #e8897c; --bad-soft: #2d1a18; --bad-line: #58302c;
    --code: #22262b;
  }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--ink);
  font: 14px/1.5 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
  -webkit-font-smoothing: antialiased;
  min-height: 100vh; display: flex; flex-direction: column; }
code, pre, .mono { font-family: ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace;
  font-size: 12.5px; }

/* The top bar carries what is true of the whole driver: which view you are in, and
   how it is doing. Nothing about one station belongs here. */
header { background: var(--panel); border-bottom: 1px solid var(--line); height: 52px;
  display: flex; align-items: stretch; gap: 22px; padding: 0 18px; }
header .brand { display: flex; align-items: center; gap: 9px; }
header h1 { font-size: 14px; margin: 0; font-weight: 600; letter-spacing: -.01em;
  white-space: nowrap; }
header .ver { color: var(--dim); font-size: 12px; }
header .meta { color: var(--dim); font-size: 12.5px; display: flex; align-items: center;
  gap: 16px; margin-left: auto; min-width: 0; }
header .meta span { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
header .meta .answers { min-width: 0; }
header .meta b { color: var(--ink2); font-weight: 400;
  font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 12px; }
nav.views { display: flex; gap: 2px; }
nav.views button { background: none; border: 0; padding: 0 13px; color: var(--ink2);
  cursor: pointer; font: inherit; font-size: 13.5px; display: flex; align-items: center;
  gap: 7px; box-shadow: inset 0 -2px 0 transparent; }
nav.views button:hover { color: var(--ink); }
nav.views button.on { color: var(--accent); font-weight: 500;
  box-shadow: inset 0 -2px 0 var(--accent); }
.count { min-width: 19px; height: 18px; padding: 0 6px; border-radius: 9px;
  background: var(--warn); color: #fff; font-size: 11px; font-weight: 600;
  display: none; align-items: center; justify-content: center; }
.count.on { display: flex; }

/* What is wrong across the whole driver, in one line, above everything. The
   checklist behind it is where the sentences and the buttons are; this is only the
   part that has to be visible from a station page you happen to be on. */
#alert { display: none; align-items: center; gap: 11px; padding: 11px 18px;
  background: var(--warn-soft); border-bottom: 1px solid var(--warn-line);
  font-size: 13px; }
#alert.on { display: flex; }
#alert.bad { background: var(--bad-soft); border-bottom-color: var(--bad-line); }
#alert b { font-weight: 600; }
#alert .act { margin-left: auto; flex: none; }

main { display: grid; grid-template-columns: 304px 1fr; flex-grow: 1; min-height: 0; }
@media (max-width: 860px) { main { grid-template-columns: 1fr; } }
aside { border-right: 1px solid var(--line); background: var(--panel);
  padding: 12px 12px 18px; min-width: 0; }
@media (max-width: 860px) { aside { border-right: 0; border-bottom: 1px solid var(--line); } }
section { padding: 0; min-width: 0; background: var(--panel); }
.side-head { display: flex; align-items: center; gap: 8px; margin-bottom: 9px; }
.side-head h2 { margin: 0; flex: 1; font-size: 14px; font-weight: 600;
  text-transform: none; letter-spacing: 0; color: var(--ink); }
#find { margin-bottom: 12px; background: var(--sink); }
h2 { font-size: 11.5px; text-transform: uppercase; letter-spacing: .07em;
  color: var(--dim); margin: 14px 0 6px; font-weight: 600; }

/* One station, in the list on the left. The badge says what it is; the line under
   the name says how it is doing, because those are two different questions and the
   second one changes every fifteen seconds. */
.card { background: var(--panel); border: 1px solid var(--line); border-radius: 4px;
  padding: 9px 11px; margin-bottom: 6px; cursor: pointer; }
.card:hover { border-color: var(--accent-line); }
.card.on { border-color: var(--accent); background: var(--accent-soft);
  box-shadow: inset 3px 0 0 var(--accent); }
.card .top { display: flex; align-items: center; gap: 8px; }
.card .id { font-weight: 600; font-size: 13.5px; flex: 1; min-width: 0;
  overflow-wrap: anywhere; }
.card .sub { color: var(--dim); font-size: 12px; margin-top: 3px;
  overflow-wrap: anywhere; }
.card .sub.warn { color: var(--warn); }
.card.refused { border-color: var(--bad-line); background: var(--bad-soft); }
.card.quiet { background: var(--sink); }
.tag { height: 18px; padding: 0 6px; border-radius: 3px; background: var(--soft);
  color: var(--ink2); font-size: 10.5px; font-weight: 600; letter-spacing: .04em;
  display: flex; align-items: center; flex: none; }
.tag.main { background: var(--accent-soft); color: var(--accent); }

/* The detail side: who this station is, then what you want to know about it. The
   header stays put while the tabs under it change. */
.dhead { padding: 16px 22px 0; }
.dhead .name { display: flex; align-items: center; gap: 9px; }
.dhead .name b { font-size: 18px; font-weight: 600; letter-spacing: -.015em;
  overflow-wrap: anywhere; }
.dhead .name b.mono { font-size: 14px; font-weight: 500; letter-spacing: 0; }
.card .id.mono { font-size: 12px; font-weight: 500; white-space: nowrap;
  overflow: hidden; text-overflow: ellipsis; }
.dhead .about { color: var(--dim); font-size: 12.5px; margin-top: 3px;
  display: flex; flex-wrap: wrap; gap: 9px; }
.dhead .about .mono { color: var(--ink2); }
.dhead .acts { margin-left: auto; display: flex; gap: 7px; flex: none; }
.tabs { display: flex; gap: 2px; margin-top: 13px; padding: 0 22px;
  border-bottom: 1px solid var(--line); }
.tabs button { background: none; border: 0; padding: 0 12px; height: 36px;
  color: var(--ink2); cursor: pointer; font: inherit; font-size: 13.5px;
  display: flex; align-items: center; gap: 7px; box-shadow: inset 0 -2px 0 transparent; }
.tabs button:hover { color: var(--ink); }
.tabs button.on { color: var(--accent); font-weight: 500;
  box-shadow: inset 0 -2px 0 var(--accent); }
.tabs .count { background: var(--warn); }
#body { padding: 18px 22px 26px; min-width: 0; }

table { border-collapse: collapse; width: 100%; table-layout: fixed; }
/* The chooser fills its cell. Left to itself it takes 240px in a column twice that
   wide, and the option it is showing reads 'dayRain \u2014 new colu'. */
td select { max-width: none; }
th.raw { width: 15%; } th.value { width: 8%; } th.goes { width: 23%; }
th.group { width: 12%; } th.state { width: 20%; } th.why { width: 22%; }
th, td { text-align: left; padding: 9px 14px 9px 0; border-bottom: 1px solid var(--soft);
  vertical-align: top; }
th { color: var(--dim); font-weight: 600; font-size: 11.5px; text-transform: uppercase;
  letter-spacing: .05em; border-bottom-color: var(--line); padding-bottom: 7px; }
tbody tr:hover { background: var(--sink); }
input[type=text] { background: var(--panel); color: var(--ink); border: 1px solid var(--line);
  border-radius: 4px; padding: 6px 9px; font: inherit; font-size: 13px; width: 100%;
  max-width: 240px; }
input[type=text]:focus { outline: 2px solid var(--accent); outline-offset: -1px; }
button.act { background: var(--panel); color: var(--ink2); border: 1px solid var(--line);
  border-radius: 4px; padding: 0 11px; height: 30px; font: inherit; font-size: 12.5px;
  cursor: pointer; display: inline-flex; align-items: center; gap: 6px; }
button.act:hover { border-color: var(--accent-line); color: var(--ink); }
button.act.primary { background: var(--accent); border-color: var(--accent); color: #fff;
  font-weight: 500; }
button.act.primary:hover { background: var(--accent); color: #fff; filter: brightness(1.08); }
pre { background: var(--code); border: 1px solid var(--line); border-radius: 4px;
  padding: 10px; overflow-x: auto; white-space: pre-wrap; word-break: break-all; margin: 0; }
.ok { color: var(--ok); } .warn { color: var(--warn); } .bad { color: var(--bad); }
.dim { color: var(--dim); }
.row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.note { background: var(--warn-soft); border: 1px solid var(--warn-line);
  border-radius: 4px; padding: 10px 12px; margin-bottom: 14px; font-size: 13px; }
.note.bad { background: var(--bad-soft); border-color: var(--bad-line); }
.upload { margin-bottom: 12px; }
.upload .head { display: flex; justify-content: space-between; gap: 10px;
  font-size: 12px; color: var(--dim); margin-bottom: 4px; }
.setup { max-width: 52rem; }
.step { border: 1px solid var(--line); border-radius: 4px; margin-bottom: 8px;
  background: var(--panel); }
.step > .head { display: flex; gap: 10px; align-items: baseline; padding: 12px 14px; }
.step .mark { font-weight: 700; width: 1.4rem; flex: none; }
.step.done .mark { color: var(--ok); }
.step.todo .mark { color: var(--warn); }
.step.todo { border-color: var(--warn-line); }
.step.done > .head { color: var(--dim); }
.step .what { font-weight: 600; }
.step .body { padding: 0 14px 14px 38px; }
.step .body p { margin: 0 0 10px; }
.step > .head.shut { cursor: pointer; user-select: none; }
.step > .head.shut:hover .caret { color: var(--accent); }
.step > .head .caret { color: var(--dim); width: 12px; flex: none; }
/* Every kind of hardware this driver knows, as rows rather than pills. A pill can
   only carry a name, so the models a name covers were shown after choosing it, which
   is the wrong way round for somebody holding a box that says GW1100. */
/* Two steps, because the list and the form do not fit on one screen together.
   Twenty-five kinds of hardware, each carrying the models it covers, is a thousand
   pixels before the first field of the form. Step one is the list and nothing else;
   step two is the form and nothing else. */
.steps { display: flex; align-items: center; gap: 10px; margin-bottom: 14px;
  padding-bottom: 12px; border-bottom: 1px solid var(--line); flex-wrap: wrap; }
.steps .at { display: inline-flex; align-items: center; gap: 8px; font-size: 13.5px;
  color: var(--dim); }
.steps .at.now { color: var(--ink); font-weight: 600; }
.steps .n { width: 21px; height: 21px; border-radius: 11px; background: var(--soft);
  color: var(--dim); font-size: 12px; font-weight: 600; display: inline-flex;
  align-items: center; justify-content: center; flex: none; }
.steps .at.now .n { background: var(--accent); color: #fff; }
.steps .sep { color: var(--dim); }
.hwrow { display: flex; align-items: center; gap: 12px; margin-bottom: 6px; }
#hwfind { max-width: 24rem; margin-bottom: 0; }
/* The list scrolls inside itself. Letting it push the rest of the checklist down
   is what put the form a screen and a half away in the first place. */
.hwlist { display: flex; flex-direction: column; gap: 1px; margin-bottom: 4px;
  max-height: 52vh; overflow-y: auto; }
.hwpicked { margin-bottom: 18px; }
.hwpicked b { font-size: 15px; }
.hwpicked .kit { color: var(--dim); font-size: 12.5px; margin-top: 3px; }
.hw { display: flex; align-items: baseline; gap: 12px; width: 100%; text-align: left;
  padding: 8px 11px; background: none; border: 1px solid transparent; border-radius: 4px;
  font: inherit; color: var(--ink); cursor: pointer; }
.hw:hover { background: var(--sink); }
.hw.on { border-color: var(--accent); background: var(--accent-soft); }
.hw .what { font-weight: 600; font-size: 13.5px; flex: none; min-width: 12rem; }
.hw .kit { color: var(--dim); font-size: 12.5px; flex: 1; min-width: 0; }
.hw .why { color: var(--dim); font-size: 12px; flex: none; white-space: nowrap; }
.hw[disabled] { opacity: .5; cursor: not-allowed; }
.hw[disabled]:hover { background: none; }
.hwhead { color: var(--dim); font-size: 13px; margin: 16px 0 6px; }
.hwhead b { color: var(--ink); font-size: 13.5px; }
.hwhead:first-child { margin-top: 4px; }
.settings { border-collapse: collapse; margin-bottom: 10px; }
.settings td, .settings th { border: 0; padding: 3px 14px 3px 0; text-transform: none;
  letter-spacing: 0; font-size: 13px; }
.settings td:first-child, .settings th { color: var(--dim); white-space: nowrap;
  font-weight: 400; }
.settings td:last-child { font-family: ui-monospace, Menlo, Consolas, monospace;
  font-weight: 600; font-size: 12.5px; }
select { background: var(--panel); color: var(--ink); border: 1px solid var(--line);
  border-radius: 4px; padding: 5px 7px; font: inherit; font-size: 12.5px;
  max-width: 240px; width: 100%; }
select:focus { outline: 2px solid var(--accent); outline-offset: -1px; }
.taken { color: var(--warn); font-size: 12px; }
.askentities { display: flex; flex-direction: column; gap: 3px; margin-bottom: 10px; }
.askentities label { display: flex; gap: 6px; align-items: baseline; }
.newcol { font-size: 12px; margin-top: 4px; }
.newcol code { background: var(--code); padding: 2px 5px; border-radius: 3px; }
.add { display: flex; gap: 6px; margin-top: 10px; flex-wrap: wrap; align-items: center; }
.knock { width: 100%; max-width: 30rem; border-collapse: collapse;
  margin: 8px 0 2px; font-size: 12px; }
.knock td { padding: 2px 8px 2px 0; border: 0; }
.knock td:nth-child(2) { text-align: right; font-variant-numeric: tabular-nums; }
.knock td:nth-child(3) { color: var(--dim); width: 42%; }
.made { border-left: 3px solid var(--ok); padding-left: 12px; margin: 12px 0 18px; }
.block { margin-bottom: 22px; }
.fold { cursor: pointer; display: flex; gap: 8px; align-items: baseline;
  padding: 8px 0; border-bottom: 1px solid var(--line); user-select: none; }
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
/* weewx.conf, a section at a time. The file is the only thing this view is about,
   so the section heading is written the way the file writes it: somebody who has to
   go and edit it over ssh afterwards is looking for '[[Defaults]]', not for a
   breadcrumb. */
.conf { max-width: 64rem; }
.conf .sec { margin-top: 20px; }
.conf .sechead { display: flex; gap: 10px; align-items: baseline; padding: 7px 0;
  border-bottom: 1px solid var(--line); user-select: none; }
.conf .sechead .path { font-family: ui-monospace, Menlo, Consolas, monospace;
  font-size: 13px; font-weight: 600; overflow-wrap: anywhere; }
.conf .sechead .caret { cursor: pointer; }
.conf .sechead .acts { margin-left: auto; display: flex; gap: 6px; flex: none; }
.conf .sechead .acts button.act { height: 26px; font-size: 12px; }
.conf .secwhy { color: var(--dim); font-size: 12px; margin: 6px 0 0;
  white-space: pre-wrap; }
.conf table { table-layout: fixed; }
.conf th.key { width: 24%; } .conf th.val { width: 52%; } .conf th.does { width: 24%; }
.conf th, .conf td { padding: 8px 14px 8px 0; }
/* The boxes fill the column. The 240px cap that suits a name field leaves a report
   path or a comma-separated list of six services showing about a third of itself. */
.conf input[type=text] { max-width: none; }
.conf #conffind { max-width: 30rem; }
.conf .why { color: var(--dim); font-size: 12px; margin-top: 4px;
  white-space: pre-wrap; overflow-wrap: anywhere; }
.conf tr.stale td { background: var(--warn-soft); }
.conf .held { color: var(--dim); font-size: 12.5px; font-style: italic; }
.conf .rowacts { display: flex; gap: 6px; }
.conf .rowacts button.act { height: 26px; font-size: 12px; }
#flash { position: fixed; right: 16px; bottom: 16px; background: var(--panel);
  border: 1px solid var(--line); border-radius: 4px; padding: 9px 14px; font-size: 13px;
  box-shadow: 0 6px 20px rgba(0,0,0,.13); display: none; max-width: 380px; }
</style>
</head>
<body>
<header>
  <div class="brand">
    <svg width="19" height="19" viewBox="0 0 16 16" aria-hidden="true"><rect width="16" height="16" rx="3.5" fill="var(--accent)"/><path d="M8 3 11.8 7.2H9.4v3.4H6.6V7.2H4.2z" fill="#fff"/><rect x="4.2" y="11.7" width="7.6" height="1.5" rx=".75" fill="#fff"/></svg>
    <h1>weewx-ultimate-push</h1>
    <span class="ver" id="ver"></span>
  </div>
  <nav class="views">
    <button data-view="stations" class="on">Stations</button>
    <button data-view="fields">Field map</button>
    <button data-view="conf">weewx.conf</button>
    <button data-view="setup">Checklist<span class="count" id="opencount"></span></button>
  </nav>
  <span class="meta" id="meta">loading</span>
</header>
<div id="alert"></div>
<main>
  <aside>
    <div class="side-head">
      <h2>Stations</h2>
      <button class="act primary" id="addstation">Add</button>
    </div>
    <input type="text" id="find" placeholder="Filter by name or ident">
    <div id="stations"></div>
    <div id="door"></div>
  </aside>
  <section>
    <div class="dhead" id="dhead"></div>
    <div class="tabs" id="subtabs">
      <button data-tab="console">Console</button>
      <button data-tab="readings" class="on">Readings</button>
      <button data-tab="raw">Raw uploads</button>
      <button data-tab="columns">Columns</button>
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

/* The two axes the page navigates on. The view is what the page is about, and
   the tab is what you want to know about the station you picked. Keeping them apart
   is the whole of this layout: every tab is about `chosen` and nothing else, so a
   tab can never mean something different depending on which view you came from. */
var chosen = null, view = 'stations', subtab = 'readings', state = null;
/* What has been typed into the filter over the station list. Held here rather than
   read off the input, because the list is redrawn every fifteen seconds and would
   otherwise come back unfiltered under whoever was typing. */
var finding = '';
var fieldsView = null, folded = {}, adding = false;
var setup = null, picked = null, watching = null, candidates = null;
/* Every station this driver knows, including the ones that have never uploaded.
   Read for the station list, and for the one question the setup form cannot answer
   on its own: whether there is already a main station to be moved aside. */
var stationList = null;
/* A main station about to be taken over, while the page explains what that does.
   Held here rather than in the DOM so that a redraw does not lose the question. */
var pending = null, editing = null, pendingDraw = false;
/* The options a driver's author ruled off as rarely needing attention start
   folded, which is what ruling them off meant. */
folded.driverrest = true;

/* What a source that has to be told what to read has been told, and what looking
   found. Held here rather than in the DOM because looking redraws the page, and a
   redraw would otherwise empty the two fields that were used to look. */
var asked = { what: '', address: '', token: '', found: null, chosen: {}, device: '' };

/* weewx.conf as the last read of it found it, what has been typed into the filter
   over it, and which sections have been folded away. The file is a few hundred
   settings, so folding is how a section is read on its own; it is remembered here
   because saving one setting redraws the lot. */
var confView = null, confFind = '', confShut = {};

/* The same word everywhere something is being fetched. A page that says one thing
   in one place and another somewhere else reads like two different waits. */
var LOADING = '<p class="dim">Loading.</p>';
/* Which draw is the current one. Every view here is drawn from a fetch, and picking
   a second station while the first one's readings are still in flight used to let
   the first answer land on the second station's page: the header said one station
   and the table under it was another's. Each draw takes a number, and an answer
   carrying an old one is answering a question nobody is asking any more. */
var drawn = 0;

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
    document.getElementById('ver').textContent = s.version;
    /* Labelled, because 'ecowitt, ambient' on its own reads like a list of stations
       rather than of what this listener will answer to. */
    document.getElementById('meta').innerHTML =
      '<span>up <b>' + Math.round(s.uptime / 60) + ' min</b></span>' +
      '<span>ports <b>' + esc(s.ports.join(', ')) + '</b></span>' +
      '<span class="answers" title="' + esc(s.protocols.join(', ')) +
        '">answers <b>' + esc(s.protocols.join(', ')) + '</b></span>';
    keepOrDrop();
    drawDoor(s.door);
    drawSidebar();
  });
}

function keepOrDrop() {
  /* Whether the station the detail side is showing still exists. Letting one in
     keeps its identity, so that move is safe; taking one out does not, and what was
     a station page would go on standing there saying nothing has arrived from it. */
  if (!chosen) return;
  var known = state.stations.filter(function (s) { return s.ident === chosen; });
  var knocking = state.waiting.filter(function (w) { return w.ident === chosen; });
  var quiet = (stationList ? stationList.stations : []).filter(function (s) {
    return s.ident === chosen;
  });
  if (known.length || knocking.length || quiet.length) return;
  /* A station set up here and never heard from is in stationList and nowhere else.
     While that list is being read again there is no telling one of those from one
     that has been taken out, so nothing is dropped until it is back. */
  if (!stationList) return;
  chosen = state.stations.length ? state.stations[0].ident : null;
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
    return !heard[s.ident] && !s.adopted && matches(s);
  }).map(function (s) {
    return '<div class="card quiet' + (shown(s.ident) ? ' on' : '') +
      '" data-ident="' + esc(s.ident) + '">' +
      '<div class="top"><span class="id">' + esc(s.name || s.ident) + '</span>' +
      stationTag(s) + '</div>' +
      '<div class="sub">' + esc(s.station_type || s.protocol || 'kind unknown') +
      '</div><div class="sub warn">' + (s.station_type
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


function matches(s) {
  /* The filter reads what is on the card: the name somebody gave the station and the
     identity its hardware sends. Not the protocol, because filtering two Ecowitts by
     'ecowitt' leaves two Ecowitts. */
  if (!finding) return true;
  var needle = finding.toLowerCase();
  return String(s.name || '').toLowerCase().indexOf(needle) >= 0 ||
    String(s.ident || '').toLowerCase().indexOf(needle) >= 0;
}

function stationTitle(s) {
  /* Named, or not named yet. Every station arrives unnamed, because what a console
     sends as its identity is a PASSKEY or a serial, and until somebody names it that
     string is all there is to call it by. Set as code, because that is what it is. */
  return s.name
    ? '<b>' + esc(s.name) + '</b>'
    : '<b class="mono">' + esc(s.ident) + '</b>';
}

function stationTag(s) {
  return s.role === 'extra'
    ? '<span class="tag">EXTRA ' + (s.channel || '?') + '</span>'
    : '<span class="tag main">MAIN</span>';
}

function shown(ident) {
  /* Whether this station is the one on the right. The pick is kept while you look at
     the field map or the checklist, so that coming back lands where you left, but
     marking a card there would say the page is about that station when it is not. */
  return view === 'stations' && ident === chosen;
}

function refusedRow(ident) {
  /* Whether this identity is one being turned away rather than one recording. The
     two are different enough that they cannot share a detail page: one has readings
     and columns, the other has a decision. */
  if (!state) return null;
  return state.waiting.filter(function (w) { return w.ident === ident; })[0] || null;
}

function recordingCards() {
  return state.stations.filter(matches).map(function (s) {
    return '<div class="card' + (shown(s.ident) ? ' on' : '') +
      '" data-ident="' + esc(s.ident) + '">' +
      '<div class="top"><span class="id' + (s.name ? '' : ' mono') +
      '" title="' + esc(s.ident) + '">' + esc(s.name || s.ident) + '</span>' +
      stationTag(s) + '</div>' +
      '<div class="sub">' + esc(s.protocol || '?') +
      (s.dialect && s.dialect !== s.protocol ? ' \\u00b7 ' + esc(s.dialect) : '') +
      ' \\u00b7 ' + s.field_count + ' fields \\u00b7 ' + ago(s.last_seen) + '</div>' +
      (s.undecided_count ? '<div class="sub warn">' + s.undecided_count +
        ' waiting for a placement</div>' : '') +
      (s.held_back ? '<div class="sub warn">Nothing recorded: waiting for the main ' +
        'station, which has not uploaded since this driver started.</div>' : '') +
      '</div>';
  }).join('');
}

function refusedCards() {
  /* The card says who and how often, and nothing else. What somebody needs to decide
     whether to let it in is its readings, and those are too much for a column this
     wide: clicking the card opens them beside it. */
  return state.waiting.filter(matches).map(function (w) {
    return '<div class="card refused' + (shown(w.ident) ? ' on' : '') +
      '" data-ident="' + esc(w.ident) + '">' +
      '<div class="top"><span class="id mono" title="' + esc(w.ident) + '">' +
      esc(w.ident) + '</span></div>' +
      '<div class="sub">' + esc(w.protocol || '?') + ' from ' + esc(w.client) +
      '</div><div class="sub">' + w.uploads + ' turned away \\u00b7 ' +
      ago(w.last_seen) + '</div></div>';
  }).join('');
}

function drawSidebar() {
  /* One list, in the order somebody meets these: what is working, what is knocking,
     what has been set up and is still silent. They were three places before, two of
     them off this list entirely, and a console being refused could sit unnoticed
     under a tab nobody had opened. */
  var box = document.getElementById('stations');
  var recording = recordingCards();
  var refused = refusedCards();
  var silent = waitingCards();
  var html = (refused ? '<h2>Being refused</h2>' + refused : '') +
    (recording ? '<h2>Recording</h2>' + recording : '') +
    (silent ? '<h2>Set up, not heard yet</h2>' + silent : '');
  if (!html) {
    html = '<p class="dim" style="font-size:13px">' + (finding
      ? 'Nothing here matches that.'
      : 'Nothing has uploaded yet. The checklist says what to put into the ' +
        'console.') + '</p>';
  }
  box.innerHTML = html;
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
    drawAlert();
    /* The first visit lands on what there is to do, not on an empty field table. */
    if (!s.done && was === undefined) view = 'setup';
    /* Something arrived while we were waiting. Show it, once the page is not in
       the middle of being used. */
    if (was && was !== s.next) pendingDraw = true;
    if (pendingDraw && !busy()) { pendingDraw = false; drawSidebar(); draw(); }
    if (then) then();
  });
}

function drawAlert() {
  /* The one line of the checklist that has to be readable from anywhere, because a
     station page can look entirely healthy while the reason nothing is recorded sits
     two views away. Only the count and the titles: the sentences and the buttons stay
     on the checklist, so there is one place to keep them right.

     Being refused is the loud one. The rest are decisions somebody has not made yet;
     that one is a console uploading into nothing, every minute, until somebody says
     whether it is theirs. */
  var box = document.getElementById('alert');
  var count = document.getElementById('opencount');
  var open = setup ? setup.steps.filter(function (s) {
    return !s.done && !s.optional;
  }) : [];
  count.textContent = open.length;
  count.classList.toggle('on', open.length > 0);
  if (!open.length) { box.className = ''; box.innerHTML = ''; return; }
  var loud = open.filter(function (s) { return s.id === 'refused'; }).length;
  box.className = loud ? 'on bad' : 'on';
  box.innerHTML = '<b>' + open.length +
    (open.length === 1 ? ' check is outstanding.' : ' checks are outstanding.') +
    '</b><span>' + esc(open.map(function (s) { return s.title; }).join(' \\u00b7 ')) +
    '</span><button class="act" data-view="setup">Open the checklist</button>';
}

function settle(mine, box, html) {
  /* Put an answer on the page, unless the page has moved on. See `drawn`. */
  if (mine !== drawn) return;
  box.innerHTML = html;
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
     set up. The Console tab keeps this for good and is where somebody comes back
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
      'station’s columns. It is on its Console tab too, for when the console ' +
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
     do have to know is what to do next, which is what the groups say.

     Nothing is chosen until somebody chooses it. Opening on the first entry looked
     helpful and was not: it put a form for an Ecowitt under the list for everybody,
     including the person who owns a Vantage. */
  if (!ways) { loadWays(); return LOADING; }
  if (!ways.ways.length) {
    return '<p class="dim">No hardware this driver can read.</p>';
  }
  var one = wayFor(picked);
  return hwSteps(one) + (one ? hwForm(one) : hwChoose());
}

function hwSteps(one) {
  /* Where you are, and the way back. The back button carries the name of what was
     chosen rather than the word 'back', because that name is the one thing somebody
     wants to check while they are filling the form in. */
  var first = one
    ? '<button class="act" id="hwback">\u2190 ' + esc(one.label) + '</button>'
    : '<span class="at now"><span class="n">1</span>Choose the hardware</span>';
  return '<div class="steps">' + first + '<span class="sep">\u203a</span>' +
    '<span class="at' + (one ? ' now' : '') + '"><span class="n">2</span>' +
    'Set it up</span></div>';
}

function hwChoose() {
  /* The search box is outside the list it filters, and typing replaces only the
     list. Redrawing the box under somebody's cursor takes the focus with it, and
     they lose the rest of what they were typing. */
  return '<div class="hwrow">' +
    '<input type="text" id="hwfind" autocomplete="off" ' +
    'placeholder="Search by make or model" value="' + esc(hwfind) + '">' +
    '<span class="dim" style="font-size:12.5px" id="hwcount">' + hwCount() +
    '</span></div>' +
    '<div class="hwlist" id="hwlist">' + hwGroups() + '</div>';
}

function hwCount() {
  var all = ways.ways.length;
  var hits = ways.ways.filter(hwMatches).length;
  if (hits === all) return all + ' kinds of station';
  return hits + ' of ' + all;
}

function hwForm(one) {
  return '<div class="hwpicked"><b>' + esc(one.label) + '</b>' +
    (one.hardware ? '<div class="kit' + (one.kind === 'driver' ? ' mono' : '') +
      '">' + esc(one.hardware) + '</div>' : '') + '</div>' +
    (one.kind === 'driver' ? fetchBody(one)
      : (one.how === 'fetch' ? askBody(one) : pointBody(one)));
}

function hwMatches(one) {
  /* Over the model list as well as the name. Somebody who has a GW1100 does not know
     that Ecowitt is what this driver calls it, and that is exactly the person the
     search is for. */
  if (!hwfind) return true;
  var needle = hwfind.toLowerCase();
  return (one.label + ' ' + (one.hardware || '')).toLowerCase()
    .indexOf(needle) >= 0;
}

function hwGroups() {
  var out = GROUPS.map(groupOfWays).join('');
  if (out) return out;
  return '<p class="dim" style="padding:8px 0">Nothing here matches ' +
    '\u2018' + esc(hwfind) + '\u2019. It may be hardware this driver does not ' +
    'read yet.</p>';
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

function groupOfWays(group) {
  var mine = ways.ways.filter(function (one) {
    return one.how === group[0] && hwMatches(one);
  });
  if (!mine.length) return '';
  return '<p class="hwhead"><b>' + esc(group[1]) + '</b> ' + esc(group[2]) + '</p>' +
    mine.map(function (one) {
      var why = one.problem ? esc(one.problem)
        : (one.taken ? 'already set up'
          : (one.enabled === false ? 'not switched on' : ''));
      return '<button class="hw" data-pick="' + esc(wayKey(one)) + '"' +
        (one.problem || one.taken ? ' disabled' : '') + '>' +
        '<span class="what">' + esc(one.label) + '</span>' +
        '<span class="kit' + (one.kind === 'driver' ? ' mono' : '') + '">' +
        esc(one.hardware || '') + '</span>' +
        (why ? '<span class="why">' + why + '</span>' : '') +
        '</button>';
    }).join('');
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
     to recognise, nothing to learn and nothing to let in afterwards.

     Unless it has to be told what to read. A sensor answers with whatever it
     measures and there is nothing to choose; something that reads a whole house has
     everything in it, and which of that is weather is a question only its owner can
     answer. So that one gets a token, a look, and a list to tick. */
  if (asked.what !== one.name) {
    asked = { what: one.name, address: '', token: '', found: null,
              chosen: {}, device: '' };
  }
  return '<table class="settings">' +
    '<tr><th>address</th><td><input data-askaddr placeholder="1.2.3.4" size="24"' +
    ' value="' + esc(asked.address) + '"></td></tr>' +
    (one.discovers
      ? '<tr><th>token</th><td><input data-asktoken type="password" size="24"' +
        ' value="' + esc(asked.token) + '"></td></tr>'
      : '') +
    '<tr><th>asked every</th><td><input data-askevery value="60" size="5"> seconds' +
    '</td></tr>' +
    '<tr><th>role</th><td>' + hostedRoleSelect(mainStation() ? 'extra' : 'main') +
    '</td></tr>' +
    '<tr><th>name</th><td><input data-askname value="' + esc(one.name) + '"></td>' +
    '</tr></table>' +
    (one.notes || []).map(function (note) {
      return '<p class="dim">' + esc(note) + '</p>';
    }).join('') +
    (one.discovers ? askFound(one) : '') +
    '<p><button class="act" data-askadd="' + esc(one.name) +
    '">Ask it and set it up</button></p>' +
    '<p class="dim">It is asked once before anything is saved. If nothing answers ' +
    'at that address, or something answers that is not a ' + esc(one.label) +
    ', nothing is written and the reason is shown here.</p>' + roleNote();
}

function askFound(one) {
  /* What is there, for somebody to pick from. Nothing is recorded by looking, and
     nothing is ticked that was not offered: a sensor is read because it was chosen.

     The first device's sensors come ticked, because that is the suggestion and
     because a list of thirty with nothing ticked is work rather than help. */
  if (!asked.found) {
    return '<p><button class="act" data-askfind="' + esc(one.name) +
      '">Find the sensors</button></p>' +
      '<p class="dim">Nothing is saved by looking. What comes back is a list of ' +
      'the sensors this driver can record, grouped by the device they belong to.' +
      '</p>';
  }
  return '<p><button class="act" data-askfind="' + esc(one.name) +
    '">Look again</button></p>' +
    asked.found.map(askDevice).join('') +
    '<p class="dim">One station is one device. Ticking a sensor of another device ' +
    'unticks the first, because two devices in one station would take turns ' +
    'writing the same column. Set the second one up as a station of its own.</p>';
}

function askDevice(group) {
  /* One device and its sensors. A device Home Assistant could not name is still
     shown: its sensors are as real as any other's, and leaving them out would be
     this page deciding they do not exist. */
  return '<p><b>' + esc(group.device || 'Not part of any device') + '</b></p>' +
    '<div class="askentities">' + group.entities.map(function (e) {
      return '<label><input type="checkbox" data-askentity="' + esc(e.entity_id) +
        '" data-askdevice="' + esc(group.device_id) + '"' +
        (asked.chosen[e.entity_id] ? ' checked' : '') + '> ' +
        esc(e.name || e.entity_id) + ' <span class="dim">' + esc(e.device_class) +
        (e.unit ? ', ' + esc(e.unit) : '') +
        (e.state ? ', now ' + esc(e.state) : '') + '</span></label>';
    }).join('') + '</div>';
}

function askTyped() {
  /* What is in the two fields right now, kept before a redraw empties them. */
  var address = document.querySelector('[data-askaddr]');
  var token = document.querySelector('[data-asktoken]');
  asked.address = address ? address.value : '';
  asked.token = token ? token.value : '';
}

function askChosen() {
  /* The entity ids that are ticked, in the order they were offered. */
  var out = [];
  asked.found ? asked.found.forEach(function (group) {
    group.entities.forEach(function (e) {
      if (asked.chosen[e.entity_id]) out.push(e.entity_id);
    });
  }) : null;
  return out;
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

function refresh(then) {
  /* Everything the page draws from, in the order the parts depend on each other. The
     station list comes first because keepOrDrop reads it to decide whether the
     station on the right is still there, and the suggestions are dropped because who
     holds which column can have changed. */
  candidates = null;
  return loadStations().then(loadState).then(loadSetup).then(function () {
    draw();
    if (then) then();
  });
}

function choose(ident) {
  chosen = ident;
  editing = null;
  /* Picking a station is not picking what to know about it. Somebody comparing the
     raw uploads of two consoles would otherwise be put back on Readings for every
     station they click. The one tab that cannot survive the move is Readings on a
     station being refused, which has none; markNav settles that. */
  if (view !== 'stations') view = 'stations';
  drawSidebar();
  draw();
}

function draw() {
  var box = document.getElementById('body');
  drawn += 1;
  drawHead();
  markNav();
  if (view === 'setup') return drawSetup(box);
  if (view === 'fields') { box.innerHTML = LOADING; return drawFields(box); }
  if (view === 'conf') return drawConf(box);
  return drawStations(box);
}

function show(which) {
  /* Leaving the checklist abandons a half-filled add form, which is what clicking
     away from it means. The hardware goes with it, so coming back starts at the
     first step rather than in the middle of somebody else's choice. */
  if (which !== 'setup') { adding = false; picked = null; }
  /* Coming to weewx.conf reads it again. It is a file other people edit, over ssh
     and with weectl, and a cached copy of somebody else's file is the one thing this
     view must not show. Which sections are folded is not the file, so it stays. */
  if (which === 'conf') confView = null;
  view = which;
  draw();
}

function showTab(which) {
  subtab = which;
  draw();
}

function markNav() {
  document.querySelectorAll('nav.views button').forEach(function (b) {
    b.classList.toggle('on', b.dataset.view === view);
  });
  document.querySelectorAll('.tabs button').forEach(function (b) {
    b.classList.toggle('on', b.dataset.tab === subtab);
  });
  /* The tabs are about one station that is recording. A station being refused has no
     readings, no uploads kept and no columns, and offering the tabs for it would be
     four ways to reach the same empty page. */
  document.getElementById('subtabs').style.display =
    view === 'stations' && chosen && !refusedRow(chosen) ? 'flex' : 'none';
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


function readingsTable(s) {
  return '<table><thead><tr><th class="raw">Raw field</th>' +
    '<th class="value">Last value</th><th class="goes">WeeWX field</th>' +
    '<th class="group">Group</th><th class="state">Column</th>' +
    '<th class="why">How</th></tr></thead>' +
    '<tbody>' + s.rows.map(function (f) { return fieldRow(s, f); }).join('') +
    '</tbody></table>';
}

function roleSwap(s) {
  return '<div class="add" style="margin:0 0 16px">' +
    '<button class="act" data-role="' + (s.role === 'main' ? 'extra' : 'main') +
    '" data-ident="' + esc(s.ident) + '">Make it ' +
    (s.role === 'main' ? 'an extra sensor' : 'the main station') +
    '</button><span class="dim" style="font-size:12px">' + (s.role === 'main'
      ? 'Its readings would move off outTemp and the rest, onto a channel of ' +
        'their own.'
      : 'Its readings would move onto outTemp and the rest, which is what a ' +
        'WeeWX report reads.') + '</span></div>';
}

function stationFields(s, several) {
  var open = !folded[s.ident];
  var role = s.role === 'extra'
    ? 'extra sensor on channel ' + (s.channel || '?')
    : 'the main station';
  var head = '<div class="fold" data-fold="' + esc(s.ident) + '">' +
    '<span class="caret">' + (open ? '\\u25be' : '\\u25b8') + '</span>' +
    stationTitle(s) +
    '<span class="dim">' + esc(s.protocol || '?') + ' \\u00b7 ' + role +
    ' \\u00b7 ' + s.rows.length + ' fields</span></div>';
  if (!open) return '<div class="block">' + head + '</div>';
  return '<div class="block">' + head +
    (several && !s.declared ? roleSwap(s) : '') + readingsTable(s) + '</div>';
}

/* ---------------------------------------------------------------- stations */


function drawHead() {
  /* Who this page is about, above the tabs, so that it stays put while they change.
     The two views that are not about one station say what they are about instead:
     an empty header over a full page reads like something failed to load. */
  var box = document.getElementById('dhead');
  if (view === 'setup') {
    box.innerHTML = '<div class="name"><b>Checklist</b></div><div class="about">' +
      'What still stands between this driver and a station that records ' +
      'everything.</div>';
    return;
  }
  if (view === 'fields') {
    box.innerHTML = '<div class="name"><b>Field map</b></div><div class="about">' +
      'Every reading of every station, and which column it fills. The question is ' +
      'not what one station sends, it is who fills outTemp.</div>';
    return;
  }
  if (view === 'conf') {
    box.innerHTML = '<div class="name"><b>weewx.conf</b></div>' +
      '<div class="about"><span>The file itself, section by section. Everything ' +
      'else on this page takes effect on the next upload; this takes effect at the ' +
      'next restart.</span>' +
      (confView && confView.path
        ? '<span class="mono">' + esc(confView.path) + '</span>' : '') +
      '</div>';
    return;
  }
  if (!chosen) { box.innerHTML = ''; return; }
  var turned = refusedRow(chosen);
  if (turned) {
    box.innerHTML = '<div class="name"><b class="mono">' + esc(turned.ident) +
      '</b><span class="tag">REFUSED</span></div><div class="about">' +
      '<span>' + esc(turned.protocol || 'protocol unknown') + '</span>' +
      '<span class="mono">' + esc(turned.client) + '</span>' +
      '<span>' + turned.uploads + ' uploads turned away</span>' +
      '<span>last ' + ago(turned.last_seen) + '</span></div>';
    return;
  }
  var s = state.stations.filter(function (x) { return x.ident === chosen; })[0];
  if (!s) {
    /* Set up here and still silent. It has a name and a path and nothing else, so
       the header says the name and the tabs go to the Console tab that holds the
       path. */
    var quiet = (stationList ? stationList.stations : []).filter(function (x) {
      return x.ident === chosen;
    })[0];
    box.innerHTML = quiet
      ? '<div class="name"><b>' + esc(quiet.name || quiet.ident) + '</b>' +
        stationTag(quiet) + '</div><div class="about"><span>' +
        esc(quiet.station_type || quiet.protocol || 'kind unknown') +
        '</span><span>never heard from</span></div>'
      : '';
    return;
  }
  box.innerHTML = '<div class="name">' + stationTitle(s) + stationTag(s) +
    '<span class="acts"><button class="act" data-tab="console">Console ' +
    'settings</button></span></div>' +
    '<div class="about">' + (s.name
      ? '<span class="mono">' + esc(s.ident) + '</span>' : '') +
    '<span>' + esc(s.protocol || '?') +
    (s.dialect && s.dialect !== s.protocol ? ' \\u00b7 ' + esc(s.dialect) : '') +
    '</span><span>' + s.field_count + ' readings</span>' +
    '<span>last upload ' + ago(s.last_seen) + '</span>' +
    (s.undecided_count
      ? '<span class="warn">' + s.undecided_count + ' waiting for a placement</span>'
      : '') + '</div>';
}

function drawStations(box) {
  /* The second axis. Everything under here is about `chosen` and nothing else, which
     is what makes the tabs mean one thing: before this, two of the five tabs read
     the station on the left and three ignored it. */
  if (!chosen) {
    box.innerHTML = state && state.stations.length
      ? '<p class="dim">Pick a station on the left.</p>'
      : '<p class="dim">Nothing has uploaded yet. The checklist says what to put ' +
        'into the console.</p>';
    return;
  }
  if (refusedRow(chosen)) return drawRefused(box);
  box.innerHTML = LOADING;
  if (subtab === 'console') return drawConsole(box);
  if (subtab === 'raw') return drawRaw(box);
  if (subtab === 'columns') return drawColumns(box);
  return drawReadings(box);
}

function drawRefused(box) {
  /* The decision, with what it takes to make it. An address cannot tell your own new
     console from a stranger's; nine degrees and ninety per cent can, so the readings
     are the page rather than a thing to unfold. */
  var w = refusedRow(chosen);
  var sample = w.sample || {};
  var rows = (sample.readings || []).map(function (r) {
    return '<tr><td class="mono">' + esc(r.raw) + '</td><td>' + esc(r.value) +
      '</td><td class="dim">' + (r.field ? '\\u2192 ' + esc(r.field) : '') +
      '</td></tr>';
  }).join('');
  box.innerHTML = '<div class="setup">' +
    '<div class="note bad">This driver answers to the consoles it knows. A second ' +
    'one numbering its channels from one would otherwise write into the same ' +
    'columns, and afterwards neither could be recovered. Let it in if it is ' +
    'yours.</div>' +
    (rows
      ? '<h2>What it last sent</h2><table class="knock"><tbody>' + rows +
        '</tbody></table>'
      : '<p class="dim">Nothing readable in what it sent.</p>') +
    '<div class="add"><input type="text" placeholder="name it" data-name="' +
    esc(w.ident) + '">' +
    '<button class="act primary" data-accept="' + esc(w.ident) + '">Let it in' +
    '</button>' +
    '<button class="act" data-notmine="' + esc(w.ident) + '">Not mine</button>' +
    '<button class="act" data-knock="0">Show the upload</button></div>' +
    movedPicker(w.ident) +
    '<div id="knockraw0" style="display:none">' +
    '<div class="row" style="margin-top:8px;justify-content:flex-end">' +
    '<button class="act" data-knockcopy="0">Copy</button></div>' +
    '<pre id="knocktext0">' + esc(sample.text || '') + '</pre></div></div>';
}

function drawConsole(box) {
  /* What to put into the console, and what this station is called. Shown every time
     rather than once: the checklist stops mentioning it as soon as the station is
     heard, and a console reset a year later needs it again. */
  var mine = drawn;
  loadStations().then(function (d) {
    if (!d.ok) {
      settle(mine, box, '<p class="bad">' + esc(d.error || '') + '</p>');
      return;
    }
    var s = d.stations.filter(function (x) { return x.ident === chosen; })[0];
    if (!s) {
      settle(mine, box, '<p class="dim">This station has uploaded, but the settings ' +
        'file has no record of it. The checklist can give it a name.</p>');
      return;
    }
    settle(mine, box, '<div class="setup">' +
      (pending && pending.what === 'edit' ? confirmBox() : '') +
      stationBody(s, editing === s.ident) +
      '<p class="dim">One station is the main station. Its readings go to outTemp, ' +
      'barometer and the rest, which is what a WeeWX report reads. Every other ' +
      'station is a sensor beside it: temperature and humidity go to a channel of ' +
      'their own, and what has nowhere to go is dropped rather than written over ' +
      'the main station\\u2019s.</p>' +
      '<p class="dim">Changed here, kept in ' + esc(d.settings_file) + '.</p></div>');
  });
}

function drawReadings(box) {
  /* One station's readings. The same rows the field map draws, without the fold: on
     a page that is already about this station, a heading with its name on it and a
     triangle to collapse it is furniture. */
  var mine = drawn;
  Promise.all([api('fields'), loadCandidates()]).then(function (both) {
    var d = both[0];
    if (!d.ok) { settle(mine, box, '<p class="bad">' + esc(d.error) + '</p>'); return; }
    fieldsView = d;
    var s = d.stations.filter(function (x) { return x.ident === chosen; })[0];
    if (!s) {
      settle(mine, box, '<p class="dim">Nothing has arrived from this station yet. ' +
        'The Console tab has the path to put into it.</p>');
      return;
    }
    settle(mine, box, (s.declared ? '' : roleSwap(s)) + readingsTable(s));
  });
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
        'nothing here to change: what it wants is a name, and the checklist gives ' +
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
  var mine = drawn;
  Promise.all([api('fields'), loadCandidates()]).then(function (both) {
    var d = both[0];
    if (!d.ok) { settle(mine, box, '<p class="bad">' + esc(d.error) + '</p>'); return; }
    fieldsView = d;
    if (!d.stations.length) {
      settle(mine, box, '<p class="dim">Nothing has uploaded yet.</p>');
      return;
    }
    var several = d.stations.length > 1;
    settle(mine, box, d.stations.map(function (s) {
      return stationFields(s, several);
    }).join(''));
  });
}


/* ---------------------------------------------------------------- weewx.conf */

/* The one view that is not about this driver. Everything else on this page takes
   effect on the next upload; these take effect at the next restart, and half of them
   belong to services this driver has never heard of. What it buys is that the file
   is readable from here at all: today the answer to "what is my archive interval"
   is an ssh session, and the answer to "why is nothing in the report" is often two
   lines further down the same file. */

function drawConf(box) {
  /* Drawn from the last read rather than a fresh one, so that folding a section or
     typing in the filter does not fetch a few hundred settings again. Every write
     clears it, which is what makes the page show the file rather than a memory of
     it. */
  if (confView) { box.innerHTML = confHtml(confView); return; }
  var mine = drawn;
  box.innerHTML = LOADING;
  api('conf').then(function (d) {
    confView = d;
    // The header names the file, and it was drawn before there was one to name.
    drawHead();
    settle(mine, box, confHtml(d));
  });
}

function confHtml(d) {
  if (!d.ok) return '<p class="bad">' + esc(d.error) + '</p>';
  return '<div class="conf">' + confNote(d) +
    '<div class="row">' +
    '<input type="text" id="conffind" placeholder="Filter by section, setting, ' +
    'value or comment" value="' + esc(confFind) + '">' +
    '<button class="act" data-conffold="all">Fold all</button>' +
    '<button class="act" data-conffold="none">Unfold all</button>' +
    (d.writable
      ? '<button class="act" data-confnewsec="">Add a section</button>' : '') +
    '</div><div id="confsecs">' + confSections(d) + '</div></div>';
}

function confNote(d) {
  /* Two different pieces of news, and only one of them is about this page. Which
     one comes first is which one changes what somebody can do next. */
  var html = '';
  if (!d.writable) {
    html += '<div class="note"><b>This page can read ' + esc(d.path) +
      ' and not write it.</b> Under a package installation the file belongs to root ' +
      'while WeeWX runs as another user. Every setting below still has a button that ' +
      'copies the line with its headings, ready to paste into the file.</div>';
  } else {
    html += '<div class="note"><b>A change here takes effect when WeeWX ' +
      'restarts.</b> The engine read this file at startup and a driver cannot ' +
      'restart the engine it is part of. What the file said before the most recent ' +
      'change from this page is kept in <code>' + esc(d.backup) + '</code>.</div>';
  }
  if (d.stale) {
    html += '<div class="note">' + d.stale + ' setting' +
      (d.stale === 1 ? '' : 's') + ' in this file no longer ' +
      (d.stale === 1 ? 'matches' : 'match') + ' what WeeWX is running on. The rows ' +
      'are marked, and each one says what the engine has until it is restarted.</div>';
  }
  return html;
}

function confSections(d) {
  var drawnAny = 0;
  var html = d.sections.map(function (s, i) {
    var rows = [];
    s.entries.forEach(function (e, j) {
      if (confMatches(s, e)) rows.push(confRow(i, j, e, d.writable));
    });
    /* A filter that matches nothing in a section hides the section. Without that,
       narrowing to 'interval' leaves sixty empty headings to scroll past. */
    if (confFind && !rows.length) return '';
    drawnAny += 1;
    var key = s.path.join('/');
    /* Folding is off while a filter is on: what the filter found is the point of
       typing it, and finding it folded away would be the wrong answer. */
    var shut = !confFind && !!confShut[key];
    return '<div class="sec"><div class="sechead">' +
      '<span class="caret" data-conftoggle="' + esc(key) + '">' +
      (shut ? '\\u25b8' : '\\u25be') + '</span>' +
      '<span class="path" data-conftoggle="' + esc(key) + '">' + esc(s.heading) +
      '</span><span class="dim">' + rows.length + ' of ' + s.entries.length +
      '</span><span class="acts">' + confSectionActs(s, i, d.writable) +
      '</span></div>' +
      (shut ? '' : (s.comment
        ? '<p class="secwhy">' + esc(s.comment) + '</p>' : '') +
        (rows.length ? confTable(rows) : '<p class="dim secwhy">No settings of its ' +
          'own. What is under it follows.</p>')) +
      '</div>';
  }).join('');
  if (!drawnAny) return '<p class="dim">Nothing in the file matches that.</p>';
  return html;
}

function confSectionActs(s, i, writable) {
  if (!writable) return '';
  return '<button class="act" data-confadd="' + i + '">Add a setting</button>' +
    (s.path.length
      ? '<button class="act" data-confdropsec="' + i + '">Remove</button>' : '');
}

function confTable(rows) {
  return '<table><thead><tr><th class="key">Setting</th>' +
    '<th class="val">Value</th><th class="does"></th></tr></thead>' +
    '<tbody>' + rows.join('') + '</tbody></table>';
}

function confRow(i, j, e, writable) {
  /* Addressed by its place in the answer rather than by its name. A key is whatever
     the file says it is, and a selector built out of one would break on the first
     setting with a quote in it. */
  var at = i + ':' + j;
  var box = e.single
    ? '<input type="text" data-confval="' + at + '" value="' + esc(e.value) + '"' +
      (e.hidden ? ' placeholder="set, and not shown here"' : '') + '>'
    : '<pre>' + esc(e.value) + '</pre>';
  return '<tr' + (e.differs ? ' class="stale"' : '') + '>' +
    '<td><span class="mono">' + esc(e.key) + '</span>' +
    (e.comment ? '<div class="why">' + esc(e.comment) + '</div>' : '') + '</td>' +
    '<td>' + box + confWhy(e) + '</td>' +
    '<td><div class="rowacts">' + confRowActs(at, e, writable) +
    '</div></td></tr>';
}

function confWhy(e) {
  var html = '';
  if (e.inline) html += '<div class="why">' + esc(e.inline) + '</div>';
  if (e.hidden) {
    html += '<div class="why">The name says this holds a secret, and this page is ' +
      'HTTP, so the value is not sent to it. Typing one replaces it.</div>';
  }
  if (!e.single) {
    html += '<div class="why">This value runs over more than one line, so it is ' +
      'shown here and changed in the file.</div>';
  }
  if (e.differs) {
    html += '<div class="why warn">WeeWX is running on ' +
      (e.running ? '<code>' + esc(e.running) + '</code>' : 'something else') +
      ' until it is restarted.</div>';
  }
  return html;
}

function confRowActs(at, e, writable) {
  if (!e.single) return '';
  if (!writable) {
    return '<button class="act" data-confline="' + at + '">Copy the line</button>';
  }
  return '<button class="act" data-confsave="' + at + '">Save</button>' +
    '<button class="act" data-confdrop="' + at + '">Remove</button>';
}

function confMatches(s, e) {
  if (!confFind) return true;
  return (s.heading + ' ' + s.path.join(' ') + ' ' + e.key + ' ' + e.value + ' ' +
    e.comment + ' ' + e.inline).toLowerCase().indexOf(confFind.toLowerCase()) >= 0;
}

function confAt(at) {
  /* The section and the setting a data attribute names, or nulls when the answer
     has been reloaded under it. */
  var parts = String(at).split(':');
  var s = confView && confView.sections ? confView.sections[+parts[0]] : null;
  if (!s) return { section: null, entry: null };
  return { section: s, entry: s.entries[+parts[1]] || null };
}

function confTyped(at) {
  var box = document.querySelector('[data-confval="' + at + '"]');
  return box ? box.value : null;
}

function confSave(at) {
  var found = confAt(at);
  if (!found.entry) { flash('Reload the page.', true); return; }
  var typed = confTyped(at);
  if (typed === null) return;
  if (found.entry.hidden && !typed.trim()) {
    flash('Type the new value. An empty box here would wipe the one in the file.',
      true);
    return;
  }
  api('conf/set', {
    section: found.section.path, key: found.entry.key, value: typed
  }).then(confThen);
}

function confDrop(at) {
  var found = confAt(at);
  if (!found.entry) { flash('Reload the page.', true); return; }
  if (!window.confirm('Take ' + found.entry.key + ' out of ' +
      found.section.heading + '?\\nWhatever WeeWX does without it is what it ' +
      'will do after the next restart.')) {
    return;
  }
  api('conf/remove', {
    section: found.section.path, key: found.entry.key
  }).then(confThen);
}

function confAdd(i) {
  var s = confView && confView.sections ? confView.sections[i] : null;
  if (!s) { flash('Reload the page.', true); return; }
  var key = (window.prompt('The name of a setting to add to ' + s.heading + '.',
    '') || '').trim();
  if (!key) return;
  var value = window.prompt('What ' + key + ' should be. Written as the file writes ' +
    'it: several values separated by commas are a list, and a value that holds a ' +
    'comma of its own goes in quotes.', '');
  if (value === null) return;
  api('conf/add', { section: s.path, key: key, value: value }).then(confThen);
}

function confNewSection() {
  var where = (window.prompt('A section to add. Give the whole path, one heading ' +
    'per line, outermost first, the way the file nests them.\\n\\n' +
    'StdReport\\nMyReport', '') || '').trim();
  if (!where) return;
  var path = where.split('\\n').map(function (one) { return one.trim(); })
    .filter(function (one) { return one; });
  api('conf/section', { section: path }).then(confThen);
}

function confDropSection(i) {
  var s = confView && confView.sections ? confView.sections[i] : null;
  if (!s) { flash('Reload the page.', true); return; }
  if (!window.confirm('Take ' + s.heading + ' out of the file, with everything ' +
      'under it?')) {
    return;
  }
  api('conf/remove-section', { section: s.path }).then(function (d) {
    /* A section that holds something is refused once and asked about again, with
       the count in the question. The driver counts it, because the page has the
       section it clicked on and not the ones nested inside it. */
    if (!d.ok && /holds \\d+ settings/.test(d.message || '')) {
      if (!window.confirm(d.message + '\\n\\nRemove it anyway?')) return;
      api('conf/remove-section', { section: s.path, force: true }).then(confThen);
      return;
    }
    confThen(d);
  });
}

function confLine(at) {
  /* For the installation where the file is root's. The headings go with the line,
     because a setting pasted into the wrong section is a setting that does nothing
     and reads as though it should. */
  var found = confAt(at);
  if (!found.entry) { flash('Reload the page.', true); return; }
  var typed = confTyped(at);
  var lines = [];
  found.section.path.forEach(function (name, depth) {
    var marks = depth + 1;
    lines.push(new Array(depth + 1).join('    ') +
      new Array(marks + 1).join('[') + name + new Array(marks + 1).join(']'));
  });
  lines.push(new Array(found.section.path.length + 1).join('    ') +
    found.entry.key + ' = ' + (typed === null ? found.entry.value : typed));
  copy(lines.join('\\n') + '\\n', 'the line and its headings');
}

function confThen(d) {
  flash(d.ok ? 'Written. It takes effect at the next restart.' :
    d.message || 'That did not work.', !d.ok);
  /* Read again rather than patched here. What the file says after a write is the
     file's answer, and a page that kept its own would drift from it the first time
     configobj wrote a value differently from the way it was typed. */
  if (d.ok) confView = null;
  draw();
}


function drawRaw(box) {
  var mine = drawn;
  api('raw?ident=' + encodeURIComponent(chosen)).then(function (d) {
    if (!d.uploads.length) {
      settle(mine, box, '<p class="dim">Nothing kept yet.</p>');
      return;
    }
    settle(mine, box, '<p class="dim">The last ' + d.uploads.length +
      ' uploads, newest first. Whatever names the station has been replaced, so these ' +
      'are safe to paste into an issue.</p>' +
      d.uploads.map(function (u, i) {
        return '<div class="upload"><div class="head"><span>' + esc(u.method) + ' ' +
          esc(u.path) + ' from ' + esc(u.client) + ' \\u00b7 ' + ago(u.at) +
          (u.protocol ? ' \\u00b7 ' + esc(u.protocol) : '') + '</span>' +
          '<button class="act" data-copy="' + i + '">Copy</button></div>' +
          '<pre id="raw' + i + '">' + esc(u.text) + '</pre></div>';
      }).join(''));
  });
}


function drawColumns(box) {
  var mine = drawn;
  api('columns?ident=' + encodeURIComponent(chosen)).then(function (d) {
    if (!d.ok) { settle(mine, box, '<p class="bad">' + esc(d.error) + '</p>'); return; }
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
    settle(mine, box, html);
  });
}

function createStation(body) {
  api('create', body).then(function (r) {
    if (!r.ok) { flash(r.message, true); return; }
    flash(r.station.role === 'main'
      ? 'Set up as the main station. Put the path below into the console.'
      : 'Set up as an extra sensor on channel ' + r.station.channel +
        '. Put the path below into the console.');
    refresh();
  });
}

function saveStation(ident, body) {
  body.ident = ident;
  api('edit', body).then(function (r) {
    flash(r.ok ? 'Changed. It takes effect on the next upload.' : r.message, !r.ok);
    if (!r.ok) return;
    editing = null;
    refresh();
  });
}

/* -------------------------------------------------------- hosted drivers */

/* What /api/ways last said. Held because the picker is redrawn on every choice, and
   asking again for a list that has not changed would empty the fields somebody is
   typing a serial port into. */
var ways = null;
/* What has been typed into the hardware search. Held here rather than read off the
   input, because choosing something redraws the whole form around it. */
var hwfind = '';
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
    if (view === 'setup') drawSetup(document.getElementById('body'));
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
  /* A hosted driver, on the Console tab, where every other station is managed too.
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
  if (d.ok) picked = null;
  loadWays();
  refresh();
}

/* ---------------------------------------------------------------- events */

document.addEventListener('click', function (e) {
  var t = e.target;
  if (t.dataset.view) { show(t.dataset.view); return; }
  if (t.dataset.tab) { showTab(t.dataset.tab); return; }
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
  if (t.dataset.conftoggle !== undefined) {
    var section = t.dataset.conftoggle;
    if (confShut[section]) delete confShut[section]; else confShut[section] = true;
    draw();
    return;
  }
  if (t.dataset.conffold) {
    confShut = {};
    if (t.dataset.conffold === 'all') {
      (confView && confView.sections ? confView.sections : []).forEach(function (s) {
        /* The top of the file has no heading to click on, so it cannot be folded
           back open. It stays. */
        if (s.path.length) confShut[s.path.join('/')] = true;
      });
    }
    draw();
    return;
  }
  if (t.dataset.confsave) { confSave(t.dataset.confsave); return; }
  if (t.dataset.confdrop) { confDrop(t.dataset.confdrop); return; }
  if (t.dataset.confline) { confLine(t.dataset.confline); return; }
  if (t.dataset.confadd) { confAdd(+t.dataset.confadd); return; }
  if (t.dataset.confdropsec) { confDropSection(+t.dataset.confdropsec); return; }
  if (t.dataset.confnewsec !== undefined) { confNewSection(); return; }
  if (t.dataset.moved) {
    /* The picker is the element just before the button, rather than something
       looked up by identity: an identity is whatever the hardware says it is, and
       a selector built out of one would break on the first sensor with a quote in
       its model name. */
    var moving = t.previousElementSibling;
    if (!moving || !moving.value) {
      flash('Choose which station moved onto this id.', true);
      return;
    }
    api('rebind', { was: moving.value, now: t.dataset.moved }).then(hostedThen);
    return;
  }
  if (t.dataset.askfind) {
    askTyped();
    flash('Looking.');
    api('polling/find', {
      protocol: t.dataset.askfind,
      address: asked.address,
      token: asked.token
    }).then(function (d) {
      if (!d.ok) { flash(d.message || 'Nothing was found.', true); return; }
      asked.found = d.found;
      asked.chosen = {};
      asked.device = d.found[0].device_id;
      /* The first device's sensors, ticked. That is the suggestion; the ticks are
         somebody's to change and nothing is written until they press the button. */
      d.found[0].entities.forEach(function (e) { asked.chosen[e.entity_id] = true; });
      draw();
    });
    return;
  }
  if (t.dataset.askadd) {
    askTyped();
    api('polling/add', {
      protocol: t.dataset.askadd,
      address: asked.address,
      token: asked.token || null,
      entities: askChosen(),
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
  if (t.id === 'hwback') {
    /* Back to the list, with whatever was searched for still in the box: somebody
       comparing two of four matches would otherwise type it again. */
    picked = null;
    drawSetup(document.getElementById('body'));
    return;
  }
  var hw = t.closest ? t.closest('[data-pick]') : null;
  if (hw) {
    /* Taken from whatever inside the row was clicked, so that the model list opens
       it too rather than only the name. */
    picked = hw.dataset.pick;
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
      if (r.ok) refresh();
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
    var agreed = pending;
    pending = null;
    if (agreed.what === 'create') {
      createStation({ protocol: agreed.protocol, name: agreed.name,
                      role: agreed.role, force: true });
    } else {
      saveStation(agreed.ident, { name: agreed.name, role: agreed.role,
                                  channel: agreed.channel, force: true });
    }
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
      if (r.ok) refresh();
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
      refresh();
    });
    return;
  }
  if (t.dataset.goto) {
    /* A jump from the checklist to where that step's work is done. Which axis it
       lands on depends on the target: the field map is a view of its own, and
       columns belong to one station, so that one needs a station picked first. */
    var where = t.dataset.goto;
    if (where === 'fields' || where === 'stations' || where === 'setup') {
      show(where);
      return;
    }
    if (!chosen && state && state.stations.length) chosen = state.stations[0].ident;
    view = 'stations';
    showTab(where);
    return;
  }
  if (t.dataset.accept) {
    var input = document.querySelector('[data-name="' + t.dataset.accept + '"]');
    api('accept', { ident: t.dataset.accept, name: input ? input.value : '' })
      .then(function (r) {
        flash(r.ok ? 'Let in. It records from its next upload.' : r.message, !r.ok);
        if (r.ok) refresh();
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

document.addEventListener('input', function (e) {
  if (e.target.id === 'find') {
    finding = e.target.value.trim();
    drawSidebar();
    return;
  }
  if (e.target.id === 'conffind') {
    confFind = e.target.value.trim();
    // Only the sections, so the cursor stays where it is being typed.
    var secs = document.getElementById('confsecs');
    if (secs && confView) secs.innerHTML = confSections(confView);
    return;
  }
  if (e.target.id === 'hwfind') {
    hwfind = e.target.value.trim();
    var list = document.getElementById('hwlist');
    var count = document.getElementById('hwcount');
    // Only the list and its count, so the cursor stays where it is being typed.
    if (list && ways) list.innerHTML = hwGroups();
    if (count && ways) count.textContent = hwCount();
  }
});

/* Enter in a weewx.conf box writes that setting. Everything else on this page is a
   button, and this is one too; what Enter buys is the person going down a section
   changing four values, for whom the mouse is the slow part. */
document.addEventListener('keydown', function (e) {
  if (e.key !== 'Enter') return;
  var at = e.target.dataset ? e.target.dataset.confval : null;
  if (!at) return;
  e.preventDefault();
  if (confView && confView.writable) confSave(at); else confLine(at);
});

document.addEventListener('change', function (e) {
  if (e.target.dataset.askentity !== undefined) {
    /* One station is one device. A tick on another device's sensor starts that
       device off rather than adding to the first, because a station that drew from
       two of them would have two thermometers taking turns over one column. */
    if (e.target.dataset.askdevice !== asked.device) {
      asked.device = e.target.dataset.askdevice;
      asked.chosen = {};
    }
    asked.chosen[e.target.dataset.askentity] = e.target.checked;
    askTyped();
    draw();
    return;
  }
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
  if (setup && !setup.done) view = 'setup';
  if (!chosen && state.stations.length) chosen = state.stations[0].ident;
  /* Nothing recording and something knocking: that decision is the only thing on
     this page worth opening on, and it is the one that leaves a console uploading
     into nothing until it is made. */
  if (!chosen && state.waiting.length) chosen = state.waiting[0].ident;
  drawSidebar();
  draw();
});
setInterval(function () { loadState(); loadStations(); loadSetup(); }, 15000);
</script>
</body>
</html>
"""
