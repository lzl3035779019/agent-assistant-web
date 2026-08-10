"""Create persistent user memories.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_memories",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("memory_type", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("memory_key", sa.String(length=64), nullable=False),
        sa.Column("source_conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("validation_reason", sa.String(length=255), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("usage_count", sa.Integer(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_conversation_id"], ["conversations.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["source_message_id"], ["conversation_messages.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_memories_user_id", "user_memories", ["user_id"])
    op.create_index("ix_user_memories_memory_type", "user_memories", ["memory_type"])
    op.create_index("ix_user_memories_enabled", "user_memories", ["enabled"])
    op.create_index(
        "ix_user_memories_source_conversation_id",
        "user_memories",
        ["source_conversation_id"],
    )
    op.create_index(
        "ix_user_memories_source_message_id", "user_memories", ["source_message_id"]
    )
    op.create_index(
        "uq_user_memory_key",
        "user_memories",
        ["user_id", "memory_type", "memory_key"],
        unique=True,
    )
    op.create_index(
        "ix_user_memories_user_updated", "user_memories", ["user_id", "updated_at"]
    )


def downgrade() -> None:
    op.drop_table("user_memories")
