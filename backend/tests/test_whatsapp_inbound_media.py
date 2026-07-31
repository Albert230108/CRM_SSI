import base64

import pytest

from app.models.communication import Communication
from app.models.communication_attachment import CommunicationAttachment, CommunicationAttachmentLink
from app.models.tenant import Tenant
from app.models.tenant_channel_endpoint import TenantChannelEndpoint


@pytest.fixture(autouse=True)
def attachments_root(tmp_path, monkeypatch):
    monkeypatch.setenv("ATTACHMENTS_ROOT", str(tmp_path))
    yield tmp_path


def create_tenant(db_session, booking_id):
    tenant = Tenant(name="Tenant Media", booking_id=booking_id, phone="+31600000000")
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


def create_linked_endpoint(db_session, tenant_id, chat="31612345678@c.us"):
    endpoint = TenantChannelEndpoint(
        tenant_id=tenant_id,
        channel_type="whatsapp",
        provider="whatsapp-service",
        external_account_id="edi-crm-whatsapp",
        external_chat_namespace=chat,
        is_active=True,
    )
    db_session.add(endpoint)
    db_session.commit()
    return endpoint


def inbound_payload(message_id, *, message="Look at this", attachments=None):
    payload = {
        "direction": "inbound",
        "provider": "whatsapp-service",
        "external_account_id": "edi-crm-whatsapp",
        "sender": "+31612345678",
        "sender_normalized": "31612345678",
        "whatsapp_chat_id": "31612345678@c.us",
        "whatsapp_message_id": message_id,
        "timestamp": 1710000000,
        "message": message,
    }
    if attachments is not None:
        payload["attachments"] = attachments
    return payload


def test_inbound_media_is_stored_and_linked(client, db_session, attachments_root):
    tenant = create_tenant(db_session, "B-media-1")
    create_linked_endpoint(db_session, tenant.id)

    response = client.post(
        "/webhooks/whatsapp",
        json=inbound_payload(
            "msg-media-1",
            attachments=[
                {
                    "filename": "photo.png",
                    "mime_type": "image/png",
                    "size_bytes": 5,
                    "data_base64": base64.b64encode(b"hello").decode("ascii"),
                }
            ],
        ),
    )

    assert response.status_code == 200
    assert response.json()["tenant_id"] == tenant.id

    communication = (
        db_session.query(Communication).filter(Communication.provider_message_id == "msg-media-1").one()
    )
    attachment = db_session.query(CommunicationAttachment).filter_by(tenant_id=tenant.id).one()
    assert attachment.filename == "photo.png"
    assert attachment.mime_type == "image/png"
    assert attachment.origin == "whatsapp_inbound"
    assert attachment.size_bytes == 5
    assert (attachments_root / attachment.storage_key).read_bytes() == b"hello"

    link = db_session.query(CommunicationAttachmentLink).filter_by(attachment_id=attachment.id).one()
    assert link.communication_id == communication.id


def test_inbound_message_without_attachments_is_unaffected(client, db_session):
    tenant = create_tenant(db_session, "B-media-2")
    create_linked_endpoint(db_session, tenant.id)

    response = client.post("/webhooks/whatsapp", json=inbound_payload("msg-media-2"))

    assert response.status_code == 200
    assert db_session.query(Communication).filter_by(provider_message_id="msg-media-2").count() == 1
    assert db_session.query(CommunicationAttachment).filter_by(tenant_id=tenant.id).count() == 0


def test_empty_attachments_list_is_a_no_op(client, db_session):
    tenant = create_tenant(db_session, "B-media-3")
    create_linked_endpoint(db_session, tenant.id)

    response = client.post("/webhooks/whatsapp", json=inbound_payload("msg-media-3", attachments=[]))

    assert response.status_code == 200
    assert db_session.query(CommunicationAttachment).filter_by(tenant_id=tenant.id).count() == 0


def test_oversize_attachment_is_skipped_without_failing_the_webhook(client, db_session, monkeypatch):
    monkeypatch.setenv("ATTACHMENT_MAX_FILE_BYTES", "3")
    tenant = create_tenant(db_session, "B-media-4")
    create_linked_endpoint(db_session, tenant.id)

    response = client.post(
        "/webhooks/whatsapp",
        json=inbound_payload(
            "msg-media-4",
            attachments=[
                {
                    "filename": "big.bin",
                    "mime_type": "application/octet-stream",
                    "data_base64": base64.b64encode(b"way too many bytes").decode("ascii"),
                }
            ],
        ),
    )

    # The webhook must still succeed, or the bridge retries and duplicates the message.
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert db_session.query(Communication).filter_by(provider_message_id="msg-media-4").count() == 1
    assert db_session.query(CommunicationAttachment).filter_by(tenant_id=tenant.id).count() == 0


def test_corrupt_base64_is_skipped_without_failing_the_webhook(client, db_session):
    tenant = create_tenant(db_session, "B-media-5")
    create_linked_endpoint(db_session, tenant.id)

    response = client.post(
        "/webhooks/whatsapp",
        json=inbound_payload(
            "msg-media-5",
            attachments=[{"filename": "bad.bin", "mime_type": None, "data_base64": "!!!not base64!!!"}],
        ),
    )

    assert response.status_code == 200
    assert db_session.query(Communication).filter_by(provider_message_id="msg-media-5").count() == 1
    assert db_session.query(CommunicationAttachment).filter_by(tenant_id=tenant.id).count() == 0


def test_attachment_without_filename_gets_a_generated_name(client, db_session):
    tenant = create_tenant(db_session, "B-media-6")
    create_linked_endpoint(db_session, tenant.id)

    response = client.post(
        "/webhooks/whatsapp",
        json=inbound_payload(
            "msg-media-6",
            attachments=[
                {
                    "filename": None,
                    "mime_type": "audio/ogg",
                    "data_base64": base64.b64encode(b"voice").decode("ascii"),
                }
            ],
        ),
    )

    assert response.status_code == 200
    attachment = db_session.query(CommunicationAttachment).filter_by(tenant_id=tenant.id).one()
    assert attachment.filename == "whatsapp-media-0"
