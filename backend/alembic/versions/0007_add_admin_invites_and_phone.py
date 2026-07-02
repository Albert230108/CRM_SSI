"""add admin invites and phone

Revision ID: 0007_add_admin_invites_and_phone
Revises: 0006_admin_invites_and_resets
Create Date: 2026-07-02 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0007_add_admin_invites_and_phone"
down_revision = "0006_admin_invites_and_resets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("phone", sa.String(length=100), nullable=True))
    op.create_table(
        "admin_invites",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("full_name", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=100), nullable=True),
        sa.Column("role", sa.String(length=20), nullable=False, server_default="non-admin"),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invited_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["invited_by_user_id"], ["users.id"]),
    )
    op.create_index(op.f("ix_admin_invites_id"), "admin_invites", ["id"], unique=False)
    op.create_index(op.f("ix_admin_invites_email"), "admin_invites", ["email"], unique=False)
    op.create_index(op.f("ix_admin_invites_token_hash"), "admin_invites", ["token_hash"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_admin_invites_token_hash"), table_name="admin_invites")
    op.drop_index(op.f("ix_admin_invites_email"), table_name="admin_invites")
    op.drop_index(op.f("ix_admin_invites_id"), table_name="admin_invites")
    op.drop_table("admin_invites")
    op.drop_column("users", "phone")