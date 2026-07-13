from datetime import datetime, timedelta, timezone

from app.core.security import get_password_hash, hash_token, verify_password
from app.models.admin_invite import AdminInvite
from app.models.user import User

ADMIN_ID = 1


def _make_invite(db_session, *, used=False, revoked=False, expired=False, email="invitee@example.com"):
    now = datetime.now(timezone.utc)
    invite = AdminInvite(
        email=email,
        full_name="Invitee",
        role="non-admin",
        token_hash=hash_token(f"token-{email}-{used}-{revoked}-{expired}"),
        expires_at=now - timedelta(hours=1) if expired else now + timedelta(hours=72),
        used_at=now if used else None,
        revoked_at=now if revoked else None,
        invited_by_user_id=ADMIN_ID,
    )
    db_session.add(invite)
    db_session.commit()
    db_session.refresh(invite)
    return invite


_next_user_id = [100]


def _make_user(db_session, *, email, is_admin=False, is_active=True):
    # Explicit ids avoid colliding with the mocked admin user (id=1) used by the `client` fixture.
    _next_user_id[0] += 1
    user = User(
        id=_next_user_id[0],
        email=email,
        full_name="Existing User",
        password_hash=get_password_hash("Sup3rSecret!"),
        is_active=is_active,
        is_admin=is_admin,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


# --- Authorization ---


def test_non_admin_cannot_list_or_manage_invites(non_admin_client):
    assert non_admin_client.get("/api/admin/invites").status_code == 403
    assert non_admin_client.post("/api/admin/invites/clear").status_code == 403


def test_non_admin_cannot_create_or_delete_users(non_admin_client):
    payload = {"email": "new@example.com", "password": "Sup3rSecret!", "password_confirmation": "Sup3rSecret!"}
    assert non_admin_client.post("/api/users", json=payload).status_code == 403
    assert non_admin_client.delete("/api/users/999").status_code == 403
    assert non_admin_client.get("/api/users").status_code == 403


# --- Bulk clear invites ---


def test_bulk_clear_revokes_only_pending_invites(client, db_session):
    pending = _make_invite(db_session, email="pending@example.com")
    accepted = _make_invite(db_session, used=True, email="accepted@example.com")
    expired = _make_invite(db_session, expired=True, email="expired@example.com")
    already_revoked = _make_invite(db_session, revoked=True, email="revoked@example.com")

    response = client.post("/api/admin/invites/clear")
    assert response.status_code == 200
    data = response.json()
    assert data["revoked_count"] == 1
    assert data["skipped_accepted_count"] == 1
    assert data["skipped_expired_count"] == 1

    db_session.refresh(pending)
    db_session.refresh(accepted)
    db_session.refresh(expired)
    db_session.refresh(already_revoked)
    assert pending.revoked_at is not None
    assert accepted.revoked_at is None
    assert expired.revoked_at is None
    assert already_revoked.revoked_at is not None


def test_bulk_clear_is_idempotent(client, db_session):
    _make_invite(db_session, email="pending2@example.com")
    first = client.post("/api/admin/invites/clear").json()
    assert first["revoked_count"] == 1

    second = client.post("/api/admin/invites/clear").json()
    assert second["revoked_count"] == 0


def test_invite_list_never_exposes_raw_token(client, db_session):
    _make_invite(db_session, email="secret@example.com")
    response = client.get("/api/admin/invites")
    assert response.status_code == 200
    for invite in response.json():
        assert "token_hash" not in invite
        assert "invite_url" not in invite or invite["invite_url"] is None


# --- Direct user creation ---


def test_admin_can_create_user(client, db_session):
    payload = {
        "email": "created@example.com",
        "full_name": "Created User",
        "is_admin": False,
        "password": "Sup3rSecret!",
        "password_confirmation": "Sup3rSecret!",
    }
    response = client.post("/api/users", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "created@example.com"
    assert "password" not in data
    assert "password_hash" not in data

    created = db_session.query(User).filter(User.email == "created@example.com").first()
    assert created is not None
    assert verify_password("Sup3rSecret!", created.password_hash)


def test_create_user_rejects_duplicate_email(client, db_session):
    _make_user(db_session, email="dup@example.com")
    payload = {
        "email": "dup@example.com",
        "password": "Sup3rSecret!",
        "password_confirmation": "Sup3rSecret!",
    }
    response = client.post("/api/users", json=payload)
    assert response.status_code == 400


def test_create_user_rejects_mismatched_passwords(client, db_session):
    payload = {
        "email": "mismatch@example.com",
        "password": "Sup3rSecret!",
        "password_confirmation": "Different1!",
    }
    response = client.post("/api/users", json=payload)
    assert response.status_code == 400


# --- Delete / deactivate users ---


def test_admin_can_delete_user(client, db_session):
    target = _make_user(db_session, email="todelete@example.com")
    response = client.delete(f"/api/users/{target.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["deactivated"] is True

    db_session.refresh(target)
    assert target.is_active is False


def test_deactivated_user_cannot_authenticate(client, db_session):
    target = _make_user(db_session, email="lockedout@example.com")
    client.delete(f"/api/users/{target.id}")

    login_response = client.post(
        "/api/auth/login",
        json={"email": "lockedout@example.com", "password": "Sup3rSecret!"},
    )
    assert login_response.status_code == 401


def test_delete_is_idempotent(client, db_session):
    target = _make_user(db_session, email="alreadyout@example.com", is_active=False)
    response = client.delete(f"/api/users/{target.id}")
    assert response.status_code == 200
    assert response.json()["already_inactive"] is True


def test_cannot_delete_last_active_admin(client, db_session):
    # ADMIN_USER (id=1) is a mocked current_user and is not itself a row in
    # this test's database, so this other admin is the only active admin on record.
    only_other_admin = _make_user(db_session, email="onlyadmin@example.com", is_admin=True)
    response = client.delete(f"/api/users/{only_other_admin.id}")
    assert response.status_code == 400

    db_session.refresh(only_other_admin)
    assert only_other_admin.is_active is True


def test_self_deletion_is_disallowed(client, db_session):
    self_user = User(id=ADMIN_ID, email="self@example.com", password_hash="x", is_active=True, is_admin=True)
    db_session.merge(self_user)
    db_session.commit()
    response = client.delete(f"/api/users/{ADMIN_ID}")
    assert response.status_code == 400


def test_user_list_never_exposes_password_fields(client, db_session):
    _make_user(db_session, email="visible@example.com")
    response = client.get("/api/users")
    assert response.status_code == 200
    for user in response.json():
        assert "password" not in user
        assert "password_hash" not in user
