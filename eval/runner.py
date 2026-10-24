"""Running a parser over a dataset.

What is held fixed and what varies is the point of a comparison, so it is stated here:

* **The pipeline is fixed.** Every parser runs through the same ``IntentParser`` -- guard,
  validator, policy, clarification -- and only the parse step changes. The rule baseline is the
  pipeline with an empty model chain, not a different code path.
* **Repository state is factored out.** The Git client accepts every well-formed branch and commit,
  so a parser is never marked wrong because a sample repository is unpushed or a branch was
  deleted. It is label-free -- it never looks at the gold answer -- so it cannot leak the label into
  the prediction. Whether real branches resolve is Phase 5's end-to-end measurement.
* **A model run is never rescued by the rules.** In production a failed model call falls back to
  the rule parser; here that would score the rules' answer as the model's. A model run uses a
  single-model chain, and an item the model did not answer is recorded as an error and excluded
  from accuracy -- reported in ``errors`` rather than hidden.

Quota safety, from 4.9: answers are cached on disk by prompt hash (a rerun costs nothing), live
calls are throttled to 25 a minute, a run resumes where it stopped, and it stops with a clear
message when a model's daily budget is reached rather than quietly scoring fallbacks.

**Pacing comes from the server, not from local counters.** The backend's ``QuotaTracker`` counts
every answer against the model's limits, including answers this harness replays from its disk
cache, so a cached rerun would wait out minutes it never spent and could stop for a "daily budget"
it never used. Here the chain gets limits it never reaches, and ``CachedLiveProvider`` paces only
live calls, from the ``x-ratelimit-*`` headers of the call before. Groq still has the last word: a
429 for the day stops the run.

**Latency is the model's.** A prediction's ``latency_ms`` is the answering call's own time; time
spent waiting for quota is ``elapsed_ms``, kept beside it and never mixed in.

**Plan validity (4.9)** is measured on each item's *gold* intent, after the validator, so a parse
error cannot cost the planner and every model plans the same requests. The planner is the
backend's own, with the run's model; ``max_repairs=0`` is the "no repair loop" ablation.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from app.ai.cache import ResponseCache
from app.ai.chain import CallRecord, ModelChain
from app.ai.clarify import ClarificationService
from app.ai.intent import GENERATING_ACTIONS, Intent
from app.ai.parser import IntentParser
from app.ai.policy import PolicyContext, PolicyService
from app.ai.prompting import load_prompt
from app.ai.providers import (
    ChatMessage,
    FakeProvider,
    GroqProvider,
    LLMProvider,
    ParsedResult,
    RecordingProvider,
    ReplayMissError,
    ReplayProvider,
)
from app.ai.quota import ModelLimits, QuotaTracker
from app.ai.rules import RuleBasedParser
from app.ai.validator import IntentValidator
from app.db.models import Role
from app.generation.planner import MAX_REPAIRS, Planner, PlannerError, PlanRequest
from app.generation.spec import Assistant
from app.services.catalog import Catalog
from app.services.git import GitClient, Ref
from eval.dataset import Dataset, Item
from eval.metrics import Prediction, score, score_plans

REPO_ROOT: Final = Path(__file__).resolve().parents[1]
# eval/.cache, the directory .gitignore has reserved for this since Phase 0.
CACHE_DIR: Final = REPO_ROOT / "eval" / ".cache"
RESULTS_DIR: Final = REPO_ROOT / "eval" / "results"

# 4.9: "throttle to 25 requests per minute".
REQUESTS_PER_MINUTE: Final = 25

# The eval can afford to wait out a per-minute limit; a fallback would contaminate the comparison.
EVAL_MAX_WAIT: Final = 65.0

# Limits the chain never reaches: the server is the judge (module docstring).
UNREACHABLE: Final = ModelLimits(
    requests_per_minute=1_000_000,
    requests_per_day=1_000_000_000,
    tokens_per_minute=1_000_000_000,
    tokens_per_day=1_000_000_000_000,
)

# A fallback reason that means the quota, not the model, said no. "remaining" is the server's
# "no requests remaining today"; "rate limited" covers a 429 the chain could not wait out.
_QUOTA_REASON: Final = re.compile(r"rate limited|daily|limit|remaining|quota")

# The next live call is assumed to cost this much more than the last one did.
TOKEN_MARGIN: Final = 1.25

SUBSETS: Final = ("ablation", "e2e")


class BudgetExhaustedError(RuntimeError):
    """A model's daily budget ran out mid-run. Progress is saved; rerun later to resume."""


class _EveryRef(tuple[str, ...]):
    """A branch list that contains every branch: see the module docstring."""

    def __contains__(self, item: object) -> bool:
        return isinstance(item, str)


class AcceptAllGitClient(GitClient):
    """Every well-formed ref exists. The validator still refuses malformed ones (D-023)."""

    async def list_refs(self, repo_url: str) -> tuple[Ref, ...]:
        return ()

    async def list_branches(self, repo_url: str) -> tuple[str, ...]:
        return _EveryRef()

    async def resolve(self, repo_url: str, ref: str) -> str | None:
        return "0" * 40

    async def commit_exists(self, repo_url: str, commit: str, *, branch: str | None = None) -> bool:
        return True


def _header_int(value: str | None) -> int | None:
    try:
        return int(float(value)) if value is not None else None
    except ValueError:
        return None


class CachedLiveProvider(LLMProvider):
    """Disk cache by prompt hash first, then the live model, throttled.

    The cache is the replay fixture format, so a finished evaluation run doubles as a fixture set.
    Live calls are paced to 25 a minute, and to the tokens the server last said were left in the
    minute; a cached answer waits for nothing.
    """

    def __init__(
        self,
        live: LLMProvider,
        directory: Path,
        *,
        per_minute: int = REQUESTS_PER_MINUTE,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Any] = asyncio.sleep,
    ) -> None:
        self._replay = ReplayProvider(directory)
        self._recorder = RecordingProvider(live, directory)
        self._interval = 60.0 / per_minute
        self._last_live = -1e9
        self._clock = clock
        self._sleep = sleep
        self._last_cost = 0
        self._tokens_left: int | None = None
        self._tokens_limit: int | None = None
        self._tokens_seen_at = 0.0
        self.name = live.name
        self.live_calls = 0
        self.cache_hits = 0

    async def complete_json(
        self,
        *,
        schema: dict[str, Any],
        system: str,
        messages: list[ChatMessage],
        model: str,
        reasoning_effort: str = "low",
    ) -> ParsedResult:
        try:
            cached = await self._replay.complete_json(
                schema=schema, system=system, messages=messages, model=model
            )
        except ReplayMissError:
            pass
        else:
            self.cache_hits += 1
            return cached
        wait = max(self._interval - (self._clock() - self._last_live), self._token_wait())
        if wait > 0:
            await self._sleep(wait)
        self._last_live = self._clock()
        self.live_calls += 1
        result = await self._recorder.complete_json(
            schema=schema,
            system=system,
            messages=messages,
            model=model,
            reasoning_effort=reasoning_effort,
        )
        self._observe(result)
        return result

    def _token_wait(self) -> float:
        """Seconds until the minute's bucket holds the next call, from the last call's headers.

        Groq refills tokens continuously at the per-minute limit; the headers give what was left
        and the limit, so the wait is the shortfall at that rate.
        """
        if self._tokens_left is None or not self._tokens_limit or not self._last_cost:
            return 0.0
        needed = self._last_cost * TOKEN_MARGIN
        refilled = (self._clock() - self._tokens_seen_at) * self._tokens_limit / 60.0
        shortfall = needed - (self._tokens_left + refilled)
        return max(0.0, shortfall * 60.0 / self._tokens_limit)

    def _observe(self, result: ParsedResult) -> None:
        self._last_cost = result.prompt_tokens + result.completion_tokens
        left = _header_int(result.rate_limit.get("x-ratelimit-remaining-tokens"))
        limit = _header_int(result.rate_limit.get("x-ratelimit-limit-tokens"))
        if left is not None and limit:
            self._tokens_left, self._tokens_limit = left, limit
            self._tokens_seen_at = self._clock()

    def stream_text(
        self,
        *,
        system: str,
        messages: list[ChatMessage],
        model: str,
        reasoning_effort: str = "low",
    ) -> AsyncIterator[str]:
        """Not cached: the evaluation scores structured intents, never streamed prose."""
        return self._recorder.stream_text(
            system=system, messages=messages, model=model, reasoning_effort=reasoning_effort
        )

    async def aclose(self) -> None:
        await self._recorder.aclose()


@dataclass(frozen=True)
class RunConfig:
    parser: str  # "rules", "fake", or "groq:<model>"
    dataset: Path
    out_dir: Path
    include_unreviewed: bool = False
    include_examples: bool = True
    include_enums: bool = True
    fresh: bool = False
    #: Only this split ("dev" or "test"), or every item when None.
    split: str | None = None
    #: Only 4.9's ablation subset, or the end-to-end sample.
    subset: str | None = None
    #: 4.6.2's repair budget; 0 is the "no repair loop" ablation.
    max_repairs: int = MAX_REPAIRS
    #: Measure plan validity on the gold intents (model runs only).
    plans: bool = True

    @property
    def model(self) -> str | None:
        return self.parser.split(":", 1)[1] if self.parser.startswith("groq:") else None


def labels_tier(config: RunConfig, dataset: Dataset) -> str:
    """Who wrote the gold labels this run is scored against.

    * ``human``: only items a person reviewed (the default; 4.9).
    * ``machine``: a dataset whose card declares machine labels (D-081). Reportable, with that
      provenance printed beside every figure.
    * ``draft``: drafts still awaiting review, scored to test the harness. Never reportable.
    """
    if not config.include_unreviewed:
        return "human"
    return "machine" if dataset.machine_labelled else "draft"


def default_out_dir(
    parser: str,
    dataset: Path,
    *,
    include_examples: bool,
    include_enums: bool,
    split: str | None = None,
    subset: str | None = None,
    max_repairs: int = MAX_REPAIRS,
) -> Path:
    """One directory per configuration, so rerunning the same command resumes the same run."""
    slug = re.sub(r"[^A-Za-z0-9.]+", "-", parser).strip("-")
    scope = f"-{subset}" if subset else f"-{split}" if split else ""
    ablations = []
    if not include_examples:
        ablations.append("no-examples")
    if not include_enums:
        ablations.append("no-enums")
    if max_repairs == 0:
        ablations.append("no-repair")
    suffix = "".join(f"__{name}" for name in ablations)
    return RESULTS_DIR / f"{dataset.stem}{scope}__{slug}{suffix}"


@dataclass(frozen=True)
class Harness:
    parser: IntentParser
    live: LLMProvider | None
    planner: Planner | None
    validator: IntentValidator


def build_parser(
    config: RunConfig,
    catalog: Catalog,
    *,
    groq_key: str | None = None,
    provider: LLMProvider | None = None,
) -> Harness:
    rules = RuleBasedParser(catalog)
    live: LLMProvider | None = provider
    planner: Planner | None = None
    validator = IntentValidator(catalog, AcceptAllGitClient())

    if config.parser == "rules":
        chain = ModelChain(FakeProvider(), (), quota=QuotaTracker(), cache=ResponseCache())
    elif config.parser == "fake":
        live = live or FakeProvider(
            responder=lambda s, m, sc, mo: rules.parse_intent(m[-1].content).to_card()
        )
        chain = ModelChain(live, ("fake-model",), quota=QuotaTracker(), cache=ResponseCache())
    elif config.model is not None:
        if live is None:
            if not groq_key:
                raise SystemExit(
                    f"{config.parser} needs GROQ_API_KEY in the environment or .env. "
                    "Use --parser rules to run without one."
                )
            live = CachedLiveProvider(GroqProvider(groq_key), CACHE_DIR)
        # One tracker for the parse and the plans, with limits it never reaches: the server
        # decides (module docstring).
        quota = QuotaTracker({config.model: UNREACHABLE})
        # One model, no fallback: a failure must count against this model, not be replaced by the
        # rules' answer.
        chain = ModelChain(
            live,
            (config.model,),
            quota=quota,
            cache=ResponseCache(),
            max_wait=EVAL_MAX_WAIT,
        )
        if config.plans:
            planner = Planner(
                chain=ModelChain(live, (config.model,), quota=quota, max_wait=EVAL_MAX_WAIT),
                catalog=catalog,
                prompt=load_prompt("planner_v1"),
            )
    else:
        raise SystemExit(f"unknown parser {config.parser!r}; use rules, fake or groq:<model>")

    parser = IntentParser(
        chain=chain,
        rules=rules,
        catalog=catalog,
        validator=validator,
        clarifier=ClarificationService(catalog),
        policy=PolicyService(),
        prompt=load_prompt("intent_v1"),
    )
    return Harness(parser=parser, live=live, planner=planner, validator=validator)


def _call_dicts(calls: tuple[CallRecord, ...]) -> list[dict[str, Any]]:
    return [
        {
            "provider": call.provider,
            "model": call.model,
            "outcome": call.outcome,
            "latency_ms": call.latency_ms,
            "prompt_tokens": call.prompt_tokens,
            "completion_tokens": call.completion_tokens,
        }
        for call in calls
    ]


def quota_stop(reasons: tuple[str, ...] | list[str]) -> str | None:
    joined = "; ".join(reasons)
    return joined if _QUOTA_REASON.search(joined) else None


async def predict(parser: IntentParser, item: Item, config: RunConfig) -> Prediction:
    started = time.perf_counter()
    outcome = await parser.interpret(
        item.text,
        context=PolicyContext(role=Role(item.role)),
        # Users in the dataset are assumed to have run something before, so "the status of my
        # last deploy" has a run to show rather than asking which service.
        has_recent_run=True,
        include_examples=config.include_examples,
        include_enums=config.include_enums,
    )
    elapsed = int((time.perf_counter() - started) * 1000)

    error: str | None = None
    if config.model is not None and outcome.parser == "RULES":
        stop = quota_stop(outcome.fallback_reasons)
        if stop is not None:
            raise BudgetExhaustedError(stop)
        error = f"the model did not answer: {'; '.join(outcome.fallback_reasons)}"

    # The answering call: the last that succeeded. A replayed answer (the disk cache) or one
    # from the in-memory cache has no latency of its own and is marked cached. The rule baseline
    # makes no call at all, so its latency is the pipeline's own time.
    answered = [call for call in outcome.calls if call.outcome in ("ok", "cached")]
    last = answered[-1] if answered else None
    cached = outcome.cached or (last is not None and last.provider == "replay")
    if not outcome.calls:
        latency = elapsed
    else:
        latency = last.latency_ms if last is not None and not cached else 0

    return Prediction(
        item_id=item.id,
        category=item.category,
        gold_intent=item.gold_intent,
        gold_behavior=item.gold_behavior,
        predicted_intent=outcome.model_intent.to_card(),
        predicted_behavior=outcome.behavior,
        latency_ms=latency,
        # Every attempt for this command, retries included: they spend quota too.
        prompt_tokens=sum(call.prompt_tokens for call in outcome.calls),
        completion_tokens=sum(call.completion_tokens for call in outcome.calls),
        parser=outcome.parser,
        model=outcome.model,
        ai_fallback=outcome.ai_fallback,
        cached=cached,
        error=error,
        elapsed_ms=elapsed,
        calls=_call_dicts(outcome.calls),
        role=item.role,
    )


def plannable(item: Item) -> bool:
    """Items whose gold intent the system would plan: a request that proceeds and makes jobs."""
    action = item.gold_intent.get("action")
    return (
        item.gold_behavior == "GENERATE"
        and action in {action.value for action in GENERATING_ACTIONS}
        and item.gold_intent.get("service") is not None
    )


async def plan_item(harness: Harness, item: Item, config: RunConfig) -> dict[str, Any]:
    """Plan the item's gold intent, as the validator passes it on, and record every attempt."""
    if harness.planner is None:
        raise RuntimeError("this run has no planner")
    gold, _ = Intent.from_untrusted({**item.gold_intent})
    validation = await harness.validator.validate(gold)
    record: dict[str, Any] = {
        "item_id": item.id,
        "category": item.category,
        "action": gold.action.value,
        "request": {
            "action": validation.intent.action.value,
            "service": validation.intent.service,
            "test_suite": validation.intent.test_suite,
            "environment": (
                validation.intent.environment.value if validation.intent.environment else None
            ),
            "extra_stages": sorted(stage.value for stage in validation.intent.extra_stages),
        },
        "max_repairs": config.max_repairs,
    }
    if validation.issues:
        record["error"] = "the gold intent does not pass the validator: " + "; ".join(
            issue.message for issue in validation.issues
        )
        return record
    request = PlanRequest(
        intent=validation.intent,
        assistant=Assistant.PIPELINE,
        resolved_branch=validation.resolved_branch,
        resolved_commit=validation.resolved_commit,
    )
    try:
        outcome = await harness.planner.plan(
            request, max_repairs=config.max_repairs, include_examples=config.include_examples
        )
    except PlannerError as exc:
        record["error"] = str(exc)
        return record
    if outcome.source == "default" and not outcome.model_attempts:
        stop = quota_stop(outcome.fallback_reasons)
        if stop is not None:
            raise BudgetExhaustedError(stop)
    attempts = outcome.model_attempts
    record.update(
        {
            "source": outcome.source,
            "model": outcome.model,
            "valid_before_repair": outcome.valid_before_repair,
            "valid_after_repair": outcome.valid_after_repair,
            "repairs": outcome.repairs,
            "model_attempts": len(attempts),
            "first_issues": list(attempts[0].issues) if attempts else [],
            "fallback_reasons": list(outcome.fallback_reasons),
            "prompt_tokens": sum(call.prompt_tokens for call in outcome.calls),
            "completion_tokens": sum(call.completion_tokens for call in outcome.calls),
            "calls": _call_dicts(outcome.calls),
        }
    )
    return record


def _load_done(path: Path) -> dict[str, Prediction]:
    done: dict[str, Prediction] = {}
    if not path.is_file():
        return done
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            raw = json.loads(line)
            done[raw["item_id"]] = Prediction(**raw)
    return done


def _load_plans(path: Path) -> dict[str, dict[str, Any]]:
    done: dict[str, dict[str, Any]] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                raw = json.loads(line)
                done[raw["item_id"]] = raw
    return done


def select_items(dataset: Dataset, config: RunConfig) -> list[Item]:
    items = list(dataset.items if config.include_unreviewed else dataset.scorable)
    if config.split is not None:
        items = [item for item in items if item.split == config.split]
    if config.subset == "ablation":
        items = [item for item in items if item.ablation]
    elif config.subset == "e2e":
        items = [item for item in items if item.e2e]
    elif config.subset is not None:
        raise SystemExit(f"unknown subset {config.subset!r}; use one of {SUBSETS}")
    return items


def _relative(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT)) if path.is_relative_to(REPO_ROOT) else str(path)


async def run(
    config: RunConfig,
    dataset: Dataset,
    catalog: Catalog,
    *,
    groq_key: str | None = None,
    provider: LLMProvider | None = None,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Run, resuming if a previous run left predictions, and write the metrics file."""
    config.out_dir.mkdir(parents=True, exist_ok=True)
    predictions_path = config.out_dir / "predictions.jsonl"
    plans_path = config.out_dir / "plans.jsonl"
    if config.fresh:
        for path in (predictions_path, plans_path):
            if path.exists():
                path.unlink()

    items = select_items(dataset, config)
    done = _load_done(predictions_path)
    plans = _load_plans(plans_path)
    if done:
        log(f"resuming: {len(done)} item(s) already done")

    harness = build_parser(config, catalog, groq_key=groq_key, provider=provider)
    stopped: str | None = None
    try:
        with predictions_path.open("a", encoding="utf-8") as sink:
            for item in items:
                if item.id in done:
                    continue
                try:
                    prediction = await predict(harness.parser, item, config)
                except BudgetExhaustedError as exc:
                    stopped = (
                        f"stopped at {item.id}: the daily budget for {config.model} is spent "
                        f"({exc}). Progress is saved; rerun the same command later to resume."
                    )
                    log(stopped)
                    break
                done[item.id] = prediction
                # Written per item and flushed, so an interruption loses at most one answer.
                sink.write(json.dumps(asdict(prediction)) + "\n")
                sink.flush()

        if stopped is None and harness.planner is not None:
            with plans_path.open("a", encoding="utf-8") as sink:
                for item in items:
                    if item.id in plans or not plannable(item):
                        continue
                    try:
                        record = await plan_item(harness, item, config)
                    except BudgetExhaustedError as exc:
                        stopped = (
                            f"stopped planning at {item.id}: the daily budget for {config.model} "
                            f"is spent ({exc}). Progress is saved; rerun the same command later "
                            "to resume."
                        )
                        log(stopped)
                        break
                    plans[item.id] = record
                    sink.write(json.dumps(record) + "\n")
                    sink.flush()
    finally:
        if harness.live is not None:
            await harness.live.aclose()

    tier = labels_tier(config, dataset)
    metrics = score([done[item.id] for item in items if item.id in done])
    planned = [plans[item.id] for item in items if item.id in plans]
    report: dict[str, Any] = {
        "run": {
            "parser": config.parser,
            "dataset": _relative(config.dataset),
            "split": config.split,
            "subset": config.subset,
            "prompt_version": load_prompt("intent_v1").version,
            "planner_prompt_version": load_prompt("planner_v1").version
            if harness.planner is not None
            else None,
            "include_examples": config.include_examples,
            "include_enums": config.include_enums,
            "max_repairs": config.max_repairs,
            "finished_at": datetime.now(UTC).isoformat(),
            "complete": stopped is None,
            "stopped_reason": stopped,
            "labels": tier,
            "for_reporting": tier in ("human", "machine"),
        },
        "dataset": {
            "items": len(dataset.items),
            "selected": len(items),
            "scorable": len(dataset.scorable),
            "excluded_needs_review": len(dataset.needs_review)
            if not config.include_unreviewed
            else 0,
            "warnings": list(dataset.warnings),
            "card": {
                "name": dataset.card.get("name"),
                "sha256": dataset.card.get("sha256"),
                "labels": dataset.card.get("labels"),
                "decision": dataset.card.get("decision"),
            }
            if dataset.card is not None
            else None,
        },
        "metrics": metrics,
        "plans": score_plans(planned, plannable_items=sum(plannable(item) for item in items))
        if harness.planner is not None
        else None,
    }
    if tier == "draft":
        report["warning"] = (
            "This run includes items marked needs_review. Their gold labels have not been checked "
            "by a human, so these numbers are for testing the harness only and must not be "
            "reported (BUILD_PROMPT 4.9)."
        )
    elif tier == "machine":
        report["warning"] = (
            "Gold labels written by Claude Code and checked against the card's rules by code; no "
            "person has reviewed them (docs/decisions.md D-081). Report these figures with that "
            "provenance beside them."
        )
    elif not dataset.scorable:
        report["warning"] = (
            "No item in this dataset has been reviewed by a human, so nothing was scored. Every "
            "metric is null because nothing was measured, not because the parser scored zero."
        )

    (config.out_dir / "metrics.json").write_text(
        json.dumps(report, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    return report
