#!/bin/sh
# Run one test suite. Referenced by catalog/services.yaml as test_suites[].command.
#
# Usage: ./scripts/test.sh unit | integration
set -eu

SUITE="${1:-unit}"
cd "$(dirname "$0")/.."

if [ -d .venv ]; then
    . .venv/bin/activate
fi

case "$SUITE" in
    unit)
        echo "[test] unit suite (about 8s)"
        python -m pytest tests/test_unit.py -q
        ;;
    integration)
        echo "[test] integration suite (about 20s)"
        python -m pytest tests/test_integration.py -q
        ;;
    *)
        # Fail loudly rather than silently running nothing: a typo in the catalog must not look
        # like a passing build.
        echo "[test] unknown suite '$SUITE'; expected 'unit' or 'integration'" >&2
        exit 2
        ;;
esac

echo "[test] $SUITE ok"
