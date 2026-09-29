#!/bin/sh
# Build payment-service. Referenced by catalog/services.yaml as build_command.
#
# POSIX sh with LF endings (.gitattributes enforces this): the agents are Linux containers, and a
# CRLF shebang line fails with the unhelpful "bad interpreter: /bin/sh^M".
set -eu

echo "[build] payment-service"
cd "$(dirname "$0")/.."

python3 -m venv .venv
. .venv/bin/activate

python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements-dev.txt

# Byte-compile everything: a syntax error should fail the build, not the deploy.
python -m compileall -q app tests

echo "[build] ok"
