# Reporting a new sensor

The driver notices when a station sends something it cannot place, and writes out
everything needed to report it. So this is the whole procedure:

```
cat /var/tmp/weewx-ultimate-push-report.txt
```

Paste that into an issue: <https://github.com/hilman2/weewx-ultimate-push/issues/new>

Nothing to configure, nothing to restart, and the console is not touched.

## What is in the file

```
weewx-ultimate-push 0.5.0, 2026-08-28 14:07:12

Protocol: ecowitt

This station sent 8 field(s) the driver could not place on its own. Paste
this whole file into an issue at
https://github.com/hilman2/weewx-ultimate-push/issues/new

Everything that names the station has been replaced already. The rest is weather.

---- what the station sent ----

PASSKEY=X&stationtype=EasyWeatherPro_V5.2.7&runtime=11629&...&model=HP2561AE_Pro_V2.1.4

---- what the driver made of it ----

last24hrainin        -> ecowitt_last24hrainin   group_rain    guessed: name matches rain.*in$
tf_ch1               waiting for a placement (would be soilTemp1)
...
```

The upload carries `model` and `stationtype`, so the console and its firmware come
with it. The PASSKEY, which identifies the station to Ecowitt, is already replaced.

## When the file is not there

It is only written when something cannot be placed, so its absence means the driver
understood everything. If a reading is still missing from your reports, the cause is
elsewhere: see [Troubleshooting](Troubleshooting.md).

The path can be changed, or the whole thing switched off:

```ini
[UltimatePush]
    report_file = /var/tmp/weewx-ultimate-push-report.txt
```

An empty value writes nothing. The file is rewritten at most once per driver start,
so it does not grow and does not churn.

## Without waiting for the driver

To look at a station before it is wired up, or to capture more than one upload:

```
python -m user.ultimatepush --port 8001
```

Point the console at that port for one upload. See [Diagnostics](Diagnostics.md).

## When more than the payload is needed

A genuinely new kind of sensor sends names nobody has seen. `bgt=75.3` says neither
what is measured nor in what unit. If yours is the first of its kind, add:

- what the sensor is, e.g. *WN38, black globe thermometer*
- what the WS View Plus app shows for it at the same moment, e.g. *24.1 °C at 14:05*

That second line settles both the quantity and the unit, because it ties a number in
the payload to a reading you can see. Without it, someone will ask.

## What happens then

A field that follows a pattern the driver knows needs no release: a ninth channel of
a family that goes up to eight is worked out from the eight. A sensor nobody has seen
is added to the catalog and arrives with the next version.

## If you cannot wait

Map it yourself:

```ini
[UltimatePush]
    [[field_map_extensions]]
        newfield_ch1 = extraTemp7
```

and, if the field is not one your schema already has:

```
weectl database add-column extraTemp7 --type REAL -y
```

Please still open the issue. What works for you works for everybody with that sensor.
