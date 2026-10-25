"""Campaign recovery and the acceptance gate must not turn unfinished work into success."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scripts import verify  # noqa: E402
from scripts.report import chapter_12  # noqa: E402


@pytest.fixture
def campaign(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    path = REPO / "docs/evaluation/eval-v1-2026-10-25/campaign/eval_campaign.py"
    spec = importlib.util.spec_from_file_location("eval_campaign", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "STATE", tmp_path)
    monkeypatch.setattr(module, "LOG", tmp_path / "campaign-log.txt")
    monkeypatch.setattr(module, "PROGRESS", tmp_path / "progress.jsonl")
    monkeypatch.setattr(module, "QUEUES", {"120b": [("test", ["run"])]})
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    return module


def test_failed_steps_resume_and_successful_steps_stay_done(campaign: ModuleType) -> None:
    campaign.record("120b/test", gave_up=True)
    campaign.record("20b/test", seconds=1)
    assert campaign.finished() == {"20b/test"}
    campaign.record("120b/test", seconds=2)
    assert campaign.finished() == {"120b/test", "20b/test"}


def test_attempt_numbering_preserves_logs_with_gaps(
    campaign: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    steps = campaign.STATE / "steps"
    steps.mkdir()
    previous = steps / "120b-01-test-03.log"
    previous.write_text("saved evidence", encoding="utf-8")
    monkeypatch.setattr(
        campaign.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args, 0)
    )
    assert campaign.run_queue("120b") == 0
    assert previous.read_text(encoding="utf-8") == "saved evidence"
    assert (steps / "120b-01-test-04.log").is_file()


@pytest.mark.parametrize("exit_code", [1, 3])
def test_unfinished_queue_returns_failure_and_can_resume(
    campaign: ModuleType, monkeypatch: pytest.MonkeyPatch, exit_code: int
) -> None:
    attempts = []

    def stopped(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[Any]:
        attempts.append(args)
        kwargs["stdout"].write("rate limited for 9 min")
        return subprocess.CompletedProcess(args, exit_code)

    monkeypatch.setattr(campaign.subprocess, "run", stopped)
    assert campaign.run_queue("120b", stop_on_quota=True) == exit_code
    assert campaign.finished() == set()
    assert len(attempts) == (3 if exit_code == 1 else 1)


def test_worker_exception_makes_the_campaign_fail(
    campaign: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*args: Any, **kwargs: Any) -> int:
        raise OSError("runner unavailable")

    monkeypatch.setattr(campaign, "run_queue", broken)
    assert campaign.main(["120b", "--stop-on-quota"]) == 1
    assert "unfinished queues remain" in campaign.LOG.read_text(encoding="utf-8")


def test_duplicate_queue_names_are_rejected(campaign: ModuleType) -> None:
    with pytest.raises(SystemExit) as caught:
        campaign.main(["120b", "120b"])
    assert caught.value.code == 2


def complete_report() -> dict[str, Any]:
    parsers = ["rules", "groq:openai/gpt-oss-120b", "groq:openai/gpt-oss-20b"]
    return {
        "comparison": [
            {"parser": parser, "n": 148, "errors": 2, "complete": True} for parser in parsers
        ],
        "plans": [
            {"parser": parser, "n": 74, "no_model_plan": 0, "errors": 0, "plannable_items": 74}
            for parser in parsers[1:]
        ],
        "ablations": {
            "rows": [
                {"configuration": name, "n": 74, "errors": 1, "complete": True}
                for name in ("full", "no-enums", "no-examples", "no-repair")
            ]
        },
        "e2e": [{"n": 20, "expected": 20, "complete": True, "succeeded": 18}],
        "provenance": {"labels": "machine"},
    }


def test_gate_accepts_completed_measurements_even_with_measured_failures() -> None:
    assert verify._evaluation_problems(complete_report()) == []


@pytest.mark.parametrize("section", ["comparison", "plans", "ablations", "e2e"])
def test_gate_rejects_incomplete_measurements(section: str) -> None:
    report = complete_report()
    if section == "ablations":
        report[section]["rows"][0]["complete"] = False
    elif section == "plans":
        report[section][0]["n"] = 20
    else:
        report[section][0]["complete"] = False
    assert verify._evaluation_problems(report)


def test_gate_requires_the_specified_models_and_a_full_plan_sample() -> None:
    report = complete_report()
    report["comparison"][2]["parser"] = "groq:another-model"
    report["plans"].pop()
    problems = verify._evaluation_problems(report)
    assert any("gpt-oss-20b" in problem for problem in problems)
    assert any("no plan validity" in problem for problem in problems)


def test_campaign_is_rooted_in_the_checkout() -> None:
    path = REPO / "docs/evaluation/eval-v1-2026-10-25/campaign/eval_campaign.py"
    spec = importlib.util.spec_from_file_location("eval_campaign_location", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.REPO == REPO


def test_chapter_marks_incomplete_ablations_and_reports_parser_errors() -> None:
    row = {
        "label": "no catalog enums",
        "complete": False,
        "n": 67,
        "errors": 1,
        "action_accuracy": 1.0,
        "exact_match": 1.0,
        "behavior_accuracy": 1.0,
        "refusal_rate": 1.0,
        "tokens_per_command": 100,
        "plan_valid_before_repair": None,
        "plan_valid_after_repair": None,
    }
    text = chapter_12.table_12_11(
        {"ablations": {"parser": "groq:openai/gpt-oss-120b", "rows": [row]}}
    )
    assert "No catalog enums (incomplete)" in text
    assert "67 (1 unanswered)" in text


def test_archived_evaluation_evidence_matches_its_manifest() -> None:
    archive = REPO / "docs/evaluation/eval-v1-2026-10-25"
    manifest = json.loads((archive / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["labels"] == "machine"
    assert manifest["reviewed_by_a_person"] is False
    assert manifest["files"]
    for relative, expected in manifest["files"].items():
        path = (archive / relative).resolve()
        assert path.is_relative_to(archive)
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, relative
