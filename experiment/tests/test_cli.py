"""``python -m experiment``: its commands, and how it reports a failure."""

from __future__ import annotations

from pathlib import Path

import pytest

from experiment import __main__ as cli
from experiment import harness, workload
from experiment.tests.fake_jenkins import FakeClock, FakeController


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
