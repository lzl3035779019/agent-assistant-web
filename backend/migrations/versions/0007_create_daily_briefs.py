"""Create daily brief schedules and generated brief inbox.

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "brief_schedules",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("local_time", sa.String(length=5), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("weekdays", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("topics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("include_email", sa.Boolean(), nullable=False),
        sa.Column("include_calendar", sa.Boolean(), nullable=False),
        sa.Column("include_memory", sa.Boolean(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_brief_schedules_user_id", "brief_schedules", ["user_id"])
    op.create_index("ix_brief_schedules_enabled", "brief_schedules", ["enabled"])
    op.create_index("ix_brief_schedules_next_run_at", "brief_schedules", ["next_run_at"])
    op.create_index(
        "ix_brief_schedules_user_next", "brief_schedules", ["user_id", "next_run_at"]
    )

    op.create_table(
        "daily_briefs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("schedule_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("topics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("include_email", sa.Boolean(), nullable=False),
        sa.Column("include_calendar", sa.Boolean(), nullable=False),
        sa.Column("include_memory", sa.Boolean(), nullable=False),
        sa.Column("sections", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("unread", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["schedule_id"], ["brief_schedules.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_daily_briefs_user_id", "daily_briefs", ["user_id"])
    op.create_index("ix_daily_briefs_schedule_id", "daily_briefs", ["schedule_id"])
    op.create_index("ix_daily_briefs_status", "daily_briefs", ["status"])
    op.create_index("ix_daily_briefs_unread", "daily_briefs", ["unread"])
    op.create_index("ix_daily_briefs_user_created", "daily_briefs", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_table("daily_briefs")
    op.drop_table("brief_schedules")
