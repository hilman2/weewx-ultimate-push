# weewx-ultimate-push

A WeeWX driver for weather hardware that pushes its readings to a server instead of
waiting to be asked. It listens for what a station sends, works out which protocol sent
it, and turns it into WeeWX records.

Six protocols, on one port where they will fit:

| Protocol | Hardware | How it arrives |
|---|---|---|
| Ecowitt | GW1000/1100/1200/2000/3000, HP2551, HP2561, WS3800/3900/3910, WN1980, and the Froggit and Misol rebadges | POST, any path you choose |
| Weather Underground | Fine Offset Observer, Ambient WS-1000, Sainlogic, Misol, any console set to protocol *Wunderground*, Meteobridge, most weather software | GET, `/weatherstation/updateweatherstation.php` |
| Ambient Weather | WS-2902, WS-5000, WS-1965 and the rest of the range with *Custom* upload in awnet | POST or GET, any path |
| WeatherFlow | Tempest, and the AIR and SKY before it | UDP broadcast on 50222 |
| Acurite | smartHUB and Access, with a 5-in-1, towers, Pro sensors, the 899 gauge | POST, needs a DNS entry |
| LaCrosse | LW301 and LW302 gateways | POST, needs a DNS entry |

Each is answered the way its own firmware expects. An Ecowitt gateway gets its JSON, a
Weather Underground client gets `success`, an Acurite bridge gets Chaney's own reply,
all on the same port in the same second. Hardware that does not read the answer it
wants counts the upload as failed, retries, and eventually stops.

## Why another one

Because the field lists are the hard part, and they keep changing.

New sensors ship faster than drivers get updated, and the usual outcome is that the
readings arrive and are thrown away. A current HP2561AE Pro sends 45 fields.
`weewx-interceptor` maps 25 of them and logs `unrecognized parameter` for the other 20,
including the lightning sensor, both soil probes and the whole WH52.

The same thing happens between protocols, and there it is quieter. A Weather Underground
station read with an Ecowitt catalog does not fail. `tempf` and `humidity` arrive, and
`baromin`, `rainin`, `indoortempf`, `indoorhumidity` and `UV` are dropped, because those
names are not in that catalog. The station records no pressure, no indoor readings and
no UV, and nothing anywhere says so.

So this driver keeps a catalog per protocol, decides which one an upload belongs to from
what is in it, and says out loud what it could not place. On top of that:

- **New fields are not silently dropped.** A field that continues a series the catalog
  already describes is taken, so a channel the hardware gains needs no release. A field
  that is merely recognisable by its name is reported with what it looks like, and left
  out until somebody decides.
- **The socket is not ours.** It comes from `weewx.listener`, so threads, shutdown,
  body limits, IPv6 and token checking are the core's problem and not another private
  copy of the same 200 lines.

## Install

    weectl extension install https://github.com/hilman2/weewx-ultimate-push/releases/latest/download/weewx-ultimate-push-0.8.0.zip
    sudo systemctl restart weewx

That is the whole of it. The installer sets the station type, the driver section and the
web interface, and the log then says where the interface is.

Then point the hardware at it. For an Ecowitt console, in the WSView app: *Weather
Services*, then *Customized*, protocol *Ecowitt*, server the address of the machine
running WeeWX, path and port as configured below. Every other protocol is in
[Installation](docs/Installation.md).

## Configure

```ini
[UltimatePush]
    driver = user.ultimatepush.driver
    port = 8000

    # Which protocols to listen for. 'auto' is every one that posts, and costs
    # nothing: an upload is recognised by what is in it, not by which port it came
    # to. Name them to add WeatherFlow, which needs a second socket.
    protocols = auto

    # Accept this path only. Most hardware cannot send a token any other way, so a
    # path nobody can guess is the practical way to keep strangers out. Leave it out
    # if you have Weather Underground hardware: its path is fixed in the firmware.
    path = /change-me/report

    # What to do with a field the driver does not know yet.
    infer_unknown = series

    [[field_map_extensions]]
        # Your own mapping wins over the built-in one.
        yearlyrainin = rain_year
```

`port`, `address`, `path`, `token`, `allowed_hosts`, `trust_proxy`, `max_body` and
`log_raw` are passed to the listener. They are documented in the WeeWX customization
guide, under *Porting to new hardware*.

### Rain

None of this hardware sends the rain since the last upload. It sends running counters,
and `StdWXCalculate`'s `Delta` is what turns one into a reading. The installer sets it
up for `dayRain`, which is what four of the six protocols send:

```ini
[StdWXCalculate]
    [[Delta]]
        [[[rain]]]
            input = dayRain
```

WeatherFlow needs none of that: a hub already sends the millimetres since its last
report. A LaCrosse LW30x has no daily counter and needs `input = totalRain`. The driver
says so in the log at startup when the setting does not suit the protocols you enabled,
because the alternative is finding out after a wet month.

### infer_unknown

| Value | What happens to a field the catalog does not cover |
|---|---|
| `off` | Dropped, the way other drivers do it. Still logged. |
| `series` | Taken when it continues a known series **and** the family's placement is not in question. Anything else is reported and left out. This is the default. |
| `all` | Taken whenever the name says what it measures, e.g. `mph` is a wind speed. |

`series` is the default because a derived field is not a guess. But being sure where a
channel *belongs* is not the same as being sure the field is *free*. A new WN34 channel
would land on `extraTemp`, where a sensor you set up two years ago may already have its
history, and two series in one column cannot be told apart afterwards. So a channel from
a family whose placement is a convention waits for you, with the line to paste:

    INFO user.ultimatepush.mapping: New channel 'temp9f' would go to 'extraTemp9'.
        Which sensor that is, and whether that field is free, only you know. Add
        'temp9f = extraTemp9' under [[field_map_extensions]] to accept it.

Families with nowhere else to be, such as a laser rangefinder's depth or a lightning
count, are taken without asking. `all` will get you everything sooner, at the risk of a
unit nobody checked.

Whatever the setting, the log says what turned up:

    INFO user.ultimatepush.mapping: New field 'leafwetness_ch5' -> 'leafWet5'
        (group_percent), continues leafwetness_ch, e.g. leafWet1

A field only reaches the database if the archive table has a column for it. Fields
outside the standard schema need `weectl database add-column` first.

## The web interface

On a port of its own, already switched on, with a token made at install time that is
different on every machine. The driver prints the whole address when it starts:

```
INFO user.ultimatepush.driver: The web interface is at
http://192.168.1.50:8080/?token=kJ7mQx2vRt9w
```

Open it and it shows what is still in the way of a station that records properly. If
nothing is uploading yet, name the station and pick your make: for hardware whose upload
path is yours to choose it makes one and shows exactly what to type into its app. Then
it waits and notices the first upload by itself.

A second station is where the interface earns its keep. Both send `outTemp`, and there
is one `outTemp`. It says which columns they would share, and one click makes the second
one an extra sensor: its temperature and humidity move to `extraTempN`, and what has
nowhere to go is dropped rather than written over the first station's. See
[Stations](docs/Stations.md).

After that it shows what each station sends, keeps the last twenty raw uploads, and lets
you place a field without editing a file or restarting anything.

The reason it exists: placing a field is irreversible if you get it wrong, and the one
thing you want to know first, whether that column already holds another sensor’s
readings, is the one thing a log line cannot tell you. The page shows it, per field,
next to the value that just arrived.

An address that gets the token wrong ten times in five minutes stops being answered at
all. It is plain HTTP, which on your own network is the usual trade; across the internet
put TLS in front. `enable = false` closes the port. See
[Web interface](docs/Web-interface.md).

## Documentation

| | |
|---|---|
| [Installation](docs/Installation.md) | install, point the hardware at it, start |
| [Protocols](docs/Protocols.md) | what each one sends, and how they are told apart |
| [Web interface](docs/Web-interface.md) | see what a station sends, and place a field without a restart |
| [Configuration](docs/Configuration.md) | every option, with worked examples |
| [Field map](docs/Field-map.md) | how a reading gets to a column |
| [Hardware](docs/Hardware.md) | every device, and what it takes to reach it |
| [Sensors](docs/Sensors.md) | every field this driver knows, by sensor |
| [Unknown fields](docs/Unknown-fields.md) | what happens to a field the catalog misses |
| [Stations](docs/Stations.md) | setting one up, and which station may fill which field |
| [Database columns](docs/Database-columns.md) | which columns a station needs |
| [Diagnostics](docs/Diagnostics.md) | one command that answers most questions |
| [Reporting a new sensor](docs/New-sensors.md) | exactly what to send |
| [Troubleshooting](docs/Troubleshooting.md) | symptoms and what they mean |
| [Keeping strangers out](docs/Security.md) | path, token, addresses, TLS |
| [Development](docs/Development.md) | layout, tests, rebuilding a catalog |

## Where the fields come from

Two of the catalogs are generated, because their hardware keeps gaining sensors and a
generated catalog makes the next addition a diff somebody can check:

- `tools/import_catalog.py` reads the Ecowitt names out of the `ecowittcustom` driver by
  [Werner Krenn](https://github.com/WernerKr/Ecowitt-or-DAVIS-stations-and-Season-skin).
- `tools/import_ambient.py` reads the Ambient names out of the `ambient_station`
  integration in Home Assistant, which is maintained against real hardware.

The rest are written out, because their protocols are finished. Weather Underground's
was published once and then withdrawn, and the copy this one was derived from is in
`tests/fixtures/wunderground/spec.txt`, where a test checks the catalog against it.
WeatherFlow's UDP reference is current and public. The Acurite and LaCrosse names come
from frames captured off real hardware.

What a field *is* comes from the hardware and is not negotiable. Where it *goes* is
decided in the tools and the catalogs, in lists that are meant to be read:

- `CHANNELS`, how far each sensor family reaches, from the maker's compatibility table.
- `REMAP`, families placed differently from upstream, with the reason next to them.
  The WN34 and the WH52 are there.
- `OVERRIDES`, single fields, likewise with the reason.

The generators report what they could not settle: fields written by more than one
reading, readings upstream sends to more than one field, and raw names with no target at
all. None of that is allowed to pass quietly.

## Tests

    pip install pytest
    python -m pytest tests -q

The transport, the catalogs, the protocols and the inference need nothing but Python.
That is deliberate: the tests run from captured payloads, so a change that would have
dropped a field fails a test rather than turning up in somebody's database a month
later. Captured payloads live in `tests/fixtures`, with whatever named the station
removed.

## Credit and licence

GPLv3, like everything it descends from.

- The Ecowitt catalog comes from `ecowittcustom` by Werner Krenn.
- That driver descends from `weewx-interceptor` by Matthew Wall, which is where the
  approach of listening for the upload comes from in the first place, and where the
  Acurite, LaCrosse and Fine Offset names and captured frames come from.
- The Ambient names come from the `ambient_station` integration in Home Assistant,
  which is Apache-2.0.
- WeeWX is by Tom Keffer and Matthew Wall.
