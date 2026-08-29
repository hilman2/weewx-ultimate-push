# Field map

How a reading gets from the station to a column.

```
station  ──►  protocol   ──►  raw field  ──►  WeeWX field  ──►  database column
              ecowitt        tf_ch1          extraTemp9        extraTemp9
```

The protocol is determined first, because the same raw name means different things in
different catalogs. `UV` is an index in one and microwatts per square
centimetre in another. See [Protocols](Protocols) for how an upload is recognised, and
check the log line that says which catalog was used before reading anything below as a
bug.

Three things then decide the middle step, in this order.

## 1. Your own mapping

`field_map_extensions` decides where a reading goes, ahead of the catalog and ahead
of the station's role.

```ini
[UltimatePush]
    [[field_map_extensions]]
        tf_ch1 = soilTemp5
        soilmoisture1 = soilMoist1
```

The left side is the raw name as the console sends it. The right side is any WeeWX
field name. The driver does not check whether the field is a sensible destination,
because only the person who installed the sensor knows where it is.

One thing still comes after it. A column belongs to whichever station fills it first,
and a placement does not take a column away from the station that holds it: the
reading is dropped instead, and the checklist reports it. Placing the same field for
another station on the Fields tab does hand the column over, because that is a
decision made in front of what it costs. See [Stations](Stations.md).

## 2. The catalog

One per protocol. The Ecowitt one has 532 raw fields; see [Sensors](Sensors) for the
full list, or ask the driver:

```
python -c "import sys; sys.path.insert(0, '/etc/weewx/bin/user'); \
from ultimatepush.catalogs import ecowitt; print(ecowitt.FIELDS['tf_ch1'])"
```

## 3. Inference

A field in neither of the above is examined rather than dropped. See
[Unknown fields](Unknown-fields).

## Fields that wait for you

Some readings have no natural home. Putting them in the wrong one cannot be undone:
two sensors in one column can never be told apart again. Those fields are not written
until you name them.

There are two kinds.

**Multi-channel sensors.** A WN34 reports on `tf_ch1` whether it is a spike in a bed,
a silicone lead in a pool or a probe on a north wall. Ecowitt lists the three as one
row, `WN34 S/L/D`, and nothing in an upload distinguishes them.

**Fields other drivers place elsewhere.** Where two placements are both defensible,
neither is assumed.

The log names both candidates, once per field:

```
WARNING user.ultimatepush.mapping: 'tf_ch1' is not being written, because drivers
disagree about where it goes. The wrong choice mixes two sensors into one column,
and afterwards they cannot be separated. Add one of these under
[[field_map_extensions]]: 'tf_ch1 = extraTemp9' for this driver's placement, or
'tf_ch1 = soilTemp1' if your history came from ecowittcustom.
```

`python -m user.ultimatepush` prints the whole block ready to paste.

On a station with two WN34 probes, a WH52 and a lightning sensor, six fields wait and
twenty-nine arrive without a word. An outdoor temperature is an outdoor temperature
whatever wrote it last, so nothing is asked about that.

## Where the default placements are

| Sensor | Raw | Goes to |
|---|---|---|
| WH31 and relatives | `temp1f`, `humidity1` | `extraTemp1..8`, `extraHumid1..8` |
| WN34 S/L/D | `tf_ch1..8` | `extraTemp9..16` (waits) |
| WN35 | `leafwetness_ch1..8` | `leafWet1..8` |
| WH51 | `soilmoisture1..16` | `soilMoist1..16` |
| WH52 | `soil_ec_hum1..16` | `soilMoist1..16` |
| WH52 temperature | `soil_ec_temp1..16` | `soilTemp1..16` (waits) |
| WH52 conductivity | `soil_ec1..16` | `soilEC1..16` |
| WH41, WH43 | `pm25_ch1..4` | `pm25_1..4` |
| WH55 | `leak_ch1..4` | `leak_1..4` |
| WH57 | `lightning`, `lightning_num` | `lightning_distance`, `lightning_num` |
| WH54 / LDS01 | `air_ch1..4`, `depth_ch1..4` | same names |

The WH51 and the WH52 share one pool of 16 channels, so `soilmoisture3` and
`soil_ec_hum3` are the same channel with a different probe in it. If both ever arrive
for the same number, the driver says so once:

```
WARNING user.ultimatepush.mapping: Both 'soilmoisture3' and 'soil_ec_hum3' arrived, and
they map to the same field. One will overwrite the other. Give one of them a field
of its own in field_map_extensions.
```

## Units

A field's unit group comes with its place in the catalog, and the driver registers it
with WeeWX at startup. Fields WeeWX already knows keep their own group; nothing here
overrides those.

Which unit system a packet is in comes from the protocol, not from the driver:

| Protocol | Unit system | What that means |
|---|---|---|
| Ecowitt, Ambient, Acurite, Weather Underground | `weewx.US` | °F, inHg, inches, mph |
| Weather Underground, metric dialect | `weewx.METRIC` | °C, mbar, cm, km/h |
| WeatherFlow, LaCrosse | `weewx.METRICWX` | °C, mbar, mm, m/s |

WeeWX converts for display according to your report settings, and the database stores
whatever the packet said.

A handful of readings arrive in a unit other than the one WeeWX keeps that column in,
and those are converted on the way through. The Weather Underground specification gives
some of its pollution figures in parts per billion where WeeWX keeps parts per million;
a LaCrosse gateway sends metric everything and then sends its rain in inches. Nothing
else is touched: a scaled number is a number nobody can check against the payload, so
the list is kept short and each entry has its reason written next to it in the
catalog.

## Checking a mapping

```
python -m user.ultimatepush --port 8001
```

Prints every reading with the field it went to. See [Diagnostics](Diagnostics).
