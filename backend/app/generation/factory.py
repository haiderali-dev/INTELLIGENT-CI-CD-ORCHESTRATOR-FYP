"""Wiring the planner for the configured ``LLM_MODE``, the same way ``app.ai.factory`` wires the
intent parser.

* ``live``   -- Groq through the model chain. Without a key there are no models, so the default
  plan answers every request, with ``ai_fallback`` set.
* ``replay`` -- recorded fixtures. A miss falls back to the default plan.
* ``fake``   -- the default plan, answered through ``FakeProvider`` and labelled ``fake``. The
  intent parser's fake responder answers with an *intent* whatever it is asked, so the planner
  gets its own responder rather than sharing that one.

The quota tracker is the process-wide one, shared with the intent parser: Groq counts both
against the same per-model limits (4.5.1).
"""

from __future__ import annotations

from typing import Any

from app.ai.chain import ModelChain
from app.ai.factory import build_provider, model_chain_names
from app.ai.prompting import load_prompt
from app.ai.providers import FakeProvider, LLMProvider
from app.ai.quota import QuotaTracker, get_quota_tracker
from app.ai.rules import RuleBasedParser
from app.core.settings import LlmMode, Settings
from app.generation.planner import Planner, default_plan_responder
from app.services.catalog import Catalog


def build_planner(
    settings: Settings,
    *,
    catalog: Catalog,
    provider: LLMProvider | None = None,
    quota: QuotaTracker | None = None,
    max_wait: float | None = None,
    has_models: bool | None = None,
) -> Planner:
    """A ``Planner`` for this configuration. ``provider`` and ``quota`` can be supplied by tests
    and the evaluation harness; the backend uses the process-wide ones. ``has_models`` goes with a
    supplied provider, as in ``build_intent_parser``."""
    if provider is not None:
        has_models = True if has_models is None else has_models
    elif settings.llm_mode is LlmMode.FAKE:
        provider, has_models = FakeProvider(responder=default_plan_responder(catalog)), True
    else:
        provider, has_models = build_provider(settings, RuleBasedParser(catalog))
    models = model_chain_names(settings) if has_models else ()

    chain_options: dict[str, Any] = {}
    if max_wait is not None:
        chain_options["max_wait"] = max_wait

    # No response cache: see app/generation/planner.py.
    chain = ModelChain(provider, models, quota=quota or get_quota_tracker(), **chain_options)
    return Planner(chain=chain, catalog=catalog, prompt=load_prompt("planner_v1"))
