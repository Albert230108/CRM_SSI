from app.core.dependencies import get_current_user
from app.main import app
from app.models.user import User

REFRESH_USER = User(id=42, email='refresh@example.com', password_hash='x', is_active=True, is_admin=False)


def test_refresh_returns_new_access_token(client):
    app.dependency_overrides[get_current_user] = lambda: REFRESH_USER
    try:
        response = client.post('/api/auth/refresh')

        assert response.status_code == 200
        payload = response.json()
        assert payload['access_token']
        assert payload['token_type'] == 'bearer'
    finally:
        app.dependency_overrides.pop(get_current_user, None)
