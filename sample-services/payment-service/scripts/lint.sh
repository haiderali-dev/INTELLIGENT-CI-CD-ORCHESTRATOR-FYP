#!/bin/sh
# Lint. Referenced by catalog/services.yaml as extra_stages.lint.
set -eu

cd "$(dirname "$0")/.."
if [ -d .venv ]; then
    . .venv/bin/activate
fi

echo "[lint] ruff"
python -m ruff check app tests
python -m ruff format --check app tests
echo "[lint] ok"
