#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""What a Davis AirLink answers with, and where it belongs in WeeWX.

Like a PurpleAir, this one is asked rather than pointed: it runs a small web server
on the local network and answers whoever asks. Unlike a PurpleAir, the answer is not
flat. The readings sit two levels down, in the first entry of a `conditions` list,
which is the shape every Davis WeatherLink local API uses. The protocol unwraps it;
the names below are what is inside.

Everything here is already in the units WeeWX keeps these columns in when it is
reading US: the temperatures are Fahrenheit and the particle counts are micrograms
per cubic metre, which is the only unit WeeWX has for them.

Two kinds of particle reading arrive and they are not the same thing. `pm_2p5` and
its relatives are averages the device has worked out; `pm_2p5_last` is the last raw
count from the laser. The averages are what the device is for, so those are placed.

Source: the device's own /v1/current_conditions endpoint, data structure type 6.
        https://weatherlink.github.io/airlink-local-api/
"""

FIELDS = {
    # The BME280 on the board. Fahrenheit, like everything Davis reports by default.
    'temp': 'outTemp',
    'hum': 'outHumidity',
    'dew_point': 'dewpoint',
    'heat_index': 'heatindex',
    # A reading WeeWX has no column for. Given a group so that somebody who makes
    # one gets it written in the right unit.
    'wet_bulb': 'wetbulb',
    # The averages, which is what an air quality sensor is for.
    'pm_1': 'pm1_0',
    'pm_2p5': 'pm2_5',
    'pm_10': 'pm10_0',
    # The nowcast is the number the AQI is worked out from, and the one Davis shows.
    'pm_2p5_nowcast': 'pm2_5_nowcast',
    'pm_10_nowcast': 'pm10_0_nowcast',
    # Longer averages, for somebody who wants them recorded rather than computed.
    'pm_2p5_last_1_hour': 'pm2_5_1h',
    'pm_2p5_last_3_hours': 'pm2_5_3h',
    'pm_2p5_last_24_hours': 'pm2_5_24h',
    'pm_10_last_1_hour': 'pm10_0_1h',
    'pm_10_last_3_hours': 'pm10_0_3h',
    'pm_10_last_24_hours': 'pm10_0_24h',
    # The last raw count from the laser, which is not an average of anything.
    'pm_1_last': 'pm1_0_last',
    'pm_2p5_last': 'pm2_5_last',
    'pm_10_last': 'pm10_0_last',
    # How much of each averaging window actually had data in it. Below about 90 the
    # average above it is worth less than it looks.
    'pct_pm_data_last_1_hour': 'pm_coverage_1h',
    'pct_pm_data_last_3_hours': 'pm_coverage_3h',
    'pct_pm_data_last_24_hours': 'pm_coverage_24h',
    'pct_pm_data_nowcast': 'pm_coverage_nowcast',
}

GROUPS = {
    'wetbulb': 'group_temperature',
    'pm2_5_nowcast': 'group_concentration',
    'pm10_0_nowcast': 'group_concentration',
    'pm2_5_1h': 'group_concentration',
    'pm2_5_3h': 'group_concentration',
    'pm2_5_24h': 'group_concentration',
    'pm10_0_1h': 'group_concentration',
    'pm10_0_3h': 'group_concentration',
    'pm10_0_24h': 'group_concentration',
    'pm1_0_last': 'group_concentration',
    'pm2_5_last': 'group_concentration',
    'pm10_0_last': 'group_concentration',
    'pm_coverage_1h': 'group_percent',
    'pm_coverage_3h': 'group_percent',
    'pm_coverage_24h': 'group_percent',
    'pm_coverage_nowcast': 'group_percent',
}

# What says which device answered, or how it answered, rather than measuring.
METADATA = frozenset(
    [
        'did',
        'name',
        'ts',
        'lsid',
        'data_structure_type',
        'last_report_time',
        'firmware_version',
        'bootloader_version',
        'radio_version',
        'espressif_version',
        'battery_voltage',
        'uptime',
        'link_uptime',
        'rx_bytes',
        'tx_bytes',
        'local_api_queries',
        'health_version',
        'wifi_rssi',
        'error',
    ]
)
