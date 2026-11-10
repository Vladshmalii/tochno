"""Оркестрація обробки одного документа: LLM → аналіз типу → статус review. Модуль-агностична."""

import logging
from pathlib import Path
from typing import Any, Dict

from sqlalchemy.orm import Session

from ...core.jobs import handler
from ...core.storage import get_storage
from ...core.webhooks import emit
from ...db import SessionLocal
from ...models import AuditLog, Document, Tenant, UsageEvent, utcnow
from .. import registry
from .llm import ExtractionError, InputFile, get_provider

logger = logging.getLogger(__name__)
_ORDER = {"error": 0, "warning": 1, "info": 2}


def apply_analysis(db: Session, doc: Document, data: Dict[str, Any]) -> None:
    """Аналіз + денормалізація. Викликається і після LLM, і після ручної правки."""
    dt = registry.get(doc.doc_type)
    res = dt.analyze(db, doc, data)
    doc.extracted = res.data
    doc.flags = sorted(res.flags, key=lambda f: _ORDER.get(f["severity"], 3))
    doc.match = res.match
    doc.metrics = res.metrics
    idx = dt.index(res.data)
    doc.supplier_name = (idx["name"] or "")[:300]
    doc.supplier_tax_id = idx["tax_id"] or ""
    doc.doc_number = (idx["number"] or "")[:80]
    doc.amount = idx["amount"]


def _event(doc: Document) -> Dict[str, Any]:
    return {"id": doc.id, "module": doc.module, "doc_type": doc.doc_type, "status": doc.status,
            "filename": doc.filename, "extracted": doc.extracted, "flags": doc.flags}


def process_document(doc_id: int, session_factory=SessionLocal) -> None:
    db = session_factory()
    try:
        doc = db.get(Document, doc_id)
        if doc is None:
            return
        doc.status, doc.error = "processing", ""
        db.commit()
        try:
            raw = get_storage().read(doc.storage_path)
            result = get_provider().extract([InputFile(doc.filename, doc.media_type, raw)], doc.doc_type, doc.description)
            data = result.data
            if doc.doc_type == "other" and data.get("detected_type") in registry.REGISTRY:
                doc.doc_type = data["detected_type"]
            apply_analysis(db, doc, data)
            doc.confidence = data.get("confidence", "")
            doc.status = "review"
            clean = not doc.flags and doc.confidence == "high"
            tenant = db.get(Tenant, doc.tenant_id)
            if clean and (tenant.settings or {}).get("auto_approve_clean"):
                doc.status, doc.approved_at = "approved", utcnow()
                db.add(AuditLog(tenant_id=doc.tenant_id, action="doc.auto_approve", entity="document",
                                entity_id=str(doc.id)))
            db.add(UsageEvent(tenant_id=doc.tenant_id, kind="doc_processed",
                              tokens_in=result.tokens_in, tokens_out=result.tokens_out))
            emit(db, doc.tenant_id, "document.processed", _event(doc))
            if doc.status == "approved":
                emit(db, doc.tenant_id, "document.approved", _event(doc))
        except ExtractionError as e:
            doc.status, doc.error = "failed", str(e)
            emit(db, doc.tenant_id, "document.failed", _event(doc))
        except Exception as e:  # noqa: BLE001 — збій не має залишити документ у "processing"
            logger.exception("Document %s processing failed", doc_id)
            doc.status, doc.error = "failed", f"Внутрішня помилка обробки: {e}"
        doc.updated_at = utcnow()
        db.commit()
    finally:
        db.close()


@handler("process_document")
def _job(payload: Dict[str, Any]) -> None:
    process_document(payload["doc_id"])
