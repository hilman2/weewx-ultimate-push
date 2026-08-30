#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""What Home Assistant calls a reading, and where it belongs in WeeWX.

Every other catalog here is a list of field names, one per reading the hardware can
send, and it grows every time the manufacturer adds a sensor. This one cannot be
that, and does not need to be. Home Assistant already knows what each of its sensors
measures and what unit it is in, and it says so with every reading:

    {"entity_id": "sensor.balkon_temperatur",
     "state": "-3.9",
     "attributes": {"unit_of_measurement": "°C",
                    "device_class": "temperature",
                    "friendly_name": "Balkon Temperatur"}}

So there is no table of names to write and none to keep up to date. What is needed is
the other half: which WeeWX column a temperature belongs in, and what to multiply a
Fahrenheit reading by. That is the whole of this file, and it is the same size for one
integration as for all of them.

**The names below are device classes, not field names.** `temperature` here is Home
Assistant's `device_class: temperature`, whatever the entity happens to be called.
The protocol turns each entity into a reading under the name of its class, which is
what makes this table twenty lines rather than twenty thousand.

**Everything is converted before it is placed.** The catalog is read as METRICWX, so
the target of every conversion is what WeeWX keeps that column in when it is reading
METRICWX: Celsius, millibars, millimetres, metres per second. See protocols/
homeassistant.py, which does the arithmetic.

Source: home-assistant/core, read on 31-Aug-2026.
        homeassistant/components/sensor/const.py, SensorDeviceClass and
        DEVICE_CLASS_UNITS; homeassistant/const.py, the UnitOf* enumerations.
        https://github.com/home-assistant/core
"""

# Device class to the WeeWX field a reading of that class fills.
#
# One entry per class, and one class per column: this is the first reading of that
# class on the device, and there is nothing here about the second. What happens to a
# second temperature on one device is the protocol's business, not the catalog's, and
# is explained there.
FIELDS = {
    'temperature': 'outTemp',
    'humidity': 'outHumidity',
    # The station's own pressure, not reduced to sea level. WeeWX derives
    # 'barometer' from this and the altitude in weewx.conf. Both classes land here:
    # Home Assistant added `atmospheric_pressure` to separate a barometer from a
    # tyre gauge, and an integration that predates it still says `pressure`.
    'atmospheric_pressure': 'pressure',
    'pressure': 'pressure',
    'wind_speed': 'windSpeed',
    'wind_direction': 'windDir',
    # A depth. Nearly every integration that reports one reports a running total,
    # which is what dayRain is for; see rain_counter in the protocol.
    'precipitation': 'dayRain',
    'precipitation_intensity': 'rainRate',
    'illuminance': 'illuminance',
    'irradiance': 'radiation',
    # A percentage, which is what a soil probe reports and what WeeWX means by this
    # column once GROUPS below has said so.
    'moisture': 'soilMoist1',
    'pm1': 'pm1_0',
    'pm25': 'pm2_5',
    'pm4': 'pm4_0',
    'pm10': 'pm10_0',
    'aqi': 'aqi',
    'carbon_dioxide': 'co2',
    'ozone': 'o3',
    'nitrogen_dioxide': 'no2',
    'sulphur_dioxide': 'so2',
    'sound_pressure': 'noise',
    # A percentage, so not batteryStatus1: that column is a fault flag and WeeWX
    # reports on it as one. Forty per cent of a battery is not forty faults.
    'battery': 'batteryPercent',
    # The one voltage column in the standard schema that does not claim to know
    # which voltage it is. A `voltage` entity on a weather device is usually the
    # sensor's supply and is sometimes the mains, and nothing in the reading says
    # which, so the neutral column is the honest one.
    'voltage': 'supplyVoltage',
    # WeeWX has no column for a bare distance, and lightning_distance would be a
    # guess: a distance on a device Home Assistant reads is as likely to be a snow
    # depth or a tank level. Given a group, so that somebody who makes a column for
    # it gets it written in kilometres.
    'distance': 'distance',
}

# Looked at and left out. Written down so that the next person to read Home
# Assistant's device class list does not have to work through them again.
#
#   absolute_humidity   Grams or milligrams per cubic metre. WeeWX has no unit group
#                       for either, and the one concentration group it has is
#                       micrograms per cubic metre, where a room's absolute humidity
#                       is seven million. It arrives prefixed instead, and the web
#                       interface can place it where somebody has made a column.
#   carbon_monoxide, nitrogen_monoxide, volatile_organic_compounds, radon
#                       Air quality, and real readings, but every one of them can
#                       arrive as a mass concentration or as a volume fraction, and
#                       the columns WeeWX has for them are one or the other. See the
#                       note about that below. They arrive prefixed.
#   signal_strength     How well Home Assistant hears the device, which is a fact
#                       about the radio and not about the weather. Other protocols
#                       here place an RSSI because the sensor sends it beside its
#                       readings; here it is an entity of its own that somebody
#                       would have to choose, and nobody would.
#   ph, conductivity, water, gas, energy, power and the rest
#                       Home Assistant reads a great deal that is not weather. A
#                       class that is not in FIELDS is not refused; it arrives
#                       prefixed and can be placed by hand.
#   enum, date, timestamp
#                       Not numbers at all.

# What WeeWX keeps each of these columns in, once the reading is placed. The unit
# strings are Home Assistant's own, character for character, because that is what
# arrives in `unit_of_measurement` and what has to be matched against.
#
# A class with no entry takes whatever unit it is given: `%` and `°` have one form
# each, and an air quality index has no unit at all.
UNITS = {
    'temperature': '°C',
    'atmospheric_pressure': 'hPa',
    'pressure': 'hPa',
    'wind_speed': 'm/s',
    'precipitation': 'mm',
    'precipitation_intensity': 'mm/h',
    'illuminance': 'lx',
    'irradiance': 'W/m²',
    'pm1': 'μg/m³',
    'pm25': 'μg/m³',
    'pm4': 'μg/m³',
    'pm10': 'μg/m³',
    'carbon_dioxide': 'ppm',
    'ozone': 'ppm',
    'nitrogen_dioxide': 'μg/m³',
    'sulphur_dioxide': 'ppm',
    'sound_pressure': 'dB',
    'voltage': 'V',
    'distance': 'km',
}

# How to get from the unit that arrived to the unit the column is kept in, as
# {wanted: {arrived: (multiply by, then add)}}.
#
# A unit that is spelled the way the target is spelled is not in here: the protocol
# leaves such a reading alone. What is here is every other unit the classes above can
# arrive in, and nothing that they cannot.
#
# Nor is anything that cannot be converted by arithmetic. The two that come up:
#
#   Beaufort            A scale of ranges, not a unit. Force 5 is anything from 8.0
#                       to 10.7 metres a second, and picking a number out of that
#                       range is inventing a reading rather than converting one.
#   ppb, ppm to μg/m³    Depends on the temperature and the pressure the gas is at.
#                       The usual factor assumes 25 °C and 1013 hPa, which is neither
#                       stated in the reading nor true of outdoor air, so a column
#                       would hold a number nobody could check. Left unconverted.
#
# A reading whose unit is not here keeps its unit in its name and is placed by hand.
# See the protocol.
CONVERT = {
    '°C': {
        '°F': (5.0 / 9.0, -160.0 / 9.0),
        'K': (1.0, -273.15),
    },
    # WeeWX keeps group_pressure in millibars, which is a hectopascal under an older
    # name, so hPa is the target and mbar converts by one.
    'hPa': {
        'mbar': (1.0, 0.0),
        'cbar': (10.0, 0.0),
        'bar': (1000.0, 0.0),
        'kPa': (10.0, 0.0),
        'Pa': (0.01, 0.0),
        'mPa': (1e-5, 0.0),
        'mmHg': (1.3332239, 0.0),
        'inHg': (33.863886, 0.0),
        'psi': (68.947573, 0.0),
        'inH₂O': (2.4908891, 0.0),
    },
    'm/s': {
        'km/h': (1.0 / 3.6, 0.0),
        'mph': (0.44704, 0.0),
        'kn': (1852.0 / 3600.0, 0.0),
        'ft/s': (0.3048, 0.0),
        'in/s': (0.0254, 0.0),
        'm/min': (1.0 / 60.0, 0.0),
        'mm/s': (0.001, 0.0),
    },
    'mm': {
        'cm': (10.0, 0.0),
        'in': (25.4, 0.0),
    },
    'mm/h': {
        'mm/d': (1.0 / 24.0, 0.0),
        'in/h': (25.4, 0.0),
        'in/d': (25.4 / 24.0, 0.0),
    },
    'W/m²': {
        'BTU/(h⋅ft²)': (3.154591, 0.0),
    },
    'ppm': {
        'ppb': (0.001, 0.0),
    },
    'V': {
        'mV': (0.001, 0.0),
        'μV': (1e-6, 0.0),
        'kV': (1000.0, 0.0),
        'MV': (1e6, 0.0),
    },
    'km': {
        'mm': (1e-6, 0.0),
        'cm': (1e-5, 0.0),
        'm': (0.001, 0.0),
        'in': (2.54e-5, 0.0),
        'ft': (3.048e-4, 0.0),
        'yd': (9.144e-4, 0.0),
        'mi': (1.609344, 0.0),
        'nmi': (1.852, 0.0),
    },
    # A-weighted decibels are decibels through a filter that follows the ear. The
    # number is on the same scale, so nothing is multiplied; what changes is what
    # was measured, and no arithmetic can undo that.
    'dB': {
        'dBA': (1.0, 0.0),
    },
}

# Unit groups for the fields WeeWX has no column for, and for the two it has a
# column for and means something else by.
GROUPS = {
    # WeeWX means centibars of tension by soilMoist1, because that is what a Davis
    # probe measures. Home Assistant's `moisture` is a percentage, and every other
    # catalog here that meets one says so in the same way.
    'soilMoist1': 'group_percent',
    'pm4_0': 'group_concentration',
    # An index, which is a number and nothing else. WeeWX has no group for one, and
    # group_count is what the rest of this driver uses for such a reading.
    'aqi': 'group_count',
    'batteryPercent': 'group_percent',
    'distance': 'group_distance',
}

# What the assembled answer says about itself rather than measures. The protocol
# builds its own readings out of the entities, so nothing here reaches the mapper by
# accident; this is for anything that reads the body as it stands.
METADATA = frozenset(
    [
        'homeassistant',
        'entities',
    ]
)
