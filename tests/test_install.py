#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""Check that the installer ships every file the driver needs.

A module left out of install.py is invisible here and in CI. It shows up as an
ImportError the first time somebody installs the release, which is the worst place
to find out.
"""

import glob
import os.path
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def installed_files():
    """The paths install.py says it will copy."""
    with open(os.path.join(ROOT, 'install.py'), encoding='utf-8') as fd:
        return set(re.findall(r"'(bin/user/[\w/]+\.py)'", fd.read()))


def package_files():
    """The paths that actually exist."""
    found = set()
    for path in glob.glob(os.path.join(ROOT, 'bin', 'user', '**', '*.py'),
                          recursive=True):
        found.add(os.path.relpath(path, ROOT).replace(os.sep, '/'))
    return found


def test_every_module_is_installed():
    missing = package_files() - installed_files()

    assert not missing, "install.py does not ship: %s" % ', '.join(sorted(missing))


def test_nothing_is_installed_that_does_not_exist():
    phantom = installed_files() - package_files()

    assert not phantom, "install.py ships files that are gone: %s" % ', '.join(sorted(phantom))


def test_the_version_matches_the_package():
    import ultimatepush

    with open(os.path.join(ROOT, 'install.py'), encoding='utf-8') as fd:
        declared = re.search(r"VERSION = '([^']+)'", fd.read()).group(1)

    assert declared == ultimatepush.VERSION


def installer_config():
    """The configuration the installer merges into weewx.conf."""
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location('ultimatepush_install',
                                                  os.path.join(ROOT, 'install.py'))
    module = importlib.util.module_from_spec(spec)
    sys.modules['ultimatepush_install'] = module
    spec.loader.exec_module(module)
    return module.loader()['config']


def test_the_installer_sets_up_rain():
    """Without this the station records no rain at all.

    Every protocol here sends running counters, never the amount since the last
    upload. WeeWX wants 'rain', the amount in the packet, and StdDelta is what turns
    one into the other. Every counter would arrive and 'rain' would stay empty.
    """
    import pytest

    pytest.importorskip('weecfg', reason="WeeWX is not installed")

    delta = installer_config()['StdWXCalculate']['Delta']
    assert delta['rain']['input'] == 'dayRain'


def test_the_counter_it_uses_is_one_every_protocol_produces():
    """A counter no field map fills would leave rain empty just the same.

    And one that only some of them fill would leave it empty for the others, which
    is worse: it would work on the hardware it was tested with.
    """
    import pytest

    pytest.importorskip('weecfg', reason="WeeWX is not installed")
    from ultimatepush import protocols

    wanted = installer_config()['StdWXCalculate']['Delta']['rain']['input']
    for protocol in protocols.registry():
        assert wanted in protocol.dialect({}).fields.values(), (
            "%s sends no field that maps to '%s'" % (protocol.name, wanted))
