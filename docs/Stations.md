# Stations

A single station requires nothing on this page. It uploads, the driver records it, and
every reading is written where it belongs. Everything below applies once there is a
second station.

## Setting up a station

Open the [web interface](Web-interface.md), enter a name for the station, and select
what it is.

For hardware whose upload path is yours to choose, that completes the setup. The driver
generates a path for that station and displays the settings to enter into its app:

| | |
|---|---|
| Protocol Type | Ecowitt |
| Server IP / Hostname | 192.168.1.50 |
| Path | `/E0rbpxexKCsb/report` |
| Port | 8000 |

From the first upload the driver knows which station sent it. The same settings remain
available on the **Stations** tab afterwards, for a console that has to be set up again.

### Why the path rather than the PASSKEY

The path is a secret and a PASSKEY is not.

Every Ecowitt and Ambient console sends a PASSKEY derived from its MAC address, in
every upload, in the clear. It identifies the console, but anyone who has seen one
upload can repeat it. The path is known only to whoever was shown it.

Where the hardware can be given a path, the path is the identity. Where it cannot, the
PASSKEY is used instead.

### Hardware that cannot be pointed anywhere

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
    outTemp = path:/E0rbpxexKCsb/report
    extraTemp1 = path:/g0nTdxurjQd8/report
    soilMoist1 = path:/g0nTdxurjQd8/report
```

Because it is recorded rather than learned again at each startup, an extra station is
held back only once — until the main station's first upload, ever. After that a restart
costs no readings.

The **Stations** tab lists the columns each station fills. The checklist reports
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
them up** on the Stations tab releases them, and the next station to send one of those
readings takes it. What is already in the archive is not changed.

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
            passkey = 3178AB6B42A759F51A5A4AD72E37F8DE
            path = /a8f3c1e0/report
            [[[[field_map_extensions]]]]
                tf_ch1 = soilTemp1          # spike in the raised bed

        [[[roof]]]
            passkey = 9A2B4C6D8E0F1A3B5C7D9E1F2A4B6C8D
            role = extra
            channel = 4
```

#### passkey or id

What the console sends to identify itself: a PASSKEY for Ecowitt and Ambient hardware,
an ID for Weather Underground, a serial number for WeatherFlow, a MAC address for the
two bridges. One of the two is required. No default.

#### path

An upload path belonging to this station, which is both its identity and its secret.
Default is none.

#### role

`main` or `extra`. Default is `main`.

#### channel

Which `extraTempN` and `extraHumidN` an extra station writes to. Default is the next
free channel.

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
WARNING user.ultimatepush.driver: An ecowitt upload from 192.168.1.51 names station
'9A2B4C6D8E0F1A3B5C7D9E1F2A4B6C8D', which is not one of this driver's consoles.
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
weewx.conf: 'passkey = 3178AB6B42A759F51A5A4AD72E37F8DE' under [UltimatePush].
```
