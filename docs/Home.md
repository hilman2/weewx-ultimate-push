# weewx-ultimate-push

A WeeWX driver for more than one weather station at once.

It started with hardware that pushes its readings instead of waiting to be polled. Six
protocols share one port, an upload is recognised by what is in it, and roughly 900 raw
field names are mapped.

It also runs the drivers WeeWX ships with. A Vantage on a serial port and an Ecowitt
gateway on the network are one station in one database, rather than two WeeWX
instances.

New here? [Installation](Installation.md) is twenty lines and ends with a working
station.

The wiki is in three parts. **Using it** is for running a station. **How it works** is
for understanding the machine behind it. **Development** is for changing it.

## Using it

- **[Installation](Installation.md)** — install, point the hardware at it, start
- **[Hardware](Hardware.md)** — every device that uploads, and what it takes to reach it
- **[Web interface](Web-interface.md)** — see what a station sends, and place a field without a restart
- **[Stations](Stations.md)** — setting one up, roles, and column ownership
- **[Several stations](Several-stations.md)** — growing the file, and saying which reading comes from which station
- **[Hosted hardware](Hosted-hardware.md)** — a Vantage or a USB console beside the stations that upload
- **[Sensors this driver asks](Polled-sources.md)** — a PurpleAir and anything else with a local API
- **[Database columns](Database-columns.md)** — which columns a station needs, and how to add them
- **[Configuration](Configuration.md)** — every option, with worked examples
- **[Diagnostics](Diagnostics.md)** — one command that answers most questions
- **[Troubleshooting](Troubleshooting.md)** — symptoms and what they mean
- **[Keeping strangers out](Security.md)** — path, token, addresses, TLS
- **[Reporting a new sensor](New-sensors.md)** — exactly what to send

## One page per protocol

Setting each kind up by hand, with everything that is only its own.

- **[Acurite](Protocol-Acurite.md)**
- **[Ambient](Protocol-Ambient.md)**
- **[Ecowitt](Protocol-Ecowitt.md)**
- **[Lacrosse](Protocol-Lacrosse.md)**
- **[PurpleAir](Protocol-Purpleair.md)**
- **[rtl_433](Protocol-Rtl433.md)** — cheap radio sensors, with an RTL-SDR stick
- **[Weatherflow](Protocol-Weatherflow.md)**
- **[Wunderground](Protocol-Wunderground.md)**

## One page per driver this machine can read

Generated from the drivers installed here, so they cannot describe a version nobody has.

- **[AcuRite](Driver-AcuRite.md)**
- **[CC3000](Driver-CC3000.md)**
- **[FineOffsetUSB](Driver-FineOffsetUSB.md)**
- **[Simulator](Driver-Simulator.md)**
- **[TE923](Driver-TE923.md)**
- **[Ultimeter](Driver-Ultimeter.md)**
- **[Vantage](Driver-Vantage.md)**
- **[WMR100](Driver-WMR100.md)**
- **[WMR300](Driver-WMR300.md)**
- **[WMR9x8](Driver-WMR9x8.md)**
- **[WS1](Driver-WS1.md)**
- **[WS23xx](Driver-WS23xx.md)**
- **[WS28xx](Driver-WS28xx.md)**

## How it works

- **[Protocols](Protocols.md)** — what each protocol sends, and how they are told apart
- **[Field map](Field-map.md)** — from raw field to database column
- **[Ecowitt sensors](Ecowitt-sensors.md)** — every raw field the Ecowitt catalog knows, by sensor
- **[Unknown fields](Unknown-fields.md)** — what happens to a field the catalog misses
- **[Catalogs](Catalogs.md)** — where the field names come from, and who decided their places
- **[Architecture](Architecture.md)** — the modules, and why they are cut this way

## Development

- **[Contributing](Contributing.md)** — what helps, and what a pull request needs
- **[Conventions](Conventions.md)** — formatting, types, comments, documentation, commits
- **[Development](Development.md)** — the source, the tests, the tools, releasing

## Which page answers which question

| | |
|---|---|
| Will it read my hardware? | [Hardware](Hardware.md) for hardware that uploads, [Hosted hardware](Hosted-hardware.md) for hardware on a cable |
| How do I set up my particular hardware? | its own page, under the two lists below |
| Nothing arrives | [Troubleshooting](Troubleshooting.md) |
| A sensor is missing from my reports | [Troubleshooting](Troubleshooting.md), then [Field map](Field-map.md) |
| A reading is out by a factor | [Troubleshooting](Troubleshooting.md) |
| Where does `tf_ch1` go? | [Field map](Field-map.md), and [Ecowitt sensors](Ecowitt-sensors.md) for the full list |
| The driver says it cannot place a field | [Unknown fields](Unknown-fields.md), then [Reporting a new sensor](New-sensors.md) |
| I have a second console | [Several stations](Several-stations.md) |
| I have an air quality sensor | [Sensors this driver asks](Polled-sources.md) |
| I have cheap 433 MHz sensors | [rtl_433](Protocol-Rtl433.md) |
| My station is on a cable, not the network | [Hosted hardware](Hosted-hardware.md) |
| A reading vanishes at the archive interval | [Database columns](Database-columns.md) |
| This port is on the internet | [Keeping strangers out](Security.md) |
