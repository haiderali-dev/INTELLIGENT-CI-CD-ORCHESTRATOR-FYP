"""T7.4: the table, the CSV and the charts, from analyses whose figures are known."""

from __future__ import annotations

import csv
import io
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from experiment import m2, report, results, svg

WHEN = datetime(2026, 10, 23, 3, 0, tzinfo=UTC)


def figures(
    mean: float,
    high: float,
    makespan: float,
    violations: int = 0,
    overhead: float | None = None,
    node: float | None = None,
) -> dict[str, Any]:
    """The KPIs of one run, in run_kpis' shape, with the figures a test needs to choose."""
    return {
        "jobs": 30,
        "succeeded": 30,
        "wait_s": {
            "mean": mean,
            "max": mean * 2,
            "by_level": {
                "HIGH": {"jobs": 9, "mean": high, "max": high},
                "MEDIUM": {"jobs": 15, "mean": mean, "max": mean},
                "LOW": {"jobs": 6, "mean": mean / 2, "max": mean},
            },
        },
        "completion_s": {"jobs": 30, "mean": mean + 10, "max": makespan},
        "makespan_s": makespan,
        "throughput_per_min": 5.0,
        "utilization": 0.95,
        "dependency_violations": violations,
        "violated_edges": [],
        "max_low_wait_s": mean,
        "node_block_wait_s": None
        if node is None
        else {
            "pipeline_jobs": 30,
            "first": {"jobs": 30, "mean": node, "max": node},
            "total": {"jobs": 30, "mean": node, "max": node},
        },
        "scheduler_overhead_ms": None
        if overhead is None
        else {"samples": 5, "median": overhead, "p95": overhead, "max": overhead},
    }


def analysis(
    run: str,
    arm: str,
    kpis: dict[str, Any],
    group: str = "main",
    workload: str = "freestyle-30",
    repetition: int = 1,
) -> dict[str, Any]:
    return {
        "run": run,
        "condition": {
            "group": group,
            "workload": workload,
            "executors": 1,
            "history": "warm",
            "order": "fixed",
            "arm": arm,
            "repetition": repetition,
            "controller": "plugin",
            "jenkinsVersion": "2.568.3",
            "pluginVersion": "2.0.0-SNAPSHOT",
            "pluginBuild": "f" * 40,
        },
        "kpis": kpis,
    }


ANALYSES = [
    analysis("r1-control", "observe-only", figures(150, 270, 322)),
    analysis("r2-control", "observe-only", figures(160, 280, 324), repetition=2),
    analysis("r3-control", "observe-only", figures(170, 290, 326), repetition=3),
    analysis("r1-opt", "optimized", figures(140, 170, 322, overhead=0.4), repetition=1),
    analysis("r2-opt", "optimized", figures(150, 180, 323, overhead=0.6), repetition=2),
    analysis("r3-opt", "optimized", figures(160, 190, 324, overhead=0.5), repetition=3),
    analysis("smoke-1", "observe-only", figures(20, 30, 60), group="smoke", workload="freestyle-6"),
]


def test_repetitions_aggregate_to_a_mean_and_a_standard_deviation() -> None:
    aggregates = report.aggregate(ANALYSES)
    main = next(c for c in aggregates if c.group == "main")
    assert list(aggregates[main]) == ["observe-only", "optimized"]
    control = aggregates[main]["observe-only"]["wait_mean"]
    assert control is not None
    assert (control.mean, control.sd, control.n) == (160, 10, 3)
    overhead = aggregates[main]["optimized"]["overhead"]
    assert overhead is not None and overhead.mean == pytest.approx(0.5)
    assert aggregates[main]["observe-only"]["overhead"] is None


def test_conditions_are_ordered_main_first_then_the_other_groups() -> None:
    assert [c.group for c in report.aggregate(ANALYSES)] == ["main", "smoke"]


def test_scheduling_efficiency_is_appendix_fs_formula() -> None:
    assert report.efficiency(report.Stat(280, 10, 3), report.Stat(180, 10, 3)) == pytest.approx(
        35.714, abs=0.001
    )
    assert report.efficiency(None, report.Stat(1, None, 1)) is None
    assert report.efficiency(report.Stat(0, None, 1), report.Stat(1, None, 1)) is None


def test_the_table_has_a_section_per_condition_with_n_and_spread() -> None:
    table = report.table_md(report.aggregate(ANALYSES), [], len(ANALYSES), ["broken-run"], WHEN)
    assert "## main: freestyle-30, 1 executor, warm history, fixed order" in table
    assert "## smoke: freestyle-6, 1 executor, warm history, fixed order" in table
    assert f"| observe-only | 3 | 160.00 {report.PM} 10.00 |" in table
    assert (
        "Scheduling efficiency of optimized against observe-only: mean wait +6.2%, high mean wait +35.7%"
        in table
    )
    assert "Not included, because they did not complete: broken-run." in table
    assert "small sample" in table
    assert "| observe-only | 1 | 20.00 |" in table


def test_the_table_shows_node_block_waits_only_where_there_are_pipelines() -> None:
    with_node = [analysis("p1", "optimized", figures(10, 12, 50, node=1.5), workload="pipeline-30")]
    table = report.table_md(report.aggregate(with_node), [], 1, [], WHEN)
    assert "First node-block wait (s)" in table
    assert "First node-block wait (s)" not in report.table_md(
        report.aggregate(ANALYSES), [], 7, [], WHEN
    )


def test_the_csv_has_one_row_per_run_with_every_metric() -> None:
    rows = list(csv.DictReader(io.StringIO(report.runs_csv(ANALYSES))))
    assert len(rows) == len(ANALYSES)
    first = next(r for r in rows if r["run"] == "r1-control")
    assert (first["arm"], first["wait_mean"], first["makespan"], first["violations"]) == (
        "observe-only",
        "150",
        "322",
        "0",
    )
    assert set(rows[0]) >= {key for key, _, _ in report.METRICS}


def test_the_charts_are_svg_and_cover_each_condition() -> None:
    m2_runs = m2.import_m2()
    charts = report.charts(report.aggregate(ANALYSES), m2_runs)
    assert set(charts) == {
        "waits-main-freestyle-30-1x.svg",
        "waits-smoke-freestyle-6-1x.svg",
        "makespan.svg",
        "wait-low-max.svg",
        "violations.svg",
        "m2-runs.svg",
    }
    for content in charts.values():
        assert ET.fromstring(content).tag.endswith("svg")  # noqa: S314 - our own output


def test_the_report_is_written_from_the_analysed_runs_only(tmp_path: Path) -> None:
    for item in ANALYSES[:2]:
        folder = tmp_path / "results" / item["run"]
        folder.mkdir(parents=True)
        results.write_json(folder / "run.json", {})
        results.write_json(folder / "analysis.json", item)
    unfinished = tmp_path / "results" / "r9-unfinished"
    unfinished.mkdir()
    results.write_json(unfinished / "run.json", {"complete": False})
    written = report.write_report(results.run_folders(tmp_path / "results"), tmp_path / "report")
    names = {path.name for path in written}
    assert {"table_12_1.md", "runs.csv", "m2-runs.svg"} <= names
    table = (tmp_path / "report" / "table_12_1.md").read_text(encoding="utf-8")
    assert "from 2 analysed run(s)" in table
    assert "r9-unfinished" in table


def test_a_bar_chart_draws_a_bar_per_value_and_a_whisker_per_spread() -> None:
    chart = svg.grouped_bars(
        "Waits <by band>",
        ["HIGH", "LOW"],
        [svg.Series("a", [1.0, 2.0], [0.5, None]), svg.Series("b", [3.0, None])],
        "Seconds",
    )
    root = ET.fromstring(chart)  # noqa: S314 - our own output
    namespace = "{http://www.w3.org/2000/svg}"
    bars = [r for r in root.iter(f"{namespace}rect") if r.find(f"{namespace}title") is not None]
    assert len(bars) == 3
    assert "Waits &lt;by band&gt;" in chart


@pytest.mark.parametrize(
    ("categories", "series", "message"),
    [
        ([], [svg.Series("a", [])], "at least one category"),
        (["x"], [svg.Series(str(i), [1.0]) for i in range(7)], "at most"),
        (["x", "y"], [svg.Series("a", [1.0])], "values"),
    ],
)
def test_a_chart_refuses_what_it_cannot_draw(
    categories: list[str], series: list[svg.Series], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        svg.grouped_bars("t", categories, series, "y")


def test_the_axis_ends_on_a_round_value() -> None:
    assert svg._axis(7.3) == (8, 2)
    assert svg._axis(0) == (1.0, 0.25)
    assert svg._axis(322) == (400, 100)
