"""Create information monitoring rules and notifications.

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "monitor_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("query", sa.String(length=1000), nullable=False),
        sa.Column("interval_minutes", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("baseline_keys", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("last_result", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("last_run_status", sa.String(length=32), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=False),
        sa.Column("last_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["last_run_id"], ["agent_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_monitor_rules_user_id", "monitor_rules", ["user_id"])
    op.create_index("ix_monitor_rules_target_type", "monitor_rules", ["target_type"])
    op.create_index("ix_monitor_rules_enabled", "monitor_rules", ["enabled"])
    op.create_index("ix_monitor_rules_last_run_status", "monitor_rules", ["last_run_status"])
    op.create_index("ix_monitor_rules_last_run_id", "monitor_rules", ["last_run_id"])
    op.create_index("ix_monitor_rules_next_run_at", "monitor_rules", ["next_run_at"])
    op.create_index("ix_monitor_rules_user_next", "monitor_rules", ["user_id", "next_run_at"])

    op.create_table(
        "monitor_notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rule_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("unread", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["rule_id"], ["monitor_rules.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_monitor_notifications_user_id", "monitor_notifications", ["user_id"])
    op.create_index("ix_monitor_notifications_rule_id", "monitor_notifications", ["rule_id"])
    op.create_index("ix_monitor_notifications_unread", "monitor_notifications", ["unread"])
    op.create_index(
        "ix_monitor_notifications_user_created",
        "monitor_notifications",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("monitor_notifications")
    op.drop_table("monitor_rules")
