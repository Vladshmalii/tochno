"""Первинні документи: рахунок, акт, накладна, платіжка, інше."""

import re
from typing import Any, Dict

from sqlalchemy.orm import Session

from ..registry import Analysis, DocType, N, S, arr, desc, enum, register
from .matching import find_anomalies, match_contractor
from .validators import digits, normalize_iban, validate_extraction

MODULE = "docs_extract"
CODES = ["invoice", "act", "waybill", "payment_order", "other"]

PROPERTIES = {
    "detected_type": enum(CODES, "Який це тип документа насправді"),
    "supplier_name": desc(S, "Постачальник/отримувач коштів — назва компанії чи ФОП"),
    "supplier_tax_id": desc(S, "ІПН або ЄДРПОУ постачальника, лише цифри"),
    "supplier_iban": desc(S, "IBAN постачальника (UA + 27 цифр), якщо вказано"),
    "buyer_name": desc(S, "Покупець/платник, якщо вказано"),
    "buyer_tax_id": desc(S, "ІПН/ЄДРПОУ покупця, якщо вказано"),
    "doc_number": desc(S, "Номер документа (НЕ банківський рахунок)"),
    "doc_date": desc(S, "Дата документа, РРРР-ММ-ДД"),
    "due_date": desc(S, "Термін оплати, РРРР-ММ-ДД, якщо вказано"),
    "currency": desc(S, "Валюта, ISO (UAH за замовчуванням)"),
    "total_amount": desc(N, "Підсумок до сплати з ПДВ"),
    "vat_amount": desc(N, "Сума ПДВ, 0 якщо немає"),
    "payment_purpose": desc(S, "Призначення платежу"),
    "line_items": arr({"description": S, "quantity": N, "unit_price": N, "amount": N}, "Рядки документа"),
    "confidence": enum(["high", "medium", "low"]),
    "notes": desc(S, "Коментарі щодо неточностей, українською"),
}

FIELDS = [
    {"key": "supplier_name", "label": "Постачальник", "type": "text"},
    {"key": "supplier_tax_id", "label": "ІПН / ЄДРПОУ", "type": "text"},
    {"key": "supplier_iban", "label": "IBAN", "type": "text"},
    {"key": "doc_number", "label": "Номер документа", "type": "text"},
    {"key": "doc_date", "label": "Дата документа", "type": "date"},
    {"key": "due_date", "label": "Термін оплати", "type": "date"},
    {"key": "total_amount", "label": "Сума до сплати", "type": "number"},
    {"key": "vat_amount", "label": "у т.ч. ПДВ", "type": "number"},
    {"key": "currency", "label": "Валюта", "type": "text"},
    {"key": "buyer_name", "label": "Покупець / платник", "type": "text"},
    {"key": "payment_purpose", "label": "Призначення платежу", "type": "text"},
]

PROMPT = (
    "Ви — асистент бухгалтера. Проаналізуйте ВСІ надані файли/сторінки як ОДИН документ і поверніть "
    "структуровані дані.\n"
    "Правила:\n"
    "- Не вигадуйте значень. Якщо поля немає або воно нерозбірливе — порожній рядок або 0.\n"
    "- Номер документа (doc_number) — це номер самого рахунку/акта; не плутайте його з банківським "
    "рахунком (IBAN) — слово «рахунок» часто означає саме IBAN.\n"
    "- Дати — РРРР-ММ-ДД. Суми — числом з копійками, без пробілів і валюти.\n"
    "- ІПН/ЄДРПОУ — лише цифри.\n"
    "- Усі коментарі в notes — українською.\n"
)


def normalize(data: Dict[str, Any]) -> Dict[str, Any]:
    d = dict(data)
    d["supplier_tax_id"] = digits(d.get("supplier_tax_id"))
    d["buyer_tax_id"] = digits(d.get("buyer_tax_id"))
    d["supplier_iban"] = normalize_iban(d.get("supplier_iban") or "")
    d["currency"] = (d.get("currency") or "UAH").upper()
    d["total_amount"] = float(d.get("total_amount") or 0)
    d["vat_amount"] = float(d.get("vat_amount") or 0)
    d["line_items"] = d.get("line_items") or []
    return d


def analyze(db: Session, doc, data: Dict[str, Any]) -> Analysis:
    data = normalize(data)
    flags = validate_extraction(data)
    match = match_contractor(db, doc.tenant_id, data.get("supplier_name", ""), data.get("supplier_tax_id", ""))
    flags += find_anomalies(db, doc, data, match)
    return Analysis(data=data, flags=flags, match=match)


def index(d: Dict[str, Any]) -> Dict[str, Any]:
    return {"name": d.get("supplier_name", ""), "tax_id": d.get("supplier_tax_id", ""),
            "number": d.get("doc_number", ""), "amount": float(d.get("total_amount") or 0)}


def mock(text: str) -> Dict[str, Any]:
    def find(pattern: str, default: str = "") -> str:
        m = re.search(pattern, text, re.I)
        return m.group(1).strip() if m else default

    amount = find(r"(?:разом|всього|до сплати|total)[^\d]{0,20}([\d\s]+[.,]\d{2})")
    amount_f = float(re.sub(r"\s", "", amount).replace(",", ".")) if amount else 1200.00
    return {
        "detected_type": "invoice",
        "supplier_name": find(r"(?:постачальник|отримувач|supplier)[:\s]+([^\n|]+)", "ТОВ «Демо Постачальник»"),
        "supplier_tax_id": find(r"(?:єдрпоу|ipn|іпн|інн)[:\s]+(\d{8,10})", "32855961"),
        "supplier_iban": find(r"(UA\d{27})", ""),
        "buyer_name": find(r"(?:покупець|платник|buyer)[:\s]+([^\n|]+)", ""),
        "buyer_tax_id": "",
        "doc_number": find(r"(?:рахунок|акт|накладна)[^\n\d№]{0,20}№\s*([\w/-]+)", "DEMO-1"),
        "doc_date": find(r"(\d{4}-\d{2}-\d{2})", ""),
        "due_date": "", "currency": "UAH", "total_amount": amount_f, "vat_amount": round(amount_f / 6, 2),
        "payment_purpose": "Оплата за рахунком (демо-розпізнавання)",
        "line_items": [{"description": "Послуги", "quantity": 1, "unit_price": amount_f, "amount": amount_f}],
        "confidence": "medium",
        "notes": "Демо-режим: LLM_PROVIDER=mock. Підключіть OpenAI для реального розпізнавання.",
    }


_NAMES = {
    "invoice": ("Рахунок на оплату", "Рахунок-фактура / рахунок на оплату від постачальника."),
    "act": ("Акт виконаних робіт", "Акт наданих послуг або виконаних робіт."),
    "waybill": ("Видаткова накладна", "Видаткова або товарно-транспортна накладна."),
    "payment_order": ("Платіжне доручення", "Платіжне доручення / банківська квитанція."),
    "other": ("Інший документ", "Невизначений тип первинного документа — визначте тип самостійно."),
}

for _code, (_name, _hint) in _NAMES.items():
    register(DocType(code=_code, module=MODULE, name=_name, hint=_hint, properties=PROPERTIES, prompt=PROMPT,
                     fields=FIELDS, analyze=analyze, index=index, mock=mock))
