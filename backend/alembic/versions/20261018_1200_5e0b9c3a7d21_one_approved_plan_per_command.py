"""one approved plan per command

The independent security review (docs/security-review-phases-3-5-6.md, finding 1) showed one
approved HIGH-urgency request could be generated and approved again, starting more HIGH chains
without a new justification or quota. The services now refuse it; this partial unique index holds
the same rule in the database, so two approvals of two plans for one command cannot both win.
Both PostgreSQL and SQLite support partial indexes.

The upgrade fails if a command already has two APPROVED plans. That is the state the rule forbids,
so it is reported rather than repaired.

Revision ID: 5e0b9c3a7d21
Revises: c4e1d07a5b92
Create Date: 2026-10-18 12:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5e0b9c3a7d21"
down_revision: str | None = "c4e1d07a5b92"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "uq_generated_pipelines_one_approved_per_command",
        "generated_pipelines",
        ["command_id"],
        unique=True,
        postgresql_where=sa.text("status = 'APPROVED'"),
        sqlite_where=sa.text("status = 'APPROVED'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_generated_pipelines_one_approved_per_command", table_name="generated_pipelines"
    )
