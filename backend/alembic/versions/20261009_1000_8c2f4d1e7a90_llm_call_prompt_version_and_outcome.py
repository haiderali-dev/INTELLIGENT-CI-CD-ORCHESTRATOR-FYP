"""llm_calls: prompt_version and outcome

BUILD_PROMPT 4.5.6 requires "the version stored on every call", and 4.4.3's ``llm_calls`` column
list has nowhere to put it. ``outcome`` is added for 4.5.1's "every call is recorded": a call that
was rate limited or failed carries no tokens, and without an outcome its row is indistinguishable
from a successful zero-token call. See docs/decisions.md D-036.

Both columns are additive and nullable or defaulted, so existing rows stay valid and the downgrade
is a plain drop.

Revision ID: 8c2f4d1e7a90
Revises: 31a5453f8d1d
Create Date: 2026-10-09 10:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8c2f4d1e7a90"
down_revision: str | None = "31a5453f8d1d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("llm_calls", sa.Column("prompt_version", sa.String(length=64), nullable=True))
    # server_default so rows written before this migration read as successful calls, which is
    # what they were: until now only successful calls could be recorded at all.
    op.add_column(
        "llm_calls",
        sa.Column("outcome", sa.String(length=16), nullable=False, server_default="ok"),
    )


def downgrade() -> None:
    op.drop_column("llm_calls", "outcome")
    op.drop_column("llm_calls", "prompt_version")
