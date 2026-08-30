#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""Say what a release of rtl_433 can send that this driver does not place.

rtl_433 gains decoders every month, and a decoder can bring a reading nobody here
has met. Left alone, that is the sort of thing somebody notices a year later when
their new rain gauge records everything but the rain.

So this reads a checkout of rtl_433 and compares what its decoders can emit against
what `catalogs/rtl433.py` places. What comes out is a list to look at, not a file to
apply: where a name belongs is a decision, and a generated catalog full of guesses
would be worse than a short one somebody wrote.

    git clone --branch 25.12 https://github.com/merbanan/rtl_433 /tmp/rtl_433
    python tools/check_rtl433.py /tmp/rtl_433

Nothing is written and nothing is downloaded. The exit status is 0 whatever it
finds: a new release bringing a name is news, not a broken build.

Three sources, in what they are worth:

    src/devices/*.c     every name any decoder can emit, from its output_fields.
                        The complete list, and the only one that is complete.
    docs/DATA_FORMAT.md the naming rule and what the common names mean. What makes
                        the units readable without knowing any device.
    weewx-sdr           a second opinion, given --sdr. Ten years of somebody else
                        reading the same messages, and worth most exactly where
                        rtl_433's own naming rule is not followed.
"""

import argparse
import ast
import collections
import glob
import io
import os.path
import re
import sys
import warnings
from typing import Dict, List

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, 'bin', 'user'))

from ultimatepush.catalogs import rtl433 as catalog  # noqa: E402
from ultimatepush.protocols.rtl433 import CONVERSIONS  # noqa: E402

# Names that look like weather rather than like a car key or a doorbell. The point
# of this list is to keep four hundred tyre pressure sensors out of a report that
# somebody has to read, not to be exhaustive: everything is counted either way and
# the totals say how much was set aside.
WEATHER = re.compile(
    r'temp|humid|wind|gust|rain|press|baro|uv|light|lux|solar|radiat|dew|'
    r'moist|soil|storm|strike|lightning|pm[0-9]|pm_|co2|depth|water|leak|'
    r'snow|hail|clouds|ozone|sun'
)


def emitted(where):
    """Every field name the decoders in a checkout can send.

    Read from the `output_fields` array each decoder declares, which is how rtl_433
    itself knows what a decoder emits.

    Args:
        where (str): The root of an rtl_433 checkout.

    Returns:
        collections.Counter: Field name to how many decoders emit it.
    """
    found = collections.Counter()  # type: collections.Counter
    pattern = os.path.join(where, 'src', 'devices', '*.c')
    for path in sorted(glob.glob(pattern)):
        with io.open(path, encoding='utf-8', errors='replace') as handle:
            text = handle.read()
        for block in re.findall(
            r'output_fields\w*\[\]\s*=\s*\{(.*?)\bNULL', text, re.S
        ):
            for name in re.findall(r'"([^"]+)"', block):
                found[name] += 1
    return found


def documented(where):
    """The field names rtl_433's own documentation describes.

    Args:
        where (str): The root of an rtl_433 checkout.

    Returns:
        set[str]: The names.
    """
    path = os.path.join(where, 'docs', 'DATA_FORMAT.md')
    try:
        with io.open(path, encoding='utf-8', errors='replace') as handle:
            text = handle.read()
    except OSError:
        return set()
    return set(re.findall(r'^\* \*\*([a-zA-Z0-9_.]+)\*\*', text, re.M))


def second_opinion(path):
    """What weewx-sdr calls each rtl_433 field.

    Its packet classes read rtl_433's JSON and rename it, one class per device
    family. That renaming is a second reading of the same messages, and it is worth
    most for the names rtl_433's own `<Type>_<Unit>` rule does not cover.

    Args:
        path (str): The path to its sdr.py.

    Returns:
        dict: rtl_433 field name to the names weewx-sdr gives it, most used first.
    """
    getters = ('get_float', 'get_int', 'get_bool', 'get_str')
    with io.open(path, encoding='utf-8', errors='replace') as handle:
        source = handle.read()
    with warnings.catch_warnings():
        # Somebody else's file, with regular expressions written before Python
        # minded about backslashes in them. Nothing here can fix that and the
        # warnings would bury the report.
        warnings.simplefilter('ignore', SyntaxWarning)
        tree = ast.parse(source)

    def read_names(node):
        """Every rtl_433 field name one expression reads."""
        names = []
        for inner in ast.walk(node):
            if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Attribute):
                args = inner.args
                if inner.func.attr in getters and len(args) > 1:
                    names.append(_literal(args[1]))
                elif inner.func.attr == 'get' and args:
                    names.append(_literal(args[0]))
            elif isinstance(inner, ast.Subscript):
                names.append(_literal(inner.slice))
        return [one for one in names if one]

    said = collections.defaultdict(
        collections.Counter
    )  # type: Dict[str, collections.Counter]
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for method in node.body:
            if not isinstance(method, ast.FunctionDef) or method.name != 'parse_json':
                continue
            for stmt in ast.walk(method):
                if not isinstance(stmt, ast.Assign):
                    continue
                target = stmt.targets[0]
                if not isinstance(target, ast.Subscript):
                    continue
                if getattr(target.value, 'id', '') != 'pkt':
                    continue
                left = _literal(target.slice)
                if not left or left in ('usUnits', 'dateTime'):
                    continue
                for name in read_names(stmt.value):
                    if name != 'time':
                        said[name][left] += 1
    return {
        name: [one for one, _ in counts.most_common()] for name, counts in said.items()
    }


def _literal(node):
    """One string constant out of the source, or None.

    Args:
        node (ast.AST): The expression to read.

    Returns:
        str: The string, or None for anything else.
    """
    try:
        value = ast.literal_eval(node)
    except Exception:
        return None
    return value if isinstance(value, str) else None


def converted(name):
    """What this driver renames a field to before placing it.

    Args:
        name (str): The name rtl_433 uses.

    Returns:
        str: The name the catalog is asked about.
    """
    for suffix, becomes, _ in CONVERSIONS:
        if name.endswith(suffix):
            return name[: -len(suffix)] + becomes
    return name


def main(argv=None):
    """Compare a checkout of rtl_433 against the catalog.

    Args:
        argv (list | None): Command line arguments.

    Returns:
        int: 0, unless the checkout is not one.
    """
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('checkout', help="The root of an rtl_433 checkout.")
    parser.add_argument(
        '--sdr',
        metavar='SDR_PY',
        help="A copy of weewx-sdr's bin/user/sdr.py, for a second opinion on the "
        "names rtl_433's own naming rule does not cover.",
    )
    parser.add_argument(
        '--all',
        action='store_true',
        help="List every unplaced name, not only the ones that look like weather.",
    )
    args = parser.parse_args(argv)

    sends = emitted(args.checkout)
    if not sends:
        print(
            "No decoders under %s. Give the root of an rtl_433 checkout."
            % args.checkout,
            file=sys.stderr,
        )
        return 1
    described = documented(args.checkout)
    opinions = second_opinion(args.sdr) if args.sdr else {}

    placed = []
    known = []
    unplaced = []
    for name, decoders in sends.items():
        after = converted(name)
        if after in catalog.FIELDS:
            placed.append(name)
        elif name in catalog.METADATA or after in catalog.METADATA:
            known.append(name)
        else:
            unplaced.append((decoders, name, after))

    print(
        "%d names from %d decoders. %d placed, %d set aside as naming the sensor, "
        "%d left."
        % (len(sends), _decoders(args.checkout), len(placed), len(known), len(unplaced))
    )
    if described:
        missed = sorted(
            one
            for one in described
            if converted(one) not in catalog.FIELDS and one not in catalog.METADATA
        )
        if missed:
            print(
                "\nNamed in DATA_FORMAT.md and not placed here:\n  %s"
                % ', '.join(missed)
            )

    wanted = [row for row in unplaced if args.all or WEATHER.search(row[1])]
    if not wanted:
        print("\nNothing left that looks like weather.")
        return 0
    print(
        "\n%d left that look like weather, most used first. What each is worth is a "
        "decision, so nothing here has been applied.\n" % len(wanted)
    )
    print('  %-28s %-28s %s' % ('rtl_433', 'after conversion', 'weewx-sdr says'))
    for decoders, name, after in sorted(wanted, key=lambda row: (-row[0], row[1])):
        says = ', '.join(opinions.get(name, [])[:2])
        shown = after if after != name else ''
        print('  %-28s %-28s %s' % ('%s (%d)' % (name, decoders), shown, says))
    return 0


def _decoders(where):
    """How many decoder files a checkout has.

    Args:
        where (str): The root of an rtl_433 checkout.

    Returns:
        int: The count.
    """
    return len(glob.glob(os.path.join(where, 'src', 'devices', '*.c')))


if __name__ == '__main__':
    sys.exit(main())
