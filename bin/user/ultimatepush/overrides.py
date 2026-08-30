#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""Settings the web interface may change, kept where a driver can change them.

`weewx.conf` is not that place, for three reasons that are all about the file rather
than about the interface:

    WeeWX is running from it.  A change written there takes effect at the next
    restart, and a driver cannot restart the engine it is a part of. So a web
    interface that wrote it would be a web interface whose changes did nothing until
    somebody went to a terminal anyway.

    It is often not writable.  Under a package installation it belongs to root and
    the driver runs as the weewx user.

    It is somebody's file.  It has their comments in it, and their layout, and a
    driver rewriting it is a driver that can lose those.

So the settings the interface can change live in a file of the driver's own, beside
the console list, in the same format as `weewx.conf` so that it reads the same way.
They take effect on the next upload, without a restart. Everything else the interface
shows as a block to paste, because everything else needs one.

One rule keeps the two files from fighting: **a field named in `weewx.conf` is never
touched here.** The interface shows it, says where it is set, and declines to change
it. One owner per setting, and no setting that quietly stops meaning what the file
says it means.
"""

import logging
import os
import threading

log = logging.getLogger(__name__)

FILENAME = 'ultimate-push-web.conf'

HEADER = """# Settings made through the web interface of weewx-ultimate-push.
#
# This file is the driver's, not yours, in the sense that the interface rewrites it.
# Editing it by hand works and is read on the next upload, but the interface will
# rewrite the whole file the next time somebody changes something in it, and a
# comment you add here will not survive that.
#
# Anything set in weewx.conf wins over this file and is never written here. That is
# deliberate: one owner per setting.
#
# To go back to a driver that reads nothing but weewx.conf, delete this file and
# restart WeeWX.
"""


def path_for(weewx_root=None, configured=None, sqlite_root=None):
    """Where to keep the file. Beside the console list, for the same reasons.

    Args:
        weewx_root (str | None): The WeeWX root directory, when there is one.
        configured (str | None): A path set in weewx.conf, which wins over everything else.
        sqlite_root (str | None): Where the SQLite database lives, when it is SQLite.

    Returns:
        str: The path to the file.
    """
    from . import consoles

    if configured:
        return configured
    directory = os.path.dirname(consoles.path_for(weewx_root, None, sqlite_root))
    return os.path.join(directory, FILENAME)


class Store:
    """Reads and writes the settings the interface owns.

    Args:
        path (str): The file.
        reserved (dict): What `weewx.conf` already sets, as
            {station identity or None: set of raw field names}. Anything in here is
            refused rather than written, so that the two files cannot disagree about
            one field.
    """

    def __init__(self, path, reserved=None):
        self.path = path
        self.reserved = reserved or {}
        self.settings = {}
        self.error = None
        # Two threads write this file now. The web interface writes it when somebody
        # changes something, and the upload thread writes it when a station takes a
        # column nobody had. Both rewrite the whole file, so one at a time.
        self.lock = threading.RLock()

    # ---- reading -------------------------------------------------------------

    def read(self):
        """Load the file. Returns {} when there is none, which is the usual case."""
        if not os.path.exists(self.path):
            self.settings = {}
            return self.settings
        try:
            import configobj

            parsed = configobj.ConfigObj(self.path, encoding='utf-8', file_error=True)
        except Exception as e:
            # A broken file must not stop the driver. The readings matter more than
            # the settings, and the log says what to fix.
            self.error = str(e)
            log.error(
                "Cannot read %s: %s. Carrying on with weewx.conf alone.", self.path, e
            )
            self.settings = {}
            return self.settings
        self.error = None
        self.settings = _plain(parsed)
        return self.settings

    def stations(self):
        """{identity: {name, infer_unknown, field_map_extensions}}."""
        return dict(self.settings.get('stations', {}))

    def station(self, ident):
        """What this file records about one station.

        Args:
            ident (str): The station's identity.

        Returns:
            dict: Its settings, empty if this file does not have it.
        """
        return self.stations().get(ident, {})

    def extensions_for(self, ident):
        """The field map this file adds for one station.

        Args:
            ident (str): The station's identity.

        Returns:
            dict: Raw field name to WeeWX field.
        """
        return dict(self.station(ident).get('field_map_extensions', {}))

    def hardware(self):
        """The hosted drivers this file records.

        Returns:
            dict: Station type to its settings: 'role', 'channel', 'name', and
            'options', which is the driver's own stanza, the one weewx.conf would
            otherwise carry.
        """
        held = self.settings.get('hardware', {})
        return {
            name: dict(value) for name, value in held.items() if isinstance(value, dict)
        }

    def hardware_order(self):
        """The hosted drivers, in the order that decides the archive station.

        Returns:
            list[str]: Station types. Anything this file records but does not list
            comes after the ones it does, so that a file edited by hand cannot lose
            a driver by forgetting to name it.
        """
        held = self.settings.get('hardware', {})
        named = [
            name.strip()
            for name in str(held.get('station_types', '')).split(',')
            if name.strip()
        ]
        rest = sorted(name for name in self.hardware() if name not in named)
        return [name for name in named if name in self.hardware()] + rest

    # ---- writing -------------------------------------------------------------

    def set_hardware(
        self, station_type, role=None, channel=None, name=None, options=None
    ):
        """Record a hosted driver, or change one.

        Every argument left as None is left as it was, so that one caller can change
        a role without knowing anything about serial ports.

        The driver's own options are kept here only when weewx.conf has no section
        for it. Which of the two is in force is the driver's question, not this
        file's; see driver._hosting_config.

        Args:
            station_type (str): The section the driver wants, e.g. 'Vantage'.
                Required, and it is a section heading, so it is checked as a name.
            role (str | None): MAIN or EXTRA. Setting MAIN clears any channel.
            channel (int | None): Which extra channel it writes to, from 1 to
                roles.CHANNELS.
            name (str | None): What to call it in the log and on the page.
            options (dict | None): The driver's own stanza. Must name a 'driver'
                module, because without one there is nothing to import.

        Returns:
            tuple: (ok, message), where the message is the path written or the
            reason nothing was.
        """
        with self.lock:
            station_type = _as_name(station_type)
            if not station_type:
                return False, (
                    "A section heading may hold letters, digits, dashes and "
                    "underscores."
                )
            held = self.settings.setdefault('hardware', {})
            entry = held.setdefault(station_type, {})
            if options is not None:
                if not options.get('driver'):
                    return False, (
                        "A hosted driver needs a 'driver' option naming the module "
                        "to import, such as weewx.drivers.vantage."
                    )
                entry['options'] = {
                    str(key): str(value) for key, value in options.items()
                }
            if role is not None:
                from .roles import MAIN, ROLES

                if role not in ROLES:
                    return False, "A role is one of %s." % ', '.join(ROLES)
                entry['role'] = role
                if role == MAIN:
                    entry.pop('channel', None)
            if channel is not None:
                from .roles import CHANNELS

                try:
                    channel = int(channel)
                except (TypeError, ValueError):
                    return False, "A channel is a number from 1 to %d." % CHANNELS
                if not 1 <= channel <= CHANNELS:
                    return False, (
                        "A channel is a number from 1 to %d. The standard "
                        "schema has that many extraTemp columns." % CHANNELS
                    )
                entry['channel'] = str(channel)
            if name is not None:
                clean = _as_name(name)
                if not clean:
                    return False, (
                        "A name may hold letters, digits, dashes and underscores."
                    )
                entry['name'] = clean
            self._keep_order(held)
            return self._save()

    def set_hardware_order(self, types):
        """Say which hosted driver answers for the archive.

        The first one does. Kept as an order rather than as a flag on one of them,
        because that is the shape weewx.conf uses for the same thing and two ways of
        saying it would eventually disagree.

        Args:
            types (list[str]): Station types, the archive station first.

        Returns:
            tuple: (ok, message).
        """
        with self.lock:
            held = self.settings.setdefault('hardware', {})
            known = [name for name in types if name in self.hardware()]
            rest = [name for name in sorted(self.hardware()) if name not in known]
            held['station_types'] = ', '.join(known + rest)
            return self._save()

    def forget_hardware(self, station_type):
        """Take a hosted driver out of this file.

        Args:
            station_type (str): Which one.

        Returns:
            tuple: (ok, message).
        """
        with self.lock:
            held = self.settings.get('hardware', {})
            if station_type not in held or not isinstance(held[station_type], dict):
                return False, "This file does not have that driver."
            del held[station_type]
            self._keep_order(held)
            return self._save()

    def _keep_order(self, held):
        """Keep 'station_types' naming exactly the drivers this file records.

        Args:
            held (dict): The [hardware] section, changed in place.
        """
        named = [
            name.strip()
            for name in str(held.get('station_types', '')).split(',')
            if name.strip()
        ]
        drivers = [name for name, value in held.items() if isinstance(value, dict)]
        kept = [name for name in named if name in drivers]
        kept += sorted(name for name in drivers if name not in kept)
        held['station_types'] = ', '.join(kept)

    def set_station(
        self,
        ident,
        name=None,
        infer_unknown=None,
        path=None,
        password=None,
        protocol=None,
        role=None,
        channel=None,
    ):
        """Record a station, or change one.

        Every argument left as None is left as it was, so that one caller can change
        a name without knowing anything about roles.

        Args:
            ident (str): The station's identity. Required.
            name (str | None): What to call it.
            infer_unknown (str | None): This station's own inference setting.
            path (str | None): An upload path of its own.
            password (str | None): The secret this station was given, for hardware
                that carries one rather than a path. Per station, because two
                consoles told apart by an ID need a secret each.
            protocol (str | None): Which protocol its uploads are read with.
            role (str | None): MAIN or EXTRA. Setting MAIN clears any channel, because the
                main station has no use for one.
            channel (int | None): Which extra channel it writes to, from 1 to CHANNELS.

        Returns:
            tuple: (ok, message), where the message is the path written or the
            reason nothing was.
        """
        with self.lock:
            ident = str(ident).strip()
            if not ident:
                return False, "A station with no identity cannot be told from another."
            stations = self.settings.setdefault('stations', {})
            station = stations.setdefault(ident, {})
            if path is not None:
                station['path'] = path
            if password is not None:
                station['password'] = password
            if protocol is not None:
                station['protocol'] = protocol
            if role is not None:
                from .roles import MAIN, ROLES

                if role not in ROLES:
                    return False, "A role is one of %s." % ', '.join(ROLES)
                station['role'] = role
                if role == MAIN:
                    # The main station's readings go where they belong. A channel left
                    # behind from when it was an extra sensor would read like it still
                    # meant something.
                    station.pop('channel', None)
            if channel is not None:
                from .roles import CHANNELS

                try:
                    channel = int(channel)
                except (TypeError, ValueError):
                    return False, "A channel is a number from 1 to %d." % CHANNELS
                if not 1 <= channel <= CHANNELS:
                    return False, (
                        "A channel is a number from 1 to %d. The standard "
                        "schema has that many extraTemp columns." % CHANNELS
                    )
                station['channel'] = str(channel)
            if name is not None:
                clean = _as_name(name)
                if not clean:
                    return False, (
                        "A name may hold letters, digits, dashes and "
                        "underscores. It becomes a section heading."
                    )
                station['name'] = clean
            if infer_unknown is not None:
                from .mapping import MODES

                if infer_unknown not in MODES:
                    return False, "infer_unknown must be one of %s." % ', '.join(MODES)
                station['infer_unknown'] = infer_unknown
            return self._save()

    def forget_station(self, ident):
        """Take a station out of this file.

        Args:
            ident (str): The station's identity.

        Returns:
            tuple: (ok, message).
        """
        with self.lock:
            stations = self.settings.get('stations', {})
            if ident not in stations:
                return False, "This file does not have that station."
            del stations[ident]
            return self._save()

    def set_field(self, ident, raw, field):
        """Place one raw field. An empty `field` removes the placement again.

        A placement written here outranks the driver's own `[[field_map_extensions]]`
        in `weewx.conf`, which is how the interface can be the place the decision is
        made rather than a read-only view of a file. What it cannot outrank is a
        station declared under `[[stations]]`: that station's field map is part of
        its declaration, and the driver refuses that one step higher up.

        Args:
            ident (str): The station the placement is for.
            raw (str): The raw field name, as the console sends it.
            field (str): The WeeWX field to write it to. Empty removes the placement;
                mapping.NOWHERE records that it is deliberately written nowhere.

        Returns:
            tuple: (ok, message).
        """
        with self.lock:
            from .mapping import NOWHERE

            raw = str(raw).strip()
            if not raw:
                return False, "No field named."
            stations = self.settings.setdefault('stations', {})
            station = stations.setdefault(str(ident).strip(), {})
            extensions = station.setdefault('field_map_extensions', {})
            field = str(field or '').strip()
            if not field:
                extensions.pop(raw, None)
            elif field == NOWHERE:
                # Written nowhere, on purpose, which is not the same as not
                # written here: taking the entry out would hand the reading back
                # to the catalog.
                extensions[raw] = NOWHERE
            else:
                if not _as_field(field):
                    return False, (
                        "A WeeWX field name may hold letters, digits and "
                        "underscores, and must not start with a digit."
                    )
                extensions[raw] = field
            return self._save()

    def columns(self):
        """{archive column: the identity of the station that fills it}."""
        return dict(self.settings.get('columns', {}))

    def set_column(self, field, ident):
        """Record which station fills one archive column.

        Args:
            field (str): The WeeWX field.
            ident (str): The station that fills it.

        Returns:
            tuple: (ok, message).
        """
        with self.lock:
            self.settings.setdefault('columns', {})[str(field)] = str(ident)
            return self._save()

    def drop_columns(self, fields):
        """Give up several columns at once, written once.

        Args:
            fields (iterable): The columns to release. Columns this file does not
                record are ignored.

        Returns:
            tuple: (ok, message). Releasing nothing is not an error.
        """
        with self.lock:
            held = self.settings.get('columns', {})
            gone = [f for f in fields if f in held]
            if not gone:
                return True, self.path
            for field in gone:
                del held[field]
            return self._save()

    def _save(self):
        """Write the whole file. Returns (ok, message)."""
        try:
            import configobj

            out = configobj.ConfigObj(encoding='utf-8', write_empty_values=True)
            out.filename = self.path
            out.initial_comment = HEADER.strip().splitlines()
            for key, value in self.settings.items():
                out[key] = value
            directory = os.path.dirname(self.path)
            if directory and not os.path.isdir(directory):
                os.makedirs(directory)
            # Written beside the target and moved into place, so that a full disk or
            # a power cut leaves the old file rather than half of a new one.
            temporary = self.path + '.new'
            with open(temporary, 'wb') as handle:
                out.write(handle)
            os.replace(temporary, self.path)
        except Exception as e:
            log.error("Cannot write %s: %s", self.path, e)
            return False, "Cannot write %s: %s" % (self.path, e)
        log.info("Wrote %s", self.path)
        return True, self.path


def _plain(node):
    """A configobj section as ordinary dicts, so nothing downstream has to know.

    Args:
        node (Any): A configobj.Section, whose contents are copied out, or
            anything else, which is returned unchanged.

    Returns:
        dict: The same content in plain dicts.
    """
    out = {}
    for key in node:
        value = node[key]
        out[key] = _plain(value) if hasattr(value, 'keys') else value
    return out


def _as_name(name):
    """A station name that is safe as a section heading and as a packet value.

    Args:
        name (str): The name as somebody typed it.

    Returns:
        str: The name with anything that would break a section heading removed, or
        an empty string if nothing usable is left.
    """
    name = str(name).strip()
    if not name or len(name) > 40:
        return ''
    return name if all(c.isalnum() or c in '-_' for c in name) else ''


def _as_field(field):
    """Whether this is usable as a WeeWX field name.

    Args:
        field (str): The name to check.

    Returns:
        str: The name if it is usable, otherwise an empty string. Anything else
        would make a column nobody can query.
    """
    field = str(field).strip()
    if not field or len(field) > 64 or field[0].isdigit():
        return ''
    return field if all(c.isalnum() or c == '_' for c in field) else ''
