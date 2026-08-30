# Contributing

The three that help most, in order:

1. **A payload from hardware nobody here has.** Every catalog was built from captured
   uploads, and the ones that are thin are thin because nothing was captured. See
   [Reporting a new sensor](New-sensors.md).
2. **A problem, reported with what the driver printed.** See
   [Troubleshooting](Troubleshooting.md#reporting-a-problem).
3. **A pull request.** Everything below is about those.

Before writing one, read [Conventions](Conventions.md). It is what CI checks, and it is
short.

## What a pull request needs

- a test that fails without the change
- `python -m pytest tests -q` passing
- `black bin tools tests install.py` run
- `mypy` and the docstring checker passing
- an entry in `CHANGELOG.md` for anything a user would notice, in the same voice as
  the ones above it. Documentation and formatting do not get one.

## Adding a field

1. Add the raw name to the catalog. Through the generator where there is one, not by
   hand. See [Catalogs](Catalogs.md).
2. Give it a unit group if WeeWX does not know the field.
3. If it belongs to a sensor family the driver does not know, add the family to
   `CHANNELS` with its channel count.
4. If another protocol already sends the same reading, send it to the same WeeWX field.
   A test compares the catalogs and will say so if you do not.
5. Add a captured payload to `tests/fixtures` and a test that says what should come out
   of it.

## Adding a protocol

`bin/user/ultimatepush/protocols/` has six worked examples. A new one is a class and a
catalog:

```python
class MyProtocol(Protocol):
    name = 'mine'
    label = 'My Weather Thing'
    hardware = 'the boxes this is for'

    answer = 'ok'                 # what its firmware waits for
    content_type = 'text/plain'
    identity = ('serial',)        # which field names the station
    units = US
    rain_counter = 'dayRain'      # what StdWXCalculate differences, or None

    fields = _catalog.FIELDS
    groups = _catalog.GROUPS

    @classmethod
    def claims(cls, request, raw):
        return 5 if 'something_only_mine_sends' in raw else 0
```

Then add it to `registry()`, add a captured payload to `tests/fixtures`, and write a test
that says what should come out of it.

`claims` returns how sure the protocol is, and the surest wins. Keep the numbers honest:
5 or 6 for something only this protocol sends, 2 or 3 for something it merely cannot rule
out. A protocol that overstates itself takes uploads from one that would have read them
properly.

If the payload is not name and value pairs, override `readings`. WeatherFlow unpacks JSON
arrays there; Acurite and LaCrosse rename theirs to keep two sensors apart.

## Changing the web interface

`page.py` is the whole interface: one self-contained page, no build step, no bundler, no
dependency to install. Keep it that way. `admin.py` beside it is the routing and the JSON
API, and that is where a new tab's data comes from.
