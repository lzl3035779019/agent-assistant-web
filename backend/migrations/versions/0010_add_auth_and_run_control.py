"""add users, refresh tokens and run control fields

Revision ID: 0010_add_auth_and_run_control
Revises: 0009_create_monitor_results
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_add_auth_and_run_control"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("password_hash", sa.String(length=512), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_active", "users", ["active"], unique=False)
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
    op.create_index("ix_refresh_tokens_token_hash", "refresh_tokens", ["token_hash"], unique=True)
    op.create_index("ix_refresh_tokens_expires_at", "refresh_tokens", ["expires_at"])
    op.create_index(
        "ix_refresh_tokens_user_expires",
        "refresh_tokens",
        ["user_id", "expires_at"],
    )
    op.add_column(
        "agent_runs",
        sa.Column("idempotency_key", sa.String(length=128), nullable=False, server_default=""),
    )
    op.add_column("agent_runs", sa.Column("retry_of_run_id", sa.Uuid(), nullable=True))
    op.add_column(
        "agent_runs",
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "agent_runs",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "agent_runs",
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
    )
    op.add_column(
        "agent_runs",
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_agent_runs_retry_of",
        "agent_runs",
        "agent_runs",
        ["retry_of_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_agent_runs_retry_of_run_id", "agent_runs", ["retry_of_run_id"])
    op.create_index("ix_agent_runs_next_retry_at", "agent_runs", ["next_retry_at"])
    op.create_index(
        "uq_agent_runs_user_idempotency",
        "agent_runs",
        ["user_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key <> ''"),
    )


def downgrade() -> None:
    op.drop_index("uq_agent_runs_user_idempotency", table_name="agent_runs")
    op.drop_index("ix_agent_runs_retry_of_run_id", table_name="agent_runs")
    op.drop_index("ix_agent_runs_next_retry_at", table_name="agent_runs")
    op.drop_constraint("fk_agent_runs_retry_of", "agent_runs", type_="foreignkey")
    op.drop_column("agent_runs", "cancel_requested_at")
    op.drop_column("agent_runs", "next_retry_at")
    op.drop_column("agent_runs", "max_attempts")
    op.drop_column("agent_runs", "attempt_count")
    op.drop_column("agent_runs", "retry_of_run_id")
    op.drop_column("agent_runs", "idempotency_key")
    op.drop_table("refresh_tokens")
    op.drop_table("users")
