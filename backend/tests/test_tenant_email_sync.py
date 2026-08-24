from app.models.tenant import Tenant
from app.models.tenant_email_address import TenantEmailAddress
from app.services.tenant_email_sync import sync_tenant_email_addresses_from_beds24


def create_tenant(db_session, name="Tenant A", booking_id="B-sync-1"):
    tenant = Tenant(name=name, booking_id=booking_id)
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


def test_sync_creates_link_for_new_beds24_info_item(db_session):
    tenant = create_tenant(db_session, booking_id="B-sync-create")
    info_items = [{"id": 111, "code": "CRM_EMAIL", "text": "guest@example.com"}]

    newly_linked = sync_tenant_email_addresses_from_beds24(db_session, tenant, info_items)
    db_session.commit()

    links = db_session.query(TenantEmailAddress).filter(TenantEmailAddress.tenant_id == tenant.id).all()
    assert len(links) == 1
    assert links[0].email == "guest@example.com"
    assert links[0].beds24_info_item_id == "111"
    assert links[0].beds24_sync_status == "synced"
    assert links[0].source == "beds24"
    assert links[0].is_active is True
    assert newly_linked == ["guest@example.com"]


def test_sync_does_not_report_an_already_linked_email_as_newly_linked(db_session):
    """Regression test: a repeat sync of an address that's already linked (only backfilling its
    beds24_info_item_id, if that was missing) must not be reported as newly linked - callers use
    this return value to decide whether to kick off a fresh Gmail history search, and re-searching
    on every sync of an address the CRM has already searched would be wasted work.
    """
    tenant = create_tenant(db_session, booking_id="B-sync-not-new")
    info_items = [{"id": 999, "code": "CRM_EMAIL", "text": "guest@example.com"}]

    first_pass = sync_tenant_email_addresses_from_beds24(db_session, tenant, info_items)
    db_session.commit()
    assert first_pass == ["guest@example.com"]

    second_pass = sync_tenant_email_addresses_from_beds24(db_session, tenant, info_items)
    db_session.commit()
    assert second_pass == []


def test_sync_creates_link_even_when_already_linked_to_another_tenant(db_session):
    tenant_a = create_tenant(db_session, name="Tenant A", booking_id="B-sync-conflict-a")
    tenant_b = create_tenant(db_session, name="Tenant B", booking_id="B-sync-conflict-b")
    db_session.add(
        TenantEmailAddress(tenant_id=tenant_a.id, email="shared@example.com", is_active=True, beds24_info_item_id="1")
    )
    db_session.commit()

    info_items = [{"id": 222, "code": "CRM_EMAIL", "text": "shared@example.com"}]
    sync_tenant_email_addresses_from_beds24(db_session, tenant_b, info_items)
    db_session.commit()

    b_links = db_session.query(TenantEmailAddress).filter(TenantEmailAddress.tenant_id == tenant_b.id).all()
    assert len(b_links) == 1
    assert b_links[0].email == "shared@example.com"

    a_links = db_session.query(TenantEmailAddress).filter(TenantEmailAddress.tenant_id == tenant_a.id).all()
    assert len(a_links) == 1
    assert a_links[0].is_active is True


def test_sync_backfills_missing_info_item_id(db_session):
    tenant = create_tenant(db_session, booking_id="B-sync-backfill")
    link = TenantEmailAddress(tenant_id=tenant.id, email="guest@example.com", is_active=True, beds24_sync_status="failed")
    db_session.add(link)
    db_session.commit()

    info_items = [{"id": 333, "code": "CRM_EMAIL", "text": "guest@example.com"}]
    sync_tenant_email_addresses_from_beds24(db_session, tenant, info_items)
    db_session.commit()
    db_session.refresh(link)

    assert link.beds24_info_item_id == "333"
    assert link.beds24_sync_status == "synced"
    assert link.is_active is True


def test_sync_unlinks_when_confirmed_info_item_removed_from_beds24(db_session):
    tenant = create_tenant(db_session, booking_id="B-sync-unlink")
    link = TenantEmailAddress(tenant_id=tenant.id, email="guest@example.com", is_active=True, beds24_info_item_id="444", beds24_sync_status="synced")
    db_session.add(link)
    db_session.commit()

    sync_tenant_email_addresses_from_beds24(db_session, tenant, [])
    db_session.commit()
    db_session.refresh(link)

    assert link.is_active is False
    assert link.unlinked_at is not None


def test_sync_does_not_unlink_unconfirmed_pending_link(db_session):
    """A link that was created manually but never got a confirmed beds24_info_item_id
    (e.g. the Beds24 write is still pending/failed) must not be treated as "removed from
    Beds24" just because it's absent from the current info items -- it was never confirmed
    to be there in the first place."""
    tenant = create_tenant(db_session, booking_id="B-sync-pending")
    link = TenantEmailAddress(tenant_id=tenant.id, email="guest@example.com", is_active=True, beds24_sync_status="failed")
    db_session.add(link)
    db_session.commit()

    sync_tenant_email_addresses_from_beds24(db_session, tenant, [])
    db_session.commit()
    db_session.refresh(link)

    assert link.is_active is True
