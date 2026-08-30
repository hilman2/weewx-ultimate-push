# weewx-ultimate-push

A WeeWX driver for weather hardware that pushes its readings to a server rather than
waiting to be polled. Six protocols share one port, an upload is recognised by what is
in it, and roughly 900 raw field names are mapped.

New here? [Installation](Installation.md) is twenty lines and ends with a working
station.

The wiki is in three parts. **Using it** is for running a station. **How it works** is
for understanding the machine behind it. **Development** is for changing it.

## Using it

- **[Installation](Installation.md)** — install, point the hardware at it, start
- **[Hardware](Hardware.md)** — every device, and what it takes to reach it
- **[Web interface](Web-interface.md)** — see what a station sends, and place a field without a restart
- **[Stations](Stations.md)** — setting one up, roles, and column ownership
- **[Hosted hardware](Hosted-hardware.md)** — a Vantage or a USB console beside the stations that upload
- **[Database columns](Database-columns.md)** — which columns a station needs, and how to add them
- **[Configuration](Configuration.md)** — every option, with worked examples
- **[Diagnostics](Diagnostics.md)** — one command that answers most questions
- **[Troubleshooting](Troubleshooting.md)** — symptoms and what they mean
- **[Keeping strangers out](Security.md)** — path, token, addresses, TLS
- **[Reporting a new sensor](New-sensors.md)** — exactly what to send

## How it works

- **[Protocols](Protocols.md)** — what each protocol sends, and how they are told apart
- **[Field map](Field-map.md)** — from raw field to database column
- **[Sensors](Sensors.md)** — every field this driver knows, by sensor
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
| Will it read my hardware? | [Hardware](Hardware.md), or [Protocols](Protocols.md) for what each protocol carries |
| Nothing arrives | [Troubleshooting](Troubleshooting.md) |
| A sensor is missing from my reports | [Troubleshooting](Troubleshooting.md), then [Field map](Field-map.md) |
| A reading is out by a factor | [Troubleshooting](Troubleshooting.md) |
| Where does `tf_ch1` go? | [Field map](Field-map.md), and [Sensors](Sensors.md) for the full list |
| The driver says it cannot place a field | [Unknown fields](Unknown-fields.md), then [Reporting a new sensor](New-sensors.md) |
| I have a second console | [Stations](Stations.md) |
| A reading vanishes at the archive interval | [Database columns](Database-columns.md) |
| This port is on the internet | [Keeping strangers out](Security.md) |
