"""users.token_epoch

An Admin can now reset a user's password (found in T6.3: the sign-in page said "Ask an
administrator", and no endpoint let one help). A reset must also end the sessions the old password
opened. Every token carries the epoch it was issued in; a reset moves the user's epoch on, and a
token from another epoch is refused.

Additive only: a column defaulting to 0, which is the epoch every token issued before this
migration is read as. The downgrade drops it.

Revision ID: 9d4f2b6e8a10
Revises: 5e0b9c3a7d21
Create Date: 2026-10-18 13:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9d4f2b6e8a10"
down_revision: str | None = "5e0b9c3a7d21"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("token_epoch", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("token_epoch")
