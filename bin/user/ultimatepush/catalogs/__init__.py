#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""What each protocol calls things, and where those things belong in WeeWX.

One module per protocol, and nothing in any of them but data. No imports, no logic,
no WeeWX: a catalog can be read by a person, diffed by a reviewer, and loaded by a
tool that has none of the rest of this driver.

Most of them are generated, because the hardware keeps gaining sensors and a
generated catalog makes the next addition a diff somebody can check rather than a
merge nobody can:

    ecowitt       tools/import_catalog.py, from Werner Krenn's ecowittcustom
    ambient       tools/import_ambient.py, from Home Assistant's ambient_station

The rest are written out, because their protocol is finished and there is nothing left
to generate from:

    wunderground  from the specification, which was published once and then withdrawn
"""

from . import ambient, ecowitt, wunderground

__all__ = ['ambient', 'ecowitt', 'wunderground']
