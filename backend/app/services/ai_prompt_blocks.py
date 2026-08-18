"""Every fixed string the three AI agents put into their prompts, in one editable registry.

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

PLANNER_ROLE = "planner"
CHECKER_ROLE = "checker"
DRAFTER_ROLE = "drafter"

STRUCTURE_GROUP = "structure"
CONTEXT_GROUP = "context"

_LANGUAGE_DEFAULT = (
    "## Language\n"
    "The reply must be written in the same language the guest used in their latest message."
)
_INSTRUCTIONS_HEADER_DEFAULT = "## Your Instructions"


@dataclass(frozen=True)
class PromptBlock:
    key: str
    label: str
    help: str
    default: str
    group: str = STRUCTURE_GROUP


def _context_blocks(*, include_inbound: bool) -> tuple[PromptBlock, ...]:
    """The `##` headings on the shared context blocks, which every role emits."""
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
    ]
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
) + _context_blocks(include_inbound=True)


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
        key="draft",
        label="Draft heading",
        help="Sits above the draft reply being reviewed.",
        default="## Draft To Review",
    ),
    PromptBlock(
        key="output",
        label="Output instruction",
        help=(
            "Emitted last. Reword freely, but keep the field names - passed, feedback, issues - "
            "because the response schema in code enforces them."
        ),
        default=(
            "## Output\n"
            "Return JSON only. Set `passed` to true only if the draft can be sent as-is. When it "
            "cannot, `feedback` must be specific enough for the writer to fix it in one pass, and "
            "`issues` should list each problem separately."
        ),
    ),
) + _context_blocks(include_inbound=True)


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
        key="reviewer_feedback",
        label="Reviewer feedback framing",
        help="Only emitted on a redraft, after the checker has rejected the previous attempt.",
        default=(
            "5. Reviewer Feedback\n"
            "A reviewer rejected your previous draft for the reasons below. Rewrite the reply so that "
            "every point is addressed. Output only the corrected reply."
        ),
    ),
) + _context_blocks(include_inbound=False)


BLOCKS_BY_ROLE: dict[str, tuple[PromptBlock, ...]] = {
    PLANNER_ROLE: PLANNER_BLOCKS,
    CHECKER_ROLE: CHECKER_BLOCKS,
    DRAFTER_ROLE: DRAFTER_BLOCKS,
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
