"""add beds24 webhook logs

Revision ID: 0008_add_beds24_webhook_logs
Revises: 0007_add_admin_invites_and_phone
Create Date: 2026-07-02 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0008_add_beds24_webhook_logs"
down_revision = "0007_add_admin_invites_and_phone"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "beds24_webhook_logs",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("event_type", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("booking_id", sa.String(length=100), nullable=True),
        sa.Column("room_id", sa.String(length=100), nullable=True),
        sa.Column("tenant_id", sa.Integer(), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("result_message", sa.String(length=500), nullable=True),
        sa.Column("error_summary", sa.String(length=500), nullable=True),
        sa.Column("error_traceback", sa.Text(), nullable=True),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("parsed_fields", sa.JSON(), nullable=True),
    )
    op.create_index(op.f("ix_beds24_webhook_logs_id"), "beds24_webhook_logs", ["id"], unique=False)
    op.create_index(op.f("ix_beds24_webhook_logs_received_at"), "beds24_webhook_logs", ["received_at"], unique=False)
    op.create_index(op.f("ix_beds24_webhook_logs_event_type"), "beds24_webhook_logs", ["event_type"], unique=False)
    op.create_index(op.f("ix_beds24_webhook_logs_status"), "beds24_webhook_logs", ["status"], unique=False)
    op.create_index(op.f("ix_beds24_webhook_logs_booking_id"), "beds24_webhook_logs", ["booking_id"], unique=False)
    op.create_index(op.f("ix_beds24_webhook_logs_room_id"), "beds24_webhook_logs", ["room_id"], unique=False)
    op.create_index(op.f("ix_beds24_webhook_logs_tenant_id"), "beds24_webhook_logs", ["tenant_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_beds24_webhook_logs_tenant_id"), table_name="beds24_webhook_logs")
    op.drop_index(op.f("ix_beds24_webhook_logs_room_id"), table_name="beds24_webhook_logs")
    op.drop_index(op.f("ix_beds24_webhook_logs_booking_id"), table_name="beds24_webhook_logs")
    op.drop_index(op.f("ix_beds24_webhook_logs_status"), table_name="beds24_webhook_logs")
    op.drop_index(op.f("ix_beds24_webhook_logs_event_type"), table_name="beds24_webhook_logs")
    op.drop_index(op.f("ix_beds24_webhook_logs_received_at"), table_name="beds24_webhook_logs")
    op.drop_index(op.f("ix_beds24_webhook_logs_id"), table_name="beds24_webhook_logs")
    op.drop_table("beds24_webhook_logs")
