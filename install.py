#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""Installer for the UltimatePush driver."""

from weecfg.extension import ExtensionInstaller

VERSION = '0.4.0'


def loader():
    return UltimatePushInstaller()


class UltimatePushInstaller(ExtensionInstaller):
    def __init__(self):
        super(UltimatePushInstaller, self).__init__(
            version=VERSION,
            name='ultimate-push',
            description='Collect data from weather hardware that uploads to a '
                        'custom server: Ecowitt, Weather Underground, Ambient '
                        'Weather, WeatherFlow, Acurite and LaCrosse.',
            author="Manuel Hilgert",
            author_email="hilman2@gmail.com",
            config={
                'Station': {
                    'station_type': 'UltimatePush'},
                # Every protocol here sends rain as running counters, never as the
                # amount since the last upload. WeeWX wants 'rain', the amount in
                # the packet, and StdDelta is what turns one into the other. Without
                # this the station records no rain at all: every counter arrives and
                # 'rain' stays empty.
                #
                # dayRain is the counter every one of them has. It resets at
                # midnight, which StdDelta handles, and it is the only one that does
                # not depend on which sensor the station happens to own.
                'StdWXCalculate': {
                    'Delta': {
                        'rain': {
                            'input': 'dayRain'}}},
                'UltimatePush': {
                    'driver': 'user.ultimatepush.driver',
                    'port': '8000',
                    'protocols': 'auto',
                    'infer_unknown': 'series',
                    # 'compat' is deliberately absent. Fields that drivers place
                    # differently stay out until somebody says which placement is
                    # wanted, because the wrong one cannot be undone.
                    'field_map_extensions': {}}},
            files=[
                ('bin/user', ['bin/user/listener.py']),
                # Every module in the package. A test keeps these lists complete,
                # because a missing one shows up as an ImportError on somebody else's
                # machine and nowhere earlier.
                ('bin/user/ultimatepush', [
                    'bin/user/ultimatepush/__init__.py',
                    'bin/user/ultimatepush/__main__.py',
                    'bin/user/ultimatepush/columns.py',
                    'bin/user/ultimatepush/consoles.py',
                    'bin/user/ultimatepush/driver.py',
                    'bin/user/ultimatepush/infer.py',
                    'bin/user/ultimatepush/mapping.py',
                    'bin/user/ultimatepush/report.py',
                    'bin/user/ultimatepush/server.py',
                    'bin/user/ultimatepush/transport.py']),
                ('bin/user/ultimatepush/catalogs', [
                    'bin/user/ultimatepush/catalogs/__init__.py',
                    'bin/user/ultimatepush/catalogs/acurite.py',
                    'bin/user/ultimatepush/catalogs/ambient.py',
                    'bin/user/ultimatepush/catalogs/ecowitt.py',
                    'bin/user/ultimatepush/catalogs/lacrosse.py',
                    'bin/user/ultimatepush/catalogs/weatherflow.py',
                    'bin/user/ultimatepush/catalogs/wunderground.py']),
                ('bin/user/ultimatepush/protocols', [
                    'bin/user/ultimatepush/protocols/__init__.py',
                    'bin/user/ultimatepush/protocols/acurite.py',
                    'bin/user/ultimatepush/protocols/ambient.py',
                    'bin/user/ultimatepush/protocols/ecowitt.py',
                    'bin/user/ultimatepush/protocols/lacrosse.py',
                    'bin/user/ultimatepush/protocols/weatherflow.py',
                    'bin/user/ultimatepush/protocols/wunderground.py']),
            ]
        )
