"""The JSON the assistant API stores and returns, as typed models (D-058).

A message's payload, a command's intent record, a pipeline's progress line and validation report,
and the run card were ``dict[str, Any]`` in the OpenAPI schema. The frontend generates its types
from that schema and may not write its own (4.7.1), so it could not read them (D-056). These models
describe each one exactly as the backend writes it, and the producer is named beside every model.
Tests hold the two together: what each producer writes must validate here and dump back unchanged.

They are response models, so stored rows pass through them on the way out. They keep the producers'
names and flat nesting, because stored rows and existing clients use that shape. Where an older
stored row can lack something a newer producer writes, the model says so and fills it in.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Discriminator, Field, Tag, model_validator

from app.ai.intent import Intent
from app.ai.parser import Disposition
from app.ai.policy import PolicyOutcome
from app.api.queue import ScoreComponentsResponse
from app.core.errors import ErrorCode


class _Sent(BaseModel):
    """A response always carries every field, defaults included, so the schema says each one is
    there. The frontend's types then read ``error: ErrorCode | null``, not "may be absent"."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)


# ---------------------------------------------------------------------------
# The intent record: ParseOutcome.to_record() (app/ai/parser.py)
# ---------------------------------------------------------------------------


class ClarificationRecord(_Sent):
    """The question the assistant needs answered (``Clarification``, app/ai/clarify.py)."""

    field: str = Field(description="The intent field the answer fills, such as service")
    question: str
    options: list[str] = Field(description="Answers to offer as buttons; typing still works")
    free_text: bool = Field(description="True when the answer is words, not a choice")


class HelpCardRecord(_Sent):
    """What the assistant can do (``HelpCard``, app/ai/clarify.py)."""

    title: str
    lines: list[str]


class PolicyReasonRecord(_Sent):
    """One rule's verdict: a code to switch on and a sentence to show (``PolicyReason``)."""

    code: ErrorCode
    message: str


class PolicyRecord(_Sent):
    """The policy's decision on the intent (``PolicyDecision``, app/ai/policy.py)."""

    outcome: PolicyOutcome
    reasons: list[PolicyReasonRecord]
    flags: list[str] = Field(description="Shown in the preview without blocking anything")
    can_cancel_running: bool = Field(
        description="An Admin may cancel the running chain and go ahead (4.5.5)"
    )


class ResolvedRecord(_Sent):
    """The branch and commit the backend resolved in Git, when it did."""

    branch: str | None
    commit: str | None


class IntentRecord(_Sent):
    """``ParseOutcome.to_record()``: the intent and how it was reached.

    Stored as ``nl_commands.parsed_intent``, and spread into the reply's payload. ``intent`` is what
    to act on, after answers and the policy; ``model_intent`` is what the parser itself produced.
    """

    intent: Intent
    model_intent: Intent
    disposition: Disposition
    behavior: Literal["GENERATE", "CLARIFY", "REFUSE"]
    ai_fallback: bool = Field(description="True when the rule parser answered instead of the model")
    fallback_reasons: list[str]
    cached: bool
    prompt_version: str
    notes: list[str]
    warnings: list[str]
    question: ClarificationRecord | None
    help: HelpCardRecord | None
    policy: PolicyRecord | None
    resolved: ResolvedRecord
    injection_suspected: bool


# ---------------------------------------------------------------------------
# The run card: chains.run_card() (app/services/chains.py)
# ---------------------------------------------------------------------------


class RunView(_Sent):
    """One job's run (``chains._run_view``)."""

    id: str
    build_number: int
    result: str = Field(description="SUCCESS, UNSTABLE, FAILURE, ABORTED, NOT_BUILT or RUNNING")
    started_at: str | None
    finished_at: str | None
    duration_ms: int | None
    queue_wait_ms: int | None
    url: str | None = Field(description="The build's page, as Jenkins reports it")


RunCardJobState = Literal[
    "success",
    "unstable",
    "failure",
    "aborted",
    "not_built",
    "running",
    "queued",
    "waiting",
    "not_started",
]


class RunCardJob(_Sent):
    name: str
    position: int
    state: RunCardJobState = Field(
        description="The run's result in lower case, or queued, waiting or not_started"
    )
    run: RunView | None


class StageView(_Sent):
    """One Pipeline stage, as Jenkins' stage view reports it (``chains._stage_view``)."""

    name: str
    status: str
    duration_ms: int


class RunCardQueue(_Sent):
    """Where the chain's job waits: everything the run card's score bar draws."""

    job: str
    rank: int
    score: float
    level: str
    components: ScoreComponentsResponse
    weights: dict[str, float] = Field(description="The plugin's weights, as in /api/queue")
    waiting_reason: str | None
    wait_seconds: float

    @model_validator(mode="before")
    @classmethod
    def _complete_an_older_snapshot(cls, data: Any) -> Any:
        """A status message stores the card as it was. Cards stored before D-057 have no
        ``base_score``, ``own_score`` or ``weights``. They are completed as not inherited, and with
        no weights, so the bar says its parts cannot be shown rather than drawing wrong ones."""
        if not isinstance(data, dict) or not isinstance(data.get("components"), dict):
            return data
        parts = dict(data["components"])
        if "own_score" not in parts:
            parts["own_score"] = data.get("score", 0.0)
        if "base_score" not in parts:
            parts["base_score"] = parts["own_score"] - parts.get("aging_bonus", 0.0)
        return {"weights": {}, **data, "components": parts}


class RunCard(_Sent):
    """4.7.4's run card: each job's state and run, Pipeline stages, and the queue position."""

    id: str
    pipeline_id: str | None
    service: str
    job_type: str
    status: Literal["RUNNING", "SUCCESS", "FAILURE", "ABORTED", "EXPIRED"]
    position: int
    parameters: dict[str, str]
    started_at: str | None
    finished_at: str | None
    lock_expires_at: str | None
    duration_ms: int | None
    jobs: list[RunCardJob]
    stages: list[StageView]
    queue: RunCardQueue | None
    failed_run_id: str | None = Field(description="The run Explain failure explains (T5.9)")


class CancelResult(_Sent):
    """``chains.cancel()``: what cancelling a chain stopped."""

    chain_id: str
    dequeued: list[str] = Field(description="Queued jobs taken off the queue")
    stopped: list[str] = Field(description="Running builds stopped, as name#number")


# ---------------------------------------------------------------------------
# Message payloads (app/services/conversations.py, app/services/generation.py)
# ---------------------------------------------------------------------------


class _ParsedReply(IntentRecord):
    """A reply to a parsed message: ``{"kind": ..., **record, "command_id": ...}``
    (``conversations.describe`` and ``send_message``)."""

    command_id: str


class IntentReply(_ParsedReply):
    """Understood, and ready to generate or act on."""

    kind: Literal["intent"]


class QuestionReply(_ParsedReply):
    """A question before the assistant can go on; the record's ``question`` holds it."""

    kind: Literal["question"]


class RefusalReply(_ParsedReply):
    """Refused. The record's ``policy`` says why; a run request refused while it was carried out
    (a lock, a permission, Jenkins down) also gives the ``error`` code."""

    kind: Literal["refusal"]
    error: ErrorCode | None = None


class ParsedHelpReply(_ParsedReply):
    """The parser decided the message asked for help."""

    kind: Literal["help"]


class HelpReply(_Sent):
    """``/help``, answered with the help card and nothing parsed."""

    kind: Literal["help"]
    help: HelpCardRecord


class StatusReply(_ParsedReply):
    """ "What's the status of my last deploy?": the newest chain's run card, as it was then."""

    kind: Literal["status"]
    chain: RunCard | None = Field(description="Null when there is no run yet")


class NothingToRerunReply(_ParsedReply):
    """A re-run was asked for, but no test job had failed."""

    kind: Literal["rerun"]
    chain: None


class RerunStartedReply(_ParsedReply):
    """A failed test job re-run as a new chain (``conversations._rerun``)."""

    kind: Literal["run"]
    chain_id: str
    first_job: str
    queue_item_id: int
    jobs: list[str]


class ApprovedRunReply(_Sent):
    """Approve and run started a chain (``generation.approve``)."""

    kind: Literal["run"]
    pipeline_id: str
    chain_id: str
    first_job: str
    queue_item_id: int
    jobs: list[str]
    parameters: dict[str, str]
    priority: str
    approved_at: str


class CancelReply(_ParsedReply):
    """A cancel request: what it stopped, or ``chain: null`` when nothing was running."""

    kind: Literal["cancel"]
    chain: None = None
    chain_id: str | None = None
    dequeued: list[str] | None = None
    stopped: list[str] | None = None


class PipelineReply(_Sent):
    """A plan was generated and validated, or not (``generation._store``)."""

    kind: Literal["pipeline"]
    pipeline_id: str
    status: Literal["VALIDATED", "INVALID"]


def _payload_tag(value: Any) -> str | None:
    """Which model a stored payload is. ``kind`` decides, except where one kind has two
    producers: ``help`` from ``/help`` carries no record, and ``run`` from an approval carries a
    ``pipeline_id`` where a re-run carries a record."""
    if isinstance(value, BaseModel):
        value = value.model_dump()
    if not isinstance(value, dict):
        return None
    kind = value.get("kind")
    if kind == "help":
        return "help" if "intent" not in value else "parsed-help"
    if kind == "run":
        return "approved-run" if "pipeline_id" in value else "rerun-started"
    if kind == "rerun":
        return "nothing-to-rerun"
    return kind if isinstance(kind, str) else None


MessagePayload = Annotated[
    Annotated[IntentReply, Tag("intent")]
    | Annotated[QuestionReply, Tag("question")]
    | Annotated[RefusalReply, Tag("refusal")]
    | Annotated[ParsedHelpReply, Tag("parsed-help")]
    | Annotated[HelpReply, Tag("help")]
    | Annotated[StatusReply, Tag("status")]
    | Annotated[NothingToRerunReply, Tag("nothing-to-rerun")]
    | Annotated[RerunStartedReply, Tag("rerun-started")]
    | Annotated[ApprovedRunReply, Tag("approved-run")]
    | Annotated[CancelReply, Tag("cancel")]
    | Annotated[PipelineReply, Tag("pipeline")],
    Discriminator(_payload_tag),
]


# ---------------------------------------------------------------------------
# A pipeline's progress line and validation report (app/services/generation.py)
# ---------------------------------------------------------------------------


class ProgressStep(_Sent):
    """One step of 4.7.4's progress line (``generation._progress``)."""

    step: Literal["Understood", "Planned", "Rendered", "Validated"]
    ok: bool
    detail: str = Field(description="How a step passed, or the exact error when it failed")


class ValidationCheck(_Sent):
    """One line of the 4.6.3 checklist (``Check.to_record``, app/generation/validate.py)."""

    name: str
    label: str
    status: Literal["passed", "warning", "failed"]
    message: str
    cause: Literal["plan", "input", "template"] | None = Field(
        description="What to fix: the plan, the user's input, or a template"
    )


class ValidationReportRecord(_Sent):
    """The checklist, in order (``ValidationReport.to_record``)."""

    ok: bool
    checks: list[ValidationCheck]
