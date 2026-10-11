#!/usr/bin/env python3
"""Acceptance check: a failing test stops the freestyle chain before deploy.

BUILD_PROMPT Phase 5 acceptance: "against ``demo/failing-tests`` the freestyle deploy job never
starts". The Phase 5 generator does not exist yet, so this assembles the chain 4.6 specifies by
hand -- ``build -> test -> deploy-staging``, each job triggering the next only on SUCCESS -- with
every job's XML *derived from* ``jenkins/reference-configs/freestyle-build-test-deploy.config.xml``
(rule 1.4) and every shell command taken from ``catalog/services.yaml``.

Two runs per service, because one alone proves nothing:

* **control** on ``main``: the deploy job must run. Without this, "deploy never started" could just
  mean the chain was wired wrong.
* **demo** on ``demo/failing-tests``: the test job must fail *on the intentional assertion* (checked
  in its log, so a missing dependency cannot pass for the expected failure) and the deploy job must
  never get a build.

Jobs are named ``acc-fs-<service>-*`` so they cannot collide with what the Phase 5 generator will
create. The bot token cannot delete jobs (D-033), so they are updated in place on reruns.

Usage:  python scripts/accept_failing_tests.py [--out DIR]
"""

from __future__ import annotations

import argparse
import base64
import http.cookiejar
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from xml.sax.saxutils import escape

REPO_ROOT = Path(__file__).resolve().parents[1]
JENKINS = "http://localhost:8087"
REFERENCE = REPO_ROOT / "jenkins" / "reference-configs" / "freestyle-build-test-deploy.config.xml"
SERVICES = {
    "payment-service": {
        "repo": "https://github.com/haiderali-dev/payment-service.git",
        "marker": "test_demo_failing_tests_fails_on_purpose",
    },
    "auth-service": {
        "repo": "https://github.com/haiderali-dev/auth-service.git",
        "marker": "demo/failing-tests: this test fails on purpose",
    },
}
TIMEOUT = 600


def catalog_commands(service: str) -> dict[str, str]:
    """build, unit test and staging deploy commands for a service, read from the catalog."""
    text = (REPO_ROOT / "catalog" / "services.yaml").read_text(encoding="utf-8")
    block = text.split(f"- name: {service}", 1)[1].split("\n  - name:", 1)[0]
    build = re.search(r'build_command:\s*"([^"]+)"', block)
    unit = re.search(r'- name: unit\s+command:\s*"([^"]+)"', block)
    deploy = re.search(r'staging:\s+command:\s*"([^"]+)"', block)
    if not (build and unit and deploy):
        raise SystemExit(f"could not read {service}'s commands from catalog/services.yaml")
    return {"build": build.group(1), "test": unit.group(1), "deploy": deploy.group(1)}


def job_xml(service: str, branch: str, commands: list[str], child: str | None, depends_on: str) -> str:
    """One chain job, derived from the reference export by substitution only."""
    xml = REFERENCE.read_text(encoding="utf-8")
    xml = xml.replace(
        "https://github.com/haiderali-dev/payment-service.git", SERVICES[service]["repo"]
    )
    # 4.6: branch and commit are written as parameter defaults on every chain job, because a
    # downstream trigger does not pass parameters on.
    xml = xml.replace(
        "<name>BRANCH</name>\n          <description>Branch to build</description>\n"
        "          <defaultValue>main</defaultValue>",
        "<name>BRANCH</name>\n          <description>Branch to build</description>\n"
        f"          <defaultValue>{escape(branch)}</defaultValue>",
    )
    # The reference export's branch spec is ${COMMIT:-${BRANCH}}, shell default syntax the Git
    # plugin does not support: it expands ${BRANCH} and leaves "${COMMIT:-main}" as a literal
    # revision, so every checkout fails with "Couldn't find any revision to build". Found by this
    # script's control run on 2026-10-11; the fix belongs in export_reference_configs.py before
    # Phase 5 derives templates from it (docs/decisions.md D-038). This check never sets COMMIT.
    xml = xml.replace("<name>${COMMIT:-${BRANCH}}</name>", "<name>${BRANCH}</name>")
    xml = xml.replace("<dependsOn></dependsOn>", f"<dependsOn>{escape(depends_on)}</dependsOn>")
    steps = "".join(
        f"\n    <hudson.tasks.Shell>\n      <command>{escape(c)}</command>\n"
        "      <configuredLocalRules/>\n    </hudson.tasks.Shell>"
        for c in commands
    )
    xml = re.sub(r"<builders>.*?</builders>", f"<builders>{steps}\n  </builders>", xml, flags=re.S)
    if child:
        xml = xml.replace(
            "<childProjects>reference-freestyle-downstream</childProjects>",
            f"<childProjects>{escape(child)}</childProjects>",
        )
    else:
        xml = re.sub(r"\s*<hudson\.tasks\.BuildTrigger>.*?</hudson\.tasks\.BuildTrigger>", "", xml, flags=re.S)
    # The provenance comment stays out of what Jenkins stores.
    return re.sub(r"<!--.*?-->\s*", "", xml, count=1, flags=re.S)


class Jenkins:
    def __init__(self, user: str, token: str) -> None:
        self.auth = "Basic " + base64.b64encode(f"{user}:{token}".encode()).decode()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )
        self.crumb: dict[str, str] | None = None

    def call(self, path: str, data: bytes | None = None, ctype: str | None = None) -> tuple[int, str]:
        request = urllib.request.Request(JENKINS + path, data=data)
        request.add_header("Authorization", self.auth)
        if data is not None:
            if self.crumb is None:
                _, body = self.call("/crumbIssuer/api/json")
                raw = json.loads(body)
                self.crumb = {raw["crumbRequestField"]: raw["crumb"]}
            for key, value in self.crumb.items():
                request.add_header(key, value)
            if ctype:
                request.add_header("Content-Type", ctype)
        try:
            with self.opener.open(request, timeout=60) as response:
                return response.status, response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", "replace")

    def put_job(self, name: str, xml: str) -> None:
        status, _ = self.call(f"/job/{name}/api/json")
        path = f"/job/{name}/config.xml" if status == 200 else f"/createItem?name={name}"
        status, body = self.call(path, xml.encode(), "application/xml")
        if status not in (200, 201):
            raise SystemExit(f"could not save {name}: {status} {body[:200]}")

    def last_build(self, name: str) -> int:
        status, body = self.call(f"/job/{name}/api/json?tree=lastBuild[number]")
        data = json.loads(body) if status == 200 else {}
        return int((data.get("lastBuild") or {}).get("number") or 0)

    def build(self, name: str, number: int) -> dict[str, object]:
        status, body = self.call(f"/job/{name}/{number}/api/json?tree=number,result,building,duration")
        return json.loads(body) if status == 200 else {}

    def log(self, name: str, number: int) -> str:
        return self.call(f"/job/{name}/{number}/consoleText")[1]


def wait_finished(jenkins: Jenkins, name: str, after: int) -> dict[str, object] | None:
    """The first build of ``name`` numbered above ``after``, once it has finished."""
    deadline = time.monotonic() + TIMEOUT
    while time.monotonic() < deadline:
        number = jenkins.last_build(name)
        if number > after:
            info = jenkins.build(name, number)
            if info and not info.get("building"):
                return info
        time.sleep(4)
    return None


def run_chain(jenkins: Jenkins, service: str, branch: str, label: str, out: Path) -> dict[str, object]:
    cmds = catalog_commands(service)
    names = {stage: f"acc-fs-{service}-{stage}" for stage in ("build", "test", "deploy-staging")}
    # Each job checks out into its own workspace, so the test job runs the catalog's build command
    # first to get its dependencies. Both commands come from the catalog; nothing is invented.
    jenkins.put_job(names["build"], job_xml(service, branch, [cmds["build"]], names["test"], ""))
    jenkins.put_job(
        names["test"],
        job_xml(service, branch, [cmds["build"], cmds["test"]], names["deploy-staging"], names["build"]),
    )
    jenkins.put_job(
        names["deploy-staging"], job_xml(service, branch, [cmds["deploy"]], None, names["test"])
    )

    before = {stage: jenkins.last_build(name) for stage, name in names.items()}
    status, _ = jenkins.call(
        f"/job/{names['build']}/buildWithParameters",
        urllib.parse.urlencode({"BRANCH": branch, "COMMIT": ""}).encode(),
        "application/x-www-form-urlencoded",
    )
    if status != 201:
        raise SystemExit(f"could not trigger {names['build']}: {status}")

    result: dict[str, object] = {"service": service, "branch": branch, "run": label, "jobs": {}}
    jobs: dict[str, object] = {}
    for stage in ("build", "test"):
        info = wait_finished(jenkins, names[stage], before[stage])
        jobs[stage] = info or {"result": "NEVER_FINISHED"}
        if info:
            log = jenkins.log(names[stage], int(info["number"]))
            (out / f"{label}-{service}-{stage}-{info['number']}.log").write_text(log, encoding="utf-8")
            if stage == "test":
                result["intentional_failure_in_log"] = SERVICES[service]["marker"] in log
        if not info or info.get("result") != "SUCCESS":
            break

    # Give a success-triggered deploy time to be queued and run, then look.
    deploy_info = wait_finished(jenkins, names["deploy-staging"], before["deploy-staging"]) if (
        jobs.get("test", {}).get("result") == "SUCCESS"  # type: ignore[union-attr]
    ) else None
    if deploy_info is None:
        time.sleep(20)  # a deploy that was going to be triggered would be queued by now
    after_deploy = jenkins.last_build(names["deploy-staging"])
    jobs["deploy-staging"] = deploy_info or {"result": "NOT_STARTED"}
    if deploy_info:
        log = jenkins.log(names["deploy-staging"], int(deploy_info["number"]))
        (out / f"{label}-{service}-deploy-staging-{deploy_info['number']}.log").write_text(log, encoding="utf-8")
    result["jobs"] = jobs
    result["deploy_started"] = after_deploy > before["deploy-staging"]
    return result


def credentials() -> tuple[str, str]:
    env = (REPO_ROOT / ".env").read_text(encoding="utf-8")
    user = re.search(r"^JENKINS_USER=(.*)$", env, re.M)
    token = re.search(r"^JENKINS_TOKEN=(.*)$", env, re.M)
    if not (user and token):
        raise SystemExit("JENKINS_USER and JENKINS_TOKEN are needed in .env")
    return user.group(1).strip(), token.group(1).strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "docs" / "evidence" / f"{stamp}-demo-failing-tests")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    jenkins = Jenkins(*credentials())

    results = []
    for service in SERVICES:
        for label, branch in (("control", "main"), ("demo", "demo/failing-tests")):
            print(f"-- {service} on {branch} ({label})", flush=True)
            outcome = run_chain(jenkins, service, branch, label, args.out)
            results.append(outcome)
            stages = ", ".join(f"{k}={v.get('result')}" for k, v in outcome["jobs"].items())  # type: ignore[union-attr]
            print(f"   {stages}; deploy started: {outcome['deploy_started']}", flush=True)

    verdicts = []
    for outcome in results:
        jobs = outcome["jobs"]
        if outcome["run"] == "control":
            ok = jobs["build"].get("result") == "SUCCESS" and jobs["test"].get("result") == "SUCCESS" and outcome["deploy_started"]  # type: ignore[index,union-attr]
            why = "control reached deploy" if ok else "control did NOT reach deploy, so the demo result would prove nothing"
        else:
            ok = (
                jobs["build"].get("result") == "SUCCESS"  # type: ignore[index,union-attr]
                and jobs["test"].get("result") == "FAILURE"  # type: ignore[index,union-attr]
                and bool(outcome.get("intentional_failure_in_log"))
                and not outcome["deploy_started"]
            )
            why = "test failed on the intentional assertion and deploy never started" if ok else "unexpected outcome"
        verdicts.append({"service": outcome["service"], "run": outcome["run"], "pass": ok, "why": why})

    summary = {"checked_at": datetime.now(UTC).isoformat(), "results": results, "verdicts": verdicts,
               "pass": all(v["pass"] for v in verdicts)}
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    for v in verdicts:
        print(f"[{'PASS' if v['pass'] else 'FAIL'}] {v['service']} {v['run']}: {v['why']}")
    print(f"evidence: {args.out.relative_to(REPO_ROOT)}")
    return 0 if summary["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
