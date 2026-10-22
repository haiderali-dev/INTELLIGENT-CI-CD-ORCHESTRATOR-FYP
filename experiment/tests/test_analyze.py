"""analyze: a run folder's raw files give the same KPIs every time, from what the run recorded."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from experiment import analyze as analysis_module
from experiment import harness, results, workload
from experiment.analyze import AnalysisError, analyze
from experiment.tests.fake_jenkins import FakeClock, FakeController


def one_run(tmp_path: Path) -> Path:
    clock = FakeClock()
    fake = FakeController(clock)
    smoke = workload.load("freestyle-6")
    harness.setup(fake, smoke, log=lambda _: None)  # type: ignore[arg-type]
    return harness.run(  # type: ignore[arg-type]
        fake,
        smoke,
        controller="test",
        executors=1,
        group="smoke",
        results_dir=tmp_path,
        clock=clock,
        log=lambda _: None,
    )


def test_analysing_again_gives_the_same_kpis(tmp_path: Path) -> None:
    folder = one_run(tmp_path)
    first = results.read_json(folder / "analysis.json")
    again = analyze(folder, update_latest=False)
    assert again["kpis"] == first["kpis"]
    assert again["jobs"] == first["jobs"]


def test_the_run_is_analysed_from_its_recorded_workload_not_todays_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = one_run(tmp_path)
    monkeypatch.setattr(workload, "WORKLOADS_DIR", tmp_path / "no-workloads-here")
    assert analyze(folder, update_latest=False)["kpis"]["jobs"] == 6


def test_a_tampered_workload_record_is_refused(tmp_path: Path) -> None:
    folder = one_run(tmp_path)
    meta = results.read_json(folder / "run.json")
    source = json.loads(meta["workload"]["source"])
    source["jobs"][0]["seconds"] = 99
    meta["workload"]["source"] = json.dumps(source)
    results.write_json(folder / "run.json", meta)
    with pytest.raises(AnalysisError, match="does not match its digest"):
        analyze(folder)


def test_analysing_without_updating_latest_leaves_it_alone(tmp_path: Path) -> None:
    folder = one_run(tmp_path)
    latest = tmp_path / results.LATEST
    before = latest.stat().st_mtime_ns
    analyze(folder, update_latest=False)
    assert latest.stat().st_mtime_ns == before


def test_a_folder_without_a_run_is_refused(tmp_path: Path) -> None:
    with pytest.raises(AnalysisError, match="not a run folder"):
        analyze(tmp_path)


def test_events_that_cannot_account_for_a_build_are_an_analysis_error(tmp_path: Path) -> None:
    folder = one_run(tmp_path)
    results.write_json(folder / "builds.json", {})
    with pytest.raises(AnalysisError, match="no build in this run"):
        analyze(folder)


def test_the_condition_names_what_report_groups_by(tmp_path: Path) -> None:
    meta = results.read_json(one_run(tmp_path) / "run.json")
    condition = analysis_module.condition(meta)
    assert {
        k: condition[k] for k in ("group", "workload", "executors", "history", "order", "arm")
    } == {
        "group": "smoke",
        "workload": "freestyle-6",
        "executors": 1,
        "history": "fresh",
        "order": "fixed",
        "arm": "optimized",
    }
