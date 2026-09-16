"""Bulk executor-mode assignment + the per-tenant bulk-action lock.

A locked tenant (Tenant.bulk_action_locked) must be skipped by every AI-settings bulk action, and
each bulk result reports how many locked tenants were skipped. The lock endpoints themselves are
not lock-gated (you must be able to unlock). The tenant list exposes the flag and can filter on it.
"""

from app.models.tenant import Tenant


def _create_tenant(db_session, booking_id, **overrides):
    defaults = dict(
        name="Lock Tenant", first_name="Jane", last_name="Doe",
        check_in="2026-08-01", check_out="2026-08-05", room_name="Studio 1",
    )
    defaults.update(overrides)
    tenant = Tenant(booking_id=booking_id, **defaults)
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


def _executor_mode(non_admin_client, tenant_id):
    return non_admin_client.get(f"/api/tenants/{tenant_id}/ai-settings").json()["executor_mode"]


def test_bulk_executor_mode_sets_and_resets(non_admin_client, db_session):
    a = _create_tenant(db_session, "B-exec-1", name="Exec A")
    b = _create_tenant(db_session, "B-exec-2", name="Exec B")

    response = non_admin_client.post(
        "/api/tenant-ai-settings/bulk-executor-mode",
        json={"tenant_ids": [a.id, b.id], "executor_mode": "autonomous"},
    )
    assert response.status_code == 200
    assert response.json() == {"tenants_affected": 2, "skipped_locked": 0}
    assert _executor_mode(non_admin_client, a.id) == "autonomous"
    assert _executor_mode(non_admin_client, b.id) == "autonomous"

    # None resets to "use the global default".
    reset = non_admin_client.post(
        "/api/tenant-ai-settings/bulk-executor-mode",
        json={"tenant_ids": [a.id], "executor_mode": None},
    )
    assert reset.status_code == 200
    assert _executor_mode(non_admin_client, a.id) is None


def test_bulk_executor_mode_skips_locked_tenants(non_admin_client, db_session):
    free = _create_tenant(db_session, "B-exec-free", name="Free")
    locked = _create_tenant(db_session, "B-exec-locked", name="Locked", bulk_action_locked=True)

    response = non_admin_client.post(
        "/api/tenant-ai-settings/bulk-executor-mode",
        json={"tenant_ids": [free.id, locked.id], "executor_mode": "autonomous"},
    )
    assert response.status_code == 200
    assert response.json() == {"tenants_affected": 1, "skipped_locked": 1}
    assert _executor_mode(non_admin_client, free.id) == "autonomous"
    # The locked tenant was left untouched (still on the global default).
    assert _executor_mode(non_admin_client, locked.id) is None


def test_existing_bulk_planner_mode_skips_locked_tenants(non_admin_client, db_session):
    """Regression: the lock must protect ALL AI-settings bulk actions, not just executor mode."""
    free = _create_tenant(db_session, "B-plan-free", name="Plan Free")
    locked = _create_tenant(db_session, "B-plan-locked", name="Plan Locked", bulk_action_locked=True)

    response = non_admin_client.post(
        "/api/tenant-ai-settings/bulk-planner-mode",
        json={"tenant_ids": [free.id, locked.id], "planner_mode": "auto-draft"},
    )
    assert response.status_code == 200
    assert response.json()["tenants_affected"] == 1
    assert response.json()["skipped_locked"] == 1
    assert non_admin_client.get(f"/api/tenants/{free.id}/ai-settings").json()["planner_mode"] == "auto-draft"
    assert non_admin_client.get(f"/api/tenants/{locked.id}/ai-settings").json()["planner_mode"] == "off"


def test_single_lock_toggle_and_read_exposure(non_admin_client, db_session):
    tenant = _create_tenant(db_session, "B-lock-single", name="Single")

    # TenantRead defaults the flag to false.
    listed = {t["id"]: t for t in non_admin_client.get("/api/tenants").json()}
    assert listed[tenant.id]["bulk_action_locked"] is False

    response = non_admin_client.patch(f"/api/tenants/{tenant.id}/bulk-action-lock", json={"locked": True})
    assert response.status_code == 200
    assert response.json() == {"bulk_action_locked": True}
    db_session.refresh(tenant)
    assert tenant.bulk_action_locked is True


def test_bulk_lock_unlock_is_not_self_skipped(non_admin_client, db_session):
    a = _create_tenant(db_session, "B-blk-lock-1", name="Blk A")
    b = _create_tenant(db_session, "B-blk-lock-2", name="Blk B", bulk_action_locked=True)

    # Bulk lock affects everyone, including an already-locked tenant (idempotent), and bulk unlock
    # must be able to clear the lock - otherwise a locked tenant could never be freed.
    lock = non_admin_client.post("/api/tenants/bulk-action-lock", json={"tenant_ids": [a.id, b.id], "locked": True})
    assert lock.status_code == 200
    assert lock.json()["tenants_affected"] == 2
    db_session.refresh(a)
    assert a.bulk_action_locked is True

    unlock = non_admin_client.post("/api/tenants/bulk-action-lock", json={"tenant_ids": [a.id, b.id], "locked": False})
    assert unlock.status_code == 200
    assert unlock.json()["tenants_affected"] == 2
    for tenant in (a, b):
        db_session.refresh(tenant)
        assert tenant.bulk_action_locked is False


def test_list_locked_filter(non_admin_client, db_session):
    unlocked = _create_tenant(db_session, "B-filter-unlocked", name="Filter Unlocked")
    locked = _create_tenant(db_session, "B-filter-locked", name="Filter Locked", bulk_action_locked=True)

    locked_ids = {t["id"] for t in non_admin_client.get("/api/tenants?locked=true").json()}
    assert locked.id in locked_ids
    assert unlocked.id not in locked_ids

    unlocked_ids = {t["id"] for t in non_admin_client.get("/api/tenants?locked=false").json()}
    assert unlocked.id in unlocked_ids
    assert locked.id not in unlocked_ids
