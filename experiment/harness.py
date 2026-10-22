"""``setup``, ``warmup`` and ``run``: one workload on one controller, through REST only (Part 4.8).

The rules that fix Milestone 2's harness (Part 4.8.3):

- jobs are created once; ``setup --recreate`` replaces them, and warns that it wipes history;
- ``warmup`` is its own step: it runs the workload to build the history the estimator reads;
- ``run`` always analyses at the end, writes ``results/<time>-.../`` and updates ``latest.json``;
- every run records the plugin version, Jenkins version, executor count, workload digest and the
  configuration in force.

A run checks its conditions before it starts and refuses when one is wrong, rather than measuring
the wrong thing: the executor count (``AGENT_EXECUTORS``, set when the controller starts), the arm
the controller is configured as, that the jobs were made from this version of the workload, and
that the controller is idle.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Protocol

from experiment import results, templates
from experiment.analyze import analyze
from experiment.workload import JobSpec, Workload

#: observe-only: the plugin installed, ordering nothing (the control). optimized: the report's
#: algorithm. aging-off: optimized, with the aging bonus zeroed (the ablation). stock: no plugin.
ARMS: Final = ("observe-only", "optimized", "aging-off", "stock")
HEALTH_FIELDS: Final = ("lastSortDurationMillis", "heapSize", "cacheHitRate", "droppedMetricCount")
_GROUP: Final = re.compile(r"^[a-z0-9][a-z0-9-]*$")

Log = Callable[[str], None]


class HarnessError(RuntimeError):
    """A run or setup that must not go ahead, or that did not finish."""


class Clock(Protocol):
    """Time, injectable so that the tests need not wait."""

    def now_ms(self) -> int: ...

    def monotonic(self) -> float: ...

    def sleep(self, seconds: float) -> None: ...


class SystemClock:
    def now_ms(self) -> int:
        return time.time_ns() // 1_000_000

    def monotonic(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


class Controller(Protocol):
    """What the harness asks of a controller: ``jenkins.JenkinsClient``, or the tests' in-memory
    controller (``tests/fake_jenkins.py``)."""

    base_url: str

    def jenkins_version(self) -> str | None: ...

    def executors(self) -> dict[str, int]: ...

    def busy(self) -> tuple[int, int]: ...

    def dynamic_queue(self) -> dict[str, Any] | None: ...

    def health(self) -> dict[str, Any] | None: ...

    def recent_events(self) -> list[dict[str, Any]]: ...

    def jobs(self) -> dict[str, str]: ...

    def create_job(self, name: str, config_xml: str) -> None: ...

    def delete_job(self, name: str) -> None: ...

    def trigger(self, name: str) -> int | None: ...

    def last_builds(self) -> dict[str, tuple[int, bool]]: ...

    def build(self, name: str, number: int) -> dict[str, Any]: ...


def arm_of(dynamic_queue: dict[str, Any] | None) -> str:
    """Which arm the controller runs, read from the configuration the plugin reports."""
    if dynamic_queue is None:
        return "stock"
    config = dynamic_queue["configuration"]
    if not config["optimizerEnabled"]:
        return "observe-only"
    if float(config["agingBonusPerInterval"]) == 0 or float(config["agingCap"]) == 0:
        return "aging-off"
    return "optimized"


# ------------------------------------------------------------------------------------------------
# setup
# ------------------------------------------------------------------------------------------------


@dataclass
class SetupSummary:
    created: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)


def setup(
    client: Controller,
    loaded: Workload,
    recreate: bool = False,
    admin: Controller | None = None,
    log: Log = print,
) -> SetupSummary:
    """Create the workload's jobs that are missing. Existing ones are kept, never replaced.

    ``recreate`` deletes every experiment job on the controller, of every workload, with its
    history, and creates this workload afresh: the cold start of Part 4.8.2. History is
    controller-wide, because the estimator learns from every job on it, so deleting one
    workload's jobs alone would not make a cold start.
    """
    summary = SetupSummary()
    existing = client.jobs()
    if recreate:
        if admin is None:
            raise HarnessError("--recreate deletes jobs, which needs the admin account")
        log(
            "WARNING: --recreate deletes every experiment job on this controller, of every "
            "workload, and with them the build history the estimator learns from."
        )
        for name, description in sorted(existing.items()):
            if templates.marker(description) is not None:
                admin.delete_job(name)
                summary.deleted.append(name)
        existing = client.jobs()

    differing = [
        loaded.jenkins_name(spec.name)
        for spec in loaded.jobs
        if loaded.jenkins_name(spec.name) in existing
        and templates.marker(existing[loaded.jenkins_name(spec.name)])
        != (loaded.name, loaded.digest[:12])
    ]
    if differing:
        raise HarnessError(
            f"{len(differing)} job(s) exist but were not made from this version of {loaded.name}, "
            f"{differing[0]} first. setup --recreate replaces them, and wipes their history."
        )
    for spec in loaded.jobs:
        name = loaded.jenkins_name(spec.name)
        if name in existing:
            summary.kept.append(name)
        else:
            client.create_job(name, templates.render(loaded, spec))
            summary.created.append(name)
    return summary


def check_jobs(client: Controller, loaded: Workload) -> None:
    """Every job exists and was made from this version of the workload."""
    existing = client.jobs()
    for spec in loaded.jobs:
        name = loaded.jenkins_name(spec.name)
        if name not in existing:
            raise HarnessError(f"{name} does not exist on {client.base_url}: run setup first")
        if templates.marker(existing[name]) != (loaded.name, loaded.digest[:12]):
            raise HarnessError(
                f"{name} was made from another version of {loaded.name}: run setup --recreate"
            )


def wait_idle(
    client: Controller, clock: Clock, timeout_s: float = 600, poll_s: float = 2.0
) -> None:
    """Wait until no executor is busy and nothing is queued."""
    deadline = clock.monotonic() + timeout_s
    while True:
        busy, queued = client.busy()
        if busy == 0 and queued == 0:
            return
        if clock.monotonic() > deadline:
            raise HarnessError(
                f"{client.base_url} is not idle after {timeout_s:.0f} s: "
                f"{busy} executor(s) busy, {queued} item(s) queued"
            )
        clock.sleep(poll_s)


# ------------------------------------------------------------------------------------------------
# One pass of a workload: queue every job, then wait for every build
# ------------------------------------------------------------------------------------------------


@dataclass
class Pass:
    """What one pass recorded."""

    order: list[str]
    triggered_ms: dict[str, int]
    queue_items: dict[str, int | None]
    numbers: dict[str, int]
    events: list[dict[str, Any]]
    health: list[dict[str, Any]]
    started: datetime
    finished: datetime
    complete: bool
    reason: str | None = None


def _key(event: dict[str, Any]) -> tuple[str, ...]:
    """An event's identity: the same event is reported again on every poll."""
    parts = ("kind", "timestamp", "itemId", "jobName", "buildNumber")
    return tuple(str(event.get(part)) for part in parts)


def run_pass(
    client: Controller,
    loaded: Workload,
    order: list[JobSpec],
    clock: Clock,
    record_plugin: bool,
    timeout_s: float,
    poll_s: float = 1.0,
) -> Pass:
    """Queue every job in ``order`` at once, then poll until each has built once more."""
    names = [loaded.jenkins_name(spec.name) for spec in order]
    latest = client.last_builds()
    before = {name: latest.get(name, (0, False))[0] for name in names}
    seen = {_key(e) for e in client.recent_events()} if record_plugin else set()
    events: list[dict[str, Any]] = []
    health: list[dict[str, Any]] = []

    def collect() -> None:
        if not record_plugin:
            return
        for event in client.recent_events():
            key = _key(event)
            if key not in seen:
                seen.add(key)
                events.append(event)
        sample = client.health()
        if sample is not None:
            health.append({"t": clock.now_ms(), **{f: sample.get(f) for f in HEALTH_FIELDS}})

    started = datetime.now(UTC)
    triggered: dict[str, int] = {}
    items: dict[str, int | None] = {}
    for name in names:
        triggered[name] = clock.now_ms()
        items[name] = client.trigger(name)

    deadline = clock.monotonic() + timeout_s
    complete, reason = False, None
    while True:
        collect()
        latest = client.last_builds()
        done = [n for n in names if latest.get(n, (0, True))[0] > before[n] and not latest[n][1]]
        if len(done) == len(names):
            complete = True
            break
        if clock.monotonic() > deadline:
            unfinished = len(names) - len(done)
            reason = f"{unfinished} of {len(names)} builds unfinished after {timeout_s:.0f} s"
            break
        clock.sleep(poll_s)

    numbers = {name: latest.get(name, (0, False))[0] for name in names}
    extra = [name for name in names if complete and numbers[name] != before[name] + 1]
    if extra:
        complete, reason = False, f"{extra[0]} built more than once during the pass"
    if complete and record_plugin:
        # A build's BUILD_COMPLETED can land just after REST reports it finished (D-039's lesson).
        for _ in range(10):
            finished = {e.get("jobName") for e in events if e.get("kind") == "BUILD_COMPLETED"}
            if finished >= set(names):
                break
            clock.sleep(poll_s)
            collect()
    return Pass(
        order=names,
        triggered_ms=triggered,
        queue_items=items,
        numbers=numbers,
        events=events,
        health=health,
        started=started,
        finished=datetime.now(UTC),
        complete=complete,
        reason=reason,
    )


def pass_timeout(loaded: Workload) -> float:
    """Three times the workload's total sleep, plus ten minutes: generous on one executor."""
    return 3 * sum(spec.seconds for spec in loaded.jobs) + 600


# ------------------------------------------------------------------------------------------------
# warmup and run
# ------------------------------------------------------------------------------------------------


def warmup(
    client: Controller,
    loaded: Workload,
    passes: int,
    clock: Clock | None = None,
    log: Log = print,
) -> None:
    """Run the workload ``passes`` times, in its fixed order, to build history. Nothing is kept."""
    clock = clock or SystemClock()
    if passes < 1:
        raise HarnessError("warmup needs at least one pass")
    check_jobs(client, loaded)
    for number in range(1, passes + 1):
        wait_idle(client, clock)
        done = run_pass(
            client, loaded, loaded.submission_order(), clock, False, pass_timeout(loaded)
        )
        if not done.complete:
            raise HarnessError(f"warm-up pass {number}: {done.reason}")
        log(f"warm-up pass {number} of {passes}: {len(done.order)} builds")


def run(
    client: Controller,
    loaded: Workload,
    *,
    controller: str,
    executors: int,
    group: str,
    repetition: int = 1,
    seed: int | None = None,
    expect_arm: str | None = None,
    expect_history: str | None = None,
    results_dir: Path = results.RESULTS_DIR,
    clock: Clock | None = None,
    poll_s: float = 1.0,
    log: Log = print,
) -> Path:
    """Measure one repetition, analyse it, and return its folder."""
    clock = clock or SystemClock()
    if not _GROUP.match(group):
        raise HarnessError(f"group {group!r}: use lower-case letters, digits and dashes")
    found = client.executors()
    if sum(found.values()) != executors:
        raise HarnessError(
            f"{client.base_url} has {sum(found.values())} executor(s) online {found}, not "
            f"{executors}: restart its controller with AGENT_EXECUTORS={executors}"
        )
    dynamic_queue = client.dynamic_queue()
    arm = arm_of(dynamic_queue)
    if expect_arm and arm != expect_arm:
        raise HarnessError(f"{client.base_url} is configured as the {arm} arm, not {expect_arm}")
    check_jobs(client, loaded)
    wait_idle(client, clock)

    order = loaded.submission_order(seed)
    latest = client.last_builds()
    prior = [latest.get(loaded.jenkins_name(spec.name), (0, False))[0] for spec in order]
    history = "fresh" if max(prior) == 0 else "warm"
    if expect_history and history != expect_history:
        raise HarnessError(f"the jobs' history is {history}, not {expect_history}")
    health = client.health() if dynamic_queue is not None else None

    log(f"{controller} ({arm}, {executors} executor(s)): {loaded.name}, {group} r{repetition}")
    done = run_pass(
        client, loaded, order, clock, dynamic_queue is not None, pass_timeout(loaded), poll_s
    )
    name = results.run_folder_name(done.started, group, loaded.name, arm, executors, repetition)
    folder = results_dir / name
    folder.mkdir(parents=True, exist_ok=False)
    builds = (
        {n: client.build(n, number) for n, number in done.numbers.items()} if done.complete else {}
    )

    results.write_jsonl(folder / "events.jsonl", done.events)
    results.write_json(folder / "builds.json", builds)
    results.write_jsonl(folder / "health.jsonl", done.health)
    results.write_json(
        folder / "run.json",
        {
            "group": group,
            "repetition": repetition,
            "controller": controller,
            "url": client.base_url,
            "arm": arm,
            "executors": executors,
            "executorsByAgent": found,
            "workload": {"name": loaded.name, "digest": loaded.digest, "source": loaded.source},
            "order": {"seed": seed, "jobs": done.order},
            "history": {"kind": history, "priorBuilds": {"min": min(prior), "max": max(prior)}},
            "jenkinsVersion": client.jenkins_version(),
            "pluginVersion": (health or {}).get("pluginVersion"),
            "pluginBuild": (health or {}).get("pluginBuild"),
            "configuration": dynamic_queue["configuration"] if dynamic_queue else None,
            "harness": {"pollSeconds": poll_s},
            "startedAt": done.started.isoformat(timespec="seconds"),
            "finishedAt": done.finished.isoformat(timespec="seconds"),
            "complete": done.complete,
            "incompleteReason": done.reason,
            "triggeredMs": done.triggered_ms,
            "queueItems": done.queue_items,
            "buildNumbers": done.numbers,
        },
    )
    if not done.complete:
        raise HarnessError(f"{name}: {done.reason}; its raw files are kept for a look")
    analysis = analyze(folder)
    kpis = analysis["kpis"]
    log(
        f"{name}: makespan {kpis['makespan_s']} s, mean wait {kpis['wait_s']['mean']} s, "
        f"{kpis['dependency_violations']} dependency violation(s)"
    )
    return folder
