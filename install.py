#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""Installer for the UltimatePush driver."""

import secrets

from weecfg.extension import ExtensionInstaller

VERSION = '0.19.0'


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
                'Station': {'station_type': 'UltimatePush'},
                # Every protocol here sends rain as running counters, never as the
                # amount since the last upload. WeeWX wants 'rain', the amount in
                # the packet, and StdDelta is what turns one into the other. Without
                # this the station records no rain at all: every counter arrives and
                # 'rain' stays empty.
                #
                # dayRain is the counter every one of them has. It resets at
                # midnight, which StdDelta handles, and it is the only one that does
                # not depend on which sensor the station happens to own.
                'StdWXCalculate': {'Delta': {'rain': {'input': 'dayRain'}}},
                'UltimatePush': {
                    'driver': 'user.ultimatepush.driver',
                    'port': '8000',
                    'protocols': 'auto',
                    'infer_unknown': 'series',
                    # 'compat' is deliberately absent. Fields that drivers place
                    # differently stay out until somebody says which placement is
                    # wanted, because the wrong one cannot be undone.
                    'field_map_extensions': {},
                    # The web interface, ready to open. It is where a field gets
                    # placed, and placing a field is the one thing about this
                    # hardware that cannot be undone once it is wrong, so it should
                    # not be behind three steps of setting up.
                    #
                    # The token is made here, once, and is different on every
                    # installation. An upgrade keeps the one already in the file:
                    # weecfg merges only what is missing.
                    #
                    # Set 'enable = false' to close the port. The driver prints the
                    # whole address to the log at startup.
                    'web': {
                        'enable': 'true',
                        'port': '8080',
                        'token': secrets.token_urlsafe(12),
                    },
                },
            },
            files=[
                ('bin/user', ['bin/user/listener.py']),
                # Every module in the package. A test keeps these lists complete,
                # because a missing one shows up as an ImportError on somebody else's
                # machine and nowhere earlier.
                (
                    'bin/user/ultimatepush',
                    [
                        'bin/user/ultimatepush/__init__.py',
                        'bin/user/ultimatepush/__main__.py',
                        'bin/user/ultimatepush/activity.py',
                        'bin/user/ultimatepush/admin.py',
                        'bin/user/ultimatepush/checklist.py',
                        'bin/user/ultimatepush/columns.py',
                        'bin/user/ultimatepush/consoles.py',
                        'bin/user/ultimatepush/driver.py',
                        'bin/user/ultimatepush/hardware.py',
                        'bin/user/ultimatepush/infer.py',
                        'bin/user/ultimatepush/mapping.py',
                        'bin/user/ultimatepush/overrides.py',
                        'bin/user/ultimatepush/page.py',
                        'bin/user/ultimatepush/polling.py',
                        'bin/user/ultimatepush/report.py',
                        'bin/user/ultimatepush/owners.py',
                        'bin/user/ultimatepush/roles.py',
                        'bin/user/ultimatepush/server.py',
                        'bin/user/ultimatepush/simulate.py',
                        'bin/user/ultimatepush/transport.py',
                    ],
                ),
                (
                    'bin/user/ultimatepush/catalogs',
                    [
                        'bin/user/ultimatepush/catalogs/__init__.py',
                        'bin/user/ultimatepush/catalogs/acurite.py',
                        'bin/user/ultimatepush/catalogs/airlink.py',
                        'bin/user/ultimatepush/catalogs/ambient.py',
                        'bin/user/ultimatepush/catalogs/ecowitt.py',
                        'bin/user/ultimatepush/catalogs/ecowitt_gateway.py',
                        'bin/user/ultimatepush/catalogs/homeassistant.py',
                        'bin/user/ultimatepush/catalogs/lacrosse.py',
                        'bin/user/ultimatepush/catalogs/purpleair.py',
                        'bin/user/ultimatepush/catalogs/rtl433.py',
                        'bin/user/ultimatepush/catalogs/weatherflow.py',
                        'bin/user/ultimatepush/catalogs/wunderground.py',
                    ],
                ),
                (
                    'bin/user/ultimatepush/protocols',
                    [
                        'bin/user/ultimatepush/protocols/__init__.py',
                        'bin/user/ultimatepush/protocols/acurite.py',
                        'bin/user/ultimatepush/protocols/airlink.py',
                        'bin/user/ultimatepush/protocols/purpleair.py',
                        'bin/user/ultimatepush/protocols/rtl433.py',
                        'bin/user/ultimatepush/protocols/ambient.py',
                        'bin/user/ultimatepush/protocols/ecowitt.py',
                        'bin/user/ultimatepush/protocols/ecowitt_gateway.py',
                        'bin/user/ultimatepush/protocols/ambient_cloud.py',
                        'bin/user/ultimatepush/protocols/homeassistant.py',
                        'bin/user/ultimatepush/protocols/lacrosse.py',
                        'bin/user/ultimatepush/protocols/weatherflow.py',
                        'bin/user/ultimatepush/protocols/wunderground.py',
                    ],
                ),
            ],
        )
