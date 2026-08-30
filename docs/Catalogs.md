# Catalogs

A catalog is one module per protocol, holding nothing but data: which raw name means
what, in which unit, and which WeeWX field it belongs in. Around 900 raw names are
covered.

There is one per protocol and none for a driver this machine reads: a driver hands over
WeeWX fields already, so there is nothing to translate. See
[Hosted hardware](Hosted-hardware.md).

This page is about where those names come from and how the placements were decided. To
look up where a single field goes, use [Ecowitt sensors](Ecowitt-sensors.md); to follow
one reading from
the station to a column, use [Field map](Field-map.md).

## Generated or written out

Two catalogs are generated, because their hardware keeps gaining sensors and a generated
catalog makes each addition a reviewable diff:

- `tools/import_catalog.py` reads the Ecowitt names from the `ecowittcustom` driver by
  [Werner Krenn](https://github.com/WernerKr/Ecowitt-or-DAVIS-stations-and-Season-skin).
- `tools/import_ambient.py` reads the Ambient names from the `ambient_station`
  integration in Home Assistant, which is maintained against real hardware.

The remaining four are written out, because their protocols are complete. The Weather
Underground specification was published once and then withdrawn; the copy this catalog
was derived from is in `tests/fixtures/wunderground/spec.txt`, where a test checks the
catalog against it. The WeatherFlow UDP reference is current and public. The Acurite and
LaCrosse names come from frames captured from real hardware.

## Rebuilding the Ecowitt catalog

`bin/user/ultimatepush/catalogs/ecowitt.py` is generated, not written:

```
python tools/import_catalog.py path/to/ecowittcustom.py \
    --schema path/to/weewx/schemas/wview_extended.py
```

## The three lists that decide placement

What a field measures is determined by the hardware. Where it is written is decided in
`tools/import_catalog.py`, in three lists:

- `CHANNELS` — how far each sensor family reaches, from the manufacturer's
  compatibility table
- `REMAP` — families placed differently from the source, with the reason beside each.
  The WN34 and the WH52 are here.
- `OVERRIDES` — single fields, likewise with the reason

The tool reports what it could not settle: fields written by more than one reading,
readings with more than one candidate field, raw names with no target at all. None of it
passes quietly.

`CONTESTED` in the generated catalog comes from `REMAP` and `OVERRIDES`, so the list of
fields that wait for the user cannot drift from the decisions that made them wait. What
the user then sees is in [Unknown fields](Unknown-fields.md).

## The generated pages

[Ecowitt sensors](Ecowitt-sensors.md) and [Hardware](Hardware.md) are generated from
the catalog:

```
python tools/build_reference.py
python tools/build_hardware.py
```

The hardware page keeps the descriptions in the tool and takes the field lists from the
catalog, so the two cannot drift apart. It also prints how many catalog fields belong to
no device, which is how gaps in the list get found. Eight are unidentified at the
moment.

## Checking against Ecowitt

Ecowitt publishes its cloud API, and the pages behind the site come from a plain
endpoint. The channel counts can be verified rather than trusted:

```
python tools/check_against_ecowitt.py
```

```
Ecowitt family           model    documented ours
leaf_ch                  WN35     8          8
soil_ch                  WH51     16         16
temp_ch                  WN34     8          8
```

What this cannot check is the raw field names. The cloud API says
`soil_ch1.soilmoisture` where a console posts `soilmoisture1`, and nothing published
connects the two.
