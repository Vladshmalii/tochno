"""Пошук по базі знань: чанкування + BM25 з легким стемінгом для української/російської.

Без зовнішніх залежностей (векторної БД): для баз до десятків тисяч фрагментів цього достатньо,
а інтерфейс search() можна замінити на гібридний пошук із ембедінгами без змін в API."""

import io
import math
import re
from collections import Counter
from typing import Dict, List, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import KnowledgeChunk, KnowledgeDoc
from ..docs_extract.parser import is_text_document, parse_document_to_text

_WORD = re.compile(r"[\w'’]+", re.UNICODE)
_STOP = {
    "і", "й", "та", "в", "у", "на", "з", "із", "до", "по", "за", "що", "як", "це", "я", "ми", "ви", "а", "але", "чи",
    "для", "від", "при", "про", "не", "є", "та", "який", "яка", "які", "де", "коли", "мені", "треба", "можна", "ли",
    "и", "в", "на", "с", "из", "по", "за", "что", "как", "это", "а", "но", "или", "для", "от", "при", "не", "где",
}
STEM_LEN = 6  # грубий стемінг: відкидаємо закінчення, щоб "інкасація/інкасації/інкасацією" збігались


def tokenize(text: str) -> List[str]:
    out = []
    for w in _WORD.findall((text or "").lower()):
        w = w.replace("'", "").replace("’", "")
        if len(w) < 2 or w in _STOP:
            continue
        out.append(w[:STEM_LEN])
    return out


def chunk_text(text: str, size: int = 900, overlap: int = 150) -> List[str]:
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: List[str] = []
    cur = ""
    for p in paras:
        while len(p) > size:  # дуже довгий абзац ріжемо по реченнях/символах
            cut = p.rfind(". ", 0, size)
            cut = cut + 1 if cut > size // 2 else size
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(p[:cut].strip())
            p = p[max(cut - overlap, 0):].strip() if len(p) - cut > overlap else p[cut:].strip()
            if not p:
                break
        if not p:
            continue
        if len(cur) + len(p) + 2 <= size:
            cur = f"{cur}\n\n{p}" if cur else p
        else:
            if cur:
                chunks.append(cur)
            cur = p
    if cur:
        chunks.append(cur)
    return [c for c in chunks if len(c) > 20]


def extract_text(filename: str, data: bytes) -> str:
    low = filename.lower()
    if low.endswith(".pdf"):
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        return "\n\n".join((p.extract_text() or "") for p in reader.pages)
    if is_text_document(filename):
        return parse_document_to_text(filename, data)
    return ""


def index_document(db: Session, tenant_id: int, title: str, filename: str, text: str) -> KnowledgeDoc:
    doc = KnowledgeDoc(tenant_id=tenant_id, title=title[:300], filename=filename[:300], chars=len(text))
    db.add(doc)
    db.flush()
    chunks = chunk_text(text)
    for i, c in enumerate(chunks):
        toks = tokenize(c)
        db.add(KnowledgeChunk(tenant_id=tenant_id, doc_id=doc.id, idx=i, text=c, terms=dict(Counter(toks)),
                              length=len(toks)))
    doc.chunks = len(chunks)
    return doc


def search(db: Session, tenant_id: int, query: str, k: int = 5) -> List[Tuple[float, KnowledgeChunk]]:
    q_terms = list(dict.fromkeys(tokenize(query)))
    if not q_terms:
        return []
    chunks: List[KnowledgeChunk] = list(db.scalars(select(KnowledgeChunk).where(KnowledgeChunk.tenant_id == tenant_id)))
    if not chunks:
        return []
    n = len(chunks)
    avgdl = (sum(c.length for c in chunks) / n) or 1.0
    df: Dict[str, int] = {t: sum(1 for c in chunks if t in c.terms) for t in q_terms}
    k1, b = 1.5, 0.75
    scored = []
    for c in chunks:
        s = 0.0
        for t in q_terms:
            tf = c.terms.get(t, 0)
            if not tf:
                continue
            idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
            s += idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * c.length / avgdl))
        if s > 0:
            scored.append((s, c))
    scored.sort(key=lambda x: -x[0])
    # відсікаємо випадкові збіги по одному слову: потрібен збіг хоча б половини термів запиту
    need = max(1, math.ceil(len(q_terms) / 2)) if len(q_terms) > 1 else 1
    good = [(s, c) for s, c in scored if sum(1 for t in q_terms if t in c.terms) >= need]
    return good[:k]
