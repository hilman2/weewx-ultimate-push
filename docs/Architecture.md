# Architecture

How the driver is put together, and why it is in these pieces. Nobody needs this page
to run a station. It is for reading the code, and for deciding where a change belongs.

The path a single reading takes is in [Field map](Field-map.md). What each protocol
carries is in [Protocols](Protocols.md).

## Layout

```
bin/user/ultimatepush/
    transport.py   text in, name and value pairs out. No sockets, no WeeWX.
    protocols/     one module per protocol: how to recognise it, what it answers,
                   what names its station, which catalog reads it.
    catalogs/      one module per protocol, and nothing in any of them but data.
    infer.py       what to do with a field a catalog does not cover.
    mapping.py     the three above, combined into a packet. Still no WeeWX.
    columns.py     which database columns a packet needs.
    consoles.py    which stations this driver answers to.
    roles.py       which station may fill which field: main, extra, and channels.
    owners.py      which station owns which archive column.
    server.py      an answer per protocol, and several listeners behind one iterator.
    activity.py    what each station has been doing lately. Bounded, in memory.
    report.py      the report left behind when a station sends something unplaceable.
    overrides.py   the settings the web interface may change, in a file of its own.
    checklist.py   what still stands between the current state and a working station.
    admin.py       the web interface: routing and the JSON API.
    page.py        the web interface, as one self-contained page.
    hardware.py    other WeeWX drivers, hosted: a thread each, and the rules
                   a device that is read rather than waited for needs.
    driver.py      the WeeWX end: loop packets, unit groups, shutdown.
    __main__.py    the diagnostic command.
bin/user/listener.py   WeeWX's own listener, bundled for WeeWX older than 5.6.
tools/                 catalog and reference generators, and the docstring type
                       checker CI runs.
tests/                 pytest, with captured payloads in tests/fixtures.
```

Everything except `driver.py`, `server.py`, `admin.py` and `__main__.py` runs without
WeeWX installed. This is what allows the tests to work from a captured payload rather
than from mocks, and it is worth preserving: a catalog is data, and data should be
checkable without a weather station.

## Two questions, not one

Detection works on protocols, mapping works on dialects, and they are separate
questions. [Protocols](Protocols.md#protocols-and-dialects) has what the two terms mean.

The consequence for the code is that the driver keeps one mapper per dialect it has
actually seen, rather than one per protocol. Inference learned from `tempf` and
`soiltemp2f` has no business being applied to `outtemp` and `absbaro`.

## The listening socket

The socket, the threading, the shutdown, the body limits, IPv6 and the token check all
come from `weewx.listener` in the WeeWX core. The driver contributes no socket code of
its own.

`bin/user/listener.py` is a copy of that module, byte for byte, for installations
running WeeWX older than 5.6. A test compares the two when WeeWX has one, so the copy
cannot drift. Do not edit it; when the core carries the listener, the driver picks that
up on its own and the copy can go.

That is also why `server.py` exists. The core listener sets one content type for the
whole listener, and six protocols want different ones on the same port. So the answer
carries its own content type, kept per thread, in a subclass here rather than in a
change to a file that has to stay identical. `Fan` is there for the same reason: a
driver iterates one thing, and a station with a WeatherFlow hub and an Ecowitt gateway
needs two sockets.

## Hosted drivers

`hardware.py` runs other WeeWX drivers inside this one. It loads them the way the engine
does, so a driver needs no changes and its own section is read by its own loader. What
is not obvious is why it is more than a queue, and that is four things.

**A device is one at a time.** A Vantage streaming LOOP packets cannot answer DMPAFT: it
is one serial port. So a child pulls loop packets only while it has been told to, and is
told to stop before the engine asks for archive records. The stop message reaches the
child between packets, which means it usually arrives while the child is inside a read,
and Python cannot interrupt a read. So the stop takes effect when the reading arrives,
and the engine waits for that, but only for the child it is about to ask.

**Closing comes from the calling thread.** A child waiting for hardware is not reading
its command queue. `closePort` is what WeeWX itself uses to wake such a driver, so it is
called directly rather than sent through the queue, which would otherwise cost the full
join for exactly the drivers this project is about.

**A driver may also be a service.** Of the thirteen drivers WeeWX ships, the Vantage's
loader returns a `VantageService`, which binds to NEW_LOOP_PACKET and writes the archive
period's highest gust into the packet it is given. Bound to the real engine in a stream
carrying more than one station, it would raise its gust from another console's wind and
overwrite the gust that console measured. So a child is handed a `Facade` instead of the
engine, and its bindings are called only for its own packets, on the engine's thread,
immediately before the packet is yielded. That is the thread and the moment they would
run on without this driver in the way.

**Two questions about who is in charge.** The archive station supplies archive records
and the clock. The main station, in the sense `roles.py` means, fills the plain columns.
Usually one device; not necessarily. A Vantage with a logger can carry the archive while
a console with more sensors is the main station.

What is deliberately not there: a hosted driver's packets get no catalog, no inference
and no mapper, because its fields are WeeWX's already. They do go through `roles.py` and
`owners.py`, which is the whole reason for hosting a driver here rather than beside this
one.

## Where the field names come from

The catalogs are data, and half of them are generated from sources that track real
hardware. See [Catalogs](Catalogs.md).
