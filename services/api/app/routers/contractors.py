import csv
import io
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import audit, require_module, require_roles
from ..models import Contractor, User
from ..modules.docs_extract.validators import digits, normalize_iban

router = APIRouter(prefix="/api/contractors", tags=["contractors"])

can_view = require_module("reconcile")
can_edit = require_roles("owner", "accountant")


class ContractorIn(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    tax_id: str = ""
    iban: str = ""


def _out(c: Contractor) -> dict:
    return {"id": c.id, "name": c.name, "tax_id": c.tax_id, "iban": c.iban}


def _guard(user: User) -> None:
    # редагування — тільки з підключеним модулем, ролі перевіряє can_edit
    if "reconcile" not in user.tenant.enabled_modules():
        raise HTTPException(403, "Модуль 'reconcile' не підключено до вашого тарифу")


@router.get("")
def list_contractors(q: Optional[str] = None, user: User = Depends(can_view), db: Session = Depends(get_db)):
    stmt = select(Contractor).where(Contractor.tenant_id == user.tenant_id)
    if q:
        stmt = stmt.where(Contractor.name.ilike(f"%{q}%") | Contractor.tax_id.ilike(f"%{q}%"))
    return [_out(c) for c in db.scalars(stmt.order_by(Contractor.name).limit(500))]


@router.post("", status_code=201)
def create(body: ContractorIn, user: User = Depends(can_edit), db: Session = Depends(get_db)):
    _guard(user)
    c = Contractor(tenant_id=user.tenant_id, name=body.name.strip(), tax_id=digits(body.tax_id),
                   iban=normalize_iban(body.iban))
    db.add(c)
    audit(db, user, "contractor.create", "contractor", body.name)
    db.commit()
    return _out(c)


@router.put("/{cid}")
def update(cid: int, body: ContractorIn, user: User = Depends(can_edit), db: Session = Depends(get_db)):
    _guard(user)
    c = db.get(Contractor, cid)
    if not c or c.tenant_id != user.tenant_id:
        raise HTTPException(404, "Контрагента не знайдено")
    c.name, c.tax_id, c.iban = body.name.strip(), digits(body.tax_id), normalize_iban(body.iban)
    audit(db, user, "contractor.update", "contractor", cid)
    db.commit()
    return _out(c)


@router.delete("/{cid}", status_code=204)
def delete(cid: int, user: User = Depends(can_edit), db: Session = Depends(get_db)):
    _guard(user)
    c = db.get(Contractor, cid)
    if not c or c.tenant_id != user.tenant_id:
        raise HTTPException(404, "Контрагента не знайдено")
    db.delete(c)
    audit(db, user, "contractor.delete", "contractor", cid)
    db.commit()


_NAME = ("назва", "контрагент", "name", "постачальник", "отримувач")
_TAX = ("єдрпоу", "едрпоу", "інн", "ipn", "tax")
_IBAN = ("iban", "рахунок")


def _col(headers: List[str], keys) -> Optional[int]:
    for i, h in enumerate(headers):
        if any(k in h.strip().lower() for k in keys):
            return i
    return None


@router.post("/import")
async def import_csv(file: UploadFile = File(...), user: User = Depends(can_edit), db: Session = Depends(get_db)):
    """Імпорт CSV (UTF-8/CP1251; роздільник , або ;). Колонки визначаються за назвою заголовка."""
    _guard(user)
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1251", errors="ignore")
    try:
        dialect = csv.Sniffer().sniff(text[:2048], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.reader(io.StringIO(text), dialect))
    if len(rows) < 2:
        raise HTTPException(400, "У файлі немає даних")
    ni, ti, ii = _col(rows[0], _NAME), _col(rows[0], _TAX), _col(rows[0], _IBAN)
    if ni is None:
        raise HTTPException(400, "Не знайдено колонку з назвою контрагента (напр. «Назва»)")

    existing = {(c.tax_id, c.name.lower()) for c in db.scalars(select(Contractor).where(
        Contractor.tenant_id == user.tenant_id))}
    added = skipped = 0
    for r in rows[1:]:
        if len(r) <= ni or not r[ni].strip():
            continue
        name = r[ni].strip()
        tax = digits(r[ti]) if ti is not None and len(r) > ti else ""
        iban = normalize_iban(r[ii]) if ii is not None and len(r) > ii else ""
        if (tax, name.lower()) in existing:
            skipped += 1
            continue
        existing.add((tax, name.lower()))
        db.add(Contractor(tenant_id=user.tenant_id, name=name, tax_id=tax, iban=iban))
        added += 1
    audit(db, user, "contractor.import", "contractor", "", {"added": added, "skipped": skipped})
    db.commit()
    return {"added": added, "skipped": skipped}
