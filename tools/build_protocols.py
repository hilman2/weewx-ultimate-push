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

    Args:
        text (str): One of the WRITTEN blocks.

    Returns:
        str: The same, wrapped.
    """
    return '\n\n'.join(wrap(part) for part in text.strip().split('\n\n'))


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
}


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
    lines = [
        '## Options of its own',
        '',
        wrap(
            'These belong to this protocol alone and go in the `[UltimatePush]`'
            ' section. Everything else that applies is in'
            ' [Configuration](Configuration.md#driver-options).'
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
    in_auto = 'yes' if not protocol.datagram else 'no, it has to be named'
    early = (
        'Yes' if protocol.secret_kind in ('path', 'password') else 'No, it is adopted'
    )
    lines = [
        '# %s' % protocol.label,
        '',
        wrap('Setting up %s hardware by hand, in `weewx.conf`.' % protocol.label),
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
        '| Named by | its `%s` |' % protocol.identity[0],
        '| Can be set up before it uploads | %s |' % early,
        '',
        '## The smallest configuration that works',
        '',
        '```ini',
        minimal(protocol),
        '```',
        '',
        wrap(ABOUT_MINIMAL[protocol.secret_kind]),
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
        path = os.path.join(args.docs, 'Protocol-%s.md' % protocol.name.capitalize())
        with io.open(path, 'w', encoding='utf-8', newline='\n') as handle:
            handle.write(page(protocol))
        written.append(protocol.name)
    print('%d protocol pages: %s' % (len(written), ', '.join(written)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
