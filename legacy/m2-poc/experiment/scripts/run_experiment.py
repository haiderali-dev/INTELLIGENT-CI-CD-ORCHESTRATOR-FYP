#!/usr/bin/env python3
"""
Orchestrates one end-to-end experiment run against a local Jenkins instance:

  1. Launch `java -jar jenkins.war` with the given JENKINS_HOME and port.
  2. Wait for Jenkins to come up.
  3. POST the job-creation groovy template (jobs.json injected) to /scriptText.
  4. POST the trigger-jobs template (captures T0).
  5. Poll check-queue.groovy until the queue is empty and the executor idle.
  6. POST collect-metrics.groovy and save {label, t0, jobs:[...]} to --output.
  7. Shut Jenkins down.

Stdlib-only (urllib / json / subprocess) so it runs with a plain `python`.
"""

import argparse
import http.cookiejar
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

JENKINS_WAR = (
    r"C:\Users\haide\.m2\repository\org\jenkins-ci\main\jenkins-war"
    r"\2.479.3\jenkins-war-2.479.3.war"
)

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))


def log(msg):
    print(f"[run_experiment] {msg}", flush=True)


def make_opener():
    cj = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))


def wait_for_jenkins(opener, base, timeout=300):
    start = time.time()
    while time.time() - start < timeout:
        try:
            req = urllib.request.Request(base + "/login")
            with opener.open(req, timeout=5) as resp:
                if resp.status in (200, 403):
                    return
        except urllib.error.HTTPError as e:
            if e.code in (200, 403, 404):
                return
        except Exception:
            pass
        time.sleep(2)
    raise TimeoutError("Jenkins did not come up in time")


def get_crumb(opener, base):
    url = (base + "/crumbIssuer/api/json")
    try:
        with opener.open(url, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return data["crumbRequestField"], data["crumb"]
    except urllib.error.HTTPError:
        return None, None


def run_groovy_text(opener, base, crumb, script_text):
    data = urllib.parse.urlencode({"script": script_text}).encode("utf-8")
    req = urllib.request.Request(base + "/scriptText", data=data, method="POST")
    if crumb[0]:
        req.add_header(crumb[0], crumb[1])
    with opener.open(req, timeout=60) as resp:
        return resp.read().decode("utf-8")


def run_groovy_file(opener, base, crumb, script_path):
    with open(script_path, "r", encoding="utf-8") as f:
        script = f.read()
    return run_groovy_text(opener, base, crumb, script)


def run_groovy_template(opener, base, crumb, template_path, jobs_json_text):
    with open(template_path, "r", encoding="utf-8") as f:
        template = f.read()
    script = template.replace("__JOBS_JSON__", jobs_json_text)
    return run_groovy_text(opener, base, crumb, script)


def parse_queue_status(text):
    status = {}
    for line in text.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            status[k.strip()] = v.strip()
    return status


def wait_for_queue_drain(opener, base, crumb, check_script, timeout=1800,
                          snapshot_script=None, snapshots=None, t0=None):
    # Let the queue populate before we start checking for "drained".
    time.sleep(8)
    start = time.time()
    consecutive_idle = 0
    while time.time() - start < timeout:
        out = run_groovy_file(opener, base, crumb, check_script)
        status = parse_queue_status(out)
        qlen = int(status.get("QUEUE_LEN", "1"))
        busy = int(status.get("BUSY", "1"))
        log(f"queue check -> QUEUE_LEN={qlen} BUSY={busy}")

        if snapshot_script is not None and snapshots is not None:
            try:
                snap_out = run_groovy_file(opener, base, crumb, snapshot_script)
                elapsed = round((time.time() * 1000 - t0) / 1000.0, 2) if t0 else None
                snapshots.append({
                    "t": elapsed,
                    "queueLen": qlen,
                    "busy": busy,
                    "heap": json.loads(snap_out.strip()),
                })
            except Exception as e:
                log(f"snapshot capture failed (continuing): {e}")

        if qlen == 0 and busy == 0:
            consecutive_idle += 1
            if consecutive_idle >= 2:
                return
        else:
            consecutive_idle = 0
        time.sleep(5)
    raise TimeoutError("Queue did not drain in time")


def shutdown(opener, base, crumb, proc, timeout=60):
    try:
        data = b""
        req = urllib.request.Request(base + "/safeExit", data=data, method="POST")
        if crumb[0]:
            req.add_header(crumb[0], crumb[1])
        opener.open(req, timeout=10)
    except Exception as e:
        log(f"safeExit request failed (continuing): {e}")

    start = time.time()
    while time.time() - start < timeout:
        if proc.poll() is not None:
            log("Jenkins process exited")
            return
        time.sleep(2)

    log("Jenkins did not exit gracefully, terminating process tree")
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            capture_output=True,
        )
    else:
        proc.terminate()
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()


def get_crumb_safe(base):
    try:
        opener = make_opener()
        return get_crumb(opener, base)
    except Exception:
        return (None, None)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--home", required=True, help="JENKINS_HOME directory")
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--create-template", default=None,
                         help="Groovy template (with __JOBS_JSON__ placeholder) "
                              "that creates the 30 jobs")
    parser.add_argument("--skip-create", action="store_true",
                         help="Skip job (re)creation — reuse existing jobs/build "
                              "history already present in JENKINS_HOME")
    parser.add_argument("--trigger-template", default="trigger-jobs.groovy.tmpl")
    parser.add_argument("--jobs-json", default="jobs.json")
    parser.add_argument("--collect-script", default="collect-metrics.groovy")
    parser.add_argument("--check-script", default="check-queue.groovy")
    parser.add_argument("--snapshot-script", default=None,
                         help="Optional groovy script run on every queue-check "
                              "to capture live priority-heap state")
    parser.add_argument("--snapshot-output", default=None,
                         help="Where to write the JSON array of snapshots")
    parser.add_argument("--output", required=True)
    parser.add_argument("--log", required=True)
    args = parser.parse_args()

    if not args.skip_create and not args.create_template:
        parser.error("--create-template is required unless --skip-create is set")

    home = os.path.abspath(args.home)
    env = os.environ.copy()
    env["JENKINS_HOME"] = home

    base = f"http://localhost:{args.port}"

    jobs_json_path = os.path.join(SCRIPTS_DIR, args.jobs_json)
    with open(jobs_json_path, "r", encoding="utf-8") as f:
        jobs_spec = json.load(f)
    jobs_json_text = json.dumps(jobs_spec)

    log(f"Starting Jenkins for '{args.label}' on port {args.port}, JENKINS_HOME={home}")
    logf = open(args.log, "w", encoding="utf-8")
    proc = subprocess.Popen(
        ["java", "-jar", JENKINS_WAR, f"--httpPort={args.port}"],
        env=env,
        stdout=logf,
        stderr=subprocess.STDOUT,
        cwd=home,
    )

    try:
        opener = make_opener()

        log("Waiting for Jenkins to come up...")
        wait_for_jenkins(opener, base)
        log("Jenkins is up.")

        crumb = get_crumb(opener, base)

        if args.skip_create:
            log("Skipping job creation (--skip-create) — reusing existing jobs/history.")
        else:
            create_path = os.path.join(SCRIPTS_DIR, args.create_template)
            log(f"Creating {len(jobs_spec)} jobs via {args.create_template} ...")
            out = run_groovy_template(opener, base, crumb, create_path, jobs_json_text)
            log(out.strip())

        trigger_path = os.path.join(SCRIPTS_DIR, args.trigger_template)
        log("Triggering all jobs...")
        out = run_groovy_template(opener, base, crumb, trigger_path, jobs_json_text)
        log(out.strip())
        t0 = None
        for line in out.splitlines():
            if line.startswith("T0:"):
                t0 = int(line.split(":", 1)[1].strip())
        if t0 is None:
            raise RuntimeError("Failed to capture T0 from trigger script output")
        log(f"T0 = {t0}")

        check_path = os.path.join(SCRIPTS_DIR, args.check_script)
        snapshot_path = (os.path.join(SCRIPTS_DIR, args.snapshot_script)
                         if args.snapshot_script else None)
        snapshots = [] if snapshot_path else None

        log("Waiting for queue to drain...")
        wait_for_queue_drain(opener, base, crumb, check_path,
                              snapshot_script=snapshot_path,
                              snapshots=snapshots, t0=t0)
        log("Queue drained.")

        if snapshots is not None and args.snapshot_output:
            snap_out_path = os.path.abspath(args.snapshot_output)
            os.makedirs(os.path.dirname(snap_out_path), exist_ok=True)
            with open(snap_out_path, "w", encoding="utf-8") as f:
                json.dump(snapshots, f, indent=2)
            log(f"Wrote {len(snapshots)} score snapshots to {snap_out_path}")

        collect_path = os.path.join(SCRIPTS_DIR, args.collect_script)
        log("Collecting metrics...")
        out = run_groovy_file(opener, base, crumb, collect_path)
        jobs = json.loads(out)
        log(f"Collected {len(jobs)} job results")

        result = {"label": args.label, "t0": t0, "jobs": jobs}
        out_path = os.path.abspath(args.output)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        log(f"Wrote results to {out_path}")

    finally:
        log("Shutting down Jenkins...")
        shutdown(make_opener(), base, get_crumb_safe(base), proc)
        logf.close()


if __name__ == "__main__":
    sys.exit(main())
