#!/usr/bin/env python3
#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""Check the types declared in Google-style docstrings.

WeeWX carries its types in docstrings rather than in annotations, because that is
what PyCharm reads. No command line type checker reads them: mypy and ty both walk
straight past a docstring type and see an untyped function.

This closes that gap. It reads the ``Args:`` and ``Returns:`` blocks, checks what
it finds there against the signature, and can hand the result to mypy as real
annotations.

Two modes:

    check_docstring_types.py src/weewx/jsongenerator.py
        Checks the docstrings on their own: parameter names and order against the
        signature, whether each type expression parses, whether the names in it
        resolve, and whether a parameter defaulting to None admits None.

    check_docstring_types.py --mypy src/weewx/jsongenerator.py
        Writes a copy with the docstring types as annotations, runs mypy over it,
        and reports what mypy makes of them. This is the part that finds a type
        which is simply wrong, rather than merely malformed.
"""

import argparse
import ast
import builtins
import importlib.util
import io
import os
import re
import subprocess
import sys
import tempfile
import typing

# 'name (type): text', the Google form. The type may hold brackets and pipes, so
# it is taken up to the last closing parenthesis before the colon.
ARG = re.compile(
    r'^(?P<indent>\s+)(?P<star>\*{0,2})(?P<name>\w+)\s*'
    r'\((?P<type>.+)\)\s*:\s*(?P<text>.*)$'
)
SECTION = re.compile(
    r'^\s*(Args|Returns|Yields|Raises|Attributes|Examples?|Note)s?:\s*$'
)

# mypy talking about the code rather than about the docstring types. A codebase
# without annotations produces these by the hundred, and not one of them means a
# docstring is wrong.
NOISE = re.compile(
    r'\[(var-annotated|no-any-return|import-untyped|import-not-found)\]'
    r'|Need type annotation'
    r'|has type "dict\[Never, Never\]"'
)

# Names a type expression may use without importing anything. PyCharm resolves
# these on its own, and so does this. builtins carries the exceptions and the
# lesser types that a hand-kept list forgets: BaseException was missing, and
# every docstring naming it was reported as unresolved.
BUILTIN = set(dir(builtins)) | {
    'Any',
    'AnyStr',
    'Callable',
    'ClassVar',
    'Dict',
    'FrozenSet',
    'Generator',
    'Iterable',
    'Iterator',
    'List',
    'Literal',
    'Mapping',
    'MutableMapping',
    'MutableSequence',
    'NamedTuple',
    'Optional',
    'Sequence',
    'Set',
    'Tuple',
    'Type',
    'TypeVar',
    'Union',
    'None',
    'NoneType',
    'Ellipsis',
}


def project_root(paths):
    """The directory the project's own modules live under.

    PyCharm resolves a docstring name against the whole project, not only against
    the module's own imports. Doing the same means finding the project first. A
    marker directory above one of the checked files settles it.

    Args:
        paths (list[str]): The files being checked.

    Returns:
        str|None: The root, or None if nothing marks one.
    """
    markers = ('.git', 'pyproject.toml', 'setup.py', 'setup.cfg')
    for path in paths:
        here = os.path.dirname(os.path.abspath(path))
        while True:
            if any(os.path.exists(os.path.join(here, m)) for m in markers):
                return here
            parent = os.path.dirname(here)
            if parent == here:
                break
            here = parent
    return None


def build_index(root):
    """Every name the project defines or imports anywhere, and where it came from.

    This is the stand-in for PyCharm's index. A docstring in `manager.py` naming
    `Path` resolves for anyone with PyCharm open, because `pathlib` is indexed; it
    resolves for nobody reading the file on its own. Both are worth knowing and
    they are not the same finding, so the origin is kept.

    First definition wins. A name defined twice is reported against one of the
    two, which is enough to say "this exists, just not here".

    Args:
        root (str): The project directory to walk.

    Returns:
        tuple[dict[str, str], list[str]]: Name to its origin, either a module name
            or a path; and the packages the project imports anywhere, for a bare
            name that is bound nowhere.
    """
    # The first definition of a name wins, written as a membership test rather than
    # with setdefault. setdefault on a dict that starts out empty says nothing about
    # what goes into it, and mypy then asks for an annotation this project does not
    # write: its types are in the docstrings.
    index = {}
    modules = set()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames if not d.startswith('.') and d != '__pycache__'
        ]
        for filename in filenames:
            if not filename.endswith('.py'):
                continue
            full = os.path.join(dirpath, filename)
            try:
                tree = ast.parse(read_source(full))
            except (SyntaxError, OSError, ValueError):
                continue
            where = os.path.relpath(full, root).replace(os.sep, '/')
            for node in tree.body:
                if isinstance(
                    node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
                ):
                    if node.name not in index:
                        index[node.name] = where
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    modules.add(node.module)
                    for alias in node.names:
                        bound = alias.asname or alias.name
                        if bound not in index:
                            index[bound] = node.module
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        modules.add(alias.name)
                        bound = alias.asname or alias.name
                        if bound not in index:
                            index[bound] = alias.name
    return index, sorted(modules)


def carries(module_name, attr):
    """Whether an importable module has an attribute.

    The module is imported rather than merely located, because locating it only
    answers half the question. `typing.Iterabel` needs the other half.

    Three answers, not two. "The module is not here" and "the module is here and
    the attribute is not" lead to opposite conclusions: the first says look
    elsewhere, the second says this is a typo. A checker run outside the project's
    own environment sees the first constantly - `weeutil.weeutil` is not on its
    path - and must not read that as an error.

    Args:
        module_name (str): A module or package, e.g. 'argparse'.
        attr (str): The attribute to look for.

    Returns:
        bool|None: True if the module has it, False if the module is importable
            and does not, None if the module cannot be reached from here.
    """
    try:
        if importlib.util.find_spec(module_name) is None:
            return None
        return hasattr(importlib.import_module(module_name), attr)
    except Exception:
        # A package that raises on import tells us nothing either way, and a
        # checker is not the place to let that stop the run.
        return None


def in_library(name, modules=()):
    """Where an installed package carries a name, if one does.

    Two cases, and PyCharm resolves both. `argparse.Namespace` says which module
    to look in, so it is looked up directly. A bare `ConfigObj` says nothing, so
    the packages the project imports somewhere are asked in turn: every weewx
    module writes `import configobj`, never `from configobj import ConfigObj`, and
    the name is therefore bound nowhere in the project while being perfectly real.

    Args:
        name (str): A dotted or bare name out of a type expression.
        modules (list[str]): The packages the project imports anywhere.

    Returns:
        str|None: The module that has it, or None.
    """
    if '.' in name:
        module_name, _, attr = name.rpartition('.')
        return module_name if carries(module_name, attr) else None
    for module_name in modules:
        if carries(module_name, name):
            return module_name
    return None


class Project(object):
    """The project's names, indexed the first time one is asked for.

    Indexing means parsing every file under the root, which is 2.6 of the 2.9
    seconds a run over weewx takes. Most runs never need it: a file whose
    docstring types all resolve in its own module asks nothing. So the index is
    built when the first name falls through, and not before.

    Args:
        root (str|None): The project directory, or None to index nothing.
    """

    def __init__(self, root):
        self.root = root
        self.index = None
        self.modules = ()

    def find(self, name, head):
        """Where the project or its packages carry a name.

        Args:
            name (str): The name as the docstring writes it.
            head (str): Its first segment, for a dotted name.

        Returns:
            str|None: The module or path that has it, or None.
        """
        if self.index is None:
            if self.root:
                self.index, self.modules = build_index(self.root)
            else:
                self.index = {}
        return (
            self.index.get(name)
            or self.index.get(head)
            or in_library(name, self.modules)
        )


def resolve(name, known, project):
    """Where a docstring type name resolves, in the order PyCharm would try.

    The module's own scope first, then the project, then the packages the project
    imports. A dotted name is held to its attribute as well as to its module: a
    module the checker can import gives a definite answer about what is in it, and
    `argparse.Namespac` is then a typo rather than a name to go looking for. A
    module it cannot import decides nothing, and the project is asked instead.

    Args:
        name (str): A dotted or bare name out of a type expression.
        known (set[str]): What the module itself defines or imports.
        project (Project): The project to fall back on.

    Returns:
        tuple[bool, str|None]: Whether this module resolves it on its own, and
            where else it was found. (False, None) means nowhere at all.
    """
    head = name.split('.')[0]
    if in_typing(name):
        return True, None
    if '.' in name:
        module_name, _, attr = name.rpartition('.')
        has = carries(module_name, attr)
        if has is True:
            return head in known, module_name
        if has is False:
            # The module is right here and the attribute is not in it. Nothing
            # the project holds can make that name mean anything.
            return False, None
    if name in known or head in known:
        return True, None
    return False, project.find(name, head)


def read_source(path):
    """The text of a Python file, whatever it is encoded in.

    Not every file in a long-lived project is UTF-8. `weeutil/Sun.py` carries a
    Latin-1 name in a comment and brought the whole run down with it. A byte that
    does not decode is replaced rather than raised: it can only be in a comment or
    a string, and neither affects a signature or a docstring type.

    Args:
        path (str): The file to read.

    Returns:
        str: The source.
    """
    try:
        return io.open(path, encoding='utf-8').read()
    except UnicodeDecodeError:
        return io.open(path, encoding='utf-8', errors='replace').read()


def compare_names(documented, declared):
    """How an Args: block and a signature differ over the parameter names.

    A missing `**kwargs` and a misspelled parameter are both worth knowing about,
    but they are not the same thing: one leaves the caller uninformed, the other
    tells the caller something untrue. They are reported apart so that a run over a
    large file does not bury the second sort under the first.

    The stars themselves are not held against anyone. WeeWX writes `**option_dict`
    as `option_dict (dict)`, and PyCharm reads it either way.

    Args:
        documented (list[str]): The names the Args: block gives, in its order.
        declared (list[str]): The names the signature gives, in its order, with
            `*args` and `**kwargs` still starred.

    Returns:
        tuple[bool, list[str]]: Whether the named parameters agree, and the
            variadic parameters the block leaves out.
    """
    plain = [name.lstrip('*') for name in documented]
    missing = [
        name
        for name in declared
        if name.startswith('*') and name.lstrip('*') not in plain
    ]
    kept = [name for name in declared if name not in missing]
    return plain == [name.lstrip('*') for name in kept], missing


class Finding(object):
    """One problem with one docstring.

    Args:
        path (str): The file it was found in.
        line (int): The line the function is defined on.
        func (str): The function's name.
        kind (str): A short slug for the sort of problem.
        text (str): What is wrong, in a sentence.
    """

    def __init__(self, path, line, func, kind, text):
        self.path = path
        self.line = line
        self.func = func
        self.kind = kind
        self.text = text

    def __str__(self):
        return '%s:%d: %s(): %s [%s]' % (
            os.path.basename(self.path),
            self.line,
            self.func,
            self.text,
            self.kind,
        )


def parse_args_block(doc):
    """The parameters an ``Args:`` block declares, in the order it declares them.

    A parameter's description may run over several lines. Only the first line of
    each carries a type, so a line that does not match ARG belongs to whatever
    came before it.

    Args:
        doc (str): The docstring, already dedented by ast.get_docstring().

    Returns:
        list[tuple[str, str]]: One (name, type) pair per parameter, in order.
    """
    out = []
    inside = False
    for line in doc.split('\n'):
        section = SECTION.match(line)
        if section:
            inside = section.group(1) == 'Args'
            continue
        if not inside:
            continue
        if line.strip() and not line.startswith((' ', '\t')):
            break
        m = ARG.match(line)
        if m:
            out.append((m.group('star') + m.group('name'), m.group('type').strip()))
    return out


def parse_returns(doc):
    """The type an ``Args:``-style ``Returns:`` block declares.

    Args:
        doc (str): The docstring.

    Returns:
        str|None: The type, or None where the block is absent or names no type.
            'Returns:' followed by prose alone is common and is not an error.
    """
    m = re.search(r'^\s*Returns:\s*\n(?P<body>(?:\s+.*\n?)*)', doc, re.M)
    if not m:
        return None
    first = m.group('body').lstrip()
    # 'type: description', where the type stops at the first colon that is not
    # inside brackets.
    depth = 0
    for i, ch in enumerate(first):
        if ch in '[(':
            depth += 1
        elif ch in '])':
            depth -= 1
        elif ch == ':' and depth == 0:
            candidate = first[:i].strip()
            return candidate if candidate and '\n' not in candidate else None
        elif ch == '\n':
            return None
    return None


def normalize(expr):
    """A docstring type as Python source.

    Docstrings are written for a reader as well as for a checker, so they carry
    forms Python does not accept. 'int|None' wants spaces to be legible but is
    valid either way; 'callable' and 'iterable' are English rather than types.

    Args:
        expr (str): The type as the docstring writes it.

    Returns:
        str: Something ast.parse() will accept as an expression.
    """
    expr = expr.strip()
    expr = re.sub(r'\bcallable\b', 'Callable', expr)
    expr = re.sub(r'\biterable\b', 'Iterable', expr)
    expr = re.sub(r'\bNoneType\b', 'None', expr)
    return expr


def in_typing(name):
    """Whether a dotted name is something the typing module carries.

    The bare names from typing need no import, and neither does the qualified form:
    a module that never imports typing may still write `typing.TextIO` and have
    PyCharm resolve it. A name typing does not actually carry is still a miss, so
    `typing.Iterabel` is caught rather than waved through.

    Args:
        name (str): A dotted name out of a type expression.

    Returns:
        bool: True if typing has it.
    """
    parts = name.split('.')
    return len(parts) == 2 and parts[0] == 'typing' and hasattr(typing, parts[1])


def names_in(node):
    """Every dotted name a type expression uses.

    Args:
        node (ast.AST): The parsed type expression.

    Returns:
        set[str]: The names, dotted ones joined up: {'int', 'weewx.units.ValueTuple'}.
    """
    found = set()

    def dotted(n):
        if isinstance(n, ast.Name):
            return n.id
        if isinstance(n, ast.Attribute):
            base = dotted(n.value)
            return '%s.%s' % (base, n.attr) if base else None
        return None

    def visit(n):
        # A dotted name is one name, not three. Take it whole and do not descend
        # into it, or 'weewx.units.ValueTuple' is reported once per segment.
        name = dotted(n)
        if name:
            found.add(name)
            return
        for child in ast.iter_child_nodes(n):
            visit(child)

    visit(node)
    return found


def module_names(tree):
    """The names a type expression may use in this module without qualifying them.

    Its imports, and what it defines itself. The second half matters more than it
    looks: `units.py` documents a return of `Formatter`, and `Formatter` is a class
    three hundred lines further down the same file. Counting only imports reports
    every such type as unresolved.

    Args:
        tree (ast.Module): The parsed module.

    Returns:
        set[str]: The names, including the dotted forms of 'import a.b.c'.
    """
    out = set()
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            out.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    out.add(target.id)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.add(alias.asname or alias.name)
                if not alias.asname:
                    # 'import a.b.c' also makes 'a' and 'a.b' usable.
                    parts = alias.name.split('.')
                    for i in range(1, len(parts) + 1):
                        out.add('.'.join(parts[:i]))
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                out.add(alias.asname or alias.name)
    return out


def signature(func):
    """The parameters a function declares, in order, with their defaults.

    Args:
        func (ast.FunctionDef): The function.

    Returns:
        tuple[list[str], dict[str, ast.AST]]: The names, and the default for each
            parameter that has one.
    """
    a = func.args
    names = [
        p.arg
        for p in getattr(a, 'posonlyargs', []) + a.args
        if p.arg not in ('self', 'cls')
    ]
    defaults = {}
    positional = getattr(a, 'posonlyargs', []) + a.args
    for param, default in zip(
        positional[len(positional) - len(a.defaults) :], a.defaults
    ):
        defaults[param.arg] = default
    if a.vararg:
        names.append('*' + a.vararg.arg)
    for p in a.kwonlyargs:
        names.append(p.arg)
    for param, default in zip(a.kwonlyargs, a.kw_defaults):
        if default is not None:
            defaults[param.arg] = default
    if a.kwarg:
        names.append('**' + a.kwarg.arg)
    return names, defaults


def check_file(path, project=None):
    """Every problem with the docstring types in one file.

    Args:
        path (str): The file to check.
        project (Project|None): What to fall back on for a name this module does
            not itself carry. Without one, every such name is reported as
            unresolvable, even where the project plainly has it.

    Returns:
        list[Finding]: What is wrong, in the order it appears in the file.
    """
    project = project or Project(None)
    source = read_source(path)
    tree = ast.parse(source)
    known = module_names(tree) | BUILTIN
    findings = []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        doc = ast.get_docstring(node)
        if not doc:
            continue
        declared = parse_args_block(doc)
        real, defaults = signature(node)

        if not declared:
            if real and 'Args:' in doc:
                findings.append(
                    Finding(
                        path,
                        node.lineno,
                        node.name,
                        'unparsed',
                        'has an Args: block that declares nothing',
                    )
                )
            continue

        got = [n for n, _ in declared]
        agree, missing = compare_names(got, real)
        if not agree:
            findings.append(
                Finding(
                    path,
                    node.lineno,
                    node.name,
                    'mismatch',
                    'documents (%s) but takes (%s)' % (', '.join(got), ', '.join(real)),
                )
            )
        for name in missing:
            findings.append(
                Finding(
                    path,
                    node.lineno,
                    node.name,
                    'undocumented',
                    "takes '%s', which the Args: block does not name" % name,
                )
            )

        for name, expr in declared:
            text = normalize(expr)
            try:
                parsed = ast.parse(text, mode='eval')
            except SyntaxError:
                findings.append(
                    Finding(
                        path,
                        node.lineno,
                        node.name,
                        'syntax',
                        "type of '%s' is not an expression: %s" % (name, expr),
                    )
                )
                continue
            for used in names_in(parsed.body):
                here, where = resolve(used, known, project)
                if here:
                    continue
                if where:
                    findings.append(
                        Finding(
                            path,
                            node.lineno,
                            node.name,
                            'unqualified',
                            "type of '%s' names '%s', which this module does not import "
                            "(%s has it)" % (name, used, where),
                        )
                    )
                else:
                    findings.append(
                        Finding(
                            path,
                            node.lineno,
                            node.name,
                            'unresolved',
                            "type of '%s' names '%s', which nothing in the project defines"
                            % (name, used),
                        )
                    )
            bare = name.lstrip('*')
            if (
                bare in defaults
                and isinstance(defaults[bare], ast.Constant)
                and defaults[bare].value is None
            ):
                if 'None' not in text and 'Optional' not in text and 'Any' not in text:
                    findings.append(
                        Finding(
                            path,
                            node.lineno,
                            node.name,
                            'default',
                            "'%s' defaults to None but its type (%s) does not admit it"
                            % (name, expr),
                        )
                    )
    return findings


def annotate(path):
    """The module rewritten with its docstring types as real annotations.

    This is what makes mypy useful here. It ignores docstrings, so the types have
    to become annotations before it will look at them.

    Line numbers do not survive: ast.unparse() reformats. Findings are therefore
    reported by function name, which is stable.

    Args:
        path (str): The file to rewrite.

    Returns:
        str: Python source, ready for mypy.
    """
    tree = ast.parse(read_source(path))

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        doc = ast.get_docstring(node)
        if not doc:
            continue
        declared = dict((n.lstrip('*'), t) for n, t in parse_args_block(doc))
        if not declared:
            continue
        a = node.args
        for param in getattr(a, 'posonlyargs', []) + a.args + a.kwonlyargs:
            if param.arg in declared and param.annotation is None:
                try:
                    param.annotation = ast.parse(
                        normalize(declared[param.arg]), mode='eval'
                    ).body
                except SyntaxError:
                    pass
        ret = parse_returns(doc)
        if ret and node.returns is None:
            try:
                node.returns = ast.parse(normalize(ret), mode='eval').body
            except SyntaxError:
                pass

    header = (
        'from __future__ import annotations\n'
        'from typing import Any, Callable, Iterable, Optional, Union\n'
    )
    return header + ast.unparse(ast.fix_missing_locations(tree))


def enclosing(source):
    """Which function each line of a module belongs to.

    Args:
        source (str): Python source.

    Returns:
        dict[int, str]: Line number to function name. A line inside a nested
            function is named for the innermost one holding it.
    """
    out = {}
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        end = getattr(node, 'end_lineno', node.lineno)
        for line in range(node.lineno, end + 1):
            # Innermost wins: a nested function is walked after the one holding
            # it, so overwriting is what puts the closest name in.
            out[line] = node.name
    return out


def relocate(message, annotated, original, path):
    """A mypy message moved from the annotated copy back onto the real file.

    ast.unparse() reformats, so the line numbers mypy reports are its own. The
    function name survives, and that is enough to point at the right place.

    Args:
        message (str): One line of mypy output.
        annotated (dict[int, str]): Line to function, in the annotated copy.
        original (dict[str, int]): Function to the line it is defined on, in the
            real file.
        path (str): The real file.

    Returns:
        str: The message, with the real location where one could be worked out.
    """
    m = re.match(r'^(?P<file>.+?):(?P<line>\d+): (?P<rest>.*)$', message)
    if not m:
        return message
    func = annotated.get(int(m.group('line')))
    where = original.get(func)
    if func and where:
        return '%s:%d: in %s(): %s' % (
            os.path.basename(path),
            where,
            func,
            m.group('rest'),
        )
    return '%s: %s' % (os.path.basename(path), m.group('rest'))


def run_mypy(path, keep):
    """Hand the annotated module to mypy and print what it says.

    Args:
        path (str): The file to check.
        keep (bool): Leave the annotated copy on disk, to look at.

    Returns:
        int: How many messages mypy produced.
    """
    if sys.version_info < (3, 9):
        sys.stderr.write('--mypy needs Python 3.9 or later for ast.unparse()\n')
        return 0
    folder = tempfile.mkdtemp(prefix='docstring-types-')
    target = os.path.join(folder, os.path.basename(path))
    rewritten = annotate(path)
    io.open(target, 'w', encoding='utf-8').write(rewritten)

    annotated_lines = enclosing(rewritten)
    # First definition wins, and written out for the reason given in build_index.
    original_lines = {}
    for node in ast.walk(ast.parse(read_source(path))):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name not in original_lines:
                original_lines[node.name] = node.lineno

    result = subprocess.run(
        # 'check-untyped-defs' matters more than it looks: without it mypy walks
        # straight past the body of any function that has no annotations, and a
        # function whose docstring documents no parameters gets none. That is
        # where the wrong calls are.
        [
            sys.executable,
            '-m',
            'mypy',
            '--ignore-missing-imports',
            '--no-error-summary',
            '--follow-imports=skip',
            '--check-untyped-defs',
            '--disable-error-code=var-annotated',
            '--disable-error-code=no-any-return',
            target,
        ],
        capture_output=True,
        text=True,
    )
    lines = [x for x in (result.stdout + result.stderr).split('\n') if x.strip()]
    lines = [x for x in lines if not NOISE.search(x)]
    for line in lines:
        print(relocate(line, annotated_lines, original_lines, path))
    if keep:
        print('\nannotated copy: %s' % target)
    return len(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('files', nargs='+', help="the Python files to check")
    parser.add_argument(
        '--mypy',
        action='store_true',
        help="also run mypy over the docstring types as annotations",
    )
    parser.add_argument(
        '--keep', action='store_true', help="with --mypy, keep the annotated copy"
    )
    parser.add_argument(
        '--project',
        metavar='DIR',
        help="the project root to index. Found from the checked " "files if not given.",
    )
    args = parser.parse_args(argv)

    project = Project(args.project or project_root(args.files))

    total = 0
    for path in args.files:
        findings = check_file(path, project)
        for finding in findings:
            print(finding)
        total += len(findings)

    if args.mypy:
        for path in args.files:
            print('\n--- mypy, %s' % os.path.basename(path))
            total += run_mypy(path, args.keep)

    if not total:
        print('no problems found')
    return 1 if total else 0


if __name__ == '__main__':
    sys.exit(main())
