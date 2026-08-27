#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""Check the catalog against Ecowitt's own API documentation.

Ecowitt publishes its cloud API at https://doc.ecowitt.net/. The site is a JavaScript
app, but the pages behind it come from a plain endpoint, so the sensor families and
their channel counts can be read rather than transcribed:

    https://doc.ecowitt.net/server/index.php?s=/api/page/info&page_id=19

That documentation names sensors the way Ecowitt thinks of them, which settles
questions the upload protocol leaves open. The WN34 is the clearest case: the cloud
API calls its family `temp_ch1..8`, not soil anything.

What this cannot do is name the fields of the custom-server protocol. The cloud API
says `soil_ch1.soilmoisture`, the console posts `soilmoisture1`, and nothing published
connects the two. So this is a check, not a source.

Usage:

    python tools/check_against_ecowitt.py
"""

import argparse
import json
import re
import sys
import urllib.request

DOC = "https://doc.ecowitt.net/server/index.php?s=/api/page/info&page_id=%d"
# Real-time data, history data, device detail. Between them they name every family.
PAGES = (17, 19, 23)

# What Ecowitt's family names correspond to in the raw upload, i.e. the one piece of
# knowledge the documentation does not carry.
FAMILIES = {
    'temp_and_humidity_ch': ('WH31', 'temp'),
    'temp_ch': ('WN34', 'tf_ch'),
    'leaf_ch': ('WN35', 'leafwetness_ch'),
    'soil_ch': ('WH51', 'soilmoisture'),
    'soil_moisture_ec_ch': ('WH52', 'soil_ec_hum'),
    'pm25_aqi_ch': ('WH41', 'pm25_ch'),
    'air_ch': ('LDS01', 'air_ch'),
    'depth_ch': ('LDS01', 'depth_ch'),
    'leak_ch': ('WH55', 'leak_ch'),
}


def fetch(page_id, timeout=30):
    with urllib.request.urlopen(DOC % page_id, timeout=timeout) as response:
        payload = json.loads(response.read().decode('utf-8'))
    data = payload.get('data') or {}
    return data.get('page_content', '')


def channels_in(text):
    """Return {family prefix: highest channel number} as the documentation has it."""
    found = {}
    for name, number in re.findall(r'\b([a-z_]+_ch|ch)_?(\d+)\b', text):
        found[name] = max(found.get(name, 0), int(number))
    return found


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--offline', help="Read a saved copy instead of fetching.")
    args = parser.parse_args(argv)

    sys.path.insert(0, 'bin/user')
    from ultimatepush.catalogs import ecowitt as catalog

    text = ''
    if args.offline:
        with open(args.offline, encoding='utf-8') as fd:
            text = fd.read()
    else:
        for page_id in PAGES:
            try:
                text += fetch(page_id)
            except Exception as e:
                print("Cannot read page %d: %s" % (page_id, e), file=sys.stderr)
    if not text:
        return 1

    documented = channels_in(text)
    print("%-24s %-8s %-10s %s" % ("Ecowitt family", "model", "documented", "ours"))
    problems = 0
    for family, (model, raw_prefix) in sorted(FAMILIES.items()):
        theirs = documented.get(family)
        ours = catalog.CHANNELS.get(raw_prefix)
        ours_count = ours[1] if ours else None
        flag = ''
        if theirs and ours_count and theirs != ours_count:
            flag = '  <-- differs'
            problems += 1
        elif not theirs:
            flag = '  <-- not found in the documentation'
        print("%-24s %-8s %-10s %s%s"
              % (family, model, theirs if theirs else '?', ours_count, flag))

    print("\nFamilies the documentation names that we do not map:")
    unknown = sorted(set(documented) - set(FAMILIES))
    print("  " + (' '.join("%s(%d)" % (f, documented[f]) for f in unknown) or "none"))
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
