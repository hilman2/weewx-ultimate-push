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
FROM python:${PYTHON}-slim AS base

ARG WEEWX=5.5.0

# pyserial and pyusb are what the hosted drivers need in order to be importable.
# Without them tools/build_drivers.py and the driver matrix test see an ImportError
# instead of a driver, which is a real state and not the one worth testing.
RUN pip install --no-cache-dir \
        "weewx==${WEEWX}" \
        pytest \
        pytest-timeout \
        pytest-randomly \
        pytest-xdist \
        pyserial \
        pyusb \
        black \
        mypy \
        vermin

WORKDIR /src

# Unbuffered, so that a long run says where it is while it is running rather than
# all at once when it finishes.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Not root. Two tests make a file unwritable and check the driver survives it, and
# root can write to anything, so as root those tests pass for the wrong reason and
# then fail on the assertion. The uid does not have to match anybody: the source is
# mounted read-only and everything written goes to /tmp.
RUN useradd --create-home --uid 1000 tester
USER tester

# A test that hangs fails and says where, rather than being killed with the
# whole run. Nothing here should take anywhere near this long.
#
# One worker per core. Nearly every test here waits on something real, a socket
# answering or a thread settling, so the run is mostly waiting and splitting it up
# buys that time back. Each worker is its own process, every socket is bound to
# port 0, and every file goes under the test's own tmp_path, so there is nothing
# for two workers to collide over.
CMD ["python", "-m", "pytest", "tests", "-q", "--timeout=60", "-n", "auto"]


# The same suite on a machine that has no WeeWX.
#
# Most of this driver has to work without it: the transport, the catalogs, the
# protocols and the inference are meant to be exercised from a captured payload on
# any machine, and CI runs them that way on six Python versions. Nothing local ever
# did, because every container here has WeeWX in it, and that is how
# ultimatepush.polling came to need WeeWX to import and stayed that way for eleven
# commits and one release.
#
#     docker compose -f tests/docker/compose.yml run --rm tests-bare
FROM python:${PYTHON}-slim AS bare

RUN pip install --no-cache-dir pytest pytest-timeout pytest-randomly pytest-xdist

WORKDIR /src
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
RUN useradd --create-home --uid 1000 tester
USER tester

# Everything that needs WeeWX skips itself. What must not happen is a collection
# error, which is what a module importing WeeWX at the top of the file causes.
CMD ["python", "-m", "pytest", "tests", "-q", "--timeout=60", "-n", "auto"]


# Drivers that WeeWX does not ship, for the tests that host them.
#
# They are fetched at a stated commit rather than at whatever their branch says
# today, so that a run that fails says something about this driver rather than about
# somebody else's morning.
#
# Each is read here and none is shipped: nothing from this stage goes into a
# release. That matters, because they are not all licensed the same way. Most are
# only 'all rights reserved'. Reading somebody's published source in order to test
# against it is one thing and redistributing it is another, and this stage does the
# first only.
FROM base AS external

USER root
RUN apt-get update \
    && apt-get install --no-install-recommends -y git \
    && rm -rf /var/lib/apt/lists/*

# What MQTTSubscribe talks to a broker with. The others need nothing that is not
# already here, which is why they can be hosted on a machine with no hardware.
RUN pip install --no-cache-dir paho-mqtt crcmod

ARG MQTTSUBSCRIBE=f622291360ce1e74b8f000324226a1440e8f93b3
ARG WEATHERFLOWUDP=eedfaf7b1ee1d0eb51513966b7a09e7622858791
ARG RTLDAVIS=2f3b4b344fd70ab253aabfa837b0ffc76570c075
ARG SDR=e5f1f9915322fa6d1c25b4ff8e490b804cefeac1
ARG PURPLE=7c4e11724eadea51f1a0d98261e3907801402709
# Hardware on a wire, and hardware on USB. Between them they ask the host for
# things nothing else does: a clock that can be set, startup records, and a form
# built from a driver that ships no editor.
ARG WXT5X0=d64d39747f3b446ca5706bc8c492dbb39b0aa261
ARG MAXBOTIX=cf4265253ef50a4077dca3fedf5181d7769dd245
ARG WS6IN1=1fb840239a1bbc2caee2e663208ea0c7bffe54cb
ARG KLIMALOGG=9b70be25bc1650ae109de8fa9071ae9ce384e352
# Not hosted, read. Its live_data_struct is a second person's reading of the same
# Ecowitt gateway API, written years earlier, and holding a table against an
# independent one is the only way to catch a transcription slip in it.
ARG GW1000=97376d971e35826952342a6a4a16400f3bc1cc4c

# Laid out as a WeeWX installation lays them out: bin/user, which is the package
# `available()` searches for drivers somebody installed as an extension.
RUN mkdir -p /opt/external/user && touch /opt/external/user/__init__.py
RUN set -e; \
    for one in \
        "https://github.com/bellrichm/WeeWX-MQTTSubscribe ${MQTTSUBSCRIBE}" \
        "https://github.com/captain-coredump/weatherflow-udp ${WEATHERFLOWUDP}" \
        "https://github.com/lheijst/weewx-rtldavis ${RTLDAVIS}" \
        "https://github.com/matthewwall/weewx-sdr ${SDR}" \
        "https://github.com/chaunceygardiner/weewx-purple ${PURPLE}" \
        "https://github.com/matthewwall/weewx-wxt5x0 ${WXT5X0}" \
        "https://github.com/matthewwall/weewx-maxbotix ${MAXBOTIX}" \
        "https://github.com/BobAtchley/weewx-ws6in1 ${WS6IN1}" \
        "https://github.com/matthewwall/weewx-klimalogg ${KLIMALOGG}" \
        "https://github.com/bidord/weewx-gw1000 ${GW1000}" \
    ; do \
        set -- ${one}; \
        name=$(basename "$1"); \
        git clone --quiet "$1" "/tmp/${name}"; \
        git -C "/tmp/${name}" checkout --quiet "$2"; \
        cp /tmp/${name}/bin/user/*.py /opt/external/user/; \
        rm -rf "/tmp/${name}"; \
    done; \
    ls /opt/external/user/

USER tester
ENV EXTERNAL_DRIVERS=/opt/external
CMD ["python", "-m", "pytest", "tests/test_external.py", "-q", "--timeout=90"]
