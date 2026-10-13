"""The two assistants' conversations (T5.5).

BUILD_PROMPT 4.4.4: ``POST /api/assistants/{freestyle|pipeline}/conversations``;
``GET /api/conversations``; ``POST /api/conversations/{id}/messages``;
``PATCH /api/commands/{id}/intent``.

Two reads are added beside them, because the assistant workspace (4.7.4) cannot work without
them: ``GET /api/conversations/{id}`` opens a chat from the history list with its messages, and
``GET /api/commands/{id}`` re-reads an intent card. Recorded in docs/decisions.md D-045.

Any signed-in user may use either assistant; what they may *do* is the policy's decision
(4.5.5), applied to every message.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.clarify import ClarificationService
from app.ai.parser import IntentParser
from app.api.deps import (
    ApiRateLimit,
    AssistantRateLimit,
    CurrentUser,
    get_clarifier,
    get_intent_parser,
)
from app.core.settings import Settings
from app.db.models import Assistant as AssistantKind
from app.db.models import Conversation, Message, NlCommand
from app.db.session import get_db
from app.services import conversations as service
from app.services.dependencies import (
    get_jenkins_client,
    get_plugin_client,
    get_settings_dep,
)
from app.services.jenkins import JenkinsClient
from app.services.plugin import PluginClient

router = APIRouter(tags=["assistants"])

AssistantPath = Literal["freestyle", "pipeline"]


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class ConversationResponse(BaseModel):
    id: str
    assistant: str = Field(description="freestyle or pipeline")
    title: str
    created_at: datetime

    @classmethod
    def of(cls, conversation: Conversation) -> ConversationResponse:
        return cls(
            id=conversation.id,
            assistant=conversation.assistant.lower(),
            title=conversation.title,
            created_at=conversation.created_at,
        )


class ConversationPage(BaseModel):
    items: list[ConversationResponse]
    total: int
    limit: int
    offset: int


class MessageResponse(BaseModel):
    id: str
    role: str
    content: str
    payload: dict[str, Any] | None
    created_at: datetime

    @classmethod
    def of(cls, message: Message) -> MessageResponse:
        return cls(
            id=message.id,
            role=message.role,
            content=message.content,
            payload=message.payload,
            created_at=message.created_at,
        )


class ConversationDetail(ConversationResponse):
    messages: list[MessageResponse]


class MessageRequest(BaseModel):
    # The guard enforces 4.5.3's 1,000 characters with its own error; this only bounds the body.
    text: str = Field(min_length=1, max_length=4000)


class CommandResponse(BaseModel):
    id: str
    status: str
    disposition: str | None
    raw_text: str
    parser: str
    model: str | None
    confidence: float | None
    clarification_rounds: int
    record: dict[str, Any] = Field(
        description="The intent card: intent, question, policy, resolved"
    )
    created_at: datetime

    @classmethod
    def of(cls, command: NlCommand) -> CommandResponse:
        record = command.parsed_intent or {}
        return cls(
            id=command.id,
            status=command.status,
            disposition=record.get("disposition"),
            raw_text=command.raw_text,
            parser=command.parser,
            model=command.model,
            confidence=command.confidence,
            clarification_rounds=command.clarification_rounds,
            record=record,
            created_at=command.created_at,
        )


class MessageExchange(BaseModel):
    conversation: ConversationResponse
    user_message: MessageResponse
    assistant_message: MessageResponse
    command: CommandResponse | None


class IntentEdit(BaseModel):
    """Fields the intent card may change. Values are checked against the catalog afterwards.

    Unknown fields are refused rather than ignored: an edit that tried to change the action and
    was silently dropped would leave the user believing it had been applied.
    """

    model_config = ConfigDict(extra="forbid")

    service: str | None = None
    branch: str | None = None
    commit: str | None = None
    environment: str | None = None
    test_suite: str | None = None
    urgency: str | None = None
    extra_stages: list[str] | None = None
    justification: str | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/assistants/{assistant}/conversations",
    response_model=ConversationResponse,
    status_code=201,
    dependencies=[ApiRateLimit],
)
async def create_conversation(
    assistant: AssistantPath,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_db)],
    body: ConversationCreate | None = None,
) -> ConversationResponse:
    conversation = await service.create_conversation(
        session,
        user=user,
        assistant=AssistantKind(assistant.upper()),
        title=body.title if body else None,
    )
    return ConversationResponse.of(conversation)


@router.get("/conversations", response_model=ConversationPage, dependencies=[ApiRateLimit])
async def list_conversations(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_db)],
    assistant: AssistantPath | None = None,
    limit: Annotated[int | None, Query(ge=1, le=200)] = None,
    offset: Annotated[int | None, Query(ge=0)] = None,
) -> ConversationPage:
    page = await service.list_conversations(
        session,
        user=user,
        assistant=AssistantKind(assistant.upper()) if assistant else None,
        limit=limit,
        offset=offset,
    )
    return ConversationPage(
        items=[ConversationResponse.of(item) for item in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationDetail,
    dependencies=[ApiRateLimit],
)
async def get_conversation(
    conversation_id: str,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ConversationDetail:
    conversation = await service.get_conversation(
        session, user=user, conversation_id=conversation_id
    )
    messages = await service.list_messages(session, conversation)
    base = ConversationResponse.of(conversation)
    return ConversationDetail(
        **base.model_dump(), messages=[MessageResponse.of(message) for message in messages]
    )


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=MessageExchange,
    status_code=201,
    dependencies=[AssistantRateLimit],
)
async def post_message(
    conversation_id: str,
    body: MessageRequest,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_db)],
    parser: Annotated[IntentParser, Depends(get_intent_parser)],
    clarifier: Annotated[ClarificationService, Depends(get_clarifier)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    jenkins: Annotated[JenkinsClient, Depends(get_jenkins_client)],
    plugin: Annotated[PluginClient, Depends(get_plugin_client)],
    request: Request,
) -> MessageExchange:
    conversation = await service.get_conversation(
        session, user=user, conversation_id=conversation_id
    )
    exchange = await service.post_message(
        session,
        user=user,
        conversation=conversation,
        text=body.text,
        parser=parser,
        clarifier=clarifier,
        settings=settings,
        runs=service.RunContext(
            jenkins=jenkins,
            plugin=plugin,
            tracker=getattr(request.app.state, "tracker", None),
        ),
    )
    return MessageExchange(
        conversation=ConversationResponse.of(conversation),
        user_message=MessageResponse.of(exchange.user_message),
        assistant_message=MessageResponse.of(exchange.assistant_message),
        command=CommandResponse.of(exchange.command) if exchange.command else None,
    )


@router.get("/commands/{command_id}", response_model=CommandResponse, dependencies=[ApiRateLimit])
async def get_command(
    command_id: str,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> CommandResponse:
    command, _ = await service.get_command(session, user=user, command_id=command_id)
    return CommandResponse.of(command)


@router.patch(
    "/commands/{command_id}/intent",
    response_model=CommandResponse,
    dependencies=[AssistantRateLimit],
)
async def edit_intent(
    command_id: str,
    body: IntentEdit,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_db)],
    parser: Annotated[IntentParser, Depends(get_intent_parser)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> CommandResponse:
    command, _ = await service.get_command(session, user=user, command_id=command_id)
    changes = body.model_dump(exclude_unset=True)
    edited = await service.edit_intent(
        session, user=user, command=command, changes=changes, parser=parser, settings=settings
    )
    return CommandResponse.of(edited)
