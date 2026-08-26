from app.models.communication_attachment import CommunicationAttachment
from app.models.communication_reply_draft import CommunicationReplyDraft
from app.models.gmail_integration import Conversation
from app.models.tenant import Tenant
from app.models.tenant_channel_endpoint import TenantChannelEndpoint
from app.models.tenant_conversation_link import TenantConversationLink


def create_tenant(db_session, name, booking_id):
    tenant = Tenant(name=name, booking_id=booking_id)
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


def create_linked_thread(db_session, tenant_id, subject):
    conversation = Conversation(
        provider="gmail",
        provider_thread_id=f"thread-{tenant_id}-{subject}",
        tenant_id=tenant_id,
        subject=subject,
    )
    db_session.add(conversation)
    db_session.commit()
    db_session.refresh(conversation)
    db_session.add(TenantConversationLink(tenant_id=tenant_id, conversation_id=conversation.id))
    db_session.commit()
    return conversation


def create_whatsapp_endpoint(db_session, tenant_id, external_account_id, chat_namespace):
    endpoint = TenantChannelEndpoint(
        tenant_id=tenant_id,
        channel_type="whatsapp",
        provider="whatsapp-service",
        external_account_id=external_account_id,
        external_chat_namespace=chat_namespace,
        is_active=True,
    )
    db_session.add(endpoint)
    db_session.commit()
    db_session.refresh(endpoint)
    return endpoint


def create_attachment(db_session, tenant_id, filename, size_bytes, mime_type):
    attachment = CommunicationAttachment(
        tenant_id=tenant_id,
        storage_key=f"{tenant_id}/{filename}-{size_bytes}",
        filename=filename,
        mime_type=mime_type,
        size_bytes=size_bytes,
        sha256=f"sha-{tenant_id}-{filename}-{size_bytes}",
        origin="upload",
    )
    db_session.add(attachment)
    db_session.commit()
    db_session.refresh(attachment)
    return attachment


def test_draft_saved_for_one_tenant_is_not_visible_to_another(non_admin_client, db_session):
    """Regression: the reply box body used to be one global slot, so a draft written for one
    tenant's thread followed the user into the next tenant."""
    tenant_a = create_tenant(db_session, "Draft Tenant A", "RD-A")
    tenant_b = create_tenant(db_session, "Draft Tenant B", "RD-B")
    thread_a = create_linked_thread(db_session, tenant_a.id, "subject-a")
    create_linked_thread(db_session, tenant_b.id, "subject-b")

    saved = non_admin_client.put(
        f"/api/communications/tenants/{tenant_a.id}/reply-drafts",
        json={"channel": "email", "email_thread_id": thread_a.id, "subject": "Re: A", "body": "secret to A"},
    )
    assert saved.status_code == 200

    drafts_b = non_admin_client.get(f"/api/communications/tenants/{tenant_b.id}/reply-drafts")

    assert drafts_b.status_code == 200
    assert drafts_b.json() == []

    drafts_a = non_admin_client.get(f"/api/communications/tenants/{tenant_a.id}/reply-drafts")
    assert [d["body"] for d in drafts_a.json()] == ["secret to A"]


def test_two_threads_on_same_tenant_hold_independent_drafts(non_admin_client, db_session):
    tenant = create_tenant(db_session, "Draft Tenant C", "RD-C")
    thread_one = create_linked_thread(db_session, tenant.id, "subject-one")
    thread_two = create_linked_thread(db_session, tenant.id, "subject-two")

    non_admin_client.put(
        f"/api/communications/tenants/{tenant.id}/reply-drafts",
        json={"channel": "email", "email_thread_id": thread_one.id, "body": "draft one"},
    )
    non_admin_client.put(
        f"/api/communications/tenants/{tenant.id}/reply-drafts",
        json={"channel": "email", "email_thread_id": thread_two.id, "body": "draft two"},
    )

    by_thread = {d["email_thread_id"]: d["body"] for d in non_admin_client.get(
        f"/api/communications/tenants/{tenant.id}/reply-drafts"
    ).json()}

    assert by_thread == {thread_one.id: "draft one", thread_two.id: "draft two"}


def test_upsert_round_trips_subject_and_updates_in_place(non_admin_client, db_session):
    tenant = create_tenant(db_session, "Draft Tenant D", "RD-D")
    thread = create_linked_thread(db_session, tenant.id, "subject-d")

    first = non_admin_client.put(
        f"/api/communications/tenants/{tenant.id}/reply-drafts",
        json={"channel": "email", "email_thread_id": thread.id, "subject": "Re: hello", "body": "v1"},
    )
    second = non_admin_client.put(
        f"/api/communications/tenants/{tenant.id}/reply-drafts",
        json={"channel": "email", "email_thread_id": thread.id, "subject": "Re: hello", "body": "v2"},
    )

    assert first.json()["subject"] == "Re: hello"
    assert second.json()["body"] == "v2"
    assert second.json()["id"] == first.json()["id"]
    rows = db_session.query(CommunicationReplyDraft).filter(CommunicationReplyDraft.tenant_id == tenant.id).all()
    assert len(rows) == 1


def test_blank_body_deletes_the_draft(non_admin_client, db_session):
    tenant = create_tenant(db_session, "Draft Tenant E", "RD-E")
    thread = create_linked_thread(db_session, tenant.id, "subject-e")
    non_admin_client.put(
        f"/api/communications/tenants/{tenant.id}/reply-drafts",
        json={"channel": "email", "email_thread_id": thread.id, "body": "something"},
    )

    cleared = non_admin_client.put(
        f"/api/communications/tenants/{tenant.id}/reply-drafts",
        json={"channel": "email", "email_thread_id": thread.id, "body": "   "},
    )

    assert cleared.status_code == 200
    assert cleared.json() is None
    assert non_admin_client.get(f"/api/communications/tenants/{tenant.id}/reply-drafts").json() == []


def test_attachment_only_draft_is_preserved_and_hydrated(non_admin_client, db_session):
    tenant = create_tenant(db_session, "Draft Tenant E2", "RD-E2")
    thread = create_linked_thread(db_session, tenant.id, "subject-e2")
    attachment = create_attachment(db_session, tenant.id, "contract.pdf", 1234, "application/pdf")

    saved = non_admin_client.put(
        f"/api/communications/tenants/{tenant.id}/reply-drafts",
        json={
            "channel": "email",
            "email_thread_id": thread.id,
            "body": "   ",
            "attachment_ids": [attachment.id],
        },
    )

    assert saved.status_code == 200
    body = saved.json()
    assert body["attachment_ids"] == [attachment.id]
    assert body["attachments"] == [
        {"id": attachment.id, "filename": "contract.pdf", "size_bytes": 1234, "mime_type": "application/pdf"}
    ]

    drafts = non_admin_client.get(f"/api/communications/tenants/{tenant.id}/reply-drafts")
    assert drafts.status_code == 200
    assert drafts.json()[0]["attachment_ids"] == [attachment.id]
    assert drafts.json()[0]["attachments"][0]["filename"] == "contract.pdf"


def test_delete_removes_draft_for_scope(non_admin_client, db_session):
    tenant = create_tenant(db_session, "Draft Tenant F", "RD-F")
    thread = create_linked_thread(db_session, tenant.id, "subject-f")
    non_admin_client.put(
        f"/api/communications/tenants/{tenant.id}/reply-drafts",
        json={"channel": "email", "email_thread_id": thread.id, "body": "about to send"},
    )

    response = non_admin_client.delete(
        f"/api/communications/tenants/{tenant.id}/reply-drafts",
        params={"channel": "email", "email_thread_id": thread.id},
    )

    assert response.status_code == 204
    assert non_admin_client.get(f"/api/communications/tenants/{tenant.id}/reply-drafts").json() == []


def test_email_draft_for_thread_of_another_tenant_is_rejected(non_admin_client, db_session):
    tenant_a = create_tenant(db_session, "Draft Tenant G", "RD-G")
    tenant_b = create_tenant(db_session, "Draft Tenant H", "RD-H")
    thread_b = create_linked_thread(db_session, tenant_b.id, "subject-h")

    response = non_admin_client.put(
        f"/api/communications/tenants/{tenant_a.id}/reply-drafts",
        json={"channel": "email", "email_thread_id": thread_b.id, "body": "wrong tenant"},
    )

    assert response.status_code == 404
    assert db_session.query(CommunicationReplyDraft).filter(CommunicationReplyDraft.tenant_id == tenant_a.id).count() == 0


def test_whatsapp_draft_for_endpoint_of_another_tenant_is_rejected(non_admin_client, db_session):
    tenant_a = create_tenant(db_session, "Draft Tenant I", "RD-I")
    tenant_b = create_tenant(db_session, "Draft Tenant J", "RD-J")
    endpoint_b = create_whatsapp_endpoint(db_session, tenant_b.id, "acct-j", "5511999@c.us")

    response = non_admin_client.put(
        f"/api/communications/tenants/{tenant_a.id}/reply-drafts",
        json={"channel": "whatsapp", "whatsapp_endpoint_id": endpoint_b.id, "body": "wrong tenant"},
    )

    assert response.status_code == 404


def test_whatsapp_drafts_are_independent_per_linked_chat(non_admin_client, db_session):
    """WhatsApp drafts key on the manual chat link, not on the timeline's volatile group_id,
    so two chats on the same account keep separate drafts."""
    tenant = create_tenant(db_session, "Draft Tenant K", "RD-K")
    chat_one = create_whatsapp_endpoint(db_session, tenant.id, "acct-k", "5511111@c.us")
    chat_two = create_whatsapp_endpoint(db_session, tenant.id, "acct-k", "5522222@c.us")

    non_admin_client.put(
        f"/api/communications/tenants/{tenant.id}/reply-drafts",
        json={"channel": "whatsapp", "whatsapp_endpoint_id": chat_one.id, "body": "for chat one"},
    )
    non_admin_client.put(
        f"/api/communications/tenants/{tenant.id}/reply-drafts",
        json={"channel": "whatsapp", "whatsapp_endpoint_id": chat_two.id, "body": "for chat two"},
    )

    by_endpoint = {d["whatsapp_endpoint_id"]: d["body"] for d in non_admin_client.get(
        f"/api/communications/tenants/{tenant.id}/reply-drafts"
    ).json()}

    assert by_endpoint == {chat_one.id: "for chat one", chat_two.id: "for chat two"}


def test_email_and_whatsapp_drafts_on_same_tenant_do_not_collide(non_admin_client, db_session):
    tenant = create_tenant(db_session, "Draft Tenant L", "RD-L")
    thread = create_linked_thread(db_session, tenant.id, "subject-l")
    endpoint = create_whatsapp_endpoint(db_session, tenant.id, "acct-l", "5533333@c.us")

    non_admin_client.put(
        f"/api/communications/tenants/{tenant.id}/reply-drafts",
        json={"channel": "email", "email_thread_id": thread.id, "body": "email body"},
    )
    non_admin_client.put(
        f"/api/communications/tenants/{tenant.id}/reply-drafts",
        json={"channel": "whatsapp", "whatsapp_endpoint_id": endpoint.id, "body": "whatsapp body"},
    )

    by_channel = {d["channel"]: d["body"] for d in non_admin_client.get(
        f"/api/communications/tenants/{tenant.id}/reply-drafts"
    ).json()}

    assert by_channel == {"email": "email body", "whatsapp": "whatsapp body"}


def test_invalid_attachment_ids_are_ignored(non_admin_client, db_session):
    tenant_a = create_tenant(db_session, "Draft Tenant L2", "RD-L2")
    tenant_b = create_tenant(db_session, "Draft Tenant L3", "RD-L3")
    thread = create_linked_thread(db_session, tenant_a.id, "subject-l2")
    own_attachment = create_attachment(db_session, tenant_a.id, "keep.pdf", 111, "application/pdf")
    foreign_attachment = create_attachment(db_session, tenant_b.id, "other.pdf", 222, "application/pdf")

    saved = non_admin_client.put(
        f"/api/communications/tenants/{tenant_a.id}/reply-drafts",
        json={
            "channel": "email",
            "email_thread_id": thread.id,
            "body": "draft",
            "attachment_ids": [own_attachment.id, foreign_attachment.id, 999999],
        },
    )

    assert saved.status_code == 200
    assert saved.json()["attachment_ids"] == [own_attachment.id]
    assert saved.json()["attachments"][0]["filename"] == "keep.pdf"


def test_reply_drafts_returns_404_for_missing_tenant(non_admin_client):
    assert non_admin_client.get("/api/communications/tenants/999999/reply-drafts").status_code == 404
    assert non_admin_client.put(
        "/api/communications/tenants/999999/reply-drafts",
        json={"channel": "email", "email_thread_id": 1, "body": "x"},
    ).status_code == 404


def test_unsupported_channel_is_rejected(non_admin_client, db_session):
    tenant = create_tenant(db_session, "Draft Tenant M", "RD-M")

    response = non_admin_client.put(
        f"/api/communications/tenants/{tenant.id}/reply-drafts",
        json={"channel": "sms", "email_thread_id": 1, "body": "x"},
    )

    assert response.status_code == 400
