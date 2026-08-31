#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""Write a page for each protocol: how to set one up by hand.

One page per protocol, for somebody configuring `weewx.conf` in a text editor. What
the hardware is, the smallest configuration that works, what to type into the
console, every option that is only this protocol's, and what to check when nothing
arrives.

What each protocol needs is written here. What it is called, what it sends to name
itself, what goes into the console and whether it can be set up before it has
uploaded all come from the protocol classes, so the pages cannot drift from the code.

    python tools/build_protocols.py

How an upload is recognised and what each protocol carries is a different question,
for a different reader, and stays in docs/Protocols.md.
"""

import argparse
import io
import os.path
import sys
import textwrap

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, 'bin', 'user'))

# The address, port and path the examples are written with. Fixed, so that a page
# reads the same wherever it was built.
ADDRESS = '1.2.3.4'
PORT = '8000'
# Where a polled source's example points, and what its block is called, for the two
# that are not an air quality sensor on port 80. The example has to be a block
# somebody can copy, and one pointed at the wrong port is not that.
FETCH_ADDRESS = {'homeassistant': '1.2.3.4:8123'}

# The polled protocols whose readings are a main station's rather than an extra
# sensor's. Said rather than worked out: the obvious guess is that anything with a
# rain counter is the weather station, and that is wrong for Home Assistant, which
# has one because an integration reporting rain reports a total, and is still most
# often a room sensor standing beside somebody's weather station.
IS_THE_STATION = {'ecowitt_gateway', 'ambient_cloud'}

# What the block is called, where 'air' is wrong. It is the station's name, so it has
# to read like the readings in it: a Home Assistant block whose example entities are
# sensor.garden_temperature cannot be called 'air'.
FETCH_BLOCK = {
    'homeassistant': 'garden',
    'ecowitt_gateway': 'garden',
    'ambient_cloud': 'garden',
}
PATH = '/abcdefg12345/report'
IDENT = 'up-abcde123'
PASSWORD = 'abcdefg12345'

INTERFACE = """> **There is a web interface for all of this.** It is on by default, and the driver
> prints its address when WeeWX starts:
>
> ```
> INFO user.ultimatepush.driver: The web interface is at
> http://1.2.3.4:8080/?token=abcdefg12345
> ```
>
> Everything on this page can be done there instead, and one thing is much easier:
> deciding which reading goes into which database column. See
> [Web interface](Web-interface.md).
"""

# What cannot be read off the protocol class: what is worth knowing before setting one
# up, and what to look at when nothing arrives.
WRITTEN = {
    'airlink': {
        'good': """Give the sensor a fixed address in your router, under whatever the
router calls a reserved lease. One whose address changes stops being found, and the
log is the only place that says so.

Sixty seconds is a sensible interval. The device averages over longer than that
anyway, and the readings that matter are the averages.

Set it up as an extra station. Its thermometer is inside the housing and reads above
the air outside, by less than a PurpleAir's but by enough to matter. As an extra
station it lands in `extraTemp`, where nothing mistakes it for the air temperature.

Two kinds of particle reading arrive and they are not the same thing. `pm_2p5` and
its relatives are averages the device worked out; `pm_2p5_last` is the last raw count
from the laser. Both are recorded, in columns of their own, and the averages are what
the device is for. `pct_pm_data_*` says how much of each averaging window actually had
data in it: below about 90 the average over it is worth less than it looks.

The readings are Fahrenheit and micrograms per cubic metre, which is what Davis sends
and what WeeWX keeps those columns in when it is reading US. Nothing is converted.

No sensor yet? `python -m user.ultimatepush --fake-airlink` answers like one.""",
        'wrong': """Nothing is recorded and the log says the sensor cannot be
reached: the address is wrong, or has moved. `curl http://1.2.3.4/v1/current_conditions`
from this machine settles which. It is said once and then the driver stays quiet, so
look at the start of the log rather than the end.

Something answers and it is refused. Another Davis device speaks this same API and
sends a different shape of reading, a WeatherLink Live in particular. Reading one of
those with this catalog would place a handful of names and drop the rest, so it is
turned away instead.

The temperature is too high. It is measured inside the housing. See above.""",
    },
    'rtl433': {
        'good': """rtl_433 is a separate program and none of it is part of this
driver. Install it, and have it send here:

```bash
sudo apt install rtl-433
rtl_433 -C si -F syslog:127.0.0.1:1433
```

`-C si` asks it to convert what it can itself, which costs nothing and means one
less thing that can be wrong. `-F syslog:` is how it sends: one datagram per
message, which is why nothing has to start or supervise it.

Leave it running with a unit of its own rather than starting it by hand. Put this in
`/etc/systemd/system/rtl_433.service`:

```ini
[Unit]
Description=rtl_433
After=network.target

[Service]
ExecStart=/usr/bin/rtl_433 -C si -F syslog:127.0.0.1:1433
Restart=always
User=nobody

[Install]
WantedBy=multi-user.target
```

then `sudo systemctl enable --now rtl_433`. The receiver is a USB device and belongs
to root until a udev rule says otherwise; rtl-433's package installs one.

**Everything in range turns up, including the neighbours'.** That is the nature of
listening rather than being sent to, so nothing is recorded until you say which
sensors are yours. They appear in the web interface, most often heard first, which
is a good guide: something heard sixty times an hour is close by and transmitting on
a schedule, and something heard once was a car going past. *Not mine* takes one off
the list for good.

**A battery change can rename a sensor.** rtl_433's own documentation says an id may
be programmed in or may be chosen afresh at each power on. When one of yours does
that it stops recording and turns up as something new; the web interface can move
the station onto the new id, which keeps its name, its channel and the columns it
had.

No receiver yet? `python -m user.ultimatepush --fake-rtl433` sends what rtl_433
sends, three sensors at a time, one of them a neighbour's.""",
        'wrong': """Nothing arrives at all. rtl_433 is not running, or is sending
somewhere else. `rtl_433 -C si -F json` in a terminal prints what it hears, which
settles whether the radio is working before anything about this driver comes into
it.

Everything is refused. That is what happens until a sensor is let in, and it is on
purpose: a receiver hears over the fence. The log names each one.

A sensor was recording and stopped. Look for a new one in the waiting list with the
same model and a different id: that is what a battery change does.

The temperature is right and the rain is nonsense. Nearly every one of these gauges
sends the total since its battery went in, and WeeWX has to be told to difference
it. That is `[StdWXCalculate]` and the driver says so at startup if it is not set.""",
    },
    'homeassistant': {
        'good': """Home Assistant is not hardware. It is the other program on your
network that already talks to the thermometer in the bedroom, the soil probe in the
raised bed and the sensor inside the boiler, and it will tell this driver what any of
them is reading. So the answer to "can WeeWX read my Aqara" is now: if Home Assistant
can, this can.

**Make a token first.** In Home Assistant, click your name at the bottom of the
sidebar, open the *Security* tab, scroll to *Long-lived access tokens* and create one.
It is shown once. Copy it into the `token` line before you close the dialog, because
there is no way to see it again and the only fix is to make another.

That token can do everything your user account can do, including turning things off.
Keep it the way you would keep the password. It goes in `weewx.conf`, which is
readable by whoever can read that file, or in the settings file the web interface
writes, which is the same. This driver never prints it: not in a log line, not on the
page that shows what arrived, not in an error message. If you would rather it could
do less, make the token under a Home Assistant user of its own with only the areas you
want it to see.

**One block is one device, not one Home Assistant.** Home Assistant groups its sensors
into devices, and that grouping is exactly what this driver needs: the thermometer on
the balcony is one station and the one in the living room is another, so one of them
fills the outdoor temperature and the other lands in a column of its own. Set up a
second block against the same address for the second device. There is no cost to it.

**Say which sensors, and in what order.** `entities` names them, and the order is not
decoration. The first temperature in the list is the temperature; a second one on the
same device arrives under a name of its own and waits in the web interface for you to
say which column it should have. So put the one you mean first.

The web interface does the whole of this for you: type the address, paste the token,
press *Find the sensors*, and it lists what is there grouped by device with the first
one ticked.

**Readings that are not readings are left out.** Home Assistant says `unavailable`
when it cannot reach a sensor and `unknown` before it has heard from one, and neither
of those is zero. A sensor whose battery has gone is worse, because Home Assistant
keeps returning the last number it had, for ever: left alone that would write one
afternoon's temperature into your database sixty times an hour. So a reading older
than `stale` seconds is not recorded. That is twice the interval unless you say
otherwise, which is right for a sensor that reports on a schedule and too short for
one that reports only when the reading changes. A soil probe that sends every fifteen
minutes wants `stale = 2000` or so.

**The units are Home Assistant's and the columns are WeeWX's.** Whatever it sends,
whether Fahrenheit or Kelvin, miles an hour or knots, inches of mercury or
hectopascals, is converted before it is recorded. Nothing has to match.

No Home Assistant to hand? `python -m user.ultimatepush --fake-homeassistant` answers
like one, with two devices and three sensors that are not reporting a number.""",
        'wrong': """Nothing is recorded and the log says the token was refused: the
token is wrong, or it was revoked, or it belongs to a user that has been deleted. Make
a new one. It is said once and then the driver stays quiet, so look at the start of the
log rather than the end.

One sensor is missing and the rest are fine. Either Home Assistant is saying
`unavailable` or `unknown` for it, or its last reading is older than `stale` allows.
Open the sensor in Home Assistant: it says at the top when it was last updated. If
that is minutes ago and the sensor is working normally, raise `stale`.

A sensor was recording and stopped, and Home Assistant still shows it. Its entity was
renamed. Home Assistant does that when you rename the device it belongs to, and the
old name then belongs to nothing; the log says which one it could not read.

Two sensors of the same kind and only one is recorded. That is deliberate. The first
of each kind fills the column, and the second arrives under a name of its own; the web
interface lists it and gives it a column when you say where it goes.

The device has no name and the station is called nothing. Rendering the list of
devices needs an administrator's token, and reading the sensors does not. Nothing else
is affected, and a token made under an administrator account fixes it.

The temperature is right and the rain is nonsense. Nearly every rain sensor reports
the total so far, and WeeWX has to be told to difference it. That is `[StdWXCalculate]`
and the driver says so at startup if it is not set.""",
    },
    'purpleair': {
        'good': """Give the sensor a fixed address in your router, under whatever the
router calls a reserved lease. A sensor whose address changes stops being found, and
the log is the only place that says so.

Sixty seconds is a sensible interval. The sensor averages over two minutes anyway, so
asking every ten buys nothing but traffic on your own network.

Set it up as an extra station. Its thermometer sits inside the housing next to
electronics that are warm and reads several degrees above the air outside; PurpleAir
correct it before showing it on their map and this driver does not, because a reading
adjusted by an amount nobody wrote down is worse than a reading that is plainly the
inside of a box. As an extra station it lands in `extraTemp`, where nothing mistakes
it for the air temperature.

Two laser counters means two of every particle reading. The second arrives in its own
columns rather than being averaged in, because two counters disagreeing is the one
thing that says a sensor is failing.

No sensor yet? `python -m user.ultimatepush --fake-purpleair` answers like one, and
the whole of the above can be tried against it first.""",
        'wrong': """Nothing is recorded and the log says the sensor cannot be reached:
the address is wrong, or has moved. `curl http://1.2.3.4/json` from this machine
settles which. It is said once and then the driver stays quiet, so look at the start
of the log rather than the end.

Something answers and it is refused: whatever is at that address is not a PurpleAir.
The usual cause is that the address now belongs to something else.

The temperature is too high: it is measured inside the housing. See above.

No temperature, humidity or pressure at all, and the particle counts are fine: the
BME280 on the board has failed or was never fitted. `hardwarediscovered` in the
answer names the chips the sensor found.""",
    },
    'ecowitt': {
        'good': """Choose a path of your own rather than leaving it at `/`. The path is
what tells this console from the next one, and it is a secret: a PASSKEY can be read
off anybody's upload and repeated, a path cannot.

Sixty seconds is a sensible upload interval. Sixteen is the shortest the app allows
and buys nothing: WeeWX writes an archive record every five minutes whatever arrives
in between.

Leave the console's own Weather Underground or Ecowitt.net upload switched on if you
use it. *Customized* is a separate upload and does not replace the others.""",
        'wrong': """Nothing arrives at all: the console is on a different network
segment, or the port is closed. `Upload Interval` seconds after saving, the log should
show something. If it shows nothing, try `curl -d 'PASSKEY=test' http://1.2.3.4:8000/`
from another machine to prove the port is open.

Uploads arrive but are refused: the driver does not know this console yet. It appears
in the web interface as a station waiting to be let in.""",
    },
    'ambient_cloud': {
        'good': """This is your own Ambient station, read back from Ambient's servers instead
of received from the console. The readings are the same ones and they land in the
same columns, because the API answers with the names the console posts.

Worth doing when the console cannot be pointed at this driver. The awnet app offers
one *Customized* server and older models offer none, so a station whose one slot is
already taken has no way to reach a driver on its own network. It is also the only
way to read a station that is not on that network at all: a second home, a
relative's garden, a club's field.

**Make two keys first.** Sign in at ambientweather.net, open your account page, and
create an application key and an API key. The application key names the program and
the API key names the account. Neither is typed into the console and neither is your
password.

Together they can read everything on the account. Keep them the way you would keep
the password. They go in `weewx.conf`, which is readable by whoever can read that
file, or in the settings file the web interface writes, which is the same. This
driver never puts them in the URL it keeps, so they are not in a log line, not on
the page that shows what arrived, and not in an error message.

**One station on the account needs nothing else.** Several needs a `mac` line saying
which, and a block without one is refused with a message listing every station it
found and what each is called, so the right address can be copied straight out of it.

Sixty seconds is a sensible interval. Ambient's servers have something new about once
a minute, and their documentation caps a key at one request a second, which nothing
here comes near.

Leave it as the main station. This is your weather station, so its temperature is the
outdoor temperature. That is the difference between it and a PurpleAir or an AirLink,
which are set up as extra stations because their thermometers are inside their own
housings.

**This and the console's *Customized* upload can both be on.** They are two ways of
reading one station and neither knows about the other, so nothing has to be switched
off to try this and nothing stops working if you go back to the other.

Everything arrives in Fahrenheit, inches and miles an hour, whatever the console's
display is set to. There is no unit setting in this API. WeeWX converts to whatever
your reports are in, so this changes nothing about what you see.

`feelsLike` and `dewPoint` are left alone. Ambient work both out and so does WeeWX,
and a column filled from two different sums is worse than one filled from either.

No account yet? `python -m user.ultimatepush --fake-ambient-cloud` answers like one,
with two stations on it so that picking one can be tried too.""",
        'wrong': """Nothing is recorded and the log says the keys were refused: one of the two
is wrong, or was deleted from the account page. Both are refused the same way, so the
message cannot say which. It is said once and then the driver stays quiet, so look at
the start of the log rather than the end.

The log says the account has several stations and the block has to say which. It
lists them with their MAC addresses; copy the one you want into a `mac` line.

The log says no station on the account has that MAC address. The station was removed
and added again, which gives it a new one, or the line has a typo. The same message
lists what is there.

The readings stop changing and nothing is refused. The console has stopped reaching
Ambient's servers, and their API keeps answering with the last thing it had. The
station's page at ambientweather.net says when it was last heard from.

The temperature is right and the rain is nonsense. Every Ambient console reports the
total so far, and WeeWX has to be told to difference it. That is `[StdWXCalculate]`
and the driver says so at startup if it is not set.""",
    },
    'ecowitt_gateway': {
        'good': """Nothing is set on the console. This is the one kind of weather
station here where the hardware is told nothing at all: the driver connects to the
gateway and asks it, so the whole of what it needs is the address.

The address is in the WSView Plus app, on the page that lists your gateway. It is
also in your router's list of what is connected, under a name that starts with the
model. Give it a fixed address there, under whatever the router calls a reserved
lease. One whose address moves stops being answered, and the log is the only place
that says so.

The port does not have to be written down. Ecowitt fixed it at 45000 and there is no
setting for it anywhere, so the address on its own is the whole line.

**This and the console's *Customized* upload can both be on.** They are two ways of
reading one box and neither knows about the other, so nothing has to be switched off
to try this and nothing stops working if you go back to the other. The readings land
in the same columns either way, which is what makes moving between them safe.

Sixty seconds is a sensible interval. The outdoor array transmits about every sixteen
seconds and the console keeps the last of what it heard, so asking faster than the
sensors send gets the same number twice.

Leave it as the main station. This is your weather station, so its temperature is the
outdoor temperature. That is the difference between it and a PurpleAir or an AirLink,
which are set up as extra stations because their thermometers are inside their own
housings.

Everything arrives in Celsius, hectopascals, millimetres and metres per second,
whatever the console's display is set to. There is no unit setting in this API and
the display's does not reach it. WeeWX converts to whatever your reports are in, so
this changes nothing about what you see.

No gateway yet? `python -m user.ultimatepush --fake-gw1000` answers like one, and
everything above can be tried against it first.""",
        'wrong': """Nothing is recorded and the log says the gateway cannot be
reached: the address is wrong, or has moved. It is said once and then the driver
stays quiet, so look at the start of the log rather than the end.

Something answers and it is refused. Whatever is at that address is not a gateway.
The usual cause is that the address now belongs to something else on the network.

There is no rain, and the console shows some. A WS90 measures rain with a piezo gauge
rather than a tipping bucket, and the gateway reports the two separately. The piezo
totals arrive in columns of their own, `drain_piezo` rather than `dayRain`, and which
of the two your console believes is a setting in the app.

A sensor is missing. The gateway reports the ones it has registered, so one the app
does not show is one it has lost rather than one this driver dropped. If the app
shows it and the readings do not appear, the log names the part of the answer that
could not be read, and that is worth reporting.""",
    },
    'ambient': {
        'good': """The awnet app calls it *Customized*, and it behaves exactly as the
Ecowitt one does. Choose a path of your own rather than leaving it at `/`.

An Ambient console and an Ecowitt console can sit on the same port. The driver tells
them apart by what they send, not by which port they came to.""",
        'wrong': """The most common cause of nothing arriving is that the app saved the
server but not the path, or added a trailing slash. The path must match exactly.""",
    },
    'wunderground': {
        'good': """Let the driver choose the `ID` and the `PASSWORD` rather than
inventing them. The ID is what tells this console from the next one, and a console
using its real Weather Underground station ID here would be identified by something
that is public.

Set both in `weewx.conf` before pointing the console at this machine. A console that
uploads with an ID nobody has heard of is refused and has to be let in by hand.

This is the only protocol here whose hardware can carry a secret, so it is the only
one where an upload can be turned away for presenting the wrong one.""",
        'wrong': """Uploads are refused with `wrong PASSWORD`: the console and the file
disagree. The comparison is exact, and a trailing space in the app counts.

Readings arrive but the wind is wrong by a factor: the console is sending the metric
dialect and `metric_wind` is set to the other unit. See below.""",
    },
    'weatherflow': {
        'good': """The hub has nothing to configure. It broadcasts to the whole local
network whether or not anybody listens, so the whole of the work is on this side.

Both machines have to be on the same network segment. A broadcast does not cross a
router, so a hub on a guest network or another VLAN never arrives.

Because it needs a socket of its own, it is not switched on by `protocols = auto`. It
has to be named, and that needs a restart.""",
        'wrong': """Nothing arrives: the hub is on another segment, or something else
already holds UDP 50222. `ss -lunp | grep 50222` says which.

Anything on the network can send to that port and nothing is authenticated, because
there is nobody to authenticate to. Use `allowed_hosts` if that matters.""",
    },
    'acurite': {
        'good': """The bridge cannot be told where to post. It goes to Chaney's servers
over plain HTTP on port 80, and there is no setting for it, so the only way to reach
it is to answer for that name on your own network.

Once it is pointed here it no longer reaches Chaney, so the Acurite app and website
stop showing the station. That is the trade, and it is not reversible without undoing
the DNS entry.

Redirect port 80 rather than running WeeWX as root.""",
        'wrong': """The bridge still reaches Chaney: the DNS entry is not being seen by
the bridge. A hosts file on the WeeWX machine does not help; the entry has to be
served by whatever the bridge uses for DNS, which is usually the router.

`tcpdump -i any -n port 80` on the WeeWX machine shows whether anything is arriving at
all.""",
    },
    'lacrosse': {
        'good': """The same as Acurite in every respect that matters: the gateway posts
to its manufacturer's server, the name is in the firmware, and only a DNS entry on
your own network can move it.

Once it is pointed here the manufacturer's app stops showing the station.""",
        'wrong': """As for Acurite. The name to redirect is different and is below.""",
    },
}


def wrap(paragraph):
    """One paragraph, wrapped the way the pages in docs/ are.

    Args:
        paragraph (str): The text, as one line.

    Returns:
        str: The same text over several lines.
    """
    return '\n'.join(textwrap.wrap(' '.join(paragraph.split()), width=88))


def keep_paragraphs(text):
    """Wrap a written block without running its paragraphs together.

    A fenced block is left exactly as written. Wrapping one folds a command somebody
    is meant to paste into a single line, and a systemd unit into something that is
    not a systemd unit.

    Args:
        text (str): One of the WRITTEN blocks.

    Returns:
        str: The same, wrapped.
    """
    out = []
    fenced = False
    for part in text.strip().split('\n\n'):
        # A fence opens and closes on its own line and a block may hold blank lines,
        # so which side of a fence a part is on has to be carried from one part to
        # the next rather than worked out from the part by itself.
        if fenced or part.lstrip().startswith('```'):
            out.append(part)
            if part.count('```') % 2:
                fenced = not fenced
            continue
        out.append(wrap(part))
    return '\n\n'.join(out)


def minimal(protocol):
    """The smallest configuration that records this protocol.

    Args:
        protocol (type): The protocol class.

    Returns:
        str: An ini block.
    """
    lines = [
        '[Station]',
        '    station_type = UltimatePush',
        '',
        '[UltimatePush]',
        '    driver = user.ultimatepush.driver',
        '    port = %s' % PORT,
    ]
    if protocol.datagram:
        lines.append('    protocols = %s' % protocol.name)
    if protocol.fetched:
        # Not a station under [[stations]]: a source under [[polling]], which is
        # both at once. There is nothing to identify, so there is nothing to say
        # twice.
        # A protocol that counts no rain is not the weather station. Both of the air
        # quality sensors here say so by setting rain_counter to None, and their
        # thermometers sit inside their own housings, so their readings belong in
        # columns of their own. A gateway's are the main ones, and telling somebody
        # to write role = extra would send their outdoor temperature to extraTemp3
        # and leave outTemp empty.
        beside_the_station = protocol.name not in IS_THE_STATION
        lines += [
            '',
            '    [[polling]]',
            '        [[[%s]]]' % FETCH_BLOCK.get(protocol.name, 'air'),
        ]
        # No address line for a protocol that has one address for everybody. Writing
        # api.ambientweather.net into the block is a line that can only be got wrong.
        if not protocol.fetch_host:
            lines.append(
                '            address = %s' % FETCH_ADDRESS.get(protocol.name, ADDRESS)
            )
        lines += [
            '            protocol = %s' % protocol.name,
        ]
        # What this one protocol cannot do without. A block missing the line that
        # says which sensors to read is a block nobody can copy.
        for key, value in protocol.fetch_settings:
            lines.append('            %s = %s' % (key, value))
        lines += [
            '            interval = 60',
        ]
        if beside_the_station:
            lines += [
                '            role = extra',
                '            channel = 3',
            ]
        return '\n'.join(lines)
    lines += ['', '    [[stations]]', '        [[[garden]]]']
    if protocol.secret_kind == 'path':
        lines.append('            path = %s' % PATH)
    elif protocol.secret_kind == 'password':
        lines.append('            id = %s' % IDENT)
        lines.append('            password = %s' % PASSWORD)
    else:
        lines.append('            id = %s' % _example_identity(protocol))
    return '\n'.join(lines)


def _example_identity(protocol):
    """What a station of this kind is called, as an example.

    Args:
        protocol (type): The protocol class.

    Returns:
        str: An identity of the right shape.
    """
    return {
        'weatherflow': 'HB-000abcde',
        'acurite': '246F28AABBCC',
        'lacrosse': '001D0A712233',
        'rtl433': 'Bresser-6in1/8455/0',
    }.get(protocol.name, 'the-identity-from-the-log')


# What the smallest configuration leaves out, and why. Keyed by what the hardware can
# be given, which is what decides whether anything has to be looked up first.
ABOUT_MINIMAL = {
    'path': "The path is the whole of it, and nothing in it has to be looked up"
    " first. You choose the path and type it into the console. The console names"
    " itself in its first upload, that name is written down, and every upload after"
    " it has to match, so a second console pointed at the same path is turned away."
    " Make the path with `python -m user.ultimatepush --secret` and put it between"
    " two slashes.",
    'password': "Both are yours to choose and neither has to be looked up first."
    " Make each with `python -m user.ultimatepush --secret`. The ID names the station"
    " and the password is checked on every upload it sends.",
    None: "The identity is the hardware's own and cannot be chosen, so this line"
    " cannot be written until the station has uploaded once. The log prints it the"
    " first time, ready to copy, and until then the station shows in the web"
    " interface as one waiting to be let in.",
    # A source that is asked has no identity question at all, so this says what it
    # does have instead: an address, and a station that is finished when it is
    # written down.
    # A receiver hears everything nearby, so the first thing it hears is as likely
    # to be next door's as your own, and nothing it hears is adopted.
    'chosen-extra': "`role = extra` puts the readings in columns of their own,"
    " which is what you want for anything that is not your main weather station.",
    'overheard': "The identity is what the sensor puts on the air and cannot be"
    " chosen, so this line cannot be written until it has been heard once. The log"
    " prints it, ready to copy. Nothing is adopted here, not even the first sensor"
    " heard: a receiver was pointed at nothing and hears over the fence, so every"
    " sensor waits to be let in and only the ones you let in are recorded. The port"
    " does not have to be written down either, unless you told rtl_433 to use a"
    " different one: `udp_port` defaults to the one in the command above.",
    'fetch': "There is nothing to identify and nothing to wait for. The driver knows"
    " which sensor answered because it knows which address it asked, so the block"
    " above is the whole of the station: it is recording from the first answer, with"
    " nothing to adopt and nothing to let in.",
    # The same, for one whose readings would fight with the weather station's.
    'fetch-extra': "`role = extra` puts its readings in columns of their own, which"
    " is what you want for a sensor whose thermometer is inside its own housing.",
    # Same again, for one that answers with more than it was asked about and has to
    # be told which part of it is the station. It gets a sentence of its own about
    # role, because what is behind one of its entities is not stated anywhere: a
    # PurpleAir is an air quality sensor and this could be a soil probe.
    # And for one that lives at an address nobody types, because the service has
    # one for everybody. Said rather than left out: a block with no address in it
    # looks incomplete to somebody who has set up every other source here.
    'fetch-fixed': "There is nothing to identify, nothing to wait for and no address"
    " to look up. This service is at one name for the whole world and the driver has"
    " it, so the block above is the whole of the station: it is recording from the"
    " first answer, with nothing to adopt and nothing to let in.",
    'chosen': "There is nothing to identify and nothing to wait for: the driver knows"
    " what answered because it knows what it asked. What it does have to be told is"
    " which sensors to read and what to authenticate itself with, which is the two"
    " lines above that no other polled source has.",
}


def _about_minimal(protocol):
    """What the smallest configuration leaves out, and why.

    Args:
        protocol (type): The protocol class.

    Returns:
        str: One paragraph.
    """
    if protocol.fetched:
        kind = 'chosen' if protocol.discovers else 'fetch'
        said = ABOUT_MINIMAL[kind]
        if protocol.fetch_host:
            said = ABOUT_MINIMAL['fetch-fixed']
        if protocol.name not in IS_THE_STATION:
            said += ' ' + ABOUT_MINIMAL[kind + '-extra']
        return said
    if protocol.overhears:
        return ABOUT_MINIMAL['overheard']
    return ABOUT_MINIMAL[protocol.secret_kind]


def console(protocol):
    """What to put into the console, if anything.

    Args:
        protocol (type): The protocol class.

    Returns:
        list[str]: Markdown lines.
    """
    if not protocol.settings:
        return []
    fill = {
        'address': ADDRESS,
        'port': PORT,
        'path': PATH,
        'ident': IDENT,
        'password': PASSWORD,
    }
    lines = ['## What to put into the console', '', '| | |', '|---|---|']
    for label, value in protocol.settings:
        lines.append('| %s | `%s` |' % (label, value % fill))
    lines.append('')
    return lines


def own_options(protocol):
    """The options that belong to this protocol alone.

    Args:
        protocol (type): The protocol class.

    Returns:
        list[str]: Markdown lines, empty when it has none.
    """
    mine = {
        'wunderground': [
            (
                'password',
                "Refuse uploads that do not present this as `PASSWORD`. A station "
                "with a password of its own uses that instead; this covers the ones "
                "that have none. Default is none.",
            ),
            (
                'metric_wind',
                "Whether the metric dialect's wind is kilometres per hour or metres "
                "per second, which cannot be told from a payload. One of `kph` or "
                "`mps`. Default is `kph`.",
            ),
        ],
        'weatherflow': [
            (
                'udp_port',
                "The port to listen for broadcasts on. There is no reason to change "
                "it. Default is `50222`.",
            ),
        ],
        'homeassistant': [
            (
                'stale',
                "How old a reading may be, in seconds, before it stops counting as "
                "a reading. Twice the interval by default. A sensor whose battery "
                "has gone keeps returning its last value for ever, and without this "
                "that value would be recorded as though it were fresh. Raise it for "
                "a sensor that reports only when its reading changes.",
            ),
        ],
    }.get(protocol.name)
    if not mine:
        return [
            '## Options of its own',
            '',
            wrap(
                'None. Everything that applies to this protocol applies to all of'
                ' them, and is in [Configuration](Configuration.md#driver-options).'
            ),
            '',
        ]
    # Where an option goes depends on what kind of protocol it is. A polled
    # source's options are its own block's, because a source is its own station and
    # everything about it is written in one place.
    where = (
        'go in the `[[polling]]` block that sets the source up'
        if protocol.fetched
        else 'go in the `[UltimatePush]` section'
    )
    lines = [
        '## Options of its own',
        '',
        wrap(
            'These belong to this protocol alone and %s. Everything else that'
            ' applies is in [Configuration](Configuration.md#driver-options).' % where
        ),
        '',
    ]
    for key, said in mine:
        lines += ['#### %s' % key, '', wrap(said), '']
    return lines


def page(protocol):
    """One protocol's page.

    Args:
        protocol (type): The protocol class.

    Returns:
        str: The whole page.
    """
    written = WRITTEN[protocol.name]
    if protocol.fetched:
        # Not in it and not missing from it: 'auto' is the list of protocols to
        # listen for, and nothing arrives from this one on its own.
        in_auto = (
            'no, and it does not need to be: naming it under `[[polling]]` '
            'is what switches it on'
        )
    elif protocol.datagram:
        in_auto = 'no, it has to be named'
    else:
        in_auto = 'yes'
    early = (
        'Nothing to name: it is asked'
        if protocol.fetched
        else (
            'Yes'
            if protocol.secret_kind in ('path', 'password')
            else 'No, it is adopted'
        )
    )
    lines = [
        '# %s' % protocol.label,
        '',
        wrap(
            # Not every protocol is a make of hardware. One that reads whatever
            # another program on the network has is a source, and calling it
            # hardware on its own page is the first thing a reader would query.
            'Setting up %s by hand, in `weewx.conf`.' % protocol.label
            if protocol.discovers
            else 'Setting up %s hardware by hand, in `weewx.conf`.' % protocol.label
        ),
        '',
        wrap(
            'Generated by `tools/build_protocols.py`. What each protocol needs is'
            ' written in that tool; what it is called and what goes into the console'
            ' comes from the code. Do not edit by hand.'
        ),
        '',
        INTERFACE,
        '## What it is',
        '',
        wrap(protocol.hardware),
        '',
        '| | |',
        '|---|---|',
        '| In `protocols = auto` | %s |' % in_auto,
    ]
    if protocol.fetched:
        lines += [
            '| Named by | the name you give the block |',
            '| Recording from | its first answer |',
        ]
    elif protocol.overhears:
        # A receiver hears over the fence, so nothing it hears is taken for this
        # installation's own and the usual sentence about adoption would be wrong.
        lines += [
            '| Named by | its `model`, `id` and `channel` together |',
            '| Recording from | whichever sensors you let in |',
        ]
    else:
        lines += [
            '| Named by | its `%s` |' % protocol.identity[0],
            '| Can be set up before it uploads | %s |' % early,
        ]
    lines += [
        '',
        '## The smallest configuration that works',
        '',
        '```ini',
        minimal(protocol),
        '```',
        '',
        wrap(_about_minimal(protocol)),
        '',
    ]
    lines += console(protocol)
    if protocol.notes:
        lines += ['## What else it takes', '']
        fill = {'address': ADDRESS, 'port': PORT, 'path': PATH}
        for note in protocol.notes:
            said = note % fill
            if note.startswith('    '):
                # An indented note is a thing to paste, not a thing to read.
                lines += ['```', said.replace('    ', '', 1), '```', '']
            else:
                lines += [wrap(said), '']
    lines += own_options(protocol)
    lines += ['## Worth knowing', '', keep_paragraphs(written['good']), '']
    lines += ['## When nothing arrives', '', keep_paragraphs(written['wrong']), '']
    lines += [
        '## More than one station',
        '',
        wrap(
            'This is one station among however many others. Which of them fills'
            ' `outTemp`, and where the rest of their readings go, is in'
            ' [Several stations](Several-stations.md).'
        ),
        '',
    ]
    return '\n'.join(lines)


def main(argv=None):
    """Run it from the command line.

    Args:
        argv (list | None): Arguments, without the program name.

    Returns:
        int: An exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument(
        '--docs', default=os.path.join(HERE, 'docs'), help='where to write the pages'
    )
    args = parser.parse_args(argv)

    from ultimatepush import protocols

    written = []
    for protocol in protocols.registry():
        # Hyphens, because that is how every other page in docs/ is named and
        # the wiki turns a file name into a link.
        page_name = protocol.name.capitalize().replace('_', '-')
        path = os.path.join(args.docs, 'Protocol-%s.md' % page_name)
        with io.open(path, 'w', encoding='utf-8', newline='\n') as handle:
            handle.write(page(protocol))
        written.append(protocol.name)
    print('%d protocol pages: %s' % (len(written), ', '.join(written)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
