import io
import time
import uuid

from app.config import get_settings
from app.core import telegram as tg
from app.modules.docs_extract import llm, pipeline

from .conftest import make_tenant

CLEAN = {"detected_type": "invoice", "supplier_name": "ТОВ Чисте", "supplier_tax_id": "32855961", "supplier_iban": "",
         "buyer_name": "", "buyer_tax_id": "", "doc_number": "C-1", "doc_date": "", "due_date": "", "currency": "UAH",
         "total_amount": 100.0, "vat_amount": 0.0, "payment_purpose": "", "line_items": [], "confidence": "high", "notes": ""}


def up(client, h, data=b"Razom 10,00", name="a.txt", doc_type="invoice"):
    r = client.post("/api/docs", headers=h, files=[("files", (name, io.BytesIO(data), "text/plain"))],
                    data={"doc_type": doc_type})
    assert r.status_code == 201, r.text
    return r.json()[0]["id"]


def wait(client, h, doc_id):
    for _ in range(100):
        d = client.get(f"/api/docs/{doc_id}", headers=h).json()
        if d["status"] not in ("queued", "processing"):
            return d
        time.sleep(0.05)
    raise AssertionError("timeout")


def test_auto_approve_clean_only(client, tenant_a, monkeypatch):
    h, _ = tenant_a

    class Fake(llm.MockProvider):
        def extract(self, files, doc_type, context):
            d = dict(CLEAN, doc_number=f"C-{uuid.uuid4().hex[:6]}")
            if b"bad" in files[0].data:
                d["supplier_tax_id"] = "12345679"  # не проходить контрольну суму → помилка
            return llm.LLMResult(d)

    monkeypatch.setattr(pipeline, "get_provider", lambda: Fake())
    assert wait(client, h, up(client, h))["status"] == "review"  # опція вимкнена за замовчуванням
    assert client.put("/api/settings", headers=h, json={"auto_approve_clean": True}).json()["auto_approve_clean"]
    assert wait(client, h, up(client, h))["status"] == "approved"
    assert wait(client, h, up(client, h, b"bad"))["status"] == "review"  # з помилкою — лишається людині


def test_next_and_bulk_approve(client, tenant_a):
    h, _ = tenant_a
    ok1 = up(client, h, "Рахунок №N1\nRazom 10,00".encode())
    bad = up(client, h, "Рахунок №N2\nЄДРПОУ: 12345679\nRazom 20,00".encode())
    ok2 = up(client, h, "Рахунок №N3\nRazom 30,00".encode())
    for i in (ok1, bad, ok2):
        wait(client, h, i)
    assert client.get(f"/api/docs/next?module=docs_extract&after={ok1}", headers=h).json()["id"] == bad
    res = client.post("/api/docs/bulk-approve", headers=h, json={"ids": [ok1, bad, ok2, 999999]}).json()
    assert ok1 in res["approved"] and ok2 in res["approved"]
    assert {s["id"] for s in res["skipped"]} == {bad, 999999}
    assert client.get(f"/api/docs/{bad}", headers=h).json()["status"] == "review"


def test_xlsx_export_and_dashboard(client, tenant_a):
    h, _ = tenant_a
    d = wait(client, h, up(client, h))
    client.post(f"/api/docs/{d['id']}/approve", headers=h, params={"force": True})
    r = client.get("/api/docs/export.xlsx?module=docs_extract", headers=h)
    assert r.status_code == 200 and r.content[:2] == b"PK"
    dash = client.get("/api/dashboard", headers=h).json()
    assert len(dash["series"]) == 14 and dash["series"][-1]["count"] >= 1


def test_impersonation_is_admin_only_and_audited(client, admin_h, tenant_a):
    h, tid = tenant_a
    assert client.post(f"/api/admin/tenants/{tid}/impersonate", headers=h).status_code == 403
    tok = client.post(f"/api/admin/tenants/{tid}/impersonate", headers=admin_h).json()["access_token"]
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {tok}"}).json()
    assert me["role"] == "owner" and me["tenant_id"] == tid
    log = client.get(f"/api/admin/audit?tenant_id={tid}", headers=admin_h).json()
    assert any(a["action"] == "admin.impersonate" for a in log)


def test_telegram_flow(client, tenant_a, monkeypatch):
    h, _ = tenant_a
    sent, token_ = [], "123456:" + "A" * 30
    secret_holder = {}

    def fake_call(token, method, **params):
        if method == "getMe":
            return {"username": "doc_bot"}
        if method == "setWebhook":
            secret_holder["s"] = params["secret_token"]
        if method == "sendMessage":
            sent.append(params["text"])
        return {}

    monkeypatch.setattr(tg, "call", fake_call)
    monkeypatch.setattr(tg, "download", lambda token, fid: ("file.txt", "Разом 77,00".encode()))
    monkeypatch.setattr(get_settings(), "public_api_url", "https://api.example.com")

    s = client.put("/api/settings/telegram", headers=h, json={"bot_token": token_}).json()
    assert s["telegram"]["connected"] and s["telegram"]["bot_username"] == "doc_bot"
    intake = client.get("/api/integrations", headers=h).json()["intake_token"]
    hook = f"/api/telegram/{intake}"
    sec = {"X-Telegram-Bot-Api-Secret-Token": secret_holder["s"]}
    msg = lambda **m: {"message": {"chat": {"id": 42}, **m}}  # noqa: E731

    assert client.post(hook, json=msg(text="hi"), headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"}).status_code == 404
    client.post(hook, json=msg(document={"file_id": "f", "file_name": "inv.txt"}), headers=sec)
    assert "не підключено" in sent[-1]  # чат ще не прив'язаний
    code = client.get("/api/settings", headers=h).json()["telegram"]["pair_code"]
    client.post(hook, json=msg(text="/bind 000000"), headers=sec)
    assert "Невірний код" in sent[-1]
    client.post(hook, json=msg(text=f"/bind {code}"), headers=sec)
    assert "підключено" in sent[-1]
    before = client.get("/api/docs?module=docs_extract", headers=h).json()["total"]
    client.post(hook, json=msg(document={"file_id": "f", "file_name": "inv.txt"}), headers=sec)
    assert "Прийнято" in sent[-1]
    assert client.get("/api/docs?module=docs_extract", headers=h).json()["total"] == before + 1
    assert client.delete("/api/settings/telegram", headers=h).status_code == 204
    assert client.post(hook, json=msg(text="x"), headers=sec).status_code == 404


def test_settings_owner_only(client, tenant_a):
    h, _ = tenant_a
    team = client.post("/api/team", headers=h, json={"email": f"v-{uuid.uuid4().hex[:5]}@v.com", "role": "viewer",
                                                    "password": "viewer-pass-1"})
    assert team.status_code == 201
    login = client.post("/api/auth/login", json={"email": team.json()["email"], "password": "viewer-pass-1"}).json()
    vh = {"Authorization": f"Bearer {login['access_token']}"}
    assert client.put("/api/settings", headers=vh, json={"auto_approve_clean": True}).status_code == 403
    assert client.get("/api/settings", headers=vh).status_code == 200
