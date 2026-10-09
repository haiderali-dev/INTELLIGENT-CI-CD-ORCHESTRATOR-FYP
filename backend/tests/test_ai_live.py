"""The one opt-in live test: the real factory, the real prompt, the real model.

BUILD_PROMPT T4.8: "One opt-in live test (``pytest -m live``)". Skipped unless ``GROQ_API_KEY`` is
set, in the environment or in ``.env``, so the default suite never touches the network or the
quota:

    uv run python -m pytest -m live

Everything else in Phase 4 is tested against fakes and recorded payloads. This is the test that
proves those fakes describe the real thing: that Groq accepts the strict schema this code builds,
that the prompt produces a correct intent from ``gpt-oss-120b``, and that a successful call is
recorded with real token counts. One call, about 1,800 tokens.

The message is deliberately neither a few-shot example in the prompt nor an item in
``eval/datasets/sample.jsonl``, so passing it says nothing the evaluation will later measure.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from app.ai.cache import ResponseCache
from app.ai.factory import build_intent_parser
from app.ai.intent import Action
from app.ai.parser import Disposition
from app.ai.policy import PolicyContext
from app.ai.quota import QuotaTracker
from app.core.settings import LlmMode, Settings
from app.db.models import Role
from app.services.catalog import Catalog
from app.services.git import FakeGitClient

pytestmark = pytest.mark.live

REPO_ROOT = Path(__file__).resolve().parents[2]
MESSAGE = "rebuild payment-service on release/2.1"


def groq_key() -> str:
    """From the environment, else from .env. Never printed or logged."""
    if os.environ.get("GROQ_API_KEY"):
        return os.environ["GROQ_API_KEY"]
    env_file = REPO_ROOT / ".env"
    if env_file.is_file():
        found = re.search(r"^GROQ_API_KEY=(.*)$", env_file.read_text(encoding="utf-8"), re.M)
        if found and found.group(1).strip() and "replace_me" not in found.group(1):
            return found.group(1).strip()
    pytest.skip("GROQ_API_KEY is not set; this test is opt-in")


async def test_the_real_model_parses_a_command_through_the_whole_pipeline(
    settings: Settings,
) -> None:
    key = groq_key()
    catalog = Catalog(REPO_ROOT / "catalog" / "services.yaml")
    git = FakeGitClient()
    git.add_branch(
        "https://github.com/haiderali-dev/payment-service.git",
        "release/2.1",
        "3f786850e387550fdab836ed7e6dc881de23001b",
    )
    parser = build_intent_parser(
        settings.model_copy(update={"llm_mode": LlmMode.LIVE, "groq_api_key": key}),
        catalog=catalog,
        git=git,
        quota=QuotaTracker(),
        cache=ResponseCache(),
    )

    outcome = await parser.interpret(MESSAGE, context=PolicyContext(role=Role.DEVELOPER))

    # The model answered -- not the rule parser -- through the strict schema this code builds.
    assert outcome.parser == "LLM", outcome.fallback_reasons
    assert outcome.ai_fallback is False
    assert outcome.model == "openai/gpt-oss-120b"

    # And answered correctly.
    assert outcome.model_intent.action is Action.BUILD
    assert outcome.model_intent.service == "payment-service"
    assert outcome.model_intent.branch == "release/2.1"
    assert outcome.disposition is Disposition.READY

    # Recorded as a real, successful call with real token counts and the prompt version.
    call = outcome.calls[-1]
    assert call.outcome == "ok"
    assert call.prompt_tokens > 500  # the system prompt and examples are not free
    assert call.completion_tokens > 0
    assert outcome.prompt_version.startswith("intent_v1@")
