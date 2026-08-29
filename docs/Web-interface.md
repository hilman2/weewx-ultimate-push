# The web interface

A page that shows what each station sends, keeps the most recent raw uploads, and lets
you place a field without editing a file or restarting WeeWX.

The interface is enabled by the installer, on port 8080, with a token generated at
install time that differs on every machine. No setup is required.

The driver logs the full address at startup:

```
INFO user.ultimatepush.driver: The web interface is at
http://192.168.1.50:8080/?token=kJ7mQx2vRt9w
```

To retrieve the address later:

```
python -m user.ultimatepush --url
```

The address contains the token, so treat the log as you would treat `weewx.conf`.

In a container, the address reported is the container's own, because that is where the
process runs. Use the address of the host and whichever port the container publishes.

To close the port:

```ini
[UltimatePush]
    [[web]]
        enable = false
```

## A typical installation

A Raspberry Pi or similar on a private network, with no proxy in front of it.

```
   Console                              Raspberry Pi 192.168.1.50
      |                                 WeeWX, running as user weewx
      |  POST /a8f3c1e0/report          +-------------------------+
      +-------------------------------->|  :8000   the readings   |--> weewx.sdb
                    every 16 to 60 s    |                         |
   Laptop, phone                        |  :8080   this page      |
      |  GET :8080/?token=...           +-------------------------+
      +-------------------------------->
```

Both ports are above 1024, so neither requires root.

```
weectl extension install https://github.com/hilman2/weewx-ultimate-push/releases/latest/download/weewx-ultimate-push-0.12.4.zip
sudo systemctl restart weewx
```

Then point the console at `192.168.1.50:8000` and open the address from the log.

### Where files are placed

| | |
|---|---|
| The driver | `/etc/weewx/bin/user/ultimatepush/` |
| `weewx.conf` | `/etc/weewx/`, owned by root |
| Settings written by this page | `/var/lib/weewx/ultimate-push-web.conf` |
| Which consoles are accepted | in the database, with a file beside it as a fallback |

WeeWX runs as the user `weewx` and `/etc/weewx` is owned by root. This is why the
interface writes to `/var/lib/weewx` rather than to `weewx.conf`.

### trust_proxy

Leave this off unless there is a proxy in front. With it on and no proxy present, any
client can supply an address of its choosing in `X-Forwarded-For`, and the rate limiter
described below would count invented addresses instead of the real one.

## What the interface is for

Placing a field is a decision only the person who installed the sensor can make. A WN34
reports on `tf_ch1` whether it is a spike in a raised bed or a lead in a pool. The
driver does not guess, because two sensors in one column cannot be separated afterwards.

Without the interface, that decision is made by reading a log entry, adding a line to
`weewx.conf`, restarting WeeWX, waiting for an upload and reading the log again. It
also omits the information that matters most: whether the column is already in use.

The interface shows, for each raw field, what arrived, its last value, where it would be
written, whether a column exists, and how many earlier values that column holds.

## The checklist

Until a station is recording properly, the page opens on a checklist of what still
stands in the way. It has no step numbers and no fixed order: it determines what is
true each time it is loaded.

| | |
|---|---|
| Your hardware is not pointing here | Enter a name and select the hardware. For hardware whose path is yours to choose, the driver generates one and displays the settings to enter. The page detects the first upload without being reloaded. |
| Something is being turned away | A console the driver does not know. One click accepts it. |
| A field is waiting for you | Placements only you can make. |
| Readings have nowhere of their own to go | Which readings were dropped, which station sent them, and which station holds the column. |
| A reading has no column | With the `weectl` commands. |
| The station does not know where it is | `[Station]` in `weewx.conf`, which this driver cannot write, so the block to paste is displayed. |

Once everything is resolved the checklist stops asking and remains as a status page. A
console that appears a year later puts its step back at the top.

## The tabs

### Setup

The checklist above, and the form for setting up a station. Selecting a role is part of
that form: the first station is the main station, and every station after it is offered
as an extra sensor. See [Stations](Stations.md).

### Stations

Every station the driver knows, including stations set up but never heard from, and
stations declared in `weewx.conf`. Each entry is collapsed and opens to show:

- The console settings for that station, with its own upload path. The checklist shows
  these once and then stops; a console that has to be set up again a year later needs
  them again.
- Which archive columns the station fills, and a button to release them.
- The station's name, role and channel, and a button to remove it.

Stations declared in `weewx.conf` are shown but not editable, and say so. The console
adopted as the first one ever heard is shown but has no settings to change, because it
is named in no file.

### Fields

Every station at once, one block each, collapsible. Not one page per station: the
question is not what a given station sends, it is which station fills `outTemp`, and
that answer is spread across two pages if each station has its own.

The selector in each row offers the WeeWX fields that measure the same thing first,
then everything else, then `nowhere`, then a field of your own. Numbered families run
to 16, past the end of the standard schema, so `extraTemp12` is offered even though no
database has a column for it. Each option states what it costs: `new column`, or the
station and reading that already hold it.

One WeeWX field takes one reading. Selecting a field that is taken reports who holds it
and changes nothing until you confirm, after which the reading that held it is placed
`nowhere` rather than left to take turns in the column.

A field with no column has a button in the row that creates it. A selection takes effect
on the next upload.

### Raw uploads

The last twenty uploads per station, newest first, with a copy button. Anything that
names the station is redacted, so they are safe to attach to an issue. This replaces
enabling `log_raw` and watching the log.

### Database columns

Which readings have nowhere to be written, with the `weectl database add-column`
commands, and the same check the Fields tab uses. The archive table is also checked for
what it already holds. That check is one pass over the table, so it runs when the page
is first opened rather than on every load.

## Where the settings are written

Not to `weewx.conf`, for three reasons that concern the file rather than the interface.
WeeWX is running from it, so a change written there has no effect until a restart, and a
driver cannot restart the engine it is part of. Under a package installation the file is
owned by root while the driver runs as the `weewx` user. And it is your file, with your
comments in it.

Settings the interface changes are written to `ultimate-push-web.conf`, beside the
console list, in the same format. They are read on the next upload, without a restart.

Anything that does require a restart — the port, `protocols`, `path` — is displayed as a
block to copy rather than written.

### Which file takes precedence

A placement written by the interface takes precedence over `[[field_map_extensions]]` in
`weewx.conf`. Each row states where the value it is showing came from.

A station declared under `[[stations]]` is different. Its field map is part of that
declaration, and the interface displays it and declines to change it, as it does the
station's name, role and channel.

## Access control

The interface is protected by a token, a rate limiter, and the address the socket is
bound to.

This is a weather station rather than a bank. The intent is that a stray scanner, a
curious guest and a mistyped address all come to nothing, and that you can see that it
happened.

### The rate limiter

Ten wrong tokens from one address within five minutes, and that address stops receiving
answers: not an error, an empty reply. A correct token does not help either, because the
check is not reached.

The limit is not a fixed penalty. Attempts fall out of the window and the address is
answered again. A correct token clears the count, so an address that mistyped the token
four times and then supplied it correctly is not left one attempt from a lockout.

One address exceeding the limit never affects another, or anyone on the network could
lock you out of your own station.

```ini
    [[web]]
        tries = 10
        window = 300
```

The page reports what has been attempted, so that it is not only in the log:

```
3 request(s) with the wrong token.
192.168.1.99: 3 wrong, last 2m ago
```

That record survives a successful login, because reading it requires supplying the
correct token first.

### What the token is worth

The interface serves plain HTTP. The token is in the URL on the first request, so it
appears in browser history and in the logs of anything in between. On a private network
that is a bounded exposure; across the internet it requires TLS in front.

Ten random characters is approximately sixty bits. At ten attempts per five minutes,
exhausting that takes longer than the remaining lifetime of the sun. A token chosen by
hand is weaker, and the rate limiter is what makes even that impractical from outside.
The driver refuses to start with fewer than ten characters.

The token is checked by the driver rather than by the listener. The listener would check
it first, which sounds preferable but is not: its check runs before any of this driver's
code, so a wrong token would be answered and forgotten, and there would be nothing to
count.

Anyone with the token can change the field map. There are no roles.

A page on another site cannot drive the API, which takes JSON with a token header. A
browser will not send that cross-origin without a preflight, and the listener answers no
`OPTIONS` request.

### One secret, not two

If you put a reverse proxy in front, there is no reason to give it a secret path as
well. Both are strings in the same address and both appear in the same browser history.
Use a plain path and let the token do the work; it is the one the rate limiter counts
against.

### On an untrusted network

Bind the interface to localhost and reach it through a tunnel:

```ini
    [[web]]
        enable = true
        port = 8080
        address = localhost
        token = ...
```

```
ssh -L 8080:localhost:8080 you@your-weewx-machine
```

Then open `http://localhost:8080/?token=...` locally.

Alternatively, put a reverse proxy with a certificate in front and let it handle TLS
and, if required, a second layer of authentication.

The interface can also be restricted to known addresses:

```ini
        allowed_hosts = 192.168.1.20, 192.168.1.21
```

## Why the interface uses a second port

The listener can require a token, and that check runs before anything else. It would
then apply to the readings as well, and most of this hardware cannot send a token. One
port cannot both require a token and accept a console that has none.

The interface therefore has its own listener, its own port and the token. The data port
is unchanged.

## Options

These are a subsection of `[UltimatePush]`.

#### enable

Whether to open the port. Set to `true` by the installer. Default is `true`.

#### port

Which port the interface listens on. Default is `8080`.

#### address

Bind to one address. `localhost` makes the interface unreachable from the network.
Default is every interface.

#### token

Required, at least 10 characters. Generated by the installer. Change it here and
restart. No default.

#### tries

How many wrong tokens from one address before it stops being answered. Default is `10`.

#### window

Over how many seconds those attempts are counted, and how long the silence lasts.
Default is `300`.

#### allowed_hosts

Comma-separated addresses to accept requests from. Default is anywhere.

#### trust_proxy

Take the client address from `X-Forwarded-For`. Use only with a proxy you control.
Default is `false`.

#### override_file

Where the settings the interface writes are kept. Default is beside the console list.

## What the interface does not do

**Restart WeeWX.** A driver cannot restart the engine it is part of.

**Run `weectl`.** Adding a column rewrites the archive table. The commands are
displayed; running them is yours.

**Show anything from before the driver started.** The activity it shows is held in
memory and is lost on restart. The database holds the readings; this holds what happened
to them on the way in.

**Change the port, the protocols or the path.** Those define the socket, which is
created once at startup. The interface displays the block to paste.
