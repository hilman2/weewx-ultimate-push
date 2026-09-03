#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""weewx.conf itself, shown as a table and written back a setting at a time.

overrides.py says why the settings this driver owns are kept in a file of its own
rather than here, and that reasoning stands: a field map has to take effect on the
next upload, and nothing written to weewx.conf can. This module is not a second home
for those. It is the rest of the file, which is most of it: `[Station]`, `[StdReport]`
and every skin under it, `[StdWXCalculate]`, the stanza of every other service
somebody runs. None of that is the driver's to hold, all of it is edited over ssh
today, and the person doing the editing is already looking at this page.

What it does not pretend:

    A change here takes effect at the next restart.  The engine read the file when
    it started and a driver cannot restart the engine it is part of. So every row
    the running configuration no longer agrees with is marked as such, and
    "I changed it and nothing happened" is a thing the page says rather than a
    thing somebody works out.

    The file is often root's.  Under a package installation weewx.conf belongs to
    root while the driver runs as the weewx user, so writing it fails. The page says
    so before anybody types, and offers each line with its headings to paste
    instead. Giving the file to the weewx user is enough to change that; its
    directory is not needed. See File._write for what that costs.

    Nothing here knows what a setting means.  weewx.conf has no schema, and this
    does not invent one: a value is whatever configobj can read back from the line
    it would write. What is refused is text that would not survive that round trip,
    and nothing else.

Comments survive, because configobj keeps them and this changes one value in the
file it read rather than building a new one. The file is read again immediately
before every write, so an edit made over ssh in between is carried over instead of
being overwritten, and what the file said before is kept beside it. See `BACKUP`.
"""

import logging
import os
import shutil
import threading

from typing import Any, Dict, List

log = logging.getLogger(__name__)

# What the file as it stood before the most recent change from here is called, beside
# weewx.conf. One file, overwritten every time, rather than a timestamped series:
# the mistake worth covering is "put back the thing I just did", a series of them
# would grow without limit on a machine nobody visits, and weectl already writes
# weewx.conf.YYYYMMDDHHMMSS, which this must not be mistaken for.
BACKUP = '.before-web-edit'

# The longest a key or a section heading may be. Nothing in weewx.conf comes near
# it; the limit is here so that a paste of a whole file into the name box is refused
# rather than written.
LONGEST = 200

CANNOT_QUOTE = (
    "A value holding both kinds of quote cannot be written on one line. "
    "Set it in the file itself."
)

WOULD_BE_A_COMMENT = (
    "Everything after a '#' is read as a comment. Put the value in quotes to "
    "keep it."
)


class File:
    """weewx.conf, read from disk when it is asked for and written a change at a time.

    Nothing is held between calls. The page is a picture of the file rather than of
    something this remembers, so a change made over ssh shows up on the next reload,
    and two browsers open on this page cannot save each other's stale copy.

    Args:
        path (str|None): Where weewx.conf is, or None when the driver was started
            without one. That happens in the tests and under `--url`, and every
            method says so rather than failing.
        backup_to (str|None): A directory to keep the backup in when weewx.conf's own
            directory cannot be written, which is the package installation. Defaults
            to that directory, which is where it belongs when it can go there.
    """

    def __init__(self, path, backup_to=None):
        self.path = path
        self.backup_to = backup_to
        # One writer at a time. Each write is read, change, write, and two of those
        # interleaved would lose the first change.
        self.lock = threading.Lock()

    # ---- reading -------------------------------------------------------------

    def view(self, running=None):
        """The whole file, in the shape the page draws.

        Args:
            running (dict|None): The configuration WeeWX is running on, as the
                loader was given it. Used for nothing but marking the rows the file
                and the engine now disagree about.

        Returns:
            dict: 'ok', and then either 'error' or the file: 'path', whether it is
            'writable', where the backup would go, and 'sections', each carrying its
            heading path, the comment above it, and its entries.
        """
        if not self.path:
            return {
                'ok': False,
                'error': (
                    "This driver was started without a configuration file, so there "
                    "is no weewx.conf to show."
                ),
            }
        parsed, why = self._open()
        if parsed is None:
            return {'ok': False, 'error': why}
        return {
            'ok': True,
            'path': self.path,
            'writable': _writable(self.path),
            'backup': self.backup_path(),
            'sections': _sections(parsed, running or {}),
        }

    def backup_path(self):
        """Where the copy of the file as it stood before the last change goes.

        Beside weewx.conf, unless that directory cannot be written, which is the
        package installation: there it goes beside the driver's own settings file,
        because a backup that cannot be written is a write that cannot happen.

        Returns:
            str: The path, or an empty string when there is no configuration file.
        """
        if not self.path:
            return ''
        directory = os.path.dirname(self.path) or '.'
        if not os.access(directory, os.W_OK) and self.backup_to:
            return os.path.join(self.backup_to, os.path.basename(self.path) + BACKUP)
        return self.path + BACKUP

    def _open(self):
        """The file as configobj reads it, comments and all.

        Read with interpolation off, so that a value holding `%(WEEWX_ROOT)s` is
        shown and written as the file has it rather than expanded into the file.
        WeeWX reads the same file with interpolation on, which is why a value like
        that is never compared against the running configuration.

        Returns:
            tuple: (configobj.ConfigObj, str). The file and an empty string, or None
            and the reason there is nothing to show.
        """
        try:
            import configobj

            return (
                configobj.ConfigObj(
                    self.path,
                    encoding='utf-8',
                    file_error=True,
                    interpolation=False,
                ),
                '',
            )
        except Exception as e:
            log.error("Cannot read %s: %s", self.path, e)
            return None, "Cannot read %s: %s" % (self.path, e)

    # ---- writing -------------------------------------------------------------

    def set(self, where, key, text):
        """Change a setting the file already has.

        Separate from add() on purpose. A typed key that is not there is nearly
        always a typo, and a typo written into weewx.conf is a setting that looks
        set and does nothing.

        Args:
            where (list[str]): The headings above the setting, outermost first.
                Empty for one at the top of the file.
            key (str): The setting.
            text (str): The new value, as it would be typed to the right of the
                '=' in the file.

        Returns:
            tuple: (bool, str). Whether it was written, and either the path or the
            reason it was not.
        """
        with self.lock:
            return self._change(where, key, text, must_exist=True)

    def add(self, where, key, text):
        """Put a setting the file does not have into one of its sections.

        Args:
            where (list[str]): The headings of the section it goes in, outermost
                first. Empty for the top of the file.
            key (str): The setting's name.
            text (str): Its value, as it would be typed in the file.

        Returns:
            tuple: (bool, str).
        """
        with self.lock:
            return self._change(where, key, text, must_exist=False)

    def _change(self, where, key, text, must_exist):
        """Read, put one value in, write. The whole of set() and add().

        Args:
            where (list[str]): The headings, outermost first.
            key (str): The setting.
            text (str): Its value, as typed.
            must_exist (bool): True when the setting has to be there already,
                which is what tells a change from a typo.

        Returns:
            tuple: (bool, str).
        """
        clean = _as_key(key)
        if not clean:
            return False, _NOT_A_NAME
        if _is_secret(clean) and not str(text or '').strip():
            # The page shows no value for these, so an empty box means "left alone"
            # rather than "make it empty", and writing it would wipe a password
            # nobody meant to touch. Emptying one on purpose is what remove() is for.
            return False, (
                "This value is not shown here, so an empty box would wipe it. Type "
                "the new value, or remove the setting."
            )
        value, why = _value_of(text)
        if why:
            return False, why
        parsed, reason = self._locked_open()
        if parsed is None:
            return False, reason
        section = _find(parsed, where)
        if section is None:
            return False, _no_such_section(where)
        if must_exist and clean not in section.scalars:
            return False, "%s has no setting called '%s'." % (_named(where), clean)
        if not must_exist and clean in section.scalars:
            return False, "%s already has a setting called '%s'." % (
                _named(where),
                clean,
            )
        section[clean] = value
        return self._write(parsed)

    def remove(self, where, key):
        """Take one setting out of the file.

        Args:
            where (list[str]): The headings above it, outermost first.
            key (str): The setting.

        Returns:
            tuple: (bool, str).
        """
        with self.lock:
            parsed, reason = self._locked_open()
            if parsed is None:
                return False, reason
            section = _find(parsed, where)
            if section is None:
                return False, _no_such_section(where)
            if key not in section.scalars:
                return False, "%s has no setting called '%s'." % (_named(where), key)
            del section[key]
            return self._write(parsed)

    def add_section(self, where):
        """Add an empty section, inside whichever one already holds its place.

        Args:
            where (list[str]): The new section's whole heading path, outermost
                first. Everything above the last name has to be there already:
                a section whose parent is missing is a section nothing reads, and
                asking for it usually means the path was typed wrong.

        Returns:
            tuple: (bool, str).
        """
        with self.lock:
            if not where:
                return False, "A section needs a name."
            names = [_as_key(name) for name in where]
            if not all(names):
                return False, _NOT_A_NAME
            parsed, reason = self._locked_open()
            if parsed is None:
                return False, reason
            above = _find(parsed, names[:-1])
            if above is None:
                return False, _no_such_section(names[:-1])
            if names[-1] in above.sections:
                return False, "%s is already there." % _named(names)
            if names[-1] in above.scalars:
                return False, "%s already has a setting called '%s'." % (
                    _named(names[:-1]),
                    names[-1],
                )
            above[names[-1]] = {}
            return self._write(parsed)

    def remove_section(self, where, force=False):
        """Take a section out of the file, with everything under it.

        Args:
            where (list[str]): Its heading path, outermost first.
            force (bool): Needed for a section that is not empty. Without it one
                that holds settings is refused and the reply says how many, so
                that removing `[StdReport]` is a decision rather than a click.

        Returns:
            tuple: (bool, str).
        """
        with self.lock:
            if not where:
                return False, "A section needs a name."
            parsed, reason = self._locked_open()
            if parsed is None:
                return False, reason
            above = _find(parsed, where[:-1])
            if above is None or where[-1] not in getattr(above, 'sections', []):
                return False, _no_such_section(where)
            held = _holds(above[where[-1]])
            if held and not force:
                return False, "%s holds %d settings. Removing it takes them too." % (
                    _named(where),
                    held,
                )
            del above[where[-1]]
            return self._write(parsed)

    def _locked_open(self):
        """The file, read again with the lock held, for a caller about to change it.

        Every write reads the file first rather than working from anything kept in
        memory, so that a change made in a terminal between two clicks on the page
        is carried over rather than written back out of date.

        Returns:
            tuple: (configobj.ConfigObj, str). The file and an empty string, or
            None and the reason.
        """
        if not self.path:
            return None, (
                "This driver was started without a configuration file, so there is "
                "no weewx.conf to write."
            )
        return self._open()

    def _write(self, parsed):
        """Write the file back, keeping what it said before it beside it.

        Two ways of writing, and which one is used is decided by the directory rather
        than by a setting.

        Where the directory can be written, the new file is written next to the old
        one and moved into place, so that a full disk or a power cut leaves the old
        file rather than half of a new one. That replaces the file instead of filling
        it, so the mode is carried over explicitly and the owner becomes whoever
        WeeWX runs as.

        Where it cannot, the file is filled in place. That is the package
        installation, where `/etc/weewx` is root's and `chown weewx weewx.conf` is
        the one change somebody makes to be able to edit from here. Requiring a
        writable directory as well would mean that change did nothing, and the whole
        page would be read-only on the commonest installation. What it costs is the
        power cut: the file is truncated and rewritten, so a crash in between leaves
        it short, and the backup is what puts it back.

        Args:
            parsed (configobj.ConfigObj): The file, already changed.

        Returns:
            tuple: (bool, str). Whether it was written, and either the path or the
            reason it was not.
        """
        if not _writable(self.path):
            # Asked before trying, because os.replace goes by the directory and
            # would go straight past a file somebody made read-only on purpose. The
            # page says the file cannot be written; this is what makes that true.
            return False, (
                "Cannot write %s: it does not belong to the user WeeWX runs as."
                % self.path
            )
        backup = self.backup_path()
        directory = os.path.dirname(self.path) or '.'
        try:
            shutil.copy2(self.path, backup)
            if os.access(directory, os.W_OK):
                temporary = self.path + '.new'
                with open(temporary, 'wb') as handle:
                    parsed.write(handle)
                shutil.copymode(backup, temporary)
                os.replace(temporary, self.path)
            else:
                with open(self.path, 'wb') as handle:
                    parsed.write(handle)
        except OSError as e:
            log.error("Cannot write %s: %s", self.path, e)
            return False, "Cannot write %s: %s" % (self.path, e)
        log.info("Wrote %s. What it said before is in %s.", self.path, backup)
        return True, self.path


# ---- what a row looks like ---------------------------------------------------


def _sections(parsed, running):
    """Every section of the file, in the order the file is written.

    Args:
        parsed (configobj.ConfigObj): The file.
        running (dict): What WeeWX is running on, for the 'differs' flag.

    Returns:
        list[dict]: One entry per section, the settings at the top of the file
        first under an empty heading path.
    """
    found = []  # type: List[Dict[str, Any]]
    _gather(parsed, [], _comment(parsed.initial_comment), running, found)
    return found


def _gather(node, where, comment, running, found):
    """Add one section and then the sections inside it, depth first.

    Depth first rather than a level at a time, because that is the order the file
    itself is in, and the page is a picture of the file.

    Args:
        node (configobj.Section): The section to add.
        where (list[str]): The headings above it, outermost first.
        comment (str): The comment written above its heading.
        running (dict): The matching part of what WeeWX is running on, or an empty
            dict once the file has a section the running configuration has not.
        found (list): The sections so far, appended to.
    """
    found.append(
        {
            'path': list(where),
            'depth': len(where),
            # Written the way the file writes it, and written here rather than on the
            # page, so that a heading in a message and a heading in the table are
            # one rule rather than two that drift.
            'heading': _named(where),
            'comment': comment,
            'entries': [_entry(node, key, running) for key in node.scalars],
        }
    )
    for name in node.sections:
        under = running.get(name)
        _gather(
            node[name],
            where + [name],
            _comment(node.comments.get(name)),
            under if hasattr(under, 'keys') else {},
            found,
        )


def _entry(node, key, running):
    """One setting, as the page shows it.

    Args:
        node (configobj.Section): The section it is in.
        key (str): The setting.
        running (dict): The matching part of what WeeWX is running on.

    Returns:
        dict: The key, the value as it would be typed, whatever comment stands
        above and beside it, whether it can be edited on one line, and whether the
        engine is running on something else. A setting whose name says it holds a
        secret carries no value at all: see SECRETS.
    """
    text, single = _shown(node[key])
    entry = {
        'key': key,
        'comment': _comment(node.comments.get(key)),
        'inline': (node.inline_comments.get(key) or '').lstrip('#').strip(),
        'single': single,
        'hidden': _is_secret(key),
        'differs': False,
        'running': '',
    }
    entry['value'] = '' if entry['hidden'] else text
    live = running.get(key)
    # A value holding %(...)s is never compared: WeeWX reads the file with
    # interpolation on and this reads it with interpolation off, so the two are
    # different renderings of one setting rather than a disagreement.
    if live is not None and single and '%(' not in text:
        was = _shown(live)[0]
        entry['differs'] = was != text
        if entry['differs'] and not entry['hidden']:
            entry['running'] = was
    return entry


# Settings whose name says they hold a secret. Their value is not sent to the page
# at all: the interface is HTTP, so anything it shows travels in the clear, and a
# database password in a payload is a worse exposure than one in a file that never
# leaves the machine. The row still says the setting is there and still takes a new
# value, which is what somebody changing one actually needs.
#
# Matched as a substring of the lowercased key, so that 'api_key', 'station_password'
# and 'app_token' are all covered without a list of every service's spelling.
SECRETS = ('password', 'passwd', 'passkey', 'token', 'secret', 'api_key', 'apikey')


def _is_secret(key):
    """Whether a setting's name says it holds something not to be shown.

    Args:
        key (str): The setting's name.

    Returns:
        bool: True when the value is kept off the page. See SECRETS.
    """
    low = str(key).lower()
    return any(mark in low for mark in SECRETS)


def _shown(value):
    """A value as it stands to the right of the '=' in the file.

    So that what the page shows can be typed back in and mean the same thing. The
    text is what configobj would write rather than something assembled here: a list
    is its members separated by commas, a string holding a comma is quoted, because
    unquoted it would come back as a list. Asking configobj to write the line is the
    only way to be sure of that; a rule of ours would eventually part company with
    the one that reads the file.

    Args:
        value (str|list): What configobj read for the setting.

    Returns:
        tuple: (str, bool). The text, and whether it fits on one line. A value
        configobj writes as a triple-quoted block does not, and the page shows
        those without offering to change them.
    """
    import configobj

    # An empty setting is shown as an empty box. configobj writes it as a pair of
    # quotes, which is the same thing to whatever reads the file back and reads on
    # the page as a value of two characters.
    if value == '':
        return '', True
    # No encoding on this one. Given one, write() hands back encoded bytes, and what
    # is wanted here is the line as text.
    out = configobj.ConfigObj()
    out['x'] = value
    lines = out.write()
    if len(lines) != 1:
        return '\n'.join(lines), False
    return lines[0].split('=', 1)[1].strip(), True


def _value_of(text):
    """Text somebody typed, as the value that line would mean in the file.

    Parsed by configobj rather than by a rule of ours, for the reason in _shown:
    `1, 2, 3` is a list and `"Berlin, Germany"` is one string, and which is which
    is decided by whatever will read the file back.

    Args:
        text (str): What was typed.

    Returns:
        tuple: (str|list, str). The value to store and an empty string, or None and
        the reason the line could not be written.
    """
    import configobj

    text = str(text if text is not None else '')
    if '\n' in text or '\r' in text:
        return None, "A value has to fit on one line."
    try:
        # Interpolation off, for the same reason File._open has it off: a value
        # holding %(WEEWX_ROOT)s is one this file may set, and with interpolation on
        # reading it back raises rather than returning it.
        value = configobj.ConfigObj(['x = ' + text], interpolation=False)['x']
    except Exception:
        return None, CANNOT_QUOTE
    # '#' starts a comment, so an unquoted one would silently take the rest of the
    # line with it. What configobj would write back is the test for that: if the
    # '#' is not in it, it was read as a comment and the value typed is not the
    # value that would be stored.
    if '#' in text and '#' not in _shown(value)[0]:
        return None, WOULD_BE_A_COMMENT
    return value, ''


def _comment(lines):
    """The comment above something, as prose.

    configobj keeps it as the raw lines, blank ones included and each still
    carrying its '#'. The page shows it as a paragraph beside the setting, so the
    marks come off here and the blank lines that only separate one block from the
    next are trimmed from the ends.

    Args:
        lines (list[str]|None): The lines configobj kept, or None where a setting
            has nothing written above it.

    Returns:
        str: The comment, or an empty string.
    """
    kept = []
    for line in lines or []:
        stripped = line.strip()
        if stripped.startswith('#'):
            kept.append(stripped.lstrip('#').strip())
        elif not stripped:
            kept.append('')
    while kept and not kept[0]:
        kept.pop(0)
    while kept and not kept[-1]:
        kept.pop()
    return '\n'.join(kept)


# ---- names and places --------------------------------------------------------

_NOT_A_NAME = (
    "A name may not hold '[', ']', '=' or '#', which are what a configuration "
    "file is made of."
)


def _as_key(name):
    """A key or a section heading the file could carry.

    Args:
        name (str): As somebody typed it.

    Returns:
        str: The name, trimmed, or an empty string when the file could not carry
        it: a heading needs its brackets and a setting needs its '=', so a name
        holding either is one nothing could read back.
    """
    name = str(name if name is not None else '').strip()
    if not name or len(name) > LONGEST:
        return ''
    if any(c in name for c in '[]=#\n\r'):
        return ''
    return name


def _find(parsed, where):
    """The section a heading path names.

    Args:
        parsed (configobj.ConfigObj): The file.
        where (list[str]): The headings, outermost first. Empty names the top of
            the file, which is a section like any other as far as this goes.

    Returns:
        configobj.Section: The section, or None when the path names one that is not
        in the file.
    """
    node = parsed
    for name in where:
        if name not in getattr(node, 'sections', []):
            return None
        node = node[name]
    return node


def _holds(node):
    """How many settings are in a section, counting the ones inside it.

    Args:
        node (configobj.Section): The section.

    Returns:
        int: The count, which is what decides whether removing it needs saying
        twice.
    """
    return len(node.scalars) + sum(_holds(node[name]) for name in node.sections)


def _named(where):
    """A heading path, written the way the file writes it.

    Args:
        where (list[str]): The headings, outermost first.

    Returns:
        str: '[[Defaults]]' and so on, or a phrase for the top of the file, which
        has no heading to name.
    """
    if not where:
        return "The top of the file"
    depth = len(where)
    return '%s%s%s' % ('[' * depth, where[-1], ']' * depth)


def _no_such_section(where):
    """What to say when a heading path names nothing.

    Args:
        where (list[str]): The headings that were asked for.

    Returns:
        str: A message naming the path as the file would write it.
    """
    return "%s is not in the file." % _named(where)


def _writable(path):
    """Whether this process could write the file, without writing it.

    The file alone, not the directory it is in: File._write fills the file in place
    where the directory is somebody else's, so `chown weewx weewx.conf` is enough on
    its own. Saying which it is before anybody types is worth the stat call.

    Args:
        path (str): The file.

    Returns:
        bool: True when a write would be allowed to start.
    """
    return os.access(path, os.W_OK)
