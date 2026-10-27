"""Shared fixtures. Every test run gets a throwaway SQLite file so tests never
touch a real database."""

import os
import tempfile
import uuid

import pytest

_DB = os.path.join(tempfile.gettempdir(), f"tafseel_test_{uuid.uuid4().hex}.db")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_DB}")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-used-in-production")
os.environ.setdefault("ENVIRONMENT", "test")


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth_client(client):
    """A client with a fresh registered user. Returns (client, headers)."""
    email = f"user_{uuid.uuid4().hex[:10]}@example.com"
    res = client.post("/api/auth/register", json={"email": email, "password": "correct-horse-battery"})
    assert res.status_code == 201, res.text
    token = res.json()["access_token"]
    return client, {"Authorization": f"Bearer {token}"}
