# Protocols

Six of them. What each one sends, how the driver tells them apart, and what is peculiar
about each.

If your station works and the readings look right, you do not need this page. It is for
deciding what to buy, working out why a field is missing, or adding a protocol.

## The six

| Name | Hardware | Transport | Units | Names the station with |
|---|---|---|---|---|
| `ecowitt` | Ecowitt gateways and consoles, Froggit, Misol | POST, any path | imperial | `PASSKEY` |
| `wunderground` | Fine Offset Observer, Sainlogic, Meteobridge, any console set to *Wunderground* | GET, fixed path | imperial or metric | `ID` and `PASSWORD` |
| `ambient` | Ambient Weather, *Custom* upload in awnet | POST or GET, any path | imperial | `PASSKEY` |
| `weatherflow` | Tempest, AIR, SKY | UDP broadcast, port 50222 | metric | hub serial number |
| `acurite` | smartHUB, Access | POST, fixed path | imperial | bridge id |
| `lacrosse` | LW301, LW302 | POST, any path | metric | MAC address |

## How an upload is recognised

Not by which port it came to. Every posting protocol shares one port, and the driver
looks at what is in the upload.

Each protocol says how sure it is that an upload is its own, and the surest wins. In
order of how much that settles:

**The path.** A device that speaks Weather Underground cannot be told to post anywhere
but `/weatherstation/updateweatherstation.php`. So that path is nearly conclusive.
Nearly, because an Acurite bridge posts there too.

**A name only one protocol uses.** `mt` is Acurite's and nobody else's. `mac` with a
two-character `id` is LaCrosse's. `stationtype=AMBWeather...` is Ambient's. `PASSKEY`
with any other station type is Ecowitt's.

**Credentials.** `ID` and `PASSWORD` together are Weather Underground's, which matters
behind a reverse proxy that rewrites the path.

An upload that matches none of them is refused rather than read with whichever catalog
happened to be first. The same name means different things in different catalogs, and
`UV` is the example: an index in one dialect, microwatts per square centimetre in
another, forty times apart. If you know what your hardware is, name it:

```ini
[UltimatePush]
    protocols = ecowitt
```

With exactly one protocol configured there is nothing left to guess, and an upload with
nothing in it but readings is read as that one.

## Protocols and dialects

They are different questions, and the driver asks both.

A **protocol** is an exchange: a path, an answer, a way of naming the station.

A **dialect** is a catalog: what the names mean and what units they arrive in.

Weather Underground has two dialects on one endpoint. Fine Offset consoles under one
firmware send `tempf`, `baromin` and `dailyrainin` in Fahrenheit and inches; under
another they send `outtemp`, `relbaro` and `dailyrain` in Celsius and millimetres. Same
path, same credentials, same protocol. The driver decides per upload, on names alone, so
no reading has to be plausible for the answer to be right.

## Ecowitt

The default. Set *Customized* in the WSView app, protocol *Ecowitt*, and choose your own
path.

It wants JSON back:

    {"errcode":"0","errmsg":"ok"}

An upload it cannot acknowledge is retried and eventually given up on, which is why the
answer is exact rather than an empty 200.

The catalog has 532 fields and is generated from `ecowittcustom`. See
[Sensors](Sensors.md).

## Weather Underground

The oldest of them, and the only one where the hardware can present a shared secret.
`PASSWORD` is in every upload, so it can be checked:

```ini
[UltimatePush]
    password = whatever-you-set-in-the-console
```

Everything else here has to be kept out with a path nobody can guess, or with
`allowed_hosts`. See [Keeping strangers out](Security.md).

The path is fixed in the firmware, so `path = /something/secret` and Weather Underground
hardware cannot both be had. `.php`, `.asp` and no extension at all are accepted, because
firmwares have shipped all three.

RapidFire, `realtime=1&rtfreq=2.5`, is read like any other upload. It arrives up to every
two and a half seconds; WeeWX handles that, and the archive record is unaffected.

Three things about this protocol are worth knowing, and all three come from real uploads
rather than from the specification:

**`-9999` means "no reading".** Fine Offset firmwares send it for a sensor that has
nothing to report. Read as a number it is nine thousand degrees below freezing, and it
would go into the archive and into every average computed from it.

**`baromin` means two things.** Sea-level pressure on almost every firmware, station
pressure on `WH2600GEN_V2.2.5` and `WH2650A_V1.2.1`. Both of those say so in
`softwaretype`, so the driver moves the field for them and says so once in the log. Your
own `field_map_extensions` outranks that.

**`UV` in the metric dialect is not the index.** It is the raw irradiance in microwatts
per square centimetre, which is why captured uploads carry values like 919. It goes to
`uvradiation` in watts per square metre, not to `UV`.

### The metric dialect and the wind

One thing about that dialect cannot be read off a payload: whether the wind arrives in
kilometres per hour or in metres per second. The two differ by 3.6, both are plausible
for the numbers these consoles send, and the firmware does not say.

The default follows `weewx-interceptor`, which has been pointed at this hardware for a
decade: kilometres per hour. If your console disagrees:

```ini
[UltimatePush]
    metric_wind = mps
```

The packet then becomes `weewx.METRICWX`, where rain is in millimetres and no rain
conversion is needed either.

## Ambient Weather

Descended from the same Fine Offset design as Ecowitt's, and it shows: a `PASSKEY` built
from the MAC address, imperial units, the same POST of an urlencoded form.

What differs is the vocabulary. Ambient says `soilhum1` where Ecowitt says
`soilmoisture1`, `battout` where Ecowitt says `wh65batt`, `lightning_day` where Ecowitt
says `lightning_num`. It also has `relay1` to `relay10` and the AQIN indoor air module,
which Ecowitt has no equivalent of.

Read with the Ecowitt catalog an Ambient upload does not fail. The temperature and the
wind arrive and the soil probes, the batteries and the lightning sensor are dropped. The
station type is what separates them, and Ambient consoles always send theirs.

## WeatherFlow

The odd one out, in three ways.

**It broadcasts.** A hub sends JSON to the whole local network on UDP 50222, whether or
not anybody is listening. Nothing is configured on the hub and nothing is answered, so
there is nothing to keep strangers out with beyond the network itself. Use
`allowed_hosts` if that matters.

Because it needs a socket of its own, it is not in `protocols = auto`. Name it:

```ini
[UltimatePush]
    protocols = ecowitt, weatherflow
```

**The readings are positional.** An observation is an array, and index 7 of `obs_st` is
the air temperature because it is. A mapping that is off by one puts the humidity in the
pressure column and looks entirely plausible, which is why the layouts are tested
against WeatherFlow's own examples.

**Its rain is already a difference.** Every other protocol here sends running counters.
A hub sends the millimetres since its last report, which is what WeeWX means by `rain`.
Differencing it again with `StdWXCalculate` would record almost nothing.

Eight message types are read: `obs_st`, `obs_air`, `obs_sky`, `rapid_wind`, `evt_strike`,
`evt_precip`, `device_status` and `hub_status`. `rapid_wind` arrives every three seconds
and becomes a loop packet like any other.

An AIR and a SKY on one hub are one station with two sensors, so the hub's serial number
is what names the station, not the device's.

## Acurite

A smartHUB or an Access posts to Chaney's own servers and cannot be told otherwise.
Reading it means answering for `hubapi.myacurite.com` on your own network: a DNS entry,
or a rule on the router. That is a decision about your network rather than about this
driver, and it is in [Hardware](Hardware.md).

**One request per sensor.** A frame says what kind of sensor it is in `mt` and which one
in `sensor`, then carries three or four readings. A station with a 5-in-1 and three
towers sends four requests every eighteen seconds, each with `tempf` in it, each meaning
something different.

So the 5-in-1 is the station and keeps the plain names, and everything else arrives
named after the sensor that sent it:

    tower00002719_tempf
    tower00002719_humidity

Which wall that tower is on is not in the payload. Decide, then paste:

```ini
[UltimatePush]
    [[field_map_extensions]]
        tower00002719_tempf = extraTemp1
        tower00002719_humidity = extraHumid1
```

The name stays the same across restarts, because the bridge keeps its sensor numbers.

The bridge puts its own barometer in every frame it forwards, whatever sent it, so that
one is not qualified. It is station pressure whatever the name suggests: the bridge does
not know its own altitude, and WeeWX derives `barometer` from this and the altitude in
`weewx.conf`.

**Not read: the Chaney format.** Bridges before July 2016 send their own shape, where
the readings are hex strings and the pressure has to be computed from seven calibration
constants. A bridge updates itself from Chaney on first contact, so a station still on it
has been offline for nine years.

## LaCrosse

An LW301 or LW302, likewise pointed here by a DNS entry.

Two-letter names, one request per sensor, and a `ch` saying which channel a sensor is on.
Channel 1 is the station. Channels two and up go to `extraTemp` and `extraHumid`, and
where they hang is yours to say.

The gateway sends Celsius, metres per second and millibars, and then sends its rain in
inches. That one conversion is done on the way in.

Nine of its parameters have never had their meaning established: `p`, `or`, `gw`, `av`,
`htr`, `cz`, `ttr`, `rro`, `pv`, `lb`, `ac`, `ptr` and the `uv` that is not `uvh`. They
are kept out of the database, because a column of numbers nobody can label is worse than
no column, and written to the report so that somebody with the hardware can work them
out.

**Not read: the GW1000U.** It does not send name and value pairs at all. It registers
with the server, is told its serial number, its ping interval and its display
brightness, and then exchanges binary frames. That is a different protocol, not a
dialect of this one.

## Adding one

A protocol is a small class and a catalog. `bin/user/ultimatepush/protocols/` has six
worked examples, and [Contributing](Contributing.md) has the walkthrough.

What is needed:

- how to recognise an upload as yours, in `claims`
- what the fields are called, in a catalog
- what the hardware wants to read back, if anything
- which field names the station
- which rain counter has to be differenced, or `None` if the protocol sends `rain`

A captured payload in `tests/fixtures` and a test against it are the rest.
