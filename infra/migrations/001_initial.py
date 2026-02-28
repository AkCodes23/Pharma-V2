"""
Pharma Agentic AI — Alembic database migrations.

Initial migration: creates core PostgreSQL tables for
session management, audit trail, and agent metrics.
"""

revision = "001"
down_revision = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


def upgrade() -> None:
    """Create core database tables."""

    # ── Sessions table ────────────────────────────────────
    op.create_table(
        "sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("query", sa.Text, nullable=False),
        sa.Column("drug_name", sa.String(255), nullable=True),
        sa.Column("market", sa.String(100), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="PENDING"),
        sa.Column("decision", sa.String(50), nullable=True),
        sa.Column("grounding_score", sa.Float, nullable=True),
        sa.Column("conflict_count", sa.Integer, server_default="0"),
        sa.Column("pillar_count", sa.Integer, server_default="0"),
        sa.Column("report_url", sa.Text, nullable=True),
        sa.Column("metadata", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_sessions_status", "sessions", ["status"])
    op.create_index("ix_sessions_created_at", "sessions", ["created_at"])
    op.create_index("ix_sessions_drug_name", "sessions", ["drug_name"])

    # ── Audit trail ───────────────────────────────────────
    op.create_table(
        "audit_trail",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("session_id", UUID(as_uuid=True), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("user_id", sa.String(255), nullable=False, server_default="system"),
        sa.Column("agent_type", sa.String(100), nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("payload", JSONB, nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_audit_session_id", "audit_trail", ["session_id"])
    op.create_index("ix_audit_timestamp", "audit_trail", ["timestamp"])
    op.create_index("ix_audit_agent_type", "audit_trail", ["agent_type"])

    # ── Agent metrics (time-series) ───────────────────────
    op.create_table(
        "agent_metrics",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("agent_type", sa.String(100), nullable=False),
        sa.Column("session_id", UUID(as_uuid=True), nullable=True),
        sa.Column("latency_ms", sa.Integer, nullable=False),
        sa.Column("success", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("error_type", sa.String(100), nullable=True),
        sa.Column("token_count", sa.Integer, nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_metrics_agent", "agent_metrics", ["agent_type"])
    op.create_index("ix_metrics_recorded", "agent_metrics", ["recorded_at"])

    # ── DPO training pairs ────────────────────────────────
    op.create_table(
        "dpo_training_pairs",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("session_id", UUID(as_uuid=True), nullable=True),
        sa.Column("prompt", sa.Text, nullable=False),
        sa.Column("chosen_response", sa.Text, nullable=False),
        sa.Column("rejected_response", sa.Text, nullable=False),
        sa.Column("pillar", sa.String(50), nullable=True),
        sa.Column("grounding_score", sa.Float, nullable=True),
        sa.Column("human_validated", sa.Boolean, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_dpo_pillar", "dpo_training_pairs", ["pillar"])


def downgrade() -> None:
    """Drop all tables in reverse order."""
    op.drop_table("dpo_training_pairs")
    op.drop_table("agent_metrics")
    op.drop_table("audit_trail")
    op.drop_table("sessions")
