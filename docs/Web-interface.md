# The web interface

A page that shows what each station is sending, keeps the last few raw uploads, and
lets you place a field without editing a file or restarting anything.

**It is already on.** Installing the extension switches it on, on port 8080, with a
token made at install time that is different on every machine. There is nothing to
set up.

The driver prints the whole address to the log when it starts:

```
INFO user.ultimatepush.driver: The web interface is at
http://192.168.1.50:8080/?token=kJ7mQx2vRt9w
```

Or ask for it again later:

```
python -m user.ultimatepush --url
```

That address holds the token, so treat the log the way you treat `weewx.conf`.

In a container the address it reports is the container's own, because that is where the
process is. Use the address of the host, and whichever port the container publishes.

To close the port:

```ini
[UltimatePush]
    [[web]]
        enable = false
```

## The normal case: a Pi or a NUC on your own network

Nothing in front of it, no proxy, no Docker.

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

Both ports are above 1024, so nothing here needs root.

The whole of it:

```
weectl extension install https://github.com/hilman2/weewx-ultimate-push/releases/latest/download/weewx-ultimate-push-0.8.0.zip
sudo systemctl restart weewx
```

Then point the console at `192.168.1.50:8000`, and open the address the log printed.

### Where things land

| | |
|---|---|
| The driver | `/etc/weewx/bin/user/ultimatepush/` |
| `weewx.conf` | `/etc/weewx/`, owned by root |
| What this page writes | `/var/lib/weewx/ultimate-push-web.conf` |
| Which consoles are accepted | in the database, with a file beside it as a fallback |

WeeWX runs as the user `weewx` and `/etc/weewx` belongs to root. That is exactly why
this page writes to `/var/lib/weewx` and not into `weewx.conf`: there, it could not.

### Leave `trust_proxy` alone

It is off, and on a Pi with nothing in front of it that is what you want. Turned on
without a proxy, anybody could put an address of their choosing in `X-Forwarded-For`
and the doorman below would count invented addresses instead of theirs.

## What it is for

Placing a field is a decision only the person who installed the sensor can make. A
WN34 reports on `tf_ch1` whether it is a spike in a bed or a lead in a pool, and the
driver will not guess, because two sensors in one column cannot be separated
afterwards.

Today that decision is made like this: read a log line, paste a line into
`weewx.conf`, restart WeeWX, wait for an upload, read the log again. That is a poor
loop for something irreversible, and it leaves out the one thing you actually want to
know before deciding: whether the column you are about to use already holds somebody
else's readings.

The page shows that. Per raw field: what arrived, its last value, where it would go,
whether a column exists, and how many earlier values that column already holds.

## What you see first

Until a station is recording properly, the page opens on a checklist of what is still
in the way. It is not a wizard: it has no step number, it works out what is true every
time you look, and it is right whether this is your first visit or your hundredth.

Five things can be in the way:

| | |
|---|---|
| Your hardware is not pointing here | Pick your make, and it shows exactly what to type: the address of this machine, the port, the path, the protocol name. It waits and notices the first upload by itself. |
| Something is being turned away | A console this driver does not know. One click lets it in. |
| A field is waiting for you | The placements only you can make. |
| A reading has no column | With the `weectl` commands. |
| The station does not know where it is | `[Station]` in `weewx.conf`, which this driver cannot write, so it shows the block to paste. |

Once everything is answered it stops asking and stays as a health page. A second console
that turns up next year puts its step back at the top.

## The four things it shows

**Setup.** The checklist above.

**Stations.** Everything that has uploaded since the driver started, with its
protocol, which catalog its uploads are read with, how many fields it sends and when
it was last heard from. Underneath, the stations being refused.

**Fields.** The table above. Editing the WeeWX field in a row writes it and it takes
effect on the next upload.

**Raw uploads.** The last twenty per station, newest first, with a copy button.
Everything that names the station is replaced, so they are safe to paste into an
issue. This replaces turning on `log_raw` and waiting with a grep running.

**Database columns.** Which readings have nowhere to live, with the `weectl database
add-column` commands. It does not run them: adding a column rewrites the table, and
that is a moment to have a backup rather than a button. There is also a check of what
the archive table already holds, which is one pass over it, so it happens when you ask
rather than on every page load.

## Where the settings go

Not into `weewx.conf`. Three reasons, all about the file rather than the interface:

WeeWX is running from it, so a change written there does nothing until a restart, and
a driver cannot restart the engine it is part of. Under a package installation the
file belongs to root and the driver runs as the weewx user. And it is your file, with
your comments in it.

So what the interface changes goes in `ultimate-push-web.conf`, beside the console
list, in the same format. It is read on the next upload. Nothing restarts.

Everything that does need a restart, the port, `protocols`, `path`, the interface
shows as a block to copy rather than writing it.

### One owner per setting

**A field named in `weewx.conf` is never touched by the interface.** It shows it, says
it is set there, and declines to change it.

That rule is not politeness. Two files with an answer each would mean one of them is
quietly ignored, and which one would depend on the order they happened to be read in.
One owner per setting, and no setting that stops meaning what the file says it means.

The same goes for a station named under `[[stations]]` in `weewx.conf`: its field map
lives there, and the interface will not write one for it.

## What protects it, and what does not

A token, a doorman that stops answering an address which keeps getting it wrong, and
where the socket is bound. That is all, and it is worth being plain about what it is
worth.

This is a weather station. The point is not to withstand somebody determined who has
your address. It is that a stray scanner, a curious guest and a typo all come to
nothing, and that you can see it happened.

### The doorman

Ten wrong tokens from one address inside five minutes and that address stops being
answered at all. Not an error, not a hint: an empty reply. The right token does not
help either, because the black hole does not check one, which is also what stops it
costing anything.

It is not a punishment to be served out. The tries fall out of the window and the
address is answered again. And a right token clears the tally, so somebody who
mistyped it four times and then pasted it properly is not left one try from a lockout.

One address getting it wrong never shuts out another. Otherwise anybody on the network
could lock you out of your own station.

```ini
    [[web]]
        tries = 10
        window = 300
```

The page shows what has been knocking, so it is not only in the log:

    3 request(s) with the wrong token.
    192.168.1.99: 3 wrong, last 2m ago

That record survives your own successful login. It has to: reading it means getting
the token right first, and if success cleared it there would never be anything to see.

### The rest

**It is HTTP.** The token is in the URL on the first request, so it is in the browser
history and in the logs of anything in between. On a network you trust that is a
bounded exposure. Across the internet it is not acceptable without TLS in front.

**Ten random characters is about sixty bits.** At ten guesses per five minutes, working
through that takes longer than the sun has left. A token you thought up rather than
generated is a different sum, and the doorman is what makes even that impractical from
outside. The driver refuses to start with fewer than ten characters, because an
interface that can change the field map should not be open because somebody left the
setting blank.

**The token is checked by the driver, not by the listener.** The listener would do it
first, which sounds better and is not: its check runs before anything of ours, so a
wrong token would be answered and forgotten and there would be nothing to count.

**Anybody with the token can change the field map.** There are no roles.

**A page on another site cannot drive it.** The API takes JSON with a token header,
which a browser will not send cross-origin without a preflight, and the listener
answers no `OPTIONS`. Worth having, and not something to lean on.

### One secret, not two

The token is the secret. If you put a reverse proxy in front, there is no reason to
give it a secret path as well: both are strings in the same address, both end up in
the same browser history, and two of the same thing is not twice the protection. Use a
plain path and let the token do the work. It is the one the doorman counts against.

### On a network you do not trust

Bind it to localhost and reach it through a tunnel:

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

Then `http://localhost:8080/?token=...` on your own machine.

Or put a reverse proxy with a certificate in front, and let it do the TLS and, if you
want one, a second layer of authentication.

You can also narrow it to known addresses:

```ini
        allowed_hosts = 192.168.1.20, 192.168.1.21
```

## Why it is a second port

The listener can require a token, and that check happens before anything else. But it
would then apply to the readings as well, and most of this hardware cannot send a
token at all. One port cannot both demand a token and accept a console that has none.

So the interface gets its own listener, its own port, and the token. The data port is
unchanged.

## Options

| Option | Default | Meaning |
|---|---|---|
| `enable` | `true` | Whether to open the port at all. Set by the installer. |
| `port` | 8080 | Which port. |
| `address` | every interface | Bind to one address. `localhost` makes it unreachable from the network. |
| `token` | made at install | Required. At least 10 characters. Change it here and restart. |
| `tries` | 10 | Wrong tokens from one address before it stops being answered. |
| `window` | 300 | Over how many seconds, and how long the silence lasts. |
| `allowed_hosts` | anywhere | Comma-separated addresses to accept from. |
| `trust_proxy` | `false` | Take the client address from `X-Forwarded-For`. Only with a proxy you control. |
| `override_file` | beside the console list | Where the settings the interface writes are kept. |

## What it does not do

**Restart WeeWX.** It cannot, and a driver that tried would be a driver restarting the
engine it is part of.

**Run `weectl`.** Adding a column rewrites the archive table. The commands are printed
and running them is yours.

**Show anything from before the driver started.** The activity it shows is held in
memory and is gone on restart. The database has the readings; this has what happened
to them on the way in.

**Change the port, the protocols or the path.** Those are the socket, and the socket
is made once at startup. The interface shows the block to paste.
