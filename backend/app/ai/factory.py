"""Wiring the AI core together for the configured ``LLM_MODE``.

* ``live``   -- Groq through the model chain. Without a key it degrades to the rule parser with
  ``ai_fallback`` set, rather than refusing to start: 4.8's acceptance requires that "with Groq
  unreachable, the rule parser answers", and a missing key is the most unreachable Groq gets.
* ``replay`` -- recorded fixtures (``app/ai/fixtures``). A miss falls back to the rules, so a stale
  fixture set shows up as fallbacks rather than as wrong answers.
* ``fake``   -- deterministic answers computed by the rule parser, for the demo and the tests.
  Labelled ``fake`` in every record, so it can never be mistaken for a model in the evaluation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final

from app.ai.cache import ResponseCache, get_response_cache
from app.ai.chain import ModelChain
from app.ai.clarify import ClarificationService
from app.ai.parser import IntentParser
from app.ai.policy import PolicyService
from app.ai.prompting import load_prompt
from app.ai.providers import (
    ChatMessage,
    FakeProvider,
    GroqProvider,
    LLMProvider,
    ReplayProvider,
)
from app.ai.quota import QuotaTracker, get_quota_tracker
from app.ai.rules import RuleBasedParser
from app.ai.validator import IntentValidator
from app.core.logging import get_logger
from app.core.settings import LlmMode, Settings
from app.services.catalog import Catalog
from app.services.git import GitClient

logger = get_logger(__name__)

FIXTURES_DIR: Final = Path(__file__).resolve().parent / "fixtures"


def model_chain_names(settings: Settings) -> tuple[str, ...]:
    return tuple(model.strip() for model in settings.llm_model_chain.split(",") if model.strip())


def build_provider(settings: Settings, rules: RuleBasedParser) -> tuple[LLMProvider, bool]:
    """The provider for the configured mode, and whether it has any models to call."""
    if settings.llm_mode is LlmMode.LIVE:
        if not settings.groq_api_key:
            logger.warning(
                "llm_live_without_key",
                detail="LLM_MODE=live but GROQ_API_KEY is empty; every answer will come from rules",
            )
            return FakeProvider(), False
        return GroqProvider(settings.groq_api_key), True

    if settings.llm_mode is LlmMode.REPLAY:
        return ReplayProvider(FIXTURES_DIR), True

    def respond(
        system: str, messages: list[ChatMessage], schema: dict[str, Any], model: str
    ) -> dict[str, Any]:
        return rules.parse_intent(messages[-1].content).to_card()

    return FakeProvider(responder=respond), True


def build_intent_parser(
    settings: Settings,
    *,
    catalog: Catalog,
    git: GitClient,
    provider: LLMProvider | None = None,
    quota: QuotaTracker | None = None,
    cache: ResponseCache | None = None,
    max_wait: float | None = None,
) -> IntentParser:
    """An ``IntentParser`` for this configuration.

    ``provider``, ``quota`` and ``cache`` can be supplied so the evaluation harness and the tests
    control them; the backend uses the process-wide ones.
    """
    rules = RuleBasedParser(catalog)
    if provider is None:
        provider, has_models = build_provider(settings, rules)
    else:
        has_models = True
    models = model_chain_names(settings) if has_models else ()

    chain_options: dict[str, Any] = {}
    if max_wait is not None:
        chain_options["max_wait"] = max_wait

    chain = ModelChain(
        provider,
        models,
        quota=quota or get_quota_tracker(),
        cache=cache if cache is not None else get_response_cache(),
        **chain_options,
    )
    return IntentParser(
        chain=chain,
        rules=rules,
        catalog=catalog,
        validator=IntentValidator(catalog, git),
        clarifier=ClarificationService(catalog),
        policy=PolicyService(),
        prompt=load_prompt("intent_v1"),
    )
