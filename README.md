# weewx-ultimate-push

A WeeWX driver for more than one weather station at once.

Stations that push their readings instead of waiting to be polled: Ecowitt, Weather
Underground, Ambient Weather, WeatherFlow, Acurite and LaCrosse, all on one port. It
reads what your hardware actually sends, and it comes with a web interface that shows
every reading and where it is being written.

And the drivers WeeWX ships with. A Vantage on a serial port and an Ecowitt gateway on
the network are one station in one database, rather than two WeeWX instances.

And hardware that does neither. A PurpleAir has nowhere to type a server address into,
so it is asked instead. A cheap 433 MHz thermometer cannot be asked or pointed either,
so an RTL-SDR stick listens for it. Four ways in, one database, one set of reports.

![The checklist, with what is still outstanding](docs/img/01-setup.png)

The interface opens on whatever still stands between the current state and a station that
records properly. It runs on a port of its own, is switched on by the installer, and the
driver logs its address when WeeWX starts:

```
INFO user.ultimatepush.driver: The web interface is at
http://1.2.3.4:8080/?token=abcdefg12345
```

## Setting a station up

![Choosing the hardware, the first of the two steps](docs/img/04-add-station.png)

Enter a name and select the hardware. For hardware whose upload path is yours to choose,
the driver generates one and shows the settings to type into the app that configures the
console. The page notices the first upload without being reloaded.

The first station is the main station. Every station after it is offered as an extra
sensor on a free channel, which is what a second console beside an existing one usually
is.

## Every reading, and where it goes

![Every station's readings on one page](docs/img/03-fields.png)

What each station sends, and which database column each reading is written to. Placing a
field takes effect on the next upload, with no restart and no editing of files.

Each row states what its column costs: `column ready`, `no column` with a button that
creates it, `column holds 240 earlier values`, or the station that already fills it. The
selector offers the fields that measure the same thing first, then everything else, then
`nowhere`, then a field of your own.

## Your stations

![The station list and one station's readings](docs/img/02-stations.png)

Every station the driver knows, including those set up but never heard from. Each entry
carries the console settings for that station and the archive columns it fills, and its
name, role and channel can be changed there.

## Before anything irreversible

![Confirming a change that reaches the archive](docs/img/05-confirm.png)

Two changes reach the archive rather than only the settings file: taking the main station
away from another station, and writing into a column that already holds readings. Both
are stated in full, with the row counts and dates out of the archive table, and both are
confirmed twice.

## Database columns

![Which readings have no column yet](docs/img/06-columns.png)

Which readings have nowhere to be written, with the `weectl` commands for exactly the
columns this station needs, and what the archive table already holds.

An address that presents the wrong token ten times in five minutes stops receiving
answers. The interface is plain HTTP; on a private network this is the usual trade, and
across the internet it should be placed behind TLS. Setting `enable = false` closes the
port. See [Web interface](https://github.com/hilman2/weewx-ultimate-push/wiki/Web-interface).

## Will it read your hardware

| Protocol | Hardware | How it arrives |
|---|---|---|
| Ecowitt | GW1000/1100/1200/2000/3000, HP2551, HP2561, WS3800/3900/3910, WN1980, and the Froggit and Misol rebadges | POST, to a path of your choosing |
| Ecowitt gateway API | the same hardware as the row above | asked on TCP 45000, on a schedule, with nothing set on the console |
| Weather Underground | Fine Offset Observer, Ambient WS-1000, Sainlogic, Misol, any console set to protocol *Wunderground*, Meteobridge, most weather software | GET, `/weatherstation/updateweatherstation.php` |
| Ambient Weather | WS-2902, WS-5000, WS-1965, and the rest of the range with *Custom* upload in awnet | POST or GET, to a path of your choosing |
| WeatherFlow | Tempest, and the AIR and SKY before it | UDP broadcast on port 50222 |
| Acurite | smartHUB and Access, with a 5-in-1, towers, Pro sensors, the 899 gauge | POST, requires a DNS entry |
| LaCrosse | LW301 and LW302 gateways | POST, requires a DNS entry |
| PurpleAir | PA-II, PA-II-SD and PA-I | asked over HTTP, on a schedule |
| Davis AirLink | AirLink | asked over HTTP, on a schedule |
| rtl_433 | any 433, 868 or 915 MHz sensor it decodes | UDP from rtl_433, which does the radio |
| Ambient Weather (ambientweather.net) | the same hardware as the row above, and the models with no *Custom* upload | asked over their REST API, on a schedule, with nothing set on the console |
| Home Assistant | any sensor Home Assistant can read, which is very nearly all of them | asked over its REST API, on a schedule |

Every device by name, with what it takes to reach each one, is in
[Hardware](https://github.com/hilman2/weewx-ultimate-push/wiki/Hardware).

Each protocol receives the answer its firmware expects, because hardware that does not
get one treats the upload as failed, retries, and eventually stops uploading.

## Hardware that has to be asked

WeeWX runs one driver, so a Vantage and an Ecowitt gateway normally mean two WeeWX
instances, two databases and two sets of reports for one weather station.

This driver hosts the other driver instead. Name its section under `[[hardware]]`, or
pick it in the web interface, and it runs on a thread of its own with its readings in
the same stream as the uploads. Every driver WeeWX ships works, and so does anything
installed as an extension.

```ini
[UltimatePush]
    [[hardware]]
        station_types = Vantage
        [[[Vantage]]]
            role = main
```

Its own section is read by its own loader, so `weectl device` is unaffected. With
`record_generation = hardware` the archive record comes from that station's logger, and
what the other stations sent during the period is added to it.

Every driver WeeWX ships, with a page each generated from the driver as installed, so
none of them can describe a version nobody has:

| Driver | Hardware | Reached |
|---|---|---|
| [Vantage](https://github.com/hilman2/weewx-ultimate-push/wiki/Driver-Vantage) | Davis Vantage Pro, Pro2 and Vue | a cable, or the network |
| [AcuRite](https://github.com/hilman2/weewx-ultimate-push/wiki/Driver-AcuRite) | AcuRite consoles with a USB port | USB |
| [CC3000](https://github.com/hilman2/weewx-ultimate-push/wiki/Driver-CC3000) | RainWise CC3000 data logger | a cable |
| [FineOffsetUSB](https://github.com/hilman2/weewx-ultimate-push/wiki/Driver-FineOffsetUSB) | Fine Offset WH1080 and its rebadges: Ambient, Elecsa, Maplin, Watson | USB |
| [TE923](https://github.com/hilman2/weewx-ultimate-push/wiki/Driver-TE923) | Hideki TE923 and its rebadges: Meade, Irox, Mebus, Honeywell | USB |
| [Ultimeter](https://github.com/hilman2/weewx-ultimate-push/wiki/Driver-Ultimeter) | Peet Bros Ultimeter, except the Ultimeter II | a cable |
| [WMR100](https://github.com/hilman2/weewx-ultimate-push/wiki/Driver-WMR100) | Oregon Scientific WMR100 and WMR200 | USB |
| [WMR300](https://github.com/hilman2/weewx-ultimate-push/wiki/Driver-WMR300) | Oregon Scientific WMR300 | USB |
| [WMR9x8](https://github.com/hilman2/weewx-ultimate-push/wiki/Driver-WMR9x8) | Oregon Scientific WM-918, WMR9x8 and WMR-968 | a cable |
| [WS1](https://github.com/hilman2/weewx-ultimate-push/wiki/Driver-WS1) | ADS WS1 | a cable, or the network |
| [WS23xx](https://github.com/hilman2/weewx-ultimate-push/wiki/Driver-WS23xx) | La Crosse WS-23xx | a cable |
| [WS28xx](https://github.com/hilman2/weewx-ultimate-push/wiki/Driver-WS28xx) | La Crosse WS-28xx | a USB transceiver |
| [Simulator](https://github.com/hilman2/weewx-ultimate-push/wiki/Driver-Simulator) | none, it makes its readings up | nothing |

Anything installed as an extension works the same way and gets a page of its own when
the pages are generated on that machine. These are tested against this driver at
stated commits:

| Extension | What it reads |
|---|---|
| [MQTTSubscribe](https://github.com/bellrichm/WeeWX-MQTTSubscribe) | readings republished over MQTT |
| [weewx-sdr](https://github.com/matthewwall/weewx-sdr) | rtl_433's output, as a subprocess |
| [weewx-rtldavis](https://github.com/lheijst/weewx-rtldavis) | a Davis over an RTL-SDR stick |
| [weatherflow-udp](https://github.com/captain-coredump/weatherflow-udp) | a WeatherFlow hub's broadcasts |
| [weewx-ws6in1](https://github.com/BobAtchley/weewx-ws6in1) | a 6-in-1 console over USB |
| [weewx-klimalogg](https://github.com/matthewwall/weewx-klimalogg) | a TFA KlimaLogg Pro over USB |
| [weewx-wxt5x0](https://github.com/matthewwall/weewx-wxt5x0) | a Vaisala WXT5x0 on a cable |

See [Hosted hardware](https://github.com/hilman2/weewx-ultimate-push/wiki/Hosted-hardware).

## Hardware that answers rather than sends

Some hardware has no field for a server address, because it was never meant to send
anything: it sits on your network and answers whoever asks. A PurpleAir is like this,
and so is most of what is sold with a local API.

One block says what to ask, how often, and what station it is. There is no second
block naming it and nothing waiting to be let in: the driver knows which sensor
answered because it knows which address it asked.

```ini
[UltimatePush]
    [[polling]]
        [[[air]]]
            address = 1.2.3.4
            protocol = purpleair
            interval = 60
            role = extra
            channel = 3
```

| `purpleair` | PurpleAir PA-II, PA-II-SD, PA-I |
|---|---|
| `airlink` | Davis AirLink |
| `ecowitt_gateway` | Ecowitt GW1000, GW1100, GW1200, GW2000, GW3000, WH2650, WN1900 |
| `ambient_cloud` | any Ambient console on an ambientweather.net account |
| `homeassistant` | anything Home Assistant can read |

The first two are air quality sensors, which is what tends to be sold with a local
API and no way to point it anywhere. The third is a weather station that can be
pointed and does not have to be: an Ecowitt gateway answers its own protocol on port
45000 whether or not its *Customized* upload is on, so both can run and nothing has
to be set on the console to use this one.

The fourth is the same trick as the third, from the other side. An Ambient
console offers one *Custom* server and older ones offer none, so a station whose
slot is taken cannot be pointed here at all. Reading it back from the account it
already uploads to needs nothing set on the console, and it is also the only way
to read a station that is not on your network.

The last is not a make of hardware at all. Home Assistant has an integration for
very nearly every sensor sold, so if it can read your thermometer, this can record
it.

No sensor yet? `python -m user.ultimatepush --fake-purpleair`, `--fake-airlink`,
`--fake-gw1000`, `--fake-ambient-cloud` and `--fake-homeassistant` answer like
one each.

The third is not hardware. Home Assistant has an integration for very nearly every
sensor that exists and publishes them all through one API with the type and the unit
attached, so this reads an Aqara room thermometer, a Zigbee soil probe, the sensor
inside a Shelly or a Tado, and whatever is sold next, without a line being added
here. One block is one Home Assistant device, so the thermometer indoors and the one
outdoors are two stations and do not fight over a column.

```ini
[UltimatePush]
    [[polling]]
        [[[garden]]]
            address = 192.168.1.10:8123
            protocol = homeassistant
            token = eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.a-very-long-token
            entities = sensor.garden_temperature, sensor.garden_humidity
            interval = 60
```

The token is a long-lived access token, made under your own profile in Home
Assistant. It grants everything your account can do, so keep it the way you would
keep the password; the driver never prints it. The web interface finds the sensors
for you and lists them grouped by device.

No sensor yet? `python -m user.ultimatepush --fake-purpleair`, `--fake-airlink` and
`--fake-homeassistant` answer like one each.

See [Sensors this driver asks](https://github.com/hilman2/weewx-ultimate-push/wiki/Polled-sources)
and [Home Assistant](https://github.com/hilman2/weewx-ultimate-push/wiki/Protocol-Homeassistant).

## Cheap radio sensors

A twenty-five euro RTL-SDR stick hears every sensor within a few hundred metres that
talks on 433, 868 or 915 MHz: outdoor thermometers, soil probes, rain gauges, pool
sensors. [rtl_433](https://github.com/merbanan/rtl_433) does the radio and the
decoding. It is a separate program and none of it ships here.

```bash
sudo apt install rtl-433
rtl_433 -C si -F syslog:127.0.0.1:1433
```

`-C si` asks it to convert what it can itself. `-F syslog:` is how it sends: one
datagram per message, so nothing has to start it or supervise it. Leave it running
with a unit of its own:

```bash
sudo tee /etc/systemd/system/rtl_433.service <<'EOF'
[Unit]
Description=rtl_433
After=network.target

[Service]
ExecStart=/usr/bin/rtl_433 -C si -F syslog:127.0.0.1:1433
Restart=always
User=nobody

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl enable --now rtl_433
```

Then switch the protocol on:

```ini
[UltimatePush]
    protocols = ecowitt, rtl433
```

Everything in range turns up, including the neighbours', because listening is not the
same as being sent to. Nothing is recorded until you say which sensors are yours. They
appear in the web interface, most often heard first, which is a good guide: something
heard sixty times an hour is close by and on a schedule, and something heard once was
a car going past. *Not mine* takes one off the list for good, and anything nothing has
been heard from for two days drops off by itself.

A battery change can give one of these sensors a new id. When that happens it stops
recording and turns up looking new; the interface moves the station onto the new id,
keeping its name, its channel and the columns it owns.

No stick yet? `python -m user.ultimatepush --fake-rtl433` sends what rtl_433 sends,
three sensors at a time, one of them a neighbour's.

See [rtl_433](https://github.com/hilman2/weewx-ultimate-push/wiki/Protocol-Rtl433).

## Why another driver

Field lists change as manufacturers add sensors, and drivers that are not updated drop
the readings they do not recognise.

A current HP2561AE Pro sends 45 fields. The `weewx-interceptor` driver maps 25 of them
and logs `unrecognized parameter` for the remaining 20, including the lightning sensor,
both soil probes, and the WH52.

The same happens between protocols, without a log entry. A Weather Underground station
read with an Ecowitt catalog does not fail: `tempf` and `humidity` arrive, while
`baromin`, `rainin`, `indoortempf`, `indoorhumidity` and `UV` are dropped because those
names are not in that catalog. The station records no pressure, no indoor readings and
no UV, and nothing reports it.

This driver keeps a catalog for each protocol, works out from the payload which catalog
applies, and reports what it could not place. A field that continues a series the catalog
already describes is accepted, so a channel added to existing hardware does not require a
driver release. A field that is merely recognisable by name is reported and left
unwritten until you decide where it belongs.

## Installation

Install the extension and restart WeeWX:

```
weectl extension install https://github.com/hilman2/weewx-ultimate-push/releases/latest/download/weewx-ultimate-push.zip
sudo systemctl restart weewx
```

The installer sets the station type, the driver section, and the web interface, with a
token generated on this machine. The log then reports the address of the web interface.

Next, point the hardware at the machine running WeeWX. For an Ecowitt console, use the
WSView Plus app: *Device List*, your console, *Weather Services*, then page through to
*Customized*. Set protocol type to *Ecowitt*, the server to the address of the machine,
and the path and port to match your configuration. The other protocols are described in
[Installation](https://github.com/hilman2/weewx-ultimate-push/wiki/Installation).

## Configuration

All settings are in one section of `weewx.conf`.

```ini
[UltimatePush]
    driver = user.ultimatepush.driver
    port = 8000
    protocols = auto
    path = /change-me/report
    infer_unknown = series

    [[field_map_extensions]]
        yearlyrainin = rain_year
```

### The four you are likely to touch

**`protocols`** decides which protocols to listen for. Leaving it at `auto` costs
nothing, because an upload is recognised by its content rather than by the port it
arrived on. Name them to add WeatherFlow, which needs a socket of its own, or to settle
hardware that says nothing about itself.

**`path`** narrows the driver to one upload path. A path nobody can guess is the only
secret most consoles can carry, so this is the main defence for a port reachable from
outside. Weather Underground, Acurite and LaCrosse hardware cannot be given one.

**`infer_unknown`** decides what happens to a field no catalog covers. See below.

**`field_map_extensions`** places a reading by hand, ahead of everything else. This is
where a sensor goes whose position only you know: a WN34 is a spike in a raised bed or a
lead in a pool, and nothing in the upload says which.

Every option, including the ones `weewx.listener` contributes, is described with its
default in [Configuration](https://github.com/hilman2/weewx-ultimate-push/wiki/Configuration).

## Rain

None of this hardware reports the rain since the last upload. It reports running
counters, which `StdWXCalculate` has to difference. The installer configures that for
`dayRain`, which suits four of the six protocols; WeatherFlow needs none of it and
LaCrosse needs `totalRain`. The driver logs a warning at startup when the setting does
not suit the protocols you enabled. See [Installation](https://github.com/hilman2/weewx-ultimate-push/wiki/Installation#rain).

## Fields the catalog does not cover

Manufacturers add sensors between driver releases. A field that continues a series the
catalog already describes is taken without one: if `leafwetness_ch1` to `ch4` are known,
`leafwetness_ch5` follows from them.

```
INFO user.ultimatepush.mapping: New field 'leafwetness_ch5' -> 'leafWet5'
    (group_percent), continues leafwetness_ch, e.g. leafWet1
```

A field that is merely recognisable by name is reported rather than taken, and so is a
channel whose placement is a convention rather than a reading. Both are decisions that
cannot be undone once two sensors share a column. See
[Unknown fields](https://github.com/hilman2/weewx-ultimate-push/wiki/Unknown-fields).

A field only reaches the database if the archive table has a column for it. Fields
outside the standard schema need one added, which is a button in the web interface or
`weectl database add-column` from a terminal. See
[Database columns](https://github.com/hilman2/weewx-ultimate-push/wiki/Database-columns).

## Several stations

One station requires none of this. Every reading is written where it belongs.

A second station raises a question that cannot be avoided: both send `outTemp`, and
there is one `outTemp` column. Left alone, the two would write it in turn every few
seconds, producing a column that holds a mixture nothing can separate afterwards.

The driver applies three rules.

**Exactly one station is the main station.** Its readings are written where they belong.
Every station set up after it becomes an extra sensor, whose temperature and humidity go
to `extraTempN` and `extraHumidN`.

**A column belongs to whichever station fills it first.** A reading for that column from
any other station is dropped rather than written over it.

**A column that already holds readings is not written into without confirmation.** The
driver reads the archive table and reports what is there. Continuing a series is correct
when it is the same weather station in the same place, and mixes two sensors when it is
not. Only you can tell which.

Which console holds which column, how a station is moved aside, and what that costs are
in [Stations](https://github.com/hilman2/weewx-ultimate-push/wiki/Stations).

## Documentation

The [wiki](https://github.com/hilman2/weewx-ultimate-push/wiki) is in three parts.

**Using it**, for running a station.

| | |
|---|---|
| [Installation](https://github.com/hilman2/weewx-ultimate-push/wiki/Installation) | install, point the hardware at it, start |
| [Hardware](https://github.com/hilman2/weewx-ultimate-push/wiki/Hardware) | every device, and what it takes to reach it |
| [Web interface](https://github.com/hilman2/weewx-ultimate-push/wiki/Web-interface) | see what a station sends, and place a field without a restart |
| [Stations](https://github.com/hilman2/weewx-ultimate-push/wiki/Stations) | setting one up, roles, and column ownership |
| [Database columns](https://github.com/hilman2/weewx-ultimate-push/wiki/Database-columns) | which columns a station needs |
| [Configuration](https://github.com/hilman2/weewx-ultimate-push/wiki/Configuration) | every option, with worked examples |
| [Diagnostics](https://github.com/hilman2/weewx-ultimate-push/wiki/Diagnostics) | one command that answers most questions |
| [Troubleshooting](https://github.com/hilman2/weewx-ultimate-push/wiki/Troubleshooting) | symptoms and what they mean |
| [Keeping strangers out](https://github.com/hilman2/weewx-ultimate-push/wiki/Security) | path, token, addresses, TLS |
| [Reporting a new sensor](https://github.com/hilman2/weewx-ultimate-push/wiki/New-sensors) | exactly what to send |

**How it works**, for the machine behind it.

| | |
|---|---|
| [Protocols](https://github.com/hilman2/weewx-ultimate-push/wiki/Protocols) | what each protocol sends, and how they are told apart |
| [Field map](https://github.com/hilman2/weewx-ultimate-push/wiki/Field-map) | how a reading reaches a column |
| [Sensors](https://github.com/hilman2/weewx-ultimate-push/wiki/Sensors) | every field this driver knows, by sensor |
| [Unknown fields](https://github.com/hilman2/weewx-ultimate-push/wiki/Unknown-fields) | what happens to a field the catalog misses |
| [Catalogs](https://github.com/hilman2/weewx-ultimate-push/wiki/Catalogs) | where the field names come from, and who decided their places |
| [Architecture](https://github.com/hilman2/weewx-ultimate-push/wiki/Architecture) | the modules, and why they are cut this way |

**Development**, for changing it.

| | |
|---|---|
| [Contributing](https://github.com/hilman2/weewx-ultimate-push/wiki/Contributing) | what helps, and what a pull request needs |
| [Conventions](https://github.com/hilman2/weewx-ultimate-push/wiki/Conventions) | formatting, types, comments, documentation, commits |
| [Development](https://github.com/hilman2/weewx-ultimate-push/wiki/Development) | the source, the tests, the tools, releasing |

## Credits and licence

GPLv3.

- The Ecowitt catalog comes from `ecowittcustom` by Werner Krenn.
- That driver descends from `weewx-interceptor` by Matthew Wall, which is the origin of
  the approach of listening for the upload, and of the Acurite, LaCrosse and Fine Offset
  names and captured frames.
- The Ambient names come from the `ambient_station` integration in Home Assistant, which
  is Apache-2.0.
- WeeWX is by Tom Keffer and Matthew Wall.
