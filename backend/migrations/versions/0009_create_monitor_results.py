"""Create persistent information monitoring results.

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "monitor_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rule_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("rule_name", sa.String(length=255), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("change_count", sa.Integer(), nullable=False),
        sa.Column("baseline_created", sa.Boolean(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["rule_id"], ["monitor_rules.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_monitor_results_user_id", "monitor_results", ["user_id"])
    op.create_index("ix_monitor_results_rule_id", "monitor_results", ["rule_id"])
    op.create_index("ix_monitor_results_run_id", "monitor_results", ["run_id"])
    op.create_index(
        "ix_monitor_results_user_created",
        "monitor_results",
        ["user_id", "created_at"],
    )
    op.create_index(
        "ix_monitor_results_rule_created",
        "monitor_results",
        ["rule_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("monitor_results")
