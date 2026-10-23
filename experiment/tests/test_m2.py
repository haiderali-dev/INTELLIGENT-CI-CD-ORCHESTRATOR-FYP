"""T7.5: Milestone 2's runs import as their own series and agree with the earlier recomputation."""

from __future__ import annotations

import csv
from datetime import UTC, datetime
from pathlib import Path

import pytest

from experiment import m2, report, workload

REPO_ROOT = Path(__file__).resolve().parents[2]
#: The testing chapter's recomputation of the same five files (scripts/report/testing_figures.py),
#: written independently of this package.
RECOMPUTED = REPO_ROOT / "docs" / "testing" / "data" / "m2-runs.csv"


@pytest.fixture(scope="module")
def imported() -> list[dict[str, object]]:
    return m2.import_m2()


def test_every_kept_run_is_imported_under_its_series(imported: list[dict[str, object]]) -> None:
    assert [(run["series"], run["run"]) for run in imported] == [
        ("M2 stock Jenkins", "stock Jenkins (FIFO)"),
        ("M2 dispatcher v1", "run 1"),
        ("M2 dispatcher v1", "run 2"),
        ("M2 dispatcher v1", "run 3"),
        ("M2 dispatcher v1", "run 4 (the report's)"),
    ]


def test_the_import_agrees_with_the_testing_chapters_recomputation(
    imported: list[dict[str, object]],
) -> None:
    with RECOMPUTED.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == len(imported)
    for row, run in zip(rows, imported, strict=True):
        kpis = run["kpis"]
        assert isinstance(kpis, dict)
        assert row["file"] == str(run["file"]).rsplit("/", 1)[-1]
        assert kpis["jobs"] == int(row["jobs"]) == 30
        assert kpis["makespan_s"] == pytest.approx(float(row["makespan_s"]), abs=0.01)
        assert kpis["wait_s"]["mean"] == pytest.approx(float(row["mean_wait_s"]), abs=0.01)
        for level, column in (
            ("HIGH", "high_mean_s"),
            ("MEDIUM", "medium_mean_s"),
            ("LOW", "low_mean_s"),
        ):
            assert kpis["wait_s"]["by_level"][level]["mean"] == pytest.approx(
                float(row[column]), abs=0.01
            )
        assert kpis["dependency_violations"] == int(row["dependency_violations"])


def test_the_reports_headline_run_is_the_one_the_report_printed(
    imported: list[dict[str, object]],
) -> None:
    stock, run4 = imported[0]["kpis"], imported[-1]["kpis"]
    assert isinstance(stock, dict)
    assert isinstance(run4, dict)
    # docs/m2-baseline.md: the HIGH band's mean wait fell from 271.50 s to 39.08 s in run 4.
    assert run4["wait_s"]["by_level"]["HIGH"]["mean"] == pytest.approx(39.08, abs=0.01)
    assert stock["wait_s"]["by_level"]["HIGH"]["mean"] == pytest.approx(271.50, abs=0.01)


def test_milestone_2_never_enters_a_v2_aggregate(imported: list[dict[str, object]]) -> None:
    assert report.aggregate([]) == {}
    table = report.table_md({}, imported, 0, [], datetime(2026, 10, 23, tzinfo=UTC))
    section = table.split("## Milestone 2")[1]
    assert section.count("| M2 dispatcher v1 |") == 4
    assert section.count("| M2 stock Jenkins |") == 1


def test_a_result_file_missing_a_workload_job_is_refused() -> None:
    result = {
        "label": "broken",
        "t0": 0,
        "jobs": [{"name": "lint-auth-service", "startTime": 1, "duration": 1}],
    }
    with pytest.raises(ValueError, match="no build of"):
        m2.m2_records(result, workload.load("freestyle-30"))
