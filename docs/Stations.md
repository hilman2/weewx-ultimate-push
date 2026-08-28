# Stations

One station needs nothing on this page. It uploads, the driver records it, and every
reading goes where it belongs. That case is meant to stay that simple, and everything
below only starts to matter once there is a second one.

## Setting one up

Open the [web interface](Web-interface), give the station a name and say what it is.

For hardware whose upload path is yours to choose, that is the whole of it. The driver
makes a path for that station and shows you what to type:

| | |
|---|---|
| Protocol Type | Ecowitt |
| Server IP / Hostname | 192.168.1.50 |
| Path | `/E0rbpxexKCsb/report` |
| Port | 8000 |

From the first upload the driver knows which station that is. Nothing was adopted and
nothing was guessed.

### Why the path and not the PASSKEY

Because the path is a secret and a PASSKEY is not.

Every Ecowitt and Ambient console sends a PASSKEY built from its MAC address, in every
upload, in the clear. It says which console sent something, which is useful, but anybody
who has seen one upload can repeat it. The path is known only to whoever was shown it.

So where the hardware can carry a path, that is the identity. Where it cannot, the
PASSKEY is what there is, and the driver falls back to it.

### Hardware that cannot be pointed anywhere

Three of the six cannot be set up in advance, and the interface says so rather than
offering something that would not work:

| | Why |
|---|---|
| WeatherFlow | The hub broadcasts. Nothing is configured on it at all. |
| Acurite | The bridge posts to Chaney's servers. Its path is in the firmware. |
| LaCrosse | The same, to its own maker. |

These are **adopted**: point them here, and the first thing that arrives turns up in the
interface as something waiting to be let in, with its readings, so you can see whether
it is yours. One click accepts it.

The first console a fresh driver ever hears is adopted without being asked, because at
that point there is nothing it could be confused with. Everything after that waits.

## Which station may fill which field

Two stations both send `outTemp`, and there is one `outTemp`. Left alone they would take
turns writing it every few seconds, and afterwards the column would hold a mixture that
nothing can separate. So each station has a role.

**`main`** is the station. Its readings go where they belong. Exactly one station is
this, and with only one station it is that one without anyone deciding.

**`extra`** is a sensor. Its temperature and humidity are moved to `extraTempN` and
`extraHumidN`, where N is a channel the driver picks. Everything else it sends is
**dropped rather than written over the main station's**, and said once in the log:

```
WARNING user.ultimatepush.driver: 27 reading(s) from station 'roof' are not being
written, because the main station already fills those columns and two sensors in one
column cannot be separated afterwards: UV, barometer, dayRain, ...
```

Be clear about the limit. The standard schema has `extraTemp1` to `extraTemp8` and
`extraHumid1` to `extraHumid8`, and nothing of the sort for wind, rain or pressure. A
second full weather station therefore contributes its temperature and its humidity, and
anything else it sends needs a field and a column of its own.

That is what the Fields tab is for. Pick any WeeWX field for any reading; the box offers
the ones that measure the same thing first, then everything else, then a field of your
own. A field with no column shows the `weectl database add-column` command that makes
it.

A field you place by hand outranks the role. Placing it is the decision.

### The interface says when two stations collide

```
[ ] sharing     29 column(s) more than one station would fill
                UV, barometer, dayRain, eventRain, hourRain, inHumidity ...
```

Setting a role settles it. Nothing else in WeeWX would have said anything.

## Writing it by hand

Everything the interface does can be written into `weewx.conf`, and a station written
there is the one in force: the interface shows it and declines to change it.

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

| Option | Meaning |
|---|---|
| `passkey` or `id` | What the console sends to name itself. A PASSKEY for Ecowitt and Ambient, an ID for Weather Underground, a serial number for WeatherFlow, a MAC for the two bridges. |
| `path` | An upload path of this station's own. Its identity and its secret at once. |
| `role` | `main` or `extra`. Default `main`. |
| `channel` | Which `extraTempN` an extra station gets. |
| `infer_unknown` | As in the driver section, for this station only. |
| `field_map_extensions` | This station's own field map. Wins over everything. |

Two stations set to `main` is a mistake the driver says out loud at startup. It still
refuses to let the second one overwrite the first, but it should not have to.

What the interface writes goes in `ultimate-push-web.conf` beside the console list, not
here. See [Web interface](Web-interface).

## What happens to an upload nobody expected

The driver answers only to stations it knows. Anything else is refused and shown in the
interface with its readings.

```
WARNING user.ultimatepush.driver: An ecowitt upload from 192.168.1.51 names station
'9A2B4C6D8E0F1A3B5C7D9E1F2A4B6C8D', which is not one of this driver's consoles.
```

That is not paranoia about strangers. It is the same rule as everywhere else here: two
sensors in one column cannot be separated afterwards, so nothing writes into your
station's fields until you have said it may.

### Once a path has been used, others stop being answered

A station with a path of its own is proof that the path works. From the first upload
that arrives on one, a request to any other path gets a 404, except the endpoints that
are burned into firmware and the one you may have set as `path` in the driver section.

Until then everything is accepted, so that setting a station up here and not yet having
typed it into the console does not bounce the uploads you already have.

## Where the list of accepted stations lives

In the database, in the same metadata table WeeWX keeps `lastUpdate` in, so that it
travels with the readings it protects and is in every backup of them. A text file beside
the database is the fallback when there is no database to ask.

A station named in `weewx.conf` needs neither. That is the version that survives a
rebuilt machine and a copied database, which is why the driver suggests it the first
time it adopts one:

```
INFO user.ultimatepush.driver: To keep it independent of anything stored, put it in
weewx.conf: 'passkey = 3178AB6B42A759F51A5A4AD72E37F8DE' under [UltimatePush].
```
