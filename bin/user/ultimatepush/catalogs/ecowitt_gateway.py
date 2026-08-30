#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""What an Ecowitt gateway answers with over its own API, and where it belongs.

The same hardware as `catalogs/ecowitt.py` and not one name in common with it. That
catalog is what a console uploads over HTTP; this is what the same box answers when
it is asked on TCP port 45000, and Ecowitt named the two sets separately:

    over HTTP        tempinf   tempf   baromabsin   dailyrainin
    over the API     intemp    outtemp absbaro      rainday

So there are two catalogs rather than one with two spellings, and neither has to know
about the other. Somebody running both gets the same columns from either, which is
the one thing that had to be true and is why the placements here are copied from
there rather than decided again.

The names are the document's. Every one is an ITEM_ constant from Ecowitt's *TCP API
Interface Communication Protocol* V1.7.0, lowercased with the prefix taken off, so a
line here and a line of the document can be read side by side. Where one address
carries several readings the document's own names for the parts are used.

Units are fixed by the API and are the same on every device, whatever the console's
display is set to: Celsius, hPa, millimetres, metres per second, micrograms per cubic
metre. That is METRICWX, and the only reading that is not in the unit WeeWX keeps its
column in is the light one, which is in SCALE.

Source: Ecowitt, *TCP API Interface Communication Protocol*, V1.7.0, 2024-05-27.
        https://oss.ecowitt.net/uploads/20260112/TCP%20API%20Interface%20Communication%20Protocol%20V1.7.0.pdf
"""

FIELDS = {
    # The console's own thermometer, hygrometer and barometer. `absbaro` is the
    # pressure where the console is, which is what WeeWX means by 'pressure', and
    # `relbaro` is the console's own reduction of it to sea level.
    'intemp': 'inTemp',
    'outtemp': 'outTemp',
    'inhumi': 'inHumidity',
    'outhumi': 'outHumidity',
    'absbaro': 'pressure',
    'relbaro': 'barometer',
    # Worked out by the console rather than measured. Kept because WeeWX has a column
    # for each and a console that has done the arithmetic has done it from readings
    # taken at the same instant.
    'dewpoint': 'dewpoint',
    'windchill': 'windchill',
    'heatindex': 'heatindex',
    # Wind. `daylwindmax` is the highest gust since midnight, which is a different
    # thing from the gust in this reading.
    'winddirection': 'windDir',
    'windspeed': 'windSpeed',
    'gustspeed': 'windGust',
    'daylwindmax': 'maxdailygust',
    # The tipping bucket. Every one of these is a counter that only goes up until it
    # resets, which is what StdDelta differences to get the rain in a packet.
    'rainrate': 'rainRate',
    'rainevent': 'eventRain',
    'rainday': 'dayRain',
    'rainweek': 'weekRain',
    'rainmonth': 'monthRain',
    'rainyear': 'yearRain',
    'raintotals': 'totalRain',
    # The piezo gauge on a WS90, which counts separately and is reported separately.
    # A console has one gauge or the other or both, and which of them it believes is
    # `rain_priority`, which is a setting rather than a reading and is left below.
    'piezo_rainrate': 'hailRate',
    'piezo_rainevent': 'erain_piezo',
    'piezo_rainhour': 'hrain_piezo',
    'piezo_rainday': 'drain_piezo',
    'piezo_rainweek': 'wrain_piezo',
    'piezo_rainmonth': 'mrain_piezo',
    'piezo_rainyear': 'yrain_piezo',
    # The light sensor. The API answers in lux and WeeWX keeps this column in watts
    # per square metre; see SCALE.
    'light': 'radiation',
    'uvi': 'UV',
    # WH31 thermo-hygrometers, up to eight of them.
    'temp1': 'extraTemp1',
    'temp2': 'extraTemp2',
    'temp3': 'extraTemp3',
    'temp4': 'extraTemp4',
    'temp5': 'extraTemp5',
    'temp6': 'extraTemp6',
    'temp7': 'extraTemp7',
    'temp8': 'extraTemp8',
    'humi1': 'extraHumid1',
    'humi2': 'extraHumid2',
    'humi3': 'extraHumid3',
    'humi4': 'extraHumid4',
    'humi5': 'extraHumid5',
    'humi6': 'extraHumid6',
    'humi7': 'extraHumid7',
    'humi8': 'extraHumid8',
    # WH51 soil moisture probes, up to sixteen.
    'soilmoisture1': 'soilMoist1',
    'soilmoisture2': 'soilMoist2',
    'soilmoisture3': 'soilMoist3',
    'soilmoisture4': 'soilMoist4',
    'soilmoisture5': 'soilMoist5',
    'soilmoisture6': 'soilMoist6',
    'soilmoisture7': 'soilMoist7',
    'soilmoisture8': 'soilMoist8',
    'soilmoisture9': 'soilMoist9',
    'soilmoisture10': 'soilMoist10',
    'soilmoisture11': 'soilMoist11',
    'soilmoisture12': 'soilMoist12',
    'soilmoisture13': 'soilMoist13',
    'soilmoisture14': 'soilMoist14',
    'soilmoisture15': 'soilMoist15',
    'soilmoisture16': 'soilMoist16',
    # WH34 temperature probes: pool, soil, whatever they are clipped to. The same
    # placement the HTTP catalog gives `tf_ch1`, which is extraTemp and not soilTemp,
    # because a probe on a pool lead is not a soil temperature.
    'tf_usr1': 'extraTemp9',
    'tf_usr2': 'extraTemp10',
    'tf_usr3': 'extraTemp11',
    'tf_usr4': 'extraTemp12',
    'tf_usr5': 'extraTemp13',
    'tf_usr6': 'extraTemp14',
    'tf_usr7': 'extraTemp15',
    'tf_usr8': 'extraTemp16',
    # WH35 leaf wetness.
    'leaf_wetness_ch1': 'leafWet1',
    'leaf_wetness_ch2': 'leafWet2',
    'leaf_wetness_ch3': 'leafWet3',
    'leaf_wetness_ch4': 'leafWet4',
    'leaf_wetness_ch5': 'leafWet5',
    'leaf_wetness_ch6': 'leafWet6',
    'leaf_wetness_ch7': 'leafWet7',
    'leaf_wetness_ch8': 'leafWet8',
    # WH41 particle sensors, and the running day's average of each.
    'pm25_ch1': 'pm25_1',
    'pm25_ch2': 'pm25_2',
    'pm25_ch3': 'pm25_3',
    'pm25_ch4': 'pm25_4',
    'pm25_24havg1': 'pm25_avg_24h_ch1',
    'pm25_24havg2': 'pm25_avg_24h_ch2',
    'pm25_24havg3': 'pm25_avg_24h_ch3',
    'pm25_24havg4': 'pm25_avg_24h_ch4',
    # WH55 leak detectors.
    'leak_ch1': 'leak_1',
    'leak_ch2': 'leak_2',
    'leak_ch3': 'leak_3',
    'leak_ch4': 'leak_4',
    # WH57 lightning. `lightning_power` is the count today, which is what the HTTP
    # catalog calls lightning_num, and `lightning_time` is when the last strike was.
    'lightning': 'lightning_distance',
    'lightning_time': 'lightning_time',
    'lightning_power': 'lightning_num',
    # WH45 and WH46, the CO2 combination sensors. The WH46 sends the same readings
    # with four more particle sizes on the end, so both arrive under these names.
    'tf_co2': 'co2_Temp',
    'humi_co2': 'co2_Hum',
    'co2': 'co2',
    'co2_24h': 'co2_24h',
    'pm1_co2': 'pm1_0',
    'pm25_co2': 'pm2_5',
    'pm4_co2': 'pm4_0',
    'pm10_co2': 'pm10_0',
    'pm1_24h_co2': 'pm1_24h_co2',
    'pm25_24h_co2': 'pm25_24h_co2',
    'pm4_24h_co2': 'pm4_24h_co2',
    'pm10_24h_co2': 'pm10_24h_co2',
    # The gateway itself.
    'heap_free': 'heap',
    # Battery and signal, one pair per sensor the gateway has registered. These come
    # from the sensor list rather than from the live data, which is why a sensor with
    # no reading in this packet still says whether its battery is going.
    #
    # The placements are the HTTP catalog's, sensor for sensor, so that the same
    # hardware read the other way keeps the same columns. That is also why a WH65 and
    # a WH68 share one: a station has one or the other.
    'wh65_batt': 'outTempBatteryStatus',
    'wh65_sig': 'wh65_sig',
    'wh68_batt': 'outTempBatteryStatus',
    'wh68_sig': 'wh68_sig',
    'wh80_batt': 'windBatteryStatus',
    'wh80_sig': 'ws80_sig',
    'wh90_batt': 'hailBatteryStatus',
    'wh90_sig': 'ws90_sig',
    'wh40_batt': 'rainBatteryStatus',
    'wh40_sig': 'wh40_sig',
    'wh25_batt': 'inTempBatteryStatus',
    'wh25_sig': 'wh25_sig',
    'wh26_batt': 'wh26_batt',
    'wh26_sig': 'wh26_sig',
    'wh45_batt': 'co2_Batt',
    'wh45_sig': 'wh45_sig',
    'wh57_batt': 'lightning_Batt',
    'wh57_sig': 'wh57_sig',
    'wh31_ch1_batt': 'batteryStatus1',
    'wh31_ch2_batt': 'batteryStatus2',
    'wh31_ch3_batt': 'batteryStatus3',
    'wh31_ch4_batt': 'batteryStatus4',
    'wh31_ch5_batt': 'batteryStatus5',
    'wh31_ch6_batt': 'batteryStatus6',
    'wh31_ch7_batt': 'batteryStatus7',
    'wh31_ch8_batt': 'batteryStatus8',
    'wh31_ch1_sig': 'wh31_ch1_sig',
    'wh31_ch2_sig': 'wh31_ch2_sig',
    'wh31_ch3_sig': 'wh31_ch3_sig',
    'wh31_ch4_sig': 'wh31_ch4_sig',
    'wh31_ch5_sig': 'wh31_ch5_sig',
    'wh31_ch6_sig': 'wh31_ch6_sig',
    'wh31_ch7_sig': 'wh31_ch7_sig',
    'wh31_ch8_sig': 'wh31_ch8_sig',
    'wh51_ch1_batt': 'soilMoistBatt1',
    'wh51_ch2_batt': 'soilMoistBatt2',
    'wh51_ch3_batt': 'soilMoistBatt3',
    'wh51_ch4_batt': 'soilMoistBatt4',
    'wh51_ch5_batt': 'soilMoistBatt5',
    'wh51_ch6_batt': 'soilMoistBatt6',
    'wh51_ch7_batt': 'soilMoistBatt7',
    'wh51_ch8_batt': 'soilMoistBatt8',
    'wh51_ch1_sig': 'wh51_ch1_sig',
    'wh51_ch2_sig': 'wh51_ch2_sig',
    'wh51_ch3_sig': 'wh51_ch3_sig',
    'wh51_ch4_sig': 'wh51_ch4_sig',
    'wh51_ch5_sig': 'wh51_ch5_sig',
    'wh51_ch6_sig': 'wh51_ch6_sig',
    'wh51_ch7_sig': 'wh51_ch7_sig',
    'wh51_ch8_sig': 'wh51_ch8_sig',
    'wh41_ch1_batt': 'pm25_Batt1',
    'wh41_ch2_batt': 'pm25_Batt2',
    'wh41_ch3_batt': 'pm25_Batt3',
    'wh41_ch4_batt': 'pm25_Batt4',
    'wh41_ch1_sig': 'wh41_ch1_sig',
    'wh41_ch2_sig': 'wh41_ch2_sig',
    'wh41_ch3_sig': 'wh41_ch3_sig',
    'wh41_ch4_sig': 'wh41_ch4_sig',
    'wh55_ch1_batt': 'leak_Batt1',
    'wh55_ch2_batt': 'leak_Batt2',
    'wh55_ch3_batt': 'leak_Batt3',
    'wh55_ch4_batt': 'leak_Batt4',
    'wh55_ch1_sig': 'wh55_ch1_sig',
    'wh55_ch2_sig': 'wh55_ch2_sig',
    'wh55_ch3_sig': 'wh55_ch3_sig',
    'wh55_ch4_sig': 'wh55_ch4_sig',
    'wh34_ch1_batt': 'wn34_ch1_batt',
    'wh34_ch2_batt': 'wn34_ch2_batt',
    'wh34_ch3_batt': 'wn34_ch3_batt',
    'wh34_ch4_batt': 'wn34_ch4_batt',
    'wh34_ch5_batt': 'wn34_ch5_batt',
    'wh34_ch6_batt': 'wn34_ch6_batt',
    'wh34_ch7_batt': 'wn34_ch7_batt',
    'wh34_ch8_batt': 'wn34_ch8_batt',
    'wh34_ch1_sig': 'wn34_ch1_sig',
    'wh34_ch2_sig': 'wn34_ch2_sig',
    'wh34_ch3_sig': 'wn34_ch3_sig',
    'wh34_ch4_sig': 'wn34_ch4_sig',
    'wh34_ch5_sig': 'wn34_ch5_sig',
    'wh34_ch6_sig': 'wn34_ch6_sig',
    'wh34_ch7_sig': 'wn34_ch7_sig',
    'wh34_ch8_sig': 'wn34_ch8_sig',
    'wh35_ch1_batt': 'leafWetBatt1',
    'wh35_ch2_batt': 'leafWetBatt2',
    'wh35_ch3_batt': 'leafWetBatt3',
    'wh35_ch4_batt': 'leafWetBatt4',
    'wh35_ch5_batt': 'leafWetBatt5',
    'wh35_ch6_batt': 'leafWetBatt6',
    'wh35_ch7_batt': 'leafWetBatt7',
    'wh35_ch8_batt': 'leafWetBatt8',
    'wh35_ch1_sig': 'wn35_ch1_sig',
    'wh35_ch2_sig': 'wn35_ch2_sig',
    'wh35_ch3_sig': 'wn35_ch3_sig',
    'wh35_ch4_sig': 'wn35_ch4_sig',
    'wh35_ch5_sig': 'wn35_ch5_sig',
    'wh35_ch6_sig': 'wn35_ch6_sig',
    'wh35_ch7_sig': 'wn35_ch7_sig',
    'wh35_ch8_sig': 'wn35_ch8_sig',
    # Everything the gateway sends that is not here is read and is not placed. It
    # arrives under a name of its own with 'ecowitt_gateway_' in front of it, where
    # it shows on the page of raw uploads and can be given a column by hand. What is
    # in that list and why:
    #
    #   soiltemp1 to soiltemp16   The API pairs a temperature with every soil
    #                             moisture channel and no sensor Ecowitt sells fills
    #                             it in. Placing it would claim a reading that is
    #                             not there.
    #   uv                        Irradiance in microwatts per square metre, which
    #                             is not the UV index and has no WeeWX column.
    #                             `uvi` beside it is the index and is placed.
    #   tf_usr1_batt to _8_batt   The same battery the sensor list reports, sent a
    #   co2_batt                  second time inside the reading. One of the two is
    #                             placed and it is the sensor list's, so that every
    #                             sensor's battery comes from one place.
    #   rain_gain, piezo_gain0    Calibration and reset settings rather than
    #   to piezo_gain9,           readings. They say how the gauge is configured, and
    #   rain_priority,            recording them every minute would fill a column
    #   radcompensation,          with a constant.
    #   rst_rainday_time,
    #   rst_rainweek_time,
    #   rst_rainyear_time
    #   aqi_pm25 and its five     Air quality indexes the document marks for Ambient
    #   relatives                 consoles only. Read so that the reading after them
    #                             is not misplaced; not given a column, because an
    #                             index derived from a concentration that is already
    #                             recorded is worked out and not measured.
}

# WeeWX field -> unit group, for the fields that are not already in the WeeWX schema.
# The same groups the HTTP catalog gives the same columns, because the same column
# holding two units depending on which way it was read would be worse than either.
GROUPS = {
    'co2': 'group_fraction',
    'co2_24h': 'group_fraction',
    'co2_Batt': 'group_count',
    'co2_Hum': 'group_percent',
    'co2_Temp': 'group_temperature',
    'drain_piezo': 'group_rain',
    'erain_piezo': 'group_rain',
    'eventRain': 'group_rain',
    'extraTemp9': 'group_temperature',
    'extraTemp10': 'group_temperature',
    'extraTemp11': 'group_temperature',
    'extraTemp12': 'group_temperature',
    'extraTemp13': 'group_temperature',
    'extraTemp14': 'group_temperature',
    'extraTemp15': 'group_temperature',
    'extraTemp16': 'group_temperature',
    'heap': 'group_data',
    'hailBatteryStatus': 'group_volt',
    'leafWet1': 'group_percent',
    'leafWet2': 'group_percent',
    'leafWet3': 'group_percent',
    'leafWet4': 'group_percent',
    'leafWet5': 'group_percent',
    'leafWet6': 'group_percent',
    'leafWet7': 'group_percent',
    'leafWet8': 'group_percent',
    'hrain_piezo': 'group_rain',
    'leafWetBatt1': 'group_volt',
    'leafWetBatt2': 'group_volt',
    'leafWetBatt3': 'group_volt',
    'leafWetBatt4': 'group_volt',
    'leafWetBatt5': 'group_volt',
    'leafWetBatt6': 'group_volt',
    'leafWetBatt7': 'group_volt',
    'leafWetBatt8': 'group_volt',
    'leak_1': 'group_count',
    'leak_2': 'group_count',
    'leak_3': 'group_count',
    'leak_4': 'group_count',
    'leak_Batt1': 'group_count',
    'leak_Batt2': 'group_count',
    'leak_Batt3': 'group_count',
    'leak_Batt4': 'group_count',
    'lightning_Batt': 'group_count',
    'lightning_distance': 'group_distance',
    'lightning_num': 'group_count',
    'lightning_time': 'group_time',
    'maxdailygust': 'group_speed2',
    'mrain_piezo': 'group_rain',
    'pm10_0': 'group_concentration',
    'pm2_5': 'group_concentration',
    'pm10_24h_co2': 'group_concentration',
    'pm1_0': 'group_concentration',
    'pm1_24h_co2': 'group_concentration',
    'pm25_1': 'group_concentration',
    'pm25_2': 'group_concentration',
    'pm25_3': 'group_concentration',
    'pm25_4': 'group_concentration',
    'pm25_24h_co2': 'group_concentration',
    'pm25_Batt1': 'group_count',
    'pm25_Batt2': 'group_count',
    'pm25_Batt3': 'group_count',
    'pm25_Batt4': 'group_count',
    'pm25_avg_24h_ch1': 'group_concentration',
    'pm25_avg_24h_ch2': 'group_concentration',
    'pm25_avg_24h_ch3': 'group_concentration',
    'pm25_avg_24h_ch4': 'group_concentration',
    'pm4_0': 'group_concentration',
    'pm4_24h_co2': 'group_concentration',
    'rainBatteryStatus': 'group_volt',
    'soilMoist1': 'group_percent',
    'soilMoist2': 'group_percent',
    'soilMoist3': 'group_percent',
    'soilMoist4': 'group_percent',
    'soilMoist5': 'group_percent',
    'soilMoist6': 'group_percent',
    'soilMoist7': 'group_percent',
    'soilMoist8': 'group_percent',
    'soilMoist9': 'group_percent',
    'soilMoist10': 'group_percent',
    'soilMoist11': 'group_percent',
    'soilMoist12': 'group_percent',
    'soilMoist13': 'group_percent',
    'soilMoist14': 'group_percent',
    'soilMoist15': 'group_percent',
    'soilMoist16': 'group_percent',
    'soilMoistBatt1': 'group_volt',
    'soilMoistBatt2': 'group_volt',
    'soilMoistBatt3': 'group_volt',
    'soilMoistBatt4': 'group_volt',
    'soilMoistBatt5': 'group_volt',
    'soilMoistBatt6': 'group_volt',
    'soilMoistBatt7': 'group_volt',
    'soilMoistBatt8': 'group_volt',
    'weekRain': 'group_rain',
    'wh25_sig': 'group_count',
    'wh26_batt': 'group_count',
    'wh26_sig': 'group_count',
    'wh31_ch1_sig': 'group_count',
    'wh31_ch2_sig': 'group_count',
    'wh31_ch3_sig': 'group_count',
    'wh31_ch4_sig': 'group_count',
    'wh31_ch5_sig': 'group_count',
    'wh31_ch6_sig': 'group_count',
    'wh31_ch7_sig': 'group_count',
    'wh31_ch8_sig': 'group_count',
    'wh40_sig': 'group_count',
    'wh41_ch1_sig': 'group_count',
    'wh41_ch2_sig': 'group_count',
    'wh41_ch3_sig': 'group_count',
    'wh41_ch4_sig': 'group_count',
    'wh45_sig': 'group_count',
    'wh51_ch1_sig': 'group_count',
    'wh51_ch2_sig': 'group_count',
    'wh51_ch3_sig': 'group_count',
    'wh51_ch4_sig': 'group_count',
    'wh51_ch5_sig': 'group_count',
    'wh51_ch6_sig': 'group_count',
    'wh51_ch7_sig': 'group_count',
    'wh51_ch8_sig': 'group_count',
    'wh55_ch1_sig': 'group_count',
    'wh55_ch2_sig': 'group_count',
    'wh55_ch3_sig': 'group_count',
    'wh55_ch4_sig': 'group_count',
    'wh57_sig': 'group_count',
    'wh65_sig': 'group_count',
    'wh68_sig': 'group_count',
    'wn34_ch1_batt': 'group_volt',
    'wn34_ch2_batt': 'group_volt',
    'wn34_ch3_batt': 'group_volt',
    'wn34_ch4_batt': 'group_volt',
    'wn34_ch5_batt': 'group_volt',
    'wn34_ch6_batt': 'group_volt',
    'wn34_ch7_batt': 'group_volt',
    'wn34_ch8_batt': 'group_volt',
    'wn34_ch1_sig': 'group_count',
    'wn34_ch2_sig': 'group_count',
    'wn34_ch3_sig': 'group_count',
    'wn34_ch4_sig': 'group_count',
    'wn34_ch5_sig': 'group_count',
    'wn34_ch6_sig': 'group_count',
    'wn34_ch7_sig': 'group_count',
    'wn34_ch8_sig': 'group_count',
    'wn35_ch1_sig': 'group_count',
    'wn35_ch2_sig': 'group_count',
    'wn35_ch3_sig': 'group_count',
    'wn35_ch4_sig': 'group_count',
    'wn35_ch5_sig': 'group_count',
    'wn35_ch6_sig': 'group_count',
    'wn35_ch7_sig': 'group_count',
    'wn35_ch8_sig': 'group_count',
    'windBatteryStatus': 'group_volt',
    'wrain_piezo': 'group_rain',
    'ws80_sig': 'group_count',
    'ws90_sig': 'group_count',
    'yearRain': 'group_rain',
    'yrain_piezo': 'group_rain',
}

SCALE = {
    # The one reading that is not in the unit WeeWX keeps its column in. The API
    # answers with the light sensor in lux; 'radiation' is watts per square metre.
    #
    # 126.7 lux to the watt is the ratio Ecowitt's own firmware uses to produce the
    # `solarradiation` it uploads over HTTP from the same sensor, so a station read
    # this way and read that way draws the same graph, which is the whole point of
    # having a number here rather than a column of lux nothing plots. It is a
    # convention for daylight rather than a measurement, and it is the same one
    # every reader of this hardware uses. The number below is one over 126.7.
    'light': 0.00789266,
}

# What names the gateway rather than measures anything.
METADATA = frozenset(
    [
        'mac',
        'model',
        'firmware',
        'frequency',
        'sensor_type',
    ]
)
