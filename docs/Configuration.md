# Configuration

All settings are in one section of `weewx.conf`.

## A complete example

```ini
[Station]
    station_type = UltimatePush

[UltimatePush]
    driver = user.ultimatepush.driver

    # Where to listen.
    address = 0.0.0.0
    port = 8000

    # Which protocols to listen for. 'auto' is every one that posts.
    protocols = auto

    # Accept this path only. Anything else receives a 404.
    path = /a8f3c1e0/report

    # What to do with a field the driver does not know yet.
    infer_unknown = series

    # How the station is named in reports.
    model = HP2561AE Pro

    [[field_map_extensions]]
        # Fields the driver will not place on its own.
        tf_ch1 = soilTemp5          # WN34S, spike in the raised bed
        tf_ch2 = extraTemp10        # WN34L, silicone lead in the pool
        tf_batt1 = wn34_ch1_batt
        tf_batt2 = wn34_ch2_batt
        soil_ec_temp1 = soilTemp1   # WH52, 10 cm deep
        lightning_time = lightning_time
```

## Listener options

These are passed to `weewx.listener` and behave the same for every driver that uses it.
With WeatherFlow enabled, `address`, `allowed_hosts`, `max_body`, `queue_size` and
`log_raw` apply to the UDP socket as well; the rest are HTTP only.

#### port

The port to listen on. Ports below 1024 require root. Default is `80`.

#### address

The address to bind to. Use `localhost` when running behind a reverse proxy. Default is
every interface.

#### path

Accept uploads on this path only. Any other path receives a 404. Leave it unset if you
have Weather Underground, Acurite or LaCrosse hardware, whose path is fixed in the
firmware. Default is every path.

#### token

Require this token, supplied as the query parameter `token`, the header `X-Auth-Token`,
or a bearer token in `Authorization`. Most weather hardware cannot send one. Default is
none.

#### allowed_hosts

Comma-separated addresses to accept uploads from. Default is anywhere.

#### trust_proxy

Take the client address from `X-Forwarded-For`. Use only with a proxy you control.
Default is `False`.

#### max_body

The largest upload accepted, in bytes. Larger uploads receive a 413. Default is `65536`.

#### socket_timeout

How long an idle client may hold a connection, in seconds. Default is `20`.

#### queue_size

How many uploads may wait to be processed. Beyond this the oldest is dropped, with a
warning. Default is `10`.

#### log_raw

Log every upload at debug level. Turn this on when a sensor is missing. Default is
`False`.

## Driver options

#### driver

The driver module. Set to `user.ultimatepush.driver`. Required. No default.

#### protocols

Which protocols to listen for, as a comma-separated list. `auto` is every protocol that
arrives over HTTP, which costs nothing: an upload is recognised by its content rather
than by the port it arrived on. Name them explicitly to add WeatherFlow, which requires
a second socket, or to settle an upload that identifies nothing. Default is `auto`. See
[Protocols](Protocols.md).

#### model

What reports call the station. Default is `UltimatePush`.

#### infer_unknown

What happens to fields the catalog does not cover. One of `off`, `series` or `all`.
Default is `series`. See [Unknown fields](Unknown-fields.md).

#### field_map_extensions

A subsection mapping raw field names to WeeWX field names. Takes precedence over the
catalog and over the station role. Default is empty. See [Field map](Field-map.md).

#### report_file

Where to write a report when a station sends something the driver cannot place. An
empty value disables it. Default is
`/var/tmp/weewx-ultimate-push-report.txt`.

#### max_behind

How many seconds behind the computer's clock a console's own timestamp may be and still
be believed. Default is `3600`. See [The console's clock](#the-consoles-clock).

#### max_ahead

The same, for a console whose clock runs fast. Default is `60`.

#### password

Weather Underground only. Refuse uploads that do not present this as `PASSWORD`. This
is the only protocol here whose hardware can carry a secret. A station with a password
of its own uses that instead; this covers the ones that have none. Default is none. See
[Stations](Stations.md#configuring-stations-in-weewxconf).

#### metric_wind

Weather Underground metric dialect only. Whether its wind is kilometres per hour or
metres per second, which cannot be determined from a payload. One of `kph` or `mps`.
Default is `kph`. See [Protocols](Protocols.md).

#### udp_port

WeatherFlow only. The port to listen for broadcasts on. There is no reason to change
it. Default is `50222`.

#### override_file

Where the settings the web interface writes are kept. Default is beside the console
list.

## What each protocol needs

Six protocols share one port and one section. Most of the settings above apply to all
of them at once, and three belong to one protocol each. This is the whole of what
differs.

| | In `protocols = auto` | Only it has | A station is named by |
|---|---|---|---|
| Ecowitt | yes | none | its PASSKEY, or a path you choose |
| Ambient Weather | yes | none | its PASSKEY, or a path you choose |
| Weather Underground | yes | `password`, `metric_wind` | its `ID`, with a `PASSWORD` |
| WeatherFlow | **no** | `udp_port` | the hub's serial number |
| Acurite | yes | none | the bridge's MAC address |
| LaCrosse | yes | none | the gateway's MAC address |

So for four of the six there is nothing to configure beyond the port everything shares.
Point the hardware at this machine and it is read.

**WeatherFlow has to be named.** It broadcasts rather than posting, which needs a second
socket, and a socket is not opened for hardware nobody has:

```ini
[UltimatePush]
    protocols = ecowitt, weatherflow
```

**Acurite and LaCrosse need a DNS entry** rather than a setting here. Their server name
is in the firmware. See [Hardware](Hardware.md#the-two-that-need-a-dns-entry).

What each protocol sends and how they are told apart is in
[Protocols](Protocols.md). What to write for a station of each kind is in
[Stations](Stations.md#setting-up-a-station).

## The web interface

A subsection of `[UltimatePush]`, enabled by the installer. See
[Web interface](Web-interface.md) for the full list of options.

```ini
[UltimatePush]
    [[web]]
        enable = true
        port = 8080
        token = paste-a-long-random-string-here
        # address = localhost
        # allowed_hosts =
```

## Stations

A subsection naming the consoles this driver answers to, and what each one may write.
Required only when there is more than one console, or to keep a station's identity in
`weewx.conf` rather than in the database. See [Stations](Stations.md).

```ini
[UltimatePush]
    [[stations]]
        [[[garden]]]
            passkey = 3178AB6B42A759F51A5A4AD72E37F8DE
        [[[roof]]]
            passkey = 9A2B4C6D8E0F1A3B5C7D9E1F2A4B6C8D
            role = extra
            channel = 4
```

## Hosted hardware

Other WeeWX drivers, run inside this one. Each is configured in its own top-level
section, exactly as it would be on its own, and named here. See
[Hosted hardware](Hosted-hardware.md).

```ini
[UltimatePush]
    [[hardware]]
        station_types = Vantage, WMR100

        [[[Vantage]]]
            role = main

        [[[WMR100]]]
            role = extra
            channel = 3
            name = The old Oregon
```

#### station_types

Comma-separated top-level sections to run, each of which must carry its own `driver`
option. The first is the archive station: only that one is asked for archive records and
only its clock is read. Default is none, and nothing is hosted.

#### role

`main` or `extra`, in one subsection per station type. `main` writes to the plain
columns; `extra` is moved to a channel. Default is `main`.

#### channel

Which `extraTemp` and `extraHumid` column an extra station writes to, from 1 to 8.
Required when `role = extra`. Default is none.

#### name

What to call the station in the log and in the web interface. Default is the section
name.

## What the web interface does not write here

Settings made in the web interface never reach `weewx.conf`. They go to
`ultimate-push-web.conf`, beside the console list, and are read on the next upload
without a restart. Anything set in `weewx.conf` takes precedence over them, so a station
or a placement you write here stays yours. What that other file holds is in
[Web interface](Web-interface.md#where-the-settings-are-written).

## The console's clock

Every upload carries `dateutc`, the time the console read its sensors. The driver uses
it, so a reading belongs to the minute it was taken rather than the minute it arrived.

This matters when an upload is delayed by a relay, a queue, or a network outage. A
console with an internet connection keeps its clock by NTP, so a timestamp a few minutes
old means the upload was slow rather than that the clock is wrong.

The window is not symmetric. A reading can be delayed, so `max_behind` is generous. A
reading cannot arrive before it was taken, so `max_ahead` only has to cover the drift
between two clocks that are both roughly correct. Outside the window the driver reports
it and uses the time the upload arrived:

```
WARNING user.ultimatepush.transport: Device time 2015-01-01 00:00:00 is 4255 days behind
ours, past what max_behind allows. Using ours.
```

Whether a late reading then reaches the archive record it belongs to is handled by
WeeWX. WeeWX 5.5 and later keep the LOOP packets and recompute the record; see
`[StdLoopStore]` in the WeeWX reference. On older versions a packet from an interval
that has already been written cannot be added to it, so `max_behind` is better set to
something small, around `90`.

## Common setups

### On its own, on a local network

The console posts directly to WeeWX.

```ini
[UltimatePush]
    driver = user.ultimatepush.driver
    port = 8000
```

Set the console's server to the WeeWX machine's address, port 8000, path `/`.

### Behind a reverse proxy, reachable from outside

The web server keeps port 443 and passes one path through. A path nobody can guess is
the only secret most consoles can carry.

```ini
[UltimatePush]
    driver = user.ultimatepush.driver
    address = localhost
    port = 8000
    path = /a8f3c1e0/report
    trust_proxy = true
```

nginx:

```nginx
location /a8f3c1e0/report {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

Caddy:

```
weather.example.com {
    handle /a8f3c1e0/* {
        reverse_proxy 127.0.0.1:8000
    }
}
```

Set the console's server to `weather.example.com`, port 443, path `/a8f3c1e0/report`.

### Alongside a web server on the same machine

No special configuration is required as long as the ports differ. WeeWX writes its
reports to files, the web server serves them, and the driver listens on its own port.

### Two stations, one machine

WeeWX runs one driver per instance, so two stations means two instances, each with its
own configuration file, database and port. See the WeeWX wiki article *Run multiple
instances of WeeWX on one computer*.

Two consoles reporting to one instance is a different arrangement and is supported. See
[Stations](Stations.md).

### A Tempest and an Ecowitt gateway together

Two sockets, one loop. WeatherFlow is not included in `auto`, because it requires a
port of its own.

```ini
[UltimatePush]
    driver = user.ultimatepush.driver
    port = 8000
    protocols = ecowitt, weatherflow

    [[stations]]
        [[[garden]]]
            passkey = 34A1B2C3D4E5F60718293A4B5C6D7E8F
        [[[roof]]]
            passkey = HB-00013030
```

A hub is identified by its serial number, which goes in `passkey` like any other
identity.

### One protocol, named

An upload with nothing in it to say which protocol it uses is refused rather than read
with whichever catalog happened to be first. Naming one settles it:

```ini
[UltimatePush]
    protocols = wunderground
```

This is worth doing whenever the hardware is known. It removes a class of mistake and
costs nothing.

## Configuring the console

What to type into each app is in [Installation](Installation.md).

One choice is worth making deliberately. An Ecowitt console speaks Weather Underground
as well, and this driver reads both, but the Weather Underground field list is the
shorter one by far. Nothing outside it reaches WeeWX that way, which on a current
station means most of the sensors. Set the console to Ecowitt unless something prevents
it.

## Checking the configuration

```
python -m user.ultimatepush --port 8001
```

Point the console at port 8001 for one upload. See [Diagnostics](Diagnostics.md).
