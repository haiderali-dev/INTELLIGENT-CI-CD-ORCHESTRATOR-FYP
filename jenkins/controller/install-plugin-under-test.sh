#!/usr/bin/env bash
# Install the freshly built Dynamic Queue Optimizer over whatever a persistent home already holds,
# then hand over to the stock Jenkins entrypoint.
#
# Why this exists. Jenkins seeds /usr/share/jenkins/ref/plugins into $JENKINS_HOME/plugins only
# when the plugin is not already installed, or when the image carries a newer version. The plugin
# under test is always 2.0.0-SNAPSHOT, so "newer" is never true: after the first boot of a named
# volume, every later `docker compose build` produced an image whose plugin was silently ignored,
# and the controller kept running the first build forever.
#
# That cost real debugging time once already -- a fix to the metrics publisher appeared not to
# work, because the running controller still had the previous .hpi. For a plugin that is rebuilt
# on nearly every task, replacing it on start is the correct behaviour, not a convenience.
#
# Scoped deliberately to this one plugin: everything from plugins.txt is version-pinned and must
# keep Jenkins' own upgrade semantics (docs/decisions.md D-003 pins the baseline for exactly that
# reason).
set -euo pipefail

readonly PLUGIN_NAME="dynamic-queue-optimizer"
readonly REF="/usr/share/jenkins/ref/plugins/${PLUGIN_NAME}.jpi"
readonly HOME_PLUGINS="${JENKINS_HOME:-/var/jenkins_home}/plugins"

if [ -f "$REF" ]; then
    mkdir -p "$HOME_PLUGINS"
    # The exploded directory, the .jpi, and the .pinned marker that tells Jenkins to keep the
    # installed copy. All three must go, or the stale one wins.
    rm -rf \
        "${HOME_PLUGINS}/${PLUGIN_NAME}" \
        "${HOME_PLUGINS}/${PLUGIN_NAME}.jpi" \
        "${HOME_PLUGINS}/${PLUGIN_NAME}.jpi.pinned" \
        "${HOME_PLUGINS}/${PLUGIN_NAME}.jpi.version_from_image"
    cp "$REF" "${HOME_PLUGINS}/${PLUGIN_NAME}.jpi"
    echo "installed ${PLUGIN_NAME} from the image ($(stat -c %s "$REF") bytes)"
else
    echo "WARNING: ${REF} is missing; the controller will start without the plugin under test" >&2
fi

exec /usr/local/bin/jenkins.sh "$@"
