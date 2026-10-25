"""The evaluation harness (``eval/``).

Its numbers go into a dissertation, so the tests that matter are about integrity: a draft cannot
pass itself off as reviewed, an unscored metric is null rather than zero, a model's failure is never
scored with the rules' answer in its place, and an interrupted run resumes instead of re-spending
quota.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eval import curation as cu  # noqa: E402
from eval import dataset as ds  # noqa: E402
from eval import metrics as em  # noqa: E402
from eval import report as er  # noqa: E402
from eval import runner as er_run  # noqa: E402

from app.ai.intent import Action, Intent  # noqa: E402
from app.ai.prompting import load_prompt  # noqa: E402
from app.ai.providers import FakeProvider, ProviderUnavailableError, RateLimitedError  # noqa: E402
from app.ai.providers.base import ChatMessage, LLMProvider, ParsedResult  # noqa: E402
from app.ai.validator import IntentValidator, IssueKind  # noqa: E402
from app.generation.planner import default_plan  # noqa: E402
from app.services.catalog import Catalog  # noqa: E402

CATALOG = REPO_ROOT / "catalog" / "services.yaml"
SAMPLE = REPO_ROOT / "eval" / "datasets" / "sample.jsonl"
V1 = REPO_ROOT / "eval" / "datasets" / "eval-v1.jsonl"
V1_SOURCE = REPO_ROOT / "eval" / "datasets" / "eval-v1.source.yaml"


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
        config(tmp_path, path, parser="groq:m", plans=False),
        ds.load_dataset(path),
        catalog,
        provider=first,
        log=lambda _: None,
    )

    second = FakeProvider(per_model={"m": [good]})
    report = await er_run.run(
        config(tmp_path, path, parser="groq:m", plans=False),
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


# ---------------------------------------------------------------------------
# eval-v1, the curated dataset (D-081)
# ---------------------------------------------------------------------------


def test_eval_v1_has_the_size_mix_and_split_4_9_asks_for() -> None:
    dataset = ds.load_dataset(V1)

    assert len(dataset.items) == 250
    assert Counter(item.split for item in dataset.items) == {"dev": 100, "test": 150}
    assert dataset.warnings == ()
    cells = Counter((item.category, item.split) for item in dataset.items)
    for category, sizes in cu.CATEGORY_SPLITS.items():
        assert (cells[(category, "dev")], cells[(category, "test")]) == (
            sizes["dev"],
            sizes["test"],
        )


def test_eval_v1_is_machine_labelled_and_never_claims_a_review() -> None:
    """No person reviewed these labels, and nothing in the file may say otherwise."""
    dataset = ds.load_dataset(V1)

    assert dataset.machine_labelled
    assert dataset.card is not None and dataset.card["reviewed_by_a_person"] == 0
    assert all(item.labeled_by == ds.MACHINE_LABELER for item in dataset.items)
    assert all(item.needs_review for item in dataset.items)
    assert dataset.scorable == ()


def test_eval_v1_matches_a_rebuild_from_its_source() -> None:
    """The JSONL is generated, never edited: the same source and seed give the same bytes."""
    report = cu.build(
        V1_SOURCE, CATALOG, example_texts=[example.user for example in load_prompt().examples]
    )

    assert cu.render_jsonl(report.items) == V1.read_bytes()
    assert cu.render_card(report.card) == ds.card_path(V1).read_bytes()


def test_eval_v1_carries_the_ablation_subset_and_the_end_to_end_sample() -> None:
    dataset = ds.load_dataset(V1)
    ablation = [item for item in dataset.items if item.ablation]
    e2e = [item for item in dataset.items if item.e2e]

    assert len(ablation) == 75
    assert all(item.split == "test" for item in ablation + e2e)
    assert Counter(item.category for item in ablation) == {
        "clear": 30,
        "paraphrase_typos": 15,
        "missing_field": 12,
        "ambiguous": 8,
        "unsafe_out_of_scope": 7,
        "prompt_injection": 3,
    }
    assert len(e2e) == 20
    assert Counter(item.assistant for item in e2e) == {"freestyle": 10, "pipeline": 10}
    assert Counter(item.gold_intent["action"] for item in e2e) == dict.fromkeys(
        cu.GENERATING_ACTIONS, 5
    )
    assert all(item.gold_behavior == "GENERATE" for item in e2e)
    assert all(item.gold_intent.get("branch") in (None, "main") for item in e2e)


def test_eval_v1_repeats_no_few_shot_example() -> None:
    dataset = ds.load_dataset(V1)

    assert ds.overlap_with_examples(dataset, [ex.user for ex in load_prompt().examples]) == []


@pytest.mark.parametrize(
    ("gold", "role", "expected"),
    [
        ({"action": "UNSUPPORTED"}, "ADMIN", "REFUSE"),
        ({"action": "DEPLOY", "environment": "production"}, "DEVELOPER", "REFUSE"),
        (
            {
                "action": "DEPLOY",
                "service": "auth-service",
                "environment": "production",
                "urgency": "HIGH",
            },
            "DEVELOPER",
            "REFUSE",
        ),
        ({"action": "STATUS"}, "DEVELOPER", "GENERATE"),
        ({"action": "CANCEL"}, "DEVOPS", "GENERATE"),
        ({"action": "BUILD"}, "DEVOPS", "CLARIFY"),
        ({"action": "BUILD", "service": "auth-service"}, "DEVELOPER", "GENERATE"),
        ({"action": "TEST", "service": "payment-service"}, "DEVELOPER", "CLARIFY"),
        ({"action": "TEST", "service": "auth-service"}, "DEVELOPER", "GENERATE"),
        (
            {"action": "TEST", "service": "auth-service", "test_suite": "integration"},
            "DEVELOPER",
            "CLARIFY",
        ),
        ({"action": "DEPLOY", "service": "auth-service"}, "ADMIN", "CLARIFY"),
        (
            {
                "action": "DEPLOY",
                "service": "auth-service",
                "environment": "staging",
                "urgency": "HIGH",
            },
            "DEVELOPER",
            "CLARIFY",
        ),
        (
            {
                "action": "DEPLOY",
                "service": "auth-service",
                "environment": "staging",
                "urgency": "HIGH",
            },
            "DEVOPS",
            "GENERATE",
        ),
        (
            {
                "action": "DEPLOY",
                "service": "auth-service",
                "environment": "staging",
                "urgency": "HIGH",
                "justification": "the demo is at three",
            },
            "DEVELOPER",
            "GENERATE",
        ),
    ],
)
def test_the_label_rules_follow_4_5_4_and_4_5_5(
    gold: dict[str, Any], role: str, expected: str
) -> None:
    assert cu.expected_behavior(gold, role, cu.read_catalog(CATALOG))[0] == expected


def source_item(**overrides: Any) -> cu.SourceItem:
    fields: dict[str, Any] = {
        "key": "x001",
        "category": "clear",
        "role": "DEVELOPER",
        "text": "Build payment-service from main",
        "gold": {"action": "BUILD", "service": "payment-service", "branch": "main"},
        "behavior": "GENERATE",
        "notes": "",
        "source": "authored",
        "source_ref": "",
        "split": None,
        "labeled_by": ds.MACHINE_LABELER,
        "needs_review": True,
    }
    fields.update(overrides)
    return cu.SourceItem(**fields)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"gold": {"action": "BUILD", "service": "billing-service"}}, "not in the catalog"),
        (
            {"gold": {"action": "BUILD", "service": "payment-service", "branch": "develop"}},
            "copied exactly",
        ),
        ({"gold": {"action": "UNSUPPORTED", "service": "payment-service"}}, "no other field"),
        ({"gold": {"action": "BUILD", "service": "payment-service", "commit": "abc"}}, "SHA"),
        (
            {
                "gold": {
                    "action": "BUILD",
                    "service": "payment-service",
                    "urgency": "HIGH",
                    "justification": "because I said so",
                }
            },
            "user's words",
        ),
        ({"behavior": "CLARIFY"}, "the rules give GENERATE"),
        ({"needs_review": False}, "cannot claim"),
        ({"source": "clinc150"}, "source_ref"),
        ({"text": "x" * 1001}, "1 to 1000"),
    ],
)
def test_a_label_that_breaks_a_rule_is_refused(overrides: dict[str, Any], message: str) -> None:
    problems = cu.check_item(source_item(**overrides), cu.read_catalog(CATALOG))

    assert any(message in problem for problem in problems), problems


def write_source(path: Path, entries: list[dict[str, Any]]) -> Path:
    source = {"version": 1, "defaults": {"role": "DEVELOPER"}, "categories": {"clear": entries}}
    path.write_text(yaml.safe_dump(source), encoding="utf-8")
    return path


def test_the_build_refuses_a_repeated_text_and_a_few_shot_example(tmp_path: Path) -> None:
    entry = {
        "text": "Build payment-service from main",
        "gold": {"action": "BUILD", "service": "payment-service", "branch": "main"},
        "behavior": "GENERATE",
    }
    source = write_source(tmp_path / "s.yaml", [{"key": "x001", **entry}, {"key": "x002", **entry}])

    with pytest.raises(cu.CurationError, match="same text as x001") as exc:
        cu.build(source, CATALOG, example_texts=["build payment-service from MAIN"])

    assert "repeats a few-shot example" in str(exc.value)


def test_near_duplicates_in_different_splits_are_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Leakage: tuning on a development item would also tune on its test twin."""
    monkeypatch.setattr(cu, "NEAR_DUPLICATE", 0.6)

    with pytest.raises(cu.CurationError, match="near-duplicates fall in different splits"):
        cu.build(V1_SOURCE, CATALOG, example_texts=[])


def test_allocation_is_largest_remainder() -> None:
    # 1.5, 1.5 and 2.0: the one seat left goes to the first of the two tied remainders.
    assert cu.allocate({"a": 3, "b": 3, "c": 4}, 5) == {"a": 2, "b": 1, "c": 2}
    assert sum(cu.allocate({"a": 7, "b": 1}, 4).values()) == 4


# ---------------------------------------------------------------------------
# Machine-labelled datasets in the loader and the runner (D-081)
# ---------------------------------------------------------------------------


def write_machine_dataset(
    path: Path, items: list[dict[str, Any]], *, sha256: str | None = None
) -> Path:
    write_dataset(path, items)
    digest = sha256 or hashlib.sha256(path.read_bytes()).hexdigest()
    ds.card_path(path).write_text(
        json.dumps({"name": "m", "labels": "machine", "sha256": digest, "decision": "D-081"}),
        encoding="utf-8",
    )
    return path


def machine_item(index: int = 1, **overrides: Any) -> dict[str, Any]:
    return raw_item(index, **{"labeled_by": ds.MACHINE_LABELER, "needs_review": True, **overrides})


def test_machine_labelled_items_need_a_card(tmp_path: Path) -> None:
    path = write_dataset(tmp_path / "d.jsonl", [machine_item()])

    with pytest.raises(ds.DatasetError, match="needs a card"):
        ds.load_dataset(path)


def test_a_machine_labelled_item_cannot_claim_a_review(tmp_path: Path) -> None:
    path = write_machine_dataset(tmp_path / "d.jsonl", [machine_item(needs_review=False)])

    with pytest.raises(ds.DatasetError, match="needs_review"):
        ds.load_dataset(path)


def test_a_file_edited_without_rebuilding_is_refused(tmp_path: Path) -> None:
    path = write_machine_dataset(tmp_path / "d.jsonl", [machine_item()], sha256="0" * 64)

    with pytest.raises(ds.DatasetError, match="checksum"):
        ds.load_dataset(path)


async def test_a_machine_labelled_run_is_reportable_with_its_provenance(
    tmp_path: Path, catalog: Catalog
) -> None:
    path = write_machine_dataset(tmp_path / "d.jsonl", [machine_item()])

    report = await er_run.run(
        config(tmp_path, path, include_unreviewed=True),
        ds.load_dataset(path),
        catalog,
        log=lambda _: None,
    )

    assert report["run"]["labels"] == "machine"
    assert report["run"]["for_reporting"] is True
    assert "Claude Code" in report["warning"] and "D-081" in report["warning"]
    assert report["dataset"]["card"]["labels"] == "machine"


async def test_split_and_subset_choose_the_items(tmp_path: Path, catalog: Catalog) -> None:
    path = write_dataset(
        tmp_path / "d.jsonl",
        [
            raw_item(1, split="dev"),
            raw_item(2, text="Build auth-service from main", split="test"),
            raw_item(3, text="Build auth-service from develop", split="test", ablation=True),
        ],
    )
    dataset = ds.load_dataset(path)

    test_only = await er_run.run(
        config(tmp_path, path, split="test"), dataset, catalog, log=lambda _: None
    )
    ablation = await er_run.run(
        config(tmp_path, path, subset="ablation", fresh=True), dataset, catalog, log=lambda _: None
    )

    assert test_only["metrics"]["n"] == 2
    assert ablation["metrics"]["n"] == 1


@pytest.mark.parametrize(
    ("split", "subset", "repairs", "name"),
    [
        ("test", None, 2, "eval-v1-test__groq-m"),
        (None, "ablation", 2, "eval-v1-ablation__groq-m"),
        (None, "ablation", 0, "eval-v1-ablation__groq-m__no-repair"),
    ],
)
def test_a_split_subset_or_repair_budget_gets_its_own_directory(
    split: str | None, subset: str | None, repairs: int, name: str
) -> None:
    out = er_run.default_out_dir(
        "groq:m",
        V1,
        include_examples=True,
        include_enums=True,
        split=split,
        subset=subset,
        max_repairs=repairs,
    )

    assert out.name == name


# ---------------------------------------------------------------------------
# Pacing, latency and the disk cache
# ---------------------------------------------------------------------------


class HeaderProvider(LLMProvider):
    """Answers like Groq: with the minute's remaining tokens in the headers."""

    name = "headers"

    def __init__(self, remaining: int, limit: int = 8000, tokens: int = 1000) -> None:
        self.remaining, self.limit, self.tokens = remaining, limit, tokens

    async def complete_json(
        self,
        *,
        schema: dict[str, Any],
        system: str,
        messages: list[ChatMessage],
        model: str,
        reasoning_effort: str = "low",
    ) -> ParsedResult:
        return ParsedResult(
            data={"action": "BUILD"},
            provider=self.name,
            model=model,
            prompt_tokens=self.tokens,
            completion_tokens=0,
            latency_ms=7,
            rate_limit={
                "x-ratelimit-remaining-tokens": str(self.remaining),
                "x-ratelimit-limit-tokens": str(self.limit),
            },
        )

    def stream_text(self, **_: Any) -> Any:
        raise NotImplementedError


async def test_a_live_call_waits_for_the_tokens_the_minute_has_left(tmp_path: Path) -> None:
    """A 1,000-token prompt last time, 500 left: the next is admitted against its prompt and its
    1,024-token completion allowance, plus 5%, so it waits for the shortfall at 8,000 a minute."""
    now = [1000.0]
    waits: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)
        now[0] += seconds

    cached = er_run.CachedLiveProvider(
        HeaderProvider(remaining=500), tmp_path, clock=lambda: now[0], sleep=fake_sleep
    )
    await cached.complete_json(
        schema={}, system="a", messages=[ChatMessage("user", "a")], model="m"
    )
    await cached.complete_json(
        schema={}, system="b", messages=[ChatMessage("user", "b")], model="m"
    )

    needed = (1000 + er_run.MAX_COMPLETION_TOKENS) * er_run.TOKEN_MARGIN
    assert waits == [pytest.approx((needed - 500) * 60 / 8000)]


async def test_a_per_minute_429_is_waited_out_and_a_daily_one_is_not(tmp_path: Path) -> None:
    """A minute's limit clears in seconds; the day's must stop the run (4.9)."""
    waits: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)

    minute = RateLimitedError("tpm", retry_after=3.0)
    live = FakeProvider(script=[minute, {"action": "BUILD"}])
    cached = er_run.CachedLiveProvider(live, tmp_path, per_minute=10**9, sleep=fake_sleep)

    answer = await cached.complete_json(
        schema={}, system="s", messages=[ChatMessage("user", "a")], model="m"
    )
    assert answer.data == {"action": "BUILD"}
    assert cached.transient_waits == 1
    assert 3.0 in waits

    daily = RateLimitedError("tpd", retry_after=40_000, exhausted=True)
    spent = er_run.CachedLiveProvider(
        FakeProvider(script=[daily]), tmp_path / "b", per_minute=10**9, sleep=fake_sleep
    )
    with pytest.raises(RateLimitedError):
        await spent.complete_json(
            schema={}, system="s", messages=[ChatMessage("user", "b")], model="m"
        )
    assert spent.transient_waits == 0


async def test_a_429_asking_for_seconds_is_waited_out_though_called_exhausted(
    tmp_path: Path,
) -> None:
    """Groq's provider calls a wait over 20 s exhaustion, for a user's sake; the eval waits it out.
    Seen live on 2026-10-25: qwen3.8-27b asked for 27 s and stopped a run for a "daily budget"."""
    waits: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)

    short = RateLimitedError("tpm", retry_after=27.0, exhausted=True)
    cached = er_run.CachedLiveProvider(
        FakeProvider(script=[short, {"action": "BUILD"}]),
        tmp_path,
        per_minute=10**9,
        sleep=fake_sleep,
    )

    answer = await cached.complete_json(
        schema={}, system="s", messages=[ChatMessage("user", "a")], model="m"
    )

    assert answer.data == {"action": "BUILD"}
    assert 27.0 in waits


async def test_cached_answers_spend_no_quota_and_are_marked_cached(
    tmp_path: Path, catalog: Catalog
) -> None:
    """The backend's tracker would count a replay against the day; here the server judges."""
    path = write_dataset(
        tmp_path / "d.jsonl",
        [
            raw_item(index, text=f"Build payment-service from main, take {index}")
            for index in range(5)
        ],
    )
    # Far over 4.5.1's per-minute and per-day token limits if they were counted locally.
    huge = FakeProvider(
        responder=lambda s, m, sc, mo: Intent(
            action=Action.BUILD, service="payment-service"
        ).to_card(),
        prompt_tokens=90_000,
    )
    live = er_run.CachedLiveProvider(huge, tmp_path / "cache", per_minute=10**9)

    first = await er_run.run(
        config(tmp_path, path, parser="groq:m", plans=False),
        ds.load_dataset(path),
        catalog,
        provider=live,
        log=lambda _: None,
    )
    again = er_run.CachedLiveProvider(huge, tmp_path / "cache", per_minute=10**9)
    second = await er_run.run(
        config(tmp_path, path, parser="groq:m", plans=False, fresh=True),
        ds.load_dataset(path),
        catalog,
        provider=again,
        log=lambda _: None,
    )

    assert first["run"]["complete"] and first["metrics"]["errors"] == 0
    assert second["run"]["complete"] and again.live_calls == 0
    assert second["metrics"]["cache_hits"] == 5
    assert second["metrics"]["latency_ms"]["median"] is None


async def test_latency_is_the_answering_calls_and_waits_are_elapsed(
    tmp_path: Path, catalog: Catalog
) -> None:
    path = write_dataset(tmp_path / "d.jsonl", [raw_item(1)])

    await er_run.run(
        config(tmp_path, path, parser="groq:m", plans=False),
        ds.load_dataset(path),
        catalog,
        provider=FakeProvider(per_model={"m": [Intent(action=Action.BUILD).to_card()]}),
        log=lambda _: None,
    )

    saved = json.loads((tmp_path / "out" / "predictions.jsonl").read_text(encoding="utf-8"))
    assert saved["latency_ms"] == 1  # FakeProvider's own latency
    assert saved["elapsed_ms"] >= 0
    assert [call["outcome"] for call in saved["calls"]] == ["ok"]


# ---------------------------------------------------------------------------
# Plan validity (4.9)
# ---------------------------------------------------------------------------


def good_plan(catalog: Catalog) -> dict[str, Any]:
    service = catalog.get("payment-service")
    assert service is not None
    intent = Intent(action=Action.BUILD, service="payment-service", branch="main")
    return default_plan(intent, service).model_dump(mode="json")


async def test_plan_validity_before_and_after_repair(tmp_path: Path, catalog: Catalog) -> None:
    path = write_dataset(tmp_path / "d.jsonl", [raw_item(1)])
    card = Intent(action=Action.BUILD, service="payment-service", branch="main").to_card()
    provider = FakeProvider(per_model={"m": [card, {"stages": []}, good_plan(catalog)]})

    report = await er_run.run(
        config(tmp_path, path, parser="groq:m"),
        ds.load_dataset(path),
        catalog,
        provider=provider,
        log=lambda _: None,
    )

    plans = report["plans"]
    assert (plans["n"], plans["valid_before_repair"], plans["valid_after_repair"]) == (1, 0.0, 1.0)
    assert plans["repaired"] == 1


async def test_no_repair_loop_keeps_the_first_plan(tmp_path: Path, catalog: Catalog) -> None:
    """4.9's ablation: with no repair, an invalid first plan stays invalid."""
    path = write_dataset(tmp_path / "d.jsonl", [raw_item(1)])
    card = Intent(action=Action.BUILD, service="payment-service", branch="main").to_card()
    provider = FakeProvider(per_model={"m": [card, {"stages": []}, good_plan(catalog)]})

    report = await er_run.run(
        config(tmp_path, path, parser="groq:m", max_repairs=0),
        ds.load_dataset(path),
        catalog,
        provider=provider,
        log=lambda _: None,
    )

    assert (report["plans"]["valid_before_repair"], report["plans"]["valid_after_repair"]) == (
        0.0,
        0.0,
    )
    assert provider.calls_to("m") == 2  # the parse and one plan, no repair


async def test_a_budget_stop_while_planning_saves_the_parse(
    tmp_path: Path, catalog: Catalog
) -> None:
    path = write_dataset(tmp_path / "d.jsonl", [raw_item(1)])
    card = Intent(action=Action.BUILD, service="payment-service", branch="main").to_card()
    daily = RateLimitedError("daily", retry_after=40_000, exhausted=True)
    provider = FakeProvider(per_model={"m": [card, daily]})

    report = await er_run.run(
        config(tmp_path, path, parser="groq:m"),
        ds.load_dataset(path),
        catalog,
        provider=provider,
        log=lambda _: None,
    )

    assert report["run"]["complete"] is False
    assert "stopped planning" in report["run"]["stopped_reason"]
    assert report["metrics"]["n"] == 1
    assert report["plans"]["planned"] == 0


def test_score_plans_counts_what_no_model_answered_apart() -> None:
    records = [
        {"valid_before_repair": True, "valid_after_repair": True, "request": {"a": 1}},
        {"valid_before_repair": False, "valid_after_repair": True, "request": {"a": 1}},
        {"valid_before_repair": False, "valid_after_repair": False, "request": {"a": 2}},
        {"valid_before_repair": None, "valid_after_repair": None},
        {"error": "the spec could not be built"},
    ]

    result = em.score_plans(records, plannable_items=6)

    assert (result["n"], result["valid_before_repair"], result["valid_after_repair"]) == (
        3,
        0.3333,
        0.6667,
    )
    assert (result["no_model_plan"], result["errors"], result["distinct_requests"]) == (1, 1, 2)


# ---------------------------------------------------------------------------
# The report and the Analytics page
# ---------------------------------------------------------------------------


def a_run(name: str, parser: str, **meta: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "parser": parser,
        "for_reporting": True,
        "labels": "machine",
        "split": "test",
        "subset": None,
        "include_examples": True,
        "include_enums": True,
        "max_repairs": 2,
        "complete": True,
    }
    fields.update(meta)
    plans = (
        em.score_plans(
            [{"valid_before_repair": True, "valid_after_repair": True, "request": {}}],
            plannable_items=1,
        )
        if parser != "rules"
        else None
    )
    return {"name": name, "run": fields, "metrics": em.score([prediction()]), "plans": plans}


def report_runs() -> list[dict[str, Any]]:
    return [
        a_run("eval-v1-test__groq-m", "groq:m"),
        a_run("eval-v1-test__rules", "rules"),
        a_run("eval-v1-ablation__groq-m", "groq:m", split=None, subset="ablation"),
        a_run(
            "eval-v1-ablation__groq-m__no-enums",
            "groq:m",
            split=None,
            subset="ablation",
            include_enums=False,
        ),
        a_run("eval-v1-ablation__rules", "rules", split=None, subset="ablation"),
        {
            "name": "eval-v1-e2e__groq-m",
            "run": {"kind": "e2e", "model": "m", "for_reporting": True, "labels": "machine"},
            "summary": {
                "n": 2,
                "expected": 2,
                "succeeded": 1,
                "success_rate": 0.5,
                "failed_at": {"ran": 1},
                "by_assistant": {"freestyle": {"n": 1, "succeeded": 1}},
            },
        },
    ]


def test_the_report_puts_the_provenance_above_machine_labelled_figures() -> None:
    markdown = er.render_markdown(report_runs())

    assert markdown.index("**Provenance.**") < markdown.index("## Comparison on the test split")
    assert "Claude Code" in markdown and "D-081" in markdown
    # The rule baseline is tabled first, then the models.
    comparison = markdown.split("## Comparison on the test split")[1]
    assert comparison.index("| rules |") < comparison.index("| groq:m |")
    assert "| no catalog enums |" in markdown
    assert "## End to end against jenkins-dev" in markdown


def test_the_report_is_exactly_what_the_analytics_endpoint_serves() -> None:
    """A contract test: the generator's JSON must validate against the page's schema."""
    from app.api.analytics import EvaluationResponse

    report = json.loads(json.dumps(er.build_report(report_runs())))
    served = EvaluationResponse.model_validate({**report, "available": True, "detail": None})

    assert [row.parser for row in served.comparison] == ["rules", "groq:m"]
    assert served.ablations is not None and served.ablations.parser == "groq:m"
    assert [row.configuration for row in served.ablations.rows] == ["full", "no-enums"]
    assert served.e2e[0].failed_at == {"ran": 1}
    assert served.provenance is not None and served.provenance.labels == "machine"


def test_an_incomplete_run_is_tabled_as_incomplete() -> None:
    markdown = er.render_markdown([a_run("eval-v1-test__groq-m", "groq:m", complete=False)])

    assert "| groq:m (incomplete) |" in markdown
