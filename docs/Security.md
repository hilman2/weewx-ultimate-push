# Keeping strangers out

The driver opens a port that accepts weather readings. Anyone who can reach it can
post readings, and most of this hardware has no way to prove it is the station.

One protocol is an exception. Weather Underground sends `PASSWORD` in every upload,
which is a shared secret and can be checked. A station set up in the web interface is
given one of its own, along with the `ID` that names it, and both are shown once so they
can be typed into the console. Uploads that do not present it are refused, and the
comparison is constant time.

A password for every console that has none of its own goes in the driver section:

```ini
[UltimatePush]
    password = whatever-you-set-in-the-console
```

A station's own comes first. Two consoles told apart by an `ID` would otherwise be able
to use each other's, and an `ID` is readable by anybody who can watch the network.

Neither is protection against somebody who can. They travel in the query string over
plain HTTP, exactly as a secret upload path does, and what they keep out is a stranger
who has found the port rather than one who is watching the wire. Put TLS in front if
that matters.

Everything else sends an identifier rather than a secret. An Ecowitt or Ambient
`PASSKEY` is derived from the MAC address and is visible in every upload; a
WeatherFlow hub broadcasts to the whole network and is not asked for anything at all.
So the port has to be narrowed instead. Use as many of these as fit.

## Bind to one address

```ini
[UltimatePush]
    address = 192.168.1.10
```

Only that interface accepts anything. Behind a reverse proxy, `localhost` means the
port cannot be reached from the network at all:

```ini
    address = localhost
    trust_proxy = true
```

`trust_proxy` makes the driver take the client address from `X-Forwarded-For`, which
is right only when a proxy you control sets that header. Without a proxy, leave it
off: anyone can send that header themselves.

## A path nobody can guess

```ini
    path = /a8f3c1e0-4b2d/report
```

Anything else gets a 404. Most consoles can be given a path but not a header or a
query parameter, which makes this the practical secret for hardware.

Generate one:

```
python -c "import secrets; print('/%s/report' % secrets.token_hex(8))"
```

## A token

For anything that can send a header or a query parameter:

```ini
    token = 4f8a2c1e9b7d3a5f
```

Accepted as query parameter `token`, header `X-Auth-Token`, or a bearer token in
`Authorization`. Compared in constant time. Anything else gets a 403.

## Only from known addresses

```ini
    allowed_hosts = 192.168.1.42, 192.168.1.43
```

Anything else gets a 403. Behind a proxy this sees the proxy unless `trust_proxy` is
set, so set both together or neither.

## What does not work for every protocol

**A path.** Weather Underground hardware has its endpoint burned into the firmware and
cannot be told to use another. An Acurite bridge and a LaCrosse gateway likewise. If
you have any of those, `path` is not available to you and `allowed_hosts` is what is
left.

**Anything at all, for WeatherFlow.** A hub broadcasts on the local network and is
answered by nobody. There is no path, no token and no password, because there is no
request. `allowed_hosts` restricts which senders are accepted, and beyond that the
network is the boundary.

## The web interface is a second door

If you switch it on, there is a second port that can change the field map. It is off by
default and refuses to start without a token of at least 10 characters. An address that
gets the token wrong ten times in five minutes stops being answered at all, right token
or not, until those tries fall out of the window.

It is still plain HTTP, so the token travels in clear and ends up in the browser
history. Bind it to `localhost` and use an SSH tunnel, or put TLS in front, unless the
network is one you trust. See [Web interface](Web-interface.md).

## What none of this does

**Encryption.** All of these protocols are plain HTTP, and none of the hardware offers
TLS. On a local network that is usually acceptable. Across the internet, put a reverse
proxy with a certificate in front and let it terminate TLS. The path and the readings
are then encrypted between the station and the proxy, and the proxy talks to the
driver on localhost.

**Authentication of the sensor.** Nothing stops somebody who knows your path from
posting a plausible temperature. The defence is that they have to know it.

**Protecting a station from a second one.** That is a different problem, and it has
its own answer: the driver answers only to consoles it knows about. See
[Stations](Stations.md).

## A limit worth keeping

```ini
    max_body = 65536
```

The default. An upload is a few hundred bytes, so anything near this is not a weather
station. Requests above it get a 413 without being read into memory.

## After changing any of it

Restart WeeWX and change the console to match. A console pointed at the old path will
be answered with a 404 and its readings dropped, silently as far as it is concerned.
The log says so:

```
WARNING weewx.listener: Rejected a request from 192.168.1.42: bad or missing token
```
