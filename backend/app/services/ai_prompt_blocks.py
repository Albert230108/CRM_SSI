"""Every fixed string the agent prompts put into their prompts, in one editable registry.

Historically the role preamble, the framing above each section and the `## Output` JSON
instruction were Python literals, so an operator reading the run log at /ai-runs saw text
nobody in the business had written and had no way to change. Each of those strings is now a
named block with a built-in default; an agent profile may override any of them.

The registry is also the contract the settings UI renders from - label, help and default all
come from here, so the wording is never duplicated in TypeScript.

This module deliberately imports nothing from `ai_reply_service` or `ai_agent_orchestrator`;
both of them import it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.datetime_placeholders import resolve_datetime_placeholders

PLANNER_ROLE = "planner"
CHECKER_ROLE = "checker"
DRAFTER_ROLE = "drafter"
FORMATTER_ROLE = "formatter"
MEMORY_REDO_ROLE = "memory_redo"
MEMORY_QA_ROLE = "memory_qa"
RUN_QA_ROLE = "run_qa"

STRUCTURE_GROUP = "structure"
CONTEXT_GROUP = "context"

_LANGUAGE_DEFAULT = (
    "## Language\n"
    "The reply must be written in the same language the guest used in their latest message."
)
_INSTRUCTIONS_HEADER_DEFAULT = "## Your Instructions"
_ATTACHMENT_INSTRUCTION_DEFAULT = (
    "## Attachments\n"
    "The operator attached {count} file(s) to this request, included below as inline "
    "attachments: {names}. Review their actual visual/document content and factor it into "
    "your response where relevant."
)


@dataclass(frozen=True)
class PromptBlock:
    key: str
    label: str
    help: str
    default: str
    group: str = STRUCTURE_GROUP


def _context_blocks(*, include_inbound: bool, include_actions: bool = False) -> tuple[PromptBlock, ...]:
    """The `##` headings on the shared context blocks. Some callers add action items too."""
    blocks = [
        PromptBlock(
            key="ctx_history",
            label="Conversation history heading",
            help="{limit} and {scope} are replaced with the message count and the channels included.",
            default="## Conversation History (last {limit} messages across {scope})",
            group=CONTEXT_GROUP,
        ),
        PromptBlock(
            key="ctx_beds24",
            label="Booking information heading",
            help="Sits above the Beds24 booking fields.",
            default="## Booking Information (Beds24)",
            group=CONTEXT_GROUP,
        ),
        PromptBlock(
            key="ctx_payments",
            label="Payments heading",
            help="Sits above the payment and charge records.",
            default="## Payments & Charges",
            group=CONTEXT_GROUP,
        ),
        PromptBlock(
            key="ctx_notes",
            label="Internal notes heading",
            help="Sits above the tenant's internal notes.",
            default="## Internal Notes",
            group=CONTEXT_GROUP,
        ),
        PromptBlock(
            key="ctx_availability",
            label="Availability heading",
            help="Sits above the parsed Beds24 room/studio availability summary.",
            default="## Room Availability (Beds24)",
            group=CONTEXT_GROUP,
        ),
    ]
    if include_actions:
        blocks.append(
            PromptBlock(
                key="ctx_actions",
                label="Action items heading",
                help="Sits above the tenant's action items.",
                default="## Action Items",
                group=CONTEXT_GROUP,
            )
        )
    if include_inbound:
        blocks.append(
            PromptBlock(
                key="ctx_inbound",
                label="Message to answer heading",
                help="Sits above the guest message this run is reacting to.",
                default="## Message To Answer",
                group=CONTEXT_GROUP,
            )
        )
    return tuple(blocks)


PLANNER_BLOCKS: tuple[PromptBlock, ...] = (
    PromptBlock(
        key="preamble",
        label="Role preamble",
        help="The opening line that tells the model what job it is doing. Emitted first.",
        default=(
            "You are the planner for a short-stay rental CRM. Read the conversation and decide how to "
            "reply. Choose exactly one template from the catalogue, name any extra knowledge-base "
            "sections the reply needs, and write the concrete instruction the drafting model should "
            "follow. Do not write the reply itself."
        ),
    ),
    PromptBlock(
        key="instructions_header",
        label="Instructions heading",
        help="Sits above the Instructions you wrote for this profile. Omitted when Instructions is blank.",
        default=_INSTRUCTIONS_HEADER_DEFAULT,
    ),
    PromptBlock(
        key="language",
        label="Language rule",
        help="Only emitted when 'Match the guest's language' is on.",
        default=_LANGUAGE_DEFAULT,
    ),
    PromptBlock(
        key="catalogue",
        label="Template catalogue framing",
        help="Sits above the list of templates this tenant may use.",
        default="## Template Catalogue\nPick `template_id` from this list only.",
    ),
    PromptBlock(
        key="brain_index",
        label="Knowledge base index framing",
        help="Sits above the brain's table of contents. Only emitted when 'Include brain index' is on.",
        default=(
            "## Knowledge Base Index\n"
            "Put any paths the reply needs into `extra_brain_sections`. Referencing a parent path "
            "also pulls in everything nested under it."
        ),
    ),
    PromptBlock(
        key="brain_sections",
        label="Always included brain sections",
        help="Sits above planner-pinned brain sections that should always be rendered in full.",
        default="## Always Included Brain Sections",
    ),
    PromptBlock(
        key="ctx_fields",
        label="Structured fields heading",
        help="Sits above the tenant's named working-memory fields.",
        default="## Structured Fields",
        group=CONTEXT_GROUP,
    ),
    PromptBlock(
        key="ctx_entries",
        label="Free-text entries heading",
        help="Sits above the tenant's free-text brain entries.",
        default="## Free-Text Brain Entries",
        group=CONTEXT_GROUP,
    ),
    PromptBlock(
        key="operator_note",
        label="Operator note framing",
        help="Sits above whatever a member of staff typed into the reply box. Omitted when they typed nothing.",
        default=(
            "## Operator Note\n"
            "A member of staff typed this into the reply box before asking for a draft. Treat it as "
            "the strongest signal about what the reply must contain."
        ),
    ),
    PromptBlock(
        key="attachment_instruction",
        label="Attachment instruction",
        help=(
            "Only emitted when the operator's staged attachment(s) are being forwarded to the AI. "
            "{count} and {names} are replaced with how many files were attached and their name/type list."
        ),
        default=_ATTACHMENT_INSTRUCTION_DEFAULT,
    ),
    PromptBlock(
        key="output",
        label="Output instruction",
        help=(
            "Emitted last. Reword freely, but keep the field names - should_reply, template_id, "
            "extra_brain_sections, extra_instructions, confidence, reasoning, alternatives - because "
            "the response schema in code enforces them."
        ),
        default=(
            "## Output\n"
            "Return JSON only. `confidence` is 0-1 for how well the chosen template fits. `reasoning` "
            "explains why you chose it. `alternatives` lists the other templates you seriously "
            "considered and why you rejected each. Set `should_reply` to false if no reply is warranted."
        ),
    ),
) + _context_blocks(include_inbound=True, include_actions=True)


CHECKER_BLOCKS: tuple[PromptBlock, ...] = (
    PromptBlock(
        key="preamble",
        label="Role preamble",
        help="The opening line that tells the model what job it is doing. Emitted first.",
        default=(
            "You are the reviewer for a short-stay rental CRM. Proof-read the draft reply below "
            "against your instructions and the conversation. You do not rewrite the reply - you "
            "either approve it or explain precisely what must change."
        ),
    ),
    PromptBlock(
        key="instructions_header",
        label="Instructions heading",
        help="Sits above the Instructions you wrote for this profile. Omitted when Instructions is blank.",
        default=_INSTRUCTIONS_HEADER_DEFAULT,
    ),
    PromptBlock(
        key="language",
        label="Language rule",
        help="Only emitted when 'Match the guest's language' is on.",
        default=_LANGUAGE_DEFAULT,
    ),
    PromptBlock(
        key="plan_instructions",
        label="Plan instruction heading",
        help="Sits above the instruction the planner gave the drafter. Omitted when there was none.",
        default="## What The Draft Was Asked To Do",
    ),
    PromptBlock(
        key="knowledge",
        label="Knowledge base heading",
        help=(
            "Sits above the resolved brain sections the draft was actually written from, so the "
            "checker reviews against the same policy text the drafter saw. Only emitted when "
            "'Include brain index' is on and there is at least one resolved section."
        ),
        default="## Knowledge Base (used to write this draft)",
    ),
    PromptBlock(
        key="brain_index",
        label="Knowledge base index framing",
        help=(
            "Sits above the brain's table of contents (titles/paths only, no section text). Lets the "
            "checker name a section it needs that the draft didn't already include. Only emitted "
            "when 'Include brain index' is on."
        ),
        default=(
            "## Knowledge Base Index\n"
            "If properly reviewing this draft requires information from a section not already shown "
            "above under \"Knowledge Base\", list its path in `extra_brain_sections`. The reply will "
            "be rewritten with that section included and you will review it again."
        ),
    ),
    PromptBlock(
        key="ctx_fields",
        label="Structured fields heading",
        help="Sits above the tenant's named working-memory fields.",
        default="## Structured Fields",
        group=CONTEXT_GROUP,
    ),
    PromptBlock(
        key="ctx_entries",
        label="Free-text entries heading",
        help="Sits above the tenant's free-text brain entries.",
        default="## Free-Text Brain Entries",
        group=CONTEXT_GROUP,
    ),
    PromptBlock(
        key="template",
        label="Template heading",
        help=(
            "Sits above the goal, guidelines and template text the planner picked for this "
            "reply, so the checker can tell whether the draft actually followed it. Omitted "
            "when the template has no guidelines or sections."
        ),
        default=(
            "## Template The Draft Was Written From\n"
            "The draft was asked to follow this template. Treat a draft that ignores its "
            "instructions as failing review, and say which instruction was missed."
        ),
    ),
    PromptBlock(
        key="draft",
        label="Draft heading",
        help="Sits above the draft reply being reviewed.",
        default="## Draft To Review",
    ),
    PromptBlock(
        key="attachment_instruction",
        label="Attachment instruction",
        help=(
            "Only emitted when the operator's staged attachment(s) were forwarded to the AI. "
            "{count} and {names} are replaced with how many files were attached and their name/type list."
        ),
        default=_ATTACHMENT_INSTRUCTION_DEFAULT,
    ),
    PromptBlock(
        key="output",
        label="Output instruction",
        help=(
            "Emitted last. Reword freely, but keep the field names - passed, feedback, issues, "
            "extra_brain_sections - because the response schema in code enforces them."
        ),
        default=(
            "## Output\n"
            "Return JSON only. Set `passed` to true only if the draft can be sent as-is and follows "
            "the template it was written from. When it "
            "cannot, `feedback` must be specific enough for the writer to fix it in one pass, and "
            "`issues` should list each problem separately. Set `extra_brain_sections` to the paths of "
            "any additional knowledge-base sections you need to properly review this draft - leave it "
            "empty if the sections already shown are enough."
        ),
    ),
) + _context_blocks(include_inbound=True, include_actions=True)


DRAFTER_BLOCKS: tuple[PromptBlock, ...] = (
    PromptBlock(
        key="preamble",
        label="Role preamble",
        help="Blank by default - the drafter has never had an opening line. Fill it in to add one.",
        default="",
    ),
    PromptBlock(
        key="instructions_header",
        label="Instructions heading",
        help=(
            "Blank by default. Set both this and the profile's Instructions to give the drafter "
            "standing rules that apply on top of every template."
        ),
        default="",
    ),
    PromptBlock(
        key="guidelines",
        label="Guidelines label",
        help="Sits above the template's Goal & Guidelines text.",
        default="0. Goal & Guidelines",
    ),
    PromptBlock(
        key="sections",
        label="Template text label",
        help="Sits above the template's subprompt sections.",
        default="1. Template Text",
    ),
    PromptBlock(
        key="knowledge",
        label="Knowledge base label",
        help="Sits above the brain sections attached to the template plus any the planner asked for.",
        default="1b. Knowledge Base",
    ),
    PromptBlock(
        key="history",
        label="Message history label",
        help="Sits above the conversation history. Only emitted when the template includes history.",
        default="2. Message History",
    ),
    PromptBlock(
        key="beds24",
        label="Beds24 info label",
        help="Sits above the booking, payments and notes group.",
        default="3. Beds24 Info",
    ),
    PromptBlock(
        key="user_instruction",
        label="Typed instruction label",
        help="Sits above what the operator typed, or what the planner told the drafter to write.",
        default="4. Your Instruction",
    ),
    PromptBlock(
        key="previous_draft",
        label="Previous draft label",
        help="Only emitted on a redraft. Shows the drafter exactly what it wrote last time, so the rewrite is grounded rather than guessed at.",
        default="5. Your Previous Draft (Rejected)",
    ),
    PromptBlock(
        key="reviewer_feedback",
        label="Reviewer feedback framing",
        help="Only emitted on a redraft, after the checker has rejected the previous attempt.",
        default=(
            "6. Reviewer Feedback\n"
            "A reviewer rejected your previous draft for the reasons below. Rewrite the reply so that "
            "every point is addressed. Output only the corrected reply."
        ),
    ),
    PromptBlock(
        key="attachment_instruction",
        label="Attachment instruction",
        help=(
            "Only emitted when the operator's staged attachment(s) are being forwarded to the AI. "
            "{count} and {names} are replaced with how many files were attached and their name/type list."
        ),
        default=_ATTACHMENT_INSTRUCTION_DEFAULT,
    ),
) + _context_blocks(include_inbound=True)


FORMATTER_BLOCKS: tuple[PromptBlock, ...] = (
    PromptBlock(
        key="preamble",
        label="Role preamble",
        help="The opening line that tells the model what job it is doing. Emitted first.",
        default=(
            "You are the formatter for a short-stay rental CRM. Rewrite an approved plain-text reply "
            "into channel-appropriate output without changing its meaning."
        ),
    ),
    PromptBlock(
        key="instructions_header",
        label="Instructions heading",
        help="Sits above the Instructions you wrote for this profile. Omitted when Instructions is blank.",
        default=_INSTRUCTIONS_HEADER_DEFAULT,
    ),
    PromptBlock(
        key="email",
        label="Email formatting rule",
        help="Only emitted when formatting an email reply. Keep the result as HTML, without wrapper tags.",
        default=(
            "## Email Formatting\n"
            "Convert the reply to HTML. Preserve paragraphs and line breaks, use simple safe inline "
            "HTML, and do not add <html> or <body> wrappers."
        ),
    ),
    PromptBlock(
        key="whatsapp",
        label="WhatsApp formatting rule",
        help="Only emitted when formatting a WhatsApp reply. Use WhatsApp markdown, never HTML.",
        default=(
            "## WhatsApp Formatting\n"
            "Convert the reply to WhatsApp markdown. Use *bold*, _italic_, ~strikethrough~, and - "
            "for bullet lines. Never introduce HTML."
        ),
    ),
    PromptBlock(
        key="draft",
        label="Approved draft heading",
        help="Sits above the plain-text draft being reformatted.",
        default="## Approved Plain-Text Draft",
    ),
    PromptBlock(
        key="output",
        label="Output instruction",
        help="Emitted last. Keep the `formatted_text` field name because the response schema enforces it.",
        default=(
            "## Output\n"
            "Return JSON only with a `formatted_text` field containing the final formatted reply."
        ),
    ),
)



MEMORY_QA_BLOCKS: tuple[PromptBlock, ...] = (
    PromptBlock(
        key="preamble",
        label="Role preamble",
        help="The opening line that tells the model what job it is doing. Emitted first.",
        default=(
            "You answer a staff member's question about one tenant in a short-stay rental CRM, using "
            "only the working-memory context provided below. If the context doesn't contain the "
            "answer, say so plainly rather than guessing."
        ),
    ),
    PromptBlock(
        key="instructions_header",
        label="Instructions heading",
        help="Sits above the Instructions you wrote for this profile. Omitted when Instructions is blank.",
        default=_INSTRUCTIONS_HEADER_DEFAULT,
    ),
    PromptBlock(
        key="ctx_fields",
        label="Structured fields heading",
        help="Sits above the tenant's named working-memory fields.",
        default="## Structured Fields",
        group=CONTEXT_GROUP,
    ),
    PromptBlock(
        key="ctx_entries",
        label="Free-text entries heading",
        help="Sits above the tenant's free-text brain entries.",
        default="## Free-Text Brain Entries",
        group=CONTEXT_GROUP,
    ),
    PromptBlock(
        key="ctx_actions",
        label="Action items heading",
        help="Sits above the tenant's action items.",
        default="## Action Items",
        group=CONTEXT_GROUP,
    ),
    PromptBlock(
        key="ctx_brain_index",
        label="Knowledge base index heading",
        help="Sits above the brain's table of contents. Helpful when the answer needs a specific section path.",
        default="## Knowledge Base Index",
        group=CONTEXT_GROUP,
    ),
    PromptBlock(
        key="ctx_tenant_history",
        label="Tenant history heading",
        help="Sits above the tenant's email and WhatsApp conversation history.",
        default="## Tenant Conversation History",
        group=CONTEXT_GROUP,
    ),
    PromptBlock(
        key="ctx_beds24",
        label="Booking information heading",
        help="Sits above the tenant's Beds24 booking fields.",
        default="## Booking Information (Beds24)",
        group=CONTEXT_GROUP,
    ),
    PromptBlock(
        key="ctx_payments",
        label="Payments heading",
        help="Sits above the payment and charge records.",
        default="## Payments & Charges",
        group=CONTEXT_GROUP,
    ),
    PromptBlock(
        key="ctx_notes",
        label="Internal notes heading",
        help="Sits above the tenant's internal notes.",
        default="## Internal Notes",
        group=CONTEXT_GROUP,
    ),
    PromptBlock(
        key="ctx_availability",
        label="Availability heading",
        help="Sits above the parsed Beds24 room/studio availability summary.",
        default="## Room Availability (Beds24)",
        group=CONTEXT_GROUP,
    ),
    PromptBlock(
        key="ctx_history",
        label="Session history heading",
        help="Sits above prior memory-QA turns in this session.",
        default="## Prior Questions In This Session",
        group=CONTEXT_GROUP,
    ),
    PromptBlock(
        key="ctx_question",
        label="Question heading",
        help="Sits above the current staff question.",
        default="## Question",
        group=CONTEXT_GROUP,
    ),
)


MEMORY_REDO_BLOCKS: tuple[PromptBlock, ...] = (
    PromptBlock(
        key="qa_preamble",
        label="RedoQA Chat Preamble",
        help="The opening line for the redo-question chat. Emitted first.",
        default=(
            "You are answering a staff member's questions about one specific redo-agent run in a "
            "short-stay rental CRM. Use only the context provided below, and say plainly when "
            "the context does not support an answer instead of guessing."
        ),
    ),
    PromptBlock(
        key="preamble",
        label="Role preamble",
        help="The opening line that tells the model what job it is doing. Emitted first.",
        default=(
            "A staff member asked to redo an AI-generated reply in a short-stay rental CRM, explaining "
            "what to change and why. Decide whether that feedback reveals something worth permanently "
            "changing in this tenant's working memory, in a general rule that would apply across "
            "tenants, or in the agent profile/reply template that produced the draft (compare the "
            "feedback against the full run log below to tell these apart). Most redos are one-off "
            "wording notes and warrant no suggestion at all - only propose a change when the \"why\" "
            "points at a durable, generalizable fact, policy, or misconfiguration, not a one-time "
            "stylistic tweak."
        ),
    ),
    PromptBlock(
        key="instructions_header",
        label="Instructions heading",
        help="Sits above the Instructions you wrote for this profile. Omitted when Instructions is blank.",
        default=_INSTRUCTIONS_HEADER_DEFAULT,
    ),
    PromptBlock(
        key="ctx_fields",
        label="Structured fields heading",
        help="Sits above the tenant's named working-memory fields.",
        default="## Structured Fields (key | label | current value)",
        group=CONTEXT_GROUP,
    ),
    PromptBlock(
        key="ctx_entries",
        label="Free-text entries heading",
        help="Sits above the tenant's free-text brain entries.",
        default="## Free-Text Brain Entries",
        group=CONTEXT_GROUP,
    ),
    PromptBlock(
        key="ctx_beds24",
        label="Booking information heading",
        help="Sits above the tenant's Beds24 booking fields.",
        default="## Booking Information (Beds24)",
        group=CONTEXT_GROUP,
    ),
    PromptBlock(
        key="ctx_payments",
        label="Payments heading",
        help="Sits above the payment and charge records.",
        default="## Payments & Charges",
        group=CONTEXT_GROUP,
    ),
    PromptBlock(
        key="ctx_notes",
        label="Internal notes heading",
        help="Sits above the tenant's internal notes.",
        default="## Internal Notes",
        group=CONTEXT_GROUP,
    ),
    PromptBlock(
        key="ctx_rules",
        label="Global rules heading",
        help="Sits above the existing working-memory rules.",
        default="## Existing Global Rules (id | condition -> action)",
        group=CONTEXT_GROUP,
    ),
    PromptBlock(
        key="ctx_availability",
        label="Availability heading",
        help="Sits above the parsed Beds24 room/studio availability summary.",
        default="## Availability",
        group=CONTEXT_GROUP,
    ),
    PromptBlock(
        key="draft",
        label="Draft heading",
        help="Sits above the draft being redone.",
        default="## Draft Being Redone",
        group=CONTEXT_GROUP,
    ),
    PromptBlock(
        key="ctx_recent_decisions",
        label="Recent send/dismiss reasoning heading",
        help="Sits above recent AI-draft send/dismiss outcomes and why they happened, for this tenant.",
        default="## Recent Send/Dismiss Reasoning",
        group=CONTEXT_GROUP,
    ),
    PromptBlock(
        key="ctx_redo",
        label="Redo feedback heading",
        help="Sits above the staff member's redo explanation.",
        default="## Redo Feedback",
        group=CONTEXT_GROUP,
    ),
    PromptBlock(
        key="ctx_history",
        label="RedoQA history heading",
        help="Sits above prior redo-QA turns in this session.",
        default="## Prior Questions In This Redo Session",
        group=CONTEXT_GROUP,
    ),
    PromptBlock(
        key="ctx_question",
        label="Question heading",
        help="Sits above the staff member's follow-up question in the redo QA chat.",
        default="## Question",
        group=CONTEXT_GROUP,
    ),
    PromptBlock(
        key="ctx_run_log",
        label="Full run log heading",
        help=(
            "Sits above the full planner/drafter/checker log of the run that produced the draft "
            "being redone (prompts, responses, and which profile/template were used). Omitted "
            "when no run is linked."
        ),
        default="## Full Run Log Being Redone",
        group=CONTEXT_GROUP,
    ),
    PromptBlock(
        key="output",
        label="Output instruction",
        help=(
            "Emitted last. Reword freely, but keep the field names - suggestions, kind, field_key, "
            "value, content, rule_id, condition_text, action_text, profile_id, template_id, field, "
            "section_id, suggested_text, reasoning - because the response schema in code enforces "
            "them."
        ),
        default=(
            "## Output\n"
            "Return JSON only. `suggestions` is a list of 0 or more proposed changes, each with a "
            "`kind`, the fields relevant to that kind, and a `reasoning` explaining why it's durable "
            "and generalizable rather than one-off. Compare the redo feedback against the run log: "
            "if the planner/drafter/checker's own instructions caused the mistake, propose a "
            "`profile_change`; if the chosen reply template's guidelines/sections caused it, propose "
            "a `template_change` - when `field` is `\"sections\"`, set `section_id` to one of the "
            "`section_id=...` values listed under the run log's template sections, never invent one; "
            "leave `section_id` empty for any other `field`. Only propose "
            "`rule_add`/`rule_modify`/`rule_delete` or `field_value`/`brain_entry` for a durable, "
            "generalizable fact or policy. Leave `suggestions` empty when in doubt."
        ),
    ),
)


RUN_QA_BLOCKS: tuple[PromptBlock, ...] = (
    PromptBlock(
        key="qa_preamble",
        label="Run QA Chat Preamble",
        help="The opening line for the run-debug chat. Emitted first.",
        default=(
            "You are answering a staff member's questions about one specific AI agent run in a "
            "short-stay rental CRM - it may be a planner, brain writer, or action writer run. Use "
            "only the run log provided below (its prompts, responses, model, and settings), and say "
            "plainly when the log does not support an answer instead of guessing."
        ),
    ),
    PromptBlock(
        key="instructions_header",
        label="Instructions heading",
        help="Sits above the Instructions you wrote for this profile. Omitted when Instructions is blank.",
        default=_INSTRUCTIONS_HEADER_DEFAULT,
    ),
    PromptBlock(
        key="ctx_run_summary",
        label="Run summary heading",
        help="Sits above the one-line summary of the run being debugged (id, mode, channel, status).",
        default="## Run Summary",
        group=CONTEXT_GROUP,
    ),
    PromptBlock(
        key="ctx_run_log",
        label="Full run log heading",
        help=(
            "Sits above the full step log of the run being debugged - every stage's prompt and "
            "response, the model used, and which profile/template drove it."
        ),
        default="## Full Run Log",
        group=CONTEXT_GROUP,
    ),
    PromptBlock(
        key="ctx_history",
        label="Run QA history heading",
        help="Sits above prior run-QA turns in this session.",
        default="## Prior Questions In This Session",
        group=CONTEXT_GROUP,
    ),
    PromptBlock(
        key="ctx_question",
        label="Question heading",
        help="Sits above the staff member's follow-up question in the run QA chat.",
        default="## Question",
        group=CONTEXT_GROUP,
    ),
)


BLOCKS_BY_ROLE: dict[str, tuple[PromptBlock, ...]] = {
    PLANNER_ROLE: PLANNER_BLOCKS,
    CHECKER_ROLE: CHECKER_BLOCKS,
    DRAFTER_ROLE: DRAFTER_BLOCKS,
    FORMATTER_ROLE: FORMATTER_BLOCKS,
    MEMORY_QA_ROLE: MEMORY_QA_BLOCKS,
    MEMORY_REDO_ROLE: MEMORY_REDO_BLOCKS,
    RUN_QA_ROLE: RUN_QA_BLOCKS,
}

DEFAULTS_BY_ROLE: dict[str, dict[str, str]] = {
    role: {block.key: block.default for block in blocks} for role, blocks in BLOCKS_BY_ROLE.items()
}


def resolve_blocks(profile: Any | None, role: str) -> dict[str, str]:
    """Merge the role's built-in defaults with whatever the profile overrides.

    A key *present* in `prompt_blocks` wins even when its value is an empty string - that is how
    an operator deletes a block from the prompt entirely. A key that is *absent* falls back to
    the built-in default, so a profile saved before a block existed keeps working.
    """
    resolved = dict(DEFAULTS_BY_ROLE.get(role, {}))
    overrides = getattr(profile, "prompt_blocks", None) or {}
    if isinstance(overrides, dict):
        for key in resolved:
            if key in overrides:
                value = overrides[key]
                resolved[key] = "" if value is None else str(value)
    for key, value in list(resolved.items()):
        resolved[key] = resolve_datetime_placeholders(value)
    return resolved


def fill(text: str, **values: object) -> str:
    """Substitute `{name}` placeholders literally.

    Uses str.replace rather than str.format so an unmatched brace in operator-written text can
    never raise KeyError/ValueError mid-run.
    """
    for name, value in values.items():
        text = text.replace("{" + name + "}", str(value))
    return text


def join(header: str, body: str) -> str:
    """Put a block's fixed framing above its live data, tolerating either side being empty."""
    header = header or ""
    body = body or ""
    if not header:
        return body
    if not body:
        return header
    return f"{header}\n{body}"
