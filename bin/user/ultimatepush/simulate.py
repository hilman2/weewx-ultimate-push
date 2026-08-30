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

answers like a PurpleAir at `http://127.0.0.1:8081/json`, for a `[[polling]]` source
to be pointed at.

    python -m user.ultimatepush --fake-rtl433 1433

sends what rtl_433 sends, three sensors at a time, one of them a neighbour's,
because letting in the ones that are yours is the part worth trying out.

The tests read the same two, so what is shipped and what is known to work are one
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


def serve(port, address='127.0.0.1'):
    """Answer like a PurpleAir until interrupted.

    Args:
        port (int): The port to listen on.
        address (str): The address to bind to. The loopback by default, because a
            sensor that does not exist has no business being on the network.

    Returns:
        int: The exit status, which is 0 unless the port could not be had.
    """
    import time

    class Handler(http.server.BaseHTTPRequestHandler):
        """Answers anything with the same reading, which is what the real one does."""

        def do_GET(self):
            body = json.dumps(purpleair_answer(time.time())).encode('utf-8')
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
        "Answering like a PurpleAir at http://%s:%d/json\n"
        "Point a source at it:\n"
        "\n"
        "    [[polling]]\n"
        "        [[[air]]]\n"
        "            address = %s:%d\n"
        "            protocol = purpleair\n"
        "            interval = 10\n" % (address, port, address, port)
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
