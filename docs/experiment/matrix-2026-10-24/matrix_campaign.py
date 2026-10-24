"""Run Part 4.8.2's matrix, step by step and resumably, with `python -m experiment`.

    python matrix_campaign.py plan     the steps, with what is done
    python matrix_campaign.py run      run every step not yet done, in order

A step that fails stops the campaign, for a person to look at. A measured run counts as done when
experiment/results holds a complete, analysed run of its condition started during this campaign,
so a step cut short runs again and a finished one never runs twice. Every other step is done once
it has succeeded. Before each measured run the laptop must be on mains power (BatteryStatus 2),
and while the campaign runs Windows is asked not to sleep.

The order (experiment/README.md): set up and warm every workload, the warm-ups of different
controllers in parallel since nothing is measured; then the measured runs one at a time, the two
arms of a repetition back to back: the main group on 1 executor, the aging ablation, the stock
sanity run, the main group and the random order on 3 executors, and cold start last, because
`setup --recreate` deletes the warm history every other group needs.

The default stack is stopped for the campaign, so that only the controllers measured run, and
started again at its end, as is the stock profile.
"""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(r"D:/FYP POC/CICD project - Copy")
STATE = REPO / ".tmp" / "matrix"
PROGRESS = STATE / "progress.jsonl"
CAMPAIGN = STATE / "campaign.json"
LOG = STATE / "campaign.log"
sys.path.insert(0, str(REPO))

from experiment import harness, results  # noqa: E402
from experiment.jenkins import BOT_USER, CONTROLLERS, JenkinsClient, credentials  # noqa: E402

MAIN = ("freestyle-30", "pipeline-30", "mixed-30")
ARM = {"baseline": "observe-only", "plugin": "optimized", "stock": "stock"}
PLUGIN_CASC = REPO / "jenkins" / "casc" / "experiment-plugin.yaml"
AGING_ON = b'    agingBonusPerInterval: "0.05"\n    agingCap: "0.15"\n'
AGING_OFF = b'    agingBonusPerInterval: "0.0"\n    agingCap: "0.0"\n'
DEFAULT_STACK = ("postgres", "jenkins-dev", "agent-1", "agent-2", "backend", "frontend")
STAGED = ("auth-service-staging", "payment-service-staging")


@dataclass
class Step:
    id: str
    title: str
    commands: list[list[str]] = field(default_factory=list)
    parallel: bool = False
    env: dict[str, str] = field(default_factory=dict)
    condition: tuple | None = None  # a measured run: (controller, group, workload, executors, rep, seed, arm, history)
    action: str | None = None  # executors:N, aging:on|off, stock:start|stop
    timeout: int = 2400


def exp(*args: str) -> list[str]:
    return [sys.executable, "-m", "experiment", *args]


def compose(*args: str) -> list[str]:
    return ["docker", "compose", *args]


def run_step(group: str, workload: str, executors: int, rep: int, controller: str,
             seed: int | None = None, arm: str | None = None, history: str = "warm") -> Step:
    arm = arm or ARM[controller]
    command = exp("run", "--controller", controller, "--workload", workload, "--executors",
                  str(executors), "--group", group, "--repetition", str(rep), "--arm", arm,
                  "--history", history)
    if seed is not None:
        command += ["--seed", str(seed)]
    where = f"seed{seed}" if seed is not None else f"r{rep}"
    return Step(
        id=f"{group}-{workload}-{executors}x-{arm}-{where}",
        title=f"{group}: {workload}, {executors} executor(s), {arm}, "
        + (f"seed {seed}" if seed is not None else f"repetition {rep}"),
        commands=[command],
        condition=(controller, group, workload, executors, rep, seed, arm, history),
    )


def plan() -> list[Step]:
    steps = [
        Step("stop-default-stack", "stop the default stack and the staged sample services",
             [compose("stop", *DEFAULT_STACK), ["docker", "stop", *STAGED]], timeout=600),
        Step("executors-1", "both experiment controllers on 1 executor", action="executors:1"),
        Step("stock-start", "the stock controller up, for its set-up and warm-up", action="stock:start"),
    ]
    for workload in MAIN:
        steps.append(Step(f"setup-{workload}", f"set up {workload} on baseline and plugin",
                          [exp("setup", "--controller", c, "--workload", workload)
                           for c in ("baseline", "plugin")], timeout=600))
    steps.append(Step("setup-stock", "set up freestyle-30 on stock",
                      [exp("setup", "--controller", "stock", "--workload", "freestyle-30")],
                      timeout=600))
    for workload in MAIN:
        controllers = ["baseline", "plugin"] + (["stock"] if workload == "freestyle-30" else [])
        for number in (1, 2, 3):
            steps.append(Step(
                f"warmup-{workload}-{number}", f"warm-up pass {number} of 3, {workload}, on "
                + ", ".join(controllers),
                [exp("warmup", "--controller", c, "--workload", workload, "--passes", "1")
                 for c in controllers], parallel=True))
    steps.append(Step("stock-stop", "stop the stock controller until its sanity run",
                      action="stock:stop"))
    for workload in MAIN:
        for rep in (1, 2, 3):
            for controller in ("baseline", "plugin"):
                steps.append(run_step("main", workload, 1, rep, controller))
    for rep in (1, 2, 3):
        steps.append(run_step("aging-ablation", "freestyle-30", 1, rep, "plugin"))
    steps.append(Step("aging-off", "plugin controller: aging bonus and cap at 0.0",
                      action="aging:off"))
    for rep in (1, 2, 3):
        steps.append(run_step("aging-ablation", "freestyle-30", 1, rep, "plugin", arm="aging-off"))
    steps.append(Step("aging-on", "plugin controller: its configuration file restored",
                      action="aging:on"))
    steps.append(Step("stock-start-sanity", "the stock controller up for its sanity run",
                      action="stock:start"))
    steps.append(run_step("sanity", "freestyle-30", 1, 1, "stock"))
    steps.append(Step("stock-stop-sanity", "stop the stock controller", action="stock:stop"))
    steps.append(Step("executors-3", "both experiment controllers on 3 executors",
                      action="executors:3"))
    for workload in MAIN:
        for rep in (1, 2, 3):
            for controller in ("baseline", "plugin"):
                steps.append(run_step("main", workload, 3, rep, controller))
    for seed in (1, 2):
        for controller in ("baseline", "plugin"):
            steps.append(run_step("random-order", "mixed-30", 3, 1, controller, seed=seed))
    steps.append(Step("executors-1-again", "both experiment controllers back on 1 executor",
                      action="executors:1"))
    for rep in (1, 2, 3):
        for controller in ("baseline", "plugin"):
            step = run_step("cold-start", "freestyle-30", 1, rep, controller, history="fresh")
            # Every cold-start repetition starts from no history: --recreate deletes every
            # experiment job on the controller first. In the same step, so a retry recreates too.
            step.commands.insert(0, exp("setup", "--controller", controller, "--workload",
                                        "freestyle-30", "--recreate"))
            steps.append(step)
    steps.append(Step("report", "python -m experiment report", [exp("report")], timeout=600))
    steps.append(Step("restore-stack", "start the default stack, the staged services and stock",
                      [compose("up", "-d", "--wait", "--wait-timeout", "600", *DEFAULT_STACK),
                       ["docker", "start", *STAGED]], timeout=900))
    steps.append(Step("stock-start-end", "the stock controller up again", action="stock:start"))
    return steps


# ------------------------------------------------------------------------------------------------


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def say(line: str) -> None:
    text = f"{datetime.now().strftime('%H:%M:%S')} {line}"
    print(text, flush=True)
    with LOG.open("a", encoding="utf-8") as log:
        log.write(text + "\n")


def done_ids() -> set[str]:
    if not PROGRESS.is_file():
        return set()
    return {json.loads(line)["id"] for line in PROGRESS.read_text(encoding="utf-8").splitlines()
            if line.strip() and json.loads(line)["status"] == "done"}


def record(step: Step, status: str, started: float, detail: str = "") -> None:
    with PROGRESS.open("a", encoding="utf-8") as out:
        out.write(json.dumps({"id": step.id, "status": status, "at": now(),
                              "seconds": round(time.monotonic() - started, 1),
                              "detail": detail}) + "\n")


def campaign_start() -> str:
    if not CAMPAIGN.is_file():
        CAMPAIGN.write_text(json.dumps({"started": now()}), encoding="utf-8")
    return str(json.loads(CAMPAIGN.read_text(encoding="utf-8"))["started"])


def finished_run(condition: tuple, since: str) -> Path | None:
    controller, group, workload, executors, rep, seed, arm, _history = condition
    for folder in results.run_folders():
        meta = results.read_json(folder / "run.json")
        found = (meta.get("controller"), meta.get("group"), meta["workload"]["name"],
                 meta.get("executors"), meta.get("repetition"), meta["order"]["seed"],
                 meta.get("arm"))
        if (found == (controller, group, workload, executors, rep, seed, arm)
                and str(meta.get("startedAt", "")) >= since and meta.get("complete")
                and (folder / "analysis.json").is_file()):
            return folder
    return None


def battery_status() -> str:
    out = subprocess.run(["powershell.exe", "-NoProfile", "-Command",
                          "(Get-CimInstance Win32_Battery).BatteryStatus"],
                         capture_output=True, text=True, timeout=60, check=False)
    return out.stdout.strip()


def client(name: str) -> JenkinsClient:
    return JenkinsClient(CONTROLLERS[name], credentials(BOT_USER, "JENKINS_BOT_PASSWORD"))


def wait_for(check, what: str, timeout: float = 420) -> None:
    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        try:
            ok, last = check()
            if ok:
                return
        except Exception as exc:  # the controller is still starting
            last = f"{type(exc).__name__}: {exc}"
        time.sleep(5)
    raise RuntimeError(f"{what} not reached after {timeout:.0f} s: {last}")


def executors_on(names: tuple[str, ...], count: int) -> None:
    def check() -> tuple[bool, str]:
        found = {name: sum(client(name).executors().values()) for name in names}
        return all(n == count for n in found.values()), str(found)
    wait_for(check, f"{count} executor(s) online on {', '.join(names)}")


def arm_is(name: str, arm: str) -> None:
    def check() -> tuple[bool, str]:
        found = harness.arm_of(client(name).dynamic_queue())
        return found == arm, found
    wait_for(check, f"{name} configured as {arm}")


def shell(commands: list[list[str]], parallel: bool, env: dict[str, str], log: Path,
          timeout: int) -> int:
    environment = {**os.environ, **env}
    with log.open("a", encoding="utf-8") as out:
        if parallel:
            processes = [subprocess.Popen(command, cwd=REPO, env=environment, stdout=out,
                                          stderr=subprocess.STDOUT) for command in commands]
            codes = [process.wait(timeout=timeout) for process in processes]
            return max(codes)
        for command in commands:
            out.write("$ " + " ".join(command) + "\n")
            out.flush()
            code = subprocess.run(command, cwd=REPO, env=environment, stdout=out,
                                  stderr=subprocess.STDOUT, timeout=timeout,
                                  check=False).returncode
            if code:
                return code
    return 0


def act(step: Step, log: Path) -> None:
    kind, _, value = (step.action or "").partition(":")
    if kind == "executors":
        command = compose("--profile", "experiment", "up", "-d", "--force-recreate", "--no-deps",
                          "--wait", "--wait-timeout", "600", "jenkins-baseline", "jenkins-plugin")
        if shell([command], False, {"AGENT_EXECUTORS": value}, log, 900):
            raise RuntimeError("recreating the experiment controllers failed")
        executors_on(("baseline", "plugin"), int(value))
        arm_is("baseline", "observe-only")
        arm_is("plugin", "optimized")
    elif kind == "stock" and value == "start":
        command = compose("--profile", "stock", "up", "-d", "--wait", "--wait-timeout", "600",
                          "jenkins-stock", "stock-agent")
        if shell([command], False, {"AGENT_EXECUTORS": "1"}, log, 900):
            raise RuntimeError("starting the stock controller failed")
        executors_on(("stock",), 1)
        arm_is("stock", "stock")
    elif kind == "stock" and value == "stop":
        if shell([compose("--profile", "stock", "stop", "jenkins-stock", "stock-agent")], False,
                 {}, log, 600):
            raise RuntimeError("stopping the stock controller failed")
    elif kind == "aging":
        data = PLUGIN_CASC.read_bytes()
        old, new = (AGING_ON, AGING_OFF) if value == "off" else (AGING_OFF, AGING_ON)
        if data.count(new) == 1 and data.count(old) == 0:
            pass  # already as wanted: a retry
        elif data.count(old) == 1:
            PLUGIN_CASC.write_bytes(data.replace(old, new))
        else:
            raise RuntimeError(f"{PLUGIN_CASC.name} does not hold the aging lines as expected")
        if value == "on":
            diff = subprocess.run(["git", "diff", "--quiet", "--", str(PLUGIN_CASC)], cwd=REPO,
                                  check=False)
            if diff.returncode != 0:
                raise RuntimeError(f"{PLUGIN_CASC.name} differs from git after restoring it")
        command = compose("--profile", "experiment", "up", "-d", "--force-recreate", "--no-deps",
                          "--wait", "--wait-timeout", "600", "jenkins-plugin")
        if shell([command], False, {"AGENT_EXECUTORS": "1"}, log, 900):
            raise RuntimeError("recreating jenkins-plugin failed")
        executors_on(("plugin",), 1)
        arm_is("plugin", "aging-off" if value == "off" else "optimized")
    else:
        raise RuntimeError(f"unknown action {step.action}")


def run_campaign() -> int:
    STATE.mkdir(parents=True, exist_ok=True)
    (STATE / "steps").mkdir(exist_ok=True)
    since = campaign_start()
    # Keep Windows awake while this process lives: ES_CONTINUOUS | ES_SYSTEM_REQUIRED.
    ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)
    steps = plan()
    done = done_ids()
    say(f"CAMPAIGN since {since}: {len(steps)} steps, {len(done)} done")
    for number, step in enumerate(steps, 1):
        if step.id in done:
            continue
        log = STATE / "steps" / f"{number:02d}-{step.id}.log"
        started = time.monotonic()
        if step.condition:
            folder = finished_run(step.condition, since)
            if folder:
                record(step, "done", started, f"already in {folder.name}")
                say(f"DONE {number}/{len(steps)} {step.id}: already in {folder.name}")
                continue
            power = battery_status()
            if power != "2":
                say(f"STOP before {step.id}: BatteryStatus {power}, not mains power")
                return 3
        say(f"STEP {number}/{len(steps)} {step.id}: {step.title}")
        try:
            if step.action:
                act(step, log)
            elif shell(step.commands, step.parallel, step.env, log, step.timeout):
                raise RuntimeError(f"a command exited non-zero; see {log.name}")
            if step.condition:
                folder = finished_run(step.condition, since)
                if folder is None:
                    raise RuntimeError(f"no complete, analysed run found; see {log.name}")
                analysis = results.read_json(folder / "analysis.json")["kpis"]
                detail = (f"{folder.name}: makespan {analysis['makespan_s']} s, mean wait "
                          f"{analysis['wait_s']['mean']} s, "
                          f"{analysis['dependency_violations']} violation(s)")
            else:
                detail = ""
        except Exception as exc:
            record(step, "failed", started, str(exc))
            say(f"FAIL {number}/{len(steps)} {step.id} after "
                f"{time.monotonic() - started:.0f} s: {exc}")
            return 1
        record(step, "done", started, detail)
        say(f"DONE {number}/{len(steps)} {step.id} in {time.monotonic() - started:.0f} s"
            + (f": {detail}" if detail else ""))
    say("CAMPAIGN COMPLETE")
    return 0


def show_plan() -> int:
    done = done_ids()
    steps = plan()
    measured = sum(1 for s in steps if s.condition)
    for number, step in enumerate(steps, 1):
        mark = "x" if step.id in done else " "
        print(f"[{mark}] {number:02d} {step.id}: {step.title}")
    print(f"\n{len(steps)} steps, {measured} measured runs, {len(done)} done")
    return 0


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "plan"
    sys.exit(run_campaign() if command == "run" else show_plan())
