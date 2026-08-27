from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import app.main as main_module
import pytest

from app.database import SessionLocal
from app.models.ai_auto_draft import AiAutoDraft
from app.models.bulk_planner_schedule import BulkPlannerSchedule
from app.models.bulk_planner_schedule_run import BulkPlannerScheduleRun
from app.models.bulk_planner_schedule_run_result import BulkPlannerScheduleRunResult
from app.models.communication import Communication
from app.models.gmail_integration import Conversation, ConversationMessage
from app.models.tenant import Tenant
from app.models.tenant_ai_settings import TenantAiSettings
from app.models.tenant_conversation_link import TenantConversationLink
from app.models.user import User
from app.services import bulk_planner_schedule_service

AMSTERDAM = ZoneInfo("Europe/Amsterdam")


def _ensure_user(db, user_id: int = 2) -> User:
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        user = User(id=user_id, email=f"user-{user_id}@example.com", password_hash="x", is_active=True, is_admin=False)
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def _create_tenant(db, *, name: str, booking_id: str, booking_status: str | None = None) -> Tenant:
    tenant = Tenant(name=name, booking_id=booking_id, booking_status=booking_status)
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    return tenant


def _add_whatsapp_message(db, tenant_id: int, *, when: datetime, direction: str) -> None:
    db.add(
        Communication(
            tenant_id=tenant_id,
            channel="whatsapp",
            direction=direction,
            provider="whatsapp-service",
            message=f"{direction} message",
            created_at=when,
        )
    )
    db.commit()


def _add_email_message(db, tenant_id: int, *, when: datetime, direction: str) -> None:
    conversation = Conversation(provider="gmail", provider_thread_id=f"thread-{tenant_id}-{when.timestamp()}", subject="Hi")
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    db.add(TenantConversationLink(tenant_id=tenant_id, conversation_id=conversation.id))
    db.commit()
    db.add(
        ConversationMessage(
            conversation_id=conversation.id,
            provider="gmail",
            provider_message_id=f"msg-{tenant_id}-{when.timestamp()}",
            direction=direction,
            body="email message",
            sent_at=when,
        )
    )
    db.commit()


def _create_schedule(
    db,
    *,
    name: str = "Morning run",
    enabled: bool = True,
    run_time_local: time = time(9, 30),
    status_filter: list[str] | None = None,
    last_message_within_days: int | None = None,
    last_message_direction: str | None = None,
    next_run_at: datetime | None = None,
    created_by_user_id: int = 2,
) -> BulkPlannerSchedule:
    schedule = BulkPlannerSchedule(
        name=name,
        enabled=enabled,
        run_time_local=run_time_local,
        status_filter=status_filter,
        last_message_within_days=last_message_within_days,
        last_message_direction=last_message_direction,
        next_run_at=next_run_at or datetime.now(timezone.utc) + timedelta(days=1),
        created_by_user_id=created_by_user_id,
    )
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    return schedule




def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _expected_next_run(now_utc: datetime, run_time_local: time) -> datetime:
    local_now = now_utc.astimezone(AMSTERDAM)
    candidate = datetime.combine(local_now.date(), run_time_local, tzinfo=AMSTERDAM)
    if candidate <= local_now:
        candidate = datetime.combine(local_now.date() + timedelta(days=1), run_time_local, tzinfo=AMSTERDAM)
    return candidate.astimezone(timezone.utc)


def test_schedule_crud_and_next_run_at_computation(non_admin_client, db_session, monkeypatch):
    _ensure_user(db_session, 2)
    frozen_now = datetime(2026, 8, 26, 6, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(bulk_planner_schedule_service, "_utc_now", lambda: frozen_now)

    create_response = non_admin_client.post(
        "/api/bulk-planner-schedules",
        json={
            "name": "Daily confirmed",
            "enabled": True,
            "run_time_local": "09:30:00",
            "status_filter": ["Confirmed"],
            "last_message_within_days": 3,
            "last_message_direction": "inbound",
        },
    )
    assert create_response.status_code == 201
    created = create_response.json()
    assert created["name"] == "Daily confirmed"
    assert created["status_filter"] == ["Confirmed"]
    assert _as_utc(datetime.fromisoformat(created["next_run_at"])) == _expected_next_run(frozen_now, time(9, 30))

    schedule_id = created["id"]
    detail_response = non_admin_client.get(f"/api/bulk-planner-schedules/{schedule_id}")
    assert detail_response.status_code == 200
    assert detail_response.json()["id"] == schedule_id

    updated_now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(bulk_planner_schedule_service, "_utc_now", lambda: updated_now)
    patch_response = non_admin_client.patch(
        f"/api/bulk-planner-schedules/{schedule_id}",
        json={"run_time_local": "07:15:00", "enabled": False, "status_filter": []},
    )
    assert patch_response.status_code == 200
    patched = patch_response.json()
    assert patched["enabled"] is False
    assert patched["status_filter"] == []
    assert _as_utc(datetime.fromisoformat(patched["next_run_at"])) == _expected_next_run(updated_now, time(7, 15))

    list_response = non_admin_client.get("/api/bulk-planner-schedules")
    assert list_response.status_code == 200
    assert list_response.json()[0]["id"] == schedule_id

    delete_response = non_admin_client.delete(f"/api/bulk-planner-schedules/{schedule_id}")
    assert delete_response.status_code == 204
    assert db_session.query(BulkPlannerSchedule).filter(BulkPlannerSchedule.id == schedule_id).first() is None


def test_preview_endpoint_returns_light_tenant_list(non_admin_client, db_session):
    _create_tenant(db_session, name="Confirmed A", booking_id="PREVIEW-A", booking_status="Confirmed")
    _create_tenant(db_session, name="Pending B", booking_id="PREVIEW-B", booking_status="Pending")

    response = non_admin_client.post(
        "/api/bulk-planner-schedules/preview",
        json={"status_filter": ["Confirmed"], "last_message_direction": None, "last_message_within_days": None},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["matched_tenant_count"] == 1
    assert payload["tenants"] == [
        {
            "id": pytest.approx(payload["tenants"][0]["id"]),
            "name": "Confirmed A",
            "booking_id": "PREVIEW-A",
            "booking_status": "Confirmed",
        }
    ]


def test_find_matching_tenant_ids_applies_status_days_direction_and_history_rules(db_session, monkeypatch):
    frozen_now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(bulk_planner_schedule_service, "_utc_now", lambda: frozen_now)

    tenant_confirmed_inbound = _create_tenant(db_session, name="Confirmed Inbound", booking_id="MATCH-A", booking_status="Confirmed")
    tenant_confirmed_outbound = _create_tenant(db_session, name="Confirmed Outbound", booking_id="MATCH-B", booking_status="Confirmed")
    tenant_request_inbound = _create_tenant(db_session, name="Request Inbound", booking_id="MATCH-C", booking_status="Request")
    tenant_no_history = _create_tenant(db_session, name="No History", booking_id="MATCH-D", booking_status="Confirmed")

    _add_whatsapp_message(db_session, tenant_confirmed_inbound.id, when=frozen_now - timedelta(days=2), direction="inbound")
    _add_email_message(db_session, tenant_confirmed_outbound.id, when=frozen_now - timedelta(days=2), direction="outbound")
    _add_whatsapp_message(db_session, tenant_request_inbound.id, when=frozen_now - timedelta(days=5), direction="inbound")

    assert set(
        bulk_planner_schedule_service.find_matching_tenant_ids(
            db_session,
            BulkPlannerSchedule(status_filter=["Confirmed"], run_time_local=time(9, 0), next_run_at=frozen_now),
        )
    ) == {tenant_confirmed_inbound.id, tenant_confirmed_outbound.id, tenant_no_history.id}

    assert set(
        bulk_planner_schedule_service.find_matching_tenant_ids(
            db_session,
            BulkPlannerSchedule(last_message_within_days=2, run_time_local=time(9, 0), next_run_at=frozen_now),
        )
    ) == {tenant_confirmed_inbound.id, tenant_confirmed_outbound.id}

    assert set(
        bulk_planner_schedule_service.find_matching_tenant_ids(
            db_session,
            BulkPlannerSchedule(last_message_direction="inbound", run_time_local=time(9, 0), next_run_at=frozen_now),
        )
    ) == {tenant_confirmed_inbound.id, tenant_request_inbound.id}

    assert set(
        bulk_planner_schedule_service.find_matching_tenant_ids(
            db_session,
            BulkPlannerSchedule(last_message_direction="outbound", run_time_local=time(9, 0), next_run_at=frozen_now),
        )
    ) == {tenant_confirmed_outbound.id}

    assert set(
        bulk_planner_schedule_service.find_matching_tenant_ids(
            db_session,
            BulkPlannerSchedule(last_message_direction="either", run_time_local=time(9, 0), next_run_at=frozen_now),
        )
    ) == {tenant_confirmed_inbound.id, tenant_confirmed_outbound.id, tenant_request_inbound.id}

    assert bulk_planner_schedule_service.find_matching_tenant_ids(
        db_session,
        BulkPlannerSchedule(
            status_filter=["Confirmed"],
            last_message_within_days=2,
            last_message_direction="inbound",
            run_time_local=time(9, 0),
            next_run_at=frozen_now,
        ),
    ) == [tenant_confirmed_inbound.id]

    assert tenant_no_history.id not in bulk_planner_schedule_service.find_matching_tenant_ids(
        db_session,
        BulkPlannerSchedule(last_message_within_days=30, run_time_local=time(9, 0), next_run_at=frozen_now),
    )

    assert set(
        bulk_planner_schedule_service.find_matching_tenant_ids(
            db_session,
            BulkPlannerSchedule(status_filter=[], run_time_local=time(9, 0), next_run_at=frozen_now),
        )
    ) == {
        tenant_confirmed_inbound.id,
        tenant_confirmed_outbound.id,
        tenant_request_inbound.id,
        tenant_no_history.id,
    }


def test_execute_due_schedule_records_success_and_skips(db_session, monkeypatch):
    frozen_now = datetime(2026, 8, 26, 8, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(bulk_planner_schedule_service, "_utc_now", lambda: frozen_now)

    tenant_both = _create_tenant(db_session, name="Both Channels", booking_id="EXEC-A", booking_status="Confirmed")
    tenant_email_off = _create_tenant(db_session, name="Email Off", booking_id="EXEC-B", booking_status="Confirmed")
    tenant_planner_off = _create_tenant(db_session, name="Planner Off", booking_id="EXEC-C", booking_status="Confirmed")

    for tenant in (tenant_both, tenant_email_off, tenant_planner_off):
        _add_whatsapp_message(db_session, tenant.id, when=frozen_now - timedelta(hours=1), direction="inbound")

    db_session.add(
        TenantAiSettings(
            tenant_id=tenant_both.id,
            planner_mode="manual",
            auto_draft_email=True,
            auto_draft_whatsapp=True,
        )
    )
    db_session.add(
        TenantAiSettings(
            tenant_id=tenant_email_off.id,
            planner_mode="manual",
            auto_draft_email=False,
            auto_draft_whatsapp=True,
        )
    )
    db_session.add(
        TenantAiSettings(
            tenant_id=tenant_planner_off.id,
            planner_mode="off",
            auto_draft_email=True,
            auto_draft_whatsapp=True,
        )
    )
    db_session.commit()

    planned: list[tuple[int, str]] = []

    def fake_run(db, *, draft_id, tenant_id, channel, operator_note, attachment_ids, user_id):
        planned.append((tenant_id, channel))
        draft = db.query(AiAutoDraft).filter(AiAutoDraft.id == draft_id).one()
        draft.generated_text = f"Draft for {tenant_id}-{channel}"
        draft.status = "pending"
        db.commit()

    monkeypatch.setattr(bulk_planner_schedule_service, "run_ai_plan_for_draft", fake_run)

    schedule = _create_schedule(
        db_session,
        status_filter=["Confirmed"],
        last_message_direction="either",
        next_run_at=frozen_now - timedelta(minutes=1),
    )

    run = bulk_planner_schedule_service.execute_due_schedule(db_session, schedule, trigger_reason="scheduled")
    results = (
        db_session.query(BulkPlannerScheduleRunResult)
        .filter(BulkPlannerScheduleRunResult.run_id == run.id)
        .order_by(BulkPlannerScheduleRunResult.id.asc())
        .all()
    )

    assert run.status == "completed"
    assert run.matched_tenant_count == 3
    assert set(planned) == {
        (tenant_both.id, "whatsapp"),
        (tenant_email_off.id, "whatsapp"),
    }
    assert len(results) == 6
    assert sum(1 for row in results if row.outcome == "success") == 2
    assert any(row.outcome == "skipped" and row.channel == "email" and row.tenant_id == tenant_email_off.id for row in results)
    assert any(row.outcome == "skipped" and row.tenant_id == tenant_planner_off.id for row in results)
    assert db_session.query(AiAutoDraft).filter(AiAutoDraft.tenant_id == tenant_both.id).count() == 1
    assert db_session.query(AiAutoDraft).filter(AiAutoDraft.tenant_id == tenant_email_off.id).count() == 1
    db_session.refresh(schedule)
    assert schedule.last_run_at is not None
    assert _as_utc(schedule.next_run_at) > frozen_now


def test_execute_due_schedule_picks_most_recent_channel_and_records_losers(db_session, monkeypatch):
    frozen_now = datetime(2026, 8, 26, 8, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(bulk_planner_schedule_service, "_utc_now", lambda: frozen_now)

    tenant_whatsapp_wins = _create_tenant(db_session, name="WhatsApp Wins", booking_id="WIN-A", booking_status="Confirmed")
    tenant_email_wins = _create_tenant(db_session, name="Email Wins", booking_id="WIN-B", booking_status="Confirmed")
    tenant_whatsapp_disabled = _create_tenant(db_session, name="WhatsApp Disabled", booking_id="WIN-C", booking_status="Confirmed")
    tenant_no_history = _create_tenant(db_session, name="No History", booking_id="WIN-D", booking_status="Confirmed")

    _add_email_message(db_session, tenant_whatsapp_wins.id, when=frozen_now - timedelta(hours=2), direction="inbound")
    _add_whatsapp_message(db_session, tenant_whatsapp_wins.id, when=frozen_now - timedelta(hours=1), direction="outbound")

    _add_whatsapp_message(db_session, tenant_email_wins.id, when=frozen_now - timedelta(hours=2), direction="inbound")
    _add_email_message(db_session, tenant_email_wins.id, when=frozen_now - timedelta(hours=1), direction="outbound")

    _add_email_message(db_session, tenant_whatsapp_disabled.id, when=frozen_now - timedelta(hours=2), direction="outbound")
    _add_whatsapp_message(db_session, tenant_whatsapp_disabled.id, when=frozen_now - timedelta(hours=1), direction="inbound")

    db_session.add_all(
        [
            TenantAiSettings(
                tenant_id=tenant_whatsapp_wins.id,
                planner_mode="manual",
                auto_draft_email=True,
                auto_draft_whatsapp=True,
            ),
            TenantAiSettings(
                tenant_id=tenant_email_wins.id,
                planner_mode="manual",
                auto_draft_email=True,
                auto_draft_whatsapp=True,
            ),
            TenantAiSettings(
                tenant_id=tenant_whatsapp_disabled.id,
                planner_mode="manual",
                auto_draft_email=True,
                auto_draft_whatsapp=False,
            ),
            TenantAiSettings(
                tenant_id=tenant_no_history.id,
                planner_mode="manual",
                auto_draft_email=True,
                auto_draft_whatsapp=True,
            ),
        ]
    )
    db_session.commit()

    planned: list[tuple[int, str]] = []

    def fake_run(db, *, draft_id, tenant_id, channel, operator_note, attachment_ids, user_id):
        planned.append((tenant_id, channel))
        draft = db.query(AiAutoDraft).filter(AiAutoDraft.id == draft_id).one()
        draft.generated_text = f"Draft for {tenant_id}-{channel}"
        draft.status = "pending"
        db.commit()

    monkeypatch.setattr(bulk_planner_schedule_service, "run_ai_plan_for_draft", fake_run)

    schedule = _create_schedule(
        db_session,
        status_filter=["Confirmed"],
        next_run_at=frozen_now - timedelta(minutes=1),
    )

    run = bulk_planner_schedule_service.execute_due_schedule(db_session, schedule, trigger_reason="scheduled")
    results = (
        db_session.query(BulkPlannerScheduleRunResult)
        .filter(BulkPlannerScheduleRunResult.run_id == run.id)
        .order_by(BulkPlannerScheduleRunResult.id.asc())
        .all()
    )

    assert run.status == "completed"
    assert run.matched_tenant_count == 4
    assert planned == [
        (tenant_whatsapp_wins.id, "whatsapp"),
        (tenant_email_wins.id, "email"),
    ]
    assert db_session.query(AiAutoDraft).filter(AiAutoDraft.tenant_id == tenant_whatsapp_wins.id).count() == 1
    assert db_session.query(AiAutoDraft).filter(AiAutoDraft.tenant_id == tenant_email_wins.id).count() == 1
    assert db_session.query(AiAutoDraft).filter(AiAutoDraft.tenant_id == tenant_whatsapp_disabled.id).count() == 0
    assert db_session.query(AiAutoDraft).filter(AiAutoDraft.tenant_id == tenant_no_history.id).count() == 0
    assert len(results) == 8

    whatsapp_wins_results = [row for row in results if row.tenant_id == tenant_whatsapp_wins.id]
    assert {(row.channel, row.outcome, row.skip_reason) for row in whatsapp_wins_results} == {
        ("email", "skipped", "Not the most recent channel for this tenant."),
        ("whatsapp", "success", None),
    }

    email_wins_results = [row for row in results if row.tenant_id == tenant_email_wins.id]
    assert {(row.channel, row.outcome, row.skip_reason) for row in email_wins_results} == {
        ("email", "success", None),
        ("whatsapp", "skipped", "Not the most recent channel for this tenant."),
    }

    whatsapp_disabled_results = [row for row in results if row.tenant_id == tenant_whatsapp_disabled.id]
    assert {(row.channel, row.outcome, row.skip_reason) for row in whatsapp_disabled_results} == {
        ("email", "skipped", "Not the most recent channel for this tenant."),
        ("whatsapp", "skipped", "auto_draft_whatsapp is disabled for this tenant."),
    }

    no_history_results = [row for row in results if row.tenant_id == tenant_no_history.id]
    assert {(row.channel, row.outcome, row.skip_reason) for row in no_history_results} == {
        ("email", "skipped", "No communication history for this tenant."),
        ("whatsapp", "skipped", "No communication history for this tenant."),
    }


def test_execute_due_schedule_isolates_planner_exceptions(monkeypatch):
    frozen_now = datetime(2026, 8, 26, 8, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(bulk_planner_schedule_service, "_utc_now", lambda: frozen_now)

    db = SessionLocal()
    tenant_ok = tenant_fail = schedule = None
    try:
        tenant_ok = _create_tenant(db, name="OK", booking_id="ERR-A", booking_status="Confirmed")
        tenant_fail = _create_tenant(db, name="FAIL", booking_id="ERR-B", booking_status="Confirmed")
        for tenant in (tenant_ok, tenant_fail):
            _add_whatsapp_message(db, tenant.id, when=frozen_now - timedelta(hours=1), direction="inbound")
            db.add(
                TenantAiSettings(
                    tenant_id=tenant.id,
                    planner_mode="manual",
                    auto_draft_email=True,
                    auto_draft_whatsapp=True,
                )
            )
        db.commit()

        def fake_run(db, *, draft_id, tenant_id, channel, operator_note, attachment_ids, user_id):
            if tenant_id == tenant_fail.id and channel == "whatsapp":
                raise RuntimeError("boom")
            draft = db.query(AiAutoDraft).filter(AiAutoDraft.id == draft_id).one()
            draft.generated_text = f"draft {tenant_id}-{channel}"
            db.commit()

        monkeypatch.setattr(bulk_planner_schedule_service, "run_ai_plan_for_draft", fake_run)

        schedule = _create_schedule(
            db,
            status_filter=["Confirmed"],
            last_message_direction="either",
            next_run_at=frozen_now - timedelta(minutes=1),
        )
        run = bulk_planner_schedule_service.execute_due_schedule(db, schedule, trigger_reason="scheduled")

        results = db.query(BulkPlannerScheduleRunResult).filter(BulkPlannerScheduleRunResult.run_id == run.id).all()
        assert run.status == "completed"
        assert any(row.outcome == "error" and row.tenant_id == tenant_fail.id and row.channel == "whatsapp" for row in results)
        assert any(
            row.outcome == "skipped"
            and row.tenant_id == tenant_ok.id
            and row.channel == "email"
            and row.skip_reason == "Not the most recent channel for this tenant."
            for row in results
        )
        assert any(row.outcome == "success" and row.tenant_id == tenant_ok.id and row.channel == "whatsapp" for row in results)
    finally:
        if schedule is not None:
            run_ids = [row.id for row in db.query(BulkPlannerScheduleRun).filter(BulkPlannerScheduleRun.schedule_id == schedule.id).all()]
            if run_ids:
                db.query(BulkPlannerScheduleRunResult).filter(BulkPlannerScheduleRunResult.run_id.in_(run_ids)).delete(synchronize_session=False)
            db.query(BulkPlannerScheduleRun).filter(BulkPlannerScheduleRun.schedule_id == schedule.id).delete(synchronize_session=False)
            db.query(BulkPlannerSchedule).filter(BulkPlannerSchedule.id == schedule.id).delete(synchronize_session=False)
        for tenant in (tenant_ok, tenant_fail):
            if tenant is None:
                continue
            db.query(AiAutoDraft).filter(AiAutoDraft.tenant_id == tenant.id).delete(synchronize_session=False)
            db.query(TenantAiSettings).filter(TenantAiSettings.tenant_id == tenant.id).delete(synchronize_session=False)
            db.query(Communication).filter(Communication.tenant_id == tenant.id).delete(synchronize_session=False)
            db.query(TenantConversationLink).filter(TenantConversationLink.tenant_id == tenant.id).delete(synchronize_session=False)
            db.query(Tenant).filter(Tenant.id == tenant.id).delete(synchronize_session=False)
        db.commit()
        db.close()


def test_run_history_endpoints_return_ordering_pagination_and_results(non_admin_client, db_session):
    _ensure_user(db_session, 2)
    tenant = _create_tenant(db_session, name="History Tenant", booking_id="HIST-A", booking_status="Confirmed")
    schedule = _create_schedule(db_session, created_by_user_id=2)
    older_run = BulkPlannerScheduleRun(
        schedule_id=schedule.id,
        started_at=datetime(2026, 8, 25, 8, 0, tzinfo=timezone.utc),
        completed_at=datetime(2026, 8, 25, 8, 2, tzinfo=timezone.utc),
        trigger_reason="scheduled",
        matched_tenant_count=1,
        status="completed",
    )
    newer_run = BulkPlannerScheduleRun(
        schedule_id=schedule.id,
        started_at=datetime(2026, 8, 26, 8, 0, tzinfo=timezone.utc),
        completed_at=datetime(2026, 8, 26, 8, 2, tzinfo=timezone.utc),
        trigger_reason="catch_up",
        matched_tenant_count=2,
        status="completed",
    )
    draft = AiAutoDraft(tenant_id=tenant.id, channel="email", generated_text="", status="pending")
    db_session.add_all([older_run, newer_run, draft])
    db_session.commit()
    db_session.refresh(older_run)
    db_session.refresh(newer_run)
    db_session.refresh(draft)
    db_session.add(
        BulkPlannerScheduleRunResult(
            run_id=newer_run.id,
            tenant_id=tenant.id,
            channel="email",
            outcome="success",
            draft_id=draft.id,
        )
    )
    db_session.commit()

    runs_response = non_admin_client.get(f"/api/bulk-planner-schedules/{schedule.id}/runs?limit=1&offset=0")
    assert runs_response.status_code == 200
    runs_payload = runs_response.json()
    assert runs_payload["total"] == 2
    assert len(runs_payload["items"]) == 1
    assert runs_payload["items"][0]["id"] == newer_run.id
    assert runs_payload["items"][0]["trigger_reason"] == "catch_up"

    results_response = non_admin_client.get(f"/api/bulk-planner-schedules/{schedule.id}/runs/{newer_run.id}/results")
    assert results_response.status_code == 200
    assert results_response.json() == [
        {
            "id": pytest.approx(results_response.json()[0]["id"]),
            "run_id": newer_run.id,
            "tenant_id": tenant.id,
            "tenant_name": "History Tenant",
            "channel": "email",
            "outcome": "success",
            "skip_reason": None,
            "error_message": None,
            "draft_id": draft.id,
            "created_at": results_response.json()[0]["created_at"],
        }
    ]


def test_due_polling_respects_enabled_flag_and_catch_up_runs_once(monkeypatch):
    frozen_now = datetime.now(timezone.utc).replace(microsecond=0)
    monkeypatch.setattr(bulk_planner_schedule_service, "_utc_now", lambda: frozen_now)

    def fake_run(db, *, draft_id, tenant_id, channel, operator_note, attachment_ids, user_id):
        draft = db.query(AiAutoDraft).filter(AiAutoDraft.id == draft_id).one()
        draft.generated_text = "scheduled"
        db.commit()

    monkeypatch.setattr(bulk_planner_schedule_service, "run_ai_plan_for_draft", fake_run)

    db = SessionLocal()
    enabled_schedule = disabled_schedule = tenant = None
    try:
        tenant = _create_tenant(db, name="Poller Tenant", booking_id="POLL-A", booking_status="Confirmed")
        _add_whatsapp_message(db, tenant.id, when=frozen_now - timedelta(hours=1), direction="inbound")
        db.add(
            TenantAiSettings(
                tenant_id=tenant.id,
                planner_mode="manual",
                auto_draft_email=True,
                auto_draft_whatsapp=True,
            )
        )
        db.commit()
        enabled_schedule = _create_schedule(
            db,
            name="Enabled",
            status_filter=["Confirmed"],
            last_message_direction="either",
            next_run_at=frozen_now - timedelta(days=2),
        )
        disabled_schedule = _create_schedule(
            db,
            name="Disabled",
            enabled=False,
            status_filter=["Confirmed"],
            next_run_at=frozen_now - timedelta(days=2),
        )

        main_module._run_due_bulk_planner_schedules_once()
        main_module._run_due_bulk_planner_schedules_once()

        runs = db.query(BulkPlannerScheduleRun).filter(BulkPlannerScheduleRun.schedule_id == enabled_schedule.id).all()
        assert len(runs) == 1
        assert runs[0].trigger_reason == "catch_up"
        assert db.query(BulkPlannerScheduleRun).filter(BulkPlannerScheduleRun.schedule_id == disabled_schedule.id).count() == 0
        db.refresh(enabled_schedule)
        assert _as_utc(enabled_schedule.next_run_at) > frozen_now
    finally:
        if enabled_schedule is not None:
            db.query(BulkPlannerScheduleRunResult).filter(
                BulkPlannerScheduleRunResult.run_id.in_(
                    [row.id for row in db.query(BulkPlannerScheduleRun).filter(BulkPlannerScheduleRun.schedule_id == enabled_schedule.id).all()]
                )
            ).delete(synchronize_session=False)
            db.query(BulkPlannerScheduleRun).filter(BulkPlannerScheduleRun.schedule_id == enabled_schedule.id).delete(synchronize_session=False)
            db.query(BulkPlannerSchedule).filter(BulkPlannerSchedule.id == enabled_schedule.id).delete(synchronize_session=False)
        if disabled_schedule is not None:
            db.query(BulkPlannerSchedule).filter(BulkPlannerSchedule.id == disabled_schedule.id).delete(synchronize_session=False)
        if tenant is not None:
            db.query(AiAutoDraft).filter(AiAutoDraft.tenant_id == tenant.id).delete(synchronize_session=False)
            db.query(TenantAiSettings).filter(TenantAiSettings.tenant_id == tenant.id).delete(synchronize_session=False)
            db.query(Communication).filter(Communication.tenant_id == tenant.id).delete(synchronize_session=False)
            db.query(TenantConversationLink).filter(TenantConversationLink.tenant_id == tenant.id).delete(synchronize_session=False)
            db.query(Tenant).filter(Tenant.id == tenant.id).delete(synchronize_session=False)
        db.commit()
        db.close()
