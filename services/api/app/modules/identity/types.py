"""Документи особи: паспорт / ID-картка / довідка ІПН → картка співробітника з перевірками."""

import re
from datetime import date
from typing import Any, Dict

from sqlalchemy.orm import Session

from ..docs_extract.validators import digits, validate_ipn
from ..registry import Analysis, DocType, S, desc, enum, register
from .validators import (
    ipn_birth_date, ipn_gender, is_valid_document_number, normalize_document_number, parse_td1_mrz,
    plausible_birth_date,
)

MODULE = "identity"

PROPERTIES = {
    "document_type": enum(["passport", "id_card", "tax_certificate", "unknown"],
                          "passport — паспорт-книжечка, id_card — ID-картка, tax_certificate — довідка ІПН"),
    "last_name": desc(S, "Прізвище кирилицею"),
    "first_name": desc(S, "Ім'я кирилицею"),
    "middle_name": desc(S, "По батькові, якщо вказано"),
    "birth_date": desc(S, "Дата народження, РРРР-ММ-ДД"),
    "gender": enum(["чоловіча", "жіноча", ""], "Стать за документом"),
    "tax_id": desc(S, "ІПН, 10 цифр — довідка ІПН або зворот ID-картки"),
    "birth_place": desc(S, "Місце народження — лише паспорт"),
    "registration_address": desc(S, "Повна адреса реєстрації, як у документі"),
    "document_number": desc(S, "Серія+номер паспорта (2 кириличні літери + 6 цифр) або номер ID-картки (9 цифр)"),
    "issue_date": desc(S, "Дата видачі, РРРР-ММ-ДД"),
    "expiry_date": desc(S, "Дійсний до, РРРР-ММ-ДД (ID-картка)"),
    "issued_by": desc(S, "Орган видачі, якщо вказано"),
    "mrz": desc(S, "Сирий текст MRZ на звороті ID-картки, рядки через \\n, символ у символ; порожньо, якщо не видно"),
    "confidence": enum(["high", "medium", "low"]),
    "notes": desc(S, "Коментарі українською щодо нерозбірливих ділянок"),
}

FIELDS = [
    {"key": "last_name", "label": "Прізвище", "type": "text"},
    {"key": "first_name", "label": "Ім’я", "type": "text"},
    {"key": "middle_name", "label": "По батькові", "type": "text"},
    {"key": "birth_date", "label": "Дата народження", "type": "date"},
    {"key": "gender", "label": "Стать", "type": "text"},
    {"key": "tax_id", "label": "ІПН", "type": "text"},
    {"key": "document_number", "label": "Номер документа", "type": "text"},
    {"key": "issue_date", "label": "Дата видачі", "type": "date"},
    {"key": "expiry_date", "label": "Дійсний до", "type": "date"},
    {"key": "issued_by", "label": "Ким виданий", "type": "text"},
    {"key": "birth_place", "label": "Місце народження", "type": "text"},
    {"key": "registration_address", "label": "Адреса реєстрації", "type": "text"},
]

PROMPT = (
    "Ви — HR-асистент. Визначте тип українського документа, що встановлює особу (паспорт-книжечка, ID-картка, "
    "довідка ІПН), і витягніть дані.\n"
    "- Не вигадуйте. Поля, не властиві цьому типу документа, залишайте порожніми — це нормально.\n"
    "- Серія паспорта — кирилицею (2 літери) + 6 цифр. ID-картка — 9 цифр.\n"
    "- MRZ переписуйте символ у символ (латиниця, цифри, '<'), рядки через \\n.\n"
    "- Дати — РРРР-ММ-ДД. Коментарі — українською."
)


def _flag(code: str, sev: str, field: str, msg: str) -> dict:
    return {"code": code, "severity": sev, "field": field, "message": msg}


def analyze(db: Session, doc, data: Dict[str, Any], today: date = None) -> Analysis:
    d = dict(data)
    flags = []
    d["tax_id"] = digits(d.get("tax_id"))
    d["document_number"] = normalize_document_number(d.get("document_number", ""))

    # MRZ — надійніше за візуальне розпізнавання: значення, що пройшли контрольну цифру, виправляють поля
    mrz = parse_td1_mrz(d.get("mrz", ""), today)
    for key in ("document_number", "birth_date", "expiry_date", "gender"):
        if mrz.get(key) and d.get(key) and d[key] != mrz[key]:
            flags.append(_flag("mrz_mismatch", "warning", key,
                               f"Значення з MRZ ({mrz[key]}) відрізняється від розпізнаного ({d[key]}) — використано MRZ"))
        if mrz.get(key):
            d[key] = mrz[key]

    if d["tax_id"]:
        if not validate_ipn(d["tax_id"]):
            flags.append(_flag("tax_id_checksum", "error", "tax_id", "ІПН не проходить контрольну суму"))
        else:
            ib, ig = ipn_birth_date(d["tax_id"]), ipn_gender(d["tax_id"])
            if d.get("birth_date") and ib and ib != d["birth_date"]:
                flags.append(_flag("birth_vs_ipn", "error", "birth_date",
                                   f"Дата народження не збігається з ІПН (за ІПН: {ib})"))
            elif not d.get("birth_date") and ib:
                d["birth_date"] = ib
            if d.get("gender") and ig and ig != d["gender"]:
                flags.append(_flag("gender_vs_ipn", "warning", "gender", f"Стать не збігається з ІПН ({ig})"))
            elif not d.get("gender") and ig:
                d["gender"] = ig

    if d.get("birth_date") and not plausible_birth_date(d["birth_date"], today=today):
        flags.append(_flag("birth_implausible", "warning", "birth_date", "Вік поза очікуваним діапазоном 14–100 років"))
    if d.get("document_number") and not is_valid_document_number(d["document_number"]):
        flags.append(_flag("doc_number_format", "warning", "document_number",
                           "Номер не схожий на паспорт (2 літери + 6 цифр) чи ID-картку (9 цифр)"))
    exp = d.get("expiry_date")
    if exp and re.fullmatch(r"\d{4}-\d{2}-\d{2}", exp) and exp < (today or date.today()).isoformat():
        flags.append(_flag("expired", "error", "expiry_date", "Термін дії документа закінчився"))
    if not (d.get("last_name") and d.get("first_name")):
        flags.append(_flag("name_missing", "error", "last_name", "Не розпізнано прізвище або ім’я"))
    if d.get("document_type") == "unknown":
        flags.append(_flag("type_unknown", "warning", "document_type", "Тип документа не визначено"))
    return Analysis(data=d, flags=flags)


def index(d: Dict[str, Any]) -> Dict[str, Any]:
    name = " ".join(x for x in (d.get("last_name"), d.get("first_name"), d.get("middle_name")) if x)
    return {"name": name, "tax_id": d.get("tax_id", ""), "number": d.get("document_number", ""), "amount": 0.0}


def mock(text: str) -> Dict[str, Any]:
    def find(p: str, default: str = "") -> str:
        m = re.search(p, text, re.I)
        return m.group(1).strip() if m else default

    return {
        "document_type": "id_card", "last_name": find(r"прізвище[:\s]+(\S+)", "Шевченко"),
        "first_name": find(r"ім.я[:\s]+(\S+)", "Тарас"), "middle_name": "", "birth_date": find(r"(\d{4}-\d{2}-\d{2})", ""),
        "gender": "", "tax_id": find(r"іпн[:\s]+(\d{10})", ""), "birth_place": "", "registration_address": "",
        "document_number": find(r"номер[:\s]+(\d{9})", ""), "issue_date": "", "expiry_date": "", "issued_by": "",
        "mrz": "", "confidence": "medium", "notes": "Демо-режим: LLM_PROVIDER=mock.",
    }


register(DocType(code="identity_doc", module=MODULE, name="Документ особи", hint="Паспорт, ID-картка або довідка ІПН.",
                 properties=PROPERTIES, prompt=PROMPT, fields=FIELDS, analyze=analyze, index=index, mock=mock))
