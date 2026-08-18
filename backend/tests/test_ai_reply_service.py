from datetime import datetime, timedelta, timezone

from app.models.ai_reply_template import AiReplyTemplate
from app.models.communication import Communication
from app.models.finance import Finance
from app.models.gmail_integration import Conversation, ConversationMessage
from app.models.tenant import Tenant
from app.models.tenant_channel_endpoint import TenantChannelEndpoint
from app.models.tenant_conversation_link import TenantConversationLink
from app.services import ai_reply_service


def _create_tenant(db_session, **overrides):
    defaults = dict(
        name="Prompt Tenant",
        booking_id="B-prompt-1",
        first_name="Alex",
        last_name="Doe",
        email="alex@example.com",
        check_in="2026-08-01",
        check_out="2026-08-05",
        room_name="Studio 1",
        booking_status="confirmed",
    )
    defaults.update(overrides)
    tenant = Tenant(**defaults)
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


def _template(**overrides):
    defaults = dict(
        name="Test template",
        guidelines=None,
        sections=[{"label": "Persona", "content": "You are a helpful host."}],
        include_history=False,
        history_message_limit=None,
        include_beds24=False,
        include_payments=False,
        created_by_user_id=1,
    )
    defaults.update(overrides)
    return AiReplyTemplate(**defaults)


def _capture_gemini_call(monkeypatch):
    captured = {}

    def fake_generate_text_flat(prompt: str) -> str:
        captured["prompt"] = prompt
        return "Generated reply text"

    monkeypatch.setattr(ai_reply_service.gemini_client, "generate_text_flat", fake_generate_text_flat)
    return captured


def test_sections_are_concatenated_in_order(db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    template = _template(
        sections=[
            {"label": "Persona", "content": "You are a helpful host."},
            {"label": "Tone", "content": "Be warm and concise."},
        ]
    )
    captured = _capture_gemini_call(monkeypatch)

    result = ai_reply_service.build_prompt_and_generate(
        db_session, tenant=tenant, template=template, channel="email", rough_draft="Let them know check-in is at 3pm."
    )

    assert result == "Generated reply text"
    assert captured["prompt"].index("Persona") < captured["prompt"].index("Tone")
    assert "You are a helpful host." in captured["prompt"]
    assert "Be warm and concise." in captured["prompt"]
    assert "Let them know check-in is at 3pm." in captured["prompt"]


def test_canvas_notes_are_never_sent_to_the_ai(db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    template = _template(
        sections=[
            {"label": "Persona", "content": "You are a helpful host.", "id": "sec-1", "x": 0, "y": 0, "order": 0},
        ],
        canvas_notes=[
            {"id": "note-1", "text": "REMEMBER-TO-CHECK-WITH-LEGAL-BEFORE-SENDING", "x": 10, "y": 10, "color": "yellow"},
        ],
    )
    captured = _capture_gemini_call(monkeypatch)

    ai_reply_service.build_prompt_and_generate(
        db_session, tenant=tenant, template=template, channel="email", rough_draft="Let them know check-in is at 3pm."
    )

    assert "REMEMBER-TO-CHECK-WITH-LEGAL-BEFORE-SENDING" not in captured["prompt"]
    assert "You are a helpful host." in captured["prompt"]


def test_empty_sections_contribute_no_prompt_block(db_session, monkeypatch):
    """Blank canvas placeholders are stored but must not leak an empty heading into the prompt."""
    tenant = _create_tenant(db_session)
    template = _template(
        sections=[
            {"label": "Persona", "content": "You are a helpful host.", "id": "sec-1", "order": 0},
            {"label": "PLACEHOLDER-LABEL-ONLY", "content": "", "id": "sec-blank", "order": 1},
            {"label": "Tone", "content": "Be warm and concise.", "id": "sec-2", "order": 2},
        ]
    )
    captured = _capture_gemini_call(monkeypatch)

    ai_reply_service.build_prompt_and_generate(
        db_session, tenant=tenant, template=template, channel="email", rough_draft="Check-in is at 3pm."
    )

    assert "PLACEHOLDER-LABEL-ONLY" not in captured["prompt"]
    assert captured["prompt"].index("You are a helpful host.") < captured["prompt"].index("Be warm and concise.")


def test_no_rough_draft_sends_empty_instruction_block(db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    template = _template()
    captured = _capture_gemini_call(monkeypatch)

    ai_reply_service.build_prompt_and_generate(db_session, tenant=tenant, template=template, channel="whatsapp", rough_draft=None)

    assert "Your Instruction" not in captured["prompt"]

    captured2 = _capture_gemini_call(monkeypatch)
    ai_reply_service.build_prompt_and_generate(db_session, tenant=tenant, template=template, channel="whatsapp", rough_draft="   ")
    assert "Your Instruction" not in captured2["prompt"]


def test_beds24_and_payments_blocks_only_appear_when_checked(db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    db_session.add(Finance(tenant_id=tenant.id, type="charge", amount=100, currency="EUR", description="City tax"))
    db_session.add(Finance(tenant_id=tenant.id, type="payment", amount=100, currency="EUR", description="Deposit"))
    db_session.commit()

    captured = _capture_gemini_call(monkeypatch)
    template_off = _template(include_beds24=False, include_payments=False)
    ai_reply_service.build_prompt_and_generate(db_session, tenant=tenant, template=template_off, channel="email", rough_draft="hi")
    assert "Beds24" not in captured["prompt"]
    assert "Payments & Charges" not in captured["prompt"]

    template_on = _template(include_beds24=True, include_payments=True)
    ai_reply_service.build_prompt_and_generate(db_session, tenant=tenant, template=template_on, channel="email", rough_draft="hi")
    assert "Booking Information (Beds24)" in captured["prompt"]
    assert tenant.booking_id in captured["prompt"]
    assert "Payments & Charges" in captured["prompt"]
    assert "City tax" in captured["prompt"]


def test_beds24_context_includes_contact_details(db_session, monkeypatch):
    tenant = _create_tenant(db_session, email="guest@example.com", phone="+31600000000", mobile="+31611111111")
    captured = _capture_gemini_call(monkeypatch)
    template = _template(include_beds24=True)

    ai_reply_service.build_prompt_and_generate(db_session, tenant=tenant, template=template, channel="email", rough_draft="hi")

    prompt = captured["prompt"]
    assert f"Guest name: {tenant.name}" in prompt
    assert "Email: guest@example.com" in prompt
    assert "Phone: +31600000000" in prompt
    assert "Mobile: +31611111111" in prompt


def test_notes_block_only_appears_when_checked(db_session, monkeypatch):
    tenant = _create_tenant(db_session, notes="VIP guest, prefers late checkout.")

    captured = _capture_gemini_call(monkeypatch)
    template_off = _template(include_notes=False)
    ai_reply_service.build_prompt_and_generate(db_session, tenant=tenant, template=template_off, channel="email", rough_draft="hi")
    assert "Internal Notes" not in captured["prompt"]

    template_on = _template(include_notes=True)
    ai_reply_service.build_prompt_and_generate(db_session, tenant=tenant, template=template_on, channel="email", rough_draft="hi")
    assert "Internal Notes" in captured["prompt"]
    assert "VIP guest, prefers late checkout." in captured["prompt"]


def test_history_is_channel_wide_not_thread_scoped(db_session, monkeypatch):
    tenant = _create_tenant(db_session)

    # Two separate email threads for the same tenant - history should span both, not just one.
    thread_a = Conversation(provider="gmail", provider_thread_id="thread-a", subject="Thread A")
    thread_b = Conversation(provider="gmail", provider_thread_id="thread-b", subject="Thread B")
    db_session.add_all([thread_a, thread_b])
    db_session.commit()
    db_session.add_all(
        [
            TenantConversationLink(tenant_id=tenant.id, conversation_id=thread_a.id),
            TenantConversationLink(tenant_id=tenant.id, conversation_id=thread_b.id),
        ]
    )
    now = datetime.now(timezone.utc)
    db_session.add_all(
        [
            ConversationMessage(
                conversation_id=thread_a.id,
                provider="gmail",
                provider_message_id="msg-a1",
                direction="inbound",
                body="Message from thread A",
                sent_at=now - timedelta(days=2),
            ),
            ConversationMessage(
                conversation_id=thread_b.id,
                provider="gmail",
                provider_message_id="msg-b1",
                direction="inbound",
                body="Message from thread B",
                sent_at=now - timedelta(days=1),
            ),
        ]
    )
    db_session.commit()

    captured = _capture_gemini_call(monkeypatch)
    template = _template(include_history=True, history_message_limit=10)
    ai_reply_service.build_prompt_and_generate(db_session, tenant=tenant, template=template, channel="email", rough_draft="hi")

    assert "Message from thread A" in captured["prompt"]
    assert "Message from thread B" in captured["prompt"]


def test_history_respects_message_limit(db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    now = datetime.now(timezone.utc)
    for index in range(5):
        db_session.add(
            Communication(
                tenant_id=tenant.id,
                channel="whatsapp",
                direction="inbound",
                message=f"whatsapp message {index}",
                created_at=now - timedelta(minutes=5 - index),
            )
        )
    db_session.commit()

    captured = _capture_gemini_call(monkeypatch)
    template = _template(include_history=True, history_message_limit=2)
    ai_reply_service.build_prompt_and_generate(db_session, tenant=tenant, template=template, channel="whatsapp", rough_draft="hi")

    # Only the 2 most recent WhatsApp messages.
    assert "whatsapp message 3" in captured["prompt"]
    assert "whatsapp message 4" in captured["prompt"]
    assert "whatsapp message 0" not in captured["prompt"]


def _seed_cross_channel_history(db_session, tenant, now):
    """Two emails and two WhatsApps interleaved: wa-old, email-old, wa-new, email-new."""
    thread = Conversation(
        provider="gmail",
        provider_account_id=1,
        provider_thread_id="thread-mixed",
        subject="Booking question",
    )
    db_session.add(thread)
    db_session.commit()
    db_session.refresh(thread)
    db_session.add(TenantConversationLink(tenant_id=tenant.id, conversation_id=thread.id))
    db_session.add_all(
        [
            ConversationMessage(
                conversation_id=thread.id,
                provider="gmail",
                provider_message_id="mixed-e1",
                direction="inbound",
                subject="Booking question",
                body="email body old",
                sent_at=now - timedelta(minutes=30),
            ),
            ConversationMessage(
                conversation_id=thread.id,
                provider="gmail",
                provider_message_id="mixed-e2",
                direction="outbound",
                subject="Re: Booking question",
                body="email body new",
                sent_at=now - timedelta(minutes=10),
            ),
        ]
    )
    db_session.add_all(
        [
            Communication(
                tenant_id=tenant.id,
                channel="whatsapp",
                direction="inbound",
                message="whatsapp body old",
                created_at=now - timedelta(minutes=40),
            ),
            Communication(
                tenant_id=tenant.id,
                channel="whatsapp",
                direction="outbound",
                message="whatsapp body new",
                created_at=now - timedelta(minutes=20),
            ),
        ]
    )
    db_session.commit()


def test_history_merges_email_and_whatsapp_for_an_email_draft(db_session, monkeypatch):
    # Regression: the history block used to load only the drafted channel, so an email reply was
    # generated with zero awareness of anything the guest said over WhatsApp.
    tenant = _create_tenant(db_session)
    _seed_cross_channel_history(db_session, tenant, datetime.now(timezone.utc))

    captured = _capture_gemini_call(monkeypatch)
    template = _template(include_history=True, history_message_limit=20)
    ai_reply_service.build_prompt_and_generate(db_session, tenant=tenant, template=template, channel="email", rough_draft="hi")

    prompt = captured["prompt"]
    for body in ("email body old", "email body new", "whatsapp body old", "whatsapp body new"):
        assert body in prompt


def test_history_merges_email_and_whatsapp_for_a_whatsapp_draft(db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    _seed_cross_channel_history(db_session, tenant, datetime.now(timezone.utc))

    captured = _capture_gemini_call(monkeypatch)
    template = _template(include_history=True, history_message_limit=20)
    ai_reply_service.build_prompt_and_generate(db_session, tenant=tenant, template=template, channel="whatsapp", rough_draft="hi")

    prompt = captured["prompt"]
    for body in ("email body old", "email body new", "whatsapp body old", "whatsapp body new"):
        assert body in prompt


def test_history_is_chronological_across_channels_and_tags_each_line(db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    _seed_cross_channel_history(db_session, tenant, datetime.now(timezone.utc))

    captured = _capture_gemini_call(monkeypatch)
    template = _template(include_history=True, history_message_limit=20)
    ai_reply_service.build_prompt_and_generate(db_session, tenant=tenant, template=template, channel="email", rough_draft="hi")

    prompt = captured["prompt"]
    order = [prompt.index(body) for body in ("whatsapp body old", "email body old", "whatsapp body new", "email body new")]
    assert order == sorted(order)
    assert "[WHATSAPP inbound]" in prompt
    assert "[EMAIL inbound]" in prompt
    # Email lines carry their subject so the model can tell which thread a message belongs to.
    assert "Re: Booking question" in prompt


def test_history_limit_applies_to_the_combined_cross_channel_stream(db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    now = datetime.now(timezone.utc)
    _seed_cross_channel_history(db_session, tenant, now)

    captured = _capture_gemini_call(monkeypatch)
    template = _template(include_history=True, history_message_limit=2)
    ai_reply_service.build_prompt_and_generate(db_session, tenant=tenant, template=template, channel="email", rough_draft="hi")

    # The 2 most recent messages overall, regardless of channel - not 2 per channel.
    prompt = captured["prompt"]
    assert "whatsapp body new" in prompt
    assert "email body new" in prompt
    assert "whatsapp body old" not in prompt
    assert "email body old" not in prompt


def test_history_excludes_whatsapp_chats_hidden_from_the_tenant_timeline(db_session, monkeypatch):
    # The manual chat link is authoritative: a stray message routed to this tenant under a
    # different chat on the same account is hidden in the UI and must be hidden from the model too.
    tenant = _create_tenant(db_session)
    now = datetime.now(timezone.utc)
    db_session.add(
        TenantChannelEndpoint(
            tenant_id=tenant.id,
            channel_type="whatsapp",
            provider="whatsapp_web",
            external_account_id="acct-1",
            external_chat_namespace="351900000000@c.us",
            is_active=True,
        )
    )
    db_session.add_all(
        [
            Communication(
                tenant_id=tenant.id,
                channel="whatsapp",
                direction="inbound",
                message="linked chat message",
                external_account_id="acct-1",
                whatsapp_chat_id="351900000000@c.us",
                created_at=now - timedelta(minutes=5),
            ),
            Communication(
                tenant_id=tenant.id,
                channel="whatsapp",
                direction="inbound",
                message="stray chat message",
                external_account_id="acct-1",
                whatsapp_chat_id="351911111111@c.us",
                created_at=now - timedelta(minutes=4),
            ),
        ]
    )
    db_session.commit()

    captured = _capture_gemini_call(monkeypatch)
    template = _template(include_history=True, history_message_limit=20)
    ai_reply_service.build_prompt_and_generate(db_session, tenant=tenant, template=template, channel="email", rough_draft="hi")

    assert "linked chat message" in captured["prompt"]
    assert "stray chat message" not in captured["prompt"]


def test_guidelines_block_appears_first_when_present(db_session, monkeypatch):
    tenant = _create_tenant(db_session, notes="Some notes.")
    template = _template(
        guidelines="This template is for late check-in requests.",
        sections=[{"label": "Persona", "content": "You are a helpful host."}],
        include_history=True,
        history_message_limit=10,
        include_beds24=True,
        include_notes=True,
    )
    captured = _capture_gemini_call(monkeypatch)

    ai_reply_service.build_prompt_and_generate(db_session, tenant=tenant, template=template, channel="email", rough_draft="hi")

    prompt = captured["prompt"]
    assert "This template is for late check-in requests." in prompt
    assert prompt.index("This template is for late check-in requests.") < prompt.index("Persona")


def test_fixed_block_order_guidelines_sections_history_beds24_instruction(db_session, monkeypatch):
    tenant = _create_tenant(db_session, notes="Prefers late checkout.")
    now = datetime.now(timezone.utc)
    db_session.add(
        Communication(
            tenant_id=tenant.id,
            channel="whatsapp",
            direction="inbound",
            message="a prior whatsapp message",
            created_at=now,
        )
    )
    db_session.commit()

    template = _template(
        guidelines="Guideline text goes first.",
        sections=[{"label": "Persona", "content": "Section text goes second."}],
        include_history=True,
        history_message_limit=10,
        include_beds24=True,
        include_notes=True,
    )
    captured = _capture_gemini_call(monkeypatch)

    ai_reply_service.build_prompt_and_generate(
        db_session, tenant=tenant, template=template, channel="whatsapp", rough_draft="Typed reply text goes last."
    )

    prompt = captured["prompt"]
    positions = [
        prompt.index("Guideline text goes first."),
        prompt.index("Section text goes second."),
        prompt.index("a prior whatsapp message"),
        prompt.index("Booking Information (Beds24)"),
        prompt.index("Typed reply text goes last."),
    ]
    assert positions == sorted(positions)


def test_group_headers_are_numbered_in_the_payload(db_session, monkeypatch):
    tenant = _create_tenant(db_session, notes="Prefers late checkout.")
    template = _template(
        guidelines="Follow the numbering below.",
        sections=[{"label": "Persona", "content": "You are a helpful host."}],
        include_history=True,
        history_message_limit=10,
        include_beds24=True,
        include_payments=True,
        include_notes=True,
    )
    captured = _capture_gemini_call(monkeypatch)

    ai_reply_service.build_prompt_and_generate(
        db_session, tenant=tenant, template=template, channel="email", rough_draft="Typed reply."
    )

    prompt = captured["prompt"]
    assert "0. Goal & Guidelines" in prompt
    assert "1. Template Text" in prompt
    assert "2. Message History" in prompt
    assert "3. Beds24 Info" in prompt
    assert "4. Your Instruction" in prompt
    # Sub-headers stay nested under their numbered group.
    assert "## Booking Information (Beds24)" in prompt
    assert "## Payments & Charges" in prompt
    assert "## Internal Notes" in prompt


def test_placeholders_are_resolved_in_guidelines_and_sections(db_session, monkeypatch):
    tenant = _create_tenant(db_session, first_name="Jamie")
    template = _template(
        guidelines="Write to {{first_name}}.",
        sections=[{"label": "Persona", "content": "Their room is {{room_name}}."}],
    )
    captured = _capture_gemini_call(monkeypatch)

    ai_reply_service.build_prompt_and_generate(db_session, tenant=tenant, template=template, channel="email", rough_draft="hi")

    assert "Write to Jamie." in captured["prompt"]
    assert "Their room is Studio 1." in captured["prompt"]


def test_booking_status_placeholder_is_resolved(db_session, monkeypatch):
    tenant = _create_tenant(db_session, booking_status="confirmed")
    template = _template(guidelines="Current status: {{booking_status}}.")
    captured = _capture_gemini_call(monkeypatch)

    ai_reply_service.build_prompt_and_generate(db_session, tenant=tenant, template=template, channel="email", rough_draft="hi")

    assert "Current status: confirmed." in captured["prompt"]


def test_default_labels_match_the_prompt_blocks_registry(db_session, monkeypatch):
    """Regression: assemble_prompt's numbered labels come from ai_prompt_blocks now, not literals."""
    from app.services import ai_prompt_blocks

    tenant = _create_tenant(db_session)
    template = _template(include_history=True, history_message_limit=5, include_beds24=True)
    captured = _capture_gemini_call(monkeypatch)

    ai_reply_service.build_prompt_and_generate(
        db_session, tenant=tenant, template=template, channel="email", rough_draft="hi"
    )

    defaults = ai_prompt_blocks.DEFAULTS_BY_ROLE["drafter"]
    assert defaults["sections"] in captured["prompt"]
    assert defaults["history"] in captured["prompt"]
    assert defaults["beds24"] in captured["prompt"]
    assert defaults["user_instruction"] in captured["prompt"]


def test_custom_blocks_override_the_drafter_labels(db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    template = _template()
    captured = _capture_gemini_call(monkeypatch)

    from app.services import ai_prompt_blocks

    blocks = dict(ai_prompt_blocks.DEFAULTS_BY_ROLE["drafter"])
    blocks["sections"] = "Custom Section Heading"

    ai_reply_service.build_prompt_and_generate(
        db_session, tenant=tenant, template=template, channel="email", rough_draft="hi", blocks=blocks
    )

    assert "Custom Section Heading" in captured["prompt"]
    assert "1. Template Text" not in captured["prompt"]


def test_blank_block_omits_the_label_but_keeps_the_content(db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    template = _template()
    captured = _capture_gemini_call(monkeypatch)

    from app.services import ai_prompt_blocks

    blocks = dict(ai_prompt_blocks.DEFAULTS_BY_ROLE["drafter"])
    blocks["sections"] = ""

    ai_reply_service.build_prompt_and_generate(
        db_session, tenant=tenant, template=template, channel="email", rough_draft="hi", blocks=blocks
    )

    assert "1. Template Text" not in captured["prompt"]
    assert "You are a helpful host." in captured["prompt"]


def test_agent_instructions_use_the_instructions_header_block(db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    template = _template()
    captured = _capture_gemini_call(monkeypatch)

    from app.services import ai_prompt_blocks

    blocks = dict(ai_prompt_blocks.DEFAULTS_BY_ROLE["drafter"])
    blocks["instructions_header"] = "## Standing Rules"

    ai_reply_service.build_prompt_and_generate(
        db_session,
        tenant=tenant,
        template=template,
        channel="email",
        rough_draft="hi",
        blocks=blocks,
        agent_instructions="Never mention refunds.",
    )

    assert "## Standing Rules\nNever mention refunds." in captured["prompt"]


def test_history_heading_substitutes_limit_and_scope(db_session, monkeypatch):
    tenant = _create_tenant(db_session)
    template = _template(include_history=True, history_message_limit=7)
    captured = _capture_gemini_call(monkeypatch)

    ai_reply_service.build_prompt_and_generate(
        db_session, tenant=tenant, template=template, channel="email", rough_draft="hi"
    )

    assert "## Conversation History (last 7 messages across email and WhatsApp)" in captured["prompt"]


def test_omitting_blocks_argument_falls_back_to_built_in_defaults(db_session, monkeypatch):
    """No blocks passed at all -> identical output to before prompt blocks existed."""
    tenant = _create_tenant(db_session)
    template = _template(include_beds24=True)
    captured = _capture_gemini_call(monkeypatch)

    ai_reply_service.build_prompt_and_generate(
        db_session, tenant=tenant, template=template, channel="email", rough_draft="hi"
    )

    assert "0. Goal & Guidelines" not in captured["prompt"]  # guidelines blank for this template
    assert "1. Template Text" in captured["prompt"]
    assert "## Booking Information (Beds24)" in captured["prompt"]
