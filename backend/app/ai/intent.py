"""The structured intent every parser produces.

BUILD_PROMPT 4.5.2 fixes the ten fields. This module is the one definition of them: the LLM's JSON
schema is built from it (``app.ai.schema``), the rule parser fills it, the validator checks it, and
the policy layer decides on it. Keeping it in one place is what stops the model's schema and the
code that reads the model's answer from drifting apart.

The model's output is **never trusted as typed data**. ``Intent.from_untrusted`` coerces what came
back: an enum value that is not one of ours becomes null rather than an exception, because a null
field produces one clarifying question (4.5.3 step 4) while an exception would produce an error
page. Code then decides what the null means.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Action(StrEnum):
    BUILD = "BUILD"
    TEST = "TEST"
    DEPLOY = "DEPLOY"
    BUILD_TEST_DEPLOY = "BUILD_TEST_DEPLOY"
    STATUS = "STATUS"
    RERUN = "RERUN"
    CANCEL = "CANCEL"
    UNSUPPORTED = "UNSUPPORTED"


class Urgency(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class TargetEnvironment(StrEnum):
    """Where a deploy goes.

    ``production`` is a valid *parse* even though it is never a valid *deploy*. Appendix E says so
    explicitly: "If the user asks for production, still set environment to production and let the
    policy layer refuse it. Never silently change it to staging." A parser that quietly rewrote it
    would turn a refused request into an unrequested staging deploy.
    """

    STAGING = "staging"
    PRODUCTION = "production"


class ExtraStage(StrEnum):
    LINT = "lint"
    SECURITY_SCAN = "security_scan"
    INTEGRATION_TESTS = "integration_tests"
    SMOKE_TEST = "smoke_test"


# Actions that produce a job. The others read or act on existing runs.
GENERATING_ACTIONS: Final = frozenset(
    {Action.BUILD, Action.TEST, Action.DEPLOY, Action.BUILD_TEST_DEPLOY}
)

# Actions that operate on a run that already exists. 4.5.4: "service or a run the user already
# has".
RUN_ACTIONS: Final = frozenset({Action.STATUS, Action.RERUN, Action.CANCEL})

# A justification is free text the user wrote, copied into an audit entry and shown to reviewers.
MAX_JUSTIFICATION = 500


class Intent(BaseModel):
    """One parsed CI/CD request.

    Frozen: an intent is a record of what was understood. A change -- a policy downgrade, a user's
    edit on the intent card -- is a new intent, so the original stays available to explain itself.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    action: Action
    service: str | None = None
    branch: str | None = None
    commit: str | None = None
    environment: TargetEnvironment | None = None
    test_suite: str | None = None
    urgency: Urgency | None = None
    extra_stages: tuple[ExtraStage, ...] = ()
    justification: str | None = Field(default=None, max_length=MAX_JUSTIFICATION)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("service", "branch", "commit", "test_suite", "justification", mode="before")
    @classmethod
    def _blank_is_null(cls, value: Any) -> Any:
        """An empty string is "not said", the same as null.

        Models sometimes answer ``""`` where the schema allowed null; treating that as a real
        value would make "build from ''" look like an explicit branch.
        """
        if isinstance(value, str) and not value.strip():
            return None
        return value.strip() if isinstance(value, str) else value

    @property
    def generates_job(self) -> bool:
        return self.action in GENERATING_ACTIONS

    def with_changes(self, **changes: Any) -> Intent:
        """A copy with some fields replaced, re-validated."""
        return Intent.model_validate({**self.model_dump(), **changes})

    def to_card(self) -> dict[str, Any]:
        """The JSON shape the intent card and ``nl_commands.parsed_intent`` store."""
        return self.model_dump(mode="json")

    @classmethod
    def unsupported(cls, confidence: float = 1.0) -> Intent:
        return cls(action=Action.UNSUPPORTED, confidence=confidence)

    @classmethod
    def from_untrusted(cls, data: dict[str, Any]) -> tuple[Intent, list[str]]:
        """Build an intent from model output, coercing rather than failing.

        Returns the intent and a list of notes describing what was discarded, so the coercion is
        visible in logs and in the evaluation rather than silently papering over a bad answer.
        """
        notes: list[str] = []
        cleaned: dict[str, Any] = {}

        raw_action = str(data.get("action") or "").upper()
        if raw_action in Action.__members__:
            cleaned["action"] = Action(raw_action)
        else:
            notes.append(
                f"action {raw_action or '(missing)'!r} is not recognised; treated as UNSUPPORTED"
            )
            cleaned["action"] = Action.UNSUPPORTED

        for name in ("service", "branch", "commit", "test_suite", "justification"):
            value = data.get(name)
            if value is None or isinstance(value, str):
                cleaned[name] = value
            else:
                notes.append(f"{name} was {type(value).__name__}, not text; dropped")

        if isinstance(cleaned.get("justification"), str):
            cleaned["justification"] = cleaned["justification"][:MAX_JUSTIFICATION]

        cleaned["environment"] = _coerce_enum(
            TargetEnvironment, data.get("environment"), "environment", notes, lower=True
        )
        cleaned["urgency"] = _coerce_enum(Urgency, data.get("urgency"), "urgency", notes)

        stages: list[ExtraStage] = []
        raw_stages = data.get("extra_stages") or []
        if isinstance(raw_stages, list):
            for raw in raw_stages:
                stage = _coerce_enum(ExtraStage, raw, "extra_stages", notes, lower=True)
                if stage is not None and stage not in stages:
                    stages.append(stage)
        else:
            notes.append("extra_stages was not a list; dropped")
        cleaned["extra_stages"] = tuple(stages)

        confidence = data.get("confidence", 0.0)
        try:
            number = float(confidence)
        except (TypeError, ValueError):
            notes.append(f"confidence {confidence!r} is not a number; treated as 0")
            number = 0.0
        # Clamped rather than rejected: the strict schema cannot express bounds, and a model that
        # says 1.2 meant "very sure", which is still information.
        cleaned["confidence"] = min(1.0, max(0.0, number))

        return cls.model_validate(cleaned), notes


def _coerce_enum[E: StrEnum](
    enum: type[E], value: Any, field: str, notes: list[str], *, lower: bool = False
) -> E | None:
    if value is None:
        return None
    text = str(value).strip()
    text = text.lower() if lower else text.upper()
    for member in enum:
        if member.value == text:
            return member
    notes.append(f"{field} {value!r} is not one of {[m.value for m in enum]}; set to null")
    return None
