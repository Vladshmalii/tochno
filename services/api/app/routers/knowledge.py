"""Модуль «База знань та AI-асистент»: завантаження інструкцій, питання з відповіддю за джерелами."""

from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..deps import audit, require_module, require_module_roles
from ..models import ChatLog, KnowledgeChunk, KnowledgeDoc, UsageEvent, User
from ..modules.docs_extract.llm import ExtractionError, get_provider
from ..modules.knowledge.engine import extract_text, index_document, search

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])
can_view = require_module("knowledge")
can_edit = require_module_roles("knowledge", "owner", "accountant")

SYSTEM = (
    "Ви — внутрішній асистент компанії. Відповідайте ТІЛЬКИ на основі наданих фрагментів інструкцій. "
    "Якщо відповіді в них немає — так і скажіть, не вигадуйте. Відповідайте коротко, українською, "
    "покроково, якщо питання про процедуру."
)
NOT_FOUND = "У базі знань не знайдено відповіді на це питання. Спробуйте переформулювати або зверніться до керівника."


def _doc_out(d: KnowledgeDoc) -> dict:
    return {"id": d.id, "title": d.title, "filename": d.filename, "chars": d.chars, "chunks": d.chunks,
            "created_at": d.created_at}


@router.get("/docs")
def list_docs(user: User = Depends(can_view), db: Session = Depends(get_db)):
    rows = db.scalars(select(KnowledgeDoc).where(KnowledgeDoc.tenant_id == user.tenant_id)
                      .order_by(KnowledgeDoc.id.desc()))
    return [_doc_out(d) for d in rows]


@router.post("/docs", status_code=201)
async def upload(files: List[UploadFile] = File(...), user: User = Depends(can_edit), db: Session = Depends(get_db)):
    s = get_settings()
    out = []
    for f in files:
        raw = await f.read()
        if len(raw) > s.max_upload_mb * 1024 * 1024:
            raise HTTPException(413, f"Файл {f.filename} завеликий")
        try:
            text = extract_text(f.filename or "", raw)
        except Exception:  # noqa: BLE001 — зіпсований PDF/DOCX
            raise HTTPException(400, f"Не вдалося прочитати файл {f.filename}")
        if len(text.strip()) < 20:
            raise HTTPException(400, f"У файлі {f.filename} не знайдено тексту (скани/зображення не підтримуються — "
                                     "завантажте текстовий PDF, DOCX, XLSX або TXT)")
        out.append(index_document(db, user.tenant_id, (f.filename or "Документ").rsplit(".", 1)[0], f.filename or "", text))
    audit(db, user, "knowledge.upload", "knowledge_doc", ",".join(f.filename or "" for f in files))
    db.commit()
    return [_doc_out(d) for d in out]


class TextIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    text: str = Field(min_length=20, max_length=500_000)


@router.post("/docs/text", status_code=201)
def add_text(body: TextIn, user: User = Depends(can_edit), db: Session = Depends(get_db)):
    d = index_document(db, user.tenant_id, body.title, "", body.text)
    audit(db, user, "knowledge.add_text", "knowledge_doc", body.title)
    db.commit()
    return _doc_out(d)


@router.delete("/docs/{doc_id}", status_code=204)
def delete_doc(doc_id: int, user: User = Depends(can_edit), db: Session = Depends(get_db)):
    d = db.get(KnowledgeDoc, doc_id)
    if not d or d.tenant_id != user.tenant_id:
        raise HTTPException(404, "Документ не знайдено")
    for c in db.scalars(select(KnowledgeChunk).where(KnowledgeChunk.doc_id == d.id)):
        db.delete(c)
    audit(db, user, "knowledge.delete", "knowledge_doc", d.id, {"title": d.title})
    db.delete(d)
    db.commit()


class AskIn(BaseModel):
    question: str = Field(min_length=2, max_length=2000)


@router.post("/ask")
def ask(body: AskIn, user: User = Depends(can_view), db: Session = Depends(get_db)):
    hits = search(db, user.tenant_id, body.question, k=4)
    titles = {d.id: d.title for d in db.scalars(select(KnowledgeDoc).where(
        KnowledgeDoc.id.in_({c.doc_id for _, c in hits}) if hits else KnowledgeDoc.id == -1))}
    sources = [{"doc_id": c.doc_id, "title": titles.get(c.doc_id, ""), "snippet": c.text[:500],
                "score": round(s, 2)} for s, c in hits]
    if not hits:
        answer, found = NOT_FOUND, False
    else:
        context = "\n\n".join(f"[{i + 1}] ({x['title']})\n{c.text}" for i, (x, (_, c)) in enumerate(zip(sources, hits)))
        try:
            answer = get_provider().chat(SYSTEM, f"Фрагменти інструкцій:\n{context}\n\nПитання: {body.question}")
        except ExtractionError:
            answer = None
        found = True
        if not answer:  # без LLM: показуємо найрелевантніший фрагмент як є
            answer = f"Найбільш релевантний фрагмент («{sources[0]['title']}»):\n\n{hits[0][1].text}"
        else:
            db.add(UsageEvent(tenant_id=user.tenant_id, kind="chat", units=1))
    log = ChatLog(tenant_id=user.tenant_id, user_id=user.id, question=body.question, answer=answer,
                  sources=sources, found=found)
    db.add(log)
    db.commit()
    return {"log_id": log.id, "answer": answer, "found": found, "sources": sources}


class FeedbackIn(BaseModel):
    log_id: int
    value: int = Field(ge=-1, le=1)


@router.post("/feedback", status_code=204)
def feedback(body: FeedbackIn, user: User = Depends(can_view), db: Session = Depends(get_db)):
    log = db.get(ChatLog, body.log_id)
    if not log or log.tenant_id != user.tenant_id:
        raise HTTPException(404, "Запис не знайдено")
    log.feedback = body.value or None
    db.commit()


@router.get("/gaps")
def gaps(user: User = Depends(can_edit), db: Session = Depends(get_db)):
    """Питання без відповіді або з негативною оцінкою — що додати в базу знань."""
    rows = db.scalars(select(ChatLog).where(
        ChatLog.tenant_id == user.tenant_id, (ChatLog.found.is_(False)) | (ChatLog.feedback == -1))
        .order_by(ChatLog.id.desc()).limit(100))
    total = db.scalar(select(func.count(ChatLog.id)).where(ChatLog.tenant_id == user.tenant_id)) or 0
    return {"total_questions": total, "items": [{"id": r.id, "question": r.question, "found": r.found,
                                                 "feedback": r.feedback, "created_at": r.created_at} for r in rows]}
