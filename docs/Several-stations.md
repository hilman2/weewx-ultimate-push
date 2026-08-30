# Several stations

Growing a configuration from one station to several, by hand: how the file is built
up, how you say which reading comes from which station, and where to look to see what
each one is delivering.

> **There is a web interface for all of this.** It is on by default, and the driver
> prints its address when WeeWX starts:
>
> ```
> INFO user.ultimatepush.driver: The web interface is at
> http://1.2.3.4:8080/?token=abcdefg12345
> ```
>
> Everything on this page can be done there instead, and one thing is much easier:
> deciding which reading goes into which database column. On paper that means
> knowing the raw field name your console sends; in the interface it is a list of
> what actually arrived, with a selector beside each. See
> [Web interface](Web-interface.md).

Setting up one station of a given kind is on that kind's own page. This page starts
where those leave off.

## The problem, in one paragraph

Two stations both send an outdoor temperature. The database has one column for it. If
both write it, they take turns every few seconds, and afterwards nothing can say which
reading came from which sensor. Not a report, not an aggregate, not somebody reading
the table by hand.

So one station's readings go where a WeeWX report expects them, and everybody else is
moved aside or dropped. Everything on this page is about deciding which is which.

## Building the file up

Start from one station.

```ini
[Station]
    station_type = UltimatePush

[UltimatePush]
    driver = user.ultimatepush.driver
    port = 8000

    [[stations]]
        [[[garden]]]
            path = /abcdefg12345/report
```

Add a second by adding a subsection. It needs `role` and `channel`, because a file has
no defaults to offer you the way the interface does.

```ini
    [[stations]]
        [[[garden]]]
            path = /abcdefg12345/report

        [[[roof]]]
            path = /hijklmn67890/report
            role = extra
            channel = 4
```

Stations of different kinds sit in the same list. Their sections differ only in what
names them: a path for an Ecowitt console, an `id` and a `password` for a Weather
Underground one, a serial number for a hub. Only the last of those has to be looked up,
because it is the hardware's own and the log prints it after the first upload.

```ini
    [[stations]]
        [[[garden]]]
            path = /abcdefg12345/report

        [[[shed]]]
            id = up-abcde123
            password = abcdefg12345
            role = extra
            channel = 2

        [[[tempest]]]
            id = HB-000abcde
            role = extra
            channel = 3
```

A hub broadcasts, so it also has to be switched on:

```ini
[UltimatePush]
    protocols = ecowitt, wunderground, weatherflow
```

A station this machine reads over a cable is a station too, in a list of its own,
because it is loaded rather than waited for:

```ini
[UltimatePush]
    [[hardware]]
        station_types = Vantage
        [[[Vantage]]]
            role = extra
            channel = 5

[Vantage]
    driver = weewx.drivers.vantage
    type = serial
    port = /dev/ttyUSB0
```

See [Hosted hardware](Hosted-hardware.md).

## Which station is the main one

Exactly one is. Its readings go to `outTemp`, `barometer`, `windSpeed` and the rest,
which is what a WeeWX report reads without being told anything.

`role = main` is the default, so the station with no `role` line is it. Give every
other station `role = extra` and a `channel`.

If two sections both say `main`, the first one written is the one that writes, and the
driver says so at startup. That is a mistake worth fixing rather than relying on.

Changing which station is the main one changes what every report shows from that
moment on, and does not change what is already recorded. `outTemp` then holds one
sensor up to that point and another afterwards. See
[Stations](Stations.md#changing-which-station-is-the-main-station) before doing it.

## Where an extra station's readings go

Temperature and humidity go to the channel you gave it: `extraTemp4` and
`extraHumid4` for `channel = 4`. The standard schema has eight of each.

Everything else it sends has nowhere of its own. Wind, rain and pressure from an extra
station are dropped rather than written over the main station's. That is not a
limitation of this driver; the schema has one `windSpeed`.

Two things follow.

**A second full weather station contributes its temperature and humidity, and little
else,** unless you give the rest somewhere to go. That is the next section.

**A sensor that only the extra station has arrives intact.** A soil probe on the roof
console does not collide with anything, so it is written, and the first station to send
it owns that column from then on.

## Saying where a particular reading goes

`field_map_extensions` under a station places one of its raw readings into one WeeWX
field. It is the last word: it beats the role and it beats who got there first.

```ini
        [[[roof]]]
            path = /hijklmn67890/report
            role = extra
            channel = 4
            [[[[field_map_extensions]]]]
                soilmoisture1 = soilMoist3
                tf_ch1 = soilTemp5
                windspeedmph = windSpeed      # take the wind from this one instead
```

The name on the left is what the console sends, exactly as it sends it. Getting it
right on paper means knowing that name, which is what the **Raw uploads** tab in the
interface is for: it shows the last twenty uploads per station, verbatim.

The name on the right is a WeeWX field. Whether the database has a column for it is a
separate question, and the answer is usually no for anything outside the standard
schema. See [Database columns](Database-columns.md).

A placement applies to one station. Writing `windspeedmph = windSpeed` under the roof
console does not stop the garden console sending wind; it means both would write it,
and the second one to arrive is turned away. If you want the roof console's wind
instead of the garden one's, take the column from the garden console as well.

## Who owns which column

A column belongs to whichever station first filled it. Everybody else is turned away
from it, and the main station outranks that.

This is what stops three identical extra sensors from taking turns in `soilMoist1`.
It is recorded in `ultimate-push-web.conf` rather than worked out again at each
startup, so it survives a restart and a station being offline for a week.

To move a column from one station to another, release it. The next station to send
that reading takes it. In the interface that is a button on the station; by hand it is
the `[columns]` section of that file.

## Seeing what each station delivers

Four ways, in the order they are useful.

**The web interface, Fields tab.** Every station, every reading it sends, and where
each one goes. This is the only view that answers "which station fills `outTemp`"
directly.

**The log, at startup.** Each station reports the catalog it was read with and how many
fields it has. When a reading is dropped because another station owns the column, that
is logged once per station rather than per upload:

```
INFO user.ultimatepush.driver: 'roof' sends windSpeed, rain and 3 more that
'garden' already fills. They are not being recorded.
```

**The diagnostic command.** One run says what arrived, how it was read and where it
went, without a browser. See [Diagnostics](Diagnostics.md).

**The database.** `weectl database check` and a `SELECT` on the archive table say what
is actually stored, which is the answer that settles arguments.

## What to check when a station records nothing

In this order.

**Is it known?** An upload from a station the driver does not know is refused. The log
says so, and the interface shows it waiting to be let in.

**Is it being held back?** An extra station is held back until the main station has
been heard once, ever, so that its readings cannot land in columns the main station is
about to claim. This happens once, not at every restart, and it is logged.

**Does it own any columns?** An extra station whose readings all collide with the main
station's records nothing, and that is the intended behaviour. It needs
`field_map_extensions` to place them somewhere else.

**Do the columns exist?** A reading placed into a field the database has no column for
is dropped by WeeWX, not by this driver. See
[Database columns](Database-columns.md).
