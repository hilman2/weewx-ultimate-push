#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""Make the driver importable, and hand the captured payloads to the tests."""

import os.path
import sys
import types

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
USER_DIR = os.path.join(os.path.dirname(HERE), 'bin', 'user')
sys.path.insert(0, USER_DIR)
# So that a test can import tests/helpers.py by name.
sys.path.insert(0, HERE)

# In a WeeWX installation these modules live under the 'user' package, and the driver
# imports them by that name. Make the same name work here, so the tests exercise the
# import the driver really uses.
if 'user' not in sys.modules:
    user_package = types.ModuleType('user')
    user_package.__path__ = [USER_DIR]
    sys.modules['user'] = user_package


@pytest.fixture
def payload():
    """Return a captured payload by name, e.g. payload('hp2561ae_pro')."""

    def _load(name):
        """A captured payload, by name. 'hp2561ae_pro', or 'wunderground/metric'."""
        path = os.path.join(HERE, 'fixtures', *(name.split('/'))) + '.txt'
        with open(path, encoding='utf-8') as fd:
            return fd.read().strip()

    return _load
