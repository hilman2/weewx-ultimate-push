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

    check_docstring_types.py bin/user/ultimatepush/mapping.py
        Checks the docstrings on their own: parameter names and order against the
        signature, whether each type expression parses, whether the names in it
        resolve, and whether a parameter defaulting to None admits None.

    check_docstring_types.py --mypy bin/user/ultimatepush/mapping.py
        Writes a copy with the docstring types as annotations, runs mypy over it,
        and reports what mypy makes of them. This is the part that finds a type
        which is simply wrong, rather than merely malformed.
"""

import argparse
import ast
import io
import os
import re
import subprocess
import sys
import tempfile
from typing import Dict

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
# these on its own, and so does this.
BUILTIN = {
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
    'bool',
    'bytes',
    'callable',
    'complex',
    'dict',
    'float',
    'frozenset',
    'int',
    'list',
    'object',
    'set',
    'str',
    'tuple',
    'None',
    'NoneType',
    'Ellipsis',
    'bytearray',
    'type',
    'Exception',
    'memoryview',
    'range',
    'slice',
}


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


def module_imports(tree):
    """The names a module has imported, as a type expression may use them.

    Args:
        tree (ast.Module): The parsed module.

    Returns:
        set[str]: Importable names, including the dotted forms of 'import a.b.c' and
        the classes and functions the module defines itself.
    """
    out = set()
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            out.add(node.name)
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


def check_file(path):
    """Every problem with the docstring types in one file.

    Args:
        path (str): The file to check.

    Returns:
        list[Finding]: What is wrong, in the order it appears in the file.
    """
    source = io.open(path, encoding='utf-8').read()
    tree = ast.parse(source)
    known = module_imports(tree) | BUILTIN
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
        if got != real:
            findings.append(
                Finding(
                    path,
                    node.lineno,
                    node.name,
                    'mismatch',
                    'documents (%s) but takes (%s)' % (', '.join(got), ', '.join(real)),
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
                root = used.split('.')[0]
                if used not in known and root not in known:
                    findings.append(
                        Finding(
                            path,
                            node.lineno,
                            node.name,
                            'unresolved',
                            "type of '%s' names '%s', which the module does not import"
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
    tree = ast.parse(io.open(path, encoding='utf-8').read())

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
    original_lines = {}  # type: Dict[str, int]
    for node in ast.walk(ast.parse(io.open(path, encoding='utf-8').read())):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            original_lines.setdefault(node.name, node.lineno)

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
    args = parser.parse_args(argv)

    total = 0
    for path in args.files:
        findings = check_file(path)
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
