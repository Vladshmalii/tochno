"""Звірка постачальника з довідником контрагентів + виявлення дублікатів і зміни IBAN.

Пріоритет — точний збіг за ІПН/ЄДРПОУ; fuzzy-звірка лише за назвою ризикує
зматчити схожу, але іншу компанію, тому вона завжди лише підказка."""

import re
from typing import Any, Dict, List, Optional

from rapidfuzz import fuzz, process
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import Contractor, Document
from .validators import digits, normalize_iban

_LEGAL_FORMS = {"тов", "пп", "фоп", "прат", "пат", "тдв", "кп", "дп", "ооо", "ллс", "приватне", "підприємство"}
MATCH_THRESHOLD = 80.0


def normalize_name(name: str) -> str:
    t = (name or "").lower().replace("'", "").replace("’", "")
    t = re.sub(r"[^\w\s]", " ", t)
    return " ".join(w for w in t.split() if w not in _LEGAL_FORMS)


def match_contractor(db: Session, tenant_id: int, name: str, tax_id: str) -> Dict[str, Any]:
    rows: List[Contractor] = list(db.scalars(select(Contractor).where(Contractor.tenant_id == tenant_id)))
    if not rows:
        return {"status": "no_directory", "score": 0}

    tid = digits(tax_id)
    if tid:
        exact = [r for r in rows if digits(r.tax_id) == tid]
        if len(exact) == 1:
            r = exact[0]
            return {"status": "matched", "contractor_id": r.id, "name": r.name, "tax_id": r.tax_id,
                    "iban": r.iban, "score": 100}
        if len(exact) > 1:
            return {"status": "ambiguous", "score": 100}

    norm = normalize_name(name)
    if not norm:
        return {"status": "not_found", "score": 0}
    names = [normalize_name(r.name) for r in rows]
    top = process.extract(norm, names, scorer=fuzz.WRatio, limit=2)
    if not top or top[0][1] < MATCH_THRESHOLD:
        return {"status": "not_found", "score": round(top[0][1], 1) if top else 0}
    if len(top) > 1 and top[0][1] - top[1][1] < 5:
        return {"status": "ambiguous", "score": round(top[0][1], 1)}
    r = rows[top[0][2]]
    return {"status": "suggested", "contractor_id": r.id, "name": r.name, "tax_id": r.tax_id,
            "iban": r.iban, "score": round(top[0][1], 1)}


def find_anomalies(db: Session, doc: Document, data: Dict[str, Any], match: Optional[Dict[str, Any]]) -> List[dict]:
    flags: List[dict] = []
    tax = digits(data.get("supplier_tax_id"))
    number = (data.get("doc_number") or "").strip()
    amount = float(data.get("total_amount") or 0)

    if number and (tax or data.get("supplier_name")):
        q = select(Document).where(
            Document.tenant_id == doc.tenant_id, Document.id != doc.id, Document.doc_number == number,
            Document.status.in_(("review", "approved")),
        )
        q = q.where(Document.supplier_tax_id == tax) if tax else q.where(Document.supplier_name == data["supplier_name"])
        dup = db.scalars(q.limit(1)).first()
        if dup:
            flags.append({"code": "duplicate", "severity": "error", "field": "doc_number",
                          "message": f"Схоже на дублікат: документ №{number} цього постачальника вже є (id {dup.id})"
                                     + (" на ту саму суму" if abs(dup.amount - amount) < 0.01 else "")})

    if match and match.get("status") in ("matched", "suggested") and match.get("iban"):
        new_iban = normalize_iban(data.get("supplier_iban") or "")
        if new_iban and new_iban != normalize_iban(match["iban"]):
            flags.append({"code": "iban_changed", "severity": "error", "field": "supplier_iban",
                          "message": "IBAN відрізняється від збереженого в довіднику — перевірте перед оплатою "
                                     "(типова схема шахрайства: підміна реквізитів)"})
    return flags
