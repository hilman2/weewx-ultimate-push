#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""What rtl_433 calls a reading, and where it belongs in WeeWX.

rtl_433 listens on 433, 868 and 915 MHz and decodes about 250 kinds of cheap
sensor. It does the hard part, which is the radio, and hands over named JSON. This
says where those names go.

Two things make this catalog much shorter than the number of decoders suggests.

**The unit is in the name.** rtl_433 writes `temperature_C` or `temperature_F`,
`wind_avg_m_s` or `wind_avg_km_h` or `wind_avg_mi_h`, and its own documentation
fixes that as the rule: `<Type>_<Unit>`. So the units are not a thing anybody has to
know per device. The protocol converts them from the suffix before this table is
consulted, which is why only the metric names appear here.

**Most decoders send the same few readings.** Of the 531 names rtl_433 can emit,
some 400 come from exactly one decoder, and nearly all of those are tyre pressure
sensors, doorbells and car remotes. What is left for weather is the list below. A
name that is not here still arrives: it is prefixed and shown in the web interface,
where it can be placed with a dropdown, which is less work than editing a table.

`tools/check_rtl433.py` reads a stated release of rtl_433 and says which names it
can emit that this does not place, so that a new release is a list to look at
rather than something to notice a year later.

Source: rtl_433 25.12, docs/DATA_FORMAT.md and src/devices/*.c.
        https://github.com/merbanan/rtl_433
"""

# Everything here is the metric name, because the protocol has already converted.
# See protocols/rtl433.py, which does the arithmetic the suffixes describe.
FIELDS = {
    'temperature_C': 'outTemp',
    'humidity': 'outHumidity',
    # A few decoders carry more than one probe on one transmitter. These are that
    # transmitter's own extra channels and have nothing to do with this driver's
    # channels, which separate one station from another.
    'temperature_1_C': 'extraTemp1',
    'temperature_2_C': 'extraTemp2',
    'temperature_3_C': 'extraTemp3',
    'temperature_4_C': 'extraTemp4',
    'humidity_1': 'extraHumid1',
    'humidity_2': 'extraHumid2',
    'temp1_C': 'extraTemp1',
    'temp2_C': 'extraTemp2',
    'temp3_C': 'extraTemp3',
    'temp4_C': 'extraTemp4',
    'temp5_C': 'extraTemp5',
    'temp6_C': 'extraTemp6',
    # Wind. m/s is what METRICWX keeps these columns in, so nothing is scaled.
    'wind_avg_m_s': 'windSpeed',
    'wind_max_m_s': 'windGust',
    'wind_dir_deg': 'windDir',
    # The station's own pressure, not reduced to sea level. WeeWX derives
    # 'barometer' from this and the altitude in weewx.conf.
    'pressure_hPa': 'pressure',
    # A running total on nearly every one of these gauges, which is what dayRain is
    # for. See rain_counter in the protocol.
    'rain_mm': 'dayRain',
    'rain_rate_mm_h': 'rainRate',
    'light_lux': 'illuminance',
    # One decoder says 'lux' where the rest say 'light_lux'. weewx-sdr reads it the
    # same way, which is as close to a second opinion as there is.
    'lux': 'illuminance',
    'uvi': 'UV',
    'uv_index': 'UV',
    'moisture': 'soilMoist1',
    'co2_ppm': 'co2',
    'pm1_ug_m3': 'pm1_0',
    'pm2_5_ug_m3': 'pm2_5',
    'pm10_0_ug_m3': 'pm10_0',
    'pm10_ug_m3': 'pm10_0',
    # Strikes since the last message, and how far off the nearest was.
    'strike_count': 'lightning_strike_count',
    'strike_distance': 'lightning_distance',
    'storm_dist_km': 'lightning_distance',
    # Whether the transmitter's battery is still good. rtl_433 sends 1 for good and
    # WeeWX means the opposite by this column, so the protocol turns it round.
    'battery_ok': 'txBatteryStatus',
    'battery_V': 'txBatteryVoltage',
    'rssi': 'signal1',
}

# Looked at and left alone. Written down so that the next person to run
# tools/check_rtl433.py does not have to work through them again.
#
#   rain, rainfall      An amount with no unit in the name, from decoders that do
#                       not follow rtl_433's own rule. Guessing between millimetres
#                       and inches would be wrong half the time and silent.
#   light, light_lvl    A number with no unit and no scale. Not lux.
#   depth_cm            A tank or a well, not the weather.
#   setpoint_C          What a thermostat has been asked for, not a measurement.
#   is_raining, leak_detected, leaking
#                       Flags. Real readings, and there is no column for them in
#                       the standard schema, so they arrive prefixed and can be
#                       placed by hand where somebody has made one.
#   estimated_*         A decoder's own estimate rather than a reading. Recorded
#                       prefixed, so it is visible and not mistaken for measured.
#   average_*_1h, maximum_*_24h and the rest
#                       Statistics a sensor worked out for itself. WeeWX computes
#                       its own from what it recorded, and two of them in one
#                       database would be two answers to one question.

GROUPS = {
    'txBatteryVoltage': 'group_volt',
    'illuminance': 'group_illuminance',
    'co2': 'group_fraction',
}

# Names that say which sensor sent a message, or how the radio heard it, rather
# than measuring anything. 'id' and 'channel' are here because they are what tells
# one sensor from the next, and the protocol uses them for exactly that.
METADATA = frozenset(
    [
        'time',
        'model',
        'id',
        'channel',
        'subtype',
        'type',
        'mic',
        'protocol',
        'mod',
        'freq',
        'freq1',
        'freq2',
        'snr',
        'noise',
        'sequence_num',
        'message_type',
        'msg_type',
        'flags',
        'raw',
        'data',
        'code',
        'unknown',
        'state',
        'status',
        'event',
        'button',
        'longpress',
        'tamper',
        'alarm',
        'startup',
        'counter',
        'seq',
        'test',
        'transmit',
        'exception',
        'rfi',
        'active',
        'command',
        'radio_clock',
        'maybe_battery',
        'newbattery',
        'battery',
        'battery_low',
        'battery_mV',
        'battery_pct',
        'ext_power',
        'uv_sensor_id',
        'uv_status',
        'sensor_id',
        'ws_id',
        'sid',
        'house_code',
        'temperature_type',
        'temperature_alert',
        'temperature_alarm',
        'rain_start',
        'wind_approach',
        'solar_off',
    ]
)
