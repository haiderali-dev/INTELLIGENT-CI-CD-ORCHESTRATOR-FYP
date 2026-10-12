"""The planner: BUILD_PROMPT 4.6.2 steps 1 and 3 (T5.2).

1. **Plan:** "the model turns the intent plus catalog into the spec through a strict schema. A fixed
   default plan per action takes over when the model is unavailable."
3. **Validate:** "errors caused by the model's plan go back to it for at most 2 repairs."

What the model decides, and what code decides (D-042). 4.6.1 gives the model "only stages and
templates", and 4.5.3 says "code decides, never the model". Both hold here. The confirmed intent
fixes which stages the job must have, so code derives that stage list (``required_stages``) and
checks the model's plan against it. The model chooses the plan and names its stages. A plan with a
missing stage, an unrequested one, a wrong suite or environment, or the wrong order is an error
caused by the model's plan, and goes back to it. The default plan is the required list with
standard names, which is why it can always take over.

The rules, as the project owner decided them at the start of T5.2 (D-042):

* **Build first when needed.** BUILD is a build; TEST is a build then tests; DEPLOY is a deploy on
  its own; BUILD_TEST_DEPLOY is all three. ``test.sh``, ``lint.sh`` and ``security_scan.sh`` only
  activate the ``.venv`` that ``build.sh`` creates, and the agent has no pytest or ruff, so any
  of those stages brings a build in front of it. ``deploy.sh`` builds its own Docker image.
* **Every suite when none is named.** A plan that needs tests runs every suite the service has, in
  catalog order. ``integration_tests`` asks for the ``integration`` suite, as the intent validator
  already reads it.
* **Checks before tests.** Build, lint, security scan, tests, deploy, then a smoke test of what
  was deployed.
* **After two failed repairs, the default plan.** Marked ``ai_fallback`` with the reason. Every
  attempt is kept, so the evaluation can measure plan validity before and after repair (4.9).

The model never sees free text from the user. The request it plans from holds the action, the
service, a suite, an environment and extra stages, each already checked against the catalog. The
branch, commit and justification go straight into the spec, so a justification written to steer a
model has no model to steer here.

Planner calls are not cached. A first answer that fails the checks would otherwise be served again
for ten minutes, and each identical request would start its repairs from a plan already known to
be wrong.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final, Literal

from pydantic import ValidationError

from app.ai.chain import CallRecord, ModelChain
from app.ai.intent import GENERATING_ACTIONS, Action, ExtraStage, Intent, TargetEnvironment, Urgency
from app.ai.prompting import PromptTemplate
from app.ai.providers.base import ChatMessage, InvalidResponseError
from app.generation.spec import (
    Assistant,
    GenerationSpec,
    PlannerOutput,
    Stage,
    StageTemplate,
    build_planner_schema,
    service_templates,
)
from app.services.catalog import Catalog, CatalogService

if TYPE_CHECKING:
    from app.ai.parser import ParseOutcome

# 4.6.2 step 3: "at most 2 repairs".
MAX_REPAIRS: Final = 2

INTEGRATION_SUITE: Final = "integration"
LINT: Final = "lint"
SECURITY_SCAN: Final = "security_scan"
SMOKE_TEST: Final = "smoke_test"

# Requested checks, in the order they run: after build, before tests (D-042).
STATIC_CHECKS: Final = (LINT, SECURITY_SCAN)

# Stage names the default plan uses. The model may name stages differently.
_NAMES: Final = {
    StageTemplate.BUILD.value: "Build",
    LINT: "Lint",
    SECURITY_SCAN: "Security scan",
    SMOKE_TEST: "Smoke test",
}

PlanSource = Literal["model", "default"]


class PlannerError(ValueError):
    """The request cannot be planned at all, by the model or by default.

    Not a plan error: nothing the model answers could fix it, so it is never sent for repair. Each
    case is one the parser's validation, clarification or policy should already have stopped, so
    reaching here means a caller skipped them, or the intent was edited around them.
    """


# ---------------------------------------------------------------------------
# What the intent requires
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RequiredStage:
    """One stage the confirmed intent requires: a template, and its suite or environment."""

    template: str
    suite: str | None = None
    environment: str | None = None

    @property
    def default_name(self) -> str:
        if self.template == StageTemplate.TEST and self.suite is not None:
            return f"{self.suite.replace('_', ' ').capitalize()} tests"
        if self.template == StageTemplate.DEPLOY and self.environment is not None:
            return f"Deploy to {self.environment}"
        return _NAMES.get(self.template, self.template.replace("_", " ").capitalize())

    def describe(self) -> str:
        """How the stage is named in a repair message."""
        if self.suite is not None:
            return f"a {self.template} stage for suite {self.suite!r}"
        if self.environment is not None:
            return f"a {self.template} stage to {self.environment!r}"
        return f"a {self.template} stage"

    def as_stage(self) -> Stage:
        return Stage(
            name=self.default_name,
            template=self.template,
            suite=self.suite,
            environment=self.environment,
        )

    @classmethod
    def of(cls, stage: Stage) -> RequiredStage:
        return cls(template=stage.template, suite=stage.suite, environment=stage.environment)


def required_stages(intent: Intent, service: CatalogService) -> tuple[RequiredStage, ...]:
    """The stages this intent requires, in the order they run. Raises ``PlannerError``."""
    action = intent.action
    if action not in GENERATING_ACTIONS:
        raise PlannerError(f"{action.value} does not generate a job, so there is nothing to plan.")
    extras = {stage.value for stage in intent.extra_stages}

    wanted_suites: set[str] = set()
    if action in (Action.TEST, Action.BUILD_TEST_DEPLOY):
        if intent.test_suite is not None:
            if service.suite(intent.test_suite) is None:
                raise PlannerError(f"{service.name} has no {intent.test_suite!r} test suite.")
            wanted_suites.add(intent.test_suite)
        else:
            # Every suite when none is named (D-042).
            wanted_suites.update(suite.name for suite in service.test_suites)
            if not wanted_suites:
                raise PlannerError(f"{service.name} has no test suites to run.")
    if ExtraStage.INTEGRATION_TESTS.value in extras:
        if service.suite(INTEGRATION_SUITE) is None:
            raise PlannerError(f"{service.name} has no {INTEGRATION_SUITE!r} test suite.")
        wanted_suites.add(INTEGRATION_SUITE)
    # Catalog order, whatever order they were asked for in.
    suites = [suite.name for suite in service.test_suites if suite.name in wanted_suites]

    checks = [name for name in STATIC_CHECKS if name in extras]
    smoke = SMOKE_TEST in extras
    for name in [*checks, *([SMOKE_TEST] if smoke else [])]:
        if name not in service.extra_stages:
            raise PlannerError(f"{name} is not configured for {service.name}.")

    environment: str | None = None
    if action in (Action.DEPLOY, Action.BUILD_TEST_DEPLOY):
        if intent.environment is None:
            raise PlannerError("A deploy needs an environment.")
        environment = intent.environment.value
        # production is never in allowed_environments; the policy refuses it before this, and
        # this refuses it again, so no route through the planner can deploy there.
        if not service.allows(environment):
            raise PlannerError(f"{service.name} cannot be deployed to {environment}.")

    needs_build = action in (Action.BUILD, Action.BUILD_TEST_DEPLOY) or bool(suites or checks)

    stages: list[RequiredStage] = []
    if needs_build:
        stages.append(RequiredStage(StageTemplate.BUILD.value))
    stages.extend(RequiredStage(name) for name in checks)
    stages.extend(RequiredStage(StageTemplate.TEST.value, suite=suite) for suite in suites)
    if environment is not None:
        stages.append(RequiredStage(StageTemplate.DEPLOY.value, environment=environment))
    if smoke:
        stages.append(RequiredStage(SMOKE_TEST))
    return tuple(stages)


def default_plan(intent: Intent, service: CatalogService) -> PlannerOutput:
    """4.6.2's "fixed default plan per action": the required stages, with standard names."""
    return PlannerOutput(
        stages=tuple(stage.as_stage() for stage in required_stages(intent, service))
    )


# ---------------------------------------------------------------------------
# Checking a plan
# ---------------------------------------------------------------------------


def check_plan(
    data: dict[str, Any], required: tuple[RequiredStage, ...], service: CatalogService
) -> tuple[PlannerOutput | None, tuple[str, ...]]:
    """Parse a plan and list everything wrong with it. No issues means the plan is accepted.

    The issues are written for the model to act on, because they are exactly what a repair sends
    back. They are also what the evaluation counts as an invalid plan.
    """
    try:
        plan = PlannerOutput.model_validate(data)
    except ValidationError as exc:
        return None, tuple(_describe(error) for error in exc.errors())

    issues: list[str] = []
    offered = set(service_templates(service))
    for index, stage in enumerate(plan.stages, start=1):
        where = f"stage {index} ({stage.name!r})"
        # The strict schema's enums make these impossible from a live model. A replayed answer or
        # a provider that ignores strict must not get one through either.
        if stage.template not in offered:
            issues.append(f"{where}: {service.name} has no {stage.template!r} template")
        if stage.suite is not None and service.suite(stage.suite) is None:
            issues.append(f"{where}: {service.name} has no {stage.suite!r} test suite")
        if stage.environment is not None and not service.allows(stage.environment):
            issues.append(f"{where}: {service.name} cannot be deployed to {stage.environment!r}")

    names = Counter(stage.name.strip().casefold() for stage in plan.stages)
    for stage in plan.stages:
        key = stage.name.strip().casefold()
        if names[key] > 1:
            issues.append(f"the stage name {stage.name!r} is used more than once")
            names[key] = 0  # report each repeated name once

    got = [RequiredStage.of(stage) for stage in plan.stages]
    if got != list(required):
        missing = Counter(required) - Counter(got)
        unexpected = Counter(got) - Counter(required)
        issues.extend(f"missing: {stage.describe()}" for stage in missing.elements())
        issues.extend(
            f"not part of this request: {stage.describe()}" for stage in unexpected.elements()
        )
        if not missing and not unexpected:
            issues.append(
                "the stages are in the wrong order; the order is: "
                + " -> ".join(stage.describe() for stage in required)
            )
    return plan, tuple(issues)


def _describe(error: Any) -> str:
    location = ".".join(str(part) for part in error.get("loc", ())) or "plan"
    message = str(error.get("msg", "is not valid")).removeprefix("Value error, ")
    return f"{location}: {message}"


# ---------------------------------------------------------------------------
# What the model is asked
# ---------------------------------------------------------------------------


def planner_request(intent: Intent, service: CatalogService) -> dict[str, Any]:
    """The request the model plans from. Only catalog-checked values: no free text from the user."""
    return {
        "action": intent.action.value,
        "service": service.name,
        "test_suite": intent.test_suite,
        "environment": intent.environment.value if intent.environment is not None else None,
        "extra_stages": [stage.value for stage in intent.extra_stages],
        "service_templates": service_templates(service),
        "service_suites": [suite.name for suite in service.test_suites],
        "service_environments": list(service.allowed_environments),
    }


def intent_from_request(payload: dict[str, Any]) -> Intent:
    """The inverse of ``planner_request``, for answering a request without a model."""
    environment = payload.get("environment")
    return Intent(
        action=Action(payload["action"]),
        service=payload.get("service"),
        test_suite=payload.get("test_suite"),
        environment=TargetEnvironment(environment) if environment is not None else None,
        extra_stages=tuple(ExtraStage(stage) for stage in payload.get("extra_stages") or ()),
    )


def repair_message(issues: tuple[str, ...]) -> str:
    lines = "\n".join(f"- {issue}" for issue in issues)
    return (
        "Your previous plan was not accepted:\n"
        f"{lines}\n"
        "Answer again with the whole corrected plan, through the same schema."
    )


Responder = Callable[[str, list[ChatMessage], dict[str, Any], str], dict[str, Any]]


def default_plan_responder(catalog: Catalog) -> Responder:
    """Answer planner requests with the default plan, for ``LLM_MODE=fake``.

    The request is the last user turn that parses as one. Repair turns are prose, and the default
    plan never needs a repair, so in practice it is always the request itself.
    """

    def respond(
        system: str, messages: list[ChatMessage], schema: dict[str, Any], model: str
    ) -> dict[str, Any]:
        for message in reversed(messages):
            if message.role != "user":
                continue
            try:
                payload = json.loads(message.content)
            except ValueError:
                continue
            if isinstance(payload, dict) and "action" in payload and "service" in payload:
                service = catalog.require(str(payload["service"]))
                plan = default_plan(intent_from_request(payload), service)
                return plan.model_dump(mode="json")
        raise InvalidResponseError("no planner request in the conversation")

    return respond


# ---------------------------------------------------------------------------
# The outcome
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PlanRequest:
    """A confirmed intent, ready to plan: validated, clarified and through policy."""

    intent: Intent
    assistant: Assistant
    #: What the validator resolved, so the spec builds the commit the user approved (4.6.5).
    resolved_branch: str | None = None
    resolved_commit: str | None = None

    @classmethod
    def from_parse(cls, outcome: ParseOutcome, assistant: Assistant) -> PlanRequest:
        return cls(
            intent=outcome.intent,
            assistant=assistant,
            resolved_branch=outcome.resolved_branch,
            resolved_commit=outcome.resolved_commit,
        )


@dataclass(frozen=True)
class PlanAttempt:
    """One plan considered: a model's answer, or the default plan when it took over."""

    number: int
    source: PlanSource
    provider: str
    model: str | None
    answer: dict[str, Any]
    issues: tuple[str, ...] = ()
    calls: tuple[CallRecord, ...] = ()

    @property
    def valid(self) -> bool:
        return not self.issues

    def to_record(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "source": self.source,
            "provider": self.provider,
            "model": self.model,
            "valid": self.valid,
            "issues": list(self.issues),
            "answer": self.answer,
        }


@dataclass(frozen=True)
class PlanOutcome:
    spec: GenerationSpec
    source: PlanSource
    provider: str
    model: str | None
    #: True whenever the plan did not come from the first model: a later model, or the default.
    ai_fallback: bool
    prompt_version: str
    attempts: tuple[PlanAttempt, ...]
    fallback_reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def calls(self) -> tuple[CallRecord, ...]:
        """Every model call, for ``llm_calls``."""
        return tuple(call for attempt in self.attempts for call in attempt.calls)

    @property
    def model_attempts(self) -> tuple[PlanAttempt, ...]:
        return tuple(attempt for attempt in self.attempts if attempt.source == "model")

    @property
    def repairs(self) -> int:
        """Repairs the model was asked for."""
        return max(0, len(self.model_attempts) - 1)

    @property
    def valid_before_repair(self) -> bool | None:
        """Whether the model's first plan was valid. None when no model answered (4.9)."""
        attempts = self.model_attempts
        return attempts[0].valid if attempts else None

    @property
    def valid_after_repair(self) -> bool | None:
        """Whether the model's last plan was valid. None when no model answered (4.9)."""
        attempts = self.model_attempts
        return attempts[-1].valid if attempts else None

    def to_record(self) -> dict[str, Any]:
        """For ``generated_pipelines.validation_results`` and the evaluation."""
        return {
            "source": self.source,
            "provider": self.provider,
            "model": self.model,
            "ai_fallback": self.ai_fallback,
            "fallback_reasons": list(self.fallback_reasons),
            "prompt_version": self.prompt_version,
            "repairs": self.repairs,
            "valid_before_repair": self.valid_before_repair,
            "valid_after_repair": self.valid_after_repair,
            "attempts": [attempt.to_record() for attempt in self.attempts],
            "warnings": list(self.warnings),
        }


# ---------------------------------------------------------------------------
# The planner
# ---------------------------------------------------------------------------


@dataclass
class _Run:
    """Mutable state while a plan is made; frozen into a ``PlanOutcome`` at the end."""

    attempts: list[PlanAttempt] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


class Planner:
    def __init__(self, *, chain: ModelChain, catalog: Catalog, prompt: PromptTemplate) -> None:
        self._chain = chain
        self._catalog = catalog
        self._prompt = prompt

    @property
    def prompt_version(self) -> str:
        return self._prompt.version

    async def plan(
        self,
        request: PlanRequest,
        *,
        max_repairs: int = MAX_REPAIRS,
        include_examples: bool = True,
    ) -> PlanOutcome:
        """Plan, check, repair, and build the spec. Raises ``PlannerError`` for an unplannable
        request.

        ``max_repairs=0`` is 4.9's "no repair loop" ablation; ``include_examples=False`` its "no
        few-shot examples".
        """
        intent = request.intent
        if intent.service is None:
            raise PlannerError("There is no service to plan for.")
        service = self._catalog.get(intent.service)
        if service is None:
            raise PlannerError(f"There is no service called {intent.service!r} in the catalog.")

        required = required_stages(intent, service)
        fallback = PlannerOutput(stages=tuple(stage.as_stage() for stage in required))
        fallback_answer = fallback.model_dump(mode="json")

        rendered = self._prompt.render(catalog="", role="", include_examples=include_examples)
        schema = build_planner_schema(service)
        messages = rendered.messages_for(
            json.dumps(planner_request(intent, service), separators=(",", ":"))
        )
        run = _Run()

        chosen: PlannerOutput = fallback
        source: PlanSource = "default"
        provider = "default"
        model: str | None = None
        ai_fallback = True

        for number in range(max(0, max_repairs) + 1):
            result = await self._chain.complete(
                schema=schema,
                system=rendered.system,
                messages=messages,
                rules_fallback=lambda: fallback_answer,
            )
            run.reasons.extend(result.fallback_reasons)

            if result.parser == "rules":
                # No model answered: the default plan takes over (4.6.2 step 1).
                run.attempts.append(
                    PlanAttempt(
                        number, "default", "default", None, fallback_answer, (), result.calls
                    )
                )
                break

            plan, issues = check_plan(result.data, required, service)
            run.attempts.append(
                PlanAttempt(
                    number,
                    "model",
                    result.provider,
                    result.model,
                    result.data,
                    issues,
                    result.calls,
                )
            )
            if plan is not None and not issues:
                chosen, source, provider, model = plan, "model", result.provider, result.model
                ai_fallback = result.ai_fallback
                break

            if number >= max_repairs:
                run.reasons.append(
                    f"the plan was still not valid after {max_repairs} repair(s); "
                    "the default plan was used"
                )
                run.attempts.append(
                    PlanAttempt(number + 1, "default", "default", None, fallback_answer)
                )
                break

            messages = [
                *messages,
                ChatMessage(role="assistant", content=json.dumps(result.data)),
                ChatMessage(role="user", content=repair_message(issues)),
            ]

        spec, warnings = self._build_spec(request, service, chosen)
        return PlanOutcome(
            spec=spec,
            source=source,
            provider=provider,
            model=model,
            ai_fallback=ai_fallback,
            prompt_version=rendered.version,
            attempts=tuple(run.attempts),
            fallback_reasons=tuple(run.reasons),
            warnings=warnings,
        )

    @staticmethod
    def _build_spec(
        request: PlanRequest, service: CatalogService, plan: PlannerOutput
    ) -> tuple[GenerationSpec, tuple[str, ...]]:
        """Everything except the stages comes from the intent and the catalog, never the model."""
        intent = request.intent
        warnings: list[str] = []
        branch = request.resolved_branch or intent.branch or service.default_branch
        commit = request.resolved_commit or intent.commit
        if commit is not None and commit.lower() == "latest":
            # The validator could not reach the remote to resolve it, and told the user so on the
            # intent card. "latest" is the branch head, which is what checking out the branch
            # gives (D-041 rule 2): the same revision, only not pinned in advance.
            warnings.append(
                f"The latest commit of {branch} could not be resolved in advance, so the "
                "newest commit at build time is used."
            )
            commit = None
        try:
            spec = GenerationSpec(
                assistant=request.assistant,
                service=service.name,
                repo=service.repo,
                branch=branch,
                commit=commit,
                agent_label=service.agent_label,
                priority=intent.urgency or Urgency.MEDIUM,
                justification=intent.justification,
                stages=plan.stages,
            )
        except ValidationError as exc:
            # Not the plan's fault, so not sent for repair: the stages already passed. A revision
            # or catalog value the validator should have stopped.
            raise PlannerError(f"The spec could not be built: {exc.errors()[0]['msg']}") from exc
        return spec, tuple(warnings)
