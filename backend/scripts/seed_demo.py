"""Демо-наповнення: тенант Business з користувачами, контрагентами, документами всіх модулів,
базою знань та журналом. Ідемпотентно: повторний запуск нічого не дублює.

    cd backend && ../.venv/Scripts/python -m scripts.seed_demo
Вхід: demo@tochno.app / Demo12345!   (власник), viewer@tochno.app / Demo12345!
"""

import random
import secrets
from datetime import timedelta

from sqlalchemy import select

from app.db import Base, SessionLocal, engine
from app.main import seed
from app.models import (AuditLog, ChatLog, Contractor, Document, Plan, Tenant, UsageEvent, User, utcnow)
from app.modules import registry
from app.modules.docs_extract.pipeline import apply_analysis
from app.modules.knowledge.engine import index_document
from app.security import hash_password

PASSWORD = "Demo12345!"
SUPPLIERS = [  # name, ЄДРПОУ (валідний за контрольною сумою перевіряє validators), IBAN
    ("ТОВ «Укрпостач Плюс»", "32855961", "UA213223130000026007233566001"),
    ("ТОВ «Агро-Інвест»", "37193418", "UA903052990000026001030123456"),
    ("ФОП Коваленко О. І.", "2873412345", "UA573543470000026000300456789"),
    ("ТОВ «Логістик Груп»", "41278506", "UA463052990000026005050123987"),
    ("ПП «Офіс-Сервіс»", "30112345", "UA233052990000026003040111222"),
    ("ТОВ «Софтлайн Україна»", "35672109", "UA583220010000026009100987654"),
]
KB = [
    ("Регламент погодження рахунків",
     "Рахунки до 20 000 грн погоджує головний бухгалтер протягом 2 робочих днів. Рахунки від 20 000 до 100 000 грн "
     "погоджує фінансовий директор. Понад 100 000 грн потрібен підпис генерального директора. Оплата здійснюється "
     "по вівторках і четвергах. Рахунки без договору не оплачуються."),
    ("Інструкція з авансових звітів",
     "Авансовий звіт подається протягом 5 робочих днів після повернення з відрядження. До звіту додаються квитки, "
     "чеки та рахунки готелю. Добові виплачуються за ставкою 600 грн на добу по Україні. Звіт перевіряє бухгалтер "
     "і передає на затвердження керівнику відділу."),
    ("Робота з ПДВ-накладними",
     "Податкові накладні реєструються в ЄРПН протягом 15 календарних днів з дати складання. Відповідальний — "
     "бухгалтер з податкового обліку. Прострочена реєстрація тягне штраф від 10% до 50% суми ПДВ."),
]
QUESTIONS = [
    ("Хто погоджує рахунок на 50 000 грн?", "Рахунки від 20 000 до 100 000 грн погоджує фінансовий директор.", True),
    ("Скільки днів на авансовий звіт?", "Авансовий звіт подається протягом 5 робочих днів після повернення.", True),
    ("Який розмір премії за квартал?", "", False),
]


def get_or_create_user(db, tenant, email, name, role):
    u = db.scalar(select(User).where(User.email == email))
    if not u:
        u = User(tenant_id=tenant.id, email=email, full_name=name, role=role, password_hash=hash_password(PASSWORD),
                 last_login_at=utcnow() - timedelta(hours=random.randint(1, 48)))
        db.add(u)
        db.flush()
    return u


def add_doc(db, tenant, user, doc_type, text, days_ago, status, filename):
    dt = registry.get(doc_type)
    d = Document(tenant_id=tenant.id, created_by=user.id, filename=filename, media_type="application/pdf",
                 size=random.randint(40_000, 900_000), module=dt.module, doc_type=doc_type, status="review",
                 created_at=utcnow() - timedelta(days=days_ago, hours=random.randint(0, 8)))
    db.add(d)
    db.flush()
    data = dt.mock(text)
    apply_analysis(db, d, data)
    d.confidence = data.get("confidence") or random.choice(["high", "high", "medium", "low"])
    d.status = status
    d.updated_at = d.created_at + timedelta(minutes=2)
    if status == "approved":
        d.approved_by, d.approved_at = user.id, d.created_at + timedelta(hours=random.randint(1, 30))
    if status == "failed":
        d.error, d.extracted, d.flags = "Не вдалося розпізнати документ: низька якість скану", None, []
    db.add(UsageEvent(tenant_id=tenant.id, kind="doc_processed", tokens_in=random.randint(1500, 5000),
                      tokens_out=random.randint(300, 900), created_at=d.created_at))
    db.flush()
    return d


def main() -> None:
    random.seed(7)
    registry.load_all()
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed(db)
        if db.scalar(select(Tenant).where(Tenant.slug == "demo-company")):
            print("Демо-дані вже є — нічого не робимо.")
            return
        plan = db.scalar(select(Plan).where(Plan.code == "business"))
        tenant = Tenant(name="ТОВ «Демо Компані»", slug="demo-company", plan_id=plan.id, contact_email="demo@tochno.app",
                        intake_token=secrets.token_urlsafe(24), created_at=utcnow() - timedelta(days=60),
                        settings={"auto_approve_clean": False})
        db.add(tenant)
        db.flush()
        owner = get_or_create_user(db, tenant, "demo@tochno.app", "Олена Бондаренко", "owner")
        acc = get_or_create_user(db, tenant, "accountant@tochno.app", "Максим Литвин", "accountant")
        get_or_create_user(db, tenant, "viewer@tochno.app", "Ірина Шевчук", "viewer")

        # Другий тенант на Trial — для адмінки платформи
        trial = db.scalar(select(Plan).where(Plan.code == "trial"))
        t2 = Tenant(name="ФОП Мельник", slug="fop-melnyk", plan_id=trial.id, contact_email="melnyk@example.com",
                    intake_token=secrets.token_urlsafe(24), trial_ends_at=utcnow() + timedelta(days=9),
                    created_at=utcnow() - timedelta(days=5))
        db.add(t2)
        db.flush()
        get_or_create_user(db, t2, "melnyk@example.com", "Петро Мельник", "owner")

        for name, tax, iban in SUPPLIERS[:5]:  # 6-й навмисно відсутній у довіднику → «новий контрагент»
            db.add(Contractor(tenant_id=tenant.id, name=name, tax_id=tax, iban=iban))
        db.flush()

        kinds = ["invoice"] * 7 + ["act"] * 3 + ["waybill"] * 2 + ["payment_order"]
        statuses = ["approved"] * 6 + ["review"] * 4 + ["rejected", "failed"]
        n = 0
        for i, (kind, status) in enumerate(zip(kinds, statuses + ["review"])):
            name, tax, iban = SUPPLIERS[i % len(SUPPLIERS)]
            amount = round(random.uniform(1800, 96000), 2)
            text = (f"Рахунок №{100 + i}\nПостачальник: {name}\nЄДРПОУ: {tax}\n{iban}\nПокупець: ТОВ «Демо Компані»\n"
                    f"Дата 2026-{random.randint(8, 10):02d}-{random.randint(1, 28):02d}\nРазом до сплати: {amount:,.2f}"
                    .replace(",", " ", 1))
            if i == 4:  # підміна IBAN → попередження
                text = text.replace(iban, "UA133052990000026001999888777")
            if i == 6:  # неправильний ІПН → помилка валідації
                text = text.replace(tax, "12345678")
            add_doc(db, tenant, acc if i % 2 else owner, kind, text, days_ago=60 - i * 4, status=status,
                    filename=f"{kind}_{100 + i}.pdf")
            n += 1
        # дубль рахунку
        add_doc(db, tenant, acc, "invoice", "Рахунок №100\nПостачальник: ТОВ «Укрпостач Плюс»\nЄДРПОУ: 32855961\n"
                "Разом до сплати: 1 200,00", 2, "review", "invoice_100_copy.pdf")

        for doc_type, fn in [("bank_statement", "виписка_жовтень.pdf"), ("balance_sheet", "баланс_Q3.pdf"),
                             ("income_statement", "опу_Q3.pdf")]:
            add_doc(db, tenant, owner, doc_type, "", 6, "approved" if doc_type != "bank_statement" else "review", fn)
        for i in range(3):
            add_doc(db, tenant, owner, "identity_doc", "", 20 - i * 5, ["approved", "review", "review"][i],
                    f"passport_{i + 1}.jpg")

        for title, text in KB:
            index_document(db, tenant.id, title, f"{title}.txt", text)
        for q, a, found in QUESTIONS:
            db.add(ChatLog(tenant_id=tenant.id, user_id=owner.id, question=q, answer=a or "У базі знань не знайдено "
                           "відповіді на це питання.", found=found, sources=[KB[0][0]] if found else [],
                           feedback=1 if found else None, created_at=utcnow() - timedelta(days=random.randint(0, 9))))
        for action in ("auth.login", "doc.upload", "doc.approve", "settings.update"):
            db.add(AuditLog(tenant_id=tenant.id, user_id=owner.id, action=action, entity="document",
                            created_at=utcnow() - timedelta(hours=random.randint(1, 200))))
        db.commit()
        print(f"Готово: тенант «{tenant.name}», {n + 8} документів. Вхід: demo@tochno.app / {PASSWORD}")


if __name__ == "__main__":
    main()
