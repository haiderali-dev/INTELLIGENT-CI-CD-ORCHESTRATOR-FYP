#!/bin/sh
# Give the agent's jenkins user access to the mounted Docker socket, then start sshd.
#
# The socket's group is only known at run time, so the image cannot fix it at build time: on a
# Linux host it is the host's docker group (any GID), and under Docker Desktop it is root:root 660,
# which no build-time group can match. Every staging deploy failed with "permission denied ...
# docker.sock" until this ran at start-up (docs/decisions.md D-038).
#
# Builds run in SSH sessions, which read the user's groups at login, so fixing them here -- before
# sshd accepts a session -- is enough.
#
# Access to the Docker socket is root-equivalent on the Docker host whatever the group mechanics;
# that is the accepted "Docker socket on local agents" limitation in the report, not something this
# script widens.
set -eu

SOCKET=/var/run/docker.sock

if [ -S "$SOCKET" ]; then
    gid=$(stat -c %g "$SOCKET")
    if [ "$gid" = "0" ]; then
        # Docker Desktop. Putting jenkins in the root group would grant every root-group file in
        # the container; handing the socket to the agent's own docker group grants exactly the
        # socket. Docker Desktop recreates the socket inside its VM on restart, so this is
        # re-applied on every agent start and never touches the Windows host.
        chgrp docker "$SOCKET"
        chmod g+rw "$SOCKET"
    else
        owner=$(getent group "$gid" | cut -d: -f1 || true)
        if [ -z "$owner" ]; then
            groupmod -g "$gid" docker
            owner=docker
        fi
        usermod -aG "$owner" jenkins
    fi
    echo "[agent] docker socket $(stat -c '%U:%G %a' "$SOCKET"); $(id jenkins)"
else
    echo "[agent] no docker socket mounted; deploy steps will fail" >&2
fi

exec /usr/local/bin/setup-sshd "$@"
