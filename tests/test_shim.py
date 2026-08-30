#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""Keep the bundled listener identical to the one in WeeWX.

The copy in bin/user exists so that this driver runs on WeeWX older than 5.6, which
does not carry weewx.listener yet. It is the same file, and it has to stay the same
file. A copy that drifts is a fork, which is the thing this whole exercise is meant to
get rid of.
"""

import hashlib
import os.path

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
SHIM = os.path.join(os.path.dirname(HERE), 'bin', 'user', 'listener.py')


def digest(path):
    with open(path, 'rb') as fd:
        return hashlib.sha256(fd.read().replace(b'\r\n', b'\n')).hexdigest()


def test_the_bundled_listener_matches_weewx():
    weewx_listener = pytest.importorskip(
        'weewx.listener', reason="WeeWX with a listener is not installed"
    )

    assert digest(SHIM) == digest(weewx_listener.__file__)


def test_the_bundled_listener_is_importable():
    """However old the WeeWX, the bundled copy has to work."""
    pytest.importorskip('weeutil', reason="WeeWX is not installed")
    import user.listener as bundled

    assert hasattr(bundled, 'HTTPListener')
    assert hasattr(bundled, 'UDPListener')
