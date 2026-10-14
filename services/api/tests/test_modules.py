import io
import time
import uuid
from datetime import date

from app.modules.identity.types import analyze as analyze_identity
from app.modules.identity.validators import ipn_birth_date, mrz_check_digit, parse_td1_mrz
from app.modules.reports.types import analyze_balance, analyze_bank, analyze_pnl

from .conftest import make_tenant


def _ipn(birth: date, male=True) -> str:
    days = (birth - date(1899, 12, 31)).days
    base = f"{days:05d}" + "123" + ("1" if male else "2")  # 9-та цифра: непарна — чоловіча
    w = (-1, 5, 7, 9, 4, 6, 10, 5, 7)
    chk = sum(int(x) * y for x, y in zip(base, w)) % 11 % 10
    return base + str(chk)


def wait(client, h, doc_id):
    for _ in range(80):
        d = client.get(f"/api/docs/{doc_id}", headers=h).json()
        if d["status"] not in ("queued", "processing"):
            return d
        time.sleep(0.05)
    raise AssertionError("timeout")


def up(client, h, data, name, doc_type):
    r = client.post("/api/docs", headers=h, files=[("files", (name, io.BytesIO(data), "text/plain"))],
                    data={"doc_type": doc_type})
    assert r.status_code == 201, r.text
    return r.json()[0]["id"]


# ---------------- identity ----------------

def test_ipn_derives_birth_date_and_gender():
    ipn = _ipn(date(1990, 5, 17))
    assert ipn_birth_date(ipn) == "1990-05-17"
    res = analyze_identity(None, None, {"last_name": "А", "first_name": "Б", "tax_id": ipn, "birth_date": "",
                                        "gender": "", "document_number": "123456789", "mrz": ""})
    assert res.data["birth_date"] == "1990-05-17" and res.data["gender"] == "чоловіча"


def test_birth_date_conflicts_with_ipn():
    ipn = _ipn(date(1990, 5, 17))
    res = analyze_identity(None, None, {"last_name": "А", "first_name": "Б", "tax_id": ipn, "birth_date": "1991-01-01",
                                        "document_number": "123456789", "mrz": ""})
    assert any(f["code"] == "birth_vs_ipn" for f in res.flags)


def test_mrz_overrides_and_expiry():
    l1 = "IDUKR" + "123456789"[:9]
    l1 = l1 + str(mrz_check_digit("123456789")) + "<" * 15
    bd = "900517"
    l2 = bd + str(mrz_check_digit(bd)) + "M" + "200101" + str(mrz_check_digit("200101")) + "UKR" + "<" * 11 + "0"
    out = parse_td1_mrz(l1 + "\n" + l2, today=date(2026, 1, 1))
    assert out["document_number"] == "123456789" and out["birth_date"] == "1990-05-17"
    res = analyze_identity(None, None, {"last_name": "А", "first_name": "Б", "tax_id": "", "document_number": "000000000",
                                        "birth_date": "", "expiry_date": "", "mrz": l1 + "\n" + l2},
                           today=date(2026, 1, 1))
    assert res.data["document_number"] == "123456789"
    assert any(f["code"] == "expired" for f in res.flags)  # 2020-01-01 < 2026-01-01


def test_identity_module_flow(client, tenant_a):
    h, _ = tenant_a
    doc_id = up(client, h, "Прізвище: Коваленко\nІм'я: Олена\n".encode(), "p.txt", "identity_doc")
    d = wait(client, h, doc_id)
    assert d["module"] == "identity" and d["extracted"]["last_name"] == "Коваленко"
    assert client.get("/api/docs?module=docs_extract", headers=h).json()["total"] == 0  # модулі розділені
    assert client.get("/api/docs?module=identity", headers=h).json()["total"] >= 1


# ---------------- reports ----------------

def test_bank_statement_metrics_and_mismatch():
    res = analyze_bank(None, None, {"currency": "UAH", "opening_balance": 1000, "closing_balance": 9999, "transactions": [
        {"date": "2026-01-02", "description": "Оплата", "counterparty": "A", "amount": 5000},
        {"date": "2026-01-03", "description": "Орендна плата", "counterparty": "B", "amount": -2000},
        {"date": "2026-01-03", "description": "Орендна плата", "counterparty": "B", "amount": -2000}]})
    m = res.metrics
    assert m["total_in"] == 5000 and m["total_out"] == 4000
    assert m["by_category"][0]["name"] == "Оренда"
    codes = {f["code"] for f in res.flags}
    assert {"balance_mismatch", "duplicate_tx"} <= codes


def test_categorize_handles_ukrainian_inflections():
    from app.modules.reports.types import categorize

    assert categorize("Сплата єдиного податку", -100) == "Податки та збори"
    assert categorize("Орендної плати за січень", -100) == "Оренда"
    assert categorize("Послуги зв’язку", -100) == "Комунальні та зв'язок"
    assert categorize("Будь-що", 5) == "Надходження"


def test_balance_must_balance():
    ok = analyze_balance(None, None, {"assets": [{"name": "a", "amount": 100, "current": True}],
                                      "liabilities": [{"name": "l", "amount": 40, "current": True}],
                                      "equity": [{"name": "e", "amount": 60}]})
    assert not any(f["severity"] == "error" for f in ok.flags) and ok.metrics["current_ratio"] == 2.5
    bad = analyze_balance(None, None, {"assets": [{"name": "a", "amount": 100, "current": True}],
                                       "liabilities": [], "equity": [{"name": "e", "amount": 60}]})
    assert any(f["code"] == "balance_not_equal" for f in bad.flags)


def test_pnl_margins():
    res = analyze_pnl(None, None, {"revenue": 1000, "cost_of_sales": 600, "operating_expenses": 200, "other_income": 0,
                                   "other_expenses": 0, "tax": 40, "net_profit": 160})
    assert res.metrics["gross_margin_pct"] == 40.0 and not res.flags


def test_reports_module_flow(client, tenant_a):
    h, _ = tenant_a
    data = "2026-01-05 Оплата за товар 50 000,00\n2026-01-10 Орендна плата -12 000,00\n".encode()
    d = wait(client, h, up(client, h, data, "stmt.txt", "bank_statement"))
    assert d["view"] == "report" and d["metrics"]["total_in"] == 50000.0 and d["metrics"]["total_out"] == 12000.0


# ---------------- knowledge ----------------

def test_knowledge_ask_and_isolation(client, tenant_a):
    h, _ = tenant_a
    text = ("Порядок інкасації\n\nІнкасація виручки проводиться щодня до 18:00. Касир формує сумку, "
            "запечатує її та передає інкасатору під підпис.\n\nГенератор\n\nПри відключенні світла запустіть генератор "
            "за інструкцією на щитку.")
    r = client.post("/api/knowledge/docs", headers=h, files=[("files", ("rules.txt", io.BytesIO(text.encode()), "text/plain"))])
    assert r.status_code == 201, r.text
    a = client.post("/api/knowledge/ask", headers=h, json={"question": "Коли проводиться інкасація?"}).json()
    assert a["found"] and "інкасац" in a["answer"].lower()
    miss = client.post("/api/knowledge/ask", headers=h, json={"question": "Скільки коштує космічний корабель?"}).json()
    assert miss["found"] is False
    other, _ = make_tenant(client, "Other KB", f"kb-{uuid.uuid4().hex[:5]}@kb.com")
    assert client.post("/api/knowledge/ask", headers=other, json={"question": "інкасація"}).status_code == 403  # trial без модуля
    gaps = client.get("/api/knowledge/gaps", headers=h).json()
    assert any("космічний" in g["question"] for g in gaps["items"])


# ---------------- platform ----------------

def test_api_key_auth_and_read_only(client, tenant_a):
    h, _ = tenant_a
    full = client.post("/api/integrations/api-keys", headers=h, json={"name": "erp"}).json()["key"]
    ro = client.post("/api/integrations/api-keys", headers=h, json={"name": "ro", "read_only": True}).json()["key"]
    assert client.get("/api/docs?module=docs_extract", headers={"X-API-Key": full}).status_code == 200
    r = client.post("/api/docs", headers={"X-API-Key": full},
                    files=[("files", ("a.txt", io.BytesIO(b"Razom 10,00"), "text/plain"))], data={"doc_type": "invoice"})
    assert r.status_code == 201
    assert client.get("/api/docs?module=docs_extract", headers={"X-API-Key": ro}).status_code == 200
    assert client.post("/api/docs", headers={"X-API-Key": ro},
                       files=[("files", ("a.txt", io.BytesIO(b"x" * 30), "text/plain"))]).status_code == 403
    assert client.get("/api/docs?module=docs_extract", headers={"X-API-Key": "dm_bad_key"}).status_code == 401


def test_intake_endpoint(client, tenant_a):
    h, _ = tenant_a
    token = client.get("/api/integrations", headers=h).json()["intake_token"]
    r = client.post(f"/api/intake/{token}", files=[("files", ("inv.txt", io.BytesIO("Разом 55,00".encode()), "text/plain"))])
    assert r.status_code == 201 and len(r.json()["created"]) == 1
    assert client.post("/api/intake/wrong-token", files=[("files", ("a.txt", io.BytesIO(b"x"), "text/plain"))]).status_code == 404


def test_webhook_ssrf_and_signature(client, tenant_a, monkeypatch):
    h, _ = tenant_a
    for bad in ("http://127.0.0.1:9999/x", "http://localhost/x", "ftp://example.com", "http://169.254.169.254/latest"):
        assert client.post("/api/integrations/webhooks", headers=h, json={"url": bad}).status_code == 400
    from app.core import webhooks as wh
    sig = wh.sign("secret", b"{}")
    assert len(sig) == 64 and sig == wh.sign("secret", b"{}") and sig != wh.sign("other", b"{}")


def test_job_retry_then_fail():
    from app.core import jobs
    from app.db import SessionLocal
    from app.models import Job

    calls = []

    @jobs.handler("always_fails")
    def boom(payload):
        calls.append(1)
        raise RuntimeError("nope")

    with SessionLocal() as db:
        j = jobs.enqueue(db, "always_fails", {}, max_attempts=2)
        db.commit()
        jid = j.id
    for _ in range(2):
        for _ in range(100):  # воркер у фоні може забрати задачу раніше за нас — ок
            with SessionLocal() as db:
                st = db.get(Job, jid).status
            if st == "failed":
                break
            jobs.run_one()
            with SessionLocal() as db:  # прибираємо затримку retry для швидкого тесту
                jj = db.get(Job, jid)
                if jj.status == "queued":
                    from app.models import utcnow
                    jj.run_after = utcnow()
                    db.commit()
            time.sleep(0.02)
    with SessionLocal() as db:
        j = db.get(Job, jid)
        assert j.status == "failed" and j.attempts == 2 and "nope" in j.error


def test_login_rate_limit(client):
    email = f"rl-{uuid.uuid4().hex[:5]}@rl.com"
    for _ in range(8):
        assert client.post("/api/auth/login", json={"email": email, "password": "wrong-pass-1"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": email, "password": "wrong-pass-1"}).status_code == 429


def test_change_password(client):
    email = f"cp-{uuid.uuid4().hex[:5]}@cp.com"
    h, _ = make_tenant(client, "CP Co", email)
    assert client.post("/api/auth/change-password", headers=h,
                       json={"current_password": "bad-password", "new_password": "new-password-1"}).status_code == 400
    assert client.post("/api/auth/change-password", headers=h,
                       json={"current_password": "password-123", "new_password": "new-password-1"}).status_code == 204
    assert client.post("/api/auth/login", json={"email": email, "password": "new-password-1"}).status_code == 200


def test_trial_expiry_blocks_and_admin_extends(client, admin_h):
    from app.db import SessionLocal
    from app.models import Tenant, utcnow
    from datetime import timedelta

    h, tid = make_tenant(client, "Trial Co", f"tr-{uuid.uuid4().hex[:5]}@tr.com")
    with SessionLocal() as db:
        db.get(Tenant, tid).trial_ends_at = utcnow() - timedelta(days=1)
        db.commit()
    assert client.get("/api/docs?module=docs_extract", headers=h).status_code == 402
    client.patch(f"/api/admin/tenants/{tid}", headers=admin_h, json={"extend_trial_days": 7})
    assert client.get("/api/docs?module=docs_extract", headers=h).status_code == 200


def test_admin_reset_password_and_usage_csv(client, admin_h):
    email = f"ar-{uuid.uuid4().hex[:5]}@ar.com"
    h, tid = make_tenant(client, "AR Co", email)
    uid = client.get(f"/api/admin/tenants/{tid}/users", headers=admin_h).json()[0]["id"]
    assert client.post(f"/api/admin/users/{uid}/reset-password", headers=admin_h,
                       json={"new_password": "reset-pass-123"}).status_code == 204
    assert client.post("/api/auth/login", json={"email": email, "password": "reset-pass-123"}).status_code == 200
    assert client.get("/api/admin/usage.csv", headers=admin_h).status_code == 200
    assert "jobs" in client.get("/api/admin/health", headers=admin_h).json()
