# Sensors this driver goes and asks

Some hardware cannot be pointed anywhere. There is no field for a server address,
because it was never meant to send anything: it sits on your network and answers
whoever asks. A PurpleAir is like this, and so is a Davis AirLink, and so is most of
what is sold as having a local API.

So the driver asks. Every so often it fetches the sensor's own answer, reads it the
same way it reads an upload, and records it. From there nothing is different: the
same field map, the same channels, the same rule about which station owns which
column.

> **There is a web interface for all of this.** It is on by default, and the driver
> prints its address when WeeWX starts:
>
> ```
> INFO user.ultimatepush.driver: The web interface is at
> http://1.2.3.4:8080/?token=abcdefg12345
> ```
>
> Add a station there, pick the sensor from the list under *This machine reads it*,
> type its address, and press the button. It is asked once before anything is saved,
> so a wrong address is a message on the screen rather than something to undo. See
> [Web interface](Web-interface.md).

## The whole of it

```ini
[UltimatePush]
    [[polling]]
        [[[air]]]
            address = 1.2.3.4
            protocol = purpleair
            interval = 60
            role = extra
            channel = 3
```

That is a finished station. There is no second block naming it under `[[stations]]`,
and there is nothing waiting to be let in.

This is the one kind of station that needs nothing recognised. Everything else that
arrives here had to be identified first, because an upload turns up on a port and
something has to say which console sent it. Nothing has to say that here: the driver
asked an address it was given, and whatever answered is what it asked. That is why
the block is short.

`air` is the station's name, and you choose it. It is what the log and the web
interface call this sensor.

## What each line is

**`address`** is where the sensor is on your network. The protocol knows what to ask
it for, so the address is enough. Give the sensor a fixed address in your router,
under whatever the router calls a reserved lease: one that changes is one that stops
being found.

**`protocol`** says how to read the answer. Naming it here also switches it on;
there is nothing to add to `protocols` in the section above.

**`interval`** is seconds between one answer and the next question. Sixty is
sensible. Five is the shortest allowed, and asking faster than a sensor measures
buys nothing.

**`role`** and **`channel`** are the same as for any other station, and mean the same
thing. See [Several stations](Several-stations.md).

**`url`** can replace `address` for a sensor that answers somewhere unusual. Then
`protocol` is still needed, to say how to read what comes back.

**`timeout`** is how long to wait for an answer, in seconds. Ten by default, which is
long for anything on your own network.

## Which sensors

| Protocol | Hardware | Page |
|---|---|---|
| `purpleair` | PurpleAir PA-II, PA-II-SD and PA-I | [PurpleAir](Protocol-Purpleair.md) |
| `airlink` | Davis AirLink | [Davis AirLink](Protocol-Airlink.md) |

Adding another is a catalog and a protocol class, both small, and the asking is
already written. See [New sensors](New-sensors.md).

## Trying it without the hardware

A sensor that has to be asked is the one kind of station nobody can try before they
own it. A console that uploads can be imitated with `curl` and hardware on a cable
has the WeeWX simulator; there is nothing to ask when there is nothing there.

So there is one of each to ask:

```bash
python -m user.ultimatepush --fake-purpleair
```

```bash
python -m user.ultimatepush --fake-airlink
```

They answer on ports 8081 and 8082, with readings that move. Point a source at
`127.0.0.1:8081` and the whole of this page can be walked through before the real
sensor arrives.

## Where the readings go

An air quality sensor sends particle counts nothing else sends, and a temperature
that fights with your weather station for `outTemp`.

The particle counts have nowhere to collide, so they arrive as themselves:
`pm1_0`, `pm2_5`, `pm10_0`, and more besides. A PurpleAir has two laser counters and
sends both, and an AirLink sends averages over an hour, three hours and a day beside
the current reading. WeeWX has columns for the first three; the rest need adding, and
[Database columns](Database-columns.md) says how.

The temperature and humidity are the reason for `role = extra`. On a PurpleAir the
thermometer is inside the housing beside electronics that are warm and reads several
degrees above the air outside. As an extra station it goes to `extraTemp3` rather
than `outTemp`, where nothing mistakes it for the air temperature.

## When it stops recording

**Nothing answers.** The log says so once, when it starts failing, and then stays
quiet rather than writing a line a minute for a sensor that is away for the winter.
It keeps trying, waiting longer between tries up to five minutes, and says so again
when the sensor comes back. Look at where the log starts rather than where it ends.

**Something answers and it is refused.** Whatever is at that address is not what the
`protocol` line says. Usually the address moved and now belongs to something else.

**It answers and records nothing.** Its readings are all ones another station already
fills. That is the ordinary rule about columns and not something particular to
polling; see [Several stations](Several-stations.md#who-owns-which-column).

## What it costs

One thread per source, asleep between questions. A sensor that has been unplugged
holds up only itself.

Nothing is opened on your network. The driver makes the connection, so a polled
source needs no port, no path and no secret, and nothing about it is reachable from
outside this machine.
