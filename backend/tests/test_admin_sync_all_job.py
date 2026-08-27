"""
Regression tests for sync-all returning 504 Gateway Timeout.

A full sync-all run takes ~2 minutes (the Gmail phase alone dominates), but it used to await
all four phases inline before responding. nginx's proxy_read_timeout closed the connection at
60s, so the caller got a 504 even though the sync itself ran to completion. sync-all now starts
a background job and returns a job id immediately, so the response time no longer depends on
how long the work takes.
"""

import asyncio
import time

import pytest

from app.api import admin_sync
from app.models.tenant import Tenant
from app.services import background_jobs


@pytest.fixture(autouse=True)
def clear_job_registry():
    """The job registry is module-global, so leftovers would break the single-flight tests."""
    background_jobs._jobs.clear()
    yield
    background_jobs._jobs.clear()


@pytest.fixture()
def stub_phases(monkeypatch):
    """Replace the four sync phases with instrumented no-ops."""
    calls: dict[str, int] = {"beds24": 0, "email": 0, "whatsapp": 0}

    async def fake_beds24(db, changed_by_user_id=None, tenant_ids=None):
        calls["beds24"] += 1
        return 3

    async def fake_emails(db, tenant_ids=None, progress=None):
        calls["email"] += 1
        if progress is not None:
            progress(1, 1)
        return 5

    async def fake_whatsapp(db, tenant_ids=None):
        calls["whatsapp"] += 1
        return {"total_imported": 7, "synced_endpoints": 2, "results": [], "errors": []}

    monkeypatch.setattr(admin_sync, "_sync_beds24", fake_beds24)
    monkeypatch.setattr(admin_sync, "_sync_emails", fake_emails)
    monkeypatch.setattr(admin_sync, "_sync_whatsapp_linked_endpoints", fake_whatsapp)
    return calls


def poll_until_done(client, job_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/admin/sync-all/{job_id}").json()
        if job["status"] != "running":
            return job
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not finish within {timeout}s")


def test_sync_all_responds_immediately_without_running_phases(non_admin_client, monkeypatch):
    """The POST must return before the work happens - that is the whole point of the fix."""

    async def slow_beds24(db, changed_by_user_id=None, tenant_ids=None):
        await asyncio.sleep(30)
        return 0

    monkeypatch.setattr(admin_sync, "_sync_beds24", slow_beds24)

    begin = time.time()
    response = non_admin_client.post("/api/admin/sync-all", json={"tenant_ids": None})
    elapsed = time.time() - begin

    assert response.status_code == 202
    assert response.json()["job_id"]
    assert response.json()["status"] == "running"
    # Would have been ~30s (or a 504) under the old inline behaviour.
    assert elapsed < 5


def test_sync_all_job_completes_with_summary(non_admin_client, stub_phases):
    job_id = non_admin_client.post("/api/admin/sync-all", json={"tenant_ids": None}).json()["job_id"]

    job = poll_until_done(non_admin_client, job_id)

    assert job["status"] == "done"
    summary = job["result"]
    assert summary["bookings_updated"] == 3
    assert summary["emails_imported"] == 5
    assert summary["whatsapp_messages_imported"] == 7
    assert summary["whatsapp_endpoints_synced"] == 2
    assert summary["completed_at"] is not None
    assert summary["partial_failures"] == []
    assert stub_phases == {"beds24": 1, "email": 1, "whatsapp": 1}


def test_sync_all_reports_phase_progress(non_admin_client, stub_phases):
    job_id = non_admin_client.post("/api/admin/sync-all", json={"tenant_ids": None}).json()["job_id"]
    job = poll_until_done(non_admin_client, job_id)

    progress = job["progress"]
    assert progress["phases_total"] == 4
    # Last phase reached is the tenant-thread rebuild.
    assert progress["phase"] == "threads"
    assert progress["phase_index"] == 4


def test_sync_all_is_single_flight(non_admin_client, monkeypatch):
    """A double-click used to start a second concurrent run against the same upstreams."""

    async def slow_beds24(db, changed_by_user_id=None, tenant_ids=None):
        await asyncio.sleep(30)
        return 0

    monkeypatch.setattr(admin_sync, "_sync_beds24", slow_beds24)

    first = non_admin_client.post("/api/admin/sync-all", json={"tenant_ids": None}).json()
    second = non_admin_client.post("/api/admin/sync-all", json={"tenant_ids": None}).json()

    assert first["already_running"] is False
    assert second["already_running"] is True
    assert second["job_id"] == first["job_id"]


def test_sync_all_phase_failure_is_reported_not_fatal(non_admin_client, stub_phases, monkeypatch):
    async def failing_emails(db, tenant_ids=None, progress=None):
        raise RuntimeError("gmail exploded")

    monkeypatch.setattr(admin_sync, "_sync_emails", failing_emails)

    job_id = non_admin_client.post("/api/admin/sync-all", json={"tenant_ids": None}).json()["job_id"]
    job = poll_until_done(non_admin_client, job_id)

    assert job["status"] == "done"
    steps = {failure["step"]: failure for failure in job["result"]["partial_failures"]}
    assert "gmail exploded" in steps["email"]["error"]
    # The later phases must still have run.
    assert job["result"]["whatsapp_messages_imported"] == 7


def test_sync_all_phase_timeout_is_reported_not_fatal(non_admin_client, monkeypatch):
    monkeypatch.setattr(admin_sync, "EMAIL_PHASE_TIMEOUT_SECONDS", 0.05)

    async def slow_beds24(db, changed_by_user_id=None, tenant_ids=None):
        await asyncio.sleep(0.2)
        return 0

    async def fast_emails(db, tenant_ids=None, progress=None):
        if progress is not None:
            progress(0, 0)
        return 0

    async def fast_whatsapp(db, tenant_ids=None):
        return {"total_imported": 0, "synced_endpoints": 0, "results": [], "errors": []}

    monkeypatch.setattr(admin_sync, "_sync_beds24", slow_beds24)
    monkeypatch.setattr(admin_sync, "_sync_emails", fast_emails)
    monkeypatch.setattr(admin_sync, "_sync_whatsapp_linked_endpoints", fast_whatsapp)

    job_id = non_admin_client.post("/api/admin/sync-all", json={"tenant_ids": None}).json()["job_id"]
    job = poll_until_done(non_admin_client, job_id)

    assert job["status"] == "done"
    assert job["error"] is None
    summary = job["result"]
    assert summary["bookings_updated"] == 0
    steps = {failure["step"]: failure for failure in summary["partial_failures"]}
    assert "beds24" in steps
    assert "Timed out after 0.05s" in steps["beds24"]["error"]


def test_sync_all_email_progress_updates_within_phase(non_admin_client, monkeypatch):
    progress_updates: list[tuple[int, int]] = []

    async def fast_beds24(db, changed_by_user_id=None, tenant_ids=None):
        return 0

    async def slow_email_phase(db, tenant_ids=None, progress=None):
        if progress is not None:
            progress(0, 5)
            progress_updates.append((0, 5))
            progress(1, 5)
            progress_updates.append((1, 5))
            progress(2, 5)
            progress_updates.append((2, 5))
            progress(5, 5)
            progress_updates.append((5, 5))
        return 2

    async def fast_whatsapp(db, tenant_ids=None):
        return {"total_imported": 0, "synced_endpoints": 0, "results": [], "errors": []}

    monkeypatch.setattr(admin_sync, "_sync_beds24", fast_beds24)
    monkeypatch.setattr(admin_sync, "_sync_emails", slow_email_phase)
    monkeypatch.setattr(admin_sync, "_sync_whatsapp_linked_endpoints", fast_whatsapp)

    job_id = non_admin_client.post("/api/admin/sync-all", json={"tenant_ids": None}).json()["job_id"]
    job = poll_until_done(non_admin_client, job_id)

    assert job["status"] == "done"
    assert job["result"]["emails_imported"] == 2
    assert job["result"]["partial_failures"] == []
    assert progress_updates == [(0, 5), (1, 5), (2, 5), (5, 5)]


def test_sync_all_thread_timeout_is_reported_not_fatal(non_admin_client, monkeypatch):
    real_session_local = admin_sync.SessionLocal
    setup_session = real_session_local()
    tenant = Tenant(name="Thread timeout", booking_id="B-thread-timeout")
    setup_session.add(tenant)
    setup_session.commit()
    tenant_id = tenant.id
    setup_session.close()

    try:
        monkeypatch.setattr(admin_sync, "EMAIL_PHASE_TIMEOUT_SECONDS", 0.05)

        async def fast_beds24(db, changed_by_user_id=None, tenant_ids=None):
            return 0

        async def fast_emails(db, tenant_ids=None, progress=None):
            return 0

        async def fast_whatsapp(db, tenant_ids=None):
            return {"total_imported": 0, "synced_endpoints": 0, "results": [], "errors": []}

        def slow_thread_builder(db, tenant_id):
            time.sleep(0.2)

        monkeypatch.setattr(admin_sync, "_sync_beds24", fast_beds24)
        monkeypatch.setattr(admin_sync, "_sync_emails", fast_emails)
        monkeypatch.setattr(admin_sync, "_sync_whatsapp_linked_endpoints", fast_whatsapp)
        monkeypatch.setattr(admin_sync, "build_tenant_thread_timeline", slow_thread_builder)

        job_id = non_admin_client.post("/api/admin/sync-all", json={"tenant_ids": None}).json()["job_id"]
        job = poll_until_done(non_admin_client, job_id)

        assert job["status"] == "done"
        assert job["error"] is None
        summary = job["result"]
        assert summary["tenant_threads_updated"] == 0
        steps = {failure["step"]: failure for failure in summary["partial_failures"]}
        assert "tenant_threads" in steps
        assert f"Tenant {tenant_id} timed out after 0.05s" == steps["tenant_threads"]["error"]
    finally:
        cleanup_session = real_session_local()
        cleanup_session.query(Tenant).filter(Tenant.id == tenant_id).delete()
        cleanup_session.commit()
        cleanup_session.close()


def test_sync_all_status_unknown_job_is_404(non_admin_client):
    assert non_admin_client.get("/api/admin/sync-all/does-not-exist").status_code == 404


def test_sync_all_job_opens_its_own_session(non_admin_client, stub_phases, monkeypatch):
    """The request-scoped session is closed once the 202 is sent, so the job must not reuse it."""
    opened = []

    real_session_local = admin_sync.SessionLocal

    def tracking_session_local():
        session = real_session_local()
        opened.append(session)
        return session

    monkeypatch.setattr(admin_sync, "SessionLocal", tracking_session_local)

    job_id = non_admin_client.post("/api/admin/sync-all", json={"tenant_ids": None}).json()["job_id"]
    poll_until_done(non_admin_client, job_id)

    assert len(opened) == 1
