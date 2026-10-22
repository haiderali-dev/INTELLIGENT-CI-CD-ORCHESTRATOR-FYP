"""setup, warmup and run, end to end against an in-memory controller (tests/fake_jenkins.py)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from experiment import harness, results, workload
from experiment.analyze import AnalysisError, analyze
from experiment.harness import HarnessError
from experiment.tests.fake_jenkins import FakeClock, FakeController

SMOKE = workload.load("freestyle-6")


def controller(arm: str = "optimized", executors: int = 1) -> tuple[FakeController, FakeClock]:
    clock = FakeClock()
    return FakeController(clock, executors=executors, arm=arm), clock


def measure(fake: FakeController, clock: FakeClock, tmp_path: Path, **overrides: Any) -> Path:
    loaded = overrides.pop("loaded", SMOKE)
    options: dict[str, Any] = {
        "controller": "test",
        "executors": fake.executor_count,
        "group": "smoke",
        "results_dir": tmp_path,
        "clock": clock,
        "log": lambda _: None,
    }
    options.update(overrides)
    return harness.run(fake, loaded, **options)  # type: ignore[arg-type]


def test_setup_creates_the_missing_jobs_and_keeps_existing_ones() -> None:
    fake, _ = controller()
    first = harness.setup(fake, SMOKE, log=lambda _: None)  # type: ignore[arg-type]
    assert sorted(first.created) == sorted(SMOKE.jenkins_name(s.name) for s in SMOKE.jobs)
    again = harness.setup(fake, SMOKE, log=lambda _: None)  # type: ignore[arg-type]
    assert (again.created, len(again.kept)) == ([], 6)


def test_setup_refuses_a_job_made_from_another_version_of_the_workload() -> None:
    fake, _ = controller()
    harness.setup(fake, SMOKE, log=lambda _: None)  # type: ignore[arg-type]
    fake.jobs_["fs6-build-auth-service"]["description"] = (
        "Experiment v2 job, workload freestyle-6 (digest 000000000000): old"
    )
    with pytest.raises(HarnessError, match="not made from this version"):
        harness.setup(fake, SMOKE, log=lambda _: None)  # type: ignore[arg-type]


def test_recreate_needs_the_admin_account_and_deletes_every_experiment_job() -> None:
    fake, _ = controller()
    harness.setup(fake, SMOKE, log=lambda _: None)  # type: ignore[arg-type]
    harness.setup(fake, workload.load("freestyle-30"), log=lambda _: None)  # type: ignore[arg-type]
    fake.jobs_["someone-elses-job"] = {"description": "made by hand", "builds": []}
    with pytest.raises(HarnessError, match="admin account"):
        harness.setup(fake, SMOKE, recreate=True, log=lambda _: None)  # type: ignore[arg-type]
    warnings: list[str] = []
    summary = harness.setup(fake, SMOKE, recreate=True, admin=fake, log=warnings.append)  # type: ignore[arg-type]
    assert len(summary.deleted) == 36
    assert "someone-elses-job" in fake.jobs_
    assert len(summary.created) == 6
    assert "WARNING" in warnings[0] and "history" in warnings[0]


@pytest.mark.parametrize("arm", ["optimized", "observe-only"])
def test_a_smoke_run_writes_its_files_analyses_them_and_breaks_no_edge(
    tmp_path: Path, arm: str
) -> None:
    fake, clock = controller(arm=arm)
    harness.setup(fake, SMOKE, log=lambda _: None)  # type: ignore[arg-type]
    folder = measure(fake, clock, tmp_path, expect_arm=arm)

    for name in (*results.RAW_FILES, "analysis.json"):
        assert (folder / name).is_file(), name
    analysis = results.read_json(folder / "analysis.json")
    assert analysis["condition"]["arm"] == arm
    assert analysis["kpis"]["jobs"] == 6
    assert analysis["kpis"]["dependency_violations"] == 0
    latest = tmp_path / results.LATEST
    assert results.read_json(latest)["run"] == folder.name
    assert all(
        latest.stat().st_mtime_ns >= (folder / f).stat().st_mtime_ns for f in results.RAW_FILES
    )


def test_the_optimizer_runs_urgent_work_first_and_fifo_runs_it_last(tmp_path: Path) -> None:
    waits = {}
    for arm in ("optimized", "observe-only"):
        fake, clock = controller(arm=arm)
        harness.setup(fake, SMOKE, log=lambda _: None)  # type: ignore[arg-type]
        folder = measure(fake, clock, tmp_path / arm)
        waits[arm] = results.read_json(folder / "analysis.json")["kpis"]["wait_s"]["by_level"]
    assert waits["optimized"]["MEDIUM"]["mean"] < waits["observe-only"]["MEDIUM"]["mean"]
    assert waits["optimized"]["LOW"]["mean"] > waits["observe-only"]["LOW"]["mean"]


def test_the_run_records_what_it_ran_on(tmp_path: Path) -> None:
    fake, clock = controller()
    harness.setup(fake, SMOKE, log=lambda _: None)  # type: ignore[arg-type]
    meta = results.read_json(measure(fake, clock, tmp_path) / "run.json")
    assert meta["jenkinsVersion"] == "2.568.3"
    assert (meta["pluginVersion"], meta["pluginBuild"]) == ("2.0.0-SNAPSHOT", "f" * 40)
    assert meta["executors"] == 1
    assert meta["workload"]["digest"] == SMOKE.digest
    assert workload.parse(json.loads(meta["workload"]["source"])).digest == SMOKE.digest
    assert meta["configuration"]["optimizerEnabled"] is True
    assert meta["order"]["jobs"][:2] == ["fs6-lint-auth-service", "fs6-cleanup-old-builds"]
    assert meta["history"]["kind"] == "fresh"
    assert meta["complete"] is True


def test_a_seeded_run_queues_the_seeded_order(tmp_path: Path) -> None:
    fake, clock = controller(executors=3)
    harness.setup(fake, SMOKE, log=lambda _: None)  # type: ignore[arg-type]
    meta = results.read_json(
        measure(fake, clock, tmp_path, seed=7, group="random-order") / "run.json"
    )
    assert meta["order"]["seed"] == 7
    assert meta["order"]["jobs"] == [SMOKE.jenkins_name(s.name) for s in SMOKE.submission_order(7)]


def test_warmup_builds_history_and_a_later_run_records_it_as_warm(tmp_path: Path) -> None:
    fake, clock = controller()
    harness.setup(fake, SMOKE, log=lambda _: None)  # type: ignore[arg-type]
    harness.warmup(fake, SMOKE, 2, clock=clock, log=lambda _: None)  # type: ignore[arg-type]
    assert all(len(job["builds"]) == 2 for job in fake.jobs_.values())
    folder = measure(fake, clock, tmp_path, expect_history="warm")
    meta = results.read_json(folder / "run.json")
    assert meta["history"] == {"kind": "warm", "priorBuilds": {"min": 2, "max": 2}}
    assert results.read_json(folder / "builds.json")["fs6-build-auth-service"]["number"] == 3


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"executors": 3}, "AGENT_EXECUTORS=3"),
        ({"expect_arm": "observe-only"}, "optimized arm, not observe-only"),
        ({"expect_history": "warm"}, "history is fresh, not warm"),
        ({"group": "Main Group"}, "group"),
    ],
)
def test_a_run_refuses_the_wrong_conditions(
    tmp_path: Path, overrides: dict[str, Any], message: str
) -> None:
    fake, clock = controller()
    harness.setup(fake, SMOKE, log=lambda _: None)  # type: ignore[arg-type]
    with pytest.raises(HarnessError, match=message):
        measure(fake, clock, tmp_path, **overrides)
    assert not any(tmp_path.iterdir())


def test_a_run_refuses_jobs_that_were_never_set_up(tmp_path: Path) -> None:
    fake, clock = controller()
    with pytest.raises(HarnessError, match="run setup first"):
        measure(fake, clock, tmp_path)


def test_a_run_waits_for_a_busy_controller_and_gives_up(tmp_path: Path) -> None:
    fake, clock = controller()
    harness.setup(fake, SMOKE, log=lambda _: None)  # type: ignore[arg-type]
    fake.stuck = True
    with pytest.raises(HarnessError, match="not idle"):
        measure(fake, clock, tmp_path)


def test_an_unfinished_run_keeps_its_raw_files_and_cannot_be_analysed(tmp_path: Path) -> None:
    fake, clock = controller()
    harness.setup(fake, SMOKE, log=lambda _: None)  # type: ignore[arg-type]
    fake.jobs_["fs6-deploy-auth-service"]["seconds"] = 5_000
    with pytest.raises(HarnessError, match="unfinished"):
        measure(fake, clock, tmp_path)
    (folder,) = results.run_folders(tmp_path)
    assert results.read_json(folder / "run.json")["complete"] is False
    assert not (folder / "analysis.json").exists()
    with pytest.raises(AnalysisError, match="did not complete"):
        analyze(folder)


def test_a_stock_jenkins_run_is_analysed_from_rest_alone(tmp_path: Path) -> None:
    fake, clock = controller(arm="stock")
    harness.setup(fake, SMOKE, log=lambda _: None)  # type: ignore[arg-type]
    folder = measure(fake, clock, tmp_path, expect_arm="stock")
    meta = results.read_json(folder / "run.json")
    assert (meta["arm"], meta["pluginVersion"], meta["configuration"]) == ("stock", None, None)
    assert results.read_jsonl(folder / "events.jsonl") == []
    analysis = results.read_json(folder / "analysis.json")
    assert analysis["kpis"]["jobs"] == 6
    assert analysis["kpis"]["scheduler_overhead_ms"] is None


def test_a_pipeline_workload_records_its_node_block_waits(tmp_path: Path) -> None:
    mixed = workload.load("mixed-30")
    fake, clock = controller(executors=3)
    harness.setup(fake, mixed, log=lambda _: None)  # type: ignore[arg-type]
    folder = measure(fake, clock, tmp_path, loaded=mixed, group="main")
    kpis = results.read_json(folder / "analysis.json")["kpis"]
    assert kpis["jobs"] == 30
    assert kpis["node_block_wait_s"]["pipeline_jobs"] == 15
    assert kpis["dependency_violations"] == 0


def test_the_arm_is_read_from_the_configuration_in_force() -> None:
    def config(enabled: bool, bonus: float, cap: float) -> dict[str, Any]:
        return {
            "configuration": {
                "optimizerEnabled": enabled,
                "agingBonusPerInterval": bonus,
                "agingCap": cap,
            }
        }

    assert harness.arm_of(None) == "stock"
    assert harness.arm_of(config(False, 0.05, 0.15)) == "observe-only"
    assert harness.arm_of(config(True, 0.05, 0.15)) == "optimized"
    assert harness.arm_of(config(True, 0.0, 0.15)) == "aging-off"
    assert harness.arm_of(config(True, 0.05, 0.0)) == "aging-off"


def test_warmup_needs_a_pass() -> None:
    fake, clock = controller()
    with pytest.raises(HarnessError, match="at least one pass"):
        harness.warmup(fake, SMOKE, 0, clock=clock)  # type: ignore[arg-type]
