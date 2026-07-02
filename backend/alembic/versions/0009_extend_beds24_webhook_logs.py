"""extend beds24 webhook logs

Revision ID: 0009_extend_beds24_webhook_logs
Revises: 0008_add_beds24_webhook_logs
Create Date: 2026-07-02 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0009_extend_beds24_webhook_logs"
down_revision = "0008_add_beds24_webhook_logs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("beds24_webhook_logs", sa.Column("provider", sa.String(length=50), nullable=False, server_default="beds24"))
    op.add_column("beds24_webhook_logs", sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("beds24_webhook_logs", sa.Column("dedupe_key", sa.String(length=255), nullable=False, server_default=""))
    op.add_column("beds24_webhook_logs", sa.Column("external_event_id", sa.String(length=255), nullable=True))
    op.create_index(op.f("ix_beds24_webhook_logs_provider"), "beds24_webhook_logs", ["provider"], unique=False)
    op.create_index(op.f("ix_beds24_webhook_logs_processed_at"), "beds24_webhook_logs", ["processed_at"], unique=False)
    op.create_index(op.f("ix_beds24_webhook_logs_dedupe_key"), "beds24_webhook_logs", ["dedupe_key"], unique=False)
    op.create_index(op.f("ix_beds24_webhook_logs_external_event_id"), "beds24_webhook_logs", ["external_event_id"], unique=False)
    op.create_unique_constraint("uq_beds24_webhook_logs_provider_dedupe_key", "beds24_webhook_logs", ["provider", "dedupe_key"])


def downgrade() -> None:
    op.drop_constraint("uq_beds24_webhook_logs_provider_dedupe_key", "beds24_webhook_logs", type_="unique")
    op.drop_index(op.f("ix_beds24_webhook_logs_external_event_id"), table_name="beds24_webhook_logs")
    op.drop_index(op.f("ix_beds24_webhook_logs_dedupe_key"), table_name="beds24_webhook_logs")
    op.drop_index(op.f("ix_beds24_webhook_logs_processed_at"), table_name="beds24_webhook_logs")
    op.drop_index(op.f("ix_beds24_webhook_logs_provider"), table_name="beds24_webhook_logs")
    op.drop_column("beds24_webhook_logs", "external_event_id")
    op.drop_column("beds24_webhook_logs", "dedupe_key")
    op.drop_column("beds24_webhook_logs", "processed_at")
    op.drop_column("beds24_webhook_logs", "provider")
