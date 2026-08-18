from app.models.brain_section import BrainSection
from app.services import brain_service


def _section(db_session, path, title, content=None, parent=None, position=0, is_active=True):
    section = BrainSection(
        parent_id=parent.id if parent is not None else None,
        path=path,
        slug=path.rsplit(".", 1)[-1],
        title=title,
        content=content,
        position=position,
        is_active=is_active,
    )
    db_session.add(section)
    db_session.commit()
    db_session.refresh(section)
    return section


def test_token_expands_node_and_descendants(db_session):
    root = _section(db_session, "policies", "Policies", "General rules.")
    _section(db_session, "policies.cancellation", "Cancellation", "Free until 7 days before.", parent=root)

    result = brain_service.resolve_brain_tokens(db_session, "Before:\n{{brain:policies}}\nAfter")

    assert result.missing_paths == []
    assert "## Policies" in result.text
    assert "General rules." in result.text
    assert "### Cancellation" in result.text
    assert "Free until 7 days before." in result.text
    assert result.text.startswith("Before:")
    assert result.text.endswith("After")


def test_descendants_render_in_position_order(db_session):
    root = _section(db_session, "root", "Root")
    _section(db_session, "root.b", "Second", "b", parent=root, position=1)
    _section(db_session, "root.a", "First", "a", parent=root, position=0)

    text = brain_service.render_section(db_session, "root")
    assert text.index("First") < text.index("Second")


def test_inactive_sections_are_skipped(db_session):
    root = _section(db_session, "kb", "KB", "visible")
    _section(db_session, "kb.hidden", "Hidden", "secret", parent=root, is_active=False)
    _section(db_session, "off", "Off", "nope", is_active=False)

    assert "secret" not in brain_service.render_section(db_session, "kb")
    result = brain_service.resolve_brain_tokens(db_session, "{{brain:off}}")
    assert result.text == ""
    assert result.missing_paths == ["off"]


def test_nested_tokens_inside_brain_content_are_expanded(db_session):
    _section(db_session, "inner", "Inner", "inner text")
    _section(db_session, "outer", "Outer", "outer text {{brain:inner}}")

    result = brain_service.resolve_brain_tokens(db_session, "{{brain:outer}}")
    assert "outer text" in result.text
    assert "inner text" in result.text


def test_reference_cycle_terminates_without_raw_tokens(db_session):
    _section(db_session, "a", "A", "a-text {{brain:b}}")
    _section(db_session, "b", "B", "b-text {{brain:a}}")

    result = brain_service.resolve_brain_tokens(db_session, "{{brain:a}}")
    assert "{{brain:" not in result.text
    assert "a-text" in result.text
    assert "b-text" in result.text


def test_depth_cap_strips_remaining_tokens(db_session):
    _section(db_session, "l1", "L1", "one {{brain:l2}}")
    _section(db_session, "l2", "L2", "two {{brain:l3}}")
    _section(db_session, "l3", "L3", "three {{brain:l4}}")
    _section(db_session, "l4", "L4", "four")

    result = brain_service.resolve_brain_tokens(db_session, "{{brain:l1}}")
    assert "{{brain:" not in result.text
    assert "three" in result.text
    assert "four" not in result.text


def test_unknown_path_is_dropped_and_reported(db_session):
    result = brain_service.resolve_brain_tokens(db_session, "start {{brain:nope.here}} end")
    assert result.text == "start  end"
    assert result.missing_paths == ["nope.here"]


def test_tenant_placeholders_inside_brain_content_survive_expansion(db_session):
    _section(db_session, "greeting", "Greeting", "Hello {{first_name}}!")

    result = brain_service.resolve_brain_tokens(db_session, "{{brain:greeting}}")
    # The brain pass must leave tenant tokens alone so the tenant pass can fill them later.
    assert "{{first_name}}" in result.text


def test_render_paths_deduplicates_and_preserves_order(db_session):
    _section(db_session, "one", "One", "1")
    _section(db_session, "two", "Two", "2")

    result = brain_service.render_paths(db_session, ["two", "one", "two", "missing"])
    assert result.text.index("## Two") < result.text.index("## One")
    assert result.missing_paths == ["missing"]


def test_referenced_paths_extracts_tokens_in_order(db_session):
    assert brain_service.referenced_paths("{{brain:b}} x {{brain:a}} y {{brain:b}}") == ["b", "a"]


def test_brain_index_lists_active_paths(db_session):
    _section(db_session, "policies", "Policies")
    _section(db_session, "hidden", "Hidden", is_active=False)

    index = brain_service.build_brain_index(db_session)
    assert "- policies — Policies" in index
    assert "hidden" not in index
