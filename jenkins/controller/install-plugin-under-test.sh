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
#
# Never name a variable here REF. The stock image exports REF=/usr/share/jenkins/ref, the folder
# jenkins.sh seeds a new home from, and assigning to an exported variable exports the new value.
# This script once did, with the path of the plugin's .jpi, so jenkins.sh seeded a new home with
# that one file: a fresh controller started with 1 of its 80 plugins, the optimizer failed to load
# without structs, and configuration as code never applied (DF-46). A home that existed before
# this script came was unaffected, which is why it went unnoticed until Phase 7 first started the
# experiment controllers.
set -euo pipefail

readonly PLUGIN_NAME="dynamic-queue-optimizer"
readonly IMAGE_PLUGIN="/usr/share/jenkins/ref/plugins/${PLUGIN_NAME}.jpi"
readonly HOME_PLUGINS="${JENKINS_HOME:-/var/jenkins_home}/plugins"

if [ -f "$IMAGE_PLUGIN" ]; then
    mkdir -p "$HOME_PLUGINS"
    # The exploded directory, the .jpi, and the .pinned marker that tells Jenkins to keep the
    # installed copy. All three must go, or the stale one wins.
    rm -rf \
        "${HOME_PLUGINS}/${PLUGIN_NAME}" \
        "${HOME_PLUGINS}/${PLUGIN_NAME}.jpi" \
        "${HOME_PLUGINS}/${PLUGIN_NAME}.jpi.pinned" \
        "${HOME_PLUGINS}/${PLUGIN_NAME}.jpi.version_from_image"
    cp "$IMAGE_PLUGIN" "${HOME_PLUGINS}/${PLUGIN_NAME}.jpi"
    echo "installed ${PLUGIN_NAME} from the image ($(stat -c %s "$IMAGE_PLUGIN") bytes)"
else
    echo "WARNING: ${IMAGE_PLUGIN} is missing; the controller will start without the plugin under test" >&2
fi

exec /usr/local/bin/jenkins.sh "$@"
