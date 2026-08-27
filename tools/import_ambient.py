#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""Build the Ambient Weather catalog from the Home Assistant integration.

Ambient publishes no field list. What they do have is a cloud API that relays what a
console uploaded, and the most complete list of its keys anywhere is the
`ambient_station` integration in Home Assistant, which is maintained against real
hardware and carries a unit and a device class for every one of them.

So the names come from there, the same way the Ecowitt names come from ecowittcustom:
read out of the source, not retyped. Where each one belongs in WeeWX is decided here,
in the tables below, which are meant to be read.

Usage:

    python tools/import_ambient.py path/to/homeassistant/components/ambient_station

    # or against a checkout that is not on disk
    python tools/import_ambient.py --download

The result is reviewed and committed like any other file. Run it again when Ambient
ships a sensor, and the addition is a diff somebody can check.
"""

import argparse
import ast
import os.path
import re
import sys
import urllib.request

HA_RAW = ('https://raw.githubusercontent.com/home-assistant/core/dev/'
          'homeassistant/components/ambient_station/%s')
HA_FILES = ('sensor.py', 'binary_sensor.py', 'const.py')


# Fields Ambient's servers compute and a console never sends. Taking them would put a
# column in the database that is empty on every local install, and would quietly
# compete with the values WeeWX derives itself.
COMPUTED_BY_AMBIENT = {
    'dewPoint': 'WeeWX derives dewpoint itself, from temperature and humidity.',
    'feelsLike': 'WeeWX derives appTemp itself.',
    'lastRain': 'Computed from the rain counters, which we already have.',
}

# Raw name -> WeeWX field, for everything that is not part of a numbered family.
#
# Where a name means the same thing as one in the Ecowitt catalog, it goes to the same
# WeeWX field. Two consoles reporting the same reading into two different columns
# would be a decision nobody made on purpose.
SINGLES = {
    'tempf': 'outTemp',
    'tempinf': 'inTemp',
    'humidity': 'outHumidity',
    'humidityin': 'inHumidity',
    'baromrelin': 'barometer',
    'baromabsin': 'pressure',

    'winddir': 'windDir',
    'windspeedmph': 'windSpeed',
    'windgustmph': 'windGust',
    'windgustdir': 'windGustDir',
    'maxdailygust': 'maxdailygust',
    # The averaged wind keeps the name the hardware uses, which is also the name the
    # Ecowitt catalog gives it. WeeWX has no column for any of them, and a station
    # that changes protocol should not start a second column for one sensor.
    'windspdmph_avg2m': 'windspdmph_avg2m',
    'winddir_avg2m': 'winddir_avg2m',
    'windspdmph_avg10m': 'windspdmph_avg10m',
    'winddir_avg10m': 'winddir_avg10m',

    'hourlyrainin': 'hourRain',
    'dailyrainin': 'dayRain',
    'eventrainin': 'eventRain',
    'weeklyrainin': 'weekRain',
    'monthlyrainin': 'monthRain',
    'yearlyrainin': 'yearRain',
    'totalrainin': 'totalRain',
    '24hourrainin': 'rain24',

    'solarradiation': 'radiation',
    'solarradiation_lx': 'luminosity',
    'uv': 'UV',

    'co2': 'co2',
    'pm25': 'pm2_5',
    'pm25_24h': 'pm2_5_24h',
    'pm25_in': 'pm2_5_in',
    'pm25_in_24h': 'pm2_5_in_24h',
    'aqi_pm25': 'pm2_5_aqi',
    'aqi_pm25_24h': 'pm2_5_aqi_24h',
    'aqi_pm25_in': 'pm2_5_in_aqi',
    'aqi_pm25_in_24h': 'pm2_5_in_aqi_24h',

    # The AQIN module, Ambient's indoor air quality sensor.
    'pm25_in_aqin': 'pm2_5_in_aqin',
    'pm25_in_24h_aqin': 'pm2_5_in_24h_aqin',
    'pm10_in_aqin': 'pm10_in_aqin',
    'pm10_in_24h_aqin': 'pm10_in_24h_aqin',
    'aqi_pm25_aqin': 'pm2_5_aqi_aqin',
    'aqi_pm25_24h_aqin': 'pm2_5_aqi_24h_aqin',
    'aqi_pm10_aqin': 'pm10_aqi_aqin',
    'aqi_pm10_24h_aqin': 'pm10_aqi_24h_aqin',
    'co2_in_aqin': 'co2_in_aqin',
    'co2_in_24h_aqin': 'co2_in_24h_aqin',
    'pm_in_temp_aqin': 'aqin_Temp',
    'pm_in_humidity_aqin': 'aqin_Hum',

    # Lightning. 'lightning_day' is a running count since midnight, not the strikes
    # in this period, so it is kept where the Ecowitt catalog keeps the same reading
    # rather than in lightning_strike_count, which reports would read as a delta.
    'lightning_day': 'lightning_num',
    'lightning_hour': 'lightning_hour',
    'lightning_distance': 'lightning_distance',
    'lightning_time': 'lightning_time',

    'battin': 'inTempBatteryStatus',
    'battout': 'outTempBatteryStatus',
    'batt_25': 'pm25Batt',
    'batt_25in': 'pm25inBatt',
    'batt_co2': 'co2Batt',
    'batt_lightning': 'lightningBatt',
}

# Numbered families: raw prefix and suffix -> WeeWX prefix, with the highest channel
# Ambient documents. The console numbers its own channels, so a family is a series
# and the driver can continue it; the count is what stops it continuing past the
# hardware.
FAMILIES = [
    # (raw prefix, raw suffix, WeeWX prefix, WeeWX suffix, channels, sensor)
    ('temp', 'f', 'extraTemp', '', 10, 'WH31-equivalent temperature and humidity'),
    ('humidity', '', 'extraHumid', '', 10, 'WH31-equivalent temperature and humidity'),
    ('soiltemp', 'f', 'soilTemp', '', 10, 'soil temperature probe'),
    ('soilhum', '', 'soilMoist', '', 10, 'soil moisture probe'),
    ('batt', '', 'batteryStatus', '', 10, 'WH31-equivalent battery'),
    ('battsm', '', 'soilMoistBatt', '', 10, 'soil moisture battery'),
    ('leak', '', 'leak', '', 4, 'water leak detector'),
    ('batleak', '', 'leakBatt', '', 4, 'water leak detector battery'),
    ('relay', '', 'relay', '', 10, 'relay'),
]

# WeeWX field -> unit group, for the fields WeeWX does not already know. Written out
# rather than derived, because a wrong group is a wrong reading and a derived one
# would be no easier to check than a typed one.
GROUPS = {
    'maxdailygust': 'group_speed2',
    'windspdmph_avg2m': 'group_speed2',
    'winddir_avg2m': 'group_direction',
    'windspdmph_avg10m': 'group_speed2',
    'winddir_avg10m': 'group_direction',
    'hourRain': 'group_rain',
    'dayRain': 'group_rain',
    'eventRain': 'group_rain',
    'weekRain': 'group_rain',
    'monthRain': 'group_rain',
    'yearRain': 'group_rain',
    'totalRain': 'group_rain',
    'rain24': 'group_rain',
    'luminosity': 'group_illuminance',
    'pm2_5_24h': 'group_concentration',
    'pm2_5_in': 'group_concentration',
    'pm2_5_in_24h': 'group_concentration',
    'pm2_5_aqi': 'group_count',
    'pm2_5_aqi_24h': 'group_count',
    'pm2_5_in_aqi': 'group_count',
    'pm2_5_in_aqi_24h': 'group_count',
    'pm2_5_in_aqin': 'group_concentration',
    'pm2_5_in_24h_aqin': 'group_concentration',
    'pm10_in_aqin': 'group_concentration',
    'pm10_in_24h_aqin': 'group_concentration',
    'pm2_5_aqi_aqin': 'group_count',
    'pm2_5_aqi_24h_aqin': 'group_count',
    'pm10_aqi_aqin': 'group_count',
    'pm10_aqi_24h_aqin': 'group_count',
    'co2_in_aqin': 'group_fraction',
    'co2_in_24h_aqin': 'group_fraction',
    'aqin_Temp': 'group_temperature',
    'aqin_Hum': 'group_percent',
    'lightning_num': 'group_count',
    'lightning_hour': 'group_count',
    'lightning_time': 'group_time',
    'inTempBatteryStatus': 'group_count',
    'outTempBatteryStatus': 'group_count',
    'pm25Batt': 'group_count',
    'pm25inBatt': 'group_count',
    'co2Batt': 'group_count',
    'lightningBatt': 'group_count',
}

# Unit group per family, applied to every channel of it.
FAMILY_GROUPS = {
    'extraTemp': 'group_temperature',
    'extraHumid': 'group_percent',
    'soilTemp': 'group_temperature',
    'soilMoist': 'group_moisture',
    'batteryStatus': 'group_count',
    'soilMoistBatt': 'group_count',
    'leak': 'group_count',
    'leakBatt': 'group_count',
    'relay': 'group_boolean',
}

# Families whose target name claims more than the hardware does. Ambient's tempNf is
# whatever the user hung it on, exactly like Ecowitt's tempN.
PLACEMENT_UNKNOWN = {
    'temp': "Ambient multi-channel temperature and humidity. Placement is the user's.",
    'soiltemp': "Ambient soil temperature probe. Placement is the user's.",
}

# Raw field -> where somebody else puts it, and why this driver does not.
CONTESTED = {
    'lightning_time': 'lightning_disturber_count',
}

CONTESTED_WITH = 'ecowittcustom, which keeps the lightning timestamp in a counter'


HEADER = '''#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""What Ambient Weather hardware sends, and where it belongs in WeeWX.

Generated by tools/import_ambient.py from the ambient_station integration in Home
Assistant, https://github.com/home-assistant/core, which is Apache-2.0. Only the field
names are taken from it; where each one belongs in WeeWX is decided in the tool.

Do not edit by hand. Run the tool again instead, so that the next sensor Ambient ships
stays a reviewable diff.

Source: {source}
Fields: {count}
"""

# Raw field name as the console sends it -> the WeeWX field it belongs in.
FIELDS = {{
{fields}}}

# WeeWX field -> unit group, for the fields that are not already in the WeeWX schema.
GROUPS = {{
{groups}}}

# Raw field prefixes whose target name says more than the hardware does.
PLACEMENT_UNKNOWN = {{
{placement}}}

# Raw field prefix -> (sensor, how many channels it can have).
CHANNELS = {{
{channels}}}

# Raw field -> where another driver puts it. Not written until the user says which
# placement they want, because the wrong one cannot be undone.
CONTESTED = {{
{contested}}}

# The driver those other placements come from.
CONTESTED_WITH = {contested_with!r}
'''


def ha_field_names(source_dir=None, download=False):
    """Every raw Ambient field name Home Assistant knows.

    They are module-level assignments of the form TYPE_SOMETHING = "rawname", so the
    ast module can read them without importing Home Assistant.
    """
    names = set()
    for filename in HA_FILES:
        if download:
            url = HA_RAW % filename
            with urllib.request.urlopen(url) as response:
                text = response.read().decode('utf-8')
        else:
            path = os.path.join(source_dir, filename)
            if not os.path.exists(path):
                continue
            with open(path, encoding='utf-8') as handle:
                text = handle.read()
        tree = ast.parse(text)
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if (isinstance(target, ast.Name)
                        and target.id.startswith('TYPE_')
                        and isinstance(node.value, ast.Constant)
                        and isinstance(node.value.value, str)):
                    names.add(node.value.value)
    return names


def split_family(name):
    """Return (prefix, index, suffix) if a name belongs to a numbered family."""
    for prefix, suffix, _target, _tsuffix, count, _sensor in FAMILIES:
        pattern = r'^%s(\d+)%s$' % (re.escape(prefix), re.escape(suffix))
        match = re.match(pattern, name)
        if match:
            index = int(match.group(1))
            if index <= count:
                return prefix, index, suffix
    return None


def build(names):
    """Turn raw names into the catalog, and say what could not be placed."""
    fields = {}
    groups = dict(GROUPS)
    channels = {}
    unplaced = []

    for prefix, suffix, target, tsuffix, count, sensor in FAMILIES:
        channels[prefix] = (sensor, count)
        for index in range(1, count + 1):
            raw = '%s%d%s' % (prefix, index, suffix)
            field = '%s%d%s' % (target, index, tsuffix)
            fields[raw] = field
            group = FAMILY_GROUPS.get(target)
            if group:
                groups[field] = group

    for name in sorted(names):
        if name in COMPUTED_BY_AMBIENT:
            continue
        if name in SINGLES:
            fields[name] = SINGLES[name]
            continue
        if split_family(name):
            # Already covered by the family loop above, for every channel rather than
            # only the ones Home Assistant happens to list.
            continue
        unplaced.append(name)

    # Names decided here that Home Assistant does not list. They come out of captured
    # uploads instead, so they are kept, but they are worth seeing.
    extra = sorted(set(SINGLES) - set(names) - set(COMPUTED_BY_AMBIENT))
    for name in extra:
        fields[name] = SINGLES[name]

    return fields, groups, channels, unplaced, extra


def render(mapping, indent='    '):
    return ''.join("%s%r: %r,\n" % (indent, key, mapping[key])
                   for key in sorted(mapping))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', nargs='?',
                        help='path to homeassistant/components/ambient_station')
    parser.add_argument('--download', action='store_true',
                        help='read the files from GitHub instead')
    parser.add_argument('--out', default=os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'bin', 'user', 'ultimatepush', 'catalogs', 'ambient.py'))
    args = parser.parse_args(argv)

    if not args.source and not args.download:
        parser.error('give a path to the integration, or --download')

    names = ha_field_names(args.source, args.download)
    if not names:
        print('No field names found. Is that the right directory?', file=sys.stderr)
        return 1

    fields, groups, channels, unplaced, extra = build(names)

    with open(args.out, 'w', encoding='utf-8', newline='\n') as handle:
        handle.write(HEADER.format(
            source='home-assistant/core, ambient_station' if args.download
                   else args.source,
            count=len(fields),
            fields=render(fields),
            groups=render(groups),
            placement=render(PLACEMENT_UNKNOWN),
            channels=render(channels),
            contested=render(CONTESTED),
            contested_with=CONTESTED_WITH))

    print('%d fields -> %s' % (len(fields), args.out))
    if extra:
        print('\n%d name(s) placed here that Home Assistant does not list. They come '
              'from captured uploads:' % len(extra))
        for name in extra:
            print('    %s' % name)
    if unplaced:
        print('\n%d name(s) with nowhere to go. Add them to SINGLES or FAMILIES, or '
              'to COMPUTED_BY_AMBIENT with the reason:' % len(unplaced))
        for name in unplaced:
            print('    %s' % name)
    return 0


if __name__ == '__main__':
    sys.exit(main())
