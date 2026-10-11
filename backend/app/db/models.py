"""Every table from BUILD_PROMPT 4.4.3.

Deviations from the report's section 5.14 schema are deliberate and recorded in
``docs/decisions.md`` D-011: there is no ``job_dependencies`` or ``dependency_groups`` table.
Declared dependencies live on ``jobs.depends_on`` and grouping is computed per queue cycle by the
plugin, because a persisted grouping can disagree with the scheduler that derives it.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.base import Base, TimestampedCreation, UuidPrimaryKey, utcnow

# ---------------------------------------------------------------------------
# Enumerations. Stored as strings rather than native database enums so adding a
# value does not need a migration on PostgreSQL and the rows stay readable.
# ---------------------------------------------------------------------------


class Role(StrEnum):
    DEVELOPER = "DEVELOPER"
    DEVOPS = "DEVOPS"
    ADMIN = "ADMIN"


class Assistant(StrEnum):
    FREESTYLE = "FREESTYLE"
    PIPELINE = "PIPELINE"


class MessageRole(StrEnum):
    USER = "USER"
    ASSISTANT = "ASSISTANT"


class ParserKind(StrEnum):
    LLM = "LLM"
    RULES = "RULES"


class CommandStatus(StrEnum):
    PARSED = "PARSED"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    CONFIRMED = "CONFIRMED"
    REFUSED = "REFUSED"
    UNSUPPORTED = "UNSUPPORTED"


class PipelineStatus(StrEnum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    INVALID = "INVALID"
    APPROVED = "APPROVED"
    CANCELLED = "CANCELLED"


class JobType(StrEnum):
    FREESTYLE = "FREESTYLE"
    MAVEN = "MAVEN"
    PIPELINE = "PIPELINE"


class PriorityLevel(StrEnum):
    """Mirrors the plugin's enum. The values must stay identical or the score changes."""

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class RunResult(StrEnum):
    SUCCESS = "SUCCESS"
    UNSTABLE = "UNSTABLE"
    FAILURE = "FAILURE"
    ABORTED = "ABORTED"
    NOT_BUILT = "NOT_BUILT"
    RUNNING = "RUNNING"


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


class User(UuidPrimaryKey, TimestampedCreation, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default=Role.DEVELOPER.value)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    conversations: Mapped[list[Conversation]] = relationship(back_populates="user")

    @property
    def role_enum(self) -> Role:
        return Role(self.role)


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


class Service(UuidPrimaryKey, TimestampedCreation, Base):
    """A deployable service, mirrored from ``catalog/services.yaml``.

    The YAML remains the source of truth; this table is a cache so the API can join against it and
    the Admin page can show when each entry was last checked.
    """

    __tablename__ = "services"

    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    repo_url: Mapped[str] = mapped_column(String(512))
    default_branch: Mapped[str] = mapped_column(String(128), default="main")
    agent_label: Mapped[str] = mapped_column(String(64), default="linux")
    build_command: Mapped[str] = mapped_column(String(512))
    test_suites: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    deploy_commands: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    allowed_environments: Mapped[list[str]] = mapped_column(JSON, default=list)
    extra_stages: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    last_checked_at: Mapped[datetime | None] = mapped_column(default=None)


# ---------------------------------------------------------------------------
# Conversations and the AI core
# ---------------------------------------------------------------------------


class Conversation(UuidPrimaryKey, TimestampedCreation, Base):
    __tablename__ = "conversations"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    assistant: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(200), default="New chat")

    user: Mapped[User] = relationship(back_populates="conversations")
    messages: Mapped[list[Message]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )


class Message(UuidPrimaryKey, TimestampedCreation, Base):
    __tablename__ = "messages"

    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class NlCommand(UuidPrimaryKey, TimestampedCreation, Base):
    """One natural-language command and the intent parsed from it."""

    __tablename__ = "nl_commands"

    message_id: Mapped[str] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), index=True
    )
    raw_text: Mapped[str] = mapped_column(Text)
    parsed_intent: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    parser: Mapped[str] = mapped_column(String(16))
    model: Mapped[str | None] = mapped_column(String(128), default=None)
    confidence: Mapped[float | None] = mapped_column(Float, default=None)
    status: Mapped[str] = mapped_column(String(32), default=CommandStatus.PARSED.value)
    clarification_rounds: Mapped[int] = mapped_column(Integer, default=0)


class LlmCall(UuidPrimaryKey, TimestampedCreation, Base):
    """One provider call, for cost and latency reporting in the evaluation chapter."""

    __tablename__ = "llm_calls"

    command_id: Mapped[str | None] = mapped_column(
        ForeignKey("nl_commands.id", ondelete="SET NULL"), default=None, index=True
    )
    provider: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(128))
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    fallback_used: Mapped[bool] = mapped_column(Boolean, default=False)
    cached: Mapped[bool] = mapped_column(Boolean, default=False)


class GeneratedPipeline(UuidPrimaryKey, TimestampedCreation, Base):
    """A rendered artifact awaiting approval, or already approved."""

    __tablename__ = "generated_pipelines"

    command_id: Mapped[str] = mapped_column(
        ForeignKey("nl_commands.id", ondelete="CASCADE"), index=True
    )
    job_type: Mapped[str] = mapped_column(String(16))
    spec_yaml: Mapped[str] = mapped_column(Text)
    rendered_artifact: Mapped[str] = mapped_column(Text)
    validation_results: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default=PipelineStatus.DRAFT.value)
    approved_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    approved_at: Mapped[datetime | None] = mapped_column(default=None)
    # Set at approval so a double click cannot create two chains (BUILD_PROMPT 4.6.4).
    idempotency_key: Mapped[str | None] = mapped_column(String(64), default=None, unique=True)


# ---------------------------------------------------------------------------
# Jobs and runs
# ---------------------------------------------------------------------------


class Job(UuidPrimaryKey, TimestampedCreation, Base):
    __tablename__ = "jobs"

    jenkins_name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    job_type: Mapped[str] = mapped_column(String(16))
    service_id: Mapped[str | None] = mapped_column(
        ForeignKey("services.id", ondelete="SET NULL"), default=None, index=True
    )
    priority_level: Mapped[str] = mapped_column(String(16), default=PriorityLevel.MEDIUM.value)
    # Comma-separated upstream job names, the same shape the plugin property stores. Not a join
    # table: see D-011.
    depends_on: Mapped[str] = mapped_column(String(1024), default="")
    chain_position: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )

    runs: Mapped[list[JobRun]] = relationship(back_populates="job", cascade="all, delete-orphan")


class JobRun(UuidPrimaryKey, Base):
    """One execution. The four timestamps are what every waiting-time KPI derives from.

    No aggregate is stored. Report section 5.14 makes the same point: a metric that cannot be
    recomputed from raw rows is one nobody can defend.
    """

    __tablename__ = "job_runs"
    __table_args__ = (
        UniqueConstraint("job_id", "build_number", name="job_build"),
        Index("ix_job_runs_result_started", "result", "started_at"),
    )

    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    build_number: Mapped[int] = mapped_column(Integer)
    queue_entered_at: Mapped[datetime | None] = mapped_column(default=None)
    started_at: Mapped[datetime | None] = mapped_column(default=None)
    finished_at: Mapped[datetime | None] = mapped_column(default=None)
    result: Mapped[str] = mapped_column(String(16), default=RunResult.RUNNING.value)
    duration_ms: Mapped[int | None] = mapped_column(Integer, default=None)
    queue_wait_ms: Mapped[int | None] = mapped_column(Integer, default=None)
    # The queue item the trigger returned, used to map a queue entry onto a build number.
    queue_item_id: Mapped[int | None] = mapped_column(Integer, default=None, index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)

    job: Mapped[Job] = relationship(back_populates="runs")


# ---------------------------------------------------------------------------
# Experiments and analytics
# ---------------------------------------------------------------------------


class Experiment(UuidPrimaryKey, TimestampedCreation, Base):
    """One experiment run, as the report's section 5.14 designs it."""

    __tablename__ = "experiments"

    label: Mapped[str] = mapped_column(String(128), index=True)
    # baseline | optimized | stock, plus the M2 series imported for comparison.
    mode: Mapped[str] = mapped_column(String(32))
    workload: Mapped[str] = mapped_column(String(64))
    executors: Mapped[int] = mapped_column(Integer, default=1)
    repetition: Mapped[int] = mapped_column(Integer, default=1)
    plugin_version: Mapped[str | None] = mapped_column(String(64), default=None)
    jenkins_version: Mapped[str | None] = mapped_column(String(64), default=None)
    workload_hash: Mapped[str | None] = mapped_column(String(64), default=None)
    configuration: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(default=None)
    finished_at: Mapped[datetime | None] = mapped_column(default=None)

    metrics: Mapped[list[ExperimentMetric]] = relationship(
        back_populates="experiment", cascade="all, delete-orphan"
    )


class ExperimentMetric(UuidPrimaryKey, Base):
    """A single computed KPI for one experiment, kept alongside the raw rows it came from."""

    __tablename__ = "experiment_metrics"
    __table_args__ = (UniqueConstraint("experiment_id", "name", "band", name="experiment_metric"),)

    experiment_id: Mapped[str] = mapped_column(
        ForeignKey("experiments.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(64))
    # Empty for an overall figure, otherwise HIGH / MEDIUM / LOW.
    band: Mapped[str] = mapped_column(String(16), default="")
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(16), default="s")
    std_dev: Mapped[float | None] = mapped_column(Float, default=None)
    sample_size: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    experiment: Mapped[Experiment] = relationship(back_populates="metrics")


class ResourceSample(UuidPrimaryKey, Base):
    """A periodic executor-utilisation sample, for the utilisation KPI."""

    __tablename__ = "resource_samples"

    experiment_id: Mapped[str] = mapped_column(
        ForeignKey("experiments.id", ondelete="CASCADE"), index=True
    )
    sampled_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    busy_executors: Mapped[int] = mapped_column(Integer, default=0)
    total_executors: Mapped[int] = mapped_column(Integer, default=0)
    queue_length: Mapped[int] = mapped_column(Integer, default=0)


# ---------------------------------------------------------------------------
# Cross-cutting
# ---------------------------------------------------------------------------


class Notification(UuidPrimaryKey, TimestampedCreation, Base):
    __tablename__ = "notifications"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    read_at: Mapped[datetime | None] = mapped_column(default=None)


class AuditLog(UuidPrimaryKey, TimestampedCreation, Base):
    """Append-only record of anything worth answering "who did that?" about.

    BUILD_PROMPT 4.4.3 requires an entry for every approval, job creation, HIGH-urgency request,
    policy denial and admin change. ``actor_id`` is nullable and uses SET NULL so deleting a user
    cannot erase what they did.
    """

    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_action_created", "action", "created_at"),)

    actor_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None, index=True
    )
    action: Mapped[str] = mapped_column(String(64))
    target: Mapped[str] = mapped_column(String(255), default="")
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
