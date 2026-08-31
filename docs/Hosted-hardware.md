# Hosted hardware

A Vantage on a serial port, a Fine Offset console on USB, or any other WeeWX driver,
running beside the stations that upload. One WeeWX, one database, one set of reports.

WeeWX runs one driver, so a Vantage and an Ecowitt gateway normally mean two WeeWX
instances. This driver can host the other driver instead. It is loaded exactly as WeeWX
loads it, from its own section, and its readings join the ones that arrive over the
network. Set one up in the web interface, or in `weewx.conf`; both are below.

There are two sets of options here, and it helps to keep them apart.

Which drivers to run, and what role each has, is this driver's business and is in
[Configuration](Configuration.md#hosted-hardware). What goes inside `[Vantage]` or
`[WMR100]` is that driver's own business, and is not repeated anywhere here. See
[Where a driver's own options come from](#where-a-drivers-own-options-come-from) below.

How it is put together is in [Architecture](Architecture.md#hosted-drivers).

## Adding one in the web interface

Setting up a wired station is the same flow as setting up any other: **Add**, above
the station list. The list there is every kind of station, searchable by make or
model, in three groups by what you have to do:

- **You point it at this machine** — Ecowitt, Ambient and Weather Underground consoles.
  You type an address into the app that configures the console.
- **This machine reads it** — every WeeWX driver installed here, the ones WeeWX ships
  and any you added yourself.
- **It turns up on its own** — a Tempest, which broadcasts, and Acurite and LaCrosse
  gateways, whose firmware holds the server name so only a DNS entry can move it.

Pick a driver from the middle group and its own settings appear, with the defaults its
author wrote: the same ones `weectl station reconfigure` would offer.

Fill them in and press **Try it and set it up**. The driver is opened before anything is
saved, so a serial port that is not there is a message on the page rather than an entry
you have to take out again. On success it starts at once. There is no restart.

What you set up there is kept in `ultimate-push-web.conf`, beside the console list, not
in `weewx.conf`. WeeWX is running from that file, it is often not writable, and it is
your file with your comments in it. The form shows the block to paste into `weewx.conf`
if you would rather keep it there, which is also what `weectl device` needs in order to
find the station.

Afterwards it is a station like any other and is managed under **Stations**, beside
the consoles that upload. **Save and reopen** there closes the driver and opens it again
with the new settings, which is what it takes for a serial port to become a different
serial port. If it will not open, nothing changes and the one that was running still is.

## Adding a wired station in weewx.conf

Configure the driver as if it were the only one, in its own top-level section. That part
does not change, and `weectl device` keeps working on it.

Then name its section under `[[hardware]]`:

```ini
[Station]
    station_type = UltimatePush

[UltimatePush]
    driver = user.ultimatepush.driver
    port = 8000

    [[hardware]]
        station_types = Vantage

        [[[Vantage]]]
            role = main

[Vantage]
    type = serial
    port = /dev/ttyUSB0
    driver = weewx.drivers.vantage
```

At startup the log names what is being read:

```
INFO user.ultimatepush.hardware: Hosting 1 driver(s): Vantage. The archive station is Vantage.
```

Anything WeeWX can load works here, whether it ships with WeeWX or came from elsewhere.
A driver is named by its section, and the section says which module to import.

## Where a driver's own options come from

Every WeeWX driver has a section of its own, named after it, holding whatever that
driver takes: `[Vantage]` has a port and a baud rate, `[WMR100]` has almost nothing,
`[WS28xx]` has a radio frequency. Those options belong to that driver. This one neither
adds to them nor documents them, because there is no version of them here that could
not go out of date.

There are two places to read them, and both are on your own machine.

The web interface shows them when you pick the hardware, one field each, with the
sentence the driver's author wrote above it. That text comes out of the driver as it is
installed, so it describes the version you actually have.

`weectl station reconfigure --driver=weewx.drivers.vantage` writes the same block into
`weewx.conf`, comments and all, which is the same text from the same place.

For anything beyond that, the WeeWX documentation covers each driver it ships under
Hardware. A driver from elsewhere brings its own README.

## Which station fills the plain columns

The same question as for two consoles, with the same answer: one station is the main
one, everybody else is an extra sensor on a channel. See [Stations](Stations.md).

Suppose the Vantage is the wired station and an Ecowitt gateway uploads. The Vantage has
the better anemometer, so it is the main station and the gateway is an extra:

```ini
    [[hardware]]
        station_types = Vantage
        [[[Vantage]]]
            role = main
```

The gateway is then set up in the web interface as an extra station, and its temperature
and humidity go to a channel of its own.

The other way round, with the gateway as the main station:

```ini
    [[hardware]]
        station_types = Vantage
        [[[Vantage]]]
            role = extra
            channel = 4
            name = The Vantage
```

The Vantage's `outTemp` and `outHumidity` then go to `extraTemp4` and `extraHumid4`, and
its pressure and wind are dropped rather than written over the gateway's. An extra
station must be given a `channel`: picking one here would move readings to a different
column the next time the driver started.

## Archive records from a station that has a logger

A Vantage, a Fine Offset console and a WS23xx keep their own archive records. Set
`record_generation = hardware` and those records are used, instead of being worked out
from the readings as they arrive:

```ini
[StdArchive]
    record_generation = hardware
```

The archive station is the first entry in `station_types`. Its logger supplies the
record, and everything the other stations sent during that period is added to it: the
lightning count, the soil probes, the extra channels. Nothing is overwritten, so the
Vantage's own columns come from its logger and the rest come from whoever sent them.

Two things follow from that, and both are worth knowing before you turn it on.

**After an outage there is a gap in everything but the archive station.** When WeeWX
comes back it asks the archive station for what it logged while it was down. Nothing
else has anything to hand over, because nothing was listening. So those records carry
the Vantage's columns and not the gateway's.

**The archive interval becomes the archive station's.** `archive_interval` in
`[StdArchive]` is ignored, and the console's own setting is used. The log says which one
it took.

If the archive station has no logger, nothing changes: WeeWX falls back to working the
record out from the readings, which is what it does today.

## Setting the clock

`StdTimeSynch` reads and sets the archive station's clock, if it has one. Nothing else
is touched. See the WeeWX documentation for the service itself.

## When a wired station stops answering

A driver that fails is closed and built again, waiting ten seconds the first time and
doubling to five minutes. The log says what happened and when the next attempt is:

```
ERROR user.ultimatepush.hardware: The Vantage driver failed (1 so far): could not open
port /dev/ttyUSB0. Trying again in 10 seconds.
```

Nothing else stops. The stations that upload keep being recorded, and the web interface
stays up.

The exception is the archive station at startup. If it cannot be opened at all, the
driver does not start, because the alternative is an archive quietly filled from
software while the console's logger holds the real records.

## What this does not do

Only the archive station is asked for history, and only its clock is read. A second
console with a logger contributes its live readings and not its records.

A driver named under `[[hardware]]` in `weewx.conf` is that file's. The interface shows
it, its role and what it fills, and declines to change any of it. One owner per setting:
two files with an answer each would mean one is quietly ignored, and which one would
depend on the order they happened to be read in.
