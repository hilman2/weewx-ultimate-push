#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""Which consoles this driver accepts.

A listener answers whatever reaches its port. Anyone who knows the address can point
a console at it, and every protocol here has the hardware announce itself: a PASSKEY
derived from the MAC for Ecowitt and Ambient, an ID for Weather Underground, a serial
number for WeatherFlow. Two consoles both number their channels from one, so a second
one writing into the same fields would mix two sensors into a column, and nothing
afterwards can separate them.

So the driver accepts exactly the consoles it knows about, and the first one it ever
hears is remembered. Anything else is refused until somebody says it belongs.

Working it out from the readings instead cannot be made to work. There is no rule
that survives a restart, a console added years later, and two consoles uploading at
different intervals. A station sending every eight seconds against one sending every
sixty owns every field for a minute before anyone knows the second one exists.

Where it is remembered, in order of preference:

1.  `weewx.conf`, as `passkey` or under `[[stations]]`. Nothing is stored, and the
    answer moves with the configuration.
2.  The database, in the same metadata table WeeWX keeps `lastUpdate` in. This is
    the right place: it sits with the readings it protects, it is in every backup of
    them, and it moves with them. If the database is gone, so is the series that
    needed protecting.
3.  A text file, when there is no database to ask. Better than nothing, and enough
    to keep a restart from handing the station to whichever console speaks first.
"""

import logging
import os

log = logging.getLogger(__name__)

FILENAME = 'ultimate-push-consoles.txt'
# The key under which the list lives in the daily summary metadata table.
METADATA_KEY = 'ultimatepush_consoles'

HEADER = """# Consoles this WeeWX driver answers to, one identity per line.
#
# The identity is whatever the console sends to name itself: a PASSKEY for Ecowitt and
# Ambient hardware, an ID for Weather Underground, a serial number for WeatherFlow.
#
# This file is the fallback. Normally the list lives in the database, in the same
# metadata table WeeWX keeps lastUpdate in, so that it travels with the readings it
# protects.
#
# To add a console, do not edit this. Give it a name and a field map under
# [[stations]] in weewx.conf, so that its channels go somewhere of their own.
#
# To replace a console, delete its line and restart: the next one to upload is
# adopted. To do without any of this, set 'passkey' in the driver section.
"""


def path_for(weewx_root=None, configured=None, sqlite_root=None):
    """Where to keep the fallback file.

    Beside the database, because that is a directory WeeWX writes to as itself, and
    the one people back up. Under a package installation the configuration directory
    belongs to root and the driver cannot write there at all.
    """
    if configured:
        return configured
    for directory in (sqlite_root, weewx_root):
        if directory and os.path.isdir(directory) and os.access(directory, os.W_OK):
            return os.path.join(directory, FILENAME)
    return os.path.join('/var/tmp', 'weewx-' + FILENAME)


class Store:
    """Reads and writes the list, from the database if there is one.

    The database is asked first and written first. The file is used when there is no
    binding to open, which is the case in tests and when running the driver directly.
    """

    def __init__(self, path, config_dict=None, binding='wx_binding'):
        self.path = path
        self.config_dict = config_dict
        self.binding = binding
        self.where = 'file'

    def read(self):
        """Every identity on record, and where it was found."""
        stored = self._from_database()
        if stored is not None:
            self.where = 'database'
            return stored
        return _read_file(self.path)

    def add(self, passkey, note=''):
        """Record an identity. Returns where it went, or None if it went nowhere."""
        known = self.read()
        if passkey in known:
            return self.where
        known.append(passkey)
        if self._to_database(known):
            return 'database'
        if _write_file(self.path, passkey, note):
            return self.path
        return None

    def _manager(self):
        if not self.config_dict:
            return None
        try:
            import weewx.manager
            return weewx.manager.open_manager_with_config(self.config_dict,
                                                          self.binding)
        except Exception as e:
            log.debug("No database to keep the console list in (%s). Using %s.",
                      e, self.path)
            return None

    def _from_database(self):
        manager = self._manager()
        if manager is None:
            return None
        try:
            with manager:
                stored = manager._read_metadata(METADATA_KEY)
        except Exception as e:
            log.debug("Cannot read the console list from the database: %s", e)
            return None
        return [k for k in (stored or '').split(',') if k.strip()]

    def _to_database(self, known):
        manager = self._manager()
        if manager is None:
            return False
        try:
            with manager:
                manager._write_metadata(METADATA_KEY, ','.join(known))
        except Exception as e:
            log.warning("Cannot record the console list in the database: %s", e)
            return False
        return True


def _read_file(path):
    try:
        with open(path, encoding='utf-8') as fd:
            return [line.split('#')[0].strip() for line in fd
                    if line.split('#')[0].strip()]
    except OSError:
        return []


def _write_file(path, passkey, note=''):
    try:
        directory = os.path.dirname(path)
        if directory and not os.path.isdir(directory):
            os.makedirs(directory)
        fresh = not os.path.exists(path)
        with open(path, 'a', encoding='utf-8') as fd:
            if fresh:
                fd.write(HEADER)
            fd.write('%s%s\n' % (passkey, ('    # %s' % note) if note else ''))
    except OSError as e:
        log.error("Cannot record the console in %s: %s. It will have to be learned "
                  "again after a restart, or set 'passkey' in the driver section.",
                  path, e)
        return False
    return True


# Kept for anything that used the plain functions.
read = _read_file
