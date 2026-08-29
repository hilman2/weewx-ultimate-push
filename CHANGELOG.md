# Changelog

## 0.13.0 (2026-08-29)

**Two stations no longer share a column.** A role kept an extra station out of the main
station's columns, and said nothing about two extra sensors. Three identical consoles
beside an Ambient main station all wrote `soilMoist1`, `rainRate` and ten more, in turn,
every few seconds, because the main station has no such readings to keep them out of.

A column now belongs to whichever station fills it first. Everybody else is turned away
from it, and the main station outranks the lot. Ownership is written to `[columns]` in
`ultimate-push-web.conf`, so it survives a restart.

That has a second effect worth having. An extra station used to be held back after every
restart until the main station happened to upload again, which cost an upload interval
per station per restart. It now waits once, the first time, and never again.

**Exactly one station is the main station.** A station set up beside an existing one
becomes an extra sensor on a free channel without being asked, which is what somebody
setting up a second console means. Taking the main station from another station changes
which columns its readings land in from that moment, so the interface says what that
does and asks twice. The data path holds the count at one whatever a hand-written
configuration says.

**A column that already holds readings is not written into without being asked.** When a
station is set up, the driver reads the archive table and reports which of the columns
that station would write already hold data, how many rows and from when. Those readings
came from an older console, another driver or an import: continuing the series is right
for the same station in the same place and mixes two sensors when it is not. Where the
choice can be avoided it is, and a channel whose `extraTempN` already holds readings is
skipped when one is handed out.

**Stations have a tab of their own.** Every station the driver knows, including the ones
set up and never heard from, with the console settings for each. Name, role and channel
can be changed there, columns can be given up, and a station can be taken out again.

**Fixed:** the driver's own path stopped being answered as soon as any station had used
its own path. Setting up a second station therefore silenced the console that was there
first, and an unknown console was turned away with a 404 rather than being offered for
approval.

**Fixed:** the setup page redrew itself every five seconds, which emptied the field
somebody was typing a station name into.

The documentation follows the WeeWX reference style, and docstrings are Google style.


## 0.12.4 (2026-08-28)

Setting a station up in the interface did not work, in three separate ways.

**The path was never shown.** A station set up here gets an upload path of its own,
and that path is the entire point: it is how the driver knows which station an upload
is from, and it is a secret. The page said "Put the path below into the console" and
then showed the driver's general path, `/`, which is the one thing that cannot work.
The path now comes from the driver on every load, so closing the tab does not lose it
either.

**Add a station led to an empty page.** The button switches to Setup, and the form
lives inside a checklist step that stops being drawn once something has uploaded. The
Setup tab now offers to set up another station when asked, above the finished
checklist.

**A fresh install opened on Fields**, which said "Nothing has uploaded yet." An
installation with something still to do now opens on the thing still to do. An empty
table reads like a fault rather than like a step not taken yet.

A station made in the interface also never learned its own path: only the lookup that
routes uploads knew it. Anything wanting to show somebody what they had been given had
nowhere to read it from.

## 0.12.3 (2026-08-28)

The Fields tab and the Database columns tab disagreed with each other. Fields read the
archive table; Database columns still asked the schema, so the same reading was
`column ready` on one tab and had nowhere to live on the other.

Measured on a live station: the archive table has 134 columns, the schema names 115.
Nineteen columns had been added at some point, and the page had been asking for them
to be added again ever since.

The diagnostic run does the same now: with a configuration file it reads the table
rather than the schema.

## 0.12.2 (2026-08-28)

The Raw uploads tab said `Loading.` and never stopped. `drawRaw` was gone: 0.12.0
replaced the block of the page that drew the fields, and that function lived inside
it. The console said so; the page did not.

There are now two tests for it. One checks that every `draw` and `load` name the
script calls is a function the script defines. The other checks that every tab has a
renderer behind it. Both go red with the function taken out again.

The Fields tab also no longer waits for a station to be picked. It shows all of them
now, so there was nothing to wait for, and a fresh install saw `Pick a station.` on
the tab most worth looking at.

## 0.12.1 (2026-08-28)

A test asked the standard schema for its numbered families, which needs WeeWX
installed, in the half of the matrix that runs without it. The driver is unchanged.

## 0.12.0 (2026-08-28)

The field map is set in the browser now. No terminal, no editor.

### One view, not one per station

The Fields tab showed the station you had clicked. That is the wrong axis. The question
somebody has is not "what does this station send", it is "who fills `outTemp`", and
with two stations that answer was spread over two pages, neither of which could show
the collision that matters.

There is now one view with every station in it, one foldable block each, and a line
saying which reading of which station holds each column.

### One WeeWX field, one reading

Picking a field another station already fills says who has it and changes nothing:

    outTemp is already filled by 'tempf' from station garden. One column takes one
    reading: two of them take turns every few seconds, and afterwards nothing can
    tell them apart.

Say yes and the reading that had it is placed nowhere, which is a placement of its own
and not the same as having none: taking the entry away would hand the reading straight
back to the catalog and back into the column it was just moved out of. `nowhere` is in
the box, so it can also be chosen on its own.

### The box goes past the end of the schema

The schema stops at `extraTemp8`, `soilMoist4`, `leafWet2`. Hardware passes that on a
normal afternoon, and the way people dealt with it was to write `extraTemp9` into a
configuration file by hand, because the box had no answer for it.

Numbered families now run to 16. Each option says what it costs: `new column`, or the
station and reading that hold it.

### The column is a button

A row with no column had a command to copy into a terminal. It now has a button that
runs the same `ALTER TABLE` that `weectl database add-column` runs.

Which is worth being exact about, because this changelog was not. Adding a column does
not rewrite the table: 300 000 records, 7.6 ms, file the same size afterwards. What
cannot be undone is taking one away, so the button asks first and there is no button
for that.

The daily summary for a new column is not created, and `weectl` does not create one
either. Aggregates still work, computed from the archive table instead, which is
slower and right.

### A row says what it is

`column ready` was worked out from the schema rather than from the database, so a
database made by an older WeeWX was told it had columns it did not have. It is now read
from the archive table.

A row filled by another station said `column ready`, which was true about the column
and wrong about the row. It now says which station fills it.

The unit group was only filled in for fields outside WeeWX's own schema, so ordinary
rows fell into "everything else" and the sorting the box exists for did nothing.

### A placement made in weewx.conf can be changed here

It could not be, on the grounds that one setting should have one owner. That is a good
rule and it made the one placement people most want to fix the one thing the interface
would not touch. The row says where the placement came from; a choice here beats
`[[field_map_extensions]]`.

A station declared under `[[stations]]` is unchanged: its field map is part of that
declaration and stays there.

## 0.11.1 (2026-08-28)

The web interface drew its frame and then stopped. It looked like the server hanging;
the server was answering in seventeen milliseconds.

A newline escape in the page's source reached the browser as a real newline, inside a
JavaScript string literal. That is a syntax error, the whole script failed to parse,
and nothing on the page ran. It arrived in 0.10.0, in the prompt for naming a field of
your own.

Nothing here would have caught it. Every test asks the driver for its answers, and the
driver's answers were right the whole time. There is now a test that reads the page as
a browser would.

## 0.11.0 (2026-08-28)

### An upload nobody claimed shows what it sent

The card used to say `ecowitt from 192.168.1.51, 12 seen` and offer a button called
"Let in". That asks somebody to put a stranger into their database, or to turn their
own new console away, with nothing to tell the two apart.

It now shows the readings, ordered by what a person can check against a thermometer or
a look out of the window, with the raw name beside the field each one would fill:

    tempf           61.0    -> outTemp
    humidity        88      -> outHumidity
    windspeedmph    3.4     -> windSpeed
    baromrelin      29.91   -> barometer

"All of it" opens the whole payload, with a button to copy it. What names the console
is not shown, here or anywhere else on the page.

### An extra station no longer writes into the main station's columns after a restart

What the main station fills was learned from its uploads, so at startup nothing was
known and nothing held an extra station back. If the extra one uploaded first, which is
a coin toss, its wind and pressure went into the main station's columns until the main
station was heard.

An interval of two sensors in one column cannot be separated afterwards, and it
happened at every restart. An extra station now waits for the main one, and says so
once:

    INFO user.ultimatepush.driver: Holding back station 'roof' until the main station
    has been heard, so that its readings cannot land in the main station's columns.

Losing one upload of an extra station is the cheaper of the two.

## 0.10.0 (2026-08-28)

Stations are set up in the web interface, and the driver decides nothing about which
of them may fill which field without saying so.

### Setting one up

Name it, pick what it is, and for hardware whose upload path is yours to choose the
driver makes one and shows the settings to type in:

    Protocol Type          Ecowitt
    Server IP / Hostname   192.168.1.50
    Path                   /E0rbpxexKCsb/report
    Port                   8000

From the first upload it knows which station that is. The path is the identity and the
secret at once, which is better than a PASSKEY: that is in every upload in the clear
and anybody who has seen one can repeat it.

WeatherFlow broadcasts and the two bridges have their path in firmware, so they cannot
be set up this way and the interface says so instead of offering something that would
not work. Those are adopted, as before.

Every path is accepted until a station has actually been heard on one of its own, so
that setting a station up and not yet having typed it into the console does not bounce
the uploads you already have.

### Which station may fill which field

A station has a role. `main` is the station and its readings go where they belong.
`extra` has its temperature and humidity moved to `extraTempN` and `extraHumidN`, and
everything else it sends is dropped rather than written over the main station's, which
is said once in the log rather than once per field.

With one station none of this does anything, and nothing about that case changed.

The interface says when two stations would fill the same column, which nothing in WeeWX
would otherwise have mentioned: they would simply take turns, every few seconds, and
afterwards the column holds a mixture nothing can separate.

Roles, channels and paths can all be written into `weewx.conf` as well. Nothing here is
only reachable by clicking, and a station written by hand is the one in force.

### The field table

The box in each row offers the WeeWX fields that measure the same thing first, then
everything else, then a field of your own. Offering a wind speed as a home for a
temperature is worse than no suggestion, because somebody will pick it. A field with no
column shows the command that makes it, in the row.

### Needed a change to the listener

`path` now takes a list, or a callable for the case where the set is not known when the
socket is opened. A station added while WeeWX is running has to work from the next
upload, not the next restart. Pushed to the core listener under review as
[PR #1125](https://github.com/weewx/weewx/pull/1125); the bundled copy is byte for byte
the same file.

It also fixes something that was simply not possible before: a secret `path` and
Weather Underground hardware could not both exist, because that hardware's endpoint is
burned into its firmware and a set `path` turned it into a 404.

## 0.9.0 (2026-08-28)

The interface now opens on what is still in the way, and tells you what to type.

Before this it showed an empty list of stations until something uploaded, and said
nothing about how to make something upload. That is the commonest place to be stuck
and it was the one thing the page could not help with.

Now it asks which hardware you have and shows the settings for it, with this machine's
address and the port already filled in:

    Protocol Type          Ecowitt
    Server IP / Hostname   192.168.1.50
    Path                   /
    Port                   8000
    Upload Interval        60

Then it waits, and notices the first upload by itself. After that it works through the
placements only you can make, the columns that are missing, and whether the station
knows where it is. Hardware that cannot be pointed anywhere, an Acurite bridge or a
LaCrosse gateway, says so and gives the DNS entry instead.

**It is a checklist, not a wizard.** A wizard keeps a step number, and a step number is
wrong as soon as somebody closes the tab, points a second console at the port, or comes
back next month. This works out what is true every time it is asked. So it is right on
the first visit and the hundredth, it survives a restart, and once everything is
answered it keeps working as a health page rather than becoming a thing to dismiss. A
console that turns up next year puts its step back at the top.

Also in this release: a station that is still being turned away is now a question about
now rather than about the log. Letting one in used to leave the step outstanding until
twenty more refusals had pushed the old ones out of the ring.

## 0.8.0 (2026-08-28)

Two commands to a working station, and the driver says where its web interface is.

```
weectl extension install <the zip>
sudo systemctl restart weewx
```

The installer now switches the web interface on and puts a token in `weewx.conf` that
is made at install time and different on every machine. It was three more steps: make
a token, edit the file, work out which of your addresses the listener ended up on.

**This opens port 8080 on upgrade** for anyone who did not have `[[web]]` in their
configuration. `enable = false` closes it. The port answers nothing without the token,
and stops answering an address entirely after ten wrong ones in five minutes.

The driver prints the whole address at startup, with the machine's own address rather
than the `*` a listener bound to every interface reports:

```
INFO user.ultimatepush.driver: The web interface is at
http://192.168.1.50:8080/?token=kJ7mQx2vRt9w
```

That line holds the token, so treat the log the way you treat `weewx.conf`.

`python -m user.ultimatepush --url` prints it again later, because a log is a poor
place to keep something you want to open next week.

The page now asks for its API relative to its own path, so it works behind a reverse
proxy that puts it under a prefix. It used to ask for `/api/...` from the root, which
loaded the page and then found nothing.

## 0.7.0 (2026-08-28)

The web interface takes a shorter token, and stops answering an address that keeps
getting it wrong.

Ten characters instead of sixteen. Ten random ones is about sixty bits, which no
amount of guessing gets through; what a longer minimum bought was inconvenience.

What makes a short token sound is the doorman. Ten wrong ones from one address inside
five minutes and that address gets nothing back at all, right token or not, until
those tries fall out of the window. Not an error and not a hint: an empty reply, which
also means it costs nothing to serve.

    [[web]]
        tries = 10
        window = 300

A right token clears the tally, so somebody who mistyped it four times and then pasted
it properly is not left one try from a lockout. One address getting it wrong never
shuts out another. And the page shows what has been knocking, so it is not only in the
log.

That record is kept separately from the tally that decides, and has to be: reading it
means getting the token right first, and if success cleared both there would never be
anything to see.

### One thing moved to make this possible

The token used to be checked by `weewx.listener`, which did it before anything of ours
ran and answered a wrong one with a real 403. That is a better status code and a worse
design: a wrong token was answered and forgotten, and there was nothing to count. So
the check is now the driver's, still constant time, and every reply is a 200 with the
answer in the body.

## 0.6.0 (2026-08-28)

A web interface, on a port of its own, off unless you switch it on.

```ini
[UltimatePush]
    [[web]]
        enable = true
        port = 8080
        token = paste-a-long-random-string-here
```

It shows what each station sends, keeps the last twenty raw uploads with everything
that names the station replaced, lists the columns that are missing with the commands
that make them, and lets you place a field.

The reason it exists is the last of those. Placing a field is a decision only the
person who installed the sensor can make, it cannot be undone once two sensors have
shared a column, and the one thing worth knowing first is whether that column already
holds somebody else's readings. A log line cannot say that. The page says it per
field, next to the value that just arrived.

### Settings go in a file of the driver's own

Not `weewx.conf`. WeeWX is running from that file, so a change written there does
nothing until a restart, and a driver cannot restart the engine it is part of. Under a
package installation it belongs to root and the driver runs as the weewx user.

So what the interface changes goes in `ultimate-push-web.conf`, beside the console
list, in the same format, and is read on the next upload. Nothing restarts. Everything
that does need a restart is shown as a block to paste.

**A field named in `weewx.conf` is never touched.** The interface shows it, says it is
set there, and declines. Two files with an answer each would mean one of them is
quietly ignored.

### On the security of it

It is a second port that can change the field map, so:

- Off by default, and it refuses to start without a token of at least 16 characters.
- The token is checked by the listener before anything else runs, in constant time,
  and a wrong one gets a 403.
- It is a second port rather than a secret path on the data port, because a token on
  that port would lock out hardware that cannot send one.
- It is plain HTTP and the token travels in clear. On a network you do not trust, bind
  it to `localhost` and use an SSH tunnel, or put TLS in front.

### Also

- The driver keeps a bounded record of recent uploads whether or not the interface is
  on, so a question about what arrived is answerable afterwards.
- New page: [Web interface](docs/Web-interface.md).

## 0.5.0 (2026-08-28)

Renamed from `weewx-ecowitt`. The driver reads six protocols now, and the old name
described one of them.

**This release does not upgrade in place.** The package is `user.ultimatepush`, the
section is `[UltimatePush]`, and the extension is `ultimate-push`. To move:

    weectl extension uninstall ecowitt
    weectl extension install https://github.com/hilman2/weewx-ultimate-push/releases/latest/download/weewx-ultimate-push.zip
    weectl station reconfigure

Copy `field_map_extensions`, `passkey`, `path` and any `[[stations]]` across by hand.
The database is untouched and every column keeps its readings.

Two field names moved, both of them wind averages that only some hardware sends:
`windspdmph_avg10m` and `winddir_avg10m` now go to `windSpeed_avg10m` and
`windDir_avg10m` in every catalog rather than to their own raw names in one of them.
A station that has history in the old columns keeps it; add the old names to
`field_map_extensions` to carry on writing there.

### Protocols

| Protocol | Hardware |
|---|---|
| Ecowitt | as before |
| Weather Underground | Fine Offset Observer, Sainlogic, Meteobridge, any console set to *Wunderground* |
| Ambient Weather | WS-2902, WS-5000, WS-1965 and the rest of the range |
| WeatherFlow | Tempest, AIR, SKY, over UDP |
| Acurite | smartHUB, Access |
| LaCrosse | LW301, LW302 |

They share one port. Which one sent an upload is decided from what is in it, and each
is answered the way its own firmware expects: JSON for Ecowitt, `success` for Weather
Underground, Chaney's own reply for Acurite. Hardware that does not read the answer it
expects counts the upload as failed and eventually stops.

Weather Underground was previously listed as supported and was not, in any useful
sense. Both transports ended in the same parser, but the catalog had no Weather
Underground field names in it, so `baromin`, `rainin`, `indoortempf`, `indoorhumidity`
and `UV` were all dropped. A station on that protocol recorded no pressure, no indoor
readings and no UV, and nothing said so.

`protocols` selects them. The default `auto` is every one that posts. WeatherFlow needs
naming, because it opens a second socket.

### Three things that were silently wrong

**`-9999` was read as a number.** Fine Offset firmwares send it for a sensor with
nothing to report. It is a gap now.

**`baromin` is not always sea-level pressure.** `WH2600GEN_V2.2.5` and `WH2650A_V1.2.1`
send station pressure in it. Both say so in `softwaretype`, and the driver moves the
field for them.

**Rain needs a different counter per protocol.** WeatherFlow already sends the amount
since its last report and must not be differenced again; a LaCrosse LW30x has no daily
counter and needs `input = totalRain`. The driver warns at startup when the setting in
`weewx.conf` does not suit the protocols enabled.

### Also

- `password` checks the `PASSWORD` Weather Underground hardware sends. It is the one
  protocol here whose hardware can carry a secret.
- `metric_wind` says whether the Weather Underground metric dialect sends kilometres
  per hour or metres per second, which cannot be read off a payload.
- A packet's unit system now comes from the protocol. It was `weewx.US` for everything.
- A few readings are converted where they arrive in a unit other than the one WeeWX
  keeps that column in: parts per billion to parts per million, inches to millimetres
  in the LaCrosse rain gauge, microwatts per square centimetre to watts per square
  metre.
- Acurite and LaCrosse send one request per sensor. Everything that is not the main
  station arrives named after the sensor that sent it, ready to place.
- The Ambient catalog is generated from Home Assistant's `ambient_station`, the way the
  Ecowitt one is generated from `ecowittcustom`.
- The report file says which protocol the upload was.
- New page: [Protocols](docs/Protocols.md).

## 0.3.1 (2026-08-25)

Fix: no rain was recorded at all. Ecowitt hardware sends rain as running counters,
never as the amount since the last upload, so `rain` stayed empty in every packet
and nothing reached the daily total. The installer now sets up `StdDelta` to derive
`rain` from `dayRain`.

Anyone already running 0.3.0 or earlier should reinstall the extension, or add this
to `weewx.conf` by hand:

    [StdWXCalculate]
        [[Delta]]
            [[[rain]]]
                input = dayRain

## 0.3.0 (2026-08-25)

The driver now answers only to the consoles it knows. The first one it hears is
adopted and recorded; anything else is refused until it is named under `[[stations]]`
with a field map of its own. Two consoles both number their channels from one, so
without this a WN34 on channel 1 of each lands in the same column, and afterwards
neither can be recovered. The list is kept in the database, beside the readings it
protects, with a text file as fallback.

The console's own timestamp is believed within a window that fits a late upload:
an hour behind, a minute ahead. Consoles with an internet connection keep their
clock by NTP, so a stamp a few minutes old means the upload was held up rather than
that the clock is wrong. Both limits are configurable as `max_behind` and
`max_ahead`. On WeeWX before 5.5, where a packet from an interval that has already
been written cannot reach it, set `max_behind = 90`.

## 0.2.1 (2026-08-25)

A second console is now noticed without being configured. The driver tracks which
console wrote which field, and drops a newcomer's value for a field another console
already owns instead of writing over it. Only the clashing field is dropped; anything
that console alone carries still arrives.

## 0.2.0 (2026-08-25)

Several consoles can now share one driver, told apart by the PASSKEY each sends.
Each gets its own field map, so a WN34 on channel 1 of one console and channel 1 of
another no longer land in the same field. Every packet carries `station` with the
name given to it. Configure them under `[[stations]]`; leave it out and nothing
changes for a single console.

## 0.1.2 (2026-08-25)

The listener now says when it has stopped listening. A dead thread used to look
exactly like a station that had gone quiet, and a driver waiting on it would have
waited for good.

Tests for the failure modes: a parser that raises costs one packet rather than the
process, rubbish and oversized uploads cost nothing, a response callback that raises
still stores the reading, and a flood drops readings rather than growing without
limit.

## 0.1.1 (2026-08-25)

Fixes an installation that could not start. `install.py` left out `columns.py`,
`report.py` and `__main__.py`, so `weectl extension install` copied a package that
raised `ImportError` on the first start. The release archive contained them; the
installer did not copy them.

A test now compares the file list in `install.py` against the package, so a module
cannot be left out again.

Nobody who installed 0.1.0 has a working driver. Install this one over it.

## 0.1.0 (2026-08-25)

First version.

- Reads the Ecowitt and Weather Underground protocols from a custom-server upload.
- Field catalog generated from `ecowittcustom` by Werner Krenn: 524 fields.
- Fields that continue a known series are taken without a release, e.g. `tf_ch9`
  becomes `soilTemp9`. Fields that are only recognisable by name are reported and left
  out unless `infer_unknown = all`.
- A reading that upstream maps to more than one field goes to the one in the WeeWX
  schema, so that skins and reports find it.
- The time of the last lightning strike goes to `lightning_time`, not into
  `lightning_disturber_count`.
- Fields whose placement the hardware does not settle are not written until they are
  named in `field_map_extensions`. Six of them on a station with two WN34 probes, a
  WH52 and a lightning sensor; the other twenty-nine readings arrive as usual.
- `python -m user.ultimatepush` reports which of the fields it would write to already hold
  readings, before anything is changed.
- When a station sends something the driver cannot place, it writes the raw upload
  and its findings to `/var/tmp/weewx-ultimate-push-report.txt`, with the PASSKEY replaced.
  Reporting a new sensor is then one `cat` and a paste.
- Uses `weewx.listener` where available, and ships a copy for older WeeWX.
