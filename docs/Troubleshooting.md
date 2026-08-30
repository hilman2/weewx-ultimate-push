# Troubleshooting

## Nothing arrives at all

The log should show this at startup:

```
INFO weewx.listener: Listening for HTTP requests on *:8000
```

If it does not, the driver is not running. Check `station_type = UltimatePush` and that
the `[UltimatePush]` section has `driver = user.ultimatepush.driver`.

If it does, watch the port:

```
sudo tcpdump -i any -n port 8000
```

Nothing there means the problem is between console and machine:

- Address or port wrong in the app. Check the page again after leaving it; WS View
  Plus sometimes reports a save that did not happen.
- A firewall. `sudo ufw allow 8000/tcp` where ufw is in use.
- The console on a different network segment from WeeWX.
- For WeatherFlow: a broadcast does not cross a router, so the hub and WeeWX have to
  be on the same segment. Check that the socket is even open, with
  `ss -ulnp | grep 50222`. If it is not, `protocols` does not name `weatherflow`.
- For Acurite or LaCrosse: the DNS entry is not reaching the bridge. Check with
  `dig hubapi.myacurite.com @your-router`, not on the WeeWX machine, whose own
  `hosts` file the bridge never sees.

## Address already in use

```
ERROR weewx.listener: Cannot listen on 0.0.0.0:8000: [Errno 98] Address already in use
```

Something else holds the port:

```
ss -tlnp | grep 8000
```

Either stop it, or give the driver another port and change the console to match. A
second WeeWX instance with the same port is a common cause.

## Requests arrive but nothing is stored

Check the response first. The console treats an upload as failed until it has read
one, and stops trying after enough failures.

```
curl -s -o /dev/null -w '%{http_code}\n' -X POST -d 'tempf=59.7' http://localhost:8000/
```

| Code | Meaning |
|---|---|
| 200 | Fine. |
| 404 | `path` is set and does not match what the console sends. |
| 403 | `token` or `allowed_hosts` rejected it. |
| 413 | The upload is larger than `max_body`. |

An empty 200 means no protocol claimed the upload. See below.

## Nothing recognised the upload

```
WARNING user.ultimatepush.driver: A request from 1.2.3.6 to /data/report/ matched
none of the protocols this driver is listening for (ecowitt, ambient, acurite,
lacrosse, wunderground). Nothing in it says which protocol it is, so reading it would
mean guessing which catalog its field names belong to.
```

Something posted readings with nothing in them that names a protocol or a station. It
happens with a proxy that strips the query, with a script somebody wrote, and with a
console configured for a protocol this driver does not read.

Turn on `log_raw = true` and restart to see exactly what arrived. If you know what it
is, name it and the guessing stops:

```ini
[UltimatePush]
    protocols = wunderground
```

With one protocol configured there is nothing left to guess, and an upload with only
readings in it is read as that one.

## It was read with the wrong catalog

The log says which, on the first upload from each station:

```
INFO user.ultimatepush.driver: Reading wunderground uploads with the
'wunderground/metric' catalog, 19 fields.
```

If that is not the protocol you expected, `protocols` will settle it. This is worth
checking when a station sends fields you know it has and half of them go missing: a
Weather Underground upload read as Ecowitt loses the pressure, the indoor readings and
the UV without any error at all.

## A sensor is missing from reports

In order:

**1. Does it arrive?**

```
python -m user.ultimatepush --port 8001
```

Not listed means the station is not sending it. Check that the sensor is registered in
the console's own app and shows a reading there.

The command also prints which protocol and which catalog the upload was read with. If
that is wrong, everything after it is wrong too.

**2. Is it waiting for a decision?**

```
WARNING user.ultimatepush.mapping: 'tf_ch1' is not being written, because drivers
disagree about where it goes.
```

Name it in `field_map_extensions`. See [Field map](Field-map.md).

**3. Was it unknown?**

```
INFO user.ultimatepush.mapping: No idea what 'newfield_ch1' is. Left out.
```

See [Reporting a new sensor](New-sensors.md).

**4. Does it have a column?**

A field without a column appears as a current value and is gone at the next archive
record. See [Database columns](Database-columns.md).

**5. Does the skin show that field?**

Most skins list which fields they display. A field the skin does not name will not
appear however well it is stored.

## Rain stays empty

Almost all of this hardware sends rain as running counters: `dailyrainin`,
`hourlyrainin`, `eventrainin` and their equivalents. It never sends the amount that
fell since the last upload, which is what WeeWX calls `rain` and what every rain total
is built from. `StdWXCalculate` turns one into the other, and the installer sets it up,
so a fresh install needs nothing. See [Installation](Installation.md#rain).

Two protocols the default does not suit. The driver says so at startup:

```
WARNING user.ultimatepush.driver: StdWXCalculate differences 'dayRain' to get the
rain, and LaCrosse LW30x sends totalRain instead. Rain from LaCrosse LW30x will not be
recorded until 'input' names a counter it sends.
```

| Protocol | `input` |
|---|---|
| Ecowitt, Ambient, Weather Underground, Acurite | `dayRain` |
| LaCrosse | `totalRain` |
| WeatherFlow | none needed; it already sends `rain` |

```ini
[StdWXCalculate]
    [[Delta]]
        [[[rain]]]
            input = dayRain
```

The counter resets at midnight. WeeWX notices and logs `'rain' counter reset
detected`, then skips that one interval rather than recording a day's worth of rain
in it.

## Readings look wrong by a factor

Almost always a unit, and there are three places it can go wrong.

**The protocol was read as the wrong one.** Check the catalog line in the log. `UV` is
an index in one Weather Underground dialect and microwatts per square centimetre in
the other, forty times apart.

**The metric wind.** See below.

**A guessed field.** One the driver had to guess may have been given the wrong group.
`infer_unknown = all` accepts guesses, and this is the risk it carries. Map the field
explicitly instead, and report it so the catalog gets it right.

Which unit system a packet is in comes from the protocol, and the log says which
catalog was used. Ecowitt, Ambient, Acurite and imperial Weather Underground are US:
°F, inHg, inches, mph. WeatherFlow and LaCrosse are metric. WeeWX converts for
display either way.

## Two sensors in one column

```
WARNING user.ultimatepush.mapping: Both 'soilmoisture3' and 'soil_ec_hum3' arrived, and
they map to the same field. One will overwrite the other.
```

A WH51 and a WH52 on the same channel number. Give one of them a field of its own:

```ini
[[field_map_extensions]]
    soil_ec_hum3 = soilMoist11
```

The readings already mixed cannot be separated afterwards.

## Gaps in the data

Check the upload interval in WS View Plus against the archive interval in WeeWX. An
archive record is written from whatever arrived during the interval; if nothing did,
the record is empty.

```
WARNING weewx.listener: Queue full. Dropped the oldest request (3 so far).
```

means uploads arrived faster than they were processed. Raise `queue_size`, or lower
the upload frequency. At an eight second interval this can happen while reports are
being generated on a slow machine.

## The driver stops after a while

Look for what came before it in the log. Two known shapes:

- The console changed address, e.g. after a DHCP lease expired, and `allowed_hosts`
  no longer matches.
- The machine slept. A listener does not survive suspend on every platform; restart
  WeeWX.

## Reporting a problem

Include:

- What the log says, with a few lines before it
- The output of `python -m user.ultimatepush --port 8001`, with the `PASSKEY` replaced
- Console model and firmware, from *About* in WS View Plus
- WeeWX version, from `weectl --version`

<https://github.com/hilman2/weewx-ultimate-push/issues>


## The wind is out by a factor of 3.6

A Fine Offset console under *Weather logger* or *HP1001* firmware sends metric, and
nothing in the payload says whether its wind is kilometres per hour or metres per
second. The default is kilometres per hour. If your readings are consistently 3.6
times too small:

```ini
[UltimatePush]
    metric_wind = mps
```

Consistently 3.6 times too large means the opposite, and the default is right for you.

## A second station records nothing but its temperature

This is what an extra sensor is. Its temperature and humidity go to `extraTempN` and
`extraHumidN`; readings that another station already writes are dropped rather than
written over that station's.

```
WARNING user.ultimatepush.driver: 15 reading(s) from station 'roof' are not being
written, because garden already fill(s) those columns and two sensors in one column
cannot be separated afterwards: UV, barometer, dayRain, ...
```

The checklist lists them, with the station that holds each column. To keep a reading,
give it a field of its own on the Fields tab and add the column if the database has
none. See [Stations](Stations.md).

## A station on a cable records nothing

Everything above is about hardware that uploads. A station this machine reads is a
different case: nothing arrives because nothing was asked for, and the log says which.

The driver names what it is running at startup:

```
INFO user.ultimatepush.hardware: Hosting 1 driver(s): Vantage. The archive station is
Vantage.
```

If that line is missing, the section is not being read. Check `station_types` under
`[[hardware]]`, and that the name matches a top-level section exactly.

If the driver cannot be opened, it says so and keeps trying:

```
ERROR user.ultimatepush.hardware: The Vantage driver failed (1 so far): could not open
port /dev/ttyUSB0. Trying again in 10 seconds.
```

The wait doubles to five minutes. Nothing else stops: the stations that upload keep
being recorded and the web interface stays up.

The usual causes, in order:

- **The port is wrong.** `ls -l /dev/serial/by-id/` lists what is actually there.
- **The port moved.** `/dev/ttyUSB0` becomes `/dev/ttyUSB1` when something else is
  plugged in. The name under `by-id` does not.
- **WeeWX cannot open it.** The `weewx` user has to be in the group that owns the
  device, which is usually `dialout`. `ls -l /dev/ttyUSB0` says which.
- **Something else has it.** Another program holding the port makes it look absent.

## The driver will not start at all, with a wired station

If the archive station cannot be opened, the driver does not start. That is deliberate:
the archive record would otherwise be worked out from software while the console's
logger held the real ones, and those records would be wrong rather than missing.

A station that is not the archive station is logged and left out, and the rest run.

```
ERROR user.ultimatepush.hardware: The WMR100 driver could not be opened, so it is left
out: no device found.
```

## A station records nothing at all after a restart

Once, and only until the main station's next upload:

```
INFO user.ultimatepush.driver: Holding back station 'roof' until the main station has
been heard once, so that its readings cannot land in the main station's columns.
```

The driver writes down which station fills which column, so this happens on the first
run and not again. Seeing it after every restart means the settings file cannot be
written; the log says so separately.

## Two stations are set up as the main one

Only a configuration file written by hand can produce this. The interface does not.

```
ERROR user.ultimatepush.driver: Station 'roof' is set up as the main station, and so
is 'garden'. Two of them write the same columns, and afterwards nothing can tell one
sensor's readings from the other's.
```

The first station declared is the one that writes. The second fills only the columns
nobody else has. Give it `role = extra` and a `channel`, in `weewx.conf` or in the web
interface.

## A console that was let in is still being refused

Check that the identity in the settings file is the one the console sends. The
interface takes it from the upload, so this only happens to a station written by hand.

```
WARNING user.ultimatepush.driver: An ecowitt upload from 1.2.3.5 names station
'9A2B...', which is not one of this driver's consoles.
```

## Setting up a station asks about columns that already hold readings

That is the check working. Those readings came from an older console, another driver
or an import. Continuing the series is right when it is the same weather station in
the same place, and mixes two sensors when it is not.

Where a channel is being handed out, one whose columns are empty is chosen first, so
this only appears when every free channel has history, or for the main station's own
columns.
