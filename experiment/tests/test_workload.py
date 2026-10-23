"""The workloads port Milestone 2's jobs exactly, and a malformed workload is refused at load."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from experiment import workload
from experiment.workload import WorkloadError

REPO_ROOT = Path(__file__).resolve().parents[2]
M2_JOBS = json.loads(
    (REPO_ROOT / "legacy/m2-poc/experiment/scripts/jobs.json").read_text(encoding="utf-8")
)
ALL = ("freestyle-30", "pipeline-30", "mixed-30", "freestyle-6")


def as_m2(spec: workload.JobSpec) -> dict[str, Any]:
    """A job spec in jobs.json's own terms, to compare field by field."""
    return {
        "name": spec.name,
        "duration": spec.seconds,
        "priority": spec.level,
        "dependsOn": list(spec.depends_on),
    }


def m2_fields(entry: dict[str, Any]) -> dict[str, Any]:
    return {key: entry[key] for key in ("name", "duration", "priority", "dependsOn")}


@pytest.mark.parametrize("name", ["freestyle-30", "pipeline-30", "mixed-30"])
def test_the_30_job_workloads_are_milestone_2s_jobs_exactly(name: str) -> None:
    loaded = workload.load(name)
    assert [as_m2(spec) for spec in loaded.jobs] == [m2_fields(entry) for entry in M2_JOBS]


def test_the_bands_are_6_low_15_medium_and_9_high_with_20_edges() -> None:
    loaded = workload.load("freestyle-30")
    assert Counter(spec.level for spec in loaded.jobs) == {"LOW": 6, "MEDIUM": 15, "HIGH": 9}
    assert len(loaded.edges) == 20


def test_each_workload_has_the_job_types_part_4_8_1_gives_it() -> None:
    assert {spec.job_type for spec in workload.load("freestyle-30").jobs} == {"freestyle"}
    assert {spec.job_type for spec in workload.load("pipeline-30").jobs} == {"pipeline"}
    assert {spec.job_type for spec in workload.load("freestyle-6").jobs} == {"freestyle"}
    mixed = workload.load("mixed-30")
    assert Counter(spec.job_type for spec in mixed.jobs) == {"freestyle": 15, "pipeline": 15}
    assert [spec.job_type for spec in mixed.jobs][:4] == [
        "freestyle",
        "pipeline",
        "freestyle",
        "pipeline",
    ]


def test_the_smoke_workload_is_six_freestyle_30_jobs_with_their_chain() -> None:
    smoke, full = workload.load("freestyle-6"), workload.load("freestyle-30")
    assert len(smoke.jobs) == 6
    assert all(spec == full.job(spec.name) for spec in smoke.jobs)
    assert Counter(spec.level for spec in smoke.jobs) == {"LOW": 2, "MEDIUM": 3, "HIGH": 1}
    assert smoke.edges == (
        ("build-auth-service", "test-auth-service"),
        ("test-auth-service", "deploy-auth-service"),
    )


def test_every_workload_has_its_own_prefix_so_all_fit_on_one_controller() -> None:
    loaded = [workload.load(name) for name in ALL]
    assert len({w.prefix for w in loaded}) == len(loaded)
    names = [w.jenkins_name(spec.name) for w in loaded for spec in w.jobs]
    assert len(names) == len(set(names))
    assert (
        workload.load("freestyle-6").jenkins_name("build-auth-service") == "fs6-build-auth-service"
    )


def test_the_fixed_order_is_low_then_medium_then_high_each_band_in_file_order() -> None:
    loaded = workload.load("freestyle-30")
    order = loaded.submission_order()
    levels = [spec.level for spec in order]
    assert levels == sorted(levels, key=workload.LEVELS.index)
    for level in workload.LEVELS:
        assert [s.name for s in order if s.level == level] == [
            s.name for s in loaded.jobs if s.level == level
        ]


def test_a_seeded_order_is_a_reproducible_permutation() -> None:
    loaded = workload.load("mixed-30")
    first, again, other = (
        loaded.submission_order(1),
        loaded.submission_order(1),
        loaded.submission_order(2),
    )
    assert [s.name for s in first] == [s.name for s in again]
    assert [s.name for s in first] != [s.name for s in other]
    assert sorted(s.name for s in first) == sorted(s.name for s in loaded.jobs)
    assert [s.name for s in first] != [s.name for s in loaded.submission_order()]


def test_the_digest_follows_the_content_not_the_layout() -> None:
    data = json.loads((workload.WORKLOADS_DIR / "freestyle-6.json").read_text(encoding="utf-8"))
    reformatted = json.loads(json.dumps(data, indent=8))
    assert workload.parse(reformatted).digest == workload.load("freestyle-6").digest
    data["jobs"][0]["seconds"] = 7
    assert workload.parse(data).digest != workload.load("freestyle-6").digest


def small(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "name": "tiny",
        "description": "two jobs",
        "prefix": "t-",
        "jobs": [
            {"name": "a", "type": "freestyle", "level": "LOW", "seconds": 1, "dependsOn": []},
            {"name": "b", "type": "pipeline", "level": "HIGH", "seconds": 2, "dependsOn": ["a"]},
        ],
    }
    data.update(overrides)
    return data


def test_a_valid_small_workload_loads() -> None:
    loaded = workload.parse(small())
    assert loaded.edges == (("a", "b"),)
    assert loaded.job("b").job_type == "pipeline"


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: d.pop("prefix"), "missing 'prefix'"),
        (lambda d: d.update(prefix="Bad_"), "prefix"),
        (lambda d: d.update(jobs=[]), "no jobs"),
        (lambda d: d["jobs"].append(dict(d["jobs"][0])), "duplicate"),
        (lambda d: d["jobs"][1].update(dependsOn=["zzz"]), "not in the workload"),
        (lambda d: d["jobs"][1].update(dependsOn=["b"]), "depends on itself"),
        (lambda d: d["jobs"][0].update(dependsOn=["b"]), "cycle"),
        (lambda d: d["jobs"][0].update(level="URGENT"), "level"),
        (lambda d: d["jobs"][0].update(type="matrix"), "type"),
        (lambda d: d["jobs"][0].update(seconds=0), "seconds"),
        (lambda d: d["jobs"][0].update(seconds=601), "seconds"),
        (lambda d: d["jobs"][0].update(seconds=1.5), "seconds"),
        (lambda d: d["jobs"][0].update(seconds=True), "seconds"),
        (lambda d: d["jobs"][0].update(name="a b"), "plain Jenkins job name"),
        (lambda d: d["jobs"][0].update(dependsOn="b"), "dependsOn"),
    ],
)
def test_a_malformed_workload_is_refused(change: Any, message: str) -> None:
    data = small()
    change(data)
    with pytest.raises(WorkloadError, match=message):
        workload.parse(data)


def test_an_unknown_workload_names_the_known_ones() -> None:
    with pytest.raises(WorkloadError, match="freestyle-30"):
        workload.load("freestyle-31")
