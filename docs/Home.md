# weewx-ultimate-push

A WeeWX driver for weather hardware that pushes its readings to a server instead of
waiting to be asked.

## Getting going

- **[Installation](Installation)** — install, point the hardware at it, start
- **[Protocols](Protocols)** — what each one sends, and how they are told apart
- **[Configuration](Configuration)** — every option, with worked examples
- **[Diagnostics](Diagnostics)** — one command that answers most questions

## How readings are placed

- **[Field map](Field-map)** — from raw field to database column
- **[Hardware](Hardware)** — every device, and what it takes to reach it
- **[Sensors](Sensors)** — every field this driver knows, by sensor
- **[Unknown fields](Unknown-fields)** — what happens to a field the catalog misses
- **[Several consoles](Several-consoles)** — a second station, without the two overwriting each other
- **[Database columns](Database-columns)** — which columns a station needs, and how to add them

## When something is missing

- **[Reporting a new sensor](New-sensors)** — exactly what to send
- **[Troubleshooting](Troubleshooting)** — symptoms and what they mean

## Other

- **[Keeping strangers out](Security)** — path, token, addresses, TLS
- **[Development](Development)** — layout, tests, rebuilding a catalog

## What it supports

Six protocols:

| Protocol | Hardware |
|---|---|
| Ecowitt | GW1000, GW1100, GW1200, GW2000, GW3000, HP2551, HP2561, WS3800, WS3900, WS3910, WN1980, Froggit, Misol |
| Weather Underground | Fine Offset Observer, Ambient WS-1000, Sainlogic, any console set to *Wunderground*, Meteobridge, most weather software |
| Ambient Weather | WS-2902, WS-5000, WS-1965 and the rest of the range |
| WeatherFlow | Tempest, AIR, SKY |
| Acurite | smartHUB, Access |
| LaCrosse | LW301, LW302 |

They share one port. Which one sent an upload is worked out from what is in it, and
each is answered the way its own firmware expects.

Around 900 raw field names are mapped. On the Ecowitt side that covers the WH31, WN34,
WN35, WH40, WH41, WH43, WH45, WH46, WH51, WH52, WH55, WH57, WH65, WH68, WN20, WN38,
WS68, WS80, WS85, WS90 and LDS01; on the Ambient side the whole range including the
AQIN air quality module and the relays; and everything the consoles report about
themselves.

## In one paragraph

The station posts, or broadcasts, its readings. The driver works out which protocol
that was, turns each raw field name into a WeeWX field using that protocol's catalog,
writes the packet, and tells WeeWX what unit each new field is in. Fields the catalog
does not cover are examined rather than dropped: one that continues a known series is
worked out, one that is merely recognisable by name is reported. Fields whose placement
the hardware does not settle, such as a WN34 that might be in a bed or in a pool, or an
Acurite tower that might be anywhere, wait until you say where they go.
