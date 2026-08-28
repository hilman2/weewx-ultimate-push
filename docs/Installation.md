# Installation

## Requirements

- WeeWX 5.0 or later
- Python 3.7 or later
- Hardware that pushes. See [Protocols](Protocols) for the six it reads.

Nothing else. No pip packages, no compiler.

## Install

```
weectl extension install https://github.com/hilman2/weewx-ultimate-push/releases/latest/download/weewx-ultimate-push-0.8.0.zip
sudo systemctl restart weewx
```

Two commands. The installer sets `station_type`, writes the `[UltimatePush]` section,
sets up the rain counter, and switches on the web interface with a token of its own.

`weectl station reconfigure` also offers `UltimatePush` in its list, if you would rather
go that way.

To install from a clone instead:

```
git clone https://github.com/hilman2/weewx-ultimate-push.git
weectl extension install weewx-ultimate-push
```

## Point the hardware at it

### Ecowitt, Froggit, Misol

In **WS View Plus**: *Weather Services*, page through to *Customized*.

| Field | Value |
|---|---|
| Protocol Type | Ecowitt |
| Server IP / Hostname | the machine running WeeWX |
| Path | `/` unless you set `path` |
| Port | 8000 unless you changed it |
| Upload Interval | 60 |

### Ambient Weather

In **awnet**: *Device Settings*, then the custom server fields.

| Field | Value |
|---|---|
| Server IP / Hostname | the machine running WeeWX |
| Path | `/data/report/` unless you set `path` |
| Port | 8000 |
| Protocol | Ambient |
| Upload Interval | 60 |

### Weather Underground

Set the server to the machine running WeeWX and the port to 8000. The path is fixed in
the firmware and cannot be changed, so leave `path` out of the driver section. `ID` and
`PASSWORD` can be anything you like; set `password` in the driver section to the same
thing and uploads that do not present it are refused.

A Fine Offset console under *Weather logger* or *HP1001* firmware speaks the metric
dialect of this protocol. It is recognised on its own; read the wind note in
[Protocols](Protocols) before trusting the wind speed.

### WeatherFlow

Nothing to point. The hub broadcasts on UDP 50222 whether or not anybody is listening.
The driver has to be told to open that socket:

```ini
[UltimatePush]
    protocols = ecowitt, weatherflow
```

Both the hub and WeeWX have to be on the same network segment, because a broadcast does
not cross a router.

### Acurite and LaCrosse

Neither bridge can be told where to post. Both need their maker's hostname pointed at
the machine running WeeWX:

| Hardware | Hostname to redirect |
|---|---|
| Acurite smartHUB, Access | `hubapi.myacurite.com` |
| LaCrosse LW301, LW302 | `box.weatherdirect.com` |

How is up to your network. A `dnsmasq` entry, a rewrite on the router, or an entry in
the DNS server the bridge uses. See [Hardware](Hardware).

Both bridges post to port 80, so WeeWX has to listen there, which needs root. Running
WeeWX as root is not a good trade. Put a reverse proxy in front instead, or redirect the
port with a firewall rule:

```
iptables -t nat -A PREROUTING -p tcp --dport 80 -j REDIRECT --to-port 8000
```

## Check before starting WeeWX

```
python -m user.ultimatepush --port 8001
```

Point the station at port 8001 for one upload, then change it back. The command prints
which protocol it was, what arrived, what it could not place, which database columns are
missing, and which of those already hold readings. Running it changes nothing.

## Start

```
sudo systemctl restart weewx
sudo journalctl -u weewx -f
```

Within one upload interval the log shows:

```
INFO user.ultimatepush.driver: Driver version is 0.5.0, listening with weewx.listener for Ecowitt, Ambient Weather, Acurite, LaCrosse LW30x, Weather Underground
INFO weewx.listener: Listening for HTTP requests on *:8000
INFO weewx.engine: Starting main packet loop.
```

Then, on the first upload, which catalog it was read with:

```
INFO user.ultimatepush.driver: Reading ecowitt uploads with the 'ecowitt' catalog, 532 fields.
```

Followed by any fields waiting for a decision. See [Field map](Field-map).

## Rain

None of this hardware sends the rain since the last upload. It sends running counters,
and the installer sets up `StdWXCalculate` to difference `dayRain`, which suits four of
the six protocols. WeatherFlow needs nothing; LaCrosse needs `input = totalRain`. The
driver says so at startup if the setting does not suit what you enabled.

## Upgrade

```
weectl extension install https://github.com/hilman2/weewx-ultimate-push/releases/latest/download/weewx-ultimate-push.zip
sudo systemctl restart weewx
```

Your `[UltimatePush]` section is left alone. Read the
[changelog](https://github.com/hilman2/weewx-ultimate-push/blob/main/CHANGELOG.md) first
if you skipped versions: a field that moves is listed there.

## Uninstall

```
weectl extension uninstall ultimate-push
weectl station reconfigure
```

Pick another station type when asked. The database keeps everything it collected.
