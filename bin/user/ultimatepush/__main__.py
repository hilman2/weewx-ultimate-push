#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""Listen once, and say what the hardware is sending.

Run this before wiring anything up, or when a sensor is missing from the reports:

    python -m user.ultimatepush --port 8000

It waits for one upload, works out which protocol sent it, then prints what arrived,
what the driver could not place, the commands that would give the readings somewhere
to live, and which of those fields already hold somebody else's history. Nothing is
changed, and WeeWX does not have to be stopped as long as this uses a different port.

Every protocol the driver knows is listened for, and each one is answered the way its
hardware expects, so a console will not decide the upload failed and stop.
"""

import argparse
import logging
import sys
import time

from . import VERSION, columns, infer, protocols, server, transport
from .mapping import Mapper

try:
    from weewx.listener import HTTPListener
except ImportError:
    from user.listener import HTTPListener


def main(argv=None):
    """Run the diagnostic command.

    Args:
        argv (list): Command line arguments, without the program name. Defaults to
            what was actually passed on the command line.

    Returns:
        int: An exit status, 0 when there was nothing to complain about.
    """
    parser = argparse.ArgumentParser(prog='python -m user.ultimatepush',
                                     description=__doc__)
    parser.add_argument('--port', default=8000, help="Port to listen on. Default 8000.")
    parser.add_argument('--address', default='', help="Address to bind to.")
    parser.add_argument('--path', help="Accept this path only.")
    parser.add_argument('--samples', type=int, default=1,
                        help="How many uploads to wait for. Default 1.")
    parser.add_argument('--timeout', type=int, default=300,
                        help="Seconds to wait before giving up. Default 300.")
    parser.add_argument('--config', default='/etc/weewx/weewx.conf',
                        help="Path to weewx.conf, for the database check and for the "
                             "commands printed at the end.")
    parser.add_argument('--infer-unknown', default='all',
                        choices=['off', 'series', 'all'],
                        help="Default 'all' here, so that everything gets a proposal.")
    parser.add_argument('--no-database', action='store_true',
                        help="Skip looking at the database. Faster, and one section "
                             "less when setting up from scratch.")
    parser.add_argument('--url', action='store_true',
                        help="Print the address of the web interface and stop. It is "
                             "in the log at startup too, but this saves looking.")
    args = parser.parse_args(argv)

    if args.url:
        return _say_url(args.config)

    logging.basicConfig(level=logging.WARNING, format='%(message)s')
    known = protocols.posting()
    print("weewx-ultimate-push %s. Listening on %s:%s for %s. Point the station here."
          % (VERSION, args.address or '*', args.port,
             ', '.join(p.name for p in known)))

    def answer(request):
        """The reply the sender is waiting for, worked out from what it sent.

        Args:
            request: The upload, as the listener hands it over.

        Returns:
            tuple: (body, content_type), which is what this hardware's firmware
            waits for before it counts the upload as delivered.
        """
        try:
            protocol = protocols.detect(request, transport.parse(request.text), known)
        except Exception:
            return '', 'text/plain'
        if protocol is None:
            return '', 'text/plain'
        return protocol.answer, protocol.content_type

    mappers = {}
    packet = {}
    guesses = []
    seen = 0
    last = None

    listener = server.http_listener(HTTPListener, answer, port=args.port,
                                    address=args.address, path=args.path)
    try:
        while seen < args.samples:
            request = listener.get(timeout=args.timeout)
            if request is None:
                print("Nothing arrived in %d seconds." % args.timeout, file=sys.stderr)
                return 1
            print("\n%s" % request)
            raw = transport.parse(request.text)
            protocol = protocols.detect(request, raw, known)
            if protocol is None:
                print("  Nothing in it says which protocol this is, so there is no "
                      "catalog to\n  read it with. Not counted.")
                continue
            dialect = protocol.dialect(raw)
            print("  %s, read with the '%s' catalog"
                  % (protocol.label, dialect.name))
            mapper = mappers.get(dialect.name)
            if mapper is None:
                mapper = mappers[dialect.name] = Mapper(
                    dialect, infer_unknown=args.infer_unknown)
            mapper.settle(protocol.settled_contested(raw))
            one, fresh = mapper.to_packet(protocol.readings(request, raw))
            packet.update(one)
            guesses.extend(fresh)
            last = mapper
            seen += 1
    finally:
        listener.close()

    if last is None:
        print("Nothing that arrived could be read.", file=sys.stderr)
        return 1

    _report(packet, guesses, last, args.config)
    for mapper in mappers.values():
        _decisions(mapper)
    if not args.no_database:
        _check_history(packet, args.config)
    return 0


def _say_url(config_path):
    """Print where the web interface is, or why there is nowhere to go.

    The address is in the log at startup, but a log is a poor place to keep something
    you want to open next week.

    Args:
        config_path (str): The path to weewx.conf.

    Returns:
        int: An exit status.
    """
    try:
        import configobj
        section = configobj.ConfigObj(config_path, encoding='utf-8',
                                      interpolation=False)['UltimatePush']
    except Exception as e:
        print("Cannot read %s: %s" % (config_path, e), file=sys.stderr)
        return 1

    web = section.get('web') or {}
    if str(web.get('enable', 'false')).lower() not in ('true', 'yes', '1'):
        print("The web interface is switched off. Set 'enable = true' under "
              "[UltimatePush] [[web]] in %s, then restart WeeWX." % config_path)
        return 1
    token = str(web.get('token', '')).strip()
    if not token:
        print("The web interface has no token, so the driver will not start it. Make "
              "one with:\n"
              "    python -c \"import secrets; print(secrets.token_urlsafe(12))\"",
              file=sys.stderr)
        return 1

    from . import admin
    print(admin.url(web.get('address', ''), int(web.get('port', 8080)), token))
    return 0


def _decisions(mapper):
    """Print the configuration block for everything that is waiting on the user.

    Args:
        mapper (Mapper): The mapper that read the upload, which is holding what it
            would not place on its own.
    """
    waiting = sorted(mapper.warned & set(mapper.undecided))
    if not waiting:
        return
    print("\n%d fields are not being written, because where they go is your call and"
          "\nnot the hardware's. Paste this into your driver section and uncomment the"
          "\nline you want:\n" % len(waiting))
    print("    [[field_map_extensions]]")
    for raw in waiting:
        print("        # %s" % raw)
        print("        #%s = %s        # this driver" % (raw, mapper.fields.get(raw)))
        print("        #%s = %s        # %s"
              % (raw, mapper.undecided[raw], mapper.dialect.contested_with))
    print("\nAnything else is allowed too. A WN34 on a pool lead is not a soil"
          "\ntemperature, so somewhere in extraTemp is often what you want. The"
          "\ntemperature fields your schema already has:")
    print("    " + ', '.join(sorted(_free_temperature_fields())))


def _free_temperature_fields():
    """WeeWX fields a temperature reading could reasonably go to."""
    try:
        known = columns.schema_fields()
    except ImportError:
        return set()
    return {f for f in known if f.startswith(('extraTemp', 'soilTemp', 'leafTemp'))}


def _columns_of(config):
    """What the archive table has, or None to fall back to the standard schema.

    Asking the schema is asking what a fresh database would have been given, which is
    not the question. A database somebody has already added columns to would be told
    it needs them again.

    Args:
        config (str): The path to weewx.conf, or None when there is none to read.

    Returns:
        set: The columns the archive table has, or None to fall back to the schema.
    """
    if not config:
        return None
    try:
        return columns.existing(config)
    except Exception:                               # pylint: disable=broad-except
        return None


def _report(packet, guesses, mapper, config):
    """Print what one upload produced, and what it would still need.

    Args:
        packet (dict): The loop packet the upload became.
        guesses (dict): Fields the driver worked out for itself, and how.
        mapper (Mapper): The mapper that read it.
        config (str): The path to weewx.conf, or None.
    """
    readings = {f: v for f, v in packet.items() if f != 'dateTime'}
    print("\n%d readings" % len(readings))
    for field, value in sorted(readings.items()):
        print("  %-26s %s" % (field, value))

    if guesses:
        print("\n%d fields were not in the catalog" % len(guesses))
        for line in infer.report(guesses):
            print("  " + line)
        flagged = {g.raw for g in guesses if mapper.placement_note(g.raw)}
        if flagged:
            print("\n  Placement of these is a convention, not a reading. Say where "
                  "they\n  really are with field_map_extensions: %s"
                  % ' '.join(sorted(flagged)))

    try:
        wanted = columns.missing(packet, mapper.wanted_groups(),
                                 known=_columns_of(config))
    except ImportError:
        print("\nWeeWX is not importable here, so the columns cannot be worked out.",
              file=sys.stderr)
        return

    if not wanted:
        print("\nEvery reading has a column already.")
        return
    print("\n%d readings have nowhere to live. They will show up in reports as current"
          "\nconditions and be gone at the next archive interval. To keep them:\n"
          % len(wanted))
    for command in columns.commands(wanted, config):
        print("  " + command)
    print("\nAdding a column changes the table definition and not its rows. "
          "Taking one away again means rebuilding the table, so back up first.")


def _check_history(packet, config):
    """Say which of these fields already hold readings, and why that matters.

    Args:
        packet (dict): The loop packet the upload became.
        config (str): The path to weewx.conf, or None when there is nothing to read.
    """
    try:
        used = columns.occupied(config)
    except Exception as e:
        print("\nCannot read the database (%s). Skipping the history check." % e,
              file=sys.stderr)
        return

    clashes = {field: used[field] for field in packet if field in used}
    if not clashes:
        print("\nNo field this driver writes to has a history yet.")
        return

    print("\n%d of these fields already hold readings:\n" % len(clashes))
    for field, (count, last) in sorted(clashes.items()):
        when = time.strftime('%Y-%m-%d', time.localtime(last)) if last else '?'
        print("  %-26s %9d values, last %s" % (field, count, when))
    print("\nIf those came from the same sensor, there is nothing to do. If they came"
          "\nfrom a different one, this driver is about to write a second series into"
          "\nthe same column, and afterwards the two cannot be told apart. Give it a"
          "\nfield of its own under [[field_map_extensions]].")


if __name__ == '__main__':
    sys.exit(main())
