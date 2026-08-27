#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""Write docs/Sensors.md from the catalog.

The sensor reference is 500 lines of table. Keeping it by hand would mean it is wrong
within a release, so it is generated from the same catalog the driver uses.

    python tools/build_reference.py
"""

import argparse
import os.path
import re
import sys

HEADER = """# Sensor reference

Every raw field the Ecowitt catalog knows, grouped by the sensor that sends it.
The other five protocols have catalogs of their own; see [Protocols](Protocols).

Generated from the catalog by `tools/build_reference.py`. Do not edit by hand.

- **Raw field** is what the console posts.
- **WeeWX field** is where the reading is stored.
- **Waits** means the field is not written until it is named in
  `field_map_extensions`, because where it belongs is not something the hardware
  says. See [Field map](Field-map).

Channel counts are Ecowitt's own, from the compatibility table for its consoles and
gateways. A console older than the sensor may support fewer.

"""


def sensor_of(raw, channels):
    """Return (model, limit) for a raw field, or (None, None)."""
    stem = re.sub(r'\d+$', '', raw)
    for prefix in sorted(channels, key=len, reverse=True):
        if stem == prefix or raw.startswith(prefix):
            return channels[prefix]
    return None, None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', default='docs/Sensors.md')
    args = parser.parse_args(argv)

    sys.path.insert(0, os.path.join('bin', 'user'))
    from ultimatepush.catalogs import ecowitt as catalog

    by_model = {}
    single = []
    for raw, field in sorted(catalog.FIELDS.items()):
        model, limit = sensor_of(raw, catalog.CHANNELS)
        if model:
            by_model.setdefault((model, limit), []).append((raw, field))
        else:
            single.append((raw, field))

    lines = [HEADER]

    lines.append("## Multi-channel sensors\n")
    for (model, limit), fields in sorted(by_model.items()):
        note = catalog.PLACEMENT_UNKNOWN.get(
            next((p for p in catalog.CHANNELS
                  if catalog.CHANNELS[p][0] == model and p in catalog.PLACEMENT_UNKNOWN),
                 ''), '')
        lines.append("### %s\n" % model)
        lines.append("Up to %d channels.%s\n" % (limit, ' ' + note if note else ''))
        lines.append(_table(fields, catalog))
        lines.append("")

    lines.append("## Everything else\n")
    lines.append("Sensors with a single instance, and the readings a station sends "
                 "regardless of what is attached to it.\n")
    lines.append(_table(single, catalog))

    with open(args.out, 'w', encoding='utf-8', newline='\n') as fd:
        fd.write('\n'.join(lines) + '\n')
    print("%d fields, %d sensors -> %s" % (len(catalog.FIELDS), len(by_model), args.out))
    return 0


def _table(fields, catalog, sample=8):
    """Render a field table, abbreviating long channel runs."""
    rows = ["| Raw field | WeeWX field | Unit group | Waits |",
            "|---|---|---|---|"]
    shown = fields if len(fields) <= sample * 3 else _abbreviate(fields, sample)
    for raw, field in shown:
        if raw is None:
            rows.append("| ... | ... | | |")
            continue
        group = catalog.GROUPS.get(field, '')
        waits = 'yes' if raw in catalog.CONTESTED else ''
        rows.append("| `%s` | `%s` | %s | %s |" % (raw, field, group, waits))
    return '\n'.join(rows)


def _abbreviate(fields, sample):
    """Show the first few of a long run, then a gap, then the last."""
    return fields[:sample] + [(None, None)] + fields[-2:]


if __name__ == '__main__':
    sys.exit(main())
