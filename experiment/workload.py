"""Workloads: the jobs a run submits, with their bands, durations and dependencies (Part 4.8.1).

A workload file names its jobs as Milestone 2 did and gives them a prefix on the controller, so
that ``freestyle-30`` and ``pipeline-30`` can hold the same 30 jobs side by side: a Jenkins job
name belongs to one job type only.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

#: Submission order of the bands: LOW first and HIGH last, the order that makes FIFO run urgent
#: work last (Part 4.8.2).
LEVELS: Final = ("LOW", "MEDIUM", "HIGH")
TYPES: Final = ("freestyle", "pipeline")
WORKLOADS_DIR: Final = Path(__file__).resolve().parent / "workloads"
#: The longest a job may sleep. Milestone 2's longest is 25 s; a typo of 2500 should fail loudly.
MAX_SECONDS: Final = 600

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_PREFIX = re.compile(r"^[a-z0-9]+-$")


class WorkloadError(ValueError):
    """A workload file that cannot be run as written."""


@dataclass(frozen=True)
class JobSpec:
    """One job of a workload, under the name the workload gives it."""

    name: str
    job_type: str
    level: str
    seconds: int
    depends_on: tuple[str, ...]


@dataclass(frozen=True)
class Workload:
    """A validated workload: its jobs in file order, and a digest of the file's content.

    ``source`` is that content as canonical JSON. A run records it, so the run can be analysed
    again later from what it actually ran, whatever the workload file says by then.
    """

    name: str
    description: str
    prefix: str
    jobs: tuple[JobSpec, ...]
    digest: str
    source: str = field(default="", compare=False, repr=False)

    def jenkins_name(self, name: str) -> str:
        """The job's name on the controller: the workload's prefix, then the job's own name."""
        return self.prefix + name

    def job(self, name: str) -> JobSpec:
        for spec in self.jobs:
            if spec.name == name:
                return spec
        raise KeyError(name)

    @property
    def edges(self) -> tuple[tuple[str, str], ...]:
        """Every dependency as (upstream, downstream), in file order."""
        return tuple((upstream, spec.name) for spec in self.jobs for upstream in spec.depends_on)

    def submission_order(self, seed: int | None = None) -> list[JobSpec]:
        """The order a run triggers the jobs in.

        Without a seed: LOW, then MEDIUM, then HIGH, each band in file order, as Milestone 2
        submitted them. With one: a shuffle of every job, the same shuffle for the same seed
        (Part 4.8.2's random-order group). A run records the order it used either way.
        """
        if seed is None:
            return sorted(self.jobs, key=lambda spec: LEVELS.index(spec.level))
        shuffled = list(self.jobs)
        random.Random(seed).shuffle(shuffled)  # noqa: S311 - an experiment's order, not a secret
        return shuffled


def load(name_or_path: str | Path) -> Workload:
    """Load and validate a workload, by name (``freestyle-30``) or by path."""
    path = Path(name_or_path)
    if path.suffix != ".json":
        path = WORKLOADS_DIR / f"{name_or_path}.json"
    if not path.is_file():
        known = ", ".join(sorted(p.stem for p in WORKLOADS_DIR.glob("*.json")))
        raise WorkloadError(f"no workload {name_or_path!r}; known: {known}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise WorkloadError(f"{path.name}: not valid JSON ({exc})") from exc
    return parse(data)


def parse(data: dict[str, Any]) -> Workload:
    """Validate a workload's parsed JSON and build it."""
    for key in ("name", "description", "prefix", "jobs"):
        if key not in data:
            raise WorkloadError(f"missing {key!r}")
    name, prefix = str(data["name"]), str(data["prefix"])
    if not _PREFIX.match(prefix):
        raise WorkloadError(
            f"{name}: prefix {prefix!r} must be lower-case letters or digits and a dash"
        )
    jobs = tuple(_job(name, raw) for raw in data["jobs"])
    if not jobs:
        raise WorkloadError(f"{name}: no jobs")
    names = [spec.name for spec in jobs]
    duplicates = sorted({n for n in names if names.count(n) > 1})
    if duplicates:
        raise WorkloadError(f"{name}: duplicate job names {duplicates}")
    known = set(names)
    for spec in jobs:
        for upstream in spec.depends_on:
            if upstream == spec.name:
                raise WorkloadError(f"{name}: {spec.name} depends on itself")
            if upstream not in known:
                raise WorkloadError(
                    f"{name}: {spec.name} depends on {upstream!r}, not in the workload"
                )
    _refuse_cycles(name, jobs)
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    digest = hashlib.sha256(canonical.encode("ascii")).hexdigest()
    description = str(data["description"])
    return Workload(
        name=name,
        description=description,
        prefix=prefix,
        jobs=jobs,
        digest=digest,
        source=canonical,
    )


def _job(workload: str, raw: dict[str, Any]) -> JobSpec:
    name = str(raw.get("name", ""))
    if not _NAME.match(name):
        raise WorkloadError(f"{workload}: job name {name!r} is not a plain Jenkins job name")
    job_type, level, seconds = raw.get("type"), raw.get("level"), raw.get("seconds")
    if job_type not in TYPES:
        raise WorkloadError(f"{workload}: {name}: type must be one of {TYPES}")
    if level not in LEVELS:
        raise WorkloadError(f"{workload}: {name}: level must be one of {LEVELS}")
    if not isinstance(seconds, int) or isinstance(seconds, bool) or not 1 <= seconds <= MAX_SECONDS:
        raise WorkloadError(
            f"{workload}: {name}: seconds must be a whole number from 1 to {MAX_SECONDS}"
        )
    depends_on = raw.get("dependsOn", [])
    if not isinstance(depends_on, list) or not all(isinstance(up, str) for up in depends_on):
        raise WorkloadError(f"{workload}: {name}: dependsOn must be a list of job names")
    return JobSpec(
        name=name, job_type=job_type, level=level, seconds=seconds, depends_on=tuple(depends_on)
    )


def _refuse_cycles(workload: str, jobs: tuple[JobSpec, ...]) -> None:
    """Kahn's algorithm: a cycle would deadlock the dependency gate, so it is refused at load."""
    waiting = {spec.name: len(spec.depends_on) for spec in jobs}
    downstream: dict[str, list[str]] = {spec.name: [] for spec in jobs}
    for spec in jobs:
        for upstream in spec.depends_on:
            downstream[upstream].append(spec.name)
    ready = [name for name, count in waiting.items() if count == 0]
    done = 0
    while ready:
        current = ready.pop()
        done += 1
        for name in downstream[current]:
            waiting[name] -= 1
            if waiting[name] == 0:
                ready.append(name)
    if done != len(jobs):
        stuck = sorted(name for name, count in waiting.items() if count > 0)
        raise WorkloadError(f"{workload}: dependency cycle among {stuck}")
