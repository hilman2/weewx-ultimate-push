# Which console the driver listens to

The driver opens a port and waits. Anything on the network can send to that port, and
most of this hardware does not prove who it is. So the driver answers to the stations
it knows about and refuses the rest.

This page explains what happens, step by step.

## What names a station

Every protocol has something, and it is not the same thing:

| Protocol | Field | What it is |
|---|---|---|
| Ecowitt, Ambient | `PASSKEY` | derived from the console's MAC address |
| Weather Underground | `ID` | what you registered the station under |
| WeatherFlow | `hub_sn` | the hub's serial number, e.g. `HB-00013030` |
| Acurite | `id` | the bridge's MAC address |
| LaCrosse | `mac` | likewise |

Whichever it is goes in `passkey`, in the driver section or under `[[stations]]`. The
option is named for the commonest case rather than renamed for each protocol.

An AIR and a SKY on one WeatherFlow hub are one station with two sensors, so the hub
is what is named and not the devices.

## Why this matters at all

Every console numbers its sensor channels from one. A WN34 on channel 1 of your
gateway is `tf_ch1`. A WN34 on channel 1 of a second gateway is also `tf_ch1`. Nothing
in the upload says which gateway it came from.

If both were accepted without being told apart, both would land in the same database
column. One reading would overwrite the other every few seconds, and the column would
hold a mixture of two sensors. **That cannot be undone.** No one can look at such a
value afterwards and say which probe it came from.

Hence the rule below.

## Step by step

### 1. The driver starts and knows nobody

Nothing configured, no console yet. The driver listens, and the first upload decides
whose station this is.

### 2. Your console uploads for the first time

It says who it is in the first field of every upload:

```
PASSKEY=3178AB6B42A759F51A5A4AD72E37F8DE&stationtype=EasyWeatherPro_V5.2.7&tempf=59.7...
```

The driver adopts it, writes that value to a file, and says so:

```
INFO user.ultimatepush.driver: Console '3178AB6B42A759F51A5A4AD72E37F8DE' at 192.168.1.42
is now this driver's station, recorded in /etc/weewx/ultimate-push-consoles.txt. Uploads
from any other console are refused until it is named under [[stations]].
```

Nothing else is needed. The readings arrive from here on.

### 3. Everything carries on

The console uploads every 8 to 60 seconds, the driver recognises it, the readings go
into the database. This is the normal state, and most stations never leave it.

### 4. A second console appears

Maybe you bought one. Maybe a neighbour typed the wrong address. Maybe you were
testing. The driver does not know it, so the upload is ignored, and it says once:

```
WARNING user.ultimatepush.driver: An ecowitt upload from 192.168.1.51 names station
'9A2B4C6D8E0F1A3B5C7D9E1F2A4B6C8D', which is not one of this driver's consoles.
Ignoring it. If it is yours, add it under [[stations]] with its own field map: two
consoles number their channels from one, and would otherwise write into the same
fields.
```

Your first console keeps recording, without a gap. Nothing is mixed.

### 5. You want the second one as well

Now you decide where its sensors go. Both consoles get a name and a field map:

```ini
[UltimatePush]
    driver = user.ultimatepush.driver
    port = 8000

    [[stations]]

        [[[garden]]]
            passkey = 3178AB6B42A759F51A5A4AD72E37F8DE
            [[[[field_map_extensions]]]]
                tf_ch1 = soilTemp1          # spike in the raised bed

        [[[roof]]]
            passkey = 9A2B4C6D8E0F1A3B5C7D9E1F2A4B6C8D
            [[[[field_map_extensions]]]]
                tf_ch1 = extraTemp12        # same channel number,
                                            # different sensor
```

Restart WeeWX. Both consoles record now, each into fields of its own, and every packet
says which console it came from in a field called `station`.

The two do not have to speak the same protocol. A Tempest and an Ecowitt gateway are
two stations on one driver like any other pair, and each is named by whatever its own
protocol uses:

```ini
    protocols = ecowitt, weatherflow

    [[stations]]
        [[[garden]]]
            passkey = 3178AB6B42A759F51A5A4AD72E37F8DE
        [[[roof]]]
            passkey = HB-00013030
```

A station that changes protocol keeps its own field map. The driver holds one mapping
per catalog it has seen from that station, so a console moved from Ecowitt to Weather
Underground does not carry its Ecowitt inferences across.

### 6. WeeWX restarts

The driver reads the file, or your `[[stations]]` section, and knows at once who it
answers to. Nothing is learned again, and nothing depends on which console happens to
upload first.

That last point is the whole reason for the file. Without it, a restart would hand the
station to whichever console spoke first, and on a station where one uploads every 8
seconds and another every 60, that is a coin toss. The column would end up holding
both sensors anyway, just further apart in time.

## Where the file is

Beside `weewx.conf`, called `ultimate-push-consoles.txt`:

```
# Consoles this WeeWX driver answers to, one PASSKEY per line.
#
# The first console to upload was recorded here, so that a second one cannot start
# writing into the same fields. Two consoles number their channels from one, and
# nothing afterwards can separate two sensors that have shared a column.
#
# To add a console, do not edit this file. Give it a name and a field map under
# [[stations]] in weewx.conf, so that its channels go somewhere of their own.
#
# To replace a console, delete its line and restart: the next one to upload is
# adopted. To do without this file entirely, set 'passkey' in the driver section.

3178AB6B42A759F51A5A4AD72E37F8DE    # first console seen, from 192.168.1.42
```

Put it somewhere else with `console_file`:

```ini
[UltimatePush]
    console_file = /var/lib/weewx/my-consoles.txt
```

If it cannot be written, the driver says so and carries on. The console is then
learned again after every restart, which works, but leaves the coin toss in place. Set
`passkey` instead.

## Doing without the file

Name the console in the configuration, and nothing is learned or stored:

```ini
[UltimatePush]
    passkey = 3178AB6B42A759F51A5A4AD72E37F8DE
```

This is the tidiest arrangement, and the only one that survives a rebuilt machine
without anyone having to think about it.

## Common situations

**I replaced my console.** A new console has a new PASSKEY, because it comes from the
hardware. Delete the line in the file and restart, or change `passkey` in the
configuration.

**I moved the sensors to a new gateway.** Same thing. The gateway holds the PASSKEY,
not the sensors.

**My readings stopped after I changed something.** Look for the refusal warning in the
log. It names the PASSKEY that was ignored, which is usually the new console.

**I use the Wunderground protocol.** Those uploads carry `ID` instead of `PASSKEY`,
and it is used the same way.

**My hardware sends neither.** Then it cannot be told apart from anything else, and
the driver accepts it as its station. Nothing more is possible at the protocol level.

## Finding a PASSKEY

It is the first value in any upload. The simplest way to see it:

```
python -m user.ultimatepush --port 8001
```

Point the console at that port for one upload, read the value, change it back. Or look
in `ultimate-push-consoles.txt`, where the driver has already written it.

Keep it out of anything public. It is what Ecowitt's own servers use to recognise your
station.
