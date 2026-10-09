"""``ClarificationService``: BUILD_PROMPT 4.5.3 step 4 and 4.5.4.

"Any required field that is null or ambiguous becomes one question with up to 4 candidate buttons.
Merge the answer with the original message and re-parse. After 2 rounds, show a help card."

=============================  ====================================================
Action                         Needs before generating (4.5.4)
=============================  ====================================================
BUILD                          service
TEST                           service; suite when the service has more than one
DEPLOY, BUILD_TEST_DEPLOY      service and environment
STATUS, RERUN, CANCEL          service or a run the user already has
UNSUPPORTED                    nothing; reply with the supported commands
=============================  ====================================================

*One* question per round, not a form. The first thing to ask is whatever the validator found wrong
with a value the user actually gave -- a branch that does not exist is a more pressing question
than a field they did not mention -- and then the first missing required field in the order above.

Production is never offered as a button. A button is an invitation, and inviting a choice the policy
will refuse is a trap.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from app.ai.intent import Action, Intent, TargetEnvironment
from app.ai.validator import MAX_CANDIDATES, ValidationIssue
from app.services.catalog import Catalog

# "After 2 rounds, show a help card."
MAX_ROUNDS: Final = 2

# How a field is named when an answer is merged back into the message, chosen so both the model
# and the rule parser read it: "run the tests (service payment-service)".
_MERGE_LABELS: Final = {
    "service": "service",
    "test_suite": "test suite",
    "environment": "environment",
    "branch": "branch",
    "commit": "commit",
}


@dataclass(frozen=True)
class Clarification:
    field: str
    question: str
    options: tuple[str, ...] = ()
    #: Free text rather than a button, such as a justification.
    free_text: bool = False


@dataclass(frozen=True)
class HelpCard:
    title: str
    lines: tuple[str, ...]


class ClarificationService:
    def __init__(self, catalog: Catalog) -> None:
        self._catalog = catalog

    def missing_fields(self, intent: Intent, *, has_recent_run: bool = False) -> list[str]:
        """Required fields still null, in the order they should be asked about."""
        action = intent.action
        missing: list[str] = []

        if action is Action.UNSUPPORTED:
            return missing

        if action in (Action.STATUS, Action.RERUN, Action.CANCEL):
            # "service or a run the user already has".
            if intent.service is None and not has_recent_run:
                missing.append("service")
            return missing

        if intent.service is None:
            missing.append("service")

        if action is Action.TEST and intent.test_suite is None and intent.service is not None:
            service = self._catalog.get(intent.service)
            if service is not None and len(service.test_suites) > 1:
                missing.append("test_suite")

        if action in (Action.DEPLOY, Action.BUILD_TEST_DEPLOY) and intent.environment is None:
            missing.append("environment")

        return missing

    def next_question(
        self,
        intent: Intent,
        issues: tuple[ValidationIssue, ...] = (),
        *,
        has_recent_run: bool = False,
        round_number: int = 0,
    ) -> Clarification | HelpCard | None:
        """The one thing to ask now, the help card if the rounds are spent, or None."""
        question = self._question(intent, issues, has_recent_run=has_recent_run)
        if question is None:
            return None
        if round_number >= MAX_ROUNDS:
            return self.help_card(
                f"Still missing {question.field.replace('_', ' ')} after {MAX_ROUNDS} questions."
            )
        return question

    def _question(
        self, intent: Intent, issues: tuple[ValidationIssue, ...], *, has_recent_run: bool
    ) -> Clarification | None:
        if issues:
            # A problem with a value the user actually gave comes before anything they left out.
            first = issues[0]
            return Clarification(
                field=first.field,
                question=first.message
                + (" Which did you mean?" if first.candidates else " Please give another one."),
                options=first.candidates[:MAX_CANDIDATES],
            )

        missing = self.missing_fields(intent, has_recent_run=has_recent_run)
        if not missing:
            return None
        field = missing[0]

        if field == "service":
            names = sorted(self._catalog.service_names())
            verb = {
                Action.BUILD: "build",
                Action.TEST: "test",
                Action.DEPLOY: "deploy",
                Action.BUILD_TEST_DEPLOY: "build, test and deploy",
                Action.STATUS: "check on",
                Action.RERUN: "rerun",
                Action.CANCEL: "cancel",
            }.get(intent.action, "use")
            return Clarification(
                field="service",
                question=f"Which service should I {verb}?",
                options=tuple(names[:MAX_CANDIDATES]),
            )

        if field == "test_suite":
            service = self._catalog.get(intent.service or "")
            suites = tuple(suite.name for suite in service.test_suites) if service else ()
            return Clarification(
                field="test_suite",
                question=f"Which test suite for {intent.service}?",
                options=suites[:MAX_CANDIDATES],
            )

        # environment
        service = self._catalog.get(intent.service or "")
        allowed = tuple(
            environment
            for environment in (service.allowed_environments if service else ("staging",))
            # Never a button for production: inviting a choice the policy refuses is a trap.
            if environment != TargetEnvironment.PRODUCTION.value
        )
        return Clarification(
            field="environment",
            question=f"Where should {intent.service or 'it'} be deployed?",
            options=allowed[:MAX_CANDIDATES],
        )

    @staticmethod
    def justification_question() -> Clarification:
        """The policy's question for an unjustified HIGH request: free text, no buttons."""
        return Clarification(
            field="justification",
            question=(
                "HIGH urgency puts this ahead of everyone else's builds. What makes it urgent?"
            ),
            free_text=True,
        )

    @staticmethod
    def merge(original: str, field: str, answer: str) -> str:
        """The original message with the answer appended, for re-parsing.

        4.5.3: "Merge the answer with the original message and re-parse." Appended in a form both
        parsers understand, rather than substituted into the sentence, so nothing the user wrote is
        lost or rewritten.
        """
        label = _MERGE_LABELS.get(field, field.replace("_", " "))
        return f"{original.rstrip()} ({label} {answer.strip()})"

    def help_card(self, title: str = "Here is what I can do") -> HelpCard:
        """The supported commands, with this catalog's services. 4.5.4's reply for UNSUPPORTED."""
        services = ", ".join(sorted(self._catalog.service_names())) or "none configured"
        return HelpCard(
            title=title,
            lines=(
                "Build <service> from <branch>",
                "Run the <suite> tests for <service>",
                "Deploy <service> to staging",
                "Build, test and deploy <service> to staging",
                "What's the status of <service>?",
                "Rerun or cancel the <service> build",
                f"Services: {services}",
                "Deployments go to staging only.",
            ),
        )
