# The tests, against a real WeeWX, in a container that is the same everywhere.
#
# Two things this buys over running them on the machine you happen to be on: the
# WeeWX version is stated rather than whatever is installed, and the Python version
# is one of the ones the driver has to clear. Nothing here touches the host.
#
#     docker compose -f tests/docker/compose.yml run --rm tests
#
# The version to test against. WeeWX is on PyPI, so this is the whole of it.
ARG PYTHON=3.12
FROM python:${PYTHON}-slim

ARG WEEWX=5.5.0

# pyserial and pyusb are what the hosted drivers need in order to be importable.
# Without them tools/build_drivers.py and the driver matrix test see an ImportError
# instead of a driver, which is a real state and not the one worth testing.
RUN pip install --no-cache-dir \
        "weewx==${WEEWX}" \
        pytest \
        pytest-timeout \
        pytest-randomly \
        pyserial \
        pyusb \
        black \
        mypy \
        vermin

WORKDIR /src

# Unbuffered, so that a long run says where it is while it is running rather than
# all at once when it finishes.
ENV PYTHONDONTWRITEBYTECODE=1     PYTHONUNBUFFERED=1

# Not root. Two tests make a file unwritable and check the driver survives it, and
# root can write to anything, so as root those tests pass for the wrong reason and
# then fail on the assertion. The uid does not have to match anybody: the source is
# mounted read-only and everything written goes to /tmp.
RUN useradd --create-home --uid 1000 tester
USER tester

# A test that hangs fails and says where, rather than being killed with the
# whole run. Nothing here should take anywhere near this long.
CMD ["python", "-m", "pytest", "tests", "-q", "--timeout=60"]
