#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""Write a page for each WeeWX driver this machine can host.

One page per driver: the smallest configuration that works, every option it takes
with what its author says about it, and how to find the things a person has to look
up, such as which serial device the console is on.

Nothing here describes a driver from memory. The options, their defaults and their
explanations come out of the driver as installed, through the same reader the web
interface builds its form from, so a page cannot describe a version nobody has.

    python tools/build_drivers.py

Needs WeeWX installed, and writes only the drivers it finds. Run it again after
installing a driver from elsewhere and that driver gets a page too.
"""

import argparse
import io
import os.path
import sys
import textwrap
from typing import TYPE_CHECKING

# For the docstring types only. A driver's module is handed straight from
# importlib to the reader in hardware.py, and nothing here needs the name.
if TYPE_CHECKING:
    import types

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, 'bin', 'user'))

# What to put near the top of every page. Somebody reading a configuration file by
# hand still wants to know that the same thing can be done by clicking, especially
# the part of it that is tedious on paper.
INTERFACE = """> **There is a web interface for all of this.** It is on by default, and the driver
> prints its address when WeeWX starts:
>
> ```
> INFO user.ultimatepush.driver: The web interface is at
> http://1.2.3.4:8080/?token=abcdefg12345
> ```
>
> Everything on this page can be done there instead, and one thing is much easier:
> deciding which reading goes into which database column. See
> [Web interface](Web-interface.md).
"""

# How a driver is reached, and what somebody has to find out before they can fill the
# form in. hardware.py works out which of the three a driver is; this is what to say
# about each.
FINDING = {
    'usb': """## Finding it

There is nothing to look up. The driver searches the USB bus for the device itself.

If it does not find it, the usual cause is permissions: WeeWX runs as the `weewx`
user, and a raw USB device belongs to root until a udev rule says otherwise. WeeWX
installs those rules for the hardware it supports. Check with:

```bash
lsusb
```

and look for the console in the list. If it is there and the driver still cannot open
it, the log says so with the vendor and product number, which is what a udev rule
needs.
""",
    'cable': """## Finding the port

The console is on a serial port, which on most machines is a USB-to-serial adapter.
The name to put in `port` is whichever device it appears as.

List them with:

```bash
ls -l /dev/serial/by-id/
```

Use the name under `by-id` rather than `/dev/ttyUSB0`. It is made from the adapter's
own manufacturer and serial number, so it stays the same after a reboot and after
something else is plugged in, which `/dev/ttyUSB0` does not.

```ini
port = /dev/serial/by-id/usb-FTDI_FT232R_USB_UART_A50285BI-if00-port0
```

If nothing is listed, the adapter is not being recognised. `dmesg | tail` after
plugging it in says what the kernel made of it.

The web interface offers these devices as a list, which saves the typing.
""",
    'either': """## Finding the port, or the address

Over a cable, the name to put in `port` is whichever device the adapter appears as:

```bash
ls -l /dev/serial/by-id/
```

Use the name under `by-id` rather than `/dev/ttyUSB0`. It is made from the adapter's
own manufacturer and serial number, so it survives a reboot and anything else being
plugged in.

Over the network, `host` is the console's address or hostname. Give it a fixed
address in your router, or it will move and stop being found.

The web interface offers the serial devices this machine has as a list.
""",
    'broadcast': """## Finding it

There is nothing to look up, and that is the whole of the difficulty. The hub sends
its readings out to the entire local network, and this machine picks them up as they
pass. Neither end is configured to know about the other, so there is also nothing to
get wrong, and nothing to check when it does not work.

What has to be true is that both are on the same network. A hub on the guest network,
or on the other side of a router, is never heard, and the driver cannot say so: from
where it sits, a hub that is silent and a hub that cannot reach it look the same.

Check that anything is arriving at all:

```bash
sudo tcpdump -n -i any udp port %(port)s
```

A line every minute or so means the hub is being heard, and anything that goes wrong
after that is a setting. Nothing at all means the readings are not reaching this
machine, and no setting on this page changes that.
""",
    'network': """## Finding the address

Nothing is plugged in here. The driver opens a connection to a machine on the
network, and the address below is that machine.

Give it a fixed address, in the router, under whatever the router calls a reserved
lease. An address handed out on the day will be a different address next month, and
the driver will simply stop recording with nothing in the log to say why.

Check that it answers before putting it in the file:

```bash
ping -c 3 1.2.3.4
```

A name works in place of an address, and is worth using where the network hands out
names that stay put.
""",
    'command': """## Finding the program

This driver does not talk to the radio itself. It runs another program that does,
reads what that program prints, and turns it into readings. So the setting below is
a path, and it has to be the path on this machine.

Find it:

```bash
which rtldavis
```

If that prints nothing, the program is not installed, or not on the path, and the
full path to wherever it was built has to go in instead. Building it is on its
author's own page, not this one.

Two things go wrong here and neither says much in the log. The program has to be
executable by the user WeeWX runs as, which is `weewx` and not the user who built
it. And the receiver it uses is a USB device that belongs to root until a udev rule
says otherwise, in the same way a console does.
""",
    'nothing': '',
}


def load(module_name):
    """Import a driver module, or say why it cannot be used.

    Args:
        module_name (str): The import path, e.g. 'weewx.drivers.vantage'.

    Returns:
        tuple: (module, problem), one of which is None.
    """
    import importlib

    try:
        return importlib.import_module(module_name), None
    except Exception as e:
        return None, str(e)


def minimal(name, fields):
    """The smallest configuration that runs this driver here.

    Only the options with no sensible default: the module to import, and anything
    that names a device rather than tunes one. An option that applies only for
    certain values of another is left out unless the default takes those values, so
    that a Vantage shows a port or a host and never both.

    Args:
        name (str): The section name, e.g. 'Vantage'.
        fields (dict): What hardware.template_for returned under 'fields'.

    Returns:
        str: An ini block.
    """
    wanted = ['driver']
    for key in ('type', 'mode', 'port', 'host', 'transceiver_frequency'):
        if key not in fields or key in wanted:
            continue
        when = fields[key]['when']
        if when and fields[when['field']]['value'] not in when['values']:
            continue
        wanted.append(key)
    lines = [
        '[Station]',
        '    station_type = UltimatePush',
        '',
        '[UltimatePush]',
        '    driver = user.ultimatepush.driver',
        '',
        '    [[hardware]]',
        '        station_types = %s' % name,
        '',
        '        [[[%s]]]' % name,
        '            role = main',
        '',
        '[%s]' % name,
    ]
    for key in wanted:
        lines.append('    %s = %s' % (key, fields[key]['value']))
    return '\n'.join(lines)


def options(fields):
    """Every option, as the driver's own author describes it.

    Args:
        fields (dict): What hardware.template_for returned under 'fields'.

    Returns:
        list[str]: Markdown lines.
    """
    lines = []
    for key in fields:
        one = fields[key]
        lines.append('#### %s' % key)
        lines.append('')
        for said in one['help']:
            lines.append(wrap(said))
        if len(one['choices']) == 1:
            lines.append('')
            lines.append(
                'The only value this driver takes. Anything else raises at startup.'
            )
        elif one['choices']:
            lines.append('')
            lines.append(
                'One of %s.'
                % ', '.join('`%s`' % choice['value'] for choice in one['choices'])
            )
        if one['when']:
            lines.append('')
            lines.append(
                'Applies only when `%s` is %s.'
                % (
                    one['when']['field'],
                    ' or '.join('`%s`' % v for v in one['when']['values']),
                )
            )
        lines.append('')
        lines.append('Default is `%s`.' % one['value'])
        if one['rarely']:
            lines.append('')
            lines.append(
                "The driver's author rules this one off as rarely needing attention."
            )
        lines.append('')
    return lines


def wrap(paragraph):
    """One paragraph, wrapped the way the pages in docs/ are.

    Args:
        paragraph (str): The text, as one line.

    Returns:
        str: The same text over several lines.
    """
    return '\n'.join(textwrap.wrap(' '.join(paragraph.split()), width=88))


def page(module_name, module, made):
    """One driver's page.

    Args:
        module_name (str): The import path.
        module (types.ModuleType): The driver module.
        made (dict): What hardware.template_for returned for it.

    Returns:
        str: The whole page.
    """
    name = str(module.DRIVER_NAME)
    fields = made['fields']
    doc = (module.__doc__ or '').strip().split('\n')
    first = ' '.join(line.strip() for line in doc[:3] if line.strip())

    lines = [
        '# %s' % name,
        '',
        'Running the %s driver under this one, configured by hand.' % name,
        '',
        wrap(
            'Generated by `tools/build_drivers.py` from the driver as installed on'
            ' the machine that ran it. Do not edit by hand.'
        ),
        '',
        INTERFACE,
        '## What it is',
        '',
        wrap(first or 'The driver says nothing about itself.'),
        '',
        '## The smallest configuration that works',
        '',
        '```ini',
        minimal(name, fields),
        '```',
        '',
        wrap(
            'The `[%s]` section belongs to that driver and is read by it, exactly as'
            ' it would be if it were the only driver WeeWX ran, so `weectl device`'
            ' keeps working on it. What goes under `[[hardware]]` belongs to this'
            ' one: see [Hosted hardware](Hosted-hardware.md).' % name
        ),
        '',
    ]
    finding = FINDING.get(made['connects'], '')
    if finding:
        # The text for a listening driver names the port to watch, which is the
        # driver's own rather than a number this could know.
        port = fields.get('udp_port', {}).get('value', '')
        lines.append(finding.replace('%(port)s', str(port)))
    written = any(one['help'] for one in fields.values())
    lines += [
        '## Every option',
        '',
        wrap(
            'Straight out of `%s`, with what its author wrote above each one.'
            % module_name
            if written
            else 'Straight out of `%s`. This driver carries no template for a'
            ' configuration file, so the list is what its code reads and the'
            ' defaults are what it falls back on. What each one means is not'
            ' written down beside it, and its author\'s own page is the place'
            ' to look.' % module_name
        ),
        '',
    ]
    lines += options(fields)
    lines += [
        '## More than one station',
        '',
        wrap(
            'This driver is one station among however many others. Which of them'
            ' fills `outTemp`, and where the rest of their readings go, is in'
            ' [Several stations](Several-stations.md).'
        ),
        '',
    ]
    return '\n'.join(lines)


def main(argv=None):
    """Run it from the command line.

    Args:
        argv (list | None): Arguments, without the program name.

    Returns:
        int: An exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument(
        '--docs', default=os.path.join(HERE, 'docs'), help='where to write the pages'
    )
    args = parser.parse_args(argv)

    try:
        from ultimatepush import hardware
    except ImportError as e:
        print('Needs the driver on the path: %s' % e, file=sys.stderr)
        return 1

    written = []
    for found in hardware.available():
        if found['problem']:
            print('%s: %s' % (found['module'], found['problem']), file=sys.stderr)
            continue
        module, problem = load(found['module'])
        if module is None:
            print('%s: %s' % (found['module'], problem), file=sys.stderr)
            continue
        made = hardware.template_for(module)
        text = page(found['module'], module, made)
        path = os.path.join(args.docs, 'Driver-%s.md' % found['name'])
        with io.open(path, 'w', encoding='utf-8', newline='\n') as handle:
            handle.write(text)
        written.append(found['name'])
    print('%d driver pages: %s' % (len(written), ', '.join(written)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
