#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""Hardware that is not there, for trying a setup without owning any.

Two kinds of station cannot be tried before the hardware arrives. A console that
uploads can be imitated with `curl` and hardware on a cable has the WeeWX simulator,
but there is nothing to ask when there is no sensor to ask, and nothing to hear when
there is no receiver.

So there is one of each here.

    python -m user.ultimatepush --fake-purpleair 8081
    python -m user.ultimatepush --fake-airlink 8082

each answer like the sensor they are named after, for a `[[polling]]` source to be
pointed at. The AirLink wraps its readings the way Davis wraps everything, which is
the part of that protocol worth exercising.

    python -m user.ultimatepush --fake-rtl433 1433

sends what rtl_433 sends, three sensors at a time, one of them a neighbour's,
because letting in the ones that are yours is the part worth trying out.

    python -m user.ultimatepush --fake-gw1000 45000

answers an Ecowitt gateway's binary API on a socket. It is the only one of the five
that is not a web server, and the only one that builds its answers rather than
holding them: the frames are encoded out of the same table the driver decodes them
with, so a wrong width in that table shows up as a reading that does not come back.

    python -m user.ultimatepush --fake-homeassistant 8123

answers like Home Assistant's REST API: two devices, one outdoors and one indoors,
a token it insists on, and three entities that are not reporting a number. Those
three are the point. An installation has an unavailable sensor, an unknown one and
one whose battery went flat within a week, and a fake without them would never
exercise the code that deals with any of it.

The tests read the same five, so what is shipped and what is known to work are one
thing rather than two that can drift apart.

Nothing here is a model of anything. The numbers wander around plausible values so
that a graph is not a flat line, and that is the whole of the ambition.
"""

import http.server
import json
import math
import socketserver
from typing import Any, Dict, Tuple

# What the sensor is called. Deliberately not a real MAC: anybody reading a log or a
# page has to be able to tell at a glance that this is not their sensor.
SENSOR_ID = 'aa:bb:cc:00:11:22'

# What each reading sits at, and how far it wanders either side of that. The periods
# are different for each so that two readings do not move together, which is the one
# thing that makes a made-up graph look made up.
WANDERS = {
    'current_temp_f': (71.0, 6.0, 900.0),
    'current_humidity': (44.0, 12.0, 1100.0),
    'current_dewpoint_f': (48.0, 5.0, 1300.0),
    'pressure': (1013.2, 4.0, 3600.0),
    'pm1_0_atm': (4.1, 2.5, 300.0),
    'pm2_5_atm': (7.2, 4.0, 420.0),
    'pm10_0_atm': (8.0, 4.5, 540.0),
    'pm2_5_cf_1': (7.6, 4.0, 420.0),
}


def purpleair_answer(seconds):
    """What a PurpleAir says, at one moment.

    Args:
        seconds (float): The time, in seconds. Any clock will do: the readings are
            a function of it, so the same number twice gives the same answer, which
            is what makes a test repeatable.

    Returns:
        dict: The answer, as the sensor's own /json endpoint gives it.
    """
    answer = {
        'SensorId': SENSOR_ID,
        'DateTime': _stamp(seconds),
        'hardwareversion': '2.0',
        'hardwarediscovered': '2.0+BME280+PMSX003-B+PMSX003-A',
        'version': '7.02',
        'place': 'outside',
        'rssi': -58,
        'uptime': int(seconds) % 1000000,
        'current_temp_f_680': 0,
    }
    for name, (middle, spread, period) in WANDERS.items():
        answer[name] = _wander(seconds, middle, spread, period)
    # The integers the sensor sends as integers. A reader that turns everything into
    # a float would not notice; one that checks the type would.
    for name in ('current_temp_f', 'current_humidity', 'current_dewpoint_f'):
        answer[name] = int(round(answer[name]))
    # The second laser counter, a little behind the first, the way a real pair are.
    answer['pm1_0_atm_b'] = round(answer['pm1_0_atm'] * 0.96, 2)
    answer['pm2_5_atm_b'] = round(answer['pm2_5_atm'] * 0.96, 2)
    answer['pm10_0_atm_b'] = round(answer['pm10_0_atm'] * 0.96, 2)
    answer['pm2_5_cf_1_b'] = round(answer['pm2_5_cf_1'] * 0.96, 2)
    answer['pm2.5_aqi'] = _aqi(answer['pm2_5_atm'])
    answer['pm2.5_aqi_b'] = _aqi(answer['pm2_5_atm_b'])
    return answer


def _wander(seconds, middle, spread, period):
    """One reading, somewhere near where it belongs.

    Two waves of different lengths rather than one, so that the result does not
    repeat every period and look like the sine wave it is.

    Args:
        seconds (float): The time.
        middle (float): What it sits at.
        spread (float): How far either side it goes.
        period (float): Seconds for one turn of the slower wave.

    Returns:
        float: The reading, to two decimals.
    """
    slow = math.sin(2.0 * math.pi * seconds / period)
    quick = math.sin(2.0 * math.pi * seconds / (period / 7.0))
    return round(middle + spread * (0.75 * slow + 0.25 * quick), 2)


def _aqi(micrograms):
    """The US air quality index for a PM2.5 concentration.

    Only the two lowest bands, because a sensor that is making its readings up has
    no business claiming the air is dangerous.

    Args:
        micrograms (float): PM2.5, in micrograms per cubic metre.

    Returns:
        int: The index.
    """
    if micrograms <= 12.0:
        return int(round(micrograms * 50.0 / 12.0))
    return int(round(51 + (micrograms - 12.1) * 49.0 / 23.3))


def _stamp(seconds):
    """The time, written the way this hardware writes it.

    Args:
        seconds (float): The time.

    Returns:
        str: e.g. '2026/08/30T19:04:12z'.
    """
    import time

    return time.strftime('%Y/%m/%dT%H:%M:%Sz', time.gmtime(seconds))


def serve(port, address='127.0.0.1', answer=None, what='purpleair', at='/json'):
    """Answer like a sensor with a local API, until interrupted.

    Args:
        port (int): The port to listen on.
        address (str): The address to bind to. The loopback by default, because a
            sensor that does not exist has no business being on the network.
        answer (Callable[[float], dict] | None): Called as ``answer(seconds)``.
            Returns what the sensor says at that moment. A PurpleAir's when nothing
            is given.
        what (str): The protocol to name in the lines printed at startup.
        at (str): The path the real one answers on, for the same lines.

    Returns:
        int: The exit status, which is 0 unless the port could not be had.
    """
    import time

    if answer is None:
        answer = purpleair_answer

    class Handler(http.server.BaseHTTPRequestHandler):
        """Answers anything with the same reading, which is what the real one does."""

        def do_GET(self):
            body = json.dumps(answer(time.time())).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):
            """One line per question, which is the point of watching this run."""
            print("asked: %s" % (fmt % args))

    try:
        server = socketserver.TCPServer((address, port), Handler)
    except OSError as e:
        print("Cannot listen on %s:%d: %s" % (address, port, e))
        return 1
    print(
        "Answering like a %s at http://%s:%d%s\n"
        "Point a source at it:\n"
        "\n"
        "    [[polling]]\n"
        "        [[[air]]]\n"
        "            address = %s:%d\n"
        "            protocol = %s\n"
        "            interval = 10\n" % (what, address, port, at, address, port, what)
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopped.")
    finally:
        server.server_close()
    return 0


# ---- a receiver hearing sensors that are not there ---------------------------
#
# What rtl_433 puts on a socket, for trying the setup without a stick. Three
# sensors, and one of them is a neighbour's: a real receiver hears everything in
# range, and the part worth trying out is letting in the two that are yours.

# The frame rtl_433 wraps every message in. RFC 5424, and nothing in it is worth
# reading, which is why the driver steps over it.
SYSLOG = '<165>1 %s pretend rtl_433 - - - %s'

# The sensors this pretends to hear. Each is what rtl_433 would say about it, minus
# the readings, which move.
RADIO = (
    {
        'protocol': 40,
        'model': 'Acurite-Tower',
        'id': 11524,
        'channel': 'A',
        'mic': 'CHECKSUM',
        'readings': ('temperature_C', 'humidity'),
    },
    {
        'protocol': 172,
        'model': 'Bresser-6in1',
        'id': 8455,
        'channel': 0,
        'mic': 'CRC',
        'readings': (
            'temperature_C',
            'humidity',
            'wind_avg_m_s',
            'wind_max_m_s',
            'wind_dir_deg',
            'rain_mm',
            'light_lux',
            'uvi',
        ),
    },
    # Somebody else's. Included on purpose: a receiver hears the neighbours, and a
    # driver that quietly recorded them would be worse than one that asks.
    {
        'protocol': 12,
        'model': 'Nexus-TH',
        'id': 57,
        'channel': 1,
        'mic': 'CHECKSUM',
        'readings': ('temperature_C', 'humidity'),
    },
)  # type: Tuple[Dict[str, Any], ...]

# Where the pretend rain gauge started counting. A gauge counts up from the day its
# battery went in and never down, which is what StdDelta needs, so this is a fixed
# moment rather than anything derived from the clock: without it the count would be
# the unix time over ten hours, which is tens of metres of rain.
RAIN_FROM = 1788000000.0

# What each reading sits at, how far it wanders, and over how long.
RADIO_WANDERS = {
    'temperature_C': (14.0, 7.0, 1500.0),
    'humidity': (68.0, 18.0, 1700.0),
    'wind_avg_m_s': (3.2, 2.6, 400.0),
    'wind_max_m_s': (5.4, 3.4, 380.0),
    'wind_dir_deg': (200.0, 140.0, 2600.0),
    'light_lux': (32000.0, 30000.0, 4000.0),
    'uvi': (3.0, 3.0, 4000.0),
}


def rtl433_messages(seconds):
    """What rtl_433 would send at one moment, one datagram per sensor.

    Args:
        seconds (float): The time, in seconds.

    Returns:
        list[bytes]: The datagrams, framed the way rtl_433 frames them.
    """
    out = []
    for index, sensor in enumerate(RADIO):
        # Offset per sensor, so that three of them do not report identical weather.
        when = seconds + index * 137.0
        message = {
            'time': _stamp(seconds),
            'protocol': sensor['protocol'],
            'model': sensor['model'],
            'id': sensor['id'],
            'channel': sensor['channel'],
            'battery_ok': 1,
            'mic': sensor['mic'],
        }
        for name in sensor['readings']:
            if name == 'rain_mm':
                # A tenth of a millimetre an hour, from a fixed start, so that a day
                # of this is a believable amount of rain and it never goes backwards.
                message[name] = round(80.0 + (seconds - RAIN_FROM) / 36000.0, 1)
                continue
            middle, spread, period = RADIO_WANDERS[name]
            message[name] = _wander(when, middle, spread, period)
        if 'humidity' in message:
            message['humidity'] = int(round(message['humidity']))
        if 'uvi' in message:
            message['uvi'] = max(0, int(round(message['uvi'])))
        out.append((SYSLOG % (_stamp(seconds), json.dumps(message))).encode('utf-8'))
    return out


def send_rtl433(port, address='127.0.0.1', every=10.0, rounds=None):
    """Send what rtl_433 would send, until interrupted.

    Args:
        port (int): Where the driver is listening.
        address (str): Where to send. The loopback by default.
        every (float): Seconds between one round of messages and the next.
        rounds (int | None): How many rounds to send, or None for until stopped.

    Returns:
        int: The exit status.
    """
    import socket
    import time

    out = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    print(
        "Sending what rtl_433 sends to %s:%d, every %gs.\n"
        "Three sensors, and one of them is a neighbour's.\n"
        "\n"
        "    [UltimatePush]\n"
        "        protocols = rtl433\n"
        "        udp_port = %d\n" % (address, port, every, port)
    )
    sent = 0
    try:
        while rounds is None or sent < rounds:
            for message in rtl433_messages(time.time()):
                out.sendto(message, (address, port))
            sent += 1
            print("sent round %d" % sent)
            if rounds is not None and sent >= rounds:
                break
            time.sleep(every)
    except KeyboardInterrupt:
        print("Stopped.")
    finally:
        out.close()
    return 0


# ---- a Davis AirLink that is not there --------------------------------------

# What the device calls itself. Davis prints this on the back of the case; this one
# is deliberately not a real one.
AIRLINK_DID = '001D0A000000'

# What each reading sits at, how far it wanders, and over how long. Fahrenheit and
# micrograms per cubic metre, which is what an AirLink reports.
AIRLINK_WANDERS = {
    'temp': (71.6, 6.0, 950.0),
    'hum': (44.2, 12.0, 1150.0),
    'dew_point': (48.9, 5.0, 1350.0),
    'wet_bulb': (57.4, 4.0, 1250.0),
    'heat_index': (70.6, 6.0, 950.0),
    'pm_1': (4.1, 2.5, 320.0),
    'pm_2p5': (7.2, 4.0, 440.0),
    'pm_10': (8.0, 4.5, 560.0),
}


def airlink_answer(seconds):
    """What a Davis AirLink says, at one moment.

    Wrapped the way Davis wraps every local API answer, because unwrapping that is
    the part of this protocol worth exercising.

    Args:
        seconds (float): The time, in seconds.

    Returns:
        dict: The answer, as /v1/current_conditions gives it.
    """
    conditions = {
        'lsid': 405284,
        'data_structure_type': 6,
        'last_report_time': int(seconds),
    }  # type: Dict[str, Any]
    for name, (middle, spread, period) in AIRLINK_WANDERS.items():
        conditions[name] = _wander(seconds, middle, spread, period)
    # The last raw count from the laser is an integer, and the averages are not.
    for name, source in (
        ('pm_1_last', 'pm_1'),
        ('pm_2p5_last', 'pm_2p5'),
        ('pm_10_last', 'pm_10'),
    ):
        conditions[name] = int(round(conditions[source]))
    # The longer averages, each a little flatter than the one before it, which is
    # what averaging over longer does.
    for name, source, pull in (
        ('pm_2p5_last_1_hour', 'pm_2p5', 0.15),
        ('pm_2p5_last_3_hours', 'pm_2p5', 0.3),
        ('pm_2p5_last_24_hours', 'pm_2p5', 0.6),
        ('pm_2p5_nowcast', 'pm_2p5', 0.1),
        ('pm_10_last_1_hour', 'pm_10', 0.15),
        ('pm_10_last_3_hours', 'pm_10', 0.3),
        ('pm_10_last_24_hours', 'pm_10', 0.6),
        ('pm_10_nowcast', 'pm_10', 0.1),
    ):
        middle = AIRLINK_WANDERS[source][0]
        conditions[name] = round(conditions[source] * (1.0 - pull) + middle * pull, 2)
    for name in (
        'pct_pm_data_last_1_hour',
        'pct_pm_data_last_3_hours',
        'pct_pm_data_last_24_hours',
        'pct_pm_data_nowcast',
    ):
        conditions[name] = 100
    return {
        'data': {
            'did': AIRLINK_DID,
            'name': 'pretend AirLink',
            'ts': int(seconds),
            'conditions': [conditions],
        },
        'error': None,
    }


# ---- an Ecowitt gateway that is not there -----------------------------------
#
# The other three fakes answer HTTP, which is a line of code to imitate. This one
# speaks the binary protocol on a socket, and it builds its frames out of the same
# table the driver reads them with rather than replaying a capture. That is the
# point: a capture would prove the driver can read one recording, and this proves it
# can read what the table says a gateway sends.

# What the gateway calls itself. Deliberately not a real MAC or a real firmware
# string: anybody looking at a log or a page has to be able to tell at a glance that
# this is not their gateway.
GW1000_MAC = 'AA:BB:CC:00:11:22'
GW1000_FIRMWARE = 'GW1000_V0.0.0'

# The battery byte each sensor family sends, by the family's name.
#
# These are bytes and not volts. What one means is the gateway's business and not
# this one's: the same byte is a flag on a WH65, hundredths of a volt on a WH34 and
# a level from nought to five on a WH41, and turning it into any of those is the
# driver's job.
GW1000_BATTERIES = {
    'wh65': 0,
    'wh68': 145,
    'wh80': 145,
    'wh40': 16,
    'wh25': 0,
    'wh26': 0,
    'wh31': 0,
    'wh51': 16,
    'wh41': 5,
    'wh57': 5,
    'wh55': 5,
    'wh34': 145,
    'wh45': 5,
    'wh35': 145,
    'wh90': 140,
}

# Live-data addresses this does not send, though it can encode them.
#
# 0x6B is a WH46, which sends what the WH45 at 0x70 sends with four more particle
# sizes on the end; no gateway has both, so sending both would be a shape no reader
# will ever meet. 0x71 is an air quality index the document marks for Ambient
# consoles. Everything else the driver's table knows is sent.
GW1000_NOT_SENT = (0x6B, 0x71)

# What each of the gateway's readings sits at, how far it wanders either side of
# that, and how long one turn of the slow wave takes. Celsius, hPa, millimetres,
# metres per second, lux and micrograms per cubic metre, which is what the API
# answers in whatever the console's display says.
GW1000_WANDERS = {
    'intemp': (21.4, 2.0, 2400.0),
    'outtemp': (14.2, 7.0, 1500.0),
    'dewpoint': (9.1, 5.0, 1700.0),
    'windchill': (13.0, 7.0, 1550.0),
    'heatindex': (14.6, 7.0, 1450.0),
    'inhumi': (46.0, 8.0, 2600.0),
    'outhumi': (68.0, 18.0, 1700.0),
    'absbaro': (1006.4, 6.0, 3600.0),
    'relbaro': (1013.2, 6.0, 3600.0),
    'winddirection': (200.0, 140.0, 2600.0),
    'windspeed': (3.2, 2.6, 400.0),
    'gustspeed': (5.4, 3.4, 380.0),
    'daylwindmax': (8.8, 2.0, 5400.0),
    'rainrate': (0.6, 0.6, 900.0),
    'light': (32000.0, 30000.0, 4000.0),
    'uv': (180.0, 170.0, 4000.0),
    'uvi': (3.0, 3.0, 4000.0),
    'lightning': (12.0, 8.0, 5000.0),
    'tf_co2': (21.8, 2.0, 2500.0),
    'humi_co2': (47.0, 8.0, 2700.0),
    'co2': (620.0, 220.0, 3300.0),
    'co2_24h': (640.0, 90.0, 9000.0),
}

# Readings that are not measurements. Settings the gauge was configured with, the
# times of day it resets at, and the console's free memory. None of these wanders,
# because on real hardware none of them does.
GW1000_FIXED = {
    'rain_gain': 1.0,
    'rain_priority': 1.0,
    'radcompensation': 0.0,
    'rst_rainday_time': 0.0,
    'rst_rainweek_time': 0.0,
    'rst_rainyear_time': 0.0,
    'heap_free': 84512.0,
    'co2_batt': 5.0,
}

# When the pretend rain gauge went in. A gauge counts up from the day its battery
# was fitted and never down, which is what StdDelta differences; without a fixed
# moment to count from, the total would be the unix time over something, which is
# kilometres of rain.
GW1000_RAIN_FROM = 1788000000.0

# Each rain total, and how many hours of counting at a tenth of a millimetre an hour
# it stands for. A year's total is larger than a day's, and one that was not would
# be the first thing about this that looked wrong.
GW1000_RAIN_HOURS = {
    'rainevent': 6.0,
    'rainday': 14.0,
    'rainweek': 90.0,
    'rainmonth': 380.0,
    'rainyear': 4200.0,
    'raintotals': 9000.0,
}


def gw1000_readings(seconds):
    """Every reading an Ecowitt gateway can put in a live-data stream, at one moment.

    One value for every name the driver's table decodes, so that what is encoded here
    and what is read back there can be held against each other name for name.

    Each is rounded to what the gateway can actually send. The API carries every
    reading as an integer and a divisor, so a temperature arrives in tenths and a
    gain in hundredths, and a fake that sent 21.37 would be sending something no
    gateway can.

    Args:
        seconds (float): The time, in seconds. The readings are a function of it, so
            the same number twice gives the same answer, which is what lets a test
            use them.

    Returns:
        dict: Raw gateway field name to value, in the API's own units.
    """
    from .protocols import ecowitt_gateway as api

    out = dict(GW1000_FIXED)
    for name, (middle, spread, period) in GW1000_WANDERS.items():
        out[name] = _wander(seconds, middle, spread, period)
    for name, hours in GW1000_RAIN_HOURS.items():
        counted = 0.1 * hours + (seconds - GW1000_RAIN_FROM) / 36000.0
        out[name] = counted
        # A piezo gauge counts the same weather a little differently, which is why a
        # console with both is asked which of the two it should believe.
        out['piezo_' + name] = counted * 0.97
    out['piezo_rainrate'] = out['rainrate'] * 0.97
    out['piezo_rainhour'] = 0.3 + (seconds - GW1000_RAIN_FROM) / 360000.0
    # A strike a few minutes ago, and a believable number of them since midnight.
    out['lightning_time'] = float(int(seconds) - 900)
    out['lightning_power'] = float(int(seconds) % 37 + 3)
    for channel in range(1, 9):
        away = channel * 211.0
        out['temp%d' % channel] = _wander(seconds + away, 17.0, 5.0, 1600.0)
        out['humi%d' % channel] = _wander(seconds + away, 58.0, 15.0, 1900.0)
        out['tf_usr%d' % channel] = _wander(seconds + away, 12.0, 4.0, 2100.0)
        out['tf_usr%d_batt' % channel] = 2.9
        out['leaf_wetness_ch%d' % channel] = _wander(seconds + away, 30.0, 25.0, 2300.0)
    for channel in range(1, 17):
        away = channel * 137.0
        out['soiltemp%d' % channel] = _wander(seconds + away, 11.0, 4.0, 2900.0)
        out['soilmoisture%d' % channel] = _wander(seconds + away, 42.0, 20.0, 3100.0)
    for channel in range(1, 5):
        away = channel * 173.0
        out['pm25_ch%d' % channel] = _wander(seconds + away, 7.2, 4.0, 440.0)
        out['pm25_24havg%d' % channel] = _wander(seconds + away, 7.6, 1.5, 5400.0)
        # A leak detector says wet or dry and nothing in between.
        out['leak_ch%d' % channel] = 0.0
    for gain in range(10):
        out['piezo_gain%d' % gain] = 1.0
    for name, middle in (
        ('pm1_co2', 4.1),
        ('pm25_co2', 7.2),
        ('pm4_co2', 7.8),
        ('pm10_co2', 8.0),
    ):
        out[name] = _wander(seconds, middle, middle * 0.5, 460.0)
        out[name.replace('_co2', '_24h_co2')] = _wander(
            seconds, middle, middle * 0.2, 6400.0
        )
    for index, name in enumerate(api.AQI):
        out[name] = float(20 + index)
    return _gw1000_rounded(out, api)


def _gw1000_rounded(readings, api):
    """Each reading at the resolution the gateway can send it in.

    Args:
        readings (dict): Name to value.
        api (Any): The protocol module, for its tables. Passed in rather than
            imported again so that there is one import of it per answer.

    Returns:
        dict: The same names, each value rounded to its own resolution.
    """
    divisors = {}
    for table in (api.LIVE, api.RAIN):
        for shapes in table.values():
            for name, _, divide in shapes:
                if name is not None:
                    divisors[name] = divide
    out = {}
    for name, value in readings.items():
        divide = divisors.get(name, 1.0)
        out[name] = round(value * divide) / divide
    return out


def gw1000_sensors():
    """The sensors the pretend gateway has registered.

    Every sensor Ecowitt makes, at once. No garden has all of them, and that is the
    point of a fake: it fills every column the driver can fill, so somebody can see
    what they are setting up before the hardware arrives.

    Returns:
        dict: Sensor name to (id, battery byte, signal).
    """
    from .protocols import ecowitt_gateway as api

    made = {}
    for index, sensor in enumerate(api.SENSORS):
        family = sensor.split('_')[0]
        # Ids that are no real sensor's, and all different, so that a reader that
        # got two of them the wrong way round would be caught by it.
        made[sensor] = (0xC0DE00 + index, GW1000_BATTERIES[family], 4)
    return made


def gw1000_answer(command, seconds):
    """What the pretend gateway answers one command with.

    Args:
        command (int): The command byte that was asked for.
        seconds (float): The time, for the readings that move.

    Returns:
        bytes: The whole response frame, or b'' for a command it does not know,
        which is what a gateway with older firmware does.
    """
    from .protocols import ecowitt_gateway as api

    readings = gw1000_readings(seconds)
    if command == api.CMD_READ_STATION_MAC:
        payload = bytes(int(one, 16) for one in GW1000_MAC.split(':'))
    elif command == api.CMD_READ_FIRMWARE_VERSION:
        said = GW1000_FIRMWARE.encode('ascii')
        payload = bytes([len(said)]) + said
    elif command == api.CMD_READ_SSSS:
        # 868 MHz, set up for a WH65, with a clock and a timezone the driver does
        # not read. See read_system: there is no unit setting in here to read.
        payload = api.SYSTEM.pack(1, 1, int(seconds), 18, 0)
    elif command == api.CMD_GW1000_LIVEDATA:
        payload = api.write_stream(
            readings,
            api.LIVE,
            [one for one in api.LIVE if one not in GW1000_NOT_SENT],
        )
    elif command == api.CMD_READ_RAIN:
        payload = api.write_stream(readings, api.RAIN)
    elif command == api.CMD_READ_SENSOR_ID_NEW:
        payload = api.write_sensors(gw1000_sensors())
    else:
        return b''
    return api.frame(command, payload, answering=True)


def gw1000_serve(port=45000, address='127.0.0.1'):
    """Answer like an Ecowitt gateway on a socket, until interrupted.

    Args:
        port (int): The port to listen on. The one Ecowitt fixed, by default, so
            that an address on its own is enough to point a source at it.
        address (str): The address to bind to. The loopback by default, because a
            gateway that does not exist has no business being on the network.

    Returns:
        int: The exit status, which is 0 unless the port could not be had.
    """
    import time

    class Handler(socketserver.BaseRequestHandler):
        """One connection, answering commands until the other end goes away."""

        def handle(self):
            # A gateway holds a connection open for as long as the driver wants it,
            # and a connection nobody is using has to be let go rather than hold a
            # thread for the life of the process.
            self.request.settimeout(30.0)
            while True:
                try:
                    asked = gw1000_request(self.request)
                except (OSError, ValueError):
                    return
                if asked is None:
                    return
                answer = gw1000_answer(asked, time.time())
                if not answer:
                    # A gateway whose firmware does not have the command says
                    # nothing at all, which is the case the driver has to survive.
                    print("asked: 0x%02x, which this one does not answer" % asked)
                    continue
                print("asked: 0x%02x, answered %d bytes" % (asked, len(answer)))
                self.request.sendall(answer)

    class Gateway(socketserver.ThreadingTCPServer):
        """So that the port comes back at once, and no thread outlives the server."""

        allow_reuse_address = True
        daemon_threads = True

    try:
        server = Gateway((address, port), Handler)
    except OSError as e:
        print("Cannot listen on %s:%d: %s" % (address, port, e))
        return 1
    print(
        "Answering like an Ecowitt gateway at %s:%d\n"
        "Point a source at it:\n"
        "\n"
        "    [[polling]]\n"
        "        [[[gateway]]]\n"
        "            address = %s\n"
        "            protocol = ecowitt_gateway\n"
        "            interval = 10\n" % (address, port, address)
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopped.")
    finally:
        server.server_close()
    return 0


def gw1000_request(connection):
    """Read one request frame off a connection.

    Args:
        connection (socket.socket): The open connection.

    Returns:
        int: The command byte, or None when the other end has gone away.

    Raises:
        ValueError: If what arrived is not a request frame.
    """
    from .protocols import ecowitt_gateway as api

    # Every command the driver sends carries no payload, so a request is always the
    # two header bytes, the command, the size and the checksum.
    asked = b''
    while len(asked) < 5:
        more = connection.recv(5 - len(asked))
        if not more:
            return None
        asked += more
    api.payload_of(asked[2], asked, answering=False)
    return asked[2]


# ---- a Home Assistant that is not there -------------------------------------
#
# Enough of the REST API to set a source up against and watch it record: the two
# endpoints a reading needs, the one the device names come from, and the token it
# all hangs on.
#
# Three of the entities below are not reporting a number. They are the reason this
# exists rather than a fixture: an installation has an unavailable sensor within a
# week, and a fake without one never exercises the code that tells a missing reading
# from a zero.

# The token this insists on. Deliberately nothing like a real one, which is a signed
# token several hundred characters long: anybody reading a log or a page has to be
# able to tell at a glance that this is not their Home Assistant.
HA_TOKEN = 'pretend-long-lived-access-token'

# The two devices, and what each of their entities is. `every` is the wander, as
# (what it sits at, how far either side, seconds for one turn); `says` replaces it
# for an entity that is not reporting a number.
HA_DEVICES = (
    {
        'id': 'aa11bb22cc33dd44ee55ff6600112233',
        'name': 'Balkon',
        'entities': (
            {
                'entity_id': 'sensor.balkon_temperatur',
                'name': 'Balkon Temperatur',
                'device_class': 'temperature',
                'unit': '°C',
                'every': (11.5, 7.0, 1500.0),
            },
            # A second temperature on one device, which is the ordinary case and not
            # an edge one: a soil probe on the same transmitter, a second wire on a
            # Shelly. The block's order decides which of them is the temperature.
            {
                'entity_id': 'sensor.balkon_bodentemperatur',
                'name': 'Balkon Bodentemperatur',
                'device_class': 'temperature',
                'unit': '°C',
                'every': (9.0, 3.0, 4300.0),
            },
            {
                'entity_id': 'sensor.balkon_luftfeuchte',
                'name': 'Balkon Luftfeuchtigkeit',
                'device_class': 'humidity',
                'unit': '%',
                'every': (68.0, 18.0, 1700.0),
            },
            {
                'entity_id': 'sensor.balkon_luftdruck',
                'name': 'Balkon Luftdruck',
                'device_class': 'atmospheric_pressure',
                'unit': 'hPa',
                'every': (1013.2, 9.0, 3600.0),
            },
            # Kilometres an hour, because that is what a great many integrations
            # report and because a source that converted nothing would prove nothing.
            {
                'entity_id': 'sensor.balkon_wind',
                'name': 'Balkon Windgeschwindigkeit',
                'device_class': 'wind_speed',
                'unit': 'km/h',
                'every': (11.5, 9.0, 400.0),
            },
            # Answering an hour late for ever, which is what a sensor with a flat
            # battery does: Home Assistant keeps returning the last value it had.
            {
                'entity_id': 'sensor.balkon_helligkeit',
                'name': 'Balkon Helligkeit',
                'device_class': 'illuminance',
                'unit': 'lx',
                'every': (12000.0, 9000.0, 4000.0),
                'behind': 3600.0,
            },
            {
                'entity_id': 'sensor.balkon_batterie',
                'name': 'Balkon Batterie',
                'device_class': 'battery',
                'unit': '%',
                'says': 'unavailable',
            },
        ),
    },
    {
        'id': 'ff99ee88dd77cc66bb55aa4433221100',
        'name': 'Wohnzimmer',
        'entities': (
            {
                'entity_id': 'sensor.wohnzimmer_temperatur',
                'name': 'Wohnzimmer Temperatur',
                'device_class': 'temperature',
                'unit': '°C',
                'every': (21.5, 1.5, 5400.0),
            },
            {
                'entity_id': 'sensor.wohnzimmer_luftfeuchte',
                'name': 'Wohnzimmer Luftfeuchtigkeit',
                'device_class': 'humidity',
                'unit': '%',
                'every': (46.0, 8.0, 4900.0),
            },
            {
                'entity_id': 'sensor.wohnzimmer_co2',
                'name': 'Wohnzimmer CO2',
                'device_class': 'carbon_dioxide',
                'unit': 'ppm',
                'says': 'unknown',
            },
        ),
    },
)  # type: Tuple[Dict[str, Any], ...]


def homeassistant_entities():
    """Every entity the fake has, with the device each belongs to.

    Returns:
        list[tuple]: (the device, the entity), in the order they are written above.
    """
    found = []
    for device in HA_DEVICES:
        for entity in device['entities']:
            found.append((device, entity))
    return found


def homeassistant_state(entity_id, seconds):
    """What Home Assistant says about one entity, at one moment.

    Args:
        entity_id (str): Which entity.
        seconds (float): The time, in seconds. The readings are a function of it, so
            the same number twice gives the same answer, which is what makes a test
            repeatable.

    Returns:
        dict: The state, shaped the way the REST API shapes one, or None when there
        is no such entity.
    """
    for device, entity in homeassistant_entities():
        if entity['entity_id'] != entity_id:
            continue
        if 'says' in entity:
            state = entity['says']
        else:
            middle, spread, period = entity['every']
            state = '%.1f' % _wander(seconds, middle, spread, period)
        when = seconds - entity.get('behind', 0.0)
        return {
            'entity_id': entity_id,
            'state': state,
            'attributes': {
                'unit_of_measurement': entity['unit'],
                'device_class': entity['device_class'],
                'friendly_name': entity['name'],
                'state_class': 'measurement',
            },
            'last_changed': _iso(when),
            'last_reported': _iso(when),
            'last_updated': _iso(when),
            'context': {'id': '01JABCDEF0123456789ABCDEF', 'parent_id': None},
        }
    return None


def homeassistant_states(seconds):
    """Every entity at once, which is what the listing endpoint answers.

    Args:
        seconds (float): The time, in seconds.

    Returns:
        list: The states, each a dict.
    """
    return [
        homeassistant_state(entity['entity_id'], seconds)
        for _, entity in homeassistant_entities()
    ]


def homeassistant_devices(entities):
    """The entity-to-device map, which is what the template renders.

    The real one runs the template through Jinja with Home Assistant's own
    `device_id` and `device_name` functions. This answers what that would have
    produced, which is the part a caller can be wrong about.

    Args:
        entities (list): The entity ids the template asked about, as strings.

    Returns:
        dict: Entity id to {'id': ..., 'name': ...}, with nulls for an entity no
        device claims, which is what Home Assistant renders for one.
    """
    where = {}
    for device, entity in homeassistant_entities():
        where[entity['entity_id']] = {'id': device['id'], 'name': device['name']}
    return {
        entity_id: where.get(entity_id, {'id': None, 'name': None})
        for entity_id in entities
    }


def _iso(seconds):
    """The time, written the way Home Assistant writes a timestamp.

    Args:
        seconds (float): The time.

    Returns:
        str: e.g. '2026-08-31T09:15:00+00:00'.
    """
    import datetime

    when = datetime.datetime.fromtimestamp(seconds, datetime.timezone.utc)
    return when.isoformat()


def homeassistant_handler(token=HA_TOKEN, clock=None):
    """The request handler the fake Home Assistant answers with.

    Handed out on its own so that a test can put it on a port of its own and
    exercise the same refusals and the same routing that ship. A copy in the tests
    would be a copy that agrees with the code until the day it stops.

    Args:
        token (str): The token it insists on.
        clock (callable | None): What to use for the time. The wall clock by
            default. A test holds it still instead, so that what it asserts is the
            reading the fake sent rather than the reading it sent a moment ago.

    Returns:
        type: A BaseHTTPRequestHandler subclass.
    """
    import re
    import time
    import urllib.parse

    if clock is None:
        clock = time.time

    class Handler(http.server.BaseHTTPRequestHandler):
        """Three endpoints and a token, which is the whole of what is read here."""

        def do_GET(self):
            if not self._allowed():
                return
            if self.path in ('/api/', '/api'):
                self._say(200, {'message': 'API running.'})
                return
            if self.path == '/api/states':
                self._say(200, homeassistant_states(clock()))
                return
            if self.path.startswith('/api/states/'):
                wanted = urllib.parse.unquote(self.path[len('/api/states/') :])
                state = homeassistant_state(wanted, clock())
                if state is None:
                    self._say(404, {'message': 'Entity not found.'})
                    return
                self._say(200, state)
                return
            self._say(404, {'message': 'Not found.'})

        def do_POST(self):
            if not self._allowed():
                return
            if self.path != '/api/template':
                self._say(404, {'message': 'Not found.'})
                return
            length = int(self.headers.get('Content-Length') or 0)
            asked = self.rfile.read(length).decode('utf-8', 'replace')
            try:
                template = json.loads(asked).get('template', '')
            except ValueError:
                self._say(400, {'message': 'Invalid JSON specified.'})
                return
            # The real one renders the template. This reads the entity ids out of it
            # and answers what rendering would have produced, which is the part a
            # caller can be wrong about; running Jinja here would only test Jinja.
            wanted = re.findall(r'"([a-z_]+\.[a-z0-9_]+)"', template)
            # Rendered rather than returned as JSON: Home Assistant renders with
            # parse_result off, so what comes back is the text the template produced
            # and its type is text/plain.
            self._text(200, json.dumps(homeassistant_devices(wanted)))

        def _allowed(self):
            """Whether the request carried the token. Answers 401 when it did not.

            Returns:
                bool: Whether to go on.
            """
            presented = self.headers.get('Authorization') or ''
            if presented == 'Bearer ' + token:
                return True
            self._say(401, {'message': 'Unauthorized'})
            return False

        def _say(self, status, body):
            """Answer with JSON.

            Args:
                status (int): The status.
                body (dict | list): What to say.
            """
            self._write(status, json.dumps(body).encode('utf-8'), 'application/json')

        def _text(self, status, body):
            """Answer with text, which is what a rendered template comes back as.

            Args:
                status (int): The status.
                body (str): What to say.
            """
            self._write(status, body.encode('utf-8'), 'text/plain; charset=utf-8')

        def _write(self, status, body, content_type):
            """Send one answer.

            Args:
                status (int): The status.
                body (bytes): What to say.
                content_type (str): What to call it.
            """
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):
            """One line per question, which is the point of watching this run."""
            print("asked: %s" % (fmt % args))

    return Handler


def serve_homeassistant(port, address='127.0.0.1', token=HA_TOKEN):
    """Answer like Home Assistant's REST API, until interrupted.

    Args:
        port (int): The port to listen on. 8123 is Home Assistant's own.
        address (str): The address to bind to. The loopback by default, because a
            Home Assistant that does not exist has no business being on the network.
        token (str): The token it insists on.

    Returns:
        int: The exit status, which is 0 unless the port could not be had.
    """
    try:
        server = socketserver.TCPServer((address, port), homeassistant_handler(token))
    except OSError as e:
        print("Cannot listen on %s:%d: %s" % (address, port, e))
        return 1
    outdoors = HA_DEVICES[0]
    print(
        "Answering like Home Assistant at http://%s:%d/api/\n"
        "Two devices, %s outdoors and %s indoors. Point a source at one of them:\n"
        "\n"
        "    [[polling]]\n"
        "        [[[%s]]]\n"
        "            address = %s:%d\n"
        "            protocol = homeassistant\n"
        "            token = %s\n"
        "            entities = %s\n"
        "            interval = 10\n"
        "\n"
        "Three of its entities are not reporting a number: one unavailable, one "
        "unknown,\nand one whose reading is an hour old. None of them should reach "
        "the database.\n"
        % (
            address,
            port,
            HA_DEVICES[0]['name'],
            HA_DEVICES[1]['name'],
            outdoors['name'].lower(),
            address,
            port,
            token,
            ', '.join(one['entity_id'] for one in outdoors['entities']),
        )
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopped.")
    finally:
        server.server_close()
    return 0


# What the fake account holds. Two stations, because one is the case that needs no
# 'mac' line and two is the case that does, and a fake with only the easy one in it
# would never exercise the message that says which to pick.
AMBIENT_KEYS = ('pretend-application-key', 'pretend-api-key')
AMBIENT_STATIONS = (
    {'mac': 'AA:BB:CC:11:22:33', 'name': 'Garten', 'location': 'Zuhause'},
    {'mac': 'AA:BB:CC:44:55:66', 'name': 'Gartenhaus', 'location': 'Zuhause'},
)

# The readings, in the names Ambient's own consoles POST and their API answers with.
# Imperial throughout, which is what the API gives whatever the display is set to.
AMBIENT_WANDERS = {
    'tempf': (59.9, 11.0, 86400.0),
    'humidity': (61.0, 18.0, 40000.0),
    'tempinf': (69.4, 3.0, 86400.0),
    'humidityin': (44.0, 8.0, 50000.0),
    'baromrelin': (30.05, 0.35, 172800.0),
    'baromabsin': (28.71, 0.35, 172800.0),
    'windspeedmph': (4.2, 4.0, 1700.0),
    'windgustmph': (7.9, 6.0, 900.0),
    'winddir': (210.0, 140.0, 5400.0),
    'solarradiation': (310.0, 300.0, 86400.0),
    'uv': (3.0, 3.0, 86400.0),
    'soilhum1': (38.0, 9.0, 200000.0),
}


def ambient_reading(seconds, station):
    """One station's lastData, at one moment.

    Args:
        seconds (float): The time, in seconds. The readings are a function of it, so
            the same number twice gives the same answer, which is what makes a test
            repeatable.
        station (dict): Which one, for the small offset that keeps two stations on
            one account from reporting the same numbers.

    Returns:
        dict: The readings, as ambientweather.net puts them under 'lastData'.
    """
    # The second station reads the clock six hours out, which puts every wander a
    # good part of a turn from the first one's. Not realism: two stations reporting
    # nearly the same numbers would leave a test unable to say which it was given.
    away = 0.0 if station['mac'] == AMBIENT_STATIONS[0]['mac'] else 21600.0
    minute = seconds - seconds % 60
    reading = {
        'dateutc': int(minute * 1000),
        'date': _stamp_iso(minute),
        'stationtype': 'AMBWeatherV4.3.4',
        'tz': 'Europe/Berlin',
    }
    for name, (middle, spread, period) in AMBIENT_WANDERS.items():
        reading[name] = _wander(seconds + away, middle, spread, period)
    # The ones their consoles send as whole numbers.
    for name in ('humidity', 'humidityin', 'winddir', 'uv', 'soilhum1'):
        reading[name] = int(round(reading[name]))
    reading['uv'] = max(0, reading['uv'])
    reading['solarradiation'] = max(0.0, reading['solarradiation'])
    reading['maxdailygust'] = round(reading['windgustmph'] + 3.4, 1)
    reading['hourlyrainin'] = 0.0
    reading['dailyrainin'] = 0.04
    reading['weeklyrainin'] = 0.31
    reading['monthlyrainin'] = 1.18
    reading['yearlyrainin'] = 14.2
    reading['battout'] = 1
    reading['battin'] = 1
    # Ambient's own arithmetic, which this driver leaves alone in favour of WeeWX's.
    # Here so that leaving it alone is something a test can watch happen.
    reading['feelsLike'] = round(reading['tempf'] - 0.6, 1)
    reading['dewPoint'] = round(reading['tempf'] - 12.4, 2)
    return reading


def ambient_devices(seconds):
    """The whole account, as /v1/devices answers it.

    Args:
        seconds (float): The time.

    Returns:
        list[dict]: One entry per station, each with its macAddress, its info and
        its lastData.
    """
    return [
        {
            'macAddress': one['mac'],
            'info': {'name': one['name'], 'location': one['location']},
            'lastData': ambient_reading(seconds, one),
        }
        for one in AMBIENT_STATIONS
    ]


def _stamp_iso(seconds):
    """The time, written the way Ambient's API writes it.

    Args:
        seconds (float): The time.

    Returns:
        str: e.g. '2026-08-31T09:04:00.000Z'.
    """
    import time

    return time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime(seconds))


def ambient_handler(keys=AMBIENT_KEYS, clock=None):
    """The request handler the fake ambientweather.net answers with.

    Handed out on its own so that a test can put it on a port of its own and get the
    same refusal that ships.

    Args:
        keys (tuple): The (application key, API key) pair it insists on.
        clock (callable | None): What to use for the time. The wall clock by
            default. A test holds it still instead.

    Returns:
        type: A BaseHTTPRequestHandler subclass.
    """
    import time
    import urllib.parse

    if clock is None:
        clock = time.time

    class Handler(http.server.BaseHTTPRequestHandler):
        """One endpoint and two keys, which is the whole of this API."""

        def do_GET(self):
            split = urllib.parse.urlsplit(self.path)
            asked = urllib.parse.parse_qs(split.query)
            if split.path != '/v1/devices':
                self._say(404, {'error': 'not-found'})
                return
            # Both keys or neither. The real one answers 401 to a missing key the
            # same as to a wrong one, and a driver that told the two apart would be
            # telling somebody something the service never said.
            given = (
                (asked.get('applicationKey') or [''])[0],
                (asked.get('apiKey') or [''])[0],
            )
            if given != tuple(keys):
                self._say(401, {'error': 'invalid-application-key-or-api-key'})
                return
            self._say(200, ambient_devices(clock()))

        def _say(self, status, body):
            """Answer with JSON.

            Args:
                status (int): The status.
                body (dict | list): What to say.
            """
            encoded = json.dumps(body).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, fmt, *args):
            """One line per question, which is the point of watching this run."""
            print("asked: %s" % (fmt % args))

    return Handler


def serve_ambient_cloud(port, address='127.0.0.1', keys=AMBIENT_KEYS):
    """Answer like the ambientweather.net API, until interrupted.

    Args:
        port (int): The port to listen on.
        address (str): The address to bind to. The loopback by default, because an
            account that does not exist has no business being on the network.
        keys (tuple): The (application key, API key) pair it insists on.

    Returns:
        int: The exit status, which is 0 unless the port could not be had.
    """
    try:
        server = socketserver.TCPServer((address, port), ambient_handler(keys))
    except OSError as e:
        print("Cannot listen on %s:%d: %s" % (address, port, e))
        return 1
    print(
        "Answering as ambientweather.net on http://%s:%d/v1/devices\n"
        "\n"
        "Two stations on the account, so a block has to say which:\n"
        "\n"
        "    [[polling]]\n"
        "        [[[%s]]]\n"
        "            url = http://%s:%d\n"
        "            protocol = ambient_cloud\n"
        "            application_key = %s\n"
        "            api_key = %s\n"
        "            mac = %s\n"
        "            interval = 10\n"
        "\n"
        "A 'url' rather than an 'address', because the real one is reached over "
        "HTTPS\nat a name this driver already has. Leave 'mac' out to see what it "
        "says.\n"
        % (
            address,
            port,
            AMBIENT_STATIONS[0]['name'].lower(),
            address,
            port,
            keys[0],
            keys[1],
            AMBIENT_STATIONS[0]['mac'],
        )
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopped.")
    finally:
        server.server_close()
    return 0
