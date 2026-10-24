# Jenkins controller for the Intelligent CI/CD Orchestrator.
#
# BUILD_PROMPT 4.2.1: official Jenkins LTS image on JDK 21, plugins from plugins.txt installed with
# the plugin installation manager, the setup wizard disabled, CASC_JENKINS_CONFIG pointed at the
# mounted configuration, and the built .hpi copied into the image's reference directory so it
# installs on first start.
#
# Two stages (docs/decisions.md D-078):
#   stock      Jenkins and the pinned plugins, without the optimizer. Only jenkins-stock runs it:
#              the stock-Jenkins arm of the experiment (Part 4.8.2).
#   optimizer  stock, plus the optimizer and the entrypoint that installs it. Every other
#              controller runs it; as the last stage, it is what a build without a target gives.
# Because the second stage is built from the first, the stock controller differs from the others by
# the plugin and nothing else, and verify.py checks that the second stage adds nothing more.
#
# The build context is the repository root, not this directory, because the image needs
# plugin/target/*.hpi. Build with:
#     docker compose build jenkins-dev
# or:
#     docker build -f jenkins/controller/Dockerfile -t orchestrator-jenkins .
# The stock stage alone needs no .hpi:
#     docker compose build jenkins-stock

# Pinned to the LTS baseline the plugin targets (docs/decisions.md D-003). Floating on :lts would
# let a controller upgrade change scheduling behaviour between two experiment runs, which is
# exactly the kind of uncontrolled variable the report cannot afford.
FROM jenkins/jenkins:2.568.3-lts-jdk21 AS stock

# Everything below runs as root; the image drops back to the jenkins user at the end.
USER root

# --- Plugins -------------------------------------------------------------------
# jenkins-plugin-cli resolves and installs the pinned set. --verbose makes the resolved graph
# visible in the build log, which is what to read when a transitive bump breaks a test.
COPY jenkins/controller/plugins.txt /usr/share/jenkins/ref/plugins.txt
RUN jenkins-plugin-cli \
        --plugin-file /usr/share/jenkins/ref/plugins.txt \
        --verbose

# --- Configuration as Code -----------------------------------------------------
RUN mkdir -p /var/jenkins_conf /var/jenkins_keys \
    && chown -R jenkins:jenkins /var/jenkins_conf /var/jenkins_keys /usr/share/jenkins/ref

USER jenkins

# JAVA_OPTS:
#   runSetupWizard=false      the wizard would block JCasC from applying anything
#   AWTHeadless               no display in a container
#   csrf proxy compatibility  left at the default; the backend fetches a crumb (4.4.5)
#   update-site signatures    checked, the default: plugins come pinned from plugins.txt, and
#                             nothing should accept unsigned update metadata (security review, 13)
# JENKINS_SLAVE_AGENT_PORT=-1 turns the inbound agent port off: both agents connect over SSH
# (security review, finding 2).
ENV JAVA_OPTS="-Djenkins.install.runSetupWizard=false -Djava.awt.headless=true" \
    CASC_JENKINS_CONFIG=/var/jenkins_conf/jenkins.yaml \
    JENKINS_SLAVE_AGENT_PORT=-1

# The controller runs zero builds (4.2.2), so it needs no executors of its own. JCasC sets this
# too; declaring it here means a controller started without JCasC still does not run builds.
ENV JENKINS_OPTS=""

EXPOSE 8080

# The stock stage keeps the base image's own entrypoint: tini, then jenkins.sh.

# ===============================================================================
# The controller under test: stock, plus the Dynamic Queue Optimizer.
# ===============================================================================
FROM stock AS optimizer

USER root

# --- The Dynamic Queue Optimizer ----------------------------------------------
# Copied into the reference directory so Jenkins installs it on first start of a fresh home. This
# is BUILD_PROMPT task T2.14's install step: build the .hpi with `cd plugin && mvn -B verify`
# before building this image, or the COPY fails with a clear message rather than producing a
# controller silently missing the plugin under test. Owned by jenkins, like the rest of the
# reference directory.
COPY --chown=jenkins:jenkins plugin/target/dynamic-queue-optimizer.hpi \
     /usr/share/jenkins/ref/plugins/dynamic-queue-optimizer.jpi

# Jenkins seeds ref/plugins into a home only when the plugin is absent or the image carries a newer
# version. The plugin under test is always 2.0.0-SNAPSHOT, so "newer" is never true and a
# persistent volume keeps serving whatever it got on its first boot -- which made one rebuilt fix
# appear not to work at all. This entrypoint replaces that one plugin on every start.
COPY jenkins/controller/install-plugin-under-test.sh /usr/local/bin/install-plugin-under-test.sh
RUN chmod +x /usr/local/bin/install-plugin-under-test.sh

USER jenkins

# Wraps the stock entrypoint rather than replacing it: the wrapper reinstalls the plugin under
# test and then execs /usr/local/bin/jenkins.sh, so every other startup behaviour is unchanged.
ENTRYPOINT ["/usr/local/bin/install-plugin-under-test.sh"]
