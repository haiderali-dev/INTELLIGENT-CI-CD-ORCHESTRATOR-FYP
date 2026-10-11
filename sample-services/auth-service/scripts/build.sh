#!/bin/sh
# Build auth-service. Referenced by catalog/services.yaml as build_command.
# POSIX sh with LF endings: the agents are Linux containers and a CRLF shebang fails with
# "bad interpreter: /bin/sh^M".
set -eu

echo "[build] auth-service"
cd "$(dirname "$0")/.."

# No dependencies, so there is nothing to install. Syntax-check every source file instead, so a
# broken file fails the build rather than the deploy.
node --check src/app.js
node --check src/server.js
node --check test/unit.test.js

echo "[build] ok"
