# Conventions

What a change has to look like before it is proposed. All of it is checked by CI, so a
pull request that skips it fails before anybody reads it.

## Formatting

```
pip install black
black bin tools tests install.py
```

`black`, with the single quotes this project is written in kept. The settings are in
`pyproject.toml`, with the reason for each beside it, so this and an editor cannot
disagree.

Two rules the tool cannot state:

**Never reformat more than you changed.** A diff that touches lines nobody asked about
hides the change inside it.

**`bin/user/listener.py` is not edited or formatted.** It has to stay byte-identical to
WeeWX's own; see [Architecture](Architecture.md#the-listening-socket).

## Types

The code carries no annotations. The types are in the Google-style docstrings, which is
where WeeWX declares its own. Two checkers run, because the two places disagree
otherwise:

```
pip install mypy
mypy
python tools/check_docstring_types.py \
    $(find bin/user/ultimatepush tools -name '*.py') install.py
```

`mypy` runs with `check_untyped_defs`, without which it would see 269 functions with no
annotations and check none of their bodies.

The second checker reads the `Args:` and `Returns:` blocks and holds them against the
signature: parameter names and order, whether each type expression parses, whether its
names resolve in that module, and whether a parameter that defaults to None admits None.
No command line type checker does this, and PyCharm, which does read them, is not
something CI can run.

Adding `--mypy` writes a copy with the docstring types turned into real annotations and
runs mypy over that. It finds a type that is well-formed and simply wrong, which the
first pass cannot. It is worth running after changing a docstring's types and is not in
CI, because in a project without annotations it also reports a good deal about the code
rather than about the docstring.

## Python version

The floor is 3.7, which is WeeWX's, and it is older than anything the CI runners will
install. `vermin` checks the syntax against it. Everything that ships has to clear it;
`tools/check_docstring_types.py` is exempt, because it is in no release zip.

## Comments and docstrings

A docstring says what a caller needs: what the function is for, its arguments with their
types, what comes back. A comment says what only somebody changing the code needs, and
that is almost always a reason rather than a description. What the code plainly does is
not commented.

The modules carry a docstring that says why the module exists and what it deliberately
does not do. `mapping.py` is the example worth reading.

## Documentation

Every page is in `docs/` and reaches the wiki through `tools/publish_wiki.py`. See
[Development](Development.md#publishing-the-documentation).

Which page a fact belongs on follows from who is reading:

| Section | Reader | What belongs there |
|---|---|---|
| Using it | has a station, wants it to work | tasks, options, symptoms |
| How it works | wants to understand the machine | formats, structures, why the design is this way |
| Development | is changing the code | environment, tools, this page |

The reader of **Using it** owns a weather station. They are not a programmer and have
no reason to be. Write for somebody who knows what a barometer is and does not know
what a field map is, and who came here because a reading is missing or a second console
has arrived.

That decides the words. "Whose temperature is the outdoor temperature" rather than
"which station owns the `outTemp` column"; "the app that configures the console" rather
than "the vendor application". Our own vocabulary is introduced where it first earns
its keep, and not before. A heading names what the reader wants to do, not the
mechanism that does it.

Facts move down that table, never up. An installation page does not explain how an
upload is recognised; it links to the page that does.

State a fact on one page only. Where a second page needs it, link. `docs/Sensors.md` and
`docs/Hardware.md` are generated and are never edited by hand.

## Commits and pull requests

The subject line says what the change does, in one line, without a prefix or a ticket
number:

```
One column, one station
Ask the database everywhere, not the schema
Put drawRaw back, and notice next time
```

A pull request describes what changed and why. Release commits are `Release 0.13.0` and
carry nothing but the version bump and the changelog.
