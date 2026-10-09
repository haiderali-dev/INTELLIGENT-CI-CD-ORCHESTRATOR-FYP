"""``IntentParser``: BUILD_PROMPT 4.5.3, end to end.

1. **Guard** -- length and control characters (``app.ai.guard``).
2. **Parse** -- the model chain with the per-request schema, falling back to the rule parser.
3. **Check in code** -- ``IntentValidator``; "code decides, never the model".
4. **Clarify** -- one question, up to four buttons, a help card after two rounds.
5. **Policy** -- 4.5.5.
6. **Record** -- ``nl_commands``, ``llm_calls`` and ``audit_logs``.

Steps 1 to 5 are ``interpret``, which touches no database; step 6 is ``record``. The split is what
lets the evaluation harness score the full pipeline on 250 messages without writing 250 rows, and
lets the tests check each decision without a session.

Three decisions in the ordering are worth stating:

* **Policy before clarification.** A production deploy is refused whatever service it names, so
  asking "which service?" first would spend the user's time on a question whose answer cannot
  change the outcome.
* **Policy audit events are written only when policy decided the outcome** -- a refusal, a request
  for a justification, or a request that proceeds. A HIGH request still waiting on a clarification
  is not yet a request, and auditing it each round would count it against the daily quota once per
  question asked.
* **A model's UNSUPPORTED can be overruled, narrowly.** If the model calls a message out of scope
  but the rule parser sees a CI/CD action applied to something ("deploy it"), the action is kept and
  the missing fields are asked for. A false UNSUPPORTED is a dead end, while a question costs one
  round. T4.3's live smoke run found the model doing exactly this. The model's own answer is kept
  separately as ``model_intent``, so the evaluation measures the model, not this correction.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Final, Literal, TypedDict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.cache import cache_key
from app.ai.chain import CallRecord, ModelChain
from app.ai.clarify import Clarification, ClarificationService, HelpCard
from app.ai.guard import guard_message
from app.ai.intent import Action, Intent
from app.ai.policy import (
    HIGH_URGENCY_AUDIT_ACTION,
    AuditEvent,
    PolicyContext,
    PolicyDecision,
    PolicyOutcome,
    PolicyService,
)
from app.ai.prompting import PromptTemplate
from app.ai.rules import RuleBasedParser, RuleParse
from app.ai.schema import build_intent_schema, catalog_context, catalog_fingerprint
from app.ai.validator import IntentValidator, ValidationResult
from app.core.logging import get_logger
from app.db.models import AuditLog, CommandStatus, LlmCall, NlCommand
from app.services.catalog import Catalog

logger = get_logger(__name__)

# "it", "the build", "the tests": a CI/CD verb applied to something, which is what makes a model's
# UNSUPPORTED worth overruling. A bare verb in small talk ("how do I build a birdhouse") is not.
_CI_OBJECT: Final = re.compile(
    r"\b(?:it|this|that|them|the\s+(?:build|tests?|pipeline|job|deploy(?:ment)?|run|release))\b",
    re.I,
)

INJECTION_AUDIT_ACTION: Final = "intent.injection_suspected"


class Disposition(StrEnum):
    READY = "READY"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    NEEDS_JUSTIFICATION = "NEEDS_JUSTIFICATION"
    REFUSED = "REFUSED"
    UNSUPPORTED = "UNSUPPORTED"
    HELP = "HELP"


# nl_commands.status is 4.4.3's fixed set; these map the finer dispositions onto it.
_STATUS: Final = {
    Disposition.READY: CommandStatus.PARSED,
    Disposition.NEEDS_CLARIFICATION: CommandStatus.NEEDS_CLARIFICATION,
    Disposition.NEEDS_JUSTIFICATION: CommandStatus.NEEDS_CLARIFICATION,
    Disposition.HELP: CommandStatus.NEEDS_CLARIFICATION,
    Disposition.REFUSED: CommandStatus.REFUSED,
    Disposition.UNSUPPORTED: CommandStatus.UNSUPPORTED,
}

# 4.9's gold_behavior: GENERATE, CLARIFY or REFUSE.
_BEHAVIOR: Final = {
    Disposition.READY: "GENERATE",
    Disposition.NEEDS_CLARIFICATION: "CLARIFY",
    Disposition.NEEDS_JUSTIFICATION: "CLARIFY",
    Disposition.HELP: "CLARIFY",
    Disposition.REFUSED: "REFUSE",
    Disposition.UNSUPPORTED: "REFUSE",
}


@dataclass(frozen=True)
class ParseOutcome:
    disposition: Disposition
    text: str
    #: The intent to act on: validated, answered, and as the policy left it.
    intent: Intent
    #: What the parser itself produced, before any correction. The evaluation scores this.
    model_intent: Intent
    parser: Literal["LLM", "RULES"]
    provider: str
    model: str | None
    ai_fallback: bool
    prompt_version: str
    clarification_round: int
    fallback_reasons: tuple[str, ...] = ()
    cached: bool = False
    notes: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    question: Clarification | None = None
    help: HelpCard | None = None
    policy: PolicyDecision | None = None
    resolved_branch: str | None = None
    resolved_commit: str | None = None
    injection_suspected: bool = False
    calls: tuple[CallRecord, ...] = ()
    audit: tuple[AuditEvent, ...] = ()

    @property
    def status(self) -> CommandStatus:
        return _STATUS[self.disposition]

    @property
    def behavior(self) -> str:
        return _BEHAVIOR[self.disposition]

    def to_record(self) -> dict[str, Any]:
        """The JSON stored in ``nl_commands.parsed_intent``: the intent and how it was reached."""
        return {
            "intent": self.intent.to_card(),
            "model_intent": self.model_intent.to_card(),
            "disposition": self.disposition.value,
            "behavior": self.behavior,
            "ai_fallback": self.ai_fallback,
            "fallback_reasons": list(self.fallback_reasons),
            "cached": self.cached,
            "prompt_version": self.prompt_version,
            "notes": list(self.notes),
            "warnings": list(self.warnings),
            "question": (
                {
                    "field": self.question.field,
                    "question": self.question.question,
                    "options": list(self.question.options),
                    "free_text": self.question.free_text,
                }
                if self.question
                else None
            ),
            "help": {"title": self.help.title, "lines": list(self.help.lines)}
            if self.help
            else None,
            "policy": (
                {
                    "outcome": self.policy.outcome.value,
                    "reasons": [
                        {"code": str(reason.code), "message": reason.message}
                        for reason in self.policy.reasons
                    ],
                    "flags": list(self.policy.flags),
                    "can_cancel_running": self.policy.can_cancel_running,
                }
                if self.policy
                else None
            ),
            "resolved": {"branch": self.resolved_branch, "commit": self.resolved_commit},
            "injection_suspected": self.injection_suspected,
        }


class _Common(TypedDict):
    """The fields every outcome shares, typed so unpacking them into ``ParseOutcome`` is checked."""

    text: str
    model_intent: Intent
    parser: Literal["LLM", "RULES"]
    provider: str
    model: str | None
    ai_fallback: bool
    fallback_reasons: tuple[str, ...]
    cached: bool
    prompt_version: str
    clarification_round: int
    injection_suspected: bool
    calls: tuple[CallRecord, ...]


@dataclass
class _Draft:
    """Mutable state while the steps run; frozen into a ``ParseOutcome`` at the end."""

    notes: list[str] = field(default_factory=list)
    audit: list[AuditEvent] = field(default_factory=list)


class IntentParser:
    def __init__(
        self,
        *,
        chain: ModelChain,
        rules: RuleBasedParser,
        catalog: Catalog,
        validator: IntentValidator,
        clarifier: ClarificationService,
        policy: PolicyService,
        prompt: PromptTemplate,
    ) -> None:
        self._chain = chain
        self._rules = rules
        self._catalog = catalog
        self._validator = validator
        self._clarifier = clarifier
        self._policy = policy
        self._prompt = prompt

    async def interpret(
        self,
        text: str,
        *,
        context: PolicyContext,
        history: list[tuple[str, str]] | None = None,
        answers: dict[str, str] | None = None,
        clarification_round: int = 0,
        has_recent_run: bool = False,
        include_examples: bool = True,
        include_enums: bool = True,
    ) -> ParseOutcome:
        """Steps 1 to 5. Raises only for a message the guard refuses outright."""
        draft = _Draft()

        # 1. Guard.
        guarded = guard_message(text)
        message = guarded.text
        if guarded.removed_characters:
            draft.notes.append(f"removed {guarded.removed_characters} control character(s)")
        if guarded.injection_suspected:
            # 4.6.5: "log the attempt" -- whatever it was trying to do.
            draft.audit.append(
                AuditEvent(
                    INJECTION_AUDIT_ACTION,
                    "intent",
                    {"role": context.role.value, "excerpt": message[:200]},
                )
            )

        # 2. Parse.
        rendered = self._prompt.render(
            catalog=catalog_context(self._catalog),
            role=context.role.value,
            history=history,
            include_examples=include_examples,
        )
        schema = build_intent_schema(self._catalog, include_enums=include_enums)
        rules_parse = self._rules.parse(message)
        key = cache_key(
            text=message,
            role=context.role.value,
            catalog_fingerprint=catalog_fingerprint(self._catalog),
            # The ablation switches change the answer, so they are part of "identical": otherwise
            # an ablation run could be served the full configuration's cached answers.
            prompt_version=f"{rendered.version}|examples={include_examples}|enums={include_enums}",
            history=[content for _, content in (history or [])],
            model_chain=self._chain.models,
        )
        result = await self._chain.complete(
            schema=schema,
            system=rendered.system,
            messages=rendered.messages_for(message),
            rules_fallback=lambda: rules_parse.intent.to_card(),
            cache_key=key,
        )
        model_intent, coercion = Intent.from_untrusted(result.data)
        draft.notes.extend(coercion)
        parser: Literal["LLM", "RULES"] = "LLM" if result.parser == "llm" else "RULES"

        intent = self._rescue(model_intent, rules_parse, message, parser, draft)
        intent = self._apply_answers(intent, answers, draft)

        base: _Common = {
            "text": message,
            "model_intent": model_intent,
            "parser": parser,
            "provider": result.provider,
            "model": result.model,
            "ai_fallback": result.ai_fallback,
            "fallback_reasons": result.fallback_reasons,
            "cached": result.cached,
            "prompt_version": rendered.version,
            "clarification_round": clarification_round,
            "injection_suspected": guarded.injection_suspected,
            "calls": result.calls,
        }

        if intent.action is Action.UNSUPPORTED:
            return ParseOutcome(
                disposition=Disposition.UNSUPPORTED,
                intent=intent,
                help=self._clarifier.help_card(
                    "That is not something I can do. Here is what I can"
                ),
                notes=tuple(draft.notes),
                audit=tuple(draft.audit),
                **base,
            )

        # 3. Check in code.
        validation = await self._validator.validate(intent)
        intent = validation.intent

        # 5 before 4: a refusal does not wait on a clarification that cannot change it.
        decision = self._policy.evaluate(intent, context)
        question = self._clarifier.next_question(
            intent,
            validation.issues,
            has_recent_run=has_recent_run,
            round_number=clarification_round,
        )

        if decision.outcome is PolicyOutcome.REFUSE:
            return self._finish(
                Disposition.REFUSED, intent, decision, validation, draft, base, policy_audit=True
            )
        if isinstance(question, HelpCard):
            return self._finish(
                Disposition.HELP, intent, decision, validation, draft, base, help_card=question
            )
        if question is not None:
            return self._finish(
                Disposition.NEEDS_CLARIFICATION,
                intent,
                decision,
                validation,
                draft,
                base,
                question=question,
            )
        if decision.outcome is PolicyOutcome.NEEDS_JUSTIFICATION:
            return self._finish(
                Disposition.NEEDS_JUSTIFICATION,
                intent,
                decision,
                validation,
                draft,
                base,
                question=ClarificationService.justification_question(),
                policy_audit=True,
            )
        return self._finish(
            Disposition.READY, decision.intent, decision, validation, draft, base, policy_audit=True
        )

    # --- Steps --------------------------------------------------------------

    @staticmethod
    def _rescue(
        model_intent: Intent,
        rules_parse: RuleParse,
        message: str,
        parser: str,
        draft: _Draft,
    ) -> Intent:
        """Overrule a model's UNSUPPORTED when there is clearly a CI/CD request.

        Narrow on purpose: the rules must see an action *and* something it applies to -- a service,
        an environment, a suite, or an object such as "it" or "the build". A verb in small talk
        does not qualify.
        """
        if parser != "LLM" or model_intent.action is not Action.UNSUPPORTED:
            return model_intent
        ruled = rules_parse.intent
        if ruled.action is Action.UNSUPPORTED:
            return model_intent
        has_object = bool(
            ruled.service or ruled.environment or ruled.test_suite or _CI_OBJECT.search(message)
        )
        if not has_object:
            return model_intent
        draft.notes.append(
            f"the model called this unsupported, but it reads as {ruled.action.value}; "
            "asking for the missing details instead"
        )
        return ruled.with_changes(confidence=min(ruled.confidence, 0.5))

    @staticmethod
    def _apply_answers(intent: Intent, answers: dict[str, str] | None, draft: _Draft) -> Intent:
        """Fix fields the user answered explicitly, so a re-parse cannot lose them."""
        if not answers:
            return intent
        allowed = {"service", "branch", "commit", "environment", "test_suite", "justification"}
        merged = {**intent.to_card(), **{k: v for k, v in answers.items() if k in allowed}}
        answered, notes = Intent.from_untrusted(merged)
        draft.notes.extend(f"answer: {note}" for note in notes)
        return answered

    def _finish(
        self,
        disposition: Disposition,
        intent: Intent,
        decision: PolicyDecision,
        validation: ValidationResult,
        draft: _Draft,
        base: _Common,
        *,
        question: Clarification | None = None,
        help_card: HelpCard | None = None,
        policy_audit: bool = False,
    ) -> ParseOutcome:
        audit = list(draft.audit)
        if policy_audit:
            audit.extend(decision.audit)
        return ParseOutcome(
            disposition=disposition,
            intent=intent,
            notes=tuple(draft.notes),
            warnings=validation.warnings,
            question=question,
            help=help_card,
            policy=decision,
            resolved_branch=validation.resolved_branch,
            resolved_commit=validation.resolved_commit,
            audit=tuple(audit),
            **base,
        )

    # --- Step 6 ---------------------------------------------------------------

    @staticmethod
    async def record(
        session: AsyncSession,
        outcome: ParseOutcome,
        *,
        message_id: str,
        actor_id: str | None,
    ) -> NlCommand:
        """Write the command, every model call, and the audit entries the outcome produced."""
        command = NlCommand(
            message_id=message_id,
            raw_text=outcome.text,
            parsed_intent=outcome.to_record(),
            parser=outcome.parser,
            model=outcome.model,
            confidence=outcome.intent.confidence,
            status=outcome.status.value,
            clarification_rounds=outcome.clarification_round,
        )
        session.add(command)
        await session.flush()

        for call in outcome.calls:
            session.add(
                LlmCall(
                    command_id=command.id,
                    provider=call.provider,
                    model=call.model,
                    latency_ms=call.latency_ms,
                    prompt_tokens=call.prompt_tokens,
                    completion_tokens=call.completion_tokens,
                    fallback_used=call.fallback_used,
                    cached=call.cached,
                    prompt_version=outcome.prompt_version,
                    outcome=call.outcome,
                )
            )
        for event in outcome.audit:
            session.add(
                AuditLog(
                    actor_id=actor_id,
                    action=event.action,
                    target=event.target,
                    details={**event.details, "command_id": command.id},
                )
            )
        logger.info(
            "intent_recorded",
            command_id=command.id,
            disposition=outcome.disposition.value,
            parser=outcome.parser,
            ai_fallback=outcome.ai_fallback,
        )
        return command


async def high_urgency_used_today(session: AsyncSession, user_id: str) -> int:
    """HIGH requests *granted* to this user since midnight UTC.

    Counted from the audit entries the policy writes, filtering on ``granted`` in Python rather
    than in SQL: JSON field queries differ between SQLite and PostgreSQL, and a user's HIGH requests
    in one day number a handful, not thousands.
    """
    midnight = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    rows = (
        await session.scalars(
            select(AuditLog).where(
                AuditLog.actor_id == user_id,
                AuditLog.action == HIGH_URGENCY_AUDIT_ACTION,
                AuditLog.created_at >= midnight,
            )
        )
    ).all()
    return sum(1 for row in rows if (row.details or {}).get("granted") is True)
