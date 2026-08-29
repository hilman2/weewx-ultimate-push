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

RAW = ('https://raw.githubusercontent.com/hilman2/weewx-ultimate-push/main/'
       'docs/img/')

SIDEBAR = """### Getting started

* [Home](Home)
* [Installation](Installation)
* [Protocols](Protocols)
* [Configuration](Configuration)
* [Diagnostics](Diagnostics)
* [Web interface](Web-interface)

### Placing readings

* [Field map](Field-map)
* [Hardware](Hardware)
* [Sensors](Sensors)
* [Unknown fields](Unknown-fields)
* [Stations](Stations)
* [Database columns](Database-columns)

### When something is missing

* [Reporting a new sensor](New-sensors)
* [Troubleshooting](Troubleshooting)

### Other

* [Keeping strangers out](Security)
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
    text = re.sub(r'\]\(([A-Z][A-Za-z-]*)\.md(#[a-z-]+)?\)',
                  lambda m: '](%s%s)' % (m.group(1), m.group(2) or ''), text)
    return text.replace('](docs/img/', '](' + RAW).replace('](img/', '](' + RAW)


def publish(docs, wiki):
    """Write every page of docs/ into the wiki working copy.

    Args:
        docs (str): The docs directory in this repository.
        wiki (str): A clone of the wiki repository.

    Returns:
        list: The names written.
    """
    written = []
    for name in sorted(os.listdir(docs)):
        if not name.endswith('.md'):
            continue
        text = io.open(os.path.join(docs, name), encoding='utf-8').read()
        io.open(os.path.join(wiki, name), 'w', encoding='utf-8',
                newline='').write(for_wiki(text))
        written.append(name)
    io.open(os.path.join(wiki, '_Sidebar.md'), 'w', encoding='utf-8',
            newline='').write(SIDEBAR)
    return written


def main(argv=None):
    """Run it from the command line.

    Args:
        argv (list): Arguments, without the program name.

    Returns:
        int: An exit status.
    """
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--docs', default=os.path.join(here, 'docs'),
                        help='where the pages are')
    parser.add_argument('--wiki', required=True,
                        help='a clone of the wiki repository')
    args = parser.parse_args(argv)

    if not os.path.isdir(args.wiki):
        print('No such directory: %s' % args.wiki, file=sys.stderr)
        return 1
    written = publish(args.docs, args.wiki)
    print('%d pages and a sidebar into %s' % (len(written), args.wiki))
    print('Now: cd %s && git add -A && git commit && git push' % args.wiki)
    return 0


if __name__ == '__main__':
    sys.exit(main())
