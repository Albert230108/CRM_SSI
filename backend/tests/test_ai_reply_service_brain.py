from app.models.ai_reply_template import AiReplyTemplate, AiReplyTemplateBrainSection
from app.models.brain_section import BrainSection
from app.models.tenant import Tenant
from app.services import ai_reply_service


def _tenant(db_session, **overrides):
    defaults = dict(name="Brain Tenant", booking_id="B-brain-1", first_name="Alex", room_name="Studio 1")
    defaults.update(overrides)
    tenant = Tenant(**defaults)
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


def _section(db_session, path, title, content, parent=None):
    section = BrainSection(
        parent_id=parent.id if parent is not None else None,
        path=path,
        slug=path.rsplit(".", 1)[-1],
        title=title,
        content=content,
    )
    db_session.add(section)
    db_session.commit()
    db_session.refresh(section)
    return section


def _template(db_session, **overrides):
    defaults = dict(
        name="Brain template",
        sections=[{"label": "Persona", "content": "You are a helpful host."}],
        created_by_user_id=1,
    )
    defaults.update(overrides)
    template = AiReplyTemplate(**defaults)
    db_session.add(template)
    db_session.commit()
    db_session.refresh(template)
    return template


def test_prompt_is_unchanged_when_no_brain_is_involved(db_session):
    """Regression guard: templates that predate the Brain must produce the exact same payload."""
    tenant = _tenant(db_session)
    template = _template(
        db_session,
        guidelines="Be concise.",
        sections=[{"label": "Persona", "content": "You are a helpful host."}],
    )

    prompt = ai_reply_service.assemble_prompt(
        db_session, tenant=tenant, template=template, channel="email", rough_draft="Confirm the booking."
    )

    assert prompt == (
        "0. Goal & Guidelines\nBe concise.\n\n"
        "1. Template Text\n## Persona\nYou are a helpful host.\n\n"
        "4. Your Instruction\nConfirm the booking."
    )


def test_inline_brain_token_is_expanded_in_guidelines_and_sections(db_session):
    tenant = _tenant(db_session)
    _section(db_session, "policies", "Policies", "Free cancellation until 7 days before.")
    _section(db_session, "tone", "Tone", "Warm and brief.")
    template = _template(
        db_session,
        guidelines="{{brain:tone}}",
        sections=[{"label": "Rules", "content": "{{brain:policies}}"}],
    )

    prompt = ai_reply_service.assemble_prompt(
        db_session, tenant=tenant, template=template, channel="email", rough_draft=None
    )

    assert "Warm and brief." in prompt
    assert "Free cancellation until 7 days before." in prompt
    assert "{{brain:" not in prompt


def test_brain_content_resolves_tenant_placeholders(db_session):
    tenant = _tenant(db_session, first_name="Marta")
    _section(db_session, "greeting", "Greeting", "Hi {{first_name}}, welcome to {{room_name}}.")
    template = _template(db_session, sections=[{"label": "Open", "content": "{{brain:greeting}}"}])

    prompt = ai_reply_service.assemble_prompt(
        db_session, tenant=tenant, template=template, channel="email", rough_draft=None
    )

    assert "Hi Marta, welcome to Studio 1." in prompt


def test_attached_sections_render_as_knowledge_base_block(db_session):
    tenant = _tenant(db_session)
    section = _section(db_session, "wifi", "Wifi", "Network SSI, password guest2026.")
    template = _template(db_session)
    template.brain_links = [AiReplyTemplateBrainSection(brain_section_id=section.id, position=0)]
    db_session.commit()

    prompt = ai_reply_service.assemble_prompt(
        db_session, tenant=tenant, template=template, channel="email", rough_draft=None
    )

    assert "1b. Knowledge Base\n## Wifi\nNetwork SSI, password guest2026." in prompt


def test_extra_paths_append_after_the_templates_own_sections(db_session):
    tenant = _tenant(db_session)
    attached = _section(db_session, "wifi", "Wifi", "Network SSI.")
    _section(db_session, "parking", "Parking", "Garage on level -1.")
    template = _template(db_session)
    template.brain_links = [AiReplyTemplateBrainSection(brain_section_id=attached.id, position=0)]
    db_session.commit()

    prompt = ai_reply_service.assemble_prompt(
        db_session,
        tenant=tenant,
        template=template,
        channel="email",
        rough_draft=None,
        extra_brain_section_paths=["parking", "wifi"],
    )

    # The template's own attachment wins de-duplication, so it stays first.
    assert prompt.index("## Wifi") < prompt.index("## Parking")
    assert prompt.count("## Wifi") == 1


def test_pre_resolved_knowledge_content_skips_db_resolution(db_session, monkeypatch):
    """A caller (e.g. the planner loop's redraft attempts) can pass already-resolved text to
    avoid re-rendering the same brain paths from the DB on every attempt."""
    tenant = _tenant(db_session)
    section = _section(db_session, "wifi", "Wifi", "Network SSI, password guest2026.")
    template = _template(db_session)
    template.brain_links = [AiReplyTemplateBrainSection(brain_section_id=section.id, position=0)]
    db_session.commit()

    def _boom(*args, **kwargs):
        raise AssertionError("_build_knowledge_base should not be called when knowledge_content is supplied")

    monkeypatch.setattr(ai_reply_service, "_build_knowledge_base", _boom)

    prompt = ai_reply_service.assemble_prompt(
        db_session,
        tenant=tenant,
        template=template,
        channel="email",
        rough_draft=None,
        knowledge_content="Pre-resolved override text.",
    )

    assert "1b. Knowledge Base\nPre-resolved override text." in prompt
    assert "Network SSI" not in prompt


def test_unknown_extra_path_is_ignored(db_session):
    tenant = _tenant(db_session)
    template = _template(db_session)

    prompt = ai_reply_service.assemble_prompt(
        db_session,
        tenant=tenant,
        template=template,
        channel="email",
        rough_draft=None,
        extra_brain_section_paths=["does.not.exist"],
    )

    assert "1b. Knowledge Base" not in prompt


def test_reviewer_feedback_block_only_appears_on_a_redraft(db_session):
    tenant = _tenant(db_session)
    template = _template(db_session)

    without = ai_reply_service.assemble_prompt(
        db_session, tenant=tenant, template=template, channel="email", rough_draft=None
    )
    assert "6. Reviewer Feedback" not in without

    with_feedback = ai_reply_service.assemble_prompt(
        db_session,
        tenant=tenant,
        template=template,
        channel="email",
        rough_draft=None,
        reviewer_feedback="Wrong language; the guest wrote in Portuguese.",
    )
    assert "6. Reviewer Feedback" in with_feedback
    assert "Wrong language; the guest wrote in Portuguese." in with_feedback
    assert with_feedback.rstrip().endswith("Wrong language; the guest wrote in Portuguese.")


def test_previous_draft_block_only_appears_on_a_redraft(db_session):
    tenant = _tenant(db_session)
    template = _template(db_session)

    without = ai_reply_service.assemble_prompt(
        db_session, tenant=tenant, template=template, channel="email", rough_draft=None
    )
    assert "5. Your Previous Draft (Rejected)" not in without

    with_previous = ai_reply_service.assemble_prompt(
        db_session,
        tenant=tenant,
        template=template,
        channel="email",
        rough_draft=None,
        previous_draft="Dear guest, check-in is at 3pm.",
        reviewer_feedback="Wrong language; the guest wrote in Portuguese.",
    )
    assert "5. Your Previous Draft (Rejected)" in with_previous
    assert "Dear guest, check-in is at 3pm." in with_previous
    # The previous draft must come before the reviewer feedback that explains what was wrong with it.
    assert with_previous.index("5. Your Previous Draft") < with_previous.index("6. Reviewer Feedback")
