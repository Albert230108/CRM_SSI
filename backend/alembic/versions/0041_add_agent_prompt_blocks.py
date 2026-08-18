"""add editable prompt blocks to ai agent profiles and a drafter profile pin

Revision ID: 0041_add_agent_prompt_blocks
Revises: 0040_add_ai_reply_template_canvas_notes
Create Date: 2026-08-18 00:00:04.000000
"""
import json

from alembic import op
import sqlalchemy as sa


revision = "0041_add_agent_prompt_blocks"
down_revision = "0041_add_brain_section_color"
branch_labels = None
depends_on = None


# The prompt scaffolding as it was hardcoded before this migration. Inlined verbatim rather than
# imported from app.services.ai_prompt_blocks so that a later wording change in the registry can
# never retroactively alter what this migration wrote into existing rows.
PLANNER_DEFAULTS = {
    "preamble": "You are the planner for a short-stay rental CRM. Read the conversation and decide how to reply. Choose exactly one template from the catalogue, name any extra knowledge-base sections the reply needs, and write the concrete instruction the drafting model should follow. Do not write the reply itself.",
    "instructions_header": "## Your Instructions",
    "language": "## Language\nThe reply must be written in the same language the guest used in their latest message.",
    "catalogue": "## Template Catalogue\nPick `template_id` from this list only.",
    "brain_index": "## Knowledge Base Index\nPut any paths the reply needs into `extra_brain_sections`. Referencing a parent path also pulls in everything nested under it.",
    "operator_note": "## Operator Note\nA member of staff typed this into the reply box before asking for a draft. Treat it as the strongest signal about what the reply must contain.",
    "output": "## Output\nReturn JSON only. `confidence` is 0-1 for how well the chosen template fits. `reasoning` explains why you chose it. `alternatives` lists the other templates you seriously considered and why you rejected each. Set `should_reply` to false if no reply is warranted.",
    "ctx_history": "## Conversation History (last {limit} messages across {scope})",
    "ctx_beds24": "## Booking Information (Beds24)",
    "ctx_payments": "## Payments & Charges",
    "ctx_notes": "## Internal Notes",
    "ctx_inbound": "## Message To Answer"
}

CHECKER_DEFAULTS = {
    "preamble": "You are the reviewer for a short-stay rental CRM. Proof-read the draft reply below against your instructions and the conversation. You do not rewrite the reply - you either approve it or explain precisely what must change.",
    "instructions_header": "## Your Instructions",
    "language": "## Language\nThe reply must be written in the same language the guest used in their latest message.",
    "plan_instructions": "## What The Draft Was Asked To Do",
    "draft": "## Draft To Review",
    "output": "## Output\nReturn JSON only. Set `passed` to true only if the draft can be sent as-is. When it cannot, `feedback` must be specific enough for the writer to fix it in one pass, and `issues` should list each problem separately.",
    "ctx_history": "## Conversation History (last {limit} messages across {scope})",
    "ctx_beds24": "## Booking Information (Beds24)",
    "ctx_payments": "## Payments & Charges",
    "ctx_notes": "## Internal Notes",
    "ctx_inbound": "## Message To Answer"
}


def _has_column(connection, table_name: str, column_name: str) -> bool:
    return bool(
        connection.execute(
            sa.text(
                """
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = :table_name
                  AND column_name = :column_name
                """
            ),
            {"table_name": table_name, "column_name": column_name},
        ).first()
    )


def upgrade() -> None:
    connection = op.get_bind()
    if not _has_column(connection, "ai_agent_profiles", "prompt_blocks"):
        op.add_column(
            "ai_agent_profiles",
            sa.Column("prompt_blocks", sa.JSON(), server_default="{}", nullable=False),
        )
        # Seed the existing profiles so an operator opening the settings page sees the exact text
        # their run logs already contain, and behaviour is unchanged on day one.
        for role, defaults in (("planner", PLANNER_DEFAULTS), ("checker", CHECKER_DEFAULTS)):
            connection.execute(
                sa.text("UPDATE ai_agent_profiles SET prompt_blocks = :blocks WHERE role = :role"),
                {"blocks": json.dumps(defaults), "role": role},
            )

    if not _has_column(connection, "tenant_ai_settings", "drafter_profile_id"):
        op.add_column("tenant_ai_settings", sa.Column("drafter_profile_id", sa.Integer(), nullable=True))
        op.create_foreign_key(
            "fk_tenant_ai_settings_drafter_profile",
            "tenant_ai_settings",
            "ai_agent_profiles",
            ["drafter_profile_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    connection = op.get_bind()
    if _has_column(connection, "tenant_ai_settings", "drafter_profile_id"):
        op.drop_constraint("fk_tenant_ai_settings_drafter_profile", "tenant_ai_settings", type_="foreignkey")
        op.drop_column("tenant_ai_settings", "drafter_profile_id")
    if _has_column(connection, "ai_agent_profiles", "prompt_blocks"):
        op.drop_column("ai_agent_profiles", "prompt_blocks")
