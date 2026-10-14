import io
import time

from .conftest import make_tenant

INVOICE = ("Рахунок на оплату №145\nПостачальник: ТОВ Ромашка\nЄДРПОУ: 32855961\n"
           "IBAN UA213223130000026007233566001\nРазом до сплати: 1 200,50\n").encode("utf-8")


def upload(client, h, name="inv.txt", data=INVOICE, **form):
    return client.post("/api/docs", headers=h, files=[("files", (name, io.BytesIO(data), "text/plain"))], data=form)


def wait_review(client, h, doc_id, tries=40):
    for _ in range(tries):
        d = client.get(f"/api/docs/{doc_id}", headers=h).json()
        if d["status"] not in ("queued", "processing"):
            return d
        time.sleep(0.05)
    raise AssertionError("timeout")


def test_auth_required(client):
    assert client.get("/api/docs?module=docs_extract").status_code == 401
    assert client.post("/api/auth/login", json={"email": "x@x.io", "password": "bad-pass-1"}).status_code == 401


def test_full_flow(client, tenant_a):
    h, _ = tenant_a
    r = upload(client, h, doc_type="invoice")
    assert r.status_code == 201, r.text
    d = wait_review(client, h, r.json()[0]["id"])
    assert d["status"] == "review"
    assert d["extracted"]["total_amount"] == 1200.5
    assert d["extracted"]["supplier_tax_id"] == "32855961"
    # затвердження
    r = client.post(f"/api/docs/{d['id']}/approve", headers=h, params={"force": True})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    csv = client.get("/api/docs/export.csv?module=docs_extract", headers=h)
    assert csv.status_code == 200 and "32855961" in csv.text


def test_duplicate_detection(client, tenant_a):
    h, _ = tenant_a
    first = wait_review(client, h, upload(client, h).json()[0]["id"])
    client.post(f"/api/docs/{first['id']}/approve", headers=h, params={"force": True})
    second = wait_review(client, h, upload(client, h).json()[0]["id"])
    assert any(f["code"] == "duplicate" for f in second["flags"])


def test_approve_blocked_by_errors_without_force(client, tenant_a):
    h, _ = tenant_a
    d = wait_review(client, h, upload(client, h, data=b"no data here").json()[0]["id"])
    r = client.post(f"/api/docs/{d['id']}/approve", headers=h)
    if any(f["severity"] == "error" for f in d["flags"]):
        assert r.status_code == 422


def test_tenant_isolation(client, tenant_a):
    h_a, _ = tenant_a
    h_b, _ = make_tenant(client, "Beta Co", "beta@b.com")
    doc_id = upload(client, h_a).json()[0]["id"]
    assert client.get(f"/api/docs/{doc_id}", headers=h_b).status_code == 404
    assert client.get(f"/api/docs/{doc_id}/file", headers=h_b).status_code == 404
    assert client.post(f"/api/docs/{doc_id}/approve", headers=h_b).status_code == 404
    assert client.get("/api/docs?module=docs_extract", headers=h_b).json()["total"] == 0


def test_module_gating_and_admin_override(client, admin_h):
    h, tid = make_tenant(client, "Gamma", "gamma@g.com")  # trial: тільки docs_extract
    assert client.get("/api/contractors", headers=h).status_code == 403
    r = client.patch(f"/api/admin/tenants/{tid}", headers=admin_h, json={"modules_override": ["docs_extract", "reconcile"]})
    assert r.status_code == 200
    assert client.get("/api/contractors", headers=h).status_code == 200
    mods = {m["code"]: m["enabled"] for m in client.get("/api/modules", headers=h).json()}
    assert mods["reconcile"] and not mods["reports"]


def test_suspended_tenant_blocked(client, admin_h):
    h, tid = make_tenant(client, "Delta", "delta@d.com")
    client.patch(f"/api/admin/tenants/{tid}", headers=admin_h, json={"status": "suspended"})
    assert client.get("/api/docs?module=docs_extract", headers=h).status_code == 403


def test_admin_endpoints_forbidden_for_tenants(client, tenant_a):
    h, _ = tenant_a
    assert client.get("/api/admin/tenants", headers=h).status_code == 403


def test_doc_limit(client, admin_h):
    h, tid = make_tenant(client, "Limited", "lim@l.com")
    client.patch(f"/api/admin/tenants/{tid}", headers=admin_h, json={"doc_limit_override": 1})
    assert upload(client, h).status_code == 201
    assert upload(client, h).status_code == 402


def test_upload_validation(client, tenant_a):
    h, _ = tenant_a
    assert upload(client, h, name="evil.exe", data=b"MZ").status_code == 400
    assert upload(client, h, name="empty.txt", data=b"").status_code == 400


def test_contractor_match_and_iban_change(client, admin_h):
    h, tid = make_tenant(client, "Eps", "eps@e.com")
    client.patch(f"/api/admin/tenants/{tid}", headers=admin_h, json={"plan": "business"})
    csv_data = "Назва;ЄДРПОУ;IBAN\nТОВ Ромашка;32855961;UA903052992990004149123456789\n".encode("utf-8")
    r = client.post("/api/contractors/import", headers=h, files={"file": ("c.csv", io.BytesIO(csv_data), "text/csv")})
    assert r.status_code == 200 and r.json()["added"] == 1
    d = wait_review(client, h, upload(client, h).json()[0]["id"])
    assert d["match"]["status"] == "matched"
    assert any(f["code"] == "iban_changed" for f in d["flags"])


def test_admin_overview(client, admin_h):
    r = client.get("/api/admin/overview", headers=admin_h)
    assert r.status_code == 200 and r.json()["tenants"] >= 1
