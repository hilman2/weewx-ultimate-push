# Stations

How to get a station recorded, and what to do once there is more than one.

With a single station most of this looks after itself: it uploads, the driver records
it, and every reading is written where a WeeWX report expects it. The sections on roles
and on columns start to matter when a second one arrives.

## Setting up a station

Most hardware can be set up before it has ever sent anything. You give the station a
name and the driver hands you a few settings. You type those into the app that
configures the console. The first reading then arrives already knowing which station
it came from.

Three kinds cannot, because there is nothing on them to set. Those have to be heard
first and let in afterwards.

| What you have | What you give it |
|---|---|
| An Ecowitt console | An address and a path, both from this driver |
| An Ambient Weather console | The same |
| Anything set to *Wunderground* | An address, an ID and a password, all from this driver |
| A Tempest or other WeatherFlow hub | Nothing. It shouts to the whole network |
| An Acurite smartHUB or Access | Nothing. Only a DNS entry can move it |
| A LaCrosse LW30x gateway | Nothing. The same |
| A station on a cable or on USB | Its port, and whatever else its own driver asks |

The last of those is [hosted hardware](Hosted-hardware.md): a station this machine reads
rather than waits for.

### In the web interface

Open the [web interface](Web-interface.md), pick what you have, and give it a name. What
appears next depends on the kind.

For an Ecowitt or Ambient console the driver makes a path and shows the settings to
enter into its app:

| | |
|---|---|
| Protocol Type | Ecowitt |
| Server IP / Hostname | 1.2.3.4 |
| Path | `/abcdefg12345/report` |
| Port | 8000 |

For a Weather Underground console it makes an `ID` and a `PASSWORD` instead, because
that console cannot be told a path:

| | |
|---|---|
| Server | 1.2.3.4 |
| Port | 8000 |
| ID | `up-abcde123` |
| PASSWORD | `abcdefg12345` |

Nothing is shown until the station has a name, because the name is what produces the
path or the ID. From the first upload the driver knows which station sent it. The same
settings stay on that station's **Console** tab afterwards, for a console that has to
be set up again a year later.

For hardware this machine reads rather than waits for, the form is that driver's own.
See [Hosted hardware](Hosted-hardware.md).

### In weewx.conf

Anything the interface can do, you can write yourself. A station you put in this file
belongs to the file: the interface shows it and will not change it, so the two can never
disagree about it.

An Ecowitt or Ambient console. The path is all it needs, and you choose it:

```ini
[UltimatePush]
    [[stations]]
        [[[garden]]]
            path = /abcdefg12345/report
```

Nothing has to be looked up first. The console names itself in its first upload, and
that name is written down: every upload after it has to match, so a second console
pointed at the same path is turned away. Make the path with
`python -m user.ultimatepush --secret`.

A Weather Underground console, with the ID and password you will type into it. Both
are yours to choose; make each with `python -m user.ultimatepush --secret`:

```ini
[UltimatePush]
    [[stations]]
        [[[garden]]]
            id = up-abcde123
            password = abcdefg12345
```

A WeatherFlow hub, an Acurite bridge or a LaCrosse gateway. You cannot make up what
these are called. It is the serial number or the MAC address the hardware sends itself,
so let it upload once and then write the line:

```ini
[UltimatePush]
    [[stations]]
        [[[tempest]]]
            id = ST-00012345
```

The log prints it the first time one of them uploads, ready to copy. Every option a
station takes is listed under
[Configuring stations in weewx.conf](#configuring-stations-in-weewxconf) below.

### Why the path rather than the PASSKEY

The path is a secret and a PASSKEY is not.

Every Ecowitt and Ambient console sends a PASSKEY derived from its MAC address, in
every upload, in the clear. It identifies the console, but anyone who has seen one
upload can repeat it. The path is known only to whoever was shown it.

Where the hardware can be given a path, the path is the identity. Where it cannot, the
PASSKEY is used instead.

A Weather Underground console sits between the two. Its path is fixed in the firmware,
so it cannot be given one. But it carries an `ID` that names it and a `PASSWORD` that
proves it, and both are anybody's to choose. So the driver chooses them, which comes to
the same thing: the station is known from its first upload.

Neither is a strong secret. They travel in the address the console posts to, over plain
HTTP, exactly as a path does. They keep out a stranger who has found the port, not
somebody watching the network. See [Keeping strangers out](Security.md).

### Hardware that has to be heard first

Three of the six protocols cannot be set up in advance:

| | Reason |
|---|---|
| WeatherFlow | The hub broadcasts. Nothing is configured on it. |
| Acurite | The bridge posts to Chaney's servers. Its path is in the firmware. |
| LaCrosse | The same, to its own manufacturer's servers. |

These stations are adopted. Point one at the driver, and the first upload appears in
the web interface as a station waiting to be let in, with its readings shown so that
you can confirm it is yours. Accepting it takes one click.

The first console a new driver ever hears is adopted without being asked, because at
that point there is nothing to confuse it with. Every station after that waits.

## Adding a second station

Setting up the second one works exactly like the first. The difference is what the
driver assumes about it.

Your first station is *the* station: its temperature is the outdoor temperature, its
pressure is the pressure, and a WeeWX report reads all of it without being told
anything. A second console is almost never meant to replace that. It is usually another
thermometer somewhere else, so the driver treats it as one and gives it a channel of
its own.

In the web interface that is filled in for you and there is nothing to do. If the new
one really should take over as the main station, you can say so, and the interface
explains what that costs before it happens.

By hand it is written out, because a file has nothing to fill in for you:

```ini
[UltimatePush]
    [[stations]]

        [[[garden]]]
            passkey = AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
            path = /abcdefg12345/report

        [[[roof]]]
            passkey = BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB
            role = extra
            channel = 4
```

A station this machine reads sits in the same list, in a section of its own. See
[Hosted hardware](Hosted-hardware.md).

You can add as many as you like. What runs out is not stations but places to put their
readings, which is the next section.

## Which station's readings go where

With one station this looks after itself. With two, something has to decide whose
temperature is *the* outdoor temperature, and where the other one's goes.

It has to be decided by something, because the database has one column for it. Two
sensors writing that column in turn would leave a mixture that nothing afterwards can
untangle.

Three things decide it. You can change any of them, and each answers a different
question.

**Whose readings are the station's own.** That is the main station, and it is the big
lever: change which station has that role and all of its readings move at once. Its
temperature stops being `outTemp` and becomes `extraTemp` on a channel, and its wind,
rain and pressure stop being recorded, because there is nowhere else for them. See
[Roles](#roles) below, and read the warning there first: it changes what a report shows
from that moment on.

**Where one particular reading goes.** For a single sensor rather than a whole station.
The soil probe on channel 1 of the second console has nowhere of its own to go, and you
want it in `soilMoist3`. In the web interface that is the station's **Readings** tab,
one row per reading, with a selector saying where it goes and what that costs. By hand it is
`field_map_extensions` under that station:

```ini
[[[roof]]]
    passkey = BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB
    role = extra
    channel = 4
    [[[[field_map_extensions]]]]
        soilmoisture1 = soilMoist3
        tf_ch1 = soilTemp5
```

Either way it takes effect on the next upload, with no restart. What names are
available and where they come from is in [Field map](Field-map.md).

**Who got there first.** A column belongs to whichever station first filled it, and
everybody else is turned away from it. This is what stops three identical extra sensors
from taking turns in one soil column. If a column is held by a station that has gone, or
by the wrong one, you take it away from that station and the next one to send that
reading gets it. See [Column ownership](#column-ownership) below.

A placement you made yourself beats the other two, always. If a reading is not where you
expect it, the **Readings** tab shows which of the three put it there.

## Roles

Two stations both send `outTemp`, and there is one `outTemp` column. Left alone, the
two would write it in turn every few seconds, producing a column that holds a mixture
nothing can separate afterwards. Each station therefore has a role.

#### main

The station. Its readings are written where they belong. Exactly one station has this
role. With a single station it has the role without anyone deciding.

#### extra

A sensor beside the main station. Its temperature and humidity are written to
`extraTempN` and `extraHumidN`, where N is the channel. Readings that have nowhere of
their own to go are dropped rather than written over another station's.

A station set up while another is already the main station is given the `extra` role
and the next free channel, without being asked. This is what is meant in almost every
case: a second console beside an existing one is an additional sensor.

The standard schema provides `extraTemp1` to `extraTemp8` and `extraHumid1` to
`extraHumid8`, and nothing equivalent for wind, rain or pressure. A second full weather
station therefore contributes its temperature and its humidity, and anything else it
sends requires a field and a column of its own. See [Field map](Field-map.md).

### Changing which station is the main station

Making a second station the main station moves the first aside: from its next upload it
is an extra sensor on a channel of its own, its temperature and humidity are written to
`extraTempN` and `extraHumidN` instead of `outTemp` and `outHumidity`, and its wind,
rain and pressure are no longer recorded at all.

What is already in the archive is not changed. `outTemp` therefore holds one sensor's
readings up to that moment and another's from then on, and nothing afterwards can
determine which reading came from which sensor. Reversing the change does not undo
this; it adds a second discontinuity.

The web interface states this in full and requires confirmation twice: a checkbox
confirming that you have a copy of the archive database, and then the button itself.
The same change over the API requires `force`.

The driver refuses to have two main stations. A configuration file written by hand can
still declare two, in which case the first station declared is the one that writes and
the second is treated as any other station: it fills only the columns nobody else has.
This is reported at startup and in the log at the first upload.

## Column ownership

Roles alone do not settle every case. Three identical consoles set up as extra sensors
all send `soilmoisture1`, and if the main station is a console with no such reading,
nothing about the role keeps them out of `soilMoist1`.

A column therefore belongs to whichever station fills it first. Every other station's
reading for that column is dropped. The main station takes precedence over an existing
claim, so which console owns `outTemp` does not depend on which one happened to upload
first after a restart.

Ownership is recorded in `ultimate-push-web.conf`:

```ini
[columns]
    outTemp = path:/abcdefg12345/report
    extraTemp1 = path:/hijklmn67890/report
    soilMoist1 = path:/hijklmn67890/report
```

Because it is recorded rather than learned again at each startup, an extra station is
held back only once — until the main station's first upload, ever. After that a restart
costs no readings.

A station's **Console** tab lists the columns it fills. The checklist reports
readings that were dropped, which station sent them, and which station holds the column:

```
[ ] sharing     12 reading(s) have nowhere of their own to go

    soilMoist1     wanted by shed     held by roof
    rainRate       wanted by shed     held by roof
```

An extra sensor's wind and pressure being kept out of the main station's columns is the
role working as intended and is not reported here. A reading you placed by hand that is
not written is always reported, because placing it was a decision that did not take
effect.

### Releasing a column

A station holds its columns until it is told otherwise, which is correct while a
console is merely offline and wrong once a sensor has been removed for good. **Give
them up** on that station's **Console** tab releases them, and the next station to
send one of those readings takes it. What is already in the archive is not changed.

Changing a station's role or channel releases its columns as well, because it writes
different columns from then on. Removing a station releases them.

## Columns that already hold readings

When a station is set up, the driver reads the archive table and reports which of the
columns it would write already hold data:

```
outTemp        4000 readings, last on 2022-11-21
barometer      4000 readings, last on 2022-11-21
extraTemp1     4000 readings, last on 2022-11-21
```

Those readings came from somewhere: an older console, a different driver, an import. If
this is the same weather station in the same place, writing on is correct and the
series continues. If it is a different sensor, the column ends up holding two of them.
Only you can tell which, so the driver asks rather than choosing.

Where the choice can be avoided, it is: a channel whose `extraTempN` and `extraHumidN`
already hold readings is skipped when a channel is assigned automatically. A second
station therefore lands on a clean channel without any question being asked, and the
confirmation appears only when every free channel has history.

## Configuring stations in weewx.conf

Everything the interface does can be written into `weewx.conf`. A station declared
under `[[stations]]` is the one in force: the interface displays it and declines to
change it, field map included.

```ini
[UltimatePush]
    [[stations]]

        [[[garden]]]
            passkey = AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
            path = /abcdefg12345/report
            [[[[field_map_extensions]]]]
                tf_ch1 = soilTemp1          # spike in the raised bed

        [[[roof]]]
            passkey = BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB
            role = extra
            channel = 4
```

#### passkey or id

What the console sends to identify itself: a PASSKEY for Ecowitt and Ambient hardware,
an ID for Weather Underground, a serial number for WeatherFlow, a MAC address for the
two bridges.

Required only for a station with no `path`. For hardware whose path you choose, leave
it out: nobody knows a console's PASSKEY before it has uploaded once, and the driver
learns it from the first upload and holds the station to it afterwards. No default.

#### path

An upload path belonging to this station, which is both its identity and its secret.
A station needs this or an identity above, and this is the one you can choose before
the console has ever uploaded. Make one with `python -m user.ultimatepush --secret`.
Default is none.

#### role

`main` or `extra`. Default is `main`.

#### channel

Which `extraTempN` and `extraHumidN` an extra station writes to. Default is the next
free channel.

#### password

The secret this station presents, for hardware that carries one. Only Weather
Underground does. Checked on every upload from this station, in constant time, and
uploads that get it wrong are refused. A station's own comes before the `password` in
the driver section, so that two consoles told apart by an `ID` cannot use each other's.
Default is none, and then the driver's is used.

#### infer_unknown

As in the driver section, for this station only. Default is the driver setting.

#### field_map_extensions

This station's own field map. Takes precedence over the catalog and the role. Default
is empty.

Settings written by the web interface are kept in `ultimate-push-web.conf` beside the
console list, not in `weewx.conf`. See [Web interface](Web-interface.md).

## Uploads from stations that are not known

The driver answers only to stations it knows. Anything else is refused and shown in the
web interface with its readings, so that it can be identified before it is accepted.

```
WARNING user.ultimatepush.driver: An ecowitt upload from 1.2.3.5 names station
'BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB', which is not one of this driver's consoles.
```

The reason is the same as everywhere else here: two sensors in one column cannot be
separated afterwards, so nothing writes into an existing station's fields until it has
been accepted.

### Paths that are answered

The driver's own path is always answered, because it is what the setup page tells you
to enter and how every console that cannot be given its own path arrives.

A path belonging to a station is answered. Once any station's own path has been used,
other paths are refused with a 404, except the endpoints burned into firmware and the
path set as `path` in the driver section. Until a station path has been used, every
path is accepted, so that a station set up in the interface but not yet entered into
its console does not cause existing uploads to be refused.

## Where the list of accepted stations is kept

In the database, in the same metadata table WeeWX uses for `lastUpdate`, so that it
travels with the readings it protects and is included in every backup of them. A text
file beside the database is the fallback when there is no database to query.

A station named in `weewx.conf` requires neither. That is the configuration that
survives a rebuilt machine and a copied database, which is why the driver suggests it
the first time it adopts a console:

```
INFO user.ultimatepush.driver: To keep it independent of anything stored, put it in
weewx.conf: 'passkey = AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA' under [UltimatePush].
```
