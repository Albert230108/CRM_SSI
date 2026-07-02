"""admin invites and resets

Revision ID: 0006_admin_invites_and_resets
Revises: 0005_add_full_beds24_fields_to_tenants
Create Date: 2026-07-02 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "0006_admin_invites_and_resets"
down_revision = "0005_add_full_beds24_fields_to_tenants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("password_hash", sa.String(length=255), nullable=True))
    op.add_column("users", sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.alter_column("users", "is_active", server_default=sa.true())
    op.create_table(
        "invitations",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=True),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(op.f("ix_invitations_id"), "invitations", ["id"], unique=False)
    op.create_index(op.f("ix_invitations_email"), "invitations", ["email"], unique=False)
    op.create_index(op.f("ix_invitations_token_hash"), "invitations", ["token_hash"], unique=True)

    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(op.f("ix_password_reset_tokens_id"), "password_reset_tokens", ["id"], unique=False)
    op.create_index(op.f("ix_password_reset_tokens_user_id"), "password_reset_tokens", ["user_id"], unique=False)
    op.create_index(op.f("ix_password_reset_tokens_token_hash"), "password_reset_tokens", ["token_hash"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_password_reset_tokens_token_hash"), table_name="password_reset_tokens")
    op.drop_index(op.f("ix_password_reset_tokens_user_id"), table_name="password_reset_tokens")
    op.drop_index(op.f("ix_password_reset_tokens_id"), table_name="password_reset_tokens")
    op.drop_table("password_reset_tokens")

    op.drop_index(op.f("ix_invitations_token_hash"), table_name="invitations")
    op.drop_index(op.f("ix_invitations_email"), table_name="invitations")
    op.drop_index(op.f("ix_invitations_id"), table_name="invitations")
    op.drop_table("invitations")

    op.drop_column("users", "is_admin")
    op.drop_column("users", "password_hash")
