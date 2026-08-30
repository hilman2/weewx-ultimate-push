#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""Hardware that has to be asked, beside hardware that pushes.

WeeWX runs one driver. A station with a Vantage on a serial port and an Ecowitt
gateway uploading over HTTP therefore needs two WeeWX instances, two databases and
two sets of reports, for what is one weather station in one garden.

This module removes that. It loads WeeWX drivers the way the engine loads them:
import the module the stanza names, call its `loader()` with the untouched
`config_dict`. Each runs on a thread of its own and its loop packets join the
stream the uploads arrive on. A hosted driver needs no changes and knows nothing
about this. Its own `[Vantage]` or `[WMR100]` section is read by its own loader, so
`weectl device` and the configurators keep working, and a driver from elsewhere
works for the same reason a driver from WeeWX does.

Four things make this more than a queue.

    **LOOP and history are exclusive on one device.**  A Vantage streaming LOOP
    packets cannot answer DMPAFT at the same time, and both go down one serial
    port. So a child pulls loop packets only while it has been told to, and it is
    told to stop before the engine asks for archive records. See `Child.start_loop`.

    **A driver may also be a service.**  Of the thirteen drivers WeeWX ships,
    Vantage is the one: its loader returns a `VantageService`, which binds to
    NEW_LOOP_PACKET and writes the archive period's highest gust into the packet.
    Bound to the real engine it would do that to every packet in the stream, so an
    Ecowitt console's wind speed would raise the Vantage's gust, and the gust that
    console measured itself would be overwritten. A child is therefore given a
    `Facade` rather than the engine, and sees only its own packets.

    **A child that fails comes back.**  A USB gateway unplugged for a second must
    not cost its station until somebody restarts WeeWX. A child that raises is
    closed, waited out and built again, with the wait doubling up to LONGEST_WAIT.

    **The archive station and the main station are different questions.**  The
    archive station is the one whose logger supplies archive records and whose
    clock is read. The main station, in the sense roles.py means, is the one whose
    readings go into the plain columns. On most installations they are one device.
    They need not be: a Vantage with a logger can carry the archive while an
    Ecowitt console with more sensors is the main station.

Nothing here decides which readings are kept. A hosted driver's packets go through
roles and owners exactly as an upload's do, and that is what keeps two stations out
of one column.

Configuration, in the driver's own section:

    [UltimatePush]
        [[hardware]]
            # Top-level stanzas to run. The first is the archive station.
            station_types = Vantage, WMR100
            [[[Vantage]]]
                role = main
            [[[WMR100]]]
                role = extra
                channel = 3
"""

import collections
import ast
import importlib
import importlib.util
import inspect
import io
import logging
import os
import pkgutil
import queue
import re
import threading
from typing import Dict, List, TYPE_CHECKING

import weewx

# For the docstring types only. A hosted driver's module is handed straight from
# importlib to its own loader, and nothing here needs the name at runtime.
if TYPE_CHECKING:
    import types

log = logging.getLogger(__name__)

# How long a blocked reader waits before looking up to see whether it has been
# closed. The same interval the listener uses, for the same reason.
POLL = 1.0

# How long to wait for a child's thread to finish once it has been asked to stop.
JOIN = 5.0

# How long to wait for the archive station to stop looping before asking it for
# history. A child is told to stop between packets, so it is already waiting for its
# next reading when the message arrives, and Python cannot interrupt a read. So the
# stop takes effect when that read returns, and this is how long the engine's thread
# is prepared to wait for it. A Vantage streams a packet every two seconds, so it
# settles well inside this.
SETTLE = 5.0

# How long to wait before building a failed child again, and the ceiling the wait
# doubles towards. A gateway that is unplugged and plugged back in is back within
# the first wait; one that is gone for the evening is asked for every five minutes
# rather than every ten seconds.
FIRST_WAIT = 10.0
LONGEST_WAIT = 300.0

# What the engine's thread asks of a child's thread. CALL carries a method name and
# its arguments and waits for the answer; the other three do not.
START = 'start'
STOP = 'stop'
CALL = 'call'
CLOSE = 'close'

_Command = collections.namedtuple(
    '_Command', ['kind', 'name', 'args', 'kwargs', 'answer']
)

# The engine events a hosted driver is given. NEW_LOOP_PACKET is not among them: it
# is delivered per packet, by Host.deliver, because only the packet says which child
# it belongs to. The rest are about the run rather than about a reading, so every
# child gets them.
FORWARDED = (
    weewx.STARTUP,
    weewx.PRE_LOOP,
    weewx.POST_LOOP,
    weewx.END_ARCHIVE_PERIOD,
    weewx.SHUTDOWN,
)


# Modules under 'user' that are never hardware. This driver's own, and the copy of
# the core listener it carries for older WeeWX.
NOT_HARDWARE = frozenset(['user.listener', 'user.ultimatepush'])


def available():
    """Every driver on this machine that could be hosted.

    Both the ones WeeWX ships and the ones somebody installed as an extension, found
    the same way: a module with a `loader` and a `DRIVER_NAME` is a driver. That is
    all WeeWX itself requires of one.

    Importing a module runs it, which is what `weectl station reconfigure` does too.
    A module that will not import is reported rather than left out, because "the
    WMR300 is not in the list" and "the WMR300 needs pyusb, which is not installed"
    send somebody to very different places.

    Returns:
        list[dict]: One per driver, sorted by the section name, each holding what
        template_for returned for it, plus 'module' the import path, 'name' the
        section it wants, and 'problem' saying why it cannot be used, or None.
    """
    found = []
    for module_name in _driver_modules():
        try:
            module = importlib.import_module(module_name)
        except Exception as e:
            if not _reads_as_a_driver(module_name):
                # An extension that is not hardware at all. That it will not import
                # is worth knowing, but not here: a service missing a library it
                # needs is not a console missing from the list of consoles.
                log.debug("%s is not a driver and will not import: %s", module_name, e)
                continue
            found.append(
                {
                    'module': module_name,
                    'name': module_name.rsplit('.', 1)[-1],
                    'fields': {},
                    'connects': BY_NOTHING,
                    'about': '',
                    'problem': str(e),
                }
            )
            continue
        if not hasattr(module, 'loader') or not getattr(module, 'DRIVER_NAME', None):
            continue
        found.append(
            dict(
                template_for(module),
                module=module_name,
                name=str(module.DRIVER_NAME),
                problem=None,
            )
        )
    return sorted(found, key=lambda one: one['name'].lower())


def _reads_as_a_driver(module_name):
    """Whether a module that will not import was meant to be a driver.

    Read rather than imported, because the module has already refused to import
    once. WeeWX asks two things of a driver, a `loader` and a `DRIVER_NAME`, and
    both are visible in the source without running any of it.

    Args:
        module_name (str): The import path.

    Returns:
        bool: Whether it holds both. True as well when the source cannot be read or
        parsed at all, because then the import error is the useful thing to say.
    """
    try:
        spec = importlib.util.find_spec(module_name)
        origin = getattr(spec, 'origin', None)
        if not origin:
            return True
        with io.open(origin, encoding='utf-8') as handle:
            tree = ast.parse(handle.read())
    except Exception:
        return True
    named = False
    loaded = False
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == 'loader':
            loaded = True
        if isinstance(node, ast.Assign):
            for target in node.targets:
                named = named or getattr(target, 'id', '') == 'DRIVER_NAME'
    return named and loaded


def _driver_modules():
    """The module names worth asking whether they are drivers.

    Returns:
        list[str]: Import paths, from weewx.drivers and from the 'user' package an
        installation keeps its extensions in.
    """
    names = []
    for package_name in ('weewx.drivers', 'user'):
        try:
            package = importlib.import_module(package_name)
        except Exception:
            # No 'user' package outside a WeeWX installation, which is the usual
            # case in a test.
            continue
        for _, name, _ in pkgutil.iter_modules(getattr(package, '__path__', [])):
            full = '%s.%s' % (package_name, name)
            if full not in NOT_HARDWARE:
                names.append(full)
    return names


# Options that take one of a fixed set of values, by driver module and option name.
#
# This is a copy of something the drivers say, which is the thing to avoid, and it is
# here because they do not say it in any other way. Two of the thirteen declare their
# choices to `_prompt` and eleven state them in a comment, in prose, mixed in with
# comments that read the same and are not choices at all: `port` is "such as
# /dev/ttyS0, /dev/ttyUSB0, or /dev/cuaU0" and `model` is "e.g., 'LaCrosse WS2317' or
# 'TFA Primus'". Both are examples of a free value. Reading choices out of that
# sentence would offer three serial ports as if they were the only ones.
#
# So the four real ones are named here, and tests/test_hardware.py checks each against
# the driver it belongs to: that the option still exists, and that the driver's own
# default is one of the values. A driver that gains a choice makes that test say so.
# A field built from this always keeps a way to type something else, so that a copy
# which has fallen behind costs a convenience rather than the setting.
#
# A value on its own is its own label. A pair is (value, label), for the ones whose
# values mean nothing on their own: '2' is not an answer to "which Vantage is this",
# and 'Vantage Pro2' is.
CHOICES = {
    'weewx.drivers.simulator': {'mode': ['simulator', 'generator']},
    'weewx.drivers.vantage': {
        # vantage.py: connection_type is compared against these two and anything
        # else raises UnsupportedFeature.
        'type': ['serial', 'ethernet'],
        # "loop_request: Requested packet type. 1=LOOP; 2=LOOP2; 3=both."
        'loop_request': [('1', 'LOOP1'), ('2', 'LOOP2'), ('3', 'both')],
        # `if self.model_type not in (1, 2): raise UnsupportedFeature`.
        'model_type': [('1', 'Vantage Pro'), ('2', 'Vantage Pro2')],
    },
    'weewx.drivers.ws1': {
        # ws1.py compares con_mode against these three and raises ValueError on
        # anything else.
        'mode': ['serial', 'tcp', 'udp']
    },
    # wmr9x8.py: `if connection_type == "serial"`, and the else raises
    # UnsupportedFeature. One value, so there is nothing to choose and the field
    # says so rather than inviting somebody to type something that cannot work.
    'weewx.drivers.wmr9x8': {'type': ['serial']},
    'weewx.drivers.ws28xx': {'transceiver_frequency': ['US', 'EU']},
}  # type: Dict[str, Dict[str, list]]

# What each driver reaches its hardware over, worked out from what the module needs
# rather than from what its comments say. A driver that imports pyusb talks to a USB
# device and has no port to set; one that has a port defaulting to a device node is
# on a cable. This is the sentence a form otherwise cannot answer: an Oregon
# Scientific WMR100 offers nothing but a name, and somebody looking at that has no
# way to tell whether they have missed a step.
BY_USB = 'usb'
BY_CABLE = 'cable'
BY_EITHER = 'either'
BY_BROADCAST = 'broadcast'
BY_NETWORK = 'network'
BY_COMMAND = 'command'
BY_NOTHING = 'nothing'

CONNECTS = {
    BY_USB: (
        "It is found over USB. Nothing below has to be changed: plug it in, and "
        "the driver looks for it."
    ),
    BY_CABLE: (
        "It is read over a cable, which may be a USB-to-serial adapter. The port "
        "is the one setting that has to be right."
    ),
    BY_EITHER: (
        "It is read over a cable or over the network, and which of the two decides "
        "which of the settings below apply."
    ),
    BY_BROADCAST: (
        "It is not asked for anything. The hub sends its readings out to the whole "
        "local network and the driver listens, so the one thing that has to be true "
        "is that both are on that same network."
    ),
    BY_NETWORK: (
        "It is asked over the network. The address below is the one setting that "
        "has to be right."
    ),
    BY_COMMAND: (
        "It does not reach the hardware itself. It runs another program that does, "
        "and the path to that program is the one setting that has to be right."
    ),
    BY_NOTHING: "",
}

# Where a serial device shows up. The first is the one to offer: a name under
# by-id is made from the adapter's own manufacturer and serial number, so it is the
# same after a reboot and after something else is plugged in, which /dev/ttyUSB0
# is not.
SERIAL_DIRS = ('/dev/serial/by-id', '/dev/serial/by-path')
SERIAL_NAMES = ('ttyUSB', 'ttyACM', 'ttyS', 'cuaU', 'cu.usbserial')


def serial_ports():
    """The serial devices on this machine, for a form to offer rather than explain.

    "Which of these is my station" is a question somebody standing next to it can
    answer from the adapter's name, and cannot answer from a text box. So the list
    is what is actually there, by-id first because that name survives a reboot.

    Returns:
        list[dict]: One per device, each with 'value' to put in the field and
        'label' to show. Empty on a machine with no serial devices, and on one
        where /dev cannot be read, which is every Windows machine and every test.
    """
    found = []
    seen = set()
    for directory in SERIAL_DIRS:
        try:
            names = sorted(os.listdir(directory))
        except OSError:
            continue
        for name in names:
            path = os.path.join(directory, name)
            try:
                real = os.path.realpath(path)
            except OSError:
                real = ''
            if real in seen:
                continue
            seen.add(real)
            found.append(
                {
                    'value': path,
                    'label': '%s%s' % (name, ' \u2192 %s' % real if real else ''),
                }
            )
    try:
        rest = sorted(os.listdir('/dev'))
    except OSError:
        rest = []
    for name in rest:
        if not name.startswith(SERIAL_NAMES):
            continue
        path = os.path.join('/dev', name)
        if path in seen:
            continue
        seen.add(path)
        found.append({'value': path, 'label': name})
    return found


def template_for(module):
    """The form a driver's own configuration editor describes.

    Every driver WeeWX ships carries a `confeditor_loader`, whose `default_stanza`
    is the block `weectl station reconfigure` writes. It names every option that
    driver takes, a working default for each, and a comment above each saying what
    it is, all written by whoever wrote the driver. That is the form, and there is
    no reason to keep a second copy of it here that would be wrong the moment a
    driver gained an option.

    The comment is taken from the last run of lines above the option, so that the
    section's own preamble and the banners some stanzas carry between groups of
    options do not end up attached to whichever option happens to follow them.

    Args:
        module (types.ModuleType): The driver module.

    Returns:
        dict: 'fields', option name to {'value': the default as a string, 'help':
        what the driver's author says it is as a list of lines, 'choices': the
        values it takes or an empty list, 'kind': 'fixed', 'choice', 'port' or
        'text', 'when': the option and values it depends on or None, 'rarely':
        whether the author ruled it off as rarely needing attention}; 'connects',
        how the driver reaches its hardware; and 'about', the sentence that goes
        with it. A driver from elsewhere may have no configuration editor, and then
        there is only the 'driver' field.
    """
    plain = {
        'driver': {
            'value': module.__name__,
            'help': [],
            'choices': [],
            'kind': 'text',
            'when': None,
            'rarely': False,
        }
    }
    bare = {'fields': plain, 'connects': BY_NOTHING, 'about': ''}
    if not hasattr(module, 'confeditor_loader'):
        return _from_the_class(module, plain) or bare
    try:
        import configobj

        stanza = module.confeditor_loader().default_stanza
        parsed = configobj.ConfigObj(io.StringIO(stanza.strip()))
    except Exception as e:
        log.debug("No usable stanza from %s: %s", module.__name__, e)
        return bare
    choices = CHOICES.get(module.__name__, {})
    when = _conditions(module)
    written = {}
    for section in parsed.sections:
        for key in parsed[section].scalars:
            written[key] = parsed[section][key]
    reach = _connects(module, written)
    fields = {}
    for section in parsed.sections:
        held = parsed[section]
        # The stanza's order is somebody's idea of which options matter: a Vantage
        # names the connection type and the port first, then rules off eleven that
        # rarely need attention. That rule is the author saying so, and it is worth
        # more than any guess this could make about which are worth showing.
        rarely = False
        for key in held.scalars:
            rarely = rarely or _is_a_rule(held.comments.get(key))
            options = _offered(choices.get(key))
            fields[key] = {
                'value': held[key],
                'help': _help_for(held, key),
                'choices': options,
                'kind': _kind_for(options, key, held[key]),
                'when': when.get(key),
                'rarely': rarely and key != 'driver',
            }
    fields.setdefault('driver', plain['driver'])
    return {'fields': fields, 'connects': reach, 'about': CONNECTS[reach]}


def _connects(module, options):
    """How a driver reaches its hardware, from what the module needs to do it.

    What separates a cable from a network is the default `port` rather than the
    name: every driver WeeWX ships defaults it to a device under `/dev`, and an
    MQTT client defaults it to 1883. Both are called `port`, and telling somebody
    with a broker to go and look in `/dev/serial/by-id/` helps nobody.

    Args:
        module (types.ModuleType): The driver module.
        options (dict): Option name to its default, as template_for has them.

    Returns:
        str: One of BY_USB, BY_CABLE, BY_EITHER, BY_BROADCAST, BY_NETWORK,
        BY_COMMAND or BY_NOTHING.
    """
    cabled = str(options.get('port', '')).startswith('/dev/')
    # A second way in beside the cable, which is what makes the choice a setting.
    # Not 'type': a WMR9x8 has one of those and only ever means serial by it.
    if cabled and ('host' in options or 'mode' in options):
        return BY_EITHER
    # A driver that names a UDP port of its own is waiting to be sent to rather than
    # reading something. Asked before the rest, because 'udp_port' is not 'port'
    # and would otherwise fall past every test here.
    if any(key.startswith('udp_') for key in options):
        return BY_BROADCAST
    try:
        source = inspect.getsource(module)
    except Exception:
        source = ''
    if re.search(r'^\s*import (usb|hid)\b|usb\.core', source, re.M):
        return BY_USB
    if cabled:
        return BY_CABLE
    # A driver that shells out to a radio receiver has no hardware setting at all.
    # What has to be found is the program, which is a path like any other and
    # nothing like an address.
    if 'cmd' in options or 'command' in options:
        return BY_COMMAND
    if 'host' in options or 'port' in options:
        return BY_NETWORK
    return BY_NOTHING


def _from_the_class(module, plain):
    """The form a driver describes in its constructor, when it ships no editor.

    A driver from elsewhere often has no `confeditor_loader`, and then WeeWX has
    nothing to write into a configuration file and this has nothing to build a form
    from. The constructor does hold the list: WeeWX hands a driver its stanza as
    keyword arguments, and the constructor reads them one at a time, which names
    every option the driver takes and the default it falls back on. That is the same
    list an editor would have carried, read out of the one place that cannot
    describe a version nobody has.

    What this cannot recover is what each option means, because the author wrote
    that in a README rather than beside the option. The fields come out named and
    defaulted but unexplained, which is worth more than the one line a driver
    without an editor would otherwise show.

    Args:
        module (types.ModuleType): The driver module.
        plain (dict): The 'driver' field template_for falls back on.

    Returns:
        dict: The shape template_for returns, or None when the module holds no
        driver class, or that class does not read a stanza.
    """
    asked = _asked_of(module)
    if not asked:
        return None
    choices = CHOICES.get(module.__name__, {})
    fields = {}
    for key, value in asked.items():
        options = _offered(choices.get(key))
        fields[key] = {
            'value': value,
            'help': [],
            'choices': options,
            'kind': _kind_for(options, key, value),
            'when': None,
            'rarely': False,
        }
    fields.setdefault('driver', plain['driver'])
    reach = _connects(module, asked)
    return {'fields': fields, 'connects': reach, 'about': CONNECTS[reach]}


def _asked_of(module):
    """Every option a driver's constructor reads out of the stanza it is handed.

    Only the constructor's own keyword argument is followed, so that a `.get` on
    some other dictionary in the same method is not taken for an option.

    Args:
        module (types.ModuleType): The driver module.

    Returns:
        collections.OrderedDict: Option name to the default written the way a
        configuration file writes it, in the order the constructor reads them.
        Empty when there is nothing to read.
    """
    try:
        tree = ast.parse(inspect.getsource(module))
    except Exception as e:
        log.debug("Cannot read %s to see what it asks for: %s", module.__name__, e)
        return collections.OrderedDict()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        named = [_base_name(base) for base in node.bases]
        if not any(name.endswith('AbstractDevice') for name in named):
            continue
        found = _stanza_reads(node)
        if found:
            return found
    return collections.OrderedDict()


def _base_name(node):
    """What a class in a base list is called, without importing anything.

    Args:
        node (ast.AST): One entry of a ClassDef's bases.

    Returns:
        str: The name as written, so 'AbstractDevice' for both `AbstractDevice` and
        `weewx.drivers.AbstractDevice`. Empty for anything else.
    """
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ''


def _stanza_reads(klass):
    """The options one class's constructor reads, by name and default.

    Args:
        klass (ast.ClassDef): A driver class.

    Returns:
        collections.OrderedDict: Option name to default. Empty when the constructor
        takes no keyword arguments, which means it is not handed the stanza at all.
    """
    found = collections.OrderedDict()  # type: Dict[str, str]
    for node in klass.body:
        if not isinstance(node, ast.FunctionDef) or node.name != '__init__':
            continue
        if not node.args.kwarg:
            return found
        held = node.args.kwarg.arg
        for inner in ast.walk(node):
            name, value = _one_read(inner, held)
            if name and name not in found:
                found[name] = value
    return found


def _one_read(node, held):
    """One option read out of the stanza, if that is what this expression is.

    There are two ways a driver reads one. `stn_dict.get('x', default)` is an option
    it can do without, and `stn_dict['x']` is one it cannot. Both name an option.

    Args:
        node (ast.AST): Any node inside the constructor.
        held (str): The name of the constructor's keyword argument.

    Returns:
        tuple: (the option name, its default as a string), or (None, None). The
        default is empty for an option read without one, and the whole pair is
        dropped when the default is a section rather than a value.
    """
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == 'get'
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == held
        and node.args
    ):
        name = _literal(node.args[0])
        value = _literal(node.args[1]) if len(node.args) > 1 else ''
        if isinstance(name, str) and isinstance(value, str):
            return name, value
        return None, None
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
        if node.value.id != held:
            return None, None
        part = node.slice
        # Python 3.8 and older wrap a subscript in an Index; 3.9 dropped it.
        if isinstance(part, getattr(ast, 'Index', ())):
            part = getattr(part, 'value', part)
        name = _literal(part)
        if isinstance(name, str):
            return name, ''
    return None, None


def _literal(node):
    """One constant out of the source, written the way a configuration file does.

    Args:
        node (ast.AST): The expression to read.

    Returns:
        str: The value. None for anything that is not a constant, and for a list or
        a dictionary, which is a subsection rather than a value.
    """
    try:
        value = ast.literal_eval(node)
    except Exception:
        return None
    if isinstance(value, (dict, list, tuple, set)):
        return None
    if value is None:
        return ''
    return str(value)


def _is_a_rule(lines):
    """Whether a comment block is a rule ruling off the options that follow.

    Args:
        lines (list | None): The comment lines above an option, as configobj
            hands them over.

    Returns:
        bool: Whether one of them is a row of hashes rather than a sentence.
    """
    for line in lines or []:
        bare = line.strip().lstrip('#').strip()
        text = line.strip()
        if not bare and len(text) > 3 and set(text) == {'#'}:
            return True
    return False


def _conditions(module):
    """Which options only apply for certain values of another, from the driver.

    A Vantage takes a port or a host and never both, and it says so in its own
    configuration editor: it asks for the type, then asks for one or the other
    inside an `if`. That is code rather than prose, so it can be read rather than
    guessed at, and it is the driver's own answer rather than a copy of it.

    An option counts as conditional only when every place it is asked for is under
    the same option, and those places together do not cover all of that option's
    values. That is what separates a Vantage, which asks for a port or a host, from
    a WS1, which asks for a port either way and only changes what it suggests.

    Args:
        module (types.ModuleType): The driver module.

    Returns:
        dict: Option name to {'field': the option it depends on, 'values': the
        values of that option for which it applies}. Empty for the eleven drivers
        of the thirteen that have nothing conditional.
    """
    try:
        editor = module.confeditor_loader()
        tree = ast.parse(inspect.getsource(type(editor)))
    except Exception as e:
        log.debug("No editor source for %s: %s", module.__name__, e)
        return {}
    asked = {}  # type: Dict[str, str]
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and _is_prompt(node.value):
            for target in node.targets:
                name = _plain_name(target)
                if name:
                    asked[name] = _prompted_name(node.value)
    everywhere = {}  # type: Dict[str, list]
    # The branches are inside prompt_for_settings, so that is where the reading
    # starts. Starting at the class would put every prompt at the top level, which
    # is the same as saying nothing is conditional.
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == 'prompt_for_settings':
            _under(node.body, None, asked, everywhere)

    choices = CHOICES.get(module.__name__, {})
    found = {}
    for option, places in everywhere.items():
        if any(place is None for place in places):
            # Asked for outside any condition somewhere, so it always applies.
            continue
        fields = {field for field, _ in places}
        if len(fields) != 1:
            continue
        field = fields.pop()
        values = set()
        for _, some in places:
            values |= some
        every = {_value_of(one) for one in choices.get(field, [])}
        if every and values >= every:
            # Asked for under every value the option can take, which is the same as
            # not being conditional at all.
            continue
        found[option] = {'field': field, 'values': sorted(values)}
    return found


def _under(body, condition, asked, everywhere):
    """Note which condition each prompt in a block of code is under.

    Recursive, once per branch, so that an `elif` is read as the branch it is
    rather than a second time as a statement of its own.

    Args:
        body (list): The statements to read.
        condition (tuple | None): (option, set of its values), or None for code
            that runs whatever anything was answered.
        asked (dict): Local name to the option it was prompted for.
        everywhere (dict): Option name to the conditions it has been seen under,
            added to in place.
    """
    for statement in body:
        if isinstance(statement, ast.If):
            tested = _tested(statement.test, asked)
            if tested is None:
                # A condition this cannot read. Everything inside it might always
                # apply, so say that rather than invent a rule.
                _under(statement.body, None, asked, everywhere)
                _under(statement.orelse, None, asked, everywhere)
                continue
            field, values = tested
            _under(statement.body, (field, set(values)), asked, everywhere)
            _under(
                statement.orelse, _otherwise(field, values, asked), asked, everywhere
            )
            continue
        for node in ast.walk(statement):
            if _is_prompt(node):
                everywhere.setdefault(_prompted_name(node), []).append(condition)


def _otherwise(field, values, asked):
    """The condition an `else` branch runs under.

    Args:
        field (str): The option the `if` tested.
        values (list): The values it tested for.
        asked (dict): Local name to option, unused here and taken so that the two
            callers read alike.

    Returns:
        tuple | None: (option, the values it did not test for), or None when this
        cannot be worked out because nothing says what values the option takes.
    """
    every = set()
    for options in CHOICES.values():
        for name, choices in options.items():
            if name == field:
                every |= {_value_of(one) for one in choices}
    rest = every - set(values)
    return (field, rest) if rest else None


def _value_of(choice):
    """The value of an entry in CHOICES, which may or may not carry a label.

    Args:
        choice (str | tuple): The entry.

    Returns:
        str: Its value.
    """
    return choice[0] if isinstance(choice, tuple) else choice


def _is_prompt(value):
    """Whether an expression is a call to the editor's own _prompt.

    Args:
        value (ast.expr): The right-hand side of an assignment.

    Returns:
        bool: Whether it is `self._prompt('name', ...)`.
    """
    return (
        isinstance(value, ast.Call)
        and getattr(value.func, 'attr', None) == '_prompt'
        and value.args
        and isinstance(value.args[0], ast.Constant)
        and isinstance(value.args[0].value, str)
    )


def _prompted_name(value):
    """The option name a call to _prompt asks for.

    Args:
        value (ast.expr): A call that _is_prompt has already said yes to.

    Returns:
        str: The first argument, which is the option name.
    """
    first = value.args[0]  # type: ignore[attr-defined]  # _is_prompt checked it
    return first.value


def _plain_name(target):
    """The name an assignment writes to, for the two shapes the editors use.

    Args:
        target (ast.expr): An assignment target.

    Returns:
        str | None: `x` for `x = ...` and `k` for `settings['k'] = ...`, or None
        for anything else.
    """
    if isinstance(target, ast.Name):
        return target.id
    if (
        isinstance(target, ast.Subscript)
        and isinstance(target.slice, ast.Constant)
        and isinstance(target.slice.value, str)
    ):
        return target.slice.value
    return None


def _tested(test, asked):
    """What an `if` compares, when it compares something that was prompted for.

    Args:
        test (ast.expr): The condition.
        asked (dict): Local name to the option it was prompted for.

    Returns:
        tuple | None: (option, values it is being compared against), or None when
        the condition is anything this does not read.
    """
    if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.Or):
        field, values = None, []
        for part in test.values:
            one = _tested(part, asked)
            if one is None or (field is not None and one[0] != field):
                return None
            field = one[0]
            values.extend(one[1])
        return (field, values) if field else None
    if not isinstance(test, ast.Compare) or len(test.ops) != 1:
        return None
    if not isinstance(test.ops[0], ast.Eq):
        return None
    name = _plain_name(test.left)
    if name is None or name not in asked:
        return None
    right = test.comparators[0]
    if not isinstance(right, ast.Constant) or not isinstance(right.value, str):
        return None
    return asked[name], [right.value]


def _prompted_in(body):
    """Which options are asked for inside a branch.

    Args:
        body (list): The statements in it.

    Returns:
        set[str]: The option names.
    """
    found = set()
    for statement in body:
        for node in ast.walk(statement):
            if _is_prompt(node):
                found.add(_prompted_name(node))
    return found


def _offered(choices):
    """One shape for the values an option takes, whether or not they need labels.

    Args:
        choices (list | None): What CHOICES holds for this option: values on their
            own, or (value, label) pairs where the value does not speak for itself.

    Returns:
        list[dict]: One per value, each with 'value' and 'label'. Empty when the
        option takes anything.
    """
    made = []
    for choice in choices or []:
        if isinstance(choice, tuple):
            made.append({'value': choice[0], 'label': '%s — %s' % choice})
        else:
            made.append({'value': choice, 'label': choice})
    return made


def _help_for(section, key):
    """What the driver's author says one option is.

    Args:
        section (configobj.Section): The stanza's one section.
        key (str): The option.

    Returns:
        list[str]: The comment above it, a line each, in the order it was written.
        Empty when there is none. Kept as lines rather than joined, because these
        are laid out as lines: a Vantage says what the connection type is on one
        line and what each of the two means on the next two, and run together they
        read as one sentence that does not parse.
    """
    lines = section.comments.get(key) or []
    # Everything after the last blank line, so that a section preamble or a banner
    # between two groups of options stays with neither.
    start = 0
    for index, line in enumerate(lines):
        if not line.strip():
            start = index + 1
    kept = []
    for line in lines[start:]:
        text = line.strip().lstrip('#').strip()
        # A rule made of hashes is a divider, not a sentence.
        if text and set(text) != {'#'}:
            kept.append(text)
    return kept


def _kind_for(options, key, value):
    """What sort of field one option wants.

    Args:
        options (list): What _offered returned for it.
        key (str): The option name.
        value (str): Its default.

    Returns:
        str: 'fixed' when the driver takes exactly one value, so there is nothing
        to choose and a box would invite something that cannot work; 'choice' when
        it takes a few; 'port' for a serial device, where the machine's own devices
        are better than a description of them; 'text' otherwise.
    """
    if len(options) == 1:
        return 'fixed'
    if options:
        return 'choice'
    if key == 'port' and str(value).startswith('/dev/'):
        return 'port'
    return 'text'


def defaults_of(fields):
    """A form's values on their own, which is the shape a stanza is written in.

    Args:
        fields (dict): The 'fields' of what template_for returned.

    Returns:
        dict: Option name to value.
    """
    return {key: one['value'] for key, one in fields.items()}


class Facade:
    """The engine, as a hosted driver sees it.

    A driver that is also a service binds to the engine and expects its callbacks to
    be called. Given the real engine it would be called for every packet in the
    stream, including the ones other stations sent. So it is given this instead: it
    collects the bindings, and the host decides what reaches them.

    Everything that is not a binding is the real engine's. A driver reading
    `engine.db_binder` or `engine.stn_info` gets the real one.

    Args:
        engine (weewx.engine.StdEngine): The engine WeeWX built, or None when the
            driver was made outside one, as the tests do.
    """

    def __init__(self, engine):
        self.engine = engine
        self.callbacks = {}

    def bind(self, event_type, callback):
        """Remember a binding, rather than making it on the real engine.

        Args:
            event_type (int): One of the weewx.* event constants.
            callback (Callable[[weewx.Event], None]): Called as ``callback(event)``.
        """
        self.callbacks.setdefault(event_type, []).append(callback)

    def dispatchEvent(self, event):
        """Call this child's own callbacks for one event.

        Args:
            event (weewx.Event): The event to deliver.
        """
        for callback in self.callbacks.get(event.event_type, []):
            callback(event)

    def __getattr__(self, name):
        # Only reached for names this object does not have. Without the guard, a
        # lookup before 'engine' is set would ask for 'engine', and ask again.
        if name == 'engine':
            raise AttributeError(name)
        if self.engine is None:
            raise AttributeError(name)
        return getattr(self.engine, name)


def implements(klass, name):
    """Whether a driver class defines one part of the driver interface itself.

    Asked of the class rather than of an instance, so that finding out runs no
    driver code, and asked at all because WeeWX reads a missing part as a fact about
    the hardware. `genArchiveRecords` raising NotImplementedError means "this console
    has no logger", and StdArchive answers it by generating the record from the
    accumulator instead. Delegating a part the driver does not have would turn that
    clear answer into whatever AbstractDevice raises, one thread away from where it
    would be understood.

    The search stops at AbstractDevice, whose every method raises
    NotImplementedError. Inheriting one of those is not implementing it.

    Args:
        klass (type): The driver class.
        name (str): A method or property of weewx.drivers.AbstractDevice.

    Returns:
        bool: Whether the class, or something it inherits from below
        AbstractDevice, defines it.
    """
    for base in klass.__mro__:
        if base.__name__ == 'AbstractDevice':
            return False
        if name in vars(base):
            return True
    return False


class Child:
    """One hosted driver, and the one thread allowed to touch it.

    Every call to the driver happens on that thread, so a driver written for a
    single thread keeps getting one. The exception is `close`, which has to come
    from the caller: it is the only thing that can wake a driver blocked in a read,
    and queueing it behind that same blocked thread would defeat it.

    Args:
        station_type (str): The top-level stanza, e.g. 'Vantage'. Also what the
            packets carry as 'source'.
        config_dict (dict): The whole of weewx.conf, handed to the child's loader
            untouched. Several drivers read more of it than their own section.
        engine (weewx.engine.StdEngine): The engine, wrapped in a Facade before the
            child sees it. May be None outside an engine.
        out (queue.Queue): Where loop packets go. Shared with every other child.
    """

    def __init__(self, station_type, config_dict, engine, out):
        self.station_type = station_type
        # A synthetic identity, because a driver has no PASSKEY to send. Stable
        # across restarts, which is what owners.py needs to keep a column with the
        # station that filled it.
        self.ident = 'driver:%s' % station_type
        self.config_dict = config_dict
        self.facade = Facade(engine)
        self.out = out
        self.commands = queue.Queue()  # type: queue.Queue
        # Held while the driver is built, called or closed, so that a close from the
        # engine's thread cannot land in the middle of a rebuild on this one.
        self.lock = threading.Lock()
        self.driver = None
        self.packets = None
        self.looping = False
        # Set while this child is not pulling loop packets. What the engine's thread
        # waits on before asking the child for history, because both go down one
        # port and a read that is still in flight would collide with it.
        self.idle = threading.Event()
        self.idle.set()
        self.wait = FIRST_WAIT
        self.retry_in = None
        self.failures = 0
        self.thread = threading.Thread(
            target=self._work, name='UltimatePush-%s' % station_type, daemon=True
        )

    # ---- what the engine's thread calls -------------------------------------

    def open(self):
        """Build the driver, then start its thread.

        Separate from the constructor so that a driver which cannot be reached says
        so where the host can decide what that means: fatal for the archive station,
        survivable for any other.

        Raises:
            Exception: Whatever the child's loader raised.
        """
        self.driver = self._build()
        self.thread.start()

    def start_loop(self):
        """Begin pulling loop packets from the child."""
        self.commands.put(_Command(START, None, None, None, None))

    def stop_loop(self):
        """Stop pulling loop packets, without closing the driver.

        Called whenever the engine abandons the loop, which is once per archive
        period. A device that answers history over the same port it streams LOOP
        packets on cannot do both, so this has to have happened before the engine
        asks for archive records. Whether it actually has is a separate question,
        and `settle` is how it is asked.
        """
        self.commands.put(_Command(STOP, None, None, None, None))

    def settle(self, timeout=SETTLE):
        """Wait until this child has really stopped pulling loop packets.

        `stop_loop` puts a message on a queue the child reads between packets. By
        the time it arrives the child is usually inside a read, waiting for its next
        reading, and nothing can interrupt that read. So the stop takes effect when
        the reading arrives, and this is the wait for it.

        Args:
            timeout (float): Seconds to wait.

        Returns:
            bool: Whether it stopped. False means a read is still in flight, and
            anything asked of the same device now shares the port with it.
        """
        return self.idle.wait(timeout)

    def call(self, name, *args, **kwargs):
        """Call a method on the child, on the child's thread, and wait for it.

        Args:
            name (str): The attribute to fetch, and to call when it is callable.
            *args (Any): Passed on unchanged.
            **kwargs (Any): Passed on unchanged.

        Returns:
            object: What the child returned. A generator is drained into a list
            first, so that whatever it raises is raised on the child's thread and
            arrives here as that exception rather than as a broken iterator.

        Raises:
            weewx.WeeWxIOError: If the child is not running. Not NotImplementedError,
                which would tell WeeWX the hardware cannot do this and make it fall
                back to software records for good; a child that is down is a child
                that will be back.
            Exception: Whatever the child raised.
        """
        if self.driver is None:
            raise weewx.WeeWxIOError(
                "The %s driver is not running, so it cannot answer %s"
                % (self.station_type, name)
            )
        answer = queue.Queue(maxsize=1)  # type: queue.Queue
        self.commands.put(_Command(CALL, name, args, kwargs, answer))
        returned, value = answer.get()
        if returned:
            return value
        raise value

    def can(self, name):
        """Whether this child implements one part of the driver interface.

        Args:
            name (str): A method or property of weewx.drivers.AbstractDevice.

        Returns:
            bool: Whether the child defines it itself. False while the child is not
            running, because nothing can be asked of it then either.
        """
        return self.driver is not None and implements(type(self.driver), name)

    def close(self):
        """Close the driver, then stop the thread.

        The driver is closed from the calling thread on purpose. `closePort` is what
        WeeWX itself uses to wake a driver waiting on hardware, and a child waiting
        inside `genLoopPackets` does not read its command queue until it yields.
        Sending CLOSE through the queue would therefore wait out the full join for
        every child that is doing what a receiving driver normally does.
        """
        with self.lock:
            driver, self.driver = self.driver, None
        if driver is not None:
            try:
                driver.closePort()
            except Exception as e:
                log.error("Cannot close the %s driver: %s", self.station_type, e)
        self.commands.put(_Command(CLOSE, None, None, None, None))
        if self.thread.is_alive():
            self.thread.join(JOIN)
            if self.thread.is_alive():
                log.error(
                    "The thread for the %s driver did not stop. It still holds "
                    "the device open, and the next one will not get it.",
                    self.station_type,
                )

    # ---- the child's own thread ---------------------------------------------

    def _work(self):
        """Run the child, on this thread and no other.

        Runs as a thread. Takes a command when there is one, pulls a packet when
        there is nothing else to do, and never touches the driver from anywhere
        else.
        """
        while True:
            command = self._next_command()
            if command is not None:
                if command.kind == CLOSE:
                    return
                self._obey(command)
                continue
            if self.driver is None:
                self._build_again()
                continue
            if self.looping and self.packets is not None:
                self._pull_one(self.packets)

    def _next_command(self):
        """The next command, waiting for one when there is nothing else to do.

        Returns:
            _Command | None: The command, or None when the thread should get on
            with pulling packets or with rebuilding a failed child.
        """
        if self.looping and self.packets is not None:
            # There are packets to pull, so look for a command without waiting.
            try:
                return self.commands.get_nowait()
            except queue.Empty:
                return None
        if self.driver is None:
            # Waiting out the retry. A command during the wait cuts it short, which
            # is what makes closing a failed child immediate.
            try:
                return self.commands.get(timeout=self.retry_in or FIRST_WAIT)
            except queue.Empty:
                return None
        return self.commands.get()

    def _obey(self, command):
        """Carry out one command.

        Args:
            command (_Command): The command, which is not CLOSE. That one ends the
                thread and is handled by the caller.
        """
        if command.kind == START:
            self.looping = True
            self.idle.clear()
            self._open_stream()
        elif command.kind == STOP:
            self.looping = False
            self._close_stream()
            self.idle.set()
        elif command.kind == CALL:
            self._answer(command)

    def _answer(self, command):
        """Run one delegated call and put the outcome on its answer queue.

        Args:
            command (_Command): A CALL command, with an answer queue.
        """
        try:
            with self.lock:
                if self.driver is None:
                    raise weewx.WeeWxIOError(
                        "The %s driver is not running" % self.station_type
                    )
                value = getattr(self.driver, command.name)
                if callable(value):
                    value = value(*command.args, **command.kwargs)
            if hasattr(value, '__next__'):
                # Drained here rather than handed over, so that a failure part way
                # through a catch-up is raised on this thread and reaches the caller
                # as that failure. A long catch-up is a few thousand small dicts,
                # which is worth the certainty.
                value = list(value)
            command.answer.put((True, value))
        except Exception as e:
            command.answer.put((False, e))

    def _open_stream(self):
        """Ask the child for its loop packets, if it is running and has not been."""
        if self.driver is None or self.packets is not None:
            return
        try:
            self.packets = self.driver.genLoopPackets()
        except Exception as e:
            self._failed(e)

    def _close_stream(self):
        """Abandon the child's loop generator, so it stops talking to its hardware."""
        if self.packets is None:
            return
        try:
            self.packets.close()
        except Exception as e:
            log.error("Cannot stop the %s driver's loop: %s", self.station_type, e)
        self.packets = None

    def _pull_one(self, packets):
        """Take one packet from the child and hand it on.

        Args:
            packets (Iterator[dict]): The child's own loop generator.
        """
        try:
            packet = next(packets)
        except StopIteration:
            # A driver whose loop ended of its own accord. Nothing restarts it here;
            # ask for a new generator on the next START.
            self.packets = None
        except Exception as e:
            self.packets = None
            self._failed(e)
        else:
            # Which station this is, carried on the packet, because by the time the
            # engine's thread sees it there is nothing else left to say so.
            packet['source'] = self.station_type
            self.out.put(packet)

    def _failed(self, error):
        """Close a child that raised, and arrange for it to be built again.

        Args:
            error (Exception): What it raised.
        """
        self.failures += 1
        log.error(
            "The %s driver failed (%d so far): %s. Trying again in %.0f seconds.",
            self.station_type,
            self.failures,
            error,
            self.wait,
        )
        with self.lock:
            driver, self.driver = self.driver, None
        if driver is not None:
            try:
                driver.closePort()
            except Exception as e:
                log.error(
                    "Cannot close the %s driver after it failed: %s",
                    self.station_type,
                    e,
                )
        self.retry_in = self.wait

    def _build_again(self):
        """Build a failed child again, and resume it where it was."""
        try:
            driver = self._build()
        except Exception as e:
            self.wait = min(self.wait * 2, LONGEST_WAIT)
            self.retry_in = self.wait
            log.error(
                "The %s driver is still not there: %s. Trying again in %.0f "
                "seconds.",
                self.station_type,
                e,
                self.wait,
            )
            return
        with self.lock:
            self.driver = driver
        self.wait = FIRST_WAIT
        self.retry_in = None
        log.info("The %s driver is back.", self.station_type)
        if self.looping:
            self._open_stream()

    def _build(self):
        """Load and open the child driver, the way the engine would.

        The stanza is not reshaped and the loader is the child's own, so a driver
        that works under WeeWX works here, whether it ships with WeeWX or not.

        Returns:
            weewx.drivers.AbstractDevice: The driver, open.

        Raises:
            ValueError: If the stanza is missing or names no driver.
            Exception: Whatever the child's loader raised.
        """
        section = self.config_dict.get(self.station_type)
        if not section:
            raise ValueError(
                "There is no [%s] section in weewx.conf. A hosted driver is "
                "configured in its own section, exactly as it would be if it were "
                "the only driver." % self.station_type
            )
        module_name = section.get('driver')
        if not module_name:
            raise ValueError(
                "[%s] has no 'driver' option, so there is nothing to import."
                % self.station_type
            )
        module = importlib.import_module(module_name)
        # The whole config_dict, untouched: the simulator reads [Station] for its
        # start time and ws23xx wants the lot. The facade stands in for the engine
        # so that a driver which is also a service is bound to us, not to the engine.
        return module.loader(self.config_dict, self.facade)


class Host:
    """Every hosted driver, shaped like a listener.

    `server.Fan` takes turns on things that have `get`, `closed` and `close`. A
    listener is one such thing and so is this, which is why the merged stream needs
    nothing added to it: the engine's loop already iterates a Fan, and the packets
    from a serial console arrive on the same turn as an upload from a gateway.

    What comes out of `get` is a loop packet, not a Request. The driver tells the two
    apart and sends each the way it has to go.

    Args:
        children (list[Child]): The children, in the order they were configured.
            The first is the archive station.
        packets (queue.Queue): Where every child puts its loop packets.
    """

    # A Fan reports the port of its first listener, and hosted hardware has none.
    # Named here so that reporting it is a lookup rather than an exception.
    port = None

    def __init__(self, children, packets):
        self.children = list(children)
        self.queue = packets
        self.closed = threading.Event()
        self.by_type = {child.station_type: child for child in self.children}
        # Whether the engine is currently in its loop. A child adopted while it is
        # has to be started, or it would sit idle until the next archive period.
        self.looping = False
        # Held while the list of children changes, so that a driver added from the
        # web interface's thread cannot be half in when the engine's thread reads it.
        self.lock = threading.Lock()

    @property
    def archive(self):
        """The child whose logger answers for the archive, or None.

        Returns:
            Child | None: The first child configured, which is the archive station.
        """
        return self.children[0] if self.children else None

    def get(self, timeout=None):
        """The next loop packet from any child.

        Args:
            timeout (float | None): Seconds to wait, or None to wait until a packet
                arrives or the host is closed.

        Returns:
            dict | None: A loop packet, or None if none arrived in time or the host
            has been closed.
        """
        left = None if timeout is None else max(0.0, float(timeout))
        while not self.closed.is_set():
            wait = POLL if left is None else min(POLL, left)
            try:
                return self.queue.get(timeout=max(wait, 0.001))
            except queue.Empty:
                if left is not None:
                    left -= wait
                    if left <= 0:
                        return None
        return None

    def deliver(self, packet):
        """Give one packet to the child that produced it, before anyone else sees it.

        This is where a driver that is also a service gets its NEW_LOOP_PACKET, and
        it happens on the engine's thread, immediately before the packet is yielded.
        That is the same thread and the same moment as under WeeWX on its own, which
        is what keeps a service like the Vantage's, whose gust is reset from the
        engine's END_ARCHIVE_PERIOD, working the way it was written.

        Args:
            packet (dict): The loop packet, changed in place by whatever the child
                has bound to NEW_LOOP_PACKET.
        """
        child = self.by_type.get(packet.get('source'))
        if child is None:
            return
        child.facade.dispatchEvent(weewx.Event(weewx.NEW_LOOP_PACKET, packet=packet))

    def forward(self, event):
        """Give one engine event to every child.

        Args:
            event (weewx.Event): An event from the real engine, one of FORWARDED.
        """
        for child in self.children:
            child.facade.dispatchEvent(event)

    def start_loop(self):
        """Tell every child to start pulling loop packets."""
        self.looping = True
        for child in self.children:
            child.start_loop()

    def stop_loop(self):
        """Stop every child pulling, and wait for the one that will be asked for history.

        Only that one is waited for. A child the engine will never ask for archive
        records has nothing to be exclusive about: its next read can finish in its
        own time, and holding the engine up for it would cost an archive period's
        delay for nothing.
        """
        self.looping = False
        for child in self.children:
            child.stop_loop()
        child = self.archive
        if child is None:
            return
        if not any(
            child.can(name) for name in ('genArchiveRecords', 'genStartupRecords')
        ):
            return
        if not child.settle():
            log.warning(
                "The %s driver is still reading after %.0f seconds, so its history "
                "is about to be asked for over a port it has not finished with. If "
                "this keeps happening, the archive records are the ones to check.",
                child.station_type,
                SETTLE,
            )

    def adopt(self, child):
        """Take on a driver that was set up while WeeWX was running.

        Args:
            child (Child): The driver, already opened.
        """
        with self.lock:
            self.children = self.children + [child]
            self.by_type = dict(self.by_type, **{child.station_type: child})
        if self.looping:
            # Or it would sit idle until the next archive period came round.
            child.start_loop()
        log.info("Now hosting the %s driver as well.", child.station_type)

    def dismiss(self, station_type):
        """Close a driver and stop hosting it.

        Args:
            station_type (str): Which one.

        Returns:
            bool: Whether it was being hosted.
        """
        with self.lock:
            child = self.by_type.get(station_type)
            if child is None:
                return False
            self.children = [
                one for one in self.children if one.station_type != station_type
            ]
            self.by_type = {
                key: one for key, one in self.by_type.items() if key != station_type
            }
        child.close()
        log.info("Stopped hosting the %s driver.", station_type)
        return True

    def set_order(self, types):
        """Put the children in this order, which decides the archive station.

        Args:
            types (list[str]): Station types, most important first. Any child not
                named keeps its place after the ones that are.
        """
        with self.lock:
            wanted = [self.by_type[name] for name in types if name in self.by_type]
            rest = [one for one in self.children if one not in wanted]
            self.children = wanted + rest

    def close(self):
        """Close every child. Safe to call more than once."""
        self.closed.set()
        for child in self.children:
            try:
                child.close()
            except Exception as e:
                # One child that will not shut down must not keep the others open,
                # or their ports stay held after WeeWX has gone.
                log.error("Cannot stop the %s driver: %s", child.station_type, e)


def build(configured, config_dict, engine, always=False):
    """The hosted drivers this configuration asks for.

    The first station type listed is the archive station, and it is the only one
    allowed to stop the driver from starting: without it the archive would be
    generated from software while its logger quietly filled up, and the records
    already written would be wrong rather than missing. Any other child that cannot
    be reached is logged and left out, and the rest run.

    Args:
        configured (dict): The [[hardware]] subsection, or nothing.
        config_dict (dict): The whole of weewx.conf.
        engine (weewx.engine.StdEngine): The engine, or None outside one.
        always (bool): Whether to return an empty host when nothing is configured,
            so that the web interface has something to add a driver to. A host with
            no children costs one more turn of the listener rotation and nothing
            else.

    Returns:
        Host | None: The host, or None when no hardware is configured and none was
        asked for.

    Raises:
        Exception: Whatever the archive station's loader raised.
    """
    types = as_list(configured.get('station_types') if configured else None)
    if not types and not always:
        return None
    # One queue for every child, so that the packets are already in arrival order by
    # the time anybody looks at them.
    packets = queue.Queue()  # type: queue.Queue
    children = []  # type: List[Child]
    for station_type in types:
        child = Child(station_type, config_dict, engine, packets)
        try:
            child.open()
        except Exception as e:
            if not children:
                log.error(
                    "The archive station %s could not be opened: %s", station_type, e
                )
                raise
            log.error(
                "The %s driver could not be opened, so it is left out: %s",
                station_type,
                e,
            )
            continue
        children.append(child)
    if not children and not always:
        return None
    host = Host(children, packets)
    if not children:
        return host
    log.info(
        "Hosting %d driver(s): %s. The archive station is %s.",
        len(children),
        ', '.join(child.station_type for child in children),
        children[0].station_type,
    )
    return host


def as_list(option):
    """Return a configobj option as a list of strings.

    Args:
        option (str | list | None): What configobj gave, which is a string when the
            value had no trailing comma.

    Returns:
        list: The entries, stripped, with the empty ones left out.
    """
    if not option:
        return []
    if isinstance(option, str):
        return [x.strip() for x in option.split(',') if x.strip()]
    return [str(x).strip() for x in option]
