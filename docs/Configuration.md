# Configuration

Everything lives in one section of `weewx.conf`.

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

    # Accept this path only. Anything else gets a 404.
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

## Options

### The listener

These are passed straight to `weewx.listener`. They behave the same for every driver
that uses it. With WeatherFlow enabled, `address`, `allowed_hosts`, `max_body`,
`queue_size` and `log_raw` apply to the UDP socket as well; the rest are HTTP only.

| Option | Default | Meaning |
|---|---|---|
| `port` | 80 | Port to listen on. Below 1024 needs root. |
| `address` | every interface | Address to bind to. Use `localhost` behind a reverse proxy. |
| `path` | every path | Accept this path only. Anything else gets a 404. |
| `token` | none | Require this token, as query parameter `token`, header `X-Auth-Token`, or a bearer token in `Authorization`. |
| `allowed_hosts` | anywhere | Comma-separated addresses to accept from. |
| `trust_proxy` | False | Take the client address from `X-Forwarded-For`. Only with a proxy you control. |
| `max_body` | 65536 | Largest upload accepted, in bytes. Bigger gets a 413. |
| `socket_timeout` | 20 | How long an idle client may hold a connection, in seconds. |
| `queue_size` | 10 | How many uploads may wait to be processed. Beyond that the oldest is dropped, with a warning. |
| `log_raw` | False | Log every upload at debug level. Turn this on when a sensor is missing. |

### The driver

| Option | Default | Meaning |
|---|---|---|
| `driver` | | `user.ultimatepush.driver` |
| `protocols` | `auto` | Which protocols to listen for. `auto` is every one that posts; name them to add WeatherFlow, or to settle an upload that identifies nothing. See [Protocols](Protocols). |
| `model` | UltimatePush | What reports call the station. |
| `infer_unknown` | `series` | What happens to fields the catalog does not cover. See [Unknown fields](Unknown-fields). |
| `field_map_extensions` | empty | Raw field to WeeWX field. Wins over everything else. See [Field map](Field-map). |
| `report_file` | `/var/tmp/weewx-ultimate-push-report.txt` | Where to leave a report when a station sends something the driver cannot place. Empty switches it off. |
| `max_behind` | `3600` | How many seconds behind the computer's clock a console's own timestamp may be and still be believed. See [The console's clock](#the-consoles-clock). |
| `max_ahead` | `60` | The same, for a console whose clock runs fast. |
| `password` | none | Weather Underground only. Refuse uploads that do not present this as `PASSWORD`. It is the one protocol here whose hardware can carry a secret. |
| `metric_wind` | `kph` | Weather Underground metric dialect only. Whether its wind is kilometres per hour or metres per second, which cannot be read off a payload. `kph` or `mps`. See [Protocols](Protocols). |
| `udp_port` | 50222 | WeatherFlow only. The port to listen for broadcasts on. There is no reason to change it. |
| `override_file` | beside the console list | Where the settings the web interface writes are kept. |

### The web interface

A subsection, off unless switched on. See [Web interface](Web-interface).

```ini
[UltimatePush]
    [[web]]
        enable = true
        port = 8080
        token = paste-a-long-random-string-here
        # address = localhost
        # allowed_hosts =
```

| Option | Default | Meaning |
|---|---|---|
| `enable` | `false` | Whether to open the port at all. |
| `port` | 8080 | Which port. |
| `address` | every interface | `localhost` makes it unreachable from the network. |
| `token` | none | Required, at least 16 characters. The driver refuses to start without one. |
| `allowed_hosts` | anywhere | Comma-separated addresses to accept from. |
| `trust_proxy` | `false` | Take the client address from `X-Forwarded-For`. |

## The console's clock

Every upload carries `dateutc`, the time the console read its sensors. The driver uses
it, so a reading belongs to the minute it was taken rather than the minute it arrived.

That matters when an upload is held up: a relay, a queue, a network that was down for
a while. A console with an internet connection keeps its clock by NTP, so a timestamp a
few minutes old means the upload was slow, not that the clock is wrong.

The window is not symmetric. A reading can be delayed, so `max_behind` is generous. A
reading cannot arrive before it was taken, so `max_ahead` only has to cover the drift
between two clocks that are both roughly right. Outside the window the driver says so
and falls back to the time the upload arrived:

```
WARNING user.ultimatepush.transport: Device time 2015-01-01 00:00:00 is 4255 days behind
ours, past what max_behind allows. Using ours.
```

Whether a late reading then reaches the archive record it belongs to is WeeWX's
business, not the driver's. WeeWX 5.5 and later keep the LOOP packets and work the
record out again; see `[StdLoopStore]` in the WeeWX reference. On older versions a
packet from an interval that has already been written cannot get into it, so there
`max_behind` is better set to something small, around `90`.

## Common setups

### On its own, in a local network

The console posts straight to WeeWX. Simplest, and fine where nothing else can reach
the port.

```ini
[UltimatePush]
    driver = user.ultimatepush.driver
    port = 8000
```

Console: server is the WeeWX machine's address, port 8000, path `/`.

### Behind a reverse proxy, reachable from outside

The web server keeps 443 and passes one path through. A path nobody can guess is the
only secret most consoles can carry.

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

Console: server is `weather.example.com`, port 443, path `/a8f3c1e0/report`.

### Alongside a web server on the same machine

Nothing special is needed as long as the ports differ. WeeWX writes its reports to
files; the web server serves them; the driver listens on its own port.

### Two stations, one machine

WeeWX runs one driver per instance, so two stations means two instances, each with
its own configuration file, database and port. See the WeeWX wiki article *Run
multiple instances of WeeWX on one computer*.

### A Tempest and an Ecowitt gateway together

Two sockets, one loop. WeatherFlow is not in `auto`, because it needs a port of its
own and opening one for hardware nobody has is not a thing to do quietly.

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

A hub is named by its serial number, which goes in `passkey` like any other identity.
See [Several consoles](Several-consoles).

### One protocol, named

An upload with nothing in it that says which protocol it is gets refused rather than
read with whichever catalog happened to be first. Naming one settles it:

```ini
[UltimatePush]
    protocols = wunderground
```

Worth doing anyway when you know what you have: it removes a class of mistake, and
costs nothing.

## Configuring the station

### Ecowitt

In **WS View Plus**: *Weather Services*, then page through to *Customized*.

| Field | Value |
|---|---|
| Protocol Type | **Ecowitt** |
| Server IP / Hostname | the machine running WeeWX |
| Path | what you set as `path`, or `/` |
| Port | what you set as `port` |
| Upload Interval | 60 seconds is plenty; 16 is the minimum |

The same console will also speak Weather Underground, and that is read too, but it
carries fewer fields. Nothing outside the WU field list reaches WeeWX that way, which
on a current station means most of the sensors. Use Ecowitt unless something forces
otherwise.

### Everything else

See [Installation](Installation) for Ambient, WeatherFlow, Acurite and LaCrosse.

## Checking it works

```
python -m user.ultimatepush --port 8001
```

Point the console at 8001 for one upload. See [Diagnostics](Diagnostics).
