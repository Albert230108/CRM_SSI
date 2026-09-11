"""Covers build_instructions_text: the derivation from the Agent Instructions grid's cards back
into the flat `instructions` string every existing consumer (planner, checker, drafter, brain
writer, action writer, memory_qa, memory_redo, run_qa, redo_qa) reads unchanged."""
from app.services.ai_agent_instructions import build_instructions_text


def test_single_unlabeled_card_matches_input_verbatim():
    text = "Be concise and friendly.\n\nUse {{tenant_name}} when known."
    assert build_instructions_text([{"label": "", "content": text, "order": 0}]) == text


def test_multiple_cards_are_joined_in_order_not_array_order():
    sections = [
        {"label": "Tone", "content": "Be warm.", "order": 1},
        {"label": "Persona", "content": "You are the front desk.", "order": 0},
    ]
    result = build_instructions_text(sections)
    assert result == "## Persona\nYou are the front desk.\n\n## Tone\nBe warm."


def test_unlabeled_card_has_no_heading():
    result = build_instructions_text([{"label": "", "content": "Just the text.", "order": 0}])
    assert result == "Just the text."


def test_empty_content_cards_are_skipped():
    sections = [
        {"label": "Empty", "content": "   ", "order": 0},
        {"label": "Real", "content": "Has text.", "order": 1},
    ]
    assert build_instructions_text(sections) == "## Real\nHas text."


def test_missing_sections_returns_empty_string():
    assert build_instructions_text(None) == ""
    assert build_instructions_text([]) == ""


def test_missing_order_falls_back_to_zero_and_is_stable_among_ties():
    sections = [
        {"label": "First", "content": "A"},
        {"label": "Second", "content": "B"},
    ]
    assert build_instructions_text(sections) == "## First\nA\n\n## Second\nB"


def test_placeholders_are_left_literal_not_resolved():
    sections = [{"label": "", "content": "Today is {{current_date}} for {{tenant_name}}.", "order": 0}]
    assert build_instructions_text(sections) == "Today is {{current_date}} for {{tenant_name}}."
