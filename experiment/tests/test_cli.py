"""``python -m experiment``: its commands, and how it reports a failure."""

from __future__ import annotations

import functools
from pathlib import Path

import pytest

from experiment import __main__ as cli
from experiment import harness, results, workload
from experiment.jenkins import CONTROLLERS
from experiment.tests.fake_jenkins import FakeClock, FakeController


def fake_controllers(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, arms: dict[str, str]) -> None:
    """Answer each named controller's URL with an in-memory controller of the given arm, and
    write the runs under tmp_path on the fake clock."""
    clock = FakeClock()
    fakes = {CONTROLLERS[name]: FakeController(clock, arm=arm) for name, arm in arms.items()}
    monkeypatch.setattr(cli, "JenkinsClient", lambda url, _creds: fakes[url])
    monkeypatch.setattr(cli, "credentials", lambda _user, _variable: None)
    run = functools.partial(harness.run, results_dir=tmp_path, clock=clock, log=lambda _: None)
    monkeypatch.setattr(harness, "run", run)


def test_run_requires_its_conditions() -> None:
    with pytest.raises(SystemExit):
        cli._parser().parse_args(["run", "--controller", "plugin", "--workload", "freestyle-6"])
    args = cli._parser().parse_args(
        [
            "run",
            "--controller",
            "plugin",
            "--workload",
            "freestyle-6",
            "--executors",
            "1",
            "--group",
            "smoke",
        ]
    )
    assert (args.executors, args.group, args.repetition, args.seed, args.arm) == (
        1,
        "smoke",
        1,
        None,
        None,
    )


def test_a_controller_is_named_or_given_by_url_not_both() -> None:
    with pytest.raises(SystemExit):
        cli._parser().parse_args(
            ["setup", "--controller", "plugin", "--url", "http://x", "--workload", "freestyle-6"]
        )
    with pytest.raises(SystemExit):
        cli._parser().parse_args(["setup", "--controller", "nightly", "--workload", "freestyle-6"])


def test_an_arm_outside_the_four_is_refused() -> None:
    with pytest.raises(SystemExit):
        cli._parser().parse_args(
            [
                "run",
                "--controller",
                "plugin",
                "--workload",
                "freestyle-6",
                "--executors",
                "1",
                "--group",
                "g",
                "--arm",
                "fast",
            ]
        )


def test_a_failure_is_one_line_on_stderr_and_exit_code_1(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("JENKINS_BOT_PASSWORD", "unused")
    code = cli.main(["setup", "--url", "http://127.0.0.1:9", "--workload", "freestyle-6"])
    assert code == 1
    assert capsys.readouterr().err.startswith("error: ")


def test_an_unknown_workload_is_a_clean_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["setup", "--url", "http://127.0.0.1:9", "--workload", "nope"]) == 1
    assert "no workload 'nope'" in capsys.readouterr().err


def test_analyze_and_report_work_on_a_results_folder(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    clock = FakeClock()
    fake = FakeController(clock)
    smoke = workload.load("freestyle-6")
    harness.setup(fake, smoke, log=lambda _: None)
    folder = harness.run(
        fake,
        smoke,
        controller="test",
        executors=1,
        group="smoke",
        results_dir=tmp_path,
        clock=clock,
        log=lambda _: None,
    )
    assert cli.main(["analyze", str(folder)]) == 0
    assert "0 dependency violation(s)" in capsys.readouterr().out
    assert cli.main(["report", "--results", str(tmp_path), "--out", str(tmp_path / "report")]) == 0
    assert (tmp_path / "report" / "table_12_1.md").is_file()


def test_the_stock_controller_is_named_like_the_other_two() -> None:
    args = cli._parser().parse_args(["setup", "--controller", "stock", "--workload", "freestyle-6"])
    assert CONTROLLERS[args.controller] == "http://127.0.0.1:8088"
    with pytest.raises(SystemExit):
        cli._parser().parse_args(["smoke", "--controller", "nightly"])


def test_smoke_runs_the_two_experiment_controllers_by_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_controllers(monkeypatch, tmp_path, {"baseline": "observe-only", "plugin": "optimized"})
    assert cli.main(["smoke"]) == 0
    runs = [results.read_json(folder / "run.json") for folder in results.run_folders(tmp_path)]
    assert [(run["controller"], run["arm"]) for run in runs] == [
        ("baseline", "observe-only"),
        ("plugin", "optimized"),
    ]
    assert capsys.readouterr().out.endswith("0 dependency violation(s) across baseline, plugin\n")


def test_smoke_on_the_stock_controller_runs_without_the_plugin(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake_controllers(monkeypatch, tmp_path, {"stock": "stock"})
    assert cli.main(["smoke", "--controller", "stock"]) == 0
    (folder,) = results.run_folders(tmp_path)
    run = results.read_json(folder / "run.json")
    assert (run["controller"], run["arm"], run["pluginVersion"], run["configuration"]) == (
        "stock",
        "stock",
        None,
        None,
    )
    kpis = results.read_json(folder / "analysis.json")["kpis"]
    assert (kpis["jobs"], kpis["succeeded"], kpis["dependency_violations"]) == (6, 6, 0)


def test_smoke_refuses_a_stock_controller_that_has_the_plugin(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_controllers(monkeypatch, tmp_path, {"stock": "observe-only"})
    assert cli.main(["smoke", "--controller", "stock"]) == 1
    assert "configured as the observe-only arm, not stock" in capsys.readouterr().err
    assert results.run_folders(tmp_path) == []
