"""``python -m experiment``: set up, warm up, run, analyse and report the v2 experiment (Part 4.8).

    python -m experiment setup  --controller plugin --workload freestyle-30 [--recreate]
    python -m experiment warmup --controller plugin --workload freestyle-30 --passes 3
    python -m experiment run    --controller plugin --workload freestyle-30 --executors 1 \\
                                --group main --repetition 1 [--seed 7] [--arm optimized]
    python -m experiment analyze experiment/results/<run folder>
    python -m experiment report [--out experiment/report]
    python -m experiment smoke                  T7.6: freestyle-6, 1 executor, both controllers
    python -m experiment smoke --controller stock    the same on the stock-Jenkins controller

The controllers are the Compose ``experiment`` profile's: ``baseline`` (8085, observe-only) and
``plugin`` (8086, optimized); the ``stock`` profile's ``stock`` (8088, Jenkins without the
plugin); or any other with ``--url``. experiment/README.md describes the matrix and how to prepare
each arm.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from experiment import harness, report, results, workload
from experiment.analyze import AnalysisError, analyze
from experiment.jenkins import (
    ADMIN_USER,
    BOT_USER,
    CONTROLLERS,
    JenkinsClient,
    JenkinsError,
    credentials,
)
from experiment.workload import WorkloadError

SMOKE_WORKLOAD = "freestyle-6"
#: The arm each controller must report for a smoke run: the control, the optimizer, no plugin.
SMOKE_ARMS = {"baseline": "observe-only", "plugin": "optimized", "stock": "stock"}
#: The controllers a smoke run uses unless told otherwise: T7.6's two.
SMOKE_DEFAULT = ("baseline", "plugin")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except (JenkinsError, WorkloadError, harness.HarnessError, AnalysisError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _client(args: argparse.Namespace, admin: bool = False) -> JenkinsClient:
    url = args.url or CONTROLLERS[args.controller]
    if admin:
        return JenkinsClient(url, credentials(ADMIN_USER, "JENKINS_ADMIN_PASSWORD"))
    return JenkinsClient(url, credentials(BOT_USER, "JENKINS_BOT_PASSWORD"))


def _setup(args: argparse.Namespace) -> int:
    loaded = workload.load(args.workload)
    admin = _client(args, admin=True) if args.recreate else None
    summary = harness.setup(_client(args), loaded, recreate=args.recreate, admin=admin)
    print(
        f"{loaded.name} on {args.controller or args.url}: {len(summary.created)} created, "
        f"{len(summary.kept)} kept, {len(summary.deleted)} deleted"
    )
    return 0


def _warmup(args: argparse.Namespace) -> int:
    harness.warmup(_client(args), workload.load(args.workload), args.passes)
    return 0


def _run(args: argparse.Namespace) -> int:
    folder = harness.run(
        _client(args),
        workload.load(args.workload),
        controller=args.controller or args.url,
        executors=args.executors,
        group=args.group,
        repetition=args.repetition,
        seed=args.seed,
        expect_arm=args.arm,
        expect_history=args.history,
    )
    print(folder)
    return 0


def _analyze(args: argparse.Namespace) -> int:
    for folder in args.runs:
        analysis = analyze(Path(folder))
        kpis = analysis["kpis"]
        print(f"{analysis['run']}: {kpis['dependency_violations']} dependency violation(s)")
    return 0


def _report(args: argparse.Namespace) -> int:
    written = report.write_report(results.run_folders(Path(args.results)), Path(args.out))
    for path in written:
        print(path)
    return 0


def _smoke(args: argparse.Namespace) -> int:
    """T7.6: freestyle-6, one executor, one repetition, on each controller, after setup. Without
    ``--controller``, on both experiment controllers."""
    loaded = workload.load(SMOKE_WORKLOAD)
    controllers = args.controller or list(SMOKE_DEFAULT)
    violations = 0
    for controller in controllers:
        client = JenkinsClient(
            CONTROLLERS[controller], credentials(BOT_USER, "JENKINS_BOT_PASSWORD")
        )
        harness.setup(client, loaded)
        folder = harness.run(
            client,
            loaded,
            controller=controller,
            executors=1,
            group="smoke",
            repetition=args.repetition,
            expect_arm=SMOKE_ARMS[controller],
        )
        analysis = results.read_json(folder / "analysis.json")
        violations += int(analysis["kpis"]["dependency_violations"])
        print(folder)
    print(f"smoke: {violations} dependency violation(s) across {', '.join(controllers)}")
    return 0 if violations == 0 else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m experiment", description=__doc__.splitlines()[0]
    )
    commands = parser.add_subparsers(dest="command", required=True)

    def controller(command: argparse.ArgumentParser) -> None:
        where = command.add_mutually_exclusive_group(required=True)
        where.add_argument("--controller", choices=sorted(CONTROLLERS))
        where.add_argument("--url", help="another controller's base URL")
        command.add_argument("--workload", required=True, help="freestyle-30, pipeline-30, ...")

    setup = commands.add_parser("setup", help="create the workload's missing jobs")
    controller(setup)
    setup.add_argument(
        "--recreate",
        action="store_true",
        help="delete every experiment job on the controller, and its history, first",
    )
    setup.set_defaults(handler=_setup)

    warm = commands.add_parser("warmup", help="run the workload to build history")
    controller(warm)
    warm.add_argument("--passes", type=int, default=3)
    warm.set_defaults(handler=_warmup)

    run = commands.add_parser("run", help="measure one repetition, then analyse it")
    controller(run)
    run.add_argument("--executors", type=int, required=True)
    run.add_argument("--group", required=True, help="main, cold-start, random-order, ...")
    run.add_argument("--repetition", type=int, default=1)
    run.add_argument("--seed", type=int, help="queue the jobs in this seeded shuffle")
    run.add_argument("--arm", choices=harness.ARMS, help="refuse to run unless the arm is this")
    run.add_argument("--history", choices=("warm", "fresh"), help="refuse unless the history is")
    run.set_defaults(handler=_run)

    again = commands.add_parser("analyze", help="analyse run folders again")
    again.add_argument("runs", nargs="+")
    again.set_defaults(handler=_analyze)

    out = commands.add_parser("report", help="table_12_1.md, runs.csv and the charts")
    out.add_argument("--results", default=str(results.RESULTS_DIR), help="the run folders' parent")
    out.add_argument("--out", default=str(report.REPORT_DIR))
    out.set_defaults(handler=_report)

    smoke = commands.add_parser("smoke", help="T7.6: freestyle-6 on both controllers")
    smoke.add_argument(
        "--controller",
        action="append",
        choices=sorted(SMOKE_ARMS),
        help="run on this controller instead; repeat for more (default: baseline and plugin)",
    )
    smoke.add_argument("--repetition", type=int, default=1)
    smoke.set_defaults(handler=_smoke)
    return parser


if __name__ == "__main__":
    sys.exit(main())
