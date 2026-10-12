"""The planner against the real model: does ``gpt-oss-120b`` follow ``planner_v1``'s rules?

Opt-in, like T4.8's live test: skipped unless ``GROQ_API_KEY`` is set, so the default suite never
touches the network or the quota.

    uv run python -m pytest -m live tests/test_generation_planner_live.py -s

Everything else about the planner is tested against fakes. This is what shows the prompt works on
the model it was written for: that Groq accepts the planner schema, and that the model's own plan
passes the code's checks (after at most two repairs) rather than every request quietly ending on
the default plan. Three requests, each a combination none of the prompt's examples shows. About
6,000 tokens when no repair is needed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.ai.intent import Action, ExtraStage, Intent, TargetEnvironment
from app.ai.quota import QuotaTracker
from app.core.settings import LlmMode, Settings
from app.generation.factory import build_planner
from app.generation.planner import PlanRequest, default_plan
from app.generation.spec import Assistant
from app.services.catalog import Catalog
from tests.test_ai_live import groq_key

pytestmark = pytest.mark.live

REAL_CATALOG = Path(__file__).resolve().parents[2] / "catalog" / "services.yaml"

REQUESTS = [
    pytest.param(
        Intent(
            action=Action.BUILD_TEST_DEPLOY,
            service="payment-service",
            environment=TargetEnvironment.STAGING,
            extra_stages=(ExtraStage.SECURITY_SCAN,),
        ),
        id="every suite, with a scan",
    ),
    pytest.param(
        Intent(
            action=Action.TEST,
            service="auth-service",
            test_suite="unit",
            extra_stages=(ExtraStage.LINT,),
        ),
        id="a named suite, with lint",
    ),
    pytest.param(
        Intent(
            action=Action.DEPLOY,
            service="payment-service",
            environment=TargetEnvironment.STAGING,
            extra_stages=(ExtraStage.INTEGRATION_TESTS,),
        ),
        id="a deploy that needs tests first",
    ),
]


@pytest.fixture(scope="module")
def quota() -> QuotaTracker:
    """One tracker for the module, so the three calls are paced against one budget."""
    return QuotaTracker()


@pytest.mark.parametrize("intent", REQUESTS)
async def test_the_real_model_plans_by_the_rules(
    settings: Settings, quota: QuotaTracker, intent: Intent
) -> None:
    live = settings.model_copy(update={"llm_mode": LlmMode.LIVE, "groq_api_key": groq_key()})
    catalog = Catalog(REAL_CATALOG)
    # Waiting out a per-minute limit is cheap here, and a fallback would hide what is measured.
    planner = build_planner(live, catalog=catalog, quota=quota, max_wait=65.0)

    outcome = await planner.plan(PlanRequest(intent=intent, assistant=Assistant.PIPELINE))

    print(
        f"\n  {outcome.model}: valid before repair={outcome.valid_before_repair}, "
        f"repairs={outcome.repairs}, source={outcome.source}, "
        f"tokens={sum(c.prompt_tokens + c.completion_tokens for c in outcome.calls)}"
    )
    for attempt in outcome.attempts:
        if attempt.issues:
            print(f"    attempt {attempt.number}: {list(attempt.issues)}")

    assert outcome.source == "model", (
        f"the model never produced a valid plan: {outcome.fallback_reasons}"
    )
    expected = default_plan(intent, catalog.require(str(intent.service)))
    assert [(s.template, s.suite, s.environment) for s in outcome.spec.stages] == [
        (s.template, s.suite, s.environment) for s in expected.stages
    ]
    assert all(call.prompt_tokens > 0 for call in outcome.calls if call.outcome == "ok")
