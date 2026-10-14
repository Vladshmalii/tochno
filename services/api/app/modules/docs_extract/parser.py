"""Парсер офісних документів (DOCX/DOC/XLSX/XLS/TXT/CSV) у текст для LLM."""

import io
import logging
import re
from typing import List

logger = logging.getLogger(__name__)

TEXT_EXTENSIONS = (".docx", ".doc", ".xlsx", ".xls", ".txt", ".csv")


def is_text_document(filename: str) -> bool:
    return filename.lower().endswith(TEXT_EXTENSIONS)


def parse_docx(data: bytes) -> str:
    import docx

    try:
        doc = docx.Document(io.BytesIO(data))
    except Exception:
        logger.exception("DOCX parse failed")
        return _raw_strings(data)
    parts: List[str] = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    for i, table in enumerate(doc.tables, 1):
        rows = []
        for row in table.rows:
            cells = [c.text.strip().replace("\n", " ") for c in row.cells]
            if any(cells):
                rows.append(" | ".join(cells))
        if rows:
            parts.append(f"[Таблиця {i}]:\n" + "\n".join(rows))
    return "\n\n".join(parts)


def _sheet_to_text(name: str, rows) -> str:
    lines = []
    for row in rows:
        vals = [str(v).strip() for v in row if v is not None and str(v).strip()]
        if vals:
            lines.append(" | ".join(vals))
    return f"--- Аркуш: {name} ---\n" + "\n".join(lines) if lines else ""


def parse_xlsx(data: bytes) -> str:
    import openpyxl

    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
        sheets = [_sheet_to_text(ws.title, ws.iter_rows(values_only=True)) for ws in wb.worksheets]
        return "\n\n".join(s for s in sheets if s)
    except Exception:
        logger.exception("XLSX parse failed")
        return _raw_strings(data)


def parse_xls(data: bytes) -> str:
    try:
        import xlrd

        wb = xlrd.open_workbook(file_contents=data)
        sheets = [
            _sheet_to_text(sh.name, (sh.row_values(r) for r in range(sh.nrows))) for sh in wb.sheets()
        ]
        return "\n\n".join(s for s in sheets if s)
    except Exception:
        logger.exception("XLS parse failed, trying xlsx/raw fallback")
        return parse_xlsx(data) if data[:2] == b"PK" else _raw_strings(data)


def parse_doc(data: bytes) -> str:
    try:
        import olefile

        if olefile.isOleFile(io.BytesIO(data)):
            ole = olefile.OleFileIO(io.BytesIO(data))
            if ole.exists("WordDocument"):
                text = _raw_strings(ole.openstream("WordDocument").read())
                if text.strip():
                    return text
    except Exception:
        logger.debug("OLE parse failed", exc_info=True)
    return _raw_strings(data)


def _raw_strings(data: bytes) -> str:
    out: List[str] = []
    for m in re.finditer(rb"(?:[\x20-\x7e\t\r\n]\x00|[\x00-\xff][\x04\x05]){3,}", data):
        s = m.group(0).decode("utf-16le", errors="ignore").strip()
        if len(s) > 3 and any(c.isalnum() for c in s):
            out.append(s)
    if len(out) < 5:
        for m in re.finditer(rb"[\x20-\x7e\xc0-\xff\xa8\xb8\xaa\xba\xaf\xbf\xa5]{4,}", data):
            s = m.group(0).decode("cp1251", errors="ignore").strip()
            if any(c.isalnum() for c in s):
                out.append(s)
    return "\n".join(out)


def parse_document_to_text(filename: str, data: bytes) -> str:
    low = filename.lower()
    if low.endswith(".docx"):
        return parse_docx(data)
    if low.endswith(".doc"):
        return parse_doc(data)
    if low.endswith(".xlsx"):
        return parse_xlsx(data)
    if low.endswith(".xls"):
        return parse_xls(data)
    if low.endswith((".txt", ".csv")):
        try:
            return data.decode("utf-8-sig")
        except UnicodeDecodeError:
            return data.decode("cp1251", errors="ignore")
    return ""
