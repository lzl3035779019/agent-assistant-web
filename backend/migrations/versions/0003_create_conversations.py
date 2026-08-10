"""Create persistent conversations and messages.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-08
"""

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("next_message_sequence", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_conversations_user_id", "conversations", ["user_id"])
    op.create_index("ix_conversations_updated_at", "conversations", ["updated_at"])
    op.create_index(
        "ix_conversations_user_updated",
        "conversations",
        ["user_id", "updated_at"],
    )

    op.add_column(
        "agent_runs",
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_agent_runs_conversation_id",
        "agent_runs",
        "conversations",
        ["conversation_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_agent_runs_conversation_id", "agent_runs", ["conversation_id"])

    op.create_table(
        "conversation_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "message_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_conversation_messages_conversation_id",
        "conversation_messages",
        ["conversation_id"],
    )
    op.create_index("ix_conversation_messages_run_id", "conversation_messages", ["run_id"])
    op.create_index(
        "uq_conversation_message_sequence",
        "conversation_messages",
        ["conversation_id", "sequence"],
        unique=True,
    )

    _backfill_existing_runs()


def _backfill_existing_runs() -> None:
    connection = op.get_bind()
    runs = connection.execute(
        sa.text(
            """
            SELECT id, user_id, objective, status, result_payload, error,
                   created_at, COALESCE(finished_at, created_at) AS updated_at
            FROM agent_runs
            WHERE conversation_id IS NULL
            ORDER BY created_at
            """
        )
    ).mappings()
    for run in runs:
        conversation_id = uuid4()
        answer = ""
        result_payload = run["result_payload"] or {}
        if isinstance(result_payload, dict):
            answer = str(result_payload.get("answer", ""))
        if not answer and run["status"] == "failed":
            answer = f"任务执行失败：{run['error']}"
        message_count = 2 if answer else 1
        connection.execute(
            sa.text(
                """
                INSERT INTO conversations
                    (id, user_id, title, next_message_sequence, created_at, updated_at)
                VALUES
                    (:id, :user_id, :title, :next_sequence, :created_at, :updated_at)
                """
            ),
            {
                "id": conversation_id,
                "user_id": run["user_id"],
                "title": str(run["objective"])[:120] or "历史对话",
                "next_sequence": message_count + 1,
                "created_at": run["created_at"],
                "updated_at": run["updated_at"],
            },
        )
        connection.execute(
            sa.text("UPDATE agent_runs SET conversation_id = :conversation_id WHERE id = :run_id"),
            {"conversation_id": conversation_id, "run_id": run["id"]},
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO conversation_messages
                    (id, conversation_id, run_id, sequence, role, content,
                     message_metadata, created_at)
                VALUES
                    (:id, :conversation_id, :run_id, 1, 'user', :content,
                     CAST(:metadata AS jsonb), :created_at)
                """
            ),
            {
                "id": uuid4(),
                "conversation_id": conversation_id,
                "run_id": run["id"],
                "content": run["objective"],
                "metadata": "{}",
                "created_at": run["created_at"],
            },
        )
        if answer:
            connection.execute(
                sa.text(
                    """
                    INSERT INTO conversation_messages
                        (id, conversation_id, run_id, sequence, role, content,
                         message_metadata, created_at)
                    VALUES
                        (:id, :conversation_id, :run_id, 2, 'assistant', :content,
                         CAST(:metadata AS jsonb), :created_at)
                    """
                ),
                {
                    "id": uuid4(),
                    "conversation_id": conversation_id,
                    "run_id": run["id"],
                    "content": answer,
                    "metadata": "{}",
                    "created_at": run["updated_at"],
                },
            )


def downgrade() -> None:
    op.drop_table("conversation_messages")
    op.drop_index("ix_agent_runs_conversation_id", table_name="agent_runs")
    op.drop_constraint("fk_agent_runs_conversation_id", "agent_runs", type_="foreignkey")
    op.drop_column("agent_runs", "conversation_id")
    op.drop_table("conversations")
