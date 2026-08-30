# Development

Working on the driver itself: the source, the tests, the tools, and how a release is
made. How the code is arranged is in [Architecture](Architecture.md); what a change has
to look like is in [Conventions](Conventions.md); what to do with a change once it works
is in [Contributing](Contributing.md).

## The source

```
git clone https://github.com/hilman2/weewx-ultimate-push.git
cd weewx-ultimate-push
```

Nothing has to be built and nothing has to be installed. The driver imports only the
standard library, and all but four of its modules run without WeeWX; which four, and
why that is worth keeping, is in [Architecture](Architecture.md#layout).

To run the clone as the installed driver, `weectl extension install
weewx-ultimate-push` from the directory above it.

## Tests

```
pip install pytest
python -m pytest tests -q
```

Without WeeWX, the tests that need it are skipped. With it, everything runs:

```
pip install weewx
python -m pytest tests -q
```

The tests work from payloads captured off real hardware, in `tests/fixtures`, with
anything that named the station removed. A change that would have dropped a field fails
a test rather than appearing in a database a month later.

CI runs both, across Python 3.8 to 3.13, plus a vermin check against 3.7.

## The tools

| | |
|---|---|
| `tools/import_catalog.py` | generates the Ecowitt catalog |
| `tools/import_ambient.py` | generates the Ambient catalog |
| `tools/build_reference.py` | generates `docs/Ecowitt-sensors.md` |
| `tools/build_hardware.py` | generates `docs/Hardware.md` |
| `tools/build_protocols.py` | generates `docs/Protocol-*.md`, one per protocol |
| `tools/build_drivers.py` | generates `docs/Driver-*.md`, one per WeeWX driver installed here |
| `tools/check_against_ecowitt.py` | holds the channel counts against Ecowitt's cloud API |
| `tools/check_docstring_types.py` | holds the docstring types against the signatures |
| `tools/publish_wiki.py` | copies `docs/` into the wiki |

## Running the tests

In Docker, against a stated WeeWX, so that a run says the same thing on every machine:

```bash
docker compose -f tests/docker/compose.yml run --rm tests
```

| Service | |
|---|---|
| `tests` | the suite, with a per-test timeout |
| `watch` | the same, saying what it is doing while it does it |
| `checks` | black, mypy, the docstring types, vermin |
| `tests-oldest` | the suite on the oldest Python WeeWX supports |
| `build-docs` | the four generators, the only service that may write to `docs/` |
| `shell` | a shell in the same environment |
| `external` | drivers WeeWX does not ship, fetched into that image |

The suite runs one worker per core, which takes it from a little over two minutes to
about ten seconds. `watch` stays on one, because interleaved output from eight
workers is not worth reading.

The source is mounted read-only and everything written goes to `/tmp`. The container
runs as a normal user rather than root: two tests make a file unwritable and check the
driver survives it, and root can write to anything.

What the first five are for, and which lists decide where a reading goes, is in
[Catalogs](Catalogs.md). The docstring checker is in
[Conventions](Conventions.md#types).

## Publishing the documentation

The pages live in `docs/` because that is where they can be reviewed in a pull request
beside the code they describe, and because two of them are generated. The wiki is where
people read them.

```
git clone git@github.com:hilman2/weewx-ultimate-push.wiki.git /tmp/wiki
python tools/publish_wiki.py --wiki /tmp/wiki
cd /tmp/wiki && git add -A && git commit && git push
```

The tool takes `.md` off internal links, points images at raw.githubusercontent.com, and
writes the sidebar. A new page needs an entry in `SIDEBAR` in that tool and a line on
[Home](Home.md), or nothing links to it.

## Releasing

Set the version in `install.py` and `bin/user/ultimatepush/__init__.py`, update
`CHANGELOG.md`, then tag:

```
git tag v0.2.0
git push origin v0.2.0
```

The release workflow checks that the tag matches both files, builds the extension zip,
and publishes it as `weewx-ultimate-push.zip`. The name carries no version, so that
`releases/latest/download/weewx-ultimate-push.zip` is the install command in the
documentation and stays right without anybody editing it. Which version a download is
comes from the tag it was built from.
