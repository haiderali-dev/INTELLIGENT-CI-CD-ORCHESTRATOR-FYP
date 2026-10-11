#!/bin/sh
# Dependency and code security scan. Referenced as extra_stages.security_scan.
#
# ruff's bandit rules rather than a network scanner: the agents may have no internet during an
# experiment run, and a stage that fails on network conditions would corrupt the timings this
# project measures.
set -eu

cd "$(dirname "$0")/.."
if [ -d .venv ]; then
    . .venv/bin/activate
fi

echo "[security] ruff bandit rules"
python -m ruff check --select S app
echo "[security] ok"
