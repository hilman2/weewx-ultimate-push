# weewx-ultimate-push

A WeeWX driver for weather hardware that pushes its readings to a server rather than
waiting to be polled.

## Getting started

- **[Installation](Installation)** — install, point the hardware at it, start
- **[Protocols](Protocols)** — what each protocol sends, and how they are told apart
- **[Configuration](Configuration)** — every option, with worked examples
- **[Diagnostics](Diagnostics)** — one command that answers most questions
- **[Web interface](Web-interface)** — see what a station sends, and place a field without a restart

## How readings are placed

- **[Field map](Field-map)** — from raw field to database column
- **[Hardware](Hardware)** — every device, and what it takes to reach it
- **[Sensors](Sensors)** — every field this driver knows, by sensor
- **[Unknown fields](Unknown-fields)** — what happens to a field the catalog misses
- **[Stations](Stations)** — setting one up, roles, and column ownership
- **[Database columns](Database-columns)** — which columns a station needs, and how to add them

## When something is missing

- **[Reporting a new sensor](New-sensors)** — exactly what to send
- **[Troubleshooting](Troubleshooting)** — symptoms and what they mean

## Other

- **[Keeping strangers out](Security)** — path, token, addresses, TLS
- **[Development](Development)** — layout, tests, rebuilding a catalog

## Supported hardware

Six protocols:

| Protocol | Hardware |
|---|---|
| Ecowitt | GW1000, GW1100, GW1200, GW2000, GW3000, HP2551, HP2561, WS3800, WS3900, WS3910, WN1980, Froggit, Misol |
| Weather Underground | Fine Offset Observer, Ambient WS-1000, Sainlogic, any console set to *Wunderground*, Meteobridge, most weather software |
| Ambient Weather | WS-2902, WS-5000, WS-1965 and the rest of the range |
| WeatherFlow | Tempest, AIR, SKY |
| Acurite | smartHUB, Access |
| LaCrosse | LW301, LW302 |

They share one port. Which protocol sent an upload is determined from its content, and
each receives the response its own firmware expects.

Approximately 900 raw field names are mapped. On the Ecowitt side this covers the WH31,
WN34, WN35, WH40, WH41, WH43, WH45, WH46, WH51, WH52, WH55, WH57, WH65, WH68, WN20,
WN38, WS68, WS80, WS85, WS90 and LDS01; on the Ambient side the whole range, including
the AQIN air quality module and the relays; and everything the consoles report about
themselves.

## How it works

The station posts or broadcasts its readings. The driver determines which protocol was
used, converts each raw field name into a WeeWX field using that protocol's catalog,
writes the packet, and reports to WeeWX which unit each new field is in.

Fields the catalog does not cover are examined rather than dropped. A field that
continues a known series is placed automatically; a field that is merely recognisable
by name is reported. Fields whose placement the hardware does not settle — a WN34 that
might be in a raised bed or in a pool, an Acurite tower that might be anywhere — wait
until you say where they go.

With more than one station, three further rules apply: exactly one station is the main
station, a column belongs to whichever station fills it first, and a column that
already holds readings is not written into without confirmation. See
[Stations](Stations).
