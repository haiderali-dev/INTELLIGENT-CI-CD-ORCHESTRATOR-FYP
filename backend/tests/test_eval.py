"""The evaluation harness (``eval/``).

Its numbers go into a dissertation, so the tests that matter are about integrity: a draft cannot
pass itself off as reviewed, an unscored metric is null rather than zero, a model's failure is never
scored with the rules' answer in its place, and an interrupted run resumes instead of re-spending
quota.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eval import dataset as ds  # noqa: E402
from eval import metrics as em  # noqa: E402
from eval import report as er  # noqa: E402
from eval import runner as er_run  # noqa: E402

from app.ai.intent import Action, Intent  # noqa: E402
from app.ai.providers import FakeProvider, ProviderUnavailableError, RateLimitedError  # noqa: E402
from app.ai.validator import IntentValidator, IssueKind  # noqa: E402
from app.services.catalog import Catalog  # noqa: E402

CATALOG = REPO_ROOT / "catalog" / "services.yaml"
SAMPLE = REPO_ROOT / "eval" / "datasets" / "sample.jsonl"


def raw_item(index: int = 1, **overrides: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": f"t-{index}",
        "text": "Build payment-service from main",
        "category": "clear",
        "role": "DEVELOPER",
        "gold_intent": {"action": "BUILD", "service": "payment-service", "branch": "main"},
        "gold_behavior": "GENERATE",
        "notes": "",
        "labeled_by": "reviewer-a",
        "needs_review": False,
        "split": "dev",
    }
    item.update(overrides)
    return item


def write_dataset(path: Path, items: list[dict[str, Any]]) -> Path:
    path.write_text("".join(json.dumps(item) + "\n" for item in items), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Dataset rules (4.9)
# ---------------------------------------------------------------------------


def test_the_shipped_sample_is_thirty_unreviewed_drafts() -> None:
    """4.9: Claude Code may draft at most 30 items, each marked needs_review."""
    dataset = ds.load_dataset(SAMPLE)

    assert len(dataset.items) == 30
    assert all(item.needs_review for item in dataset.items)
    assert all(item.labeled_by == ds.DRAFT_LABELER for item in dataset.items)
    assert dataset.scorable == ()


def test_the_sample_follows_the_category_mix() -> None:
    assert ds.load_dataset(SAMPLE).warnings == ()


def test_a_draft_cannot_claim_to_be_reviewed(tmp_path: Path) -> None:
    """The rule that matters most: an unchecked gold label must not reach the report."""
    path = write_dataset(
        tmp_path / "d.jsonl", [raw_item(labeled_by=ds.DRAFT_LABELER, needs_review=False)]
    )

    with pytest.raises(ds.DatasetError, match="needs_review"):
        ds.load_dataset(path)


def test_more_than_thirty_drafts_is_refused(tmp_path: Path) -> None:
    items = [raw_item(index, labeled_by=ds.DRAFT_LABELER, needs_review=True) for index in range(31)]

    with pytest.raises(ds.DatasetError, match="at most 30"):
        ds.load_dataset(write_dataset(tmp_path / "d.jsonl", items))


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"gold_behavior": "MAYBE"}, "gold_behavior"),
        ({"category": "vibes"}, "category"),
        ({"role": "INTERN"}, "role"),
        ({"gold_intent": {"action": "BUILD", "colour": "red"}}, "unknown fields"),
        ({"split": "train"}, "split"),
        ({"text": "  "}, "empty text"),
    ],
)
def test_a_malformed_item_names_its_line_and_rule(
    tmp_path: Path, override: dict[str, Any], message: str
) -> None:
    path = write_dataset(tmp_path / "d.jsonl", [raw_item(**override)])

    with pytest.raises(ds.DatasetError, match=message) as exc:
        ds.load_dataset(path)

    assert "line 1" in str(exc.value)


def test_duplicate_ids_are_refused(tmp_path: Path) -> None:
    path = write_dataset(tmp_path / "d.jsonl", [raw_item(1), raw_item(1)])

    with pytest.raises(ds.DatasetError, match="duplicate"):
        ds.load_dataset(path)


def test_an_item_repeating_a_few_shot_example_is_caught(tmp_path: Path) -> None:
    """Otherwise the model copies the answer it was shown and inflates its own score."""
    dataset = ds.load_dataset(
        write_dataset(
            tmp_path / "d.jsonl", [raw_item(text="Can you compile auth-service off develop")]
        )
    )

    clash = ds.overlap_with_examples(dataset, ["can you compile auth-service off develop"])

    assert clash == ["t-1"]


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def prediction(**fields: Any) -> em.Prediction:
    base: dict[str, Any] = {
        "item_id": "x",
        "category": "clear",
        "gold_intent": {"action": "BUILD"},
        "gold_behavior": "GENERATE",
        "predicted_intent": {"action": "BUILD"},
        "predicted_behavior": "GENERATE",
    }
    base.update(fields)
    return em.Prediction(**base)


def test_nothing_measured_is_null_not_zero() -> None:
    """A refusal rate of 0 over no refusal items would read as a finding."""
    result = em.score([])

    assert result["n"] == 0
    assert result["action_accuracy"] is None
    assert result["refusal_rate"] is None
    assert result["clarification"] == {"precision": None, "recall": None}
    assert result["latency_ms"] == {"median": None, "p95": None}


@pytest.mark.parametrize(
    ("name", "gold", "predicted", "equal"),
    [
        ("extra_stages", ["lint", "security_scan"], ["security_scan", "lint"], True),
        ("extra_stages", ["lint"], [], False),
        ("justification", "hotfix for login bug", "high priority, hotfix for login bug", True),
        ("justification", None, None, True),
        ("justification", "login bug", None, False),
        ("branch", "Feature/X", "feature/x", False),  # Git branches are case-sensitive
        ("service", "Payment-Service", "payment-service", True),
        ("commit", "3F78685", "3f78685", True),
        ("environment", None, "staging", False),
    ],
)
def test_field_comparison_rules(name: str, gold: Any, predicted: Any, equal: bool) -> None:
    assert em.field_equal(name, gold, predicted) is equal


def test_clarification_precision_and_recall() -> None:
    predictions = [
        prediction(gold_behavior="CLARIFY", predicted_behavior="CLARIFY"),
        prediction(gold_behavior="CLARIFY", predicted_behavior="GENERATE"),
        prediction(gold_behavior="GENERATE", predicted_behavior="CLARIFY"),
        prediction(gold_behavior="GENERATE", predicted_behavior="GENERATE"),
    ]

    result = em.score(predictions)

    assert result["clarification"] == {"precision": 0.5, "recall": 0.5}


def test_the_refusal_rate_is_over_items_that_should_be_refused() -> None:
    predictions = [
        prediction(gold_behavior="REFUSE", predicted_behavior="REFUSE"),
        prediction(gold_behavior="REFUSE", predicted_behavior="GENERATE"),
        prediction(gold_behavior="GENERATE", predicted_behavior="REFUSE"),
    ]

    assert em.score(predictions)["refusal_rate"] == 0.5


def test_errors_are_counted_but_not_scored() -> None:
    result = em.score([prediction(), prediction(error="model did not answer")])

    assert result["n"] == 1
    assert result["errors"] == 1


def test_cached_answers_are_left_out_of_latency() -> None:
    """A rerun served from cache must not make the model look faster than it is."""
    predictions = [prediction(latency_ms=900), prediction(latency_ms=1, cached=True)]

    result = em.score(predictions)

    assert result["latency_ms"]["median"] == 900
    assert result["n"] == 2
    assert result["cache_hits"] == 1


def test_the_p95_is_an_observed_value() -> None:
    """Nearest rank: never a latency nobody actually experienced."""
    predictions = [prediction(latency_ms=value) for value in range(1, 101)]

    assert em.score(predictions)["latency_ms"]["p95"] == 95


# ---------------------------------------------------------------------------
# The runner
# ---------------------------------------------------------------------------


@pytest.fixture
def catalog() -> Catalog:
    return Catalog(CATALOG)


def config(tmp_path: Path, path: Path, parser: str = "rules", **extra: Any) -> er_run.RunConfig:
    return er_run.RunConfig(parser=parser, dataset=path, out_dir=tmp_path / "out", **extra)


async def test_a_rules_run_writes_a_reportable_metrics_file(
    tmp_path: Path, catalog: Catalog
) -> None:
    path = write_dataset(
        tmp_path / "d.jsonl",
        [
            raw_item(1),
            raw_item(
                2, text="deploy it", gold_intent={"action": "DEPLOY"}, gold_behavior="CLARIFY"
            ),
        ],
    )

    report = await er_run.run(
        config(tmp_path, path), ds.load_dataset(path), catalog, log=lambda _: None
    )

    written = json.loads((tmp_path / "out" / "metrics.json").read_text(encoding="utf-8"))
    assert written == report
    assert report["run"]["for_reporting"] is True
    assert report["metrics"]["n"] == 2
    assert report["metrics"]["action_accuracy"] == 1.0


async def test_unreviewed_items_are_excluded_by_default(tmp_path: Path, catalog: Catalog) -> None:
    report = await er_run.run(
        config(tmp_path, SAMPLE), ds.load_dataset(SAMPLE), catalog, log=lambda _: None
    )

    assert report["metrics"]["n"] == 0
    assert report["dataset"]["excluded_needs_review"] == 30
    assert "nothing was measured" in report["warning"]


async def test_including_unreviewed_items_stamps_the_run_not_for_reporting(
    tmp_path: Path, catalog: Catalog
) -> None:
    report = await er_run.run(
        config(tmp_path, SAMPLE, include_unreviewed=True),
        ds.load_dataset(SAMPLE),
        catalog,
        log=lambda _: None,
    )

    assert report["metrics"]["n"] == 30
    assert report["run"]["for_reporting"] is False
    assert "must not be reported" in report["warning"]


async def test_a_model_failure_is_an_error_never_the_rules_answer(
    tmp_path: Path, catalog: Catalog
) -> None:
    """In production the rules would answer; here that would score them as the model."""
    path = write_dataset(tmp_path / "d.jsonl", [raw_item(1)])
    down = ProviderUnavailableError("503")
    provider = FakeProvider(per_model={"m": [down, down, down]})

    report = await er_run.run(
        config(tmp_path, path, parser="groq:m"),
        ds.load_dataset(path),
        catalog,
        provider=provider,
        log=lambda _: None,
    )

    assert report["metrics"]["n"] == 0
    assert report["metrics"]["errors"] == 1


async def test_an_exhausted_budget_stops_and_saves_progress(
    tmp_path: Path, catalog: Catalog
) -> None:
    """4.9: stop with a clear message when the daily budget is reached."""
    path = write_dataset(
        tmp_path / "d.jsonl",
        [
            raw_item(index, text=f"Build payment-service from main, request {index}")
            for index in (1, 2, 3)
        ],
    )
    good: dict[str, Any] = Intent(
        action=Action.BUILD, service="payment-service", branch="main"
    ).to_card()
    provider = FakeProvider(
        per_model={"m": [good, RateLimitedError("daily", retry_after=40_000, exhausted=True)]}
    )
    messages: list[str] = []

    report = await er_run.run(
        config(tmp_path, path, parser="groq:m"),
        ds.load_dataset(path),
        catalog,
        provider=provider,
        log=messages.append,
    )

    assert report["run"]["complete"] is False
    assert "daily budget" in (report["run"]["stopped_reason"] or "")
    assert report["metrics"]["n"] == 1
    saved = (tmp_path / "out" / "predictions.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(saved) == 1


async def test_a_rerun_resumes_without_repeating_done_items(
    tmp_path: Path, catalog: Catalog
) -> None:
    """Resuming is what keeps an interrupted run from re-spending quota."""
    path = write_dataset(
        tmp_path / "d.jsonl",
        [
            raw_item(index, text=f"Build payment-service from main, request {index}")
            for index in (1, 2)
        ],
    )
    good: dict[str, Any] = Intent(
        action=Action.BUILD, service="payment-service", branch="main"
    ).to_card()

    first = FakeProvider(
        per_model={"m": [good, RateLimitedError("daily", exhausted=True, retry_after=9e4)]}
    )
    await er_run.run(
        config(tmp_path, path, parser="groq:m"),
        ds.load_dataset(path),
        catalog,
        provider=first,
        log=lambda _: None,
    )

    second = FakeProvider(per_model={"m": [good]})
    report = await er_run.run(
        config(tmp_path, path, parser="groq:m"),
        ds.load_dataset(path),
        catalog,
        provider=second,
        log=lambda _: None,
    )

    assert len(second.calls) == 1  # only the item the first run did not finish
    assert report["run"]["complete"] is True
    assert report["metrics"]["n"] == 2


async def test_fresh_discards_saved_progress(tmp_path: Path, catalog: Catalog) -> None:
    path = write_dataset(tmp_path / "d.jsonl", [raw_item(1)])
    await er_run.run(config(tmp_path, path), ds.load_dataset(path), catalog, log=lambda _: None)

    report = await er_run.run(
        config(tmp_path, path, fresh=True), ds.load_dataset(path), catalog, log=lambda _: None
    )

    saved = (tmp_path / "out" / "predictions.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(saved) == 1
    assert report["metrics"]["n"] == 1


@pytest.mark.parametrize(
    ("parser", "examples", "enums", "suffix"),
    [
        ("rules", True, True, "sample__rules"),
        ("groq:openai/gpt-oss-120b", True, True, "sample__groq-openai-gpt-oss-120b"),
        ("groq:openai/gpt-oss-120b", False, True, "sample__groq-openai-gpt-oss-120b__no-examples"),
        ("groq:openai/gpt-oss-120b", True, False, "sample__groq-openai-gpt-oss-120b__no-enums"),
    ],
)
def test_each_configuration_gets_its_own_results_directory(
    parser: str, examples: bool, enums: bool, suffix: str
) -> None:
    """So an ablation never resumes, or overwrites, the full configuration's run."""
    out = er_run.default_out_dir(parser, SAMPLE, include_examples=examples, include_enums=enums)

    assert out.name == suffix


# ---------------------------------------------------------------------------
# The accept-all Git client and the cached provider
# ---------------------------------------------------------------------------


async def test_the_accept_all_git_client_still_lets_the_validator_refuse_unsafe_refs(
    catalog: Catalog,
) -> None:
    """It factors out repository state, not the D-023 guard against option-shaped refs."""
    validator = IntentValidator(catalog, er_run.AcceptAllGitClient())

    any_branch = await validator.validate(
        Intent(action=Action.BUILD, service="payment-service", branch="whatever/branch")
    )
    unsafe = await validator.validate(
        Intent(action=Action.BUILD, service="payment-service", branch="--upload-pack=x")
    )

    assert any_branch.ok
    assert unsafe.issues[0].kind is IssueKind.UNSAFE


async def test_the_cache_answers_a_repeat_without_a_live_call(tmp_path: Path) -> None:
    from app.ai.providers import ChatMessage

    live = FakeProvider(script=[{"action": "BUILD"}])
    waits: list[float] = []

    async def no_sleep(seconds: float) -> None:
        waits.append(seconds)

    cached = er_run.CachedLiveProvider(live, tmp_path, sleep=no_sleep)
    messages = [ChatMessage(role="user", content="build")]

    first = await cached.complete_json(schema={}, system="s", messages=messages, model="m")
    second = await cached.complete_json(schema={}, system="s", messages=messages, model="m")

    assert first.data == second.data == {"action": "BUILD"}
    assert cached.live_calls == 1
    assert len(live.calls) == 1


async def test_live_calls_are_throttled_to_twenty_five_a_minute(tmp_path: Path) -> None:
    from app.ai.providers import ChatMessage

    live = FakeProvider(script=[{"action": "BUILD"}, {"action": "TEST"}])
    now = [1000.0]
    waits: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)
        now[0] += seconds

    cached = er_run.CachedLiveProvider(live, tmp_path, clock=lambda: now[0], sleep=fake_sleep)
    await cached.complete_json(
        schema={}, system="a", messages=[ChatMessage("user", "a")], model="m"
    )
    await cached.complete_json(
        schema={}, system="b", messages=[ChatMessage("user", "b")], model="m"
    )

    assert waits == [pytest.approx(60 / 25)]


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------


def test_the_report_never_tables_an_unreviewed_run(tmp_path: Path) -> None:
    runs = [
        {
            "name": "smoke",
            "run": {"parser": "rules", "for_reporting": False},
            "metrics": em.score([prediction()]),
        }
    ]

    markdown = er.render_markdown(runs)

    assert "No run is reportable yet" in markdown
    assert "needs_review" in markdown
    assert "| smoke |" not in markdown


def test_a_reviewed_run_is_tabled(tmp_path: Path) -> None:
    runs = [
        {
            "name": "final",
            "run": {"parser": "rules", "for_reporting": True},
            "metrics": em.score([prediction()]),
        }
    ]

    assert "| final | rules | 1 |" in er.render_markdown(runs)
