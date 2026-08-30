#!/usr/bin/env python3
#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""Copy docs/ into the GitHub wiki, with the links a wiki needs.

The pages live in `docs/` because that is where they can be reviewed in a pull
request beside the code they describe, and because two of them are generated. The
wiki is where people read them. This makes the second out of the first.

Two things have to change on the way. A wiki link carries no `.md`, and an image
cannot be a path, because the wiki is a repository of its own and has no `docs/img`
in it. Images therefore come from raw.githubusercontent.com.

    git clone git@github.com:hilman2/weewx-ultimate-push.wiki.git /tmp/wiki
    python tools/publish_wiki.py --wiki /tmp/wiki
    cd /tmp/wiki && git add -A && git commit && git push
"""

import argparse
import io
import os
import re
import sys

RAW = 'https://raw.githubusercontent.com/hilman2/weewx-ultimate-push/main/' 'docs/img/'

SIDEBAR = """* [Home](Home)

### Using it

* [Installation](Installation)
* [Hardware](Hardware)
* [Web interface](Web-interface)
* [Stations](Stations)
* [Several stations](Several-stations)
* [Hosted hardware](Hosted-hardware)
* [Sensors this driver asks](Polled-sources)
* [Database columns](Database-columns)
* [Configuration](Configuration)
* [Diagnostics](Diagnostics)
* [Troubleshooting](Troubleshooting)
* [Keeping strangers out](Security)
* [Reporting a new sensor](New-sensors)

### One page per protocol

* [Acurite](Protocol-Acurite)
* [Ambient](Protocol-Ambient)
* [Ecowitt](Protocol-Ecowitt)
* [Lacrosse](Protocol-Lacrosse)
* [PurpleAir](Protocol-Purpleair)
* [rtl_433](Protocol-Rtl433)
* [Weatherflow](Protocol-Weatherflow)
* [Wunderground](Protocol-Wunderground)

### One page per driver this machine can read

* [AcuRite](Driver-AcuRite)
* [CC3000](Driver-CC3000)
* [FineOffsetUSB](Driver-FineOffsetUSB)
* [Simulator](Driver-Simulator)
* [TE923](Driver-TE923)
* [Ultimeter](Driver-Ultimeter)
* [Vantage](Driver-Vantage)
* [WMR100](Driver-WMR100)
* [WMR300](Driver-WMR300)
* [WMR9x8](Driver-WMR9x8)
* [WS1](Driver-WS1)
* [WS23xx](Driver-WS23xx)
* [WS28xx](Driver-WS28xx)

### How it works

* [Protocols](Protocols)
* [Field map](Field-map)
* [Ecowitt sensors](Ecowitt-sensors)
* [Unknown fields](Unknown-fields)
* [Catalogs](Catalogs)
* [Architecture](Architecture)

### Development

* [Contributing](Contributing)
* [Conventions](Conventions)
* [Development](Development)
"""


def for_wiki(text):
    """One page, with its links rewritten for a wiki.

    Args:
        text (str): The page as it is in docs/.

    Returns:
        str: The same page, with `.md` taken off internal links and images
        pointing at raw.githubusercontent.com.
    """
    text = re.sub(
        r'\]\(([A-Z][A-Za-z-]*)\.md(#[a-z-]+)?\)',
        lambda m: '](%s%s)' % (m.group(1), m.group(2) or ''),
        text,
    )
    return text.replace('](docs/img/', '](' + RAW).replace('](img/', '](' + RAW)


def publish(docs, wiki):
    """Write every page of docs/ into the wiki working copy.

    A page whose source has gone is taken out. Without that a renamed page stays in
    the wiki for ever under both names, and the old one is the one search engines
    already know about.

    Args:
        docs (str): The docs directory in this repository.
        wiki (str): A clone of the wiki repository.

    Returns:
        tuple: (written, removed), the page names of each.
    """
    written = []
    for name in sorted(os.listdir(docs)):
        if not name.endswith('.md'):
            continue
        text = io.open(os.path.join(docs, name), encoding='utf-8').read()
        io.open(os.path.join(wiki, name), 'w', encoding='utf-8', newline='').write(
            for_wiki(text)
        )
        written.append(name)
    io.open(os.path.join(wiki, '_Sidebar.md'), 'w', encoding='utf-8', newline='').write(
        SIDEBAR
    )
    removed = []
    for name in sorted(os.listdir(wiki)):
        # _Sidebar.md is the wiki's own, and .git is not a page.
        if not name.endswith('.md') or name.startswith('_') or name in written:
            continue
        os.remove(os.path.join(wiki, name))
        removed.append(name)
    return written, removed


def main(argv=None):
    """Run it from the command line.

    Args:
        argv (list | None): Arguments, without the program name.

    Returns:
        int: An exit status.
    """
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument(
        '--docs', default=os.path.join(here, 'docs'), help='where the pages are'
    )
    parser.add_argument('--wiki', required=True, help='a clone of the wiki repository')
    args = parser.parse_args(argv)

    if not os.path.isdir(args.wiki):
        print('No such directory: %s' % args.wiki, file=sys.stderr)
        return 1
    written, removed = publish(args.docs, args.wiki)
    print('%d pages and a sidebar into %s' % (len(written), args.wiki))
    if removed:
        print(
            'took out %d page(s) whose source has gone: %s'
            % (len(removed), ', '.join(removed))
        )
    print('Now: cd %s && git add -A && git commit && git push' % args.wiki)
    return 0


if __name__ == '__main__':
    sys.exit(main())
