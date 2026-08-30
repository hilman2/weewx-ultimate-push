# Changelog

## Unreleased

**Davis AirLink.** The one thing Vince Skahan named in
[weewx#1124](https://github.com/weewx/weewx/issues/1124) that this driver could not
read. He queries his with Home Assistant because there was no way to get it into
WeeWX beside everything else.

It is asked like a PurpleAir, but its answer is not flat: Davis wraps every local
API reply in `data.conditions[0]`, and that is unwrapped in the protocol so the rest
of the driver sees one set of names like every other. The wrapper also carries the
device id, which is what the page shows.

Nothing is stamped from the device's own clock, though it sends two of them.
`last_report_time` is seconds since boot on some firmware rather than an epoch,
which weewx-airlink found the hard way. The driver's clock is within one interval of
the reading, because it just asked.

A WeatherLink Live speaks the same API and sends a different shape. It is turned
away rather than read with this catalog, which would place a handful of names and
drop the rest.

`python -m user.ultimatepush --fake-airlink` answers like one.

**The front page lists every driver WeeWX ships**, with what each one reads and how
it is reached, each linking to its own generated page.

## 0.15.0

**Cheap radio sensors, by way of rtl_433.** A twenty-five euro USB stick hears
every sensor within a few hundred metres that talks on 433, 868 or 915 MHz: outdoor
thermometers, soil probes, rain gauges, pool sensors. rtl_433 does the radio and the
decoding and hands over named JSON. This reads it.

```bash
rtl_433 -C si -F syslog:127.0.0.1:1433
```

rtl_433 is a separate program and none of it ships here. It sends one datagram per
message and this driver already had a socket for datagrams, so nothing had to be
started, supervised or restarted.

The catalog is 47 names rather than the 531 rtl_433 can send, and that is not a gap.
The unit is in the field name, which is rtl_433's own documented rule, so
`temperature_F` and `temperature_C` are the same reading and the protocol converts
from the suffix rather than from knowledge about any device. Four hundred of the
names come from one decoder each and are tyre pressure sensors and doorbells. A name
nothing places still arrives, prefixed, and can be placed in the web interface.
`tools/check_rtl433.py` reads a stated release and says what it can send that is not
placed, so a new release is a list to look at rather than something to notice a year
later.

**Nothing overheard becomes a station.** Everything else here had to be aimed at this
machine, by typing an address into a console or by moving a DNS entry, so the first
upload is the owner's and the driver adopts it. A receiver was aimed at nothing. It
hears over the fence, and the first thing it hears is as likely to be next door's
thermometer, so every sensor waits to be let in.

Which made two things in the waiting list matter that never had before. It was built
from the last twenty uploads, which is right for a console and useless where thirty
things are talking: the sensor somebody is looking for had already fallen off the
end. It is now counted per station as uploads arrive, most often heard first, because
something heard sixty times an hour is close by and on a schedule and something heard
once was a car going past. And *not mine* takes one off the list for good, which
survives a restart.

**A battery change can rename a sensor.** rtl_433's own documentation says an id may
be programmed in or chosen afresh at each power on. When one of yours does that it
stops recording and turns up looking new, and letting it in as a second station would
leave its name, its channel and its columns behind with a number nothing will ever
send again. The interface moves the station onto the new id instead.

**A receiver to try it against.** `python -m user.ultimatepush --fake-rtl433` sends
what rtl_433 sends, three sensors at a time, one of them a neighbour's, because
letting in the ones that are yours is the part worth trying out.

**Hardware that answers, rather than sends.** A PurpleAir cannot be pointed at
anything. It has no field for a server address, because it was never meant to send:
it sits on the network and answers whoever asks. So does a Davis AirLink, and most of
what is sold with a local API. None of it could be recorded here, because this driver
only listened.

Now it asks. `[[polling]]` names an address, how often to ask, and which protocol
reads the answer, and after that nothing is different: the same detection, the same
catalog, the same field map, the same rule about which station owns which column. A
protocol becomes pollable by saying `fetched = True`, and everything it already had
keeps working.

One block is the whole of it. A polled source is the one kind of station that needs
nothing recognised, because the driver knows which sensor answered: it knows which
address it asked. So there is no second block naming it, nothing learned on a first
answer, and nothing waiting to be let in. The role and the channel go in the same
block.

```ini
[UltimatePush]
    [[polling]]
        [[[air]]]
            address = 1.2.3.4
            protocol = purpleair
            interval = 60
            role = extra
            channel = 3
```

PurpleAir is the first, PA-II and PA-I, over the sensor's own `/json`. Its
temperature is measured inside the housing next to electronics that are warm and
reads several degrees high; nothing here corrects it, and `role = extra` puts it in a
column where it cannot be mistaken for the air temperature. Its two laser counters
each get their own columns rather than being averaged, because two counters
disagreeing is the one thing that says a sensor is failing.

It can also be set up in the web interface, under *This machine reads it*, beside the
hardware on a cable. It is asked once before anything is saved, so a wrong address is
a message on the screen rather than something to undo.

**A sensor to try it against.** `python -m user.ultimatepush --fake-purpleair` answers
like one, on the loopback, with readings that move. It is the one kind of station
nobody could try before owning the hardware. The tests read the same answer, so what
is shipped and what is known to work are one thing.

**A path is enough to set a station up.** Setting one up by hand asked for the
`passkey` its console sends, which nobody knows before that console has uploaded. So
the documented way of doing it could not be followed, and the one thing a path is for,
naming a station before it exists, did not work outside the web interface.

Now the path is the whole of it. The console names itself in its first upload, that
name is written down, and every upload after it has to match. A second console pointed
at the same path is turned away, whether it is a different make or the identical model
next to it, because what is compared is what the console sends and every console sends
its own. Taking a station out takes what was learned with it, so a path set up again
starts clean.

The comment in `web_create` had claimed this behaviour for some time. There was no code
for it: a path match skipped the identity check entirely.

**A secret can be made rather than invented.** `python -m user.ultimatepush --secret`
prints ten characters from `secrets`, leaving out the ones that are read wrong off a
screen. Every place in the documentation that asks for a path, a password or a token now
says to use it.

**The examples cannot be mistaken for somebody's settings.** Addresses are `1.2.3.4`
and secrets are `abcdefg12345`, rather than values that look like they were copied off
a working installation.

**The tests run in Docker, against a stated WeeWX.** `tests/docker/` builds WeeWX 5.5.0
on the Python versions the driver has to clear, and runs as a normal user, because two
tests make a file unwritable and root can write to anything. `pytest-timeout` is set, so
a test that hangs fails and says where instead of the whole run being killed. There is a
service that runs the same suite with live output, and one that runs the four checkers.

**The documentation no longer describes an earlier version of this driver.** It began
as an Ecowitt driver, became one for six push protocols, and then learned to run the
drivers WeeWX ships. Several pages were still written for one of those stages.

`Sensors.md` is now `Ecowitt-sensors.md`. It only ever covered the Ecowitt catalog, and
the name promised every sensor. Home, the README and Installation described a driver for
hardware that pushes, which stopped being the whole truth. Field map, Catalogs and
Unknown fields describe a path that a station on a cable does not take, and now say so
rather than leaving somebody to look for a Vantage catalog. Security is about a port
that a station on a cable is not on. Troubleshooting and Diagnostics assumed something
had failed to arrive, and now cover the case where nothing was asked for.

`tools/publish_wiki.py` also takes out a wiki page whose source has gone. It only ever
wrote, so a renamed page stayed in the wiki for ever under both names, and the old one
is the one search engines already know about.

**A page for every protocol and every driver, for setting one up by hand.** Twenty
pages: the smallest configuration that works, everything the console has to be told,
every option that is only that one's, what is worth knowing before starting, and what to
check when nothing arrives. A driver page also says how to find the thing that cannot be
guessed, which is usually which serial device the console is on.

The driver pages are generated from the drivers installed on the machine that builds
them, through the same reader the web interface builds its form from. So a page states
the options of the version somebody actually has, with the explanations that driver's
own author wrote, and cannot describe a release nobody is running.

**Several stations** covers what those pages leave off: growing the file from one
station to several of different kinds, saying which reading comes from which station,
and where to look to see what each is delivering.

Every one of them carries a note near the top saying the web interface can do the same
thing, how to find its address, and that placing readings is much easier there.

**Configuration.md says which options belong to which protocol.** Six protocols share
one section, so the option list did not tell somebody with a Tempest which of the
thirteen were theirs. One table now does: whether the protocol is in `protocols = auto`,
which options only it has, and what names a station of that kind. For four of the six
the answer is that there is nothing to configure at all.

**A station in `weewx.conf` can carry its own password.** The interface gives one to
every Weather Underground console it sets up, and `Stations.md` promises that everything
the interface does can be written by hand. It could not: only the interface wrote it.

**Stations.md says how each kind of hardware is set up, in both places.** What an
Ecowitt console is given, what a Weather Underground console is given instead, and what
the three that cannot be told anything need. What adding a second station changes. And
which of three things decides where a reading ends up, with what to do about each.

**The interface carries its own icon.** A page that declares one is not asked for
`/favicon.ico`, and that request arrives without a token: ten of them in five minutes
would have stopped the address being answered at all. A request for it is now answered
before the token is looked at, for the browsers that ask anyway.

The wiki sidebar is built from a list in `tools/publish_wiki.py` that nothing kept in
step with `docs/`. A page missing from it was published and linked from nowhere. A test
now compares the two, and `docs/Home.md` as well.

## 0.14.0 (2026-08-30)

**Hardware that has to be asked now runs beside hardware that pushes.** WeeWX runs one
driver, so a Vantage on a serial port and an Ecowitt gateway meant two WeeWX instances,
two databases and two sets of reports for one weather station. Name another driver's
section under `[[hardware]]` and it is loaded the way WeeWX loads it, on a thread of its
own, and its readings join the ones that arrive over the network. Its own section is
untouched, so `weectl device` keeps working. Anything WeeWX can load works, whether it
ships with WeeWX or came from elsewhere.

The readings go through the same rules as an upload's, which is the point: one column,
one station, whether the station is a console on the network or a console on a cable.

**Archive records can come from a station that keeps them.** With
`record_generation = hardware`, the first driver listed supplies the record from its own
logger, and everything the other stations sent during that period is added to it.
Nothing is overwritten. A catch-up after an outage carries only that station's columns,
because nothing else was listening, and the log says so.

**A wired station is set up in the web interface, like every other station.** One list,
whatever the hardware is, grouped by the only thing somebody has to decide first: point
the console at this machine, let this machine read a driver, or change something on the
network and wait for the station to turn up. "Hardware this driver polls" and "hardware
that uploads" is a distinction this driver has and its user does not.

The list holds every driver installed on this machine, WeeWX's own and anything you
added, and fills the form from the driver's own configuration editor, so the settings
are the ones its author wrote. A protocol this driver is not listening for is in the
list too, with what switching it on takes, rather than missing from a list that claims
to be every way in. The driver is opened before anything is saved: a serial
port that is not there is a message on the page rather than an entry to take out again.
What is set up there starts at once, with no restart, and is kept in
`ultimate-push-web.conf` rather than in `weewx.conf`, for the same three reasons
everything else the interface writes is. Each entry carries the block to paste into
`weewx.conf` for anyone who would rather keep it there, which is also what `weectl
device` needs.

**The form for a wired station is the one its own driver describes.** Every field
carries the sentence its author wrote above it in that driver's own configuration
stanza, which is the answer to "how do I know what goes in here". An option that takes
one of a few values is a list, one that takes exactly one is stated rather than asked
for, and a serial port offers the devices actually plugged into this machine rather
than three examples of what one might be called. A Vantage asks for a port or a host
and never both, because its own configuration editor says so in an `if`; the eleven
settings its author ruled off as rarely needing attention start folded. A station found
over USB says that there is nothing to set, instead of showing an empty form.

The four options that take a fixed set of values are the only thing repeated here, and
a test checks each against the driver it belongs to: that the option still exists, and
that the driver's own default is one of the values. Every list also keeps a way to type
something else, and a way back into the list.

**Two unit systems with nothing converting them are now said out loud.** `weewx.accum`
refuses the second one and loses the archive record for that period. It happens when
`[StdConvert] target_unit` is missing and two stations report differently, which nothing
could see at startup: which catalog reads an upload is settled per upload. It is now
noticed the moment both have been heard, once, naming both stations.

**A Weather Underground console is given its ID and password instead of being asked
for them.** The settings used to say `anything you like` for both, and the console had
to upload once and be adopted before the driver knew what it was. But an ID names the
station and a PASSWORD proves it, and both are anybody's to choose at the console, so
this driver chooses them: it is set up in advance like an Ecowitt one, known from its
first upload, and never has to be let in as a stranger.

The password belongs to the station rather than to the driver. Two consoles told apart
by an ID would otherwise be able to use each other's, and an ID is readable by anybody
who can watch the network. An installation with `password` set in the driver section
keeps working, for the consoles that have none of their own.

Hardware that carries neither a path nor an identity is unchanged: a Tempest broadcasts
and an Acurite bridge has its server name in firmware, so both are still heard first and
confirmed afterwards.

**A console is named before it is told anything.** The settings to type into it used to
be shown before the station existed, with the driver's general path where its own would
go. Somebody typing those in reaches the path, uses the general one, and the console
then uploads as a stranger while the station they just made sits there having never been
heard from. Now naming it comes first, and its settings appear when it has a path,
where the person is looking, rather than on another tab.

**A station that is set up and has not been heard from is visible.** It is in the list
of stations, with what kind it is and that it is waiting, rather than nowhere until its
first upload arrives. It can be taken out again without opening the form for changing
it, because taking one out that has never been heard from is undoing a typing mistake.
And a console `weewx.conf` names with `passkey` that has never uploaded no longer
describes itself as the first console this driver ever heard.

**A wired station that stops answering comes back on its own.** It is closed and built
again, waiting ten seconds the first time and doubling to five minutes. The stations
that upload keep being recorded and the web interface stays up. The exception is the
archive station at startup: if it cannot be opened at all the driver does not start,
because the alternative is an archive quietly filled from software while the console's
logger holds the real records.

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
