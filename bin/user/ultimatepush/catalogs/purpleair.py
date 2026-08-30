#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""What a PurpleAir sensor answers with, and where it belongs in WeeWX.

This one is not pushed at anything. The sensor runs a small web server and answers
whatever asks it, so the driver goes and asks. What comes back is one flat JSON
object, which makes it the same shape as every other catalog here.

Two things about the readings are worth knowing before they are believed.

The temperature is measured inside the housing, beside electronics that are warm. It
reads several degrees above the air around it, and PurpleAir's own site applies a
correction before showing it. Nothing here corrects it: a reading that has been
adjusted by an amount nobody wrote down is worse than a reading that is plainly the
inside of a box. Give the sensor `role = extra` and it lands in a column of its own
where it cannot be mistaken for the air temperature.

Most of these sensors carry two laser counters, called A and B, and report both. The
B channel arrives with a `_b` suffix and is left where it is rather than averaged in.
Two counters that disagree is the one thing that says a sensor is failing, and an
average hides exactly that.

Source: the sensor's own /json endpoint, which is the same JSON the PurpleAir map
        reads. There is no published specification for it; these are the names the
        firmware sends.
"""

FIELDS = {
    # The particle counts, in micrograms per cubic metre. 'atm' is the outdoor
    # calibration and is what PurpleAir's own map shows; 'cf_1' is the indoor one.
    # Both are sent, and mapping the outdoor one is what an outdoor sensor means.
    'pm1_0_atm': 'pm1_0',
    'pm2_5_atm': 'pm2_5',
    'pm10_0_atm': 'pm10_0',
    'pm2.5_aqi': 'pm2_5_aqi',
    # The second laser counter. Its own columns, so that a sensor going deaf in one
    # ear is visible rather than averaged away.
    'pm1_0_atm_b': 'pm1_0_b',
    'pm2_5_atm_b': 'pm2_5_b',
    'pm10_0_atm_b': 'pm10_0_b',
    'pm2.5_aqi_b': 'pm2_5_aqi_b',
    # The indoor calibration of the reading that matters, for somebody who has put
    # one of these inside.
    'pm2_5_cf_1': 'pm2_5_cf_1',
    'pm2_5_cf_1_b': 'pm2_5_cf_1_b',
    # The BME280 on the board. Absent on a sensor that has none, and on one whose
    # chip has failed.
    'current_temp_f': 'outTemp',
    'current_humidity': 'outHumidity',
    'current_dewpoint_f': 'dewpoint',
    # The sensor's own pressure, not reduced to sea level, which is what WeeWX means
    # by 'pressure'. It derives 'barometer' from this and the altitude in weewx.conf.
    'pressure': 'pressure',
    # How the sensor is doing, rather than what the air is doing.
    'rssi': 'signal1',
    'uptime': 'purple_uptime',
    'current_temp_f_680': 'purple_temp_680',
}

GROUPS = {
    'pm1_0_b': 'group_concentration',
    'pm2_5_b': 'group_concentration',
    'pm10_0_b': 'group_concentration',
    'pm2_5_cf_1': 'group_concentration',
    'pm2_5_cf_1_b': 'group_concentration',
    # An index, which is a number and nothing else. WeeWX has no group for one, and
    # group_count is what the rest of this driver uses for such a reading.
    'pm2_5_aqi': 'group_count',
    'pm2_5_aqi_b': 'group_count',
    'purple_uptime': 'group_deltatime',
    'purple_temp_680': 'group_temperature',
}

SCALE = {
    # The one reading that is not in the units the rest of the answer is in. The
    # temperatures are Fahrenheit and the pressure is millibars, and this catalog is
    # read as US, where pressure is inches of mercury.
    'pressure': 0.02952998,
}

# What names the sensor rather than measures anything.
METADATA = frozenset(
    [
        'SensorId',
        'DateTime',
        'Geo',
        'Mem',
        'memfrag',
        'memfb',
        'memcs',
        'Id',
        'lat',
        'lon',
        'Adc',
        'loggingrate',
        'place',
        'version',
        'hardwareversion',
        'hardwarediscovered',
        'hardware',
        'status',
        'ssid',
        'key1_response',
        'key1_response_date',
        'key1_count',
        'key2_response',
        'key2_response_date',
        'key2_count',
        'key1_response_b',
        'key1_response_date_b',
        'key1_count_b',
        'key2_response_b',
        'key2_response_date_b',
        'key2_count_b',
        'wlstate',
        'status_0',
        'status_1',
        'status_2',
        'status_3',
        'status_4',
        'status_5',
        'status_6',
        'status_7',
        'status_8',
        'status_9',
        'response',
        'response_date',
        'latency',
        'httpsuccess',
        'httpsends',
        'period',
    ]
)
