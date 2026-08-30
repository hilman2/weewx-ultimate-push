#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""Write docs/Hardware.md: every device, and the fields it sends.

What each device is, is written here. Which fields it sends comes from the catalog,
so the two cannot drift apart. The tool also reports catalog fields that belong to no
device, which is how gaps in this list get found.

    python tools/build_hardware.py
"""

import argparse
import os.path
import re
import sys
from typing import Set

# model, what it is, patterns matching the raw fields it sends.
#
# A pattern is a regular expression against the raw field name. Channel numbers are
# written as \d+ so one entry covers the whole family.
ARRAYS = [
    (
        'WS90',
        "7-in-1 array. Ultrasonic wind, piezo rain, temperature, humidity, "
        "solar, UV. No moving parts. Sold as the Wittboy.",
        [
            r'^ws90',
            r'_piezo$',
            r'^(r|e|h|d|w|m|y)rain_piezo$',
            r'^srain_piezo$',
            r'^wh90batt',
            r'^ws90cap_volt',
            r'^wh90(sig|rssi)',
        ],
    ),
    (
        'WS85',
        "3-in-1 array. Ultrasonic wind and piezo rain, no temperature.",
        [r'^ws85', r'^wh85'],
    ),
    (
        'WS80',
        "6-in-1 array. Ultrasonic wind, temperature, humidity, solar, UV. "
        "No rain gauge.",
        [r'^ws80', r'^wh80'],
    ),
    (
        'WS69 / WH65',
        "7-in-1 array with moving parts: cup anemometer, wind vane, "
        "tipping bucket, temperature, humidity, solar, UV. The one most "
        "outdoor stations ship with. Sold as WH65B and WH65L depending on "
        "the radio band.",
        [r'^wh65', r'^ws69', r'^wh69(sig|rssi)'],
    ),
    ('WS68', "Wind, solar and UV only. No temperature, no rain.", [r'^ws68', r'^wh68']),
    (
        'WH24',
        "The earlier 7-in-1 array, from the WH2900 era. Same readings as the "
        "WH65, different radio.",
        [r'^wh24'],
    ),
    ('WN67', "Array without solar or UV.", [r'^wn67', r'^wh67']),
]

SENSORS = [
    (
        'WH31 / WN31',
        "Multi-channel temperature and humidity, 8 channels. The small "
        "white sensors people put in a greenhouse or a shed.",
        [r'^temp\d+f$', r'^humidity\d+$', r'^batt\d+$', r'^wh31'],
    ),
    ('WN30', "Temperature only, on the same channels as the WH31.", [r'^wn30']),
    ('WN36', "Pool thermometer. A WN30 in a floating housing.", [r'^wn36']),
    (
        'WN32 / WH32 / WH26',
        "The outdoor temperature and humidity sensor a station "
        "without an array uses. WH26 is the older name for it.",
        [r'^wh32', r'^wn32', r'^wh26'],
    ),
    (
        'WN32P / WH25',
        "Indoor temperature, humidity and pressure. Built into most " "consoles.",
        [r'^wh25', r'^tempin', r'^humidityin', r'^barom'],
    ),
    (
        'WN34 S/L/D',
        "Multi-channel temperature, 8 channels. One device in three "
        "housings: a spike for soil, a PVC lead, and a silicone lead for a "
        "pool. Nothing in the upload says which.",
        [r'^tf_ch\d+$', r'^tf_batt\d+$', r'^wh34', r'^wn34'],
    ),
    (
        'WN35',
        "Leaf wetness, 8 channels.",
        [r'^leafwetness_ch\d+$', r'^leaf_batt\d+$', r'^wh35', r'^wn35'],
    ),
    (
        'WH51 / WH51L',
        "Soil moisture, one probe. Shares its 16 channels with the WH52.",
        [r'^soilmoisture\d+$', r'^soilbatt\d+$', r'^soilad\d+$', r'^wh51'],
    ),
    (
        'WH52',
        "Soil moisture, temperature and conductivity in one probe. Shares its "
        "channels with the WH51.",
        [r'^soil_ec'],
    ),
    (
        'WH40 / WH40H',
        "Tipping bucket rain gauge, for stations without an array. The H "
        "is the self-emptying one.",
        [r'^wh40', r'rainin$', r'^rainrate', r'^totalrain', r'^rainratein$'],
    ),
    (
        'WH41 / WH43',
        "Outdoor particulate sensor, PM2.5, 4 channels.",
        [r'^pm25', r'^wh41', r'^wh43'],
    ),
    (
        'WH45',
        "5-in-1 indoor air quality: CO2, PM2.5, PM10, temperature, humidity.",
        [r'^wh45', r'^co2', r'^tf_co2', r'^humi_co2', r'^pm25_co2', r'^pm10'],
    ),
    (
        'WH46 / WH46D',
        "7-in-1 air quality. The WH45 plus PM1 and PM4.",
        [r'^wh46', r'^pm1', r'^pm4'],
    ),
    ('WH55', "Water leak detector, 4 channels.", [r'^leak', r'^wh55']),
    (
        'WH57',
        "Lightning detector. Distance to the last strike and a daily count.",
        [r'^lightning', r'^wh57'],
    ),
    (
        'WN38',
        "Black globe thermometer, for WBGT heat stress.",
        [r'^bgt', r'^wbgt', r'^wn38'],
    ),
    (
        'WH54 / LDS01',
        "Laser distance sensor, 4 channels. Water level and snow depth.",
        [r'^air_ch\d+$', r'^depth_ch\d+$', r'^thi_ch\d+$', r'^lds', r'^wh54'],
    ),
    (
        'WFC01 / WFC02',
        "Irrigation valve with flow metering, 16 channels.",
        [r'^wfc', r'^flow', r'^water'],
    ),
    ('AC1100', "Mains power meter, 16 channels.", [r'^ac\d', r'^ac1100', r'^elect']),
    ('WN20', "Rain gauge with its own display.", [r'^wn20']),
]

# Consoles and gateways: model, what it is, how it uploads.
CONSOLES = [
    (
        'GW1000',
        "The first gateway. Wi-Fi, built-in temperature, humidity and "
        "pressure on a lead. No display.",
        "Wi-Fi",
    ),
    ('GW1100', "GW1000 with the sensor inside the housing.", "Wi-Fi"),
    ('GW1200', "Adds the LDS01 and newer sensors.", "Wi-Fi"),
    ('GW2000', "Gateway with Ethernet as well as Wi-Fi.", "Wi-Fi + RJ45"),
    (
        'GW3000',
        "Current gateway. Ethernet, and an SD card that records when the "
        "network is down.",
        "Wi-Fi + RJ45",
    ),
    ('HP2551', "Colour TFT console, the common one for a WS69 station.", "Wi-Fi"),
    ('HP2560 / HP2561', "Larger console, more channels, SD card.", "Wi-Fi"),
    ('HP3500 / HP3501', "Console with a separate outdoor array.", "Wi-Fi"),
    ('WS3800 / WS3820', "Compact colour console.", "Wi-Fi"),
    ('WS3900 / WS3910', "Console with a built-in CO2 sensor on the 3910.", "Wi-Fi"),
    ('WN1820 / WN1821', "LCD console. Uploads only, no local API.", "Wi-Fi"),
    ('WN1900 / WN1910', "LCD console, fewer channels.", "Wi-Fi"),
    ('WN1920 / WN1980', "LCD console with array support.", "Wi-Fi"),
    ('WS2910', "Older console, 4G variant exists.", "Wi-Fi"),
    ('WS6210', "Console with cellular upload.", "4G + Wi-Fi"),
    ('WS6006', "Cellular gateway.", "3G/4G"),
    ('WN1700', "IoT display.", "Wi-Fi"),
]

# Older Fine Offset hardware, sold under many names. These predate the Ecowitt brand
# and mostly speak the WU protocol rather than the Ecowitt one.
OLDER = [
    (
        'WH2900',
        "Wi-Fi console with a WH24 array. Sold as Ambient WS-2902, Froggit "
        "WH2900 and others. Uploads in Wunderground format; some firmware "
        "allows a custom server.",
    ),
    (
        'WH2600',
        "Bridge without a display, WH24 array. Sold as Ambient ObserverIP, "
        "Aercus WeatherSleuth, Froggit WH2600.",
    ),
    (
        'HP1000',
        "Console with Wi-Fi upload, same array. Sold as Aercus WeatherRanger, "
        "Ambient WS-1001.",
    ),
    ('WH2650', "Gateway between the WH24 array and Wi-Fi."),
    (
        'WH1080 / WH1081',
        "USB console, no network at all. WeeWX reads it with the "
        "`fousb` driver in the core, not with this one.",
    ),
    (
        'WH23xx / WH4000',
        "Serial or USB console. Sold as Tycon TP2700, MiSol WH2310. There is a "
        "`weewx-wh23xx` driver and it is Python 2: it stops at a syntax error "
        "under any Python WeeWX 5 runs on, and has not been touched since 2020. "
        "Nothing here reads this console.",
    ),
]

# Readings that come from whichever outdoor array is fitted. A WS90, a WS69 and a
# WS80 all send tempf, and nothing in the upload says which one it was.
ARRAY_READINGS = [
    (
        r'^tempf$|^dewptf$|^feelslikef$|^heatindexf$|^windchillf$|^humidity$',
        "Outdoor temperature and humidity, with what the console derives from them",
    ),
    (
        r'^wind(dir|speed|gust)|^winddir_avg10m$|^windspdmph_avg10m$|^windrun$|'
        r'^maxdailygust$|^windgustmph_max10m$',
        "Wind",
    ),
    (
        r'rainin$|^rainrate|^rainyear$|^piezo$|gain$|^rainGain$|^rainFallPriority$|^rst[Rr]ain',
        "Rain, and the calibration the console keeps for it",
    ),
    (
        r'^solarradiation$|^uv$|^sunhours$|^sunshine$|^radcompensation$',
        "Solar and UV, with sunshine derived from them",
    ),
    (r'^vpd$', "Vapour pressure deficit, calculated by the console"),
]

# What a console says about itself.
CONSOLE_READINGS = [
    (
        r'^(heap|runtime|interval|model|stationtype|upgrade|newVersion)$',
        "Firmware, uptime, free memory, upload interval",
    ),
    (r'^(console_batt|consolebattp|ws1900batt|charge|ext_volt)$', "Console power"),
]

HEADER = """# Hardware

Every device this driver knows about, what it is, and what it takes to reach it.

The descriptions are written; the Ecowitt field lists come from the catalog, so the two
cannot drift apart. Generated by `tools/build_hardware.py`. Do not edit by hand.

## What it takes to reach each of them

| Hardware | How it reaches WeeWX | What you have to do |
|---|---|---|
| Ecowitt, Froggit, Misol | posts, path of your choosing | set *Customized* in WS View Plus |
| Ambient Weather | posts, path of your choosing | set the custom server in awnet |
| Fine Offset Observer, Sainlogic | posts to a fixed path | set the server and port; the path cannot be changed |
| WeatherFlow | broadcasts on UDP 50222 | nothing on the hub; enable the protocol, and be on the same network segment |
| Acurite smartHUB, Access | posts to `hubapi.myacurite.com` | point that hostname at WeeWX in your own DNS |
| LaCrosse LW301, LW302 | posts to `box.weatherdirect.com` | point that hostname at WeeWX in your own DNS |

### The two that need a DNS entry

Neither an Acurite bridge nor a LaCrosse gateway can be told where to post. It goes to
its maker's servers, over plain HTTP on port 80, and there is no setting for it.

So the hostname has to resolve to the machine running WeeWX on your network. How is up
to you. With `dnsmasq`:

    address=/hubapi.myacurite.com/192.168.1.10

Most routers can do the same thing under a name like *DNS host entry* or *local DNS*.
A `hosts` file on the WeeWX machine will not work: the entry has to be seen by the
bridge, not by WeeWX.

Both post to port 80, which needs root. Running WeeWX as root to get it is not a good
trade. Redirect the port instead:

    iptables -t nat -A PREROUTING -p tcp --dport 80 -j REDIRECT --to-port 8000

Once the bridge is pointed here it no longer reaches its maker's servers, so the
maker's app and website stop showing the station. That is the trade, and it is not
reversible without undoing the DNS entry.

## Ecowitt and Fine Offset

A note on names. Ecowitt renamed its sensors partway through: `WH` became `WN` for
the smaller ones, so a WH31 and a WN31 are the same device. The uploads still use the
old names, which is why the raw fields below say `wh31` where the box says WN31.
Suffix letters are variants of one device, not different products: `WH51` and `WH51L`
differ in cable length, `WH65B` and `WH65L` in radio band, `WN34S/L/D` in housing.

Fine Offset builds all of it. The same hardware is sold as Ecowitt, Froggit, Ambient
Weather, Aercus, Misol, Sainlogic and others, usually with the model number intact.
Which protocol a given box speaks depends on its firmware rather than on its badge, and
the driver works that out per upload.

"""


def fields_for(patterns, catalog):
    """Every catalog field whose raw name matches one of these patterns."""
    matched = []
    for raw in sorted(catalog.FIELDS):
        if any(re.search(p, raw) for p in patterns):
            matched.append((raw, catalog.FIELDS[raw]))
    return matched


def summarise(matched, catalog, limit=6):
    """One line naming the WeeWX fields, with long channel runs collapsed."""
    if not matched:
        return "_no fields in the catalog_"
    targets = []
    for _, field in matched:
        stem = re.sub(r'\d+', 'N', field)
        if stem not in targets:
            targets.append(stem)
    shown = ['`%s`' % t for t in targets[:limit]]
    if len(targets) > limit:
        shown.append('and %d more' % (len(targets) - limit))
    return ', '.join(shown)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', default='docs/Hardware.md')
    args = parser.parse_args(argv)

    sys.path.insert(0, os.path.join('bin', 'user'))
    from ultimatepush.catalogs import ecowitt as catalog

    claimed = set()  # type: Set[str]
    lines = [HEADER]

    for title, group in (("Outdoor sensor arrays", ARRAYS), ("Sensors", SENSORS)):
        lines.append("## %s\n" % title)
        for model, description, patterns in group:
            matched = fields_for(patterns, catalog)
            claimed.update(raw for raw, _ in matched)
            channels = _channels_for(patterns, catalog)
            lines.append("### %s\n" % model)
            lines.append(description + "\n")
            if channels:
                lines.append("Channels: %d.\n" % channels)
            lines.append("Fields: %s\n" % summarise(matched, catalog))
        lines.append("")

    for title, readings, note in (
        (
            "What any outdoor array sends",
            ARRAY_READINGS,
            "A WS90, a WS69 and a WS80 all report the weather in the same fields. Which "
            "array sent a reading is not in the upload, so these belong to whichever one "
            "is fitted.",
        ),
        (
            "What a console says about itself",
            CONSOLE_READINGS,
            "Diagnostics rather than weather, and useful for spotting a console that is "
            "about to give trouble.",
        ),
    ):
        lines.append("## %s\n" % title)
        lines.append(note + "\n")
        for pattern, description in readings:
            matched = fields_for([pattern], catalog)
            claimed.update(raw for raw, _ in matched)
            lines.append("- **%s.** %s" % (description, summarise(matched, catalog, 8)))
        lines.append("")

    lines.append("## Consoles and gateways\n")
    lines.append(
        "What a console does for this driver is upload. The differences that "
        "matter are how many sensors it accepts and whether its firmware "
        "offers a custom server.\n"
    )
    lines.append("| Model | Upload | What it is |")
    lines.append("|---|---|---|")
    for model, description, upload in CONSOLES:
        lines.append("| %s | %s | %s |" % (model, upload, description))
    lines.append("")

    lines.append("## Older Fine Offset hardware\n")
    lines.append(
        "These predate the Ecowitt brand. Most speak the Wunderground "
        "protocol, and only some firmware versions offer a custom server. "
        "Where they do, this driver reads them.\n"
    )
    lines.append("| Model | What it is |")
    lines.append("|---|---|")
    for model, description in OLDER:
        lines.append("| %s | %s |" % (model, description))
    lines.append("")

    orphans = sorted(set(catalog.FIELDS) - claimed)
    lines.append("## Fields nobody has identified\n")
    lines.append(
        "%d of %d. Which device sends these, and what they mean, is not "
        "known here. If you can tell from your own station, please say so:\n"
        "<https://github.com/hilman2/weewx-ultimate-push/issues>\n"
        % (len(orphans), len(catalog.FIELDS))
    )
    lines.append('`' + '`, `'.join(orphans) + '`' if orphans else "_none_")

    with open(args.out, 'w', encoding='utf-8', newline='\n') as fd:
        fd.write('\n'.join(lines) + '\n')

    print(
        "%d devices, %d of %d fields claimed -> %s"
        % (
            len(ARRAYS) + len(SENSORS) + len(CONSOLES) + len(OLDER),
            len(claimed),
            len(catalog.FIELDS),
            args.out,
        )
    )
    return 0


def _channels_for(patterns, catalog):
    """The channel count Ecowitt publishes for this family, if we know it."""
    for prefix, (_model, count) in catalog.CHANNELS.items():
        if any(re.search(p, prefix + '1') for p in patterns):
            return count
    return None


if __name__ == '__main__':
    sys.exit(main())
