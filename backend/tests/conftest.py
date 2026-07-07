import os
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite:///./backend_test.db")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("WHATSAPP_SERVICE_URL", "http://example.invalid")
os.environ.setdefault("WHATSAPP_API_KEY", "test-key")
os.environ.setdefault("CRM_WEBHOOK_SECRET", "test-webhook-secret")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.dependencies import get_current_admin_user, get_db
from app.database import Base
from app.main import app
from app.models import *  # noqa: F401,F403
from app.models.user import User

TEST_DB_PATH = Path("backend_test.db")
engine = create_engine("sqlite:///./backend_test.db", connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
ADMIN_USER = User(id=1, email="admin@example.com", password_hash="x", is_active=True, is_admin=True)


@pytest.fixture(scope="session", autouse=True)
def prepare_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()


@pytest.fixture()
def db_session():
    connection = engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture()
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_admin_user] = lambda: ADMIN_USER
    with TestClient(app, headers={"X-Webhook-Secret": os.environ["CRM_WEBHOOK_SECRET"]}) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def client_without_webhook_secret(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_admin_user] = lambda: ADMIN_USER
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
