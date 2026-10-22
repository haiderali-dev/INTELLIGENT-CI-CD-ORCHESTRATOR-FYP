"""Conversations, messages and intent editing for both assistants (T5.5).

BUILD_PROMPT 4.4.4: ``POST /api/assistants/{freestyle|pipeline}/conversations``,
``GET /api/conversations``, ``POST /api/conversations/{id}/messages`` and
``PATCH /api/commands/{id}/intent``. The routers in ``app/api/assistants.py`` stay thin; the
decisions are here.

**A reply to a question is an answer, unless it is plainly a new request.** 4.5.3 step 4: "Merge
the answer with the original message and re-parse." When the conversation's last command is
waiting on a question, the next message is taken as the answer if it is one of the offered buttons,
is short (four words or fewer), or answers a request for a justification -- which is a sentence by
nature. Anything longer is treated as a new request, because "deploy auth-service to staging"
typed in reply to "Which service?" means the user started over, not that the service is called
that.

**Slash commands** (4.7.4): ``/help`` answers with the help card and parses nothing; ``/status``
and ``/rerun`` are rewritten into the sentences they stand for and parsed like any other message,
so they get the same validation, policy and audit as the words would.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Final

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.clarify import ClarificationService
from app.ai.intent import RUN_ACTIONS, Action, Intent
from app.ai.parser import Disposition, IntentParser, ParseOutcome, high_urgency_used_today
from app.ai.policy import PolicyContext, RunningChain
from app.core.errors import ApiError, ErrorCode, conflict, not_found
from app.core.logging import get_logger
from app.core.settings import Settings
from app.db.models import Assistant as AssistantKind
from app.db.models import (
    AuditLog,
    Chain,
    ChainStatus,
    Conversation,
    GeneratedPipeline,
    Job,
    Message,
    MessageRole,
    NlCommand,
    PipelineStatus,
    Role,
    User,
)
from app.services import chains
from app.services.jenkins import JenkinsClient
from app.services.plugin import PluginClient
from app.services.runs import Page, clamp_page, count_rows
from app.services.tracker import RunTracker

logger = get_logger(__name__)

DEFAULT_TITLE: Final = "New chat"
MAX_TITLE: Final = 60
# Recent turns given to the parser as context (prompting.HISTORY_TURNS keeps the last six).
HISTORY_MESSAGES: Final = 6
ANSWER_MAX_WORDS: Final = 4

# The intent fields an edit may change. The action is not one of them: changing what kind of job
# a request is, is a new request.
EDITABLE_FIELDS: Final = frozenset(
    {
        "service",
        "branch",
        "commit",
        "environment",
        "test_suite",
        "urgency",
        "extra_stages",
        "justification",
    }
)

INTENT_EDITED_AUDIT_ACTION: Final = "intent.edited"

_SLASH: Final = {
    "/status": "show the status of my last run",
    "/rerun": "rerun my last failed tests",
}


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------


async def create_conversation(
    session: AsyncSession, *, user: User, assistant: AssistantKind, title: str | None = None
) -> Conversation:
    conversation = Conversation(
        user_id=user.id,
        assistant=assistant.value,
        title=(title or DEFAULT_TITLE).strip()[:MAX_TITLE] or DEFAULT_TITLE,
    )
    session.add(conversation)
    await session.flush()
    return conversation


async def list_conversations(
    session: AsyncSession,
    *,
    user: User,
    assistant: AssistantKind | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> Page[Conversation]:
    """The user's own conversations, newest first. Nobody lists anyone else's."""
    resolved_limit, resolved_offset = clamp_page(limit, offset)
    statement = select(Conversation).where(Conversation.user_id == user.id)
    if assistant is not None:
        statement = statement.where(Conversation.assistant == assistant.value)
    total = await count_rows(session, statement)
    rows = (
        await session.scalars(
            statement.order_by(Conversation.created_at.desc())
            .limit(resolved_limit)
            .offset(resolved_offset)
        )
    ).all()
    return Page(items=tuple(rows), total=total, limit=resolved_limit, offset=resolved_offset)


async def get_conversation(
    session: AsyncSession, *, user: User, conversation_id: str
) -> Conversation:
    """The conversation, if it is this user's. Someone else's is reported as missing, not
    forbidden, so its existence is not disclosed."""
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None or conversation.user_id != user.id:
        raise not_found(
            ErrorCode.CONVERSATION_NOT_FOUND,
            "No such conversation.",
            conversation_id=conversation_id,
        )
    return conversation


async def list_messages(session: AsyncSession, conversation: Conversation) -> list[Message]:
    rows = await session.scalars(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at, Message.id)
    )
    return list(rows.all())


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


async def refuse_once_run(
    session: AsyncSession, command_id: str, *, besides: str | None = None
) -> None:
    """409 once any plan for this command was approved: one request runs once.

    Editing, generating, regenerating and approving all check it, so an approved HIGH-urgency
    request cannot be generated and approved again to start more HIGH chains without a new
    justification or quota (independent security review, finding 1). A partial unique index on
    ``generated_pipelines`` holds the same rule against two approvals racing. ``besides`` leaves
    out the plan being approved, which ``approve`` checks itself.
    """
    query = select(GeneratedPipeline.id).where(
        GeneratedPipeline.command_id == command_id,
        GeneratedPipeline.status == PipelineStatus.APPROVED.value,
    )
    if besides is not None:
        query = query.where(GeneratedPipeline.id != besides)
    approved = await session.scalar(query)
    if approved is not None:
        raise conflict(
            ErrorCode.ALREADY_APPROVED,
            "This request was already approved and run. Send a new message to run it again.",
            pipeline_id=approved,
        )


async def get_command(
    session: AsyncSession, *, user: User, command_id: str
) -> tuple[NlCommand, Conversation]:
    """A command and its conversation, if the conversation is this user's."""
    row = (
        await session.execute(
            select(NlCommand, Conversation)
            .join(Message, NlCommand.message_id == Message.id)
            .join(Conversation, Message.conversation_id == Conversation.id)
            .where(NlCommand.id == command_id)
        )
    ).first()
    if row is None or row[1].user_id != user.id:
        raise not_found(ErrorCode.COMMAND_NOT_FOUND, "No such command.", command_id=command_id)
    return row[0], row[1]


async def latest_command(session: AsyncSession, conversation: Conversation) -> NlCommand | None:
    return (
        await session.scalars(
            select(NlCommand)
            .join(Message, NlCommand.message_id == Message.id)
            .where(Message.conversation_id == conversation.id)
            .order_by(NlCommand.created_at.desc(), NlCommand.id.desc())
            .limit(1)
        )
    ).first()


@dataclass(frozen=True)
class PendingQuestion:
    field: str
    options: tuple[str, ...]
    command: NlCommand


def pending_question(command: NlCommand | None) -> PendingQuestion | None:
    """The question the last command is waiting on, if any. A help card asks nothing."""
    if command is None:
        return None
    record = command.parsed_intent or {}
    disposition = record.get("disposition")
    question = record.get("question")
    if disposition not in (Disposition.NEEDS_CLARIFICATION, Disposition.NEEDS_JUSTIFICATION):
        return None
    if not isinstance(question, dict) or not question.get("field"):
        return None
    return PendingQuestion(
        field=str(question["field"]),
        options=tuple(str(option) for option in question.get("options") or ()),
        command=command,
    )


def is_answer(text: str, pending: PendingQuestion) -> bool:
    """Whether a reply answers the pending question rather than starting a new request."""
    reply = " ".join(text.split()).casefold()
    if pending.field == "justification":
        return True
    if any(reply == option.casefold() for option in pending.options):
        return True
    return len(reply.split()) <= ANSWER_MAX_WORDS


# ---------------------------------------------------------------------------
# Posting a message
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Exchange:
    """One message in, one reply out, and the command the message became (if it was parsed)."""

    user_message: Message
    assistant_message: Message
    command: NlCommand | None


async def has_recent_run(session: AsyncSession, user: User) -> bool:
    """Whether the user has started anything, which is what "a run the user already has" needs
    (4.5.4) for status, rerun and cancel."""
    started = await session.scalar(select(exists().where(Chain.started_by == user.id)))
    created = await session.scalar(select(exists().where(Job.created_by == user.id)))
    return bool(started or created)


async def running_chain_for(session: AsyncSession, service: str | None) -> RunningChain | None:
    """The chain holding a service's lock, for the policy's "new request while its chain runs"
    rule (4.5.5)."""
    if service is None:
        return None
    return await chains.running_chain(session, service)


@dataclass(frozen=True)
class RunContext:
    """What acting on a status, rerun or cancel request needs (T5.7)."""

    jenkins: JenkinsClient
    plugin: PluginClient | None = None
    tracker: RunTracker | None = None


async def policy_context(
    session: AsyncSession, *, user: User, settings: Settings, service: str | None = None
) -> PolicyContext:
    return PolicyContext(
        role=Role(user.role),
        high_urgency_used_today=await high_urgency_used_today(session, user.id),
        high_urgency_quota=settings.high_urgency_daily_quota,
        running_chain=await running_chain_for(session, service),
    )


async def history_for(session: AsyncSession, conversation: Conversation) -> list[tuple[str, str]]:
    messages = await list_messages(session, conversation)
    return [
        ("assistant" if message.role == MessageRole.ASSISTANT.value else "user", message.content)
        for message in messages[-HISTORY_MESSAGES:]
    ]


async def post_message(
    session: AsyncSession,
    *,
    user: User,
    conversation: Conversation,
    text: str,
    parser: IntentParser,
    clarifier: ClarificationService,
    settings: Settings,
    runs: RunContext | None = None,
) -> Exchange:
    """Store the message, interpret it, record the command and reply.

    A confirmed status, rerun or cancel request is acted on at once when ``runs`` is given (4.6.5:
    "Show the latest run card, no generation"; "Re-trigger the last failed test job").
    """
    history = await history_for(session, conversation)
    stripped = text.strip()

    user_message = Message(
        conversation_id=conversation.id, role=MessageRole.USER.value, content=text
    )
    session.add(user_message)
    if conversation.title == DEFAULT_TITLE and stripped:
        conversation.title = " ".join(stripped.split())[:MAX_TITLE]
    await session.flush()

    if stripped.casefold() == "/help":
        card = clarifier.help_card()
        reply = _reply(
            conversation,
            "\n".join([card.title, *card.lines]),
            {"kind": "help", "help": {"title": card.title, "lines": list(card.lines)}},
        )
        session.add(reply)
        await session.flush()
        return Exchange(user_message=user_message, assistant_message=reply, command=None)

    to_parse, answers, round_number = await _resolve_input(session, conversation, stripped)

    # The service is not known until the message is parsed, so the running-chain rule is applied
    # by re-evaluating once it is (see _with_running_chain).
    context = await policy_context(session, user=user, settings=settings)
    recent = await has_recent_run(session, user)
    outcome = await parser.interpret(
        to_parse,
        context=context,
        history=history,
        answers=answers,
        clarification_round=round_number,
        has_recent_run=recent,
    )
    outcome = await _with_running_chain(session, outcome, parser, context, recent)

    command = await IntentParser.record(
        session, outcome, message_id=user_message.id, actor_id=user.id
    )
    content, payload = describe(outcome)
    if runs is not None:
        acted = await act_on_run_request(session, outcome=outcome, user=user, runs=runs)
        if acted is not None:
            content, extra = acted
            payload.update(extra)
    payload["command_id"] = command.id
    reply = _reply(conversation, content, payload)
    session.add(reply)
    await session.flush()
    return Exchange(user_message=user_message, assistant_message=reply, command=command)


def _service_of(job_name: str) -> str | None:
    """``fs-payment-service-test-unit`` -> ``payment-service``."""
    for prefix in ("fs-", "pl-"):
        if job_name.startswith(prefix):
            rest = job_name[len(prefix) :]
            for marker in ("-test-", "-test", "-build", "-deploy-", "-lint", "-security-scan"):
                if marker in rest:
                    return rest.split(marker, 1)[0]
    return None


async def act_on_run_request(
    session: AsyncSession, *, outcome: ParseOutcome, user: User, runs: RunContext
) -> tuple[str, dict[str, Any]] | None:
    """Carry out a confirmed STATUS, RERUN or CANCEL. None for anything else."""
    intent = outcome.intent
    if outcome.disposition is not Disposition.READY or intent.action not in RUN_ACTIONS:
        return None
    try:
        if intent.action is Action.STATUS:
            return await _status(session, user=user, service=intent.service, runs=runs)
        if intent.action is Action.RERUN:
            return await _rerun(session, user=user, service=intent.service, runs=runs)
        return await _cancel(session, user=user, service=intent.service, runs=runs)
    except ApiError as exc:
        # A refusal is an answer, not an error page: the chain lock, a permission, Jenkins down.
        return exc.message, {"kind": "refusal", "error": exc.code.value}


async def _status(
    session: AsyncSession, *, user: User, service: str | None, runs: RunContext
) -> tuple[str, dict[str, Any]]:
    chain = await chains.latest_chain(session, user=user, service=service)
    if chain is None:
        return "There is no run to show yet. Generate one and approve it first.", {
            "kind": "status",
            "chain": None,
        }
    card = await chains.run_card(session, chain, jenkins=runs.jenkins, plugin=runs.plugin)
    return status_sentence(card), {"kind": "status", "chain": card}


def status_sentence(card: dict[str, Any]) -> str:
    """One line for a run card, newest job first."""
    jobs = [job for job in card["jobs"] if job["run"] is not None]
    service = card["service"]
    status = str(card["status"]).lower()
    if not jobs:
        return f"The {service} chain is {status}; its first job has not started yet."
    newest = jobs[-1]
    run = newest["run"]
    return (
        f"The {service} chain is {status}: {newest['name']} #{run['build_number']} "
        f"is {str(run['result']).lower()}."
    )


async def _rerun(
    session: AsyncSession, *, user: User, service: str | None, runs: RunContext
) -> tuple[str, dict[str, Any]]:
    found = await chains.last_failed_test(session, service=service)
    if found is None:
        return "There is no failed test job to re-run.", {"kind": "rerun", "chain": None}
    run, job, previous = found
    target = (previous.service if previous is not None else None) or _service_of(job.jenkins_name)
    if target is None:
        return "That test job does not belong to a known service.", {"kind": "refusal"}
    chain, queue_item_id = await chains.rerun(
        session,
        jenkins=runs.jenkins,
        user=user,
        run=run,
        job=job,
        previous=previous,
        service=target,
    )
    if runs.tracker is not None:
        runs.tracker.track(
            queue_item_id=queue_item_id,
            job_id=job.id,
            job_name=job.jenkins_name,
            chain_id=chain.id,
        )
    return f"Re-run started: {job.jenkins_name} is queued.", {
        "kind": "run",
        "chain_id": chain.id,
        "first_job": job.jenkins_name,
        "queue_item_id": queue_item_id,
        "jobs": chain.jobs,
    }


async def _cancel(
    session: AsyncSession, *, user: User, service: str | None, runs: RunContext
) -> tuple[str, dict[str, Any]]:
    running = await chains.running_chain(session, service) if service else None
    chain = (
        await chains.get_chain(session, running.chain_id)
        if running is not None
        else await chains.latest_chain(session, user=user, service=service)
    )
    if chain is None or chain.status != ChainStatus.RUNNING.value:
        return "Nothing is running to cancel.", {"kind": "cancel", "chain": None}
    result = await chains.cancel(session, jenkins=runs.jenkins, chain=chain, actor=user)
    return f"Cancelled the {chain.service} chain.", {"kind": "cancel", **result}


async def _resolve_input(
    session: AsyncSession, conversation: Conversation, text: str
) -> tuple[str, dict[str, str] | None, int]:
    """What to parse: the message itself, or the pending question's original merged with it."""
    for slash, sentence in _SLASH.items():
        if text.casefold() == slash or text.casefold().startswith(slash + " "):
            rest = text[len(slash) :].strip()
            return (f"{sentence} for {rest}" if rest else sentence), None, 0

    pending = pending_question(await latest_command(session, conversation))
    if pending is None or not is_answer(text, pending):
        return text, None, 0
    original = pending.command.raw_text
    merged = ClarificationService.merge(original, pending.field, text)
    return merged, {pending.field: text}, pending.command.clarification_rounds + 1


async def _with_running_chain(
    session: AsyncSession,
    outcome: ParseOutcome,
    parser: IntentParser,
    context: PolicyContext,
    has_recent: bool,
) -> ParseOutcome:
    """Apply the running-chain rule once the service is known.

    Only a request that would otherwise go ahead is re-decided: a refusal or a question stands as
    it is. The re-decision reuses the parse, so no model is called twice.
    """
    if outcome.disposition is not Disposition.READY:
        return outcome
    running = await running_chain_for(session, outcome.intent.service)
    if running is None:
        return outcome
    with_chain = PolicyContext(
        role=context.role,
        high_urgency_used_today=context.high_urgency_used_today,
        high_urgency_quota=context.high_urgency_quota,
        running_chain=running,
        has_custom_steps=context.has_custom_steps,
    )
    decided = await parser.reconsider(
        outcome.intent,
        text=outcome.text,
        model_intent=outcome.model_intent,
        parser=outcome.parser,
        model=outcome.model,
        ai_fallback=outcome.ai_fallback,
        prompt_version=outcome.prompt_version,
        context=with_chain,
        clarification_round=outcome.clarification_round,
        has_recent_run=has_recent,
    )
    # Keep the parse's own record of how it was reached: its calls, notes and audit entries.
    return replace(
        decided,
        provider=outcome.provider,
        calls=outcome.calls,
        cached=outcome.cached,
        fallback_reasons=outcome.fallback_reasons,
        injection_suspected=outcome.injection_suspected,
        notes=tuple(note for note in outcome.notes),
        audit=(*outcome.audit, *decided.audit),
    )


def _reply(conversation: Conversation, content: str, payload: dict[str, Any]) -> Message:
    return Message(
        conversation_id=conversation.id,
        role=MessageRole.ASSISTANT.value,
        content=content,
        payload=payload,
    )


# ---------------------------------------------------------------------------
# What the reply says
# ---------------------------------------------------------------------------


def intent_summary(intent: Intent, branch: str | None = None, commit: str | None = None) -> str:
    """One line in plain words, for the reply and the approval dialog."""
    service = intent.service or "a service"
    action = intent.action
    environment = intent.environment.value if intent.environment else "an environment"
    if action is Action.BUILD:
        text = f"build {service}"
    elif action is Action.TEST:
        suite = f"the {intent.test_suite} tests" if intent.test_suite else "the tests"
        text = f"run {suite} for {service}"
    elif action is Action.DEPLOY:
        text = f"deploy {service} to {environment}"
    elif action is Action.BUILD_TEST_DEPLOY:
        text = f"build, test and deploy {service} to {environment}"
    elif action is Action.STATUS:
        text = f"show the status of {intent.service or 'your last run'}"
    elif action is Action.RERUN:
        text = f"re-run the last failed {intent.service or ''} test job".replace("  ", " ")
    elif action is Action.CANCEL:
        text = f"cancel the running {service} chain"
    else:
        text = "nothing I can do"
    shown_branch = branch or intent.branch
    if intent.generates_job and shown_branch:
        text += f" on {shown_branch}"
    shown_commit = commit or intent.commit
    if intent.generates_job and shown_commit:
        text += f" at {shown_commit[:12]}"
    if intent.urgency is not None:
        text += f", {intent.urgency.value} priority"
    if intent.extra_stages:
        text += ", with " + ", ".join(
            stage.value.replace("_", " ") for stage in intent.extra_stages
        )
    return text


def describe(outcome: ParseOutcome) -> tuple[str, dict[str, Any]]:
    """The reply's text, and the payload the frontend renders it from."""
    record = outcome.to_record()
    disposition = outcome.disposition
    if disposition is Disposition.READY:
        summary = intent_summary(outcome.intent, outcome.resolved_branch, outcome.resolved_commit)
        if outcome.intent.generates_job:
            content = f"Ready to generate: {summary}."
        else:
            content = f"Understood: {summary}."
        kind = "intent"
    elif disposition in (Disposition.NEEDS_CLARIFICATION, Disposition.NEEDS_JUSTIFICATION):
        content = outcome.question.question if outcome.question else "Could you say more?"
        kind = "question"
    elif disposition is Disposition.REFUSED:
        reasons = outcome.policy.reasons if outcome.policy else ()
        content = " ".join(reason.message for reason in reasons) or "That request was refused."
        kind = "refusal"
    else:
        card = outcome.help
        content = "\n".join([card.title, *card.lines]) if card else "Here is what I can do."
        kind = "help"
    return content, {"kind": kind, **record}


# ---------------------------------------------------------------------------
# Editing an intent
# ---------------------------------------------------------------------------


async def edit_intent(
    session: AsyncSession,
    *,
    user: User,
    command: NlCommand,
    changes: dict[str, Any],
    parser: IntentParser,
    settings: Settings,
) -> NlCommand:
    """Apply an edit from the intent card and decide again (4.5.3 steps 3 to 5)."""
    unknown = set(changes) - EDITABLE_FIELDS
    if unknown:
        raise conflict(
            ErrorCode.VALIDATION_FAILED,
            f"These fields cannot be edited: {', '.join(sorted(unknown))}.",
            fields=sorted(unknown),
        )
    await refuse_once_run(session, command.id)

    record = command.parsed_intent or {}
    current = Intent.model_validate(record.get("intent") or {})
    try:
        edited = current.with_changes(**changes)
    except ValueError as exc:
        raise conflict(ErrorCode.VALIDATION_FAILED, f"That edit is not valid: {exc}") from exc
    model_intent = Intent.model_validate(record.get("model_intent") or record.get("intent") or {})

    context = await policy_context(session, user=user, settings=settings, service=edited.service)
    outcome = await parser.reconsider(
        edited,
        text=command.raw_text,
        model_intent=model_intent,
        parser="LLM" if command.parser == "LLM" else "RULES",
        model=command.model,
        ai_fallback=bool(record.get("ai_fallback")),
        prompt_version=str(record.get("prompt_version") or ""),
        context=context,
        clarification_round=command.clarification_rounds,
        has_recent_run=await has_recent_run(session, user),
    )

    command.parsed_intent = outcome.to_record()
    command.status = outcome.status.value
    command.confidence = outcome.intent.confidence
    session.add(
        AuditLog(
            actor_id=user.id,
            action=INTENT_EDITED_AUDIT_ACTION,
            target=f"command:{command.id}",
            details={
                "changes": {key: _jsonable(value) for key, value in changes.items()},
                "disposition": outcome.disposition.value,
                "at": datetime.now(UTC).isoformat(),
            },
        )
    )
    for event in outcome.audit:
        session.add(
            AuditLog(
                actor_id=user.id,
                action=event.action,
                target=event.target,
                details={**event.details, "command_id": command.id},
            )
        )
    await session.flush()
    logger.info("intent_edited", command_id=command.id, disposition=outcome.disposition.value)
    return command


def _jsonable(value: Any) -> Any:
    if isinstance(value, list | tuple):
        return [str(item) for item in value]
    return value if value is None or isinstance(value, bool | int | float) else str(value)
