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
from app.ai.chain import ModelChain
from app.ai.clarify import ClarificationService
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
from app.ai.quota import QuotaTracker
from app.ai.rules import RuleBasedParser
from app.ai.validator import IntentValidator
from app.db.models import Role
from app.services.catalog import Catalog
from app.services.git import GitClient, Ref
from eval.dataset import Dataset, Item
from eval.metrics import Prediction, score

REPO_ROOT: Final = Path(__file__).resolve().parents[1]
# eval/.cache, the directory .gitignore has reserved for this since Phase 0.
CACHE_DIR: Final = REPO_ROOT / "eval" / ".cache"
RESULTS_DIR: Final = REPO_ROOT / "eval" / "results"

# 4.9: "throttle to 25 requests per minute".
REQUESTS_PER_MINUTE: Final = 25

# The eval can afford to wait out a per-minute limit; a fallback would contaminate the comparison.
EVAL_MAX_WAIT: Final = 65.0


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


class CachedLiveProvider(LLMProvider):
    """Disk cache by prompt hash first, then the live model, throttled.

    The cache is the replay fixture format, so a finished evaluation run doubles as a fixture set.
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
        self.name = live.name
        self.live_calls = 0

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
            return await self._replay.complete_json(
                schema=schema, system=system, messages=messages, model=model
            )
        except ReplayMissError:
            pass
        wait = self._interval - (self._clock() - self._last_live)
        if wait > 0:
            await self._sleep(wait)
        self._last_live = self._clock()
        self.live_calls += 1
        return await self._recorder.complete_json(
            schema=schema,
            system=system,
            messages=messages,
            model=model,
            reasoning_effort=reasoning_effort,
        )

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

    @property
    def model(self) -> str | None:
        return self.parser.split(":", 1)[1] if self.parser.startswith("groq:") else None

    @property
    def for_reporting(self) -> bool:
        """Only runs over human-reviewed items may appear in the report."""
        return not self.include_unreviewed


def default_out_dir(
    parser: str, dataset: Path, *, include_examples: bool, include_enums: bool
) -> Path:
    """One directory per configuration, so rerunning the same command resumes the same run."""
    slug = re.sub(r"[^A-Za-z0-9.]+", "-", parser).strip("-")
    ablations = []
    if not include_examples:
        ablations.append("no-examples")
    if not include_enums:
        ablations.append("no-enums")
    suffix = "".join(f"__{name}" for name in ablations)
    return RESULTS_DIR / f"{dataset.stem}__{slug}{suffix}"


def build_parser(
    config: RunConfig,
    catalog: Catalog,
    *,
    groq_key: str | None = None,
    provider: LLMProvider | None = None,
) -> tuple[IntentParser, LLMProvider | None]:
    rules = RuleBasedParser(catalog)
    live: LLMProvider | None = provider

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
        # One model, no fallback: a failure must count against this model, not be replaced by the
        # rules' answer.
        chain = ModelChain(
            live,
            (config.model,),
            quota=QuotaTracker(),
            cache=ResponseCache(),
            max_wait=EVAL_MAX_WAIT,
        )
    else:
        raise SystemExit(f"unknown parser {config.parser!r}; use rules, fake or groq:<model>")

    parser = IntentParser(
        chain=chain,
        rules=rules,
        catalog=catalog,
        validator=IntentValidator(catalog, AcceptAllGitClient()),
        clarifier=ClarificationService(catalog),
        policy=PolicyService(),
        prompt=load_prompt("intent_v1"),
    )
    return parser, live


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
        reasons = "; ".join(outcome.fallback_reasons)
        if re.search(r"rate limited|daily|limit", reasons):
            raise BudgetExhaustedError(reasons)
        error = f"the model did not answer: {reasons}"

    return Prediction(
        item_id=item.id,
        category=item.category,
        gold_intent=item.gold_intent,
        gold_behavior=item.gold_behavior,
        predicted_intent=outcome.model_intent.to_card(),
        predicted_behavior=outcome.behavior,
        latency_ms=elapsed,
        # Every attempt for this command, retries included: they spend quota too.
        prompt_tokens=sum(call.prompt_tokens for call in outcome.calls),
        completion_tokens=sum(call.completion_tokens for call in outcome.calls),
        parser=outcome.parser,
        model=outcome.model,
        ai_fallback=outcome.ai_fallback,
        cached=outcome.cached,
        error=error,
    )


def _load_done(path: Path) -> dict[str, Prediction]:
    done: dict[str, Prediction] = {}
    if not path.is_file():
        return done
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            raw = json.loads(line)
            done[raw["item_id"]] = Prediction(**raw)
    return done


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
    if config.fresh and predictions_path.exists():
        predictions_path.unlink()

    items = dataset.items if config.include_unreviewed else dataset.scorable
    done = _load_done(predictions_path)
    if done:
        log(f"resuming: {len(done)} item(s) already done")

    parser, live = build_parser(config, catalog, groq_key=groq_key, provider=provider)
    stopped: str | None = None
    try:
        with predictions_path.open("a", encoding="utf-8") as sink:
            for item in items:
                if item.id in done:
                    continue
                try:
                    prediction = await predict(parser, item, config)
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
    finally:
        if live is not None:
            await live.aclose()

    metrics = score([done[item.id] for item in items if item.id in done])
    report: dict[str, Any] = {
        "run": {
            "parser": config.parser,
            "dataset": str(config.dataset.relative_to(REPO_ROOT))
            if config.dataset.is_relative_to(REPO_ROOT)
            else str(config.dataset),
            "prompt_version": load_prompt("intent_v1").version,
            "include_examples": config.include_examples,
            "include_enums": config.include_enums,
            "finished_at": datetime.now(UTC).isoformat(),
            "complete": stopped is None,
            "stopped_reason": stopped,
            "for_reporting": config.for_reporting,
        },
        "dataset": {
            "items": len(dataset.items),
            "scorable": len(dataset.scorable),
            "excluded_needs_review": len(dataset.needs_review)
            if not config.include_unreviewed
            else 0,
            "warnings": list(dataset.warnings),
        },
        "metrics": metrics,
    }
    if not config.for_reporting:
        report["warning"] = (
            "This run includes items marked needs_review. Their gold labels have not been checked "
            "by a human, so these numbers are for testing the harness only and must not be "
            "reported (BUILD_PROMPT 4.9)."
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
