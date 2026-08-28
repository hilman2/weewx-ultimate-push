# Development

## Layout

```
bin/user/ultimatepush/
    transport.py   text in, name and value pairs out. No sockets, no WeeWX.
    protocols/     one module per protocol: how to recognise it, what it answers,
                   what names its station, which catalog reads it.
    catalogs/      one module per protocol, and nothing in any of them but data.
    infer.py       what to do with a field a catalog does not cover.
    mapping.py     the three above, combined into a packet. Still no WeeWX.
    columns.py     which database columns a packet needs.
    consoles.py    which stations this driver answers to.
    server.py      an answer per protocol, and several listeners behind one iterator.
    activity.py    what each station has been doing lately. Bounded, in memory.
    overrides.py   the settings the web interface may change, in a file of its own.
    admin.py       the web interface: routing and the JSON API.
    page.py        the web interface, as one self-contained page.
    driver.py      the WeeWX end: loop packets, unit groups, shutdown.
    __main__.py    the diagnostic command.
bin/user/listener.py   WeeWX's own listener, bundled for WeeWX older than 5.6.
tools/                 catalog and reference generators.
tests/                 pytest, with captured payloads in tests/fixtures.
```

Everything except `driver.py`, `server.py`, `admin.py` and `__main__.py` runs without
WeeWX installed. That is what lets the tests work from a captured payload rather than from
mocks, and it is worth keeping: a catalog is data, and data should be checkable
without a weather station or a WeeWX.

## Protocols and dialects

Two words, kept apart on purpose.

A **protocol** is an exchange: a path, an answer, a way of naming the station.

A **dialect** is a catalog: what the names mean and what units they arrive in.

Detection works on protocols, mapping works on dialects, and they are not the same
question. Weather Underground has two dialects on one endpoint. The driver keeps one
mapper per dialect it has actually seen, because inference learned from `tempf` and
`soiltemp2f` has no business being applied to `outtemp` and `absbaro`.

## Adding a protocol

`bin/user/ultimatepush/protocols/` has six worked examples. A new one is a class and
a catalog:

```python
class MyProtocol(Protocol):
    name = 'mine'
    label = 'My Weather Thing'
    hardware = 'the boxes this is for'

    answer = 'ok'                 # what its firmware waits for
    content_type = 'text/plain'
    identity = ('serial',)        # which field names the station
    units = US
    rain_counter = 'dayRain'      # what StdDelta has to difference, or None

    fields = _catalog.FIELDS
    groups = _catalog.GROUPS

    @classmethod
    def claims(cls, request, raw):
        return 5 if 'something_only_mine_sends' in raw else 0
```

Then add it to `registry()`, add a captured payload to `tests/fixtures`, and write a
test that says what should come out of it.

`claims` returns how sure the protocol is, and the surest wins. Keep the numbers
honest: 5 or 6 for something only this protocol sends, 2 or 3 for something it merely
cannot rule out. A protocol that overstates itself takes uploads from one that would
have read them properly.

If the payload is not name and value pairs, override `readings`. WeatherFlow unpacks
JSON arrays there; Acurite and LaCrosse rename theirs to keep two sensors apart.

## Tests

```
pip install pytest
python -m pytest tests -q
```

Without WeeWX, the tests that need it are skipped. With it, everything runs:

```
pip install weewx
python -m pytest tests -q
```

CI runs both, across Python 3.8 to 3.13, plus a vermin check against 3.7.

## The catalog

`bin/user/ultimatepush/catalogs/ecowitt.py` is generated, not written:

```
python tools/import_catalog.py path/to/ecowittcustom.py \
    --schema path/to/weewx/schemas/wview_extended.py
```

Three lists in `tools/import_catalog.py` decide where a reading goes:

- `CHANNELS` — how far each sensor family reaches
- `REMAP` — families placed differently from the source, with the reason
- `OVERRIDES` — single fields, likewise

The tool reports what it could not settle: fields written by more than one reading,
readings with more than one candidate field, raw names with no target. None of it
passes quietly.

`CONTESTED` in the generated catalog comes from `REMAP` and `OVERRIDES`, so the list
of fields that wait for the user cannot drift from the decisions that made them wait.

## The generated pages

`docs/Sensors.md` and `docs/Hardware.md` are generated:

```
python tools/build_reference.py
python tools/build_hardware.py
```

The hardware page keeps the descriptions in the tool and takes the field lists from
the catalog, so the two cannot drift apart. It also prints how many catalog fields
belong to no device, which is how gaps in the list get found. Eight are unidentified
at the moment.

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

## The bundled listener

`bin/user/listener.py` is a copy of `weewx/listener.py`, byte for byte. A test
compares the two when WeeWX has one, so the copy cannot drift. Do not edit it; when
the core carries the listener, the driver picks that up on its own and the copy can
go.

That is also why `server.py` exists. The core listener sets one content type for the
whole listener, and six protocols want different ones on the same port. So the answer
carries its own content type, kept per thread, in a subclass here rather than in a
change to a file that has to stay identical. `Fan` is there for the same reason: a
driver iterates one thing, and a station with a WeatherFlow hub and an Ecowitt gateway
needs two sockets.

## Adding a field

1. Add the raw name to the catalog. Through the generator where there is one, not by
   hand.
2. Give it a unit group if WeeWX does not know the field.
3. If it belongs to a sensor family the driver does not know, add the family to
   `CHANNELS` with its channel count.
4. If another protocol already sends the same reading, send it to the same WeeWX
   field. A test compares the catalogs and will say so if you do not.
5. Add a captured payload to `tests/fixtures` and a test that says what should come
   out of it.

## Releasing

Set the version in `install.py` and `bin/user/ultimatepush/__init__.py`, update
`CHANGELOG.md`, then tag:

```
git tag v0.2.0
git push origin v0.2.0
```

The release workflow checks that the tag matches both files, builds the extension
zip, and publishes it.
