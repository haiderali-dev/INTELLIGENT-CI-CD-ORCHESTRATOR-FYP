"""Wiring the failure explainer for the configured ``LLM_MODE``, as ``app.generation.factory``
wires the planner.

* ``live``   -- Groq through the model chain. Without a key there are no models, and the code's
  own explanation answers, with ``ai_fallback`` set.
* ``replay`` -- recorded fixtures. A miss falls back to the code's explanation.
* ``fake``   -- the code's explanation, answered through ``FakeProvider`` and labelled ``fake``.

No response cache, for the planner's reason: an answer that fails the checks would be served
again for ten minutes, so every repeat would be dropped for the same fault. The assistant rate
limit bounds what repeats can cost instead.
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
from app.failures.explainer import FailureExplainer, fake_failure_responder
from app.services.catalog import Catalog

PROMPT_NAME = "failure_v1"


def build_failure_explainer(
    settings: Settings,
    *,
    catalog: Catalog,
    provider: LLMProvider | None = None,
    quota: QuotaTracker | None = None,
    max_wait: float | None = None,
    has_models: bool | None = None,
) -> FailureExplainer:
    """A ``FailureExplainer`` for this configuration. ``provider`` and ``quota`` can be supplied by
    tests; the backend uses the process-wide ones. ``has_models`` goes with a supplied provider."""
    if provider is not None:
        has_models = True if has_models is None else has_models
    elif settings.llm_mode is LlmMode.FAKE:
        provider, has_models = FakeProvider(responder=fake_failure_responder), True
    else:
        provider, has_models = build_provider(settings, RuleBasedParser(catalog))
    models = model_chain_names(settings) if has_models else ()

    chain_options: dict[str, Any] = {}
    if max_wait is not None:
        chain_options["max_wait"] = max_wait

    chain = ModelChain(provider, models, quota=quota or get_quota_tracker(), **chain_options)
    return FailureExplainer(chain=chain, prompt=load_prompt(PROMPT_NAME))
