"""chains, and job_runs.chain_id

T5.7: a ``chains`` row per started chain, which is also 4.6.4's per-service lock ("a per-service
lock with a 30-minute expiry blocks a second chain while one is running"), and ``job_runs.chain_id``
so each build records which chain it was part of -- jobs are reused by every chain for their
service, so the job cannot carry it. See docs/decisions.md D-047.

The partial unique index allows one RUNNING chain per service, so two approvals racing for the same
service cannot both claim the lock. Both PostgreSQL and SQLite support partial indexes.

Names follow the metadata's naming convention (app/db/base.py), so autogenerate sees no difference
between these tables and the models.

Additive only: a new table and a nullable column. The downgrade drops both.

Revision ID: c4e1d07a5b92
Revises: 8c2f4d1e7a90
Create Date: 2026-10-13 12:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4e1d07a5b92"
down_revision: str | None = "8c2f4d1e7a90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chains",
        sa.Column("pipeline_id", sa.String(length=32), nullable=True),
        sa.Column("service", sa.String(length=128), nullable=False),
        sa.Column("job_type", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("jobs", sa.JSON(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("queue_item_id", sa.Integer(), nullable=True),
        sa.Column("started_by", sa.String(length=32), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lock_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["pipeline_id"],
            ["generated_pipelines.id"],
            name=op.f("fk_chains_pipeline_id_generated_pipelines"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["started_by"],
            ["users.id"],
            name=op.f("fk_chains_started_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chains")),
    )
    op.create_index(op.f("ix_chains_created_at"), "chains", ["created_at"], unique=False)
    op.create_index(op.f("ix_chains_pipeline_id"), "chains", ["pipeline_id"], unique=False)
    op.create_index(op.f("ix_chains_service"), "chains", ["service"], unique=False)
    op.create_index(op.f("ix_chains_started_by"), "chains", ["started_by"], unique=False)
    op.create_index(op.f("ix_chains_status"), "chains", ["status"], unique=False)
    op.create_index(
        "uq_chains_one_running_per_service",
        "chains",
        ["service"],
        unique=True,
        postgresql_where=sa.text("status = 'RUNNING'"),
        sqlite_where=sa.text("status = 'RUNNING'"),
    )

    with op.batch_alter_table("job_runs") as batch:
        batch.add_column(sa.Column("chain_id", sa.String(length=32), nullable=True))
        batch.create_foreign_key(
            op.f("fk_job_runs_chain_id_chains"),
            "chains",
            ["chain_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index(op.f("ix_job_runs_chain_id"), ["chain_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("job_runs") as batch:
        batch.drop_index(op.f("ix_job_runs_chain_id"))
        batch.drop_constraint(op.f("fk_job_runs_chain_id_chains"), type_="foreignkey")
        batch.drop_column("chain_id")

    op.drop_index("uq_chains_one_running_per_service", table_name="chains")
    op.drop_index(op.f("ix_chains_status"), table_name="chains")
    op.drop_index(op.f("ix_chains_started_by"), table_name="chains")
    op.drop_index(op.f("ix_chains_service"), table_name="chains")
    op.drop_index(op.f("ix_chains_pipeline_id"), table_name="chains")
    op.drop_index(op.f("ix_chains_created_at"), table_name="chains")
    op.drop_table("chains")
