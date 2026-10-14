import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="tochno-test-")
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{_tmp}/test.db"
os.environ["STORAGE_DIR"] = f"{_tmp}/storage"
os.environ["BOOTSTRAP_ADMIN_PASSWORD"] = "admin-pass-123"
os.environ["LLM_PROVIDER"] = "mock"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


def _login(client, email, password):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="session")
def admin_h(client):
    return _login(client, "admin@tochno.app", "admin-pass-123")


def make_tenant(client, name, email, plan="business"):
    r = client.post("/api/auth/signup", json={"company": name, "full_name": "Owner", "email": email,
                                              "password": "password-123"})
    assert r.status_code == 201, r.text
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    return h, r.json()["user"]["tenant_id"]


@pytest.fixture()
def tenant_a(client, admin_h):
    import uuid
    email = f"a-{uuid.uuid4().hex[:6]}@a.com"
    h, tid = make_tenant(client, "Alpha " + email, email)
    client.patch(f"/api/admin/tenants/{tid}", json={"plan": "business"}, headers=admin_h)
    return h, tid
