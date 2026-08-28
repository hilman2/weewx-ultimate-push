#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""Import every module.

Sounds trivial. It is not: __main__.py is never imported by the other tests, so a
syntax error in it would ship. This is the cheapest possible guard against that.
"""

import importlib

import pytest

# The transport, the catalogs, the protocols and the inference are the parts that
# have to work with nothing but Python, so that the tests can run from a captured
# payload on a machine with no WeeWX on it.
WITHOUT_WEEWX = [
    'ultimatepush',
    'ultimatepush.activity',
    'ultimatepush.columns',
    'ultimatepush.infer',
    'ultimatepush.mapping',
    'ultimatepush.overrides',
    'ultimatepush.page',
    'ultimatepush.transport',
    'ultimatepush.catalogs',
    'ultimatepush.catalogs.acurite',
    'ultimatepush.catalogs.ambient',
    'ultimatepush.catalogs.ecowitt',
    'ultimatepush.catalogs.lacrosse',
    'ultimatepush.catalogs.weatherflow',
    'ultimatepush.catalogs.wunderground',
    'ultimatepush.protocols',
    'ultimatepush.protocols.acurite',
    'ultimatepush.protocols.ambient',
    'ultimatepush.protocols.ecowitt',
    'ultimatepush.protocols.lacrosse',
    'ultimatepush.protocols.weatherflow',
    'ultimatepush.protocols.wunderground',
]
# The listener is WeeWX's own file, bundled here for older installations. It uses
# weeutil, as the core copy does, so it needs WeeWX like the driver does.
WITH_WEEWX = ['ultimatepush.driver', 'ultimatepush.server', 'ultimatepush.admin',
              'ultimatepush.__main__', 'user.listener']


@pytest.mark.parametrize('name', WITHOUT_WEEWX)
def test_imports_without_weewx(name):
    assert importlib.import_module(name)


@pytest.mark.parametrize('name', WITH_WEEWX)
def test_imports_with_weewx(name):
    pytest.importorskip('weewx', reason="WeeWX is not installed")
    assert importlib.import_module(name)


def test_the_command_line_help_works():
    """argparse builds its help from the same strings the module defines."""
    pytest.importorskip('weewx', reason="WeeWX is not installed")
    from ultimatepush.__main__ import main

    with pytest.raises(SystemExit) as caught:
        main(['--help'])
    assert caught.value.code == 0


def test_the_command_line_reads_an_upload(tmp_path, capsys):
    """--help proves it parses. This proves it runs.

    The body of a command nothing calls is the easiest thing in a repository to
    break: it has no caller to fail, and a rename slides straight past it.
    """
    import http.client
    import socket
    import threading

    pytest.importorskip('weewx', reason="WeeWX is not installed")
    from ultimatepush.__main__ import main

    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]

    result = {}

    def run():
        result['code'] = main(['--port', str(port), '--address', '127.0.0.1',
                               '--timeout', '20', '--no-database'])

    runner = threading.Thread(target=run)
    runner.start()
    try:
        for _ in range(100):
            try:
                connection = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
                connection.request('POST', '/', 'PASSKEY=ABC&stationtype=GW2000A'
                                                '&tempf=59.7&baromrelin=29.92')
                assert connection.getresponse().read() == \
                    b'{"errcode":"0","errmsg":"ok"}'
                connection.close()
                break
            except OSError:
                continue
        else:
            raise AssertionError("the listener never came up")
    finally:
        runner.join(30)

    assert result['code'] == 0
    printed = capsys.readouterr().out
    assert "Ecowitt, read with the 'ecowitt' catalog" in printed
    assert 'outTemp' in printed
    assert 'barometer' in printed
