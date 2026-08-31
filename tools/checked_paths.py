#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""Say what the checks run over, so that the CI and the container agree.

Three tools check this repository and each takes its files on the command line:
black, tools/check_docstring_types.py and vermin. Written out at both call sites,
the two copies drift. They had: the container ran vermin over `bin` alone while
the CI also covered `tools`, so a line only Python 3.9 accepts could sit in a tool
for as long as nobody pushed.

So each list is stated here once, and both call sites ask for it by name:

    vermin --target=3.7 --violations $(python tools/checked_paths.py vermin)

Which directories are this project's own Python is not decided here either. That
is `[tool.mypy] files` in pyproject.toml, which mypy reads for itself, so this
reads the same setting rather than keeping a second copy of it.

One path per line, so that a path with a space in it would still survive being
read into a shell array. There is none today.
"""

import os
import sys
import tomllib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The tools only a developer runs. Neither is in a release zip and nothing that
# ships imports either, so both are free to use syntax the driver may not:
# ast.unparse arrived in 3.9 and tomllib in 3.11, while everything WeeWX loads has
# to clear 3.7. They are checked by everything else, and skipped by vermin alone.
DEVELOPMENT = ('check_docstring_types.py', 'checked_paths.py')


def project_python():
    """The directories and files this project calls its own Python.

    Returns:
        list[str]: Paths relative to the repository root, from `[tool.mypy] files`.
    """
    with open(os.path.join(ROOT, 'pyproject.toml'), 'rb') as handle:
        return list(tomllib.load(handle)['tool']['mypy']['files'])


def python_files(paths):
    """Every .py file at or under the given paths.

    For the tools that take files rather than directories.

    Args:
        paths (list[str]): Files and directories, relative to the repository root.

    Returns:
        list[str]: The .py files among them, sorted, relative to the root.
    """
    found = set()
    for path in paths:
        whole = os.path.join(ROOT, path)
        if os.path.isfile(whole):
            found.add(path)
            continue
        for where, _, names in os.walk(whole):
            for name in names:
                if name.endswith('.py'):
                    found.add(
                        os.path.relpath(os.path.join(where, name), ROOT).replace(
                            os.sep, '/'
                        )
                    )
    return sorted(found)


def for_black():
    """What is formatted: everything written here, tests included.

    Returns:
        list[str]: Directories and files for black. It takes directories and reads
        its own exclusions from pyproject.toml, so nothing is expanded.
    """
    return project_python() + ['tests']


def for_docstrings():
    """What the docstring types are read in.

    The tests are left out. Their types are true, but several name a class the
    test module never imports because it builds one in a fixture, and the checker
    is right to say so. Adding an import for a docstring would be the wrong fix.

    Returns:
        list[str]: The .py files to check.
    """
    return python_files(project_python())


def for_vermin():
    """What has to keep parsing on Python 3.7, which is WeeWX's floor.

    Wider than the project's own Python on one side and narrower on the other. All
    of `bin` rather than the driver package alone, because bin/user/listener.py is
    a copy that ships and therefore has to load; and without the two development
    tools, which do not.

    Returns:
        list[str]: The paths to scan.
    """
    tools = [
        path
        for path in python_files(['tools'])
        if os.path.basename(path) not in DEVELOPMENT
    ]
    return ['bin', 'install.py'] + tools


LISTS = {'black': for_black, 'docstrings': for_docstrings, 'vermin': for_vermin}


def main(argv=None):
    """Print one of the lists, one path per line.

    Args:
        argv (list[str] | None): The arguments after the program name. sys.argv
            when not given.

    Returns:
        int: The exit status, which is 2 if the list was not named.
    """
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1 or argv[0] not in LISTS:
        sys.stderr.write('usage: checked_paths.py {%s}\n' % '|'.join(sorted(LISTS)))
        return 2
    for path in LISTS[argv[0]]():
        print(path)
    return 0


if __name__ == '__main__':
    sys.exit(main())
