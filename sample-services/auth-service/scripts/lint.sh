#!/bin/sh
# Lint. Referenced by catalog/services.yaml as extra_stages.lint.
set -eu

cd "$(dirname "$0")/.."
echo "[lint] node --check"
for f in src/*.js test/*.test.js; do
    node --check "$f"
done
echo "[lint] ok"
