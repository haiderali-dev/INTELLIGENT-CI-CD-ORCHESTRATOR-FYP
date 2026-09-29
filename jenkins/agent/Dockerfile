# Linux build agent.
#
# BUILD_PROMPT 4.2.1: the official SSH agent image plus Git, Python 3, Node.js LTS, the Docker CLI,
# curl and jq, labelled `linux`. The label itself is assigned by JCasC on the controller, not here;
# this image only has to be able to run what the service catalog's commands invoke.

FROM jenkins/ssh-agent:6.31.0-jdk21

USER root

# One layer, no recommended extras, and the apt lists removed afterwards. Versions are whatever the
# base image's Debian release ships, deliberately: these are build tools for sample services, not
# part of the measured system, so pinning them would add maintenance for no experimental benefit.
# docs/versions.md records that decision.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        gnupg \
        jq \
        python3 \
        python3-pip \
        python3-venv \
        unzip \
    && rm -rf /var/lib/apt/lists/*

# --- Node.js LTS ---------------------------------------------------------------
# auth-service is a Node service, so the agent needs a toolchain for it. NodeSource rather than
# Debian's package because Debian ships a much older Node than the LTS the project targets.
ARG NODE_MAJOR=24
RUN curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" -o /tmp/nodesource_setup.sh \
    && bash /tmp/nodesource_setup.sh \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -f /tmp/nodesource_setup.sh \
    && rm -rf /var/lib/apt/lists/*

# --- Docker CLI ----------------------------------------------------------------
# The CLI only. The agent talks to the host's daemon through the socket that docker-compose.yml
# mounts, rather than running a daemon of its own.
#
# Mounting the host socket gives anything on this agent effective root on the host. That is a real
# limitation of a local, single-machine setup, and BUILD_PROMPT 4.10 requires it to be disclosed in
# the report's limitations section rather than left implicit. It is acceptable here because the only
# jobs that run are the project's own sample services, on a developer machine, deploying to staging.
RUN install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg \
        -o /etc/apt/keyrings/docker.asc \
    && chmod a+r /etc/apt/keyrings/docker.asc \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
        > /etc/apt/sources.list.d/docker.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends docker-ce-cli docker-compose-plugin \
    && rm -rf /var/lib/apt/lists/*

# The agent user needs to reach the mounted Docker socket. The group id is overridden at run time
# from the host's docker group where it differs; 999 is the usual value on Debian hosts.
ARG DOCKER_GID=999
RUN groupadd -g "${DOCKER_GID}" docker 2>/dev/null || true \
    && usermod -aG docker jenkins

# deploy.sh binds each service to a fixed port (payment-service 9001, auth-service 9002), so the
# agent needs a writable workspace and nothing else.
USER jenkins
WORKDIR /home/jenkins

# Sanity: fail the build here rather than at the first job if a tool is missing.
RUN git --version && python3 --version && node --version && jq --version && docker --version
