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

## Where the field names come from

The catalogs are data, and half of them are generated from sources that track real
hardware. See [Catalogs](Catalogs.md).
