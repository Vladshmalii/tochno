"""Детерміновані перевірки реквізитів і сум — те, що не можна довіряти LLM.

Кожна перевірка повертає список прапорців {code, severity, field, message}:
severity = error (майже точно помилка) | warning (потрібна увага) | info.
"""

import re
from datetime import datetime
from typing import Any, Dict, List, Optional

_INN_WEIGHTS = (-1, 5, 7, 9, 4, 6, 10, 5, 7)


def digits(value: Optional[str]) -> str:
    return re.sub(r"\D", "", value or "")


def validate_ipn(tax_id: str) -> bool:
    d = digits(tax_id)
    if len(d) != 10:
        return False
    return sum(int(x) * w for x, w in zip(d[:9], _INN_WEIGHTS)) % 11 % 10 == int(d[9])


def validate_edrpou(code: str) -> bool:
    d = digits(code)
    if len(d) != 8:
        return False
    nums = [int(x) for x in d]
    shifted = 30000000 <= int(d) < 60000000
    w1 = (7, 1, 2, 3, 4, 5, 6) if shifted else (1, 2, 3, 4, 5, 6, 7)
    w2 = (9, 3, 4, 5, 6, 7, 8) if shifted else (3, 4, 5, 6, 7, 8, 9)
    s = sum(n * w for n, w in zip(nums[:7], w1)) % 11
    if s >= 10:
        s = sum(n * w for n, w in zip(nums[:7], w2)) % 11
        if s >= 10:
            s = 0
    return s == nums[7]


def normalize_iban(iban: str) -> str:
    return re.sub(r"\s", "", iban or "").upper()


def validate_iban(iban: str) -> bool:
    """Структура + контрольні цифри mod-97 (ISO 13616). Для UA — довжина 29."""
    v = normalize_iban(iban)
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}", v):
        return False
    if v.startswith("UA") and len(v) != 29:
        return False
    rearranged = v[4:] + v[:4]
    num = "".join(str(int(c, 36)) for c in rearranged)
    return int(num) % 97 == 1


def parse_date(value: str) -> Optional[datetime]:
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except (TypeError, ValueError):
        return None


def _flag(code: str, severity: str, field: str, message: str) -> Dict[str, str]:
    return {"code": code, "severity": severity, "field": field, "message": message}


def validate_extraction(data: Dict[str, Any]) -> List[Dict[str, str]]:
    flags: List[Dict[str, str]] = []

    tax_id = digits(data.get("supplier_tax_id"))
    if tax_id:
        if len(tax_id) == 10 and not validate_ipn(tax_id):
            flags.append(_flag("tax_id_checksum", "error", "supplier_tax_id",
                               "ІПН не проходить перевірку контрольної суми — можлива помилка розпізнавання"))
        elif len(tax_id) == 8 and not validate_edrpou(tax_id):
            flags.append(_flag("tax_id_checksum", "error", "supplier_tax_id",
                               "ЄДРПОУ не проходить перевірку контрольної суми — можлива помилка розпізнавання"))
        elif len(tax_id) not in (8, 10):
            flags.append(_flag("tax_id_length", "error", "supplier_tax_id",
                               "ІПН/ЄДРПОУ має містити 8 або 10 цифр"))
    else:
        flags.append(_flag("tax_id_missing", "warning", "supplier_tax_id", "Не знайдено ІПН/ЄДРПОУ постачальника"))

    iban = data.get("supplier_iban") or ""
    if iban and not validate_iban(iban):
        flags.append(_flag("iban_invalid", "error", "supplier_iban",
                           "IBAN не проходить перевірку (довжина або контрольні цифри) — звірте з оригіналом"))

    for fld in ("doc_date", "due_date"):
        v = data.get(fld) or ""
        if v and parse_date(v) is None:
            flags.append(_flag("date_invalid", "warning", fld, "Дата має бути у форматі РРРР-ММ-ДД"))

    d1, d2 = parse_date(data.get("doc_date") or ""), parse_date(data.get("due_date") or "")
    if d1 and d2 and d2 < d1:
        flags.append(_flag("due_before_doc", "warning", "due_date", "Термін оплати раніше дати документа"))

    total = float(data.get("total_amount") or 0)
    if total <= 0:
        flags.append(_flag("amount_missing", "error", "total_amount", "Сума не розпізнана"))

    items = data.get("line_items") or []
    if items and total > 0:
        line_sum = round(sum(float(i.get("amount") or 0) for i in items), 2)
        vat = float(data.get("vat_amount") or 0)
        # рядки можуть бути з ПДВ або без — приймаємо обидва варіанти
        if abs(line_sum - total) > 0.05 and abs(line_sum + vat - total) > 0.05:
            flags.append(_flag("sum_mismatch", "warning", "total_amount",
                               f"Сума рядків ({line_sum:.2f}) не збігається із підсумком ({total:.2f})"))

    return flags
