# Unknown fields

A field the catalog does not cover is examined rather than dropped. Two things can be
said about one without guessing, and they are kept apart.

Only hardware that uploads has a catalog. A station this machine reads over a cable
hands over WeeWX fields directly, so it has no unknown fields and nothing here happens
to it.

## Derived

The field continues a series the catalog describes. If `zz_ch1` and `zz_ch2` are
known, `zz_ch3` follows from them: the hardware numbers its own channels, and the
catalog supplies both ends of the series.

```
INFO user.ultimatepush.mapping: New field 'leafwetness_ch5' -> 'leafWet5' (group_percent),
continues leafwetness_ch, e.g. leafWet1
```

Taken automatically, unless the family's placement is a convention rather than a
reading. Those wait for you, and the log gives the line to add:

```
INFO user.ultimatepush.mapping: New channel 'temp9f' would go to 'extraTemp9'.
Which sensor that is, and whether that field is free, only you know. Add
'temp9f = extraTemp9' under [[field_map_extensions]] to accept it.
```

Knowing where a channel belongs is not the same as knowing the field is free. A new
WN34 channel would go to `extraTemp`, where a sensor configured two years ago may
already have history, and two series in one column cannot be separated afterwards.
A family with nowhere else to be placed, such as a laser rangefinder's depth or a
lightning count, is taken without asking. See [Field map](Field-map.md).

## Guessed

The name says what the reading is. Most of this hardware is consistent about it:

| Pattern | Reading |
|---|---|
| `rssi` | signal strength, dB |
| `_sig` | signal quality, a count |
| `batt` | battery |
| `_time` | a timestamp |
| `barom...in` | pressure, inHg |
| `rain...in`, `rain...piezo` | rain, inches |
| `mph` | speed, mph |
| `winddir...` | direction, degrees |
| `temp...`, `tf_...`, `soiltemp`, `thermo` | temperature, °F |
| `humidity`, `moisture`, `_hum` | percent |
| `pm1`, `pm4`, `pm10`, `pm25` | concentration, µg/m³ |
| `co2`, `co` | ppm |
| `solarradiation`, `radiation` | W/m² |
| `uv` | UV index |
| `vpd` | pressure, kPa |
| `depth_ch`, `air_ch`, `thi_ch` | distance, mm |

Reported, not taken:

```
INFO user.ultimatepush.mapping: New field 'yearlyrainin' looks like group_rain
(name matches rain.*in$|rain.*piezo$), but it was only guessed. Left out.
Add it to field_map_extensions to keep it.
```

A guessed field goes to the protocol's own prefix plus the raw name: `ecowitt_`,
`wu_`, `ambient_`, `acurite_` and so on. Two protocols that send the same unrecognised
name therefore land in different columns, which is the safe way round: a name nobody
has identified is not known to mean the same thing in both.

## Past the published channel count

Each maker publishes how many channels a sensor supports. A channel beyond that is
real but not routine, so it is reported rather than derived:

```
soilmoisture17   soilMoist17   channel 17, past the 16 a WH51 is said to support
```

Either the published figures have moved on, or something else is going on. Both are
worth a look before the reading lands in a column.

## Nothing can be said

```
INFO user.ultimatepush.mapping: No idea what 'wizzlefrob' is. Left out.
```

Please report it. See [Reporting a new sensor](New-sensors.md).

## The setting

```ini
[UltimatePush]
    infer_unknown = series
```

| Value | Effect |
|---|---|
| `off` | Nothing is taken. Everything unknown is logged and dropped. |
| `series` | Derived fields are taken, unless their placement is a convention. Guesses are logged. **Default.** |
| `all` | Guesses are taken too, under the protocol's prefix plus the raw name. |

`all` gets you the reading sooner, at the risk of a unit nobody checked. It is the
right setting while working out what a station sends, which is why
`python -m user.ultimatepush` uses it.

Whatever the setting, a field is reported once per run. Restart the driver to see the
messages again.
