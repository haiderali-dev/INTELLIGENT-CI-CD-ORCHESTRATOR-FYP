#!/usr/bin/env python3
"""Create the reference jobs on jenkins-dev and export their config.xml.

BUILD_PROMPT task T1.9. One freestyle job and one Pipeline job that build, test and deploy
payment-service to staging, created through the REST API (never the script console), then exported
to ``jenkins/reference-configs/``.

Why this exists at all. BUILD_PROMPT rule 1.4 says "Derive every ``config.xml`` template from a job
created by hand on ``jenkins-dev`` and exported with ``GET /job/<name>/config.xml``. Never write
Jenkins XML from memory." Phase 5's Jinja2 templates are built from these exports, so what matters
is that the committed XML is **what Jenkins itself produced**, not what anyone typed: Jenkins
normalises, reorders and version-stamps every element on save, and a hand-written template that
merely looks right drifts from what the controller will accept.

The jobs deliberately exercise everything 4.6.3 lists for a freestyle job -- Git SCM with branch and
commit parameters, an agent label, one shell step per stage, the priority property, archiving, and
a downstream trigger on success -- so the exported XML shows the real shape of each.

Usage:
    python scripts/export_reference_configs.py
    python scripts/export_reference_configs.py --keep   # leave the jobs on the controller
"""

from __future__ import annotations

import argparse
import base64
import http.cookiejar
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPO_ROOT / "jenkins" / "reference-configs"
ENV_FILE = REPO_ROOT / ".env"
JENKINS_URL = "http://localhost:8087"

FREESTYLE_JOB = "reference-freestyle-payment-service"
PIPELINE_JOB = "reference-pipeline-payment-service"
DOWNSTREAM_JOB = "reference-freestyle-downstream"

_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
_crumb: dict[str, str] = {}


def env() -> dict[str, str]:
    if not ENV_FILE.is_file():
        raise SystemExit("no .env file; run scripts/bootstrap.py first")
    return dict(re.findall(r"^([A-Z_][A-Z0-9_]*)=(.*)$", ENV_FILE.read_text(encoding="utf-8"), re.M))


def call(path: str, creds: tuple[str, str], *, data: bytes | None = None,
         headers: dict[str, str] | None = None) -> tuple[int, str]:
    request = urllib.request.Request(
        JENKINS_URL + path, data=data, method="POST" if data is not None else "GET"
    )
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    token = base64.b64encode(f"{creds[0]}:{creds[1]}".encode()).decode("ascii")
    request.add_header("Authorization", f"Basic {token}")
    try:
        with _opener.open(request, timeout=60) as response:  # noqa: S310
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except Exception as exc:
        return 0, f"{type(exc).__name__}: {exc}"


def crumb(creds: tuple[str, str]) -> dict[str, str]:
    global _crumb
    if not _crumb:
        status, body = call("/crumbIssuer/api/json", creds)
        if status == 200:
            payload = json.loads(body)
            _crumb = {payload["crumbRequestField"]: payload["crumb"]}
    return _crumb


# ---------------------------------------------------------------------------
# The jobs, as posted. Jenkins rewrites these on save; the export is the artifact.
# ---------------------------------------------------------------------------

# Commands come from catalog/services.yaml, never invented here. That is the same rule the
# generator follows at runtime (4.6.1): the model picks stages, the catalog supplies commands.
FREESTYLE_XML = """<?xml version='1.1' encoding='UTF-8'?>
<project>
  <description>Reference freestyle job: build, test and deploy payment-service to staging.</description>
  <keepDependencies>false</keepDependencies>
  <properties>
    <io.jenkins.plugins.queueoptimizer.property.JobPriorityProperty>
      <level>HIGH</level>
      <dependsOn></dependsOn>
    </io.jenkins.plugins.queueoptimizer.property.JobPriorityProperty>
    <hudson.model.ParametersDefinitionProperty>
      <parameterDefinitions>
        <hudson.model.StringParameterDefinition>
          <name>BRANCH</name>
          <description>Branch to build</description>
          <defaultValue>main</defaultValue>
          <trim>true</trim>
        </hudson.model.StringParameterDefinition>
        <hudson.model.StringParameterDefinition>
          <name>COMMIT</name>
          <description>Commit SHA, or empty for the branch head</description>
          <defaultValue></defaultValue>
          <trim>true</trim>
        </hudson.model.StringParameterDefinition>
      </parameterDefinitions>
    </hudson.model.ParametersDefinitionProperty>
    <jenkins.model.BuildDiscarderProperty>
      <strategy class="hudson.tasks.LogRotator">
        <daysToKeep>-1</daysToKeep>
        <numToKeep>30</numToKeep>
        <artifactDaysToKeep>-1</artifactDaysToKeep>
        <artifactNumToKeep>-1</artifactNumToKeep>
      </strategy>
    </jenkins.model.BuildDiscarderProperty>
  </properties>
  <scm class="hudson.plugins.git.GitSCM" plugin="git">
    <configVersion>2</configVersion>
    <userRemoteConfigs>
      <hudson.plugins.git.UserRemoteConfig>
        <url>https://github.com/uit-group04/payment-service.git</url>
      </hudson.plugins.git.UserRemoteConfig>
    </userRemoteConfigs>
    <branches>
      <hudson.plugins.git.BranchSpec>
        <name>${COMMIT:-${BRANCH}}</name>
      </hudson.plugins.git.BranchSpec>
    </branches>
    <doGenerateSubmoduleConfigurations>false</doGenerateSubmoduleConfigurations>
    <submoduleCfg class="empty-list"/>
    <extensions/>
  </scm>
  <assignedNode>linux</assignedNode>
  <canRoam>false</canRoam>
  <disabled>false</disabled>
  <blockBuildWhenDownstreamBuilding>false</blockBuildWhenDownstreamBuilding>
  <blockBuildWhenUpstreamBuilding>false</blockBuildWhenUpstreamBuilding>
  <triggers/>
  <concurrentBuild>false</concurrentBuild>
  <builders>
    <hudson.tasks.Shell>
      <command>./scripts/build.sh</command>
    </hudson.tasks.Shell>
    <hudson.tasks.Shell>
      <command>./scripts/test.sh unit</command>
    </hudson.tasks.Shell>
    <hudson.tasks.Shell>
      <command>./deploy.sh staging</command>
    </hudson.tasks.Shell>
  </builders>
  <publishers>
    <hudson.tasks.ArtifactArchiver>
      <artifacts>**/*.log</artifacts>
      <allowEmptyArchive>true</allowEmptyArchive>
      <onlyIfSuccessful>false</onlyIfSuccessful>
      <fingerprint>false</fingerprint>
      <defaultExcludes>true</defaultExcludes>
      <caseSensitive>true</caseSensitive>
      <followSymlinks>false</followSymlinks>
    </hudson.tasks.ArtifactArchiver>
    <hudson.tasks.BuildTrigger>
      <childProjects>{downstream}</childProjects>
      <threshold>
        <name>SUCCESS</name>
        <ordinal>0</ordinal>
        <color>BLUE</color>
        <completeBuild>true</completeBuild>
      </threshold>
    </hudson.tasks.BuildTrigger>
  </publishers>
  <buildWrappers>
    <hudson.plugins.timestamper.TimestamperBuildWrapper plugin="timestamper"/>
    <hudson.plugins.ws__cleanup.PreBuildCleanup plugin="ws-cleanup">
      <deleteDirs>false</deleteDirs>
      <cleanupParameter></cleanupParameter>
      <externalDelete></externalDelete>
      <disableDeferredWipeout>false</disableDeferredWipeout>
    </hudson.plugins.ws__cleanup.PreBuildCleanup>
  </buildWrappers>
</project>
""".replace("{downstream}", DOWNSTREAM_JOB)

# A minimal downstream job, so the BuildTrigger above names something real. Jenkins drops a
# trigger pointing at a job that does not exist, which would silently remove the very element the
# freestyle chain template needs to reproduce.
DOWNSTREAM_XML = """<?xml version='1.1' encoding='UTF-8'?>
<project>
  <description>Downstream target for the reference freestyle trigger.</description>
  <keepDependencies>false</keepDependencies>
  <properties>
    <io.jenkins.plugins.queueoptimizer.property.JobPriorityProperty>
      <level>HIGH</level>
      <dependsOn>reference-freestyle-payment-service</dependsOn>
    </io.jenkins.plugins.queueoptimizer.property.JobPriorityProperty>
  </properties>
  <scm class="hudson.scm.NullSCM"/>
  <assignedNode>linux</assignedNode>
  <canRoam>false</canRoam>
  <disabled>false</disabled>
  <triggers/>
  <builders>
    <hudson.tasks.Shell>
      <command>echo downstream</command>
    </hudson.tasks.Shell>
  </builders>
  <publishers/>
  <buildWrappers/>
</project>
"""

# Appendix F's shape, with the stage bodies taken from the catalog.
JENKINSFILE = """pipeline {
    agent { label 'linux' }
    options {
        dynamicQueuePriority(level: 'HIGH')
        timestamps()
        buildDiscarder(logRotator(numToKeepStr: '30'))
        timeout(time: 30, unit: 'MINUTES')
    }
    parameters {
        string(name: 'BRANCH', defaultValue: 'main', description: 'Branch to build')
        string(name: 'COMMIT', defaultValue: '', description: 'Commit SHA or empty for head')
    }
    stages {
        stage('Checkout') {
            steps {
                checkout([$class: 'GitSCM',
                          branches: [[name: params.COMMIT ?: params.BRANCH]],
                          userRemoteConfigs: [[url: 'https://github.com/uit-group04/payment-service.git']]])
            }
        }
        stage('Build') {
            steps { sh './scripts/build.sh' }
        }
        stage('Unit tests') {
            steps { sh './scripts/test.sh unit' }
        }
        stage('Deploy') {
            steps { sh './deploy.sh staging' }
        }
    }
    post {
        always { cleanWs() }
    }
}
"""


def pipeline_xml() -> str:
    """A Pipeline job wrapping the Jenkinsfile, with the script sandboxed (4.6.3)."""
    escaped = (
        JENKINSFILE.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )
    return f"""<?xml version='1.1' encoding='UTF-8'?>
<flow-definition plugin="workflow-job">
  <description>Reference Pipeline job: build, test and deploy payment-service to staging.</description>
  <keepDependencies>false</keepDependencies>
  <properties/>
  <definition class="org.jenkinsci.plugins.workflow.cps.CpsFlowDefinition" plugin="workflow-cps">
    <script>{escaped}</script>
    <sandbox>true</sandbox>
  </definition>
  <triggers/>
  <disabled>false</disabled>
</flow-definition>
"""


def create(name: str, xml: str, creds: tuple[str, str]) -> bool:
    call(f"/job/{name}/doDelete", creds, data=b"", headers=crumb(creds))
    status, body = call(
        "/createItem?name=" + urllib.parse.quote(name),
        creds,
        data=xml.encode("utf-8"),
        headers={"Content-Type": "application/xml; charset=utf-8", **crumb(creds)},
    )
    if status not in (200, 201):
        print(f"   create {name} -> {status}")
        print(f"   {body[:400]}")
        return False
    print(f"   created {name}")
    return True


def _with_header(body: str, header: str) -> str:
    """Insert the provenance comment after any XML declaration.

    Jenkins emits ``<?xml version="1.1" encoding="UTF-8"?>`` as the first line. XML requires that
    declaration to come first, so the comment follows it; a document without one simply gets the
    comment at the top.
    """
    match = re.match(r"^\s*<\?xml[^>]*\?>[ \t]*\r?\n?", body)
    if match is None:
        return header + body
    return body[: match.end()].rstrip("\r\n") + "\n" + header + body[match.end() :]


def export(name: str, filename: str, creds: tuple[str, str]) -> bool:
    status, body = call(f"/job/{name}/config.xml", creds)
    if status != 200:
        print(f"   export {name} -> {status}")
        return False
    target = OUTPUT_DIR / filename
    header = (
        "<!--\n"
        f"  Exported from jenkins-dev with GET /job/{name}/config.xml.\n"
        "\n"
        "  This is what Jenkins itself produced, not hand-written XML. BUILD_PROMPT rule 1.4:\n"
        "  every config.xml template is derived from a job created on jenkins-dev and exported,\n"
        "  never written from memory. Phase 5's Jinja2 templates are built from these files, and\n"
        "  the golden-file tests compare rendered output against them.\n"
        "\n"
        "  Regenerate with: python scripts/export_reference_configs.py\n"
        "-->\n"
    )
    # The comment goes *after* the XML declaration, never before it. A declaration must be the
    # first thing in the document, so a leading comment makes the file invalid XML -- which these
    # files were until 2026-10-07. That mattered: Phase 5's templates derive from them, the
    # golden-file tests compare parsed XML, and FakeJenkinsClient validates well-formedness, so
    # all three would have failed on a file that looked perfectly fine in an editor.
    target.write_text(_with_header(body, header), encoding="utf-8", newline="\n")
    print(f"   exported {filename} ({len(body)} bytes)")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep", action="store_true", help="leave the jobs on the controller")
    args = parser.parse_args()

    values = env()
    bot = (values.get("JENKINS_USER", "orchestrator-bot"), values.get("JENKINS_TOKEN", ""))
    if not bot[1]:
        raise SystemExit("JENKINS_TOKEN is empty; run `python scripts/bootstrap.py --token-only`")

    status, _ = call("/api/json?tree=mode", bot)
    if status != 200:
        raise SystemExit(f"jenkins-dev is not reachable at {JENKINS_URL} (status {status})")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("1. creating the reference jobs through the REST API")
    ok = create(DOWNSTREAM_JOB, DOWNSTREAM_XML, bot)
    ok = create(FREESTYLE_JOB, FREESTYLE_XML, bot) and ok
    ok = create(PIPELINE_JOB, pipeline_xml(), bot) and ok
    if not ok:
        return 1

    print("\n2. exporting what Jenkins stored")
    ok = export(FREESTYLE_JOB, "freestyle-build-test-deploy.config.xml", bot)
    ok = export(PIPELINE_JOB, "pipeline-build-test-deploy.config.xml", bot) and ok
    ok = export(DOWNSTREAM_JOB, "freestyle-downstream.config.xml", bot) and ok
    if not ok:
        return 1

    if not args.keep:
        print("\n3. removing the jobs from the controller")
        for name in (FREESTYLE_JOB, PIPELINE_JOB, DOWNSTREAM_JOB):
            call(f"/job/{name}/doDelete", bot, data=b"", headers=crumb(bot))
        print("   removed")

    print(f"\nreference configs written to {OUTPUT_DIR.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
