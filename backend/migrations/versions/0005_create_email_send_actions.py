"""Create auditable email send actions.

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "email_send_actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recipient", sa.String(length=512), nullable=False),
        sa.Column("subject", sa.String(length=998), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("source_message_uid", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("provider_message_id", sa.String(length=512), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_email_send_actions_user_id", "email_send_actions", ["user_id"])
    op.create_index("ix_email_send_actions_status", "email_send_actions", ["status"])
    op.create_index(
        "ix_email_send_actions_user_created",
        "email_send_actions",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("email_send_actions")
