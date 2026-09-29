#!/bin/sh
# Run one test suite. Referenced by catalog/services.yaml as test_suites[].command.
# Usage: ./scripts/test.sh unit
set -eu

SUITE="${1:-unit}"
cd "$(dirname "$0")/.."

case "$SUITE" in
    unit)
        echo "[test] unit suite (about 6s)"
        node --test test/*.test.js
        ;;
    *)
        # Fail loudly: a typo in the catalog must not look like a passing build.
        echo "[test] unknown suite '$SUITE'; auth-service has only 'unit'" >&2
        exit 2
        ;;
esac

echo "[test] $SUITE ok"
