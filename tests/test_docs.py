#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""Check that every page of the documentation can be reached.

A page in `docs/` is published to the wiki by tools/publish_wiki.py, which builds
the sidebar from a list of its own. A page missing from that list is published and
linked from nowhere, which is the same as not being there: the wiki has no index
but the sidebar.

The same goes for `docs/Home.md`, which is the other way in.
"""

import io
import os.path
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DOCS = os.path.join(ROOT, 'docs')

# Home is the page the sidebar links to first and does not list itself.
NOT_IN_THE_LISTS = {'Home'}


def pages():
    """Every page in docs/, by the name a wiki link uses.

    Returns:
        set[str]: The file names without '.md'.
    """
    return {
        name[:-3] for name in os.listdir(DOCS) if name.endswith('.md')
    } - NOT_IN_THE_LISTS


def linked_from(text):
    """The pages a block of markdown links to.

    Args:
        text (str): The markdown.

    Returns:
        set[str]: The link targets, with any '.md' taken off, so that the wiki's
        form and the repository's form compare as one thing.
    """
    found = set()
    for target in re.findall(r'\]\(([^)#]+)\)', text):
        if target.startswith(('http', '#', 'img/')):
            continue
        found.add(os.path.basename(target)[:-3] if target.endswith('.md') else target)
    return found - NOT_IN_THE_LISTS


def read(path):
    with io.open(path, encoding='utf-8') as handle:
        return handle.read()


def test_the_wiki_sidebar_lists_every_page():
    """Otherwise the page is published and nothing links to it."""
    import sys

    sys.path.insert(0, os.path.join(ROOT, 'tools'))
    import publish_wiki

    listed = linked_from(publish_wiki.SIDEBAR)
    missing = pages() - listed

    assert not missing, "the wiki sidebar does not list: %s" % ', '.join(
        sorted(missing)
    )


def test_the_wiki_sidebar_lists_nothing_that_is_gone():
    import sys

    sys.path.insert(0, os.path.join(ROOT, 'tools'))
    import publish_wiki

    stale = linked_from(publish_wiki.SIDEBAR) - pages()

    assert not stale, "the wiki sidebar links to pages that are gone: %s" % ', '.join(
        sorted(stale)
    )


def test_home_links_every_page():
    """Home is the other way in, and is what somebody lands on."""
    missing = pages() - linked_from(read(os.path.join(DOCS, 'Home.md')))

    assert not missing, "docs/Home.md does not link: %s" % ', '.join(sorted(missing))
