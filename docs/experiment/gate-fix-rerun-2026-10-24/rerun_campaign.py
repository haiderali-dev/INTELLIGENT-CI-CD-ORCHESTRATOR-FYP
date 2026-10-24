"""The targeted re-run after DF-48's fix (D-080), approved by the user on 2026-10-24.

    python rerun_campaign.py plan <plugin build>
    python rerun_campaign.py run  <plugin build>

pipeline-30 on 3 executors, three repetitions, and random order (mixed-30, 3 executors, seeds 1
and 2), both arms, on experiment controllers that must report <plugin build>, the commit the fixed
plugin was built from, before anything is measured. The groups are `main-rerun` and
`random-order-rerun`, so the runs never mix with the matrix's.

Everything else is matrix_campaign.py's, unchanged: resuming, the mains-power check before each
measured run, keeping Windows awake, the controller changes, and stopping the default stack for
the runs and starting it again at the end. Its state lives in .tmp/rerun.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import matrix_campaign as mc  # noqa: E402

mc.STATE = mc.REPO / ".tmp" / "rerun"
mc.PROGRESS = mc.STATE / "progress.jsonl"
mc.CAMPAIGN = mc.STATE / "campaign.json"
mc.LOG = mc.STATE / "campaign.log"

WORKLOADS = ("pipeline-30", "mixed-30")
CONTROLLERS = ("baseline", "plugin")


def plan(build: str) -> list[mc.Step]:
    step = mc.Step
    steps = [
        step("stop-default-stack", "stop the default stack and the staged sample services",
             [mc.compose("stop", *mc.DEFAULT_STACK), ["docker", "stop", *mc.STAGED]], timeout=600),
        step("stock-stop", "stop the stock controller, which nothing here needs",
             action="stock:stop"),
        step("executors-3", "both experiment controllers on 3 executors", action="executors:3"),
        step("plugin-build", f"both controllers run the fixed plugin, build {build[:7]}",
             action=f"build:{build}"),
    ]
    for workload in WORKLOADS:
        steps.append(step(f"setup-{workload}", f"set up {workload} on baseline and plugin",
                          [mc.exp("setup", "--controller", c, "--workload", workload)
                           for c in CONTROLLERS], timeout=600))
        for number in (1, 2, 3):
            steps.append(step(f"warmup-{workload}-{number}",
                              f"warm-up pass {number} of 3, {workload}, on baseline and plugin",
                              [mc.exp("warmup", "--controller", c, "--workload", workload,
                                      "--passes", "1") for c in CONTROLLERS], parallel=True))
    for rep in (1, 2, 3):
        for controller in CONTROLLERS:
            steps.append(mc.run_step("main-rerun", "pipeline-30", 3, rep, controller))
    for seed in (1, 2):
        for controller in CONTROLLERS:
            steps.append(mc.run_step("random-order-rerun", "mixed-30", 3, 1, controller, seed=seed))
    steps += [
        step("executors-1", "both experiment controllers back on 1 executor",
             action="executors:1"),
        step("restore-stack", "start the default stack and the staged services",
             [mc.compose("up", "-d", "--wait", "--wait-timeout", "600", *mc.DEFAULT_STACK),
              ["docker", "start", *mc.STAGED]], timeout=900),
        step("stock-start-end", "the stock controller up again", action="stock:start"),
    ]
    return steps


matrix_act = mc.act


def act(step: mc.Step, log: Path) -> None:
    kind, _, value = (step.action or "").partition(":")
    if kind != "build":
        matrix_act(step, log)
        return
    for name in CONTROLLERS:
        found = str((mc.client(name).health() or {}).get("pluginBuild"))
        if not found.startswith(value):
            raise RuntimeError(f"{name} runs plugin build {found}, not {value}")


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in ("plan", "run"):
        sys.exit(__doc__)
    fixed = sys.argv[2]
    mc.plan = lambda: plan(fixed)
    mc.act = act
    sys.exit(mc.run_campaign() if sys.argv[1] == "run" else mc.show_plan())
