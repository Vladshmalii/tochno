import csv
import io
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..core.jobs import enqueue
from ..core.storage import get_storage
from ..core.webhooks import emit
from ..db import get_db
from ..deps import audit, current_tenant_user
from ..models import Document, User, utcnow
from ..modules import registry
from ..modules.docs_extract.pipeline import _event, apply_analysis

router = APIRouter(prefix="/api/docs", tags=["documents"])

ALLOWED_EXT = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".docx", ".doc", ".xlsx", ".xls", ".txt", ".csv"}
MEDIA_BY_EXT = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".webp": "image/webp"}
DOC_MODULES = ("docs_extract", "identity", "reports")
WRITE_ROLES = ("owner", "accountant")


def month_start() -> datetime:
    return utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def docs_used(db: Session, tenant_id: int) -> int:
    return db.scalar(select(func.count(Document.id)).where(
        Document.tenant_id == tenant_id, Document.created_at >= month_start())) or 0


def access(user: User, module: str, write: bool = False) -> None:
    if module not in DOC_MODULES:
        raise HTTPException(400, "Невідомий модуль")
    if module not in user.tenant.enabled_modules():
        raise HTTPException(403, f"Модуль '{module}' не підключено до вашого тарифу")
    if write and user.role not in WRITE_ROLES:
        raise HTTPException(403, "Недостатньо прав")


def doc_out(d: Document, full: bool = False) -> Dict[str, Any]:
    out = {
        "id": d.id, "module": d.module, "filename": d.filename, "doc_type": d.doc_type, "status": d.status,
        "confidence": d.confidence, "supplier_name": d.supplier_name, "doc_number": d.doc_number, "amount": d.amount,
        "currency": (d.extracted or {}).get("currency", ""), "created_at": d.created_at,
        "flag_count": len(d.flags or []), "error_count": sum(1 for f in (d.flags or []) if f["severity"] == "error"),
        "match_status": (d.match or {}).get("status"), "error": d.error,
    }
    if full:
        dt = registry.get(d.doc_type)
        out.update({"extracted": d.extracted, "flags": d.flags or [], "match": d.match, "metrics": d.metrics,
                    "description": d.description, "media_type": d.media_type, "size": d.size,
                    "approved_at": d.approved_at, "fields": dt.fields if dt else [], "view": dt.view if dt else "form"})
    return out


def _get(db: Session, user: User, doc_id: int, write: bool = False) -> Document:
    d = db.get(Document, doc_id)
    if not d or d.tenant_id != user.tenant_id:  # чужі документи не розкриваємо навіть фактом існування
        raise HTTPException(404, "Документ не знайдено")
    access(user, d.module, write)
    return d


def ingest(db: Session, user: User, items: List[Tuple[str, str, bytes]], doc_type: str,
           description: str = "") -> List[Document]:
    """Спільна логіка створення документів (веб-завантаження та intake-вебхук)."""
    s = get_settings()
    dt = registry.get(doc_type)
    if dt is None:
        raise HTTPException(400, "Невідомий тип документа")
    access(user, dt.module, write=True)
    limit = user.tenant.doc_limit()
    if limit and docs_used(db, user.tenant_id) + len(items) > limit:
        raise HTTPException(402, f"Вичерпано місячний ліміт документів ({limit}). Оновіть тариф.")
    created: List[Document] = []
    for filename, content_type, raw in items:
        ext = Path(filename or "").suffix.lower()
        if ext not in ALLOWED_EXT:
            raise HTTPException(400, f"Непідтримуваний формат файлу: {filename}")
        if len(raw) > s.max_upload_mb * 1024 * 1024:
            raise HTTPException(413, f"Файл {filename} більший за {s.max_upload_mb} МБ")
        if not raw:
            raise HTTPException(400, f"Файл {filename} порожній")
        key = get_storage().save(user.tenant_id, ext, raw)
        d = Document(tenant_id=user.tenant_id, created_by=user.id, filename=Path(filename).name[:300],
                     media_type=content_type or MEDIA_BY_EXT.get(ext, "application/octet-stream"), size=len(raw),
                     storage_path=key, module=dt.module, doc_type=doc_type, description=description, status="queued")
        db.add(d)
        created.append(d)
    db.flush()
    for d in created:
        enqueue(db, "process_document", {"doc_id": d.id})
    audit(db, user, "doc.upload", "document", ",".join(str(d.id) for d in created))
    db.commit()
    return created


@router.get("/types")
def types(module: str, user: User = Depends(current_tenant_user)):
    access(user, module)
    return [t.public() for t in registry.for_module(module)]


@router.post("", status_code=201)
async def upload(
    files: List[UploadFile] = File(...),
    doc_type: str = Form("invoice"),
    description: str = Form(""),
    user: User = Depends(current_tenant_user),
    db: Session = Depends(get_db),
):
    items = [(f.filename or "file", f.content_type or "", await f.read()) for f in files]
    return [doc_out(d) for d in ingest(db, user, items, doc_type, description)]


@router.get("")
def list_docs(
    module: str,
    status: Optional[str] = None,
    q: Optional[str] = None,
    doc_type: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    user: User = Depends(current_tenant_user),
    db: Session = Depends(get_db),
):
    access(user, module)
    cond = [Document.tenant_id == user.tenant_id, Document.module == module]
    if status:
        cond.append(Document.status == status)
    if doc_type:
        cond.append(Document.doc_type == doc_type)
    if q:
        like = f"%{q}%"
        cond.append(or_(Document.filename.ilike(like), Document.supplier_name.ilike(like),
                        Document.doc_number.ilike(like), Document.supplier_tax_id.ilike(like)))
    total = db.scalar(select(func.count(Document.id)).where(*cond)) or 0
    rows = db.scalars(select(Document).where(*cond).order_by(Document.id.desc())
                      .offset((page - 1) * page_size).limit(page_size))
    return {"total": total, "page": page, "page_size": page_size, "items": [doc_out(d) for d in rows]}


@router.get("/stats")
def stats(module: str, user: User = Depends(current_tenant_user), db: Session = Depends(get_db)):
    access(user, module)
    base = [Document.tenant_id == user.tenant_id, Document.module == module]
    by_status = dict(db.execute(select(Document.status, func.count(Document.id)).where(*base)
                                .group_by(Document.status)).all())
    approved_sum = db.scalar(select(func.coalesce(func.sum(Document.amount), 0)).where(
        *base, Document.status == "approved", Document.created_at >= month_start()))
    return {"by_status": by_status, "approved_amount_month": approved_sum,
            "docs_used_month": docs_used(db, user.tenant_id), "docs_limit": user.tenant.doc_limit()}


@router.get("/export.csv")
def export_csv(module: str, user: User = Depends(current_tenant_user), db: Session = Depends(get_db)):
    access(user, module)
    cols: Dict[str, str] = {}
    for t in registry.for_module(module):
        for f in t.fields:
            cols.setdefault(f["key"], f["label"])
    rows = db.scalars(select(Document).where(Document.tenant_id == user.tenant_id, Document.module == module,
                                             Document.status == "approved").order_by(Document.id))
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["id", "тип"] + list(cols.values()))
    for d in rows:
        e = d.extracted or {}
        w.writerow([d.id, d.doc_type] + [e.get(k, "") for k in cols])
    # BOM, щоб Excel коректно відкрив кирилицю
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{module}.csv"'})


@router.get("/export.xlsx")
def export_xlsx(module: str, user: User = Depends(current_tenant_user), db: Session = Depends(get_db)):
    access(user, module)
    import openpyxl

    cols: Dict[str, str] = {}
    for t in registry.for_module(module):
        for f in t.fields:
            cols.setdefault(f["key"], f["label"])
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = module
    ws.append(["id", "тип"] + list(cols.values()))
    rows = db.scalars(select(Document).where(Document.tenant_id == user.tenant_id, Document.module == module,
                                             Document.status == "approved").order_by(Document.id))
    for d in rows:
        e = d.extracted or {}
        ws.append([d.id, d.doc_type] + [e.get(k, "") for k in cols])
    buf = io.BytesIO()
    wb.save(buf)
    return Response(buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{module}.xlsx"'})


@router.get("/next")
def next_in_queue(module: str, after: int = 0, user: User = Depends(current_tenant_user),
                  db: Session = Depends(get_db)):
    """Наступний документ на перевірці (за зростанням id після поточного, інакше найстаріший) — для конвеєра перевірки."""
    access(user, module)
    base = [Document.tenant_id == user.tenant_id, Document.module == module, Document.status == "review"]
    d = db.scalar(select(Document).where(*base, Document.id > after).order_by(Document.id).limit(1))         or db.scalar(select(Document).where(*base, Document.id != after).order_by(Document.id).limit(1))
    return {"id": d.id if d else None}


class BulkIn(BaseModel):
    ids: List[int] = Field(min_length=1, max_length=200)


@router.post("/bulk-approve")
def bulk_approve(body: BulkIn, user: User = Depends(current_tenant_user), db: Session = Depends(get_db)):
    """Затверджує вибрані документи на перевірці БЕЗ критичних попереджень; решту повертає як пропущені."""
    approved, skipped = [], []
    for doc_id in dict.fromkeys(body.ids):
        d = db.get(Document, doc_id)
        if not d or d.tenant_id != user.tenant_id:
            skipped.append({"id": doc_id, "reason": "не знайдено"})
            continue
        access(user, d.module, write=True)
        if d.status != "review":
            skipped.append({"id": doc_id, "reason": "не на перевірці"})
        elif any(f["severity"] == "error" for f in (d.flags or [])):
            skipped.append({"id": doc_id, "reason": "є критичні попередження"})
        else:
            d.status, d.approved_by, d.approved_at = "approved", user.id, utcnow()
            emit(db, d.tenant_id, "document.approved", _event(d))
            approved.append(doc_id)
    audit(db, user, "doc.bulk_approve", "document", ",".join(map(str, approved)))
    db.commit()
    return {"approved": approved, "skipped": skipped}


@router.get("/{doc_id}")
def get_doc(doc_id: int, user: User = Depends(current_tenant_user), db: Session = Depends(get_db)):
    return doc_out(_get(db, user, doc_id), full=True)


@router.get("/{doc_id}/file")
def get_file(doc_id: int, user: User = Depends(current_tenant_user), db: Session = Depends(get_db)):
    d = _get(db, user, doc_id)
    st = get_storage()
    if not st.exists(d.storage_path):
        raise HTTPException(404, "Файл відсутній у сховищі")
    safe = re.sub(r"[^\w.\- ]", "_", d.filename)
    return Response(st.read(d.storage_path), media_type=d.media_type,
                    headers={"Content-Disposition": f'inline; filename="{safe}"',
                             "X-Content-Type-Options": "nosniff"})


class DocPatch(BaseModel):
    extracted: Dict[str, Any]
    doc_type: Optional[str] = None


@router.patch("/{doc_id}")
def edit_doc(doc_id: int, body: DocPatch, user: User = Depends(current_tenant_user), db: Session = Depends(get_db)):
    d = _get(db, user, doc_id, write=True)
    if d.status not in ("review", "rejected", "failed"):
        raise HTTPException(409, "Редагувати можна лише документ на перевірці")
    if body.doc_type:
        nt = registry.get(body.doc_type)
        if nt is None or nt.module != d.module:
            raise HTTPException(400, "Невідомий тип документа")
        d.doc_type = body.doc_type
    allowed = registry.get(d.doc_type).properties
    merged = {**(d.extracted or {}), **{k: v for k, v in body.extracted.items() if k in allowed}}
    apply_analysis(db, d, merged)
    if d.status == "failed":
        d.status, d.error = "review", ""
    audit(db, user, "doc.edit", "document", d.id)
    db.commit()
    return doc_out(d, full=True)


@router.post("/{doc_id}/approve")
def approve(doc_id: int, force: bool = False, user: User = Depends(current_tenant_user),
            db: Session = Depends(get_db)):
    d = _get(db, user, doc_id, write=True)
    if d.status != "review":
        raise HTTPException(409, "Затвердити можна лише документ на перевірці")
    errors = [f for f in (d.flags or []) if f["severity"] == "error"]
    if errors and not force:
        raise HTTPException(422, {"message": "Є критичні попередження — виправте або підтвердьте явно (force=true)",
                                  "flags": errors})
    d.status, d.approved_by, d.approved_at = "approved", user.id, utcnow()
    audit(db, user, "doc.approve", "document", d.id, {"forced": bool(errors)})
    emit(db, d.tenant_id, "document.approved", _event(d))
    db.commit()
    return doc_out(d, full=True)


@router.post("/{doc_id}/reject")
def reject(doc_id: int, user: User = Depends(current_tenant_user), db: Session = Depends(get_db)):
    d = _get(db, user, doc_id, write=True)
    if d.status not in ("review", "failed"):
        raise HTTPException(409, "Відхилити можна лише документ на перевірці")
    d.status = "rejected"
    audit(db, user, "doc.reject", "document", d.id)
    db.commit()
    return doc_out(d, full=True)


@router.post("/{doc_id}/reprocess")
def reprocess(doc_id: int, user: User = Depends(current_tenant_user), db: Session = Depends(get_db)):
    d = _get(db, user, doc_id, write=True)
    if d.status in ("processing", "approved", "queued"):
        raise HTTPException(409, "Цей документ не можна переобробити")
    d.status = "queued"
    enqueue(db, "process_document", {"doc_id": d.id})
    audit(db, user, "doc.reprocess", "document", d.id)
    db.commit()
    return doc_out(d)


@router.delete("/{doc_id}", status_code=204)
def delete_doc(doc_id: int, user: User = Depends(current_tenant_user), db: Session = Depends(get_db)):
    d = _get(db, user, doc_id)
    if user.role != "owner":
        raise HTTPException(403, "Видаляти документи може лише власник")
    get_storage().delete(d.storage_path)
    audit(db, user, "doc.delete", "document", d.id, {"filename": d.filename})
    db.delete(d)
    db.commit()
