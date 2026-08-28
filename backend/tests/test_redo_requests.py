import pytest

from app.core.dependencies import get_current_user
from app.main import app
from app.models.redo_request_log import RedoRequestLog
from app.models.tenant import Tenant
from app.models.user import User

REDO_USER = User(id=8, email="redo-review@example.com", password_hash="x", is_active=True, is_admin=False)


@pytest.fixture()
def user_client(client):
    app.dependency_overrides[get_current_user] = lambda: REDO_USER
    yield client
    app.dependency_overrides.pop(get_current_user, None)


def _create_tenant(db_session):
    tenant = Tenant(name="Redo Review Tenant", booking_id="B-redo-review-1")
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


def _create_redo_log(db_session, tenant):
    redo_log = RedoRequestLog(tenant_id=tenant.id, channel="crm", what="make it shorter", why=None, reviewed=False)
    db_session.add(redo_log)
    db_session.commit()
    db_session.refresh(redo_log)
    return redo_log


def test_patch_reviewed_flag_updates_and_lists(user_client, db_session):
    tenant = _create_tenant(db_session)
    redo_log = _create_redo_log(db_session, tenant)

    response = user_client.patch(f"/api/redo-requests/{redo_log.id}", json={"reviewed": True})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["reviewed"] is True

    db_session.expire_all()
    persisted = db_session.query(RedoRequestLog).filter(RedoRequestLog.id == redo_log.id).one()
    assert persisted.reviewed is True

    listed = user_client.get("/api/redo-requests")
    assert listed.status_code == 200
    assert listed.json()[0]["reviewed"] is True
