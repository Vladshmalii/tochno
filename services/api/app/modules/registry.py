"""Реєстр типів документів. Кожен модуль реєструє свої типи: схему для LLM, промпт,
опис полів для UI та функцію аналізу (валідації, метрики). Пайплайн і API —
універсальні й про конкретні модулі нічого не знають."""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.orm import Session

S = {"type": "string"}
N = {"type": "number"}
B = {"type": "boolean"}


def desc(t: dict, text: str) -> dict:
    return {**t, "description": text}


def enum(values: List[str], text: str = "") -> dict:
    return {"type": "string", "enum": values, **({"description": text} if text else {})}


def obj(props: Dict[str, dict]) -> dict:
    """Об'єкт у strict-режимі OpenAI: усі поля обов'язкові, додаткових немає."""
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def arr(item_props: Dict[str, dict], text: str = "") -> dict:
    return {"type": "array", "items": obj(item_props), **({"description": text} if text else {})}


@dataclass
class Analysis:
    data: Dict[str, Any]
    flags: List[dict] = field(default_factory=list)
    match: Optional[dict] = None
    metrics: Optional[dict] = None


@dataclass
class DocType:
    code: str
    module: str
    name: str
    hint: str
    properties: Dict[str, dict]
    prompt: str
    fields: List[dict]  # [{key,label,type: text|number|date|textarea}] — для форми перевірки
    analyze: Callable[[Session, Any, Dict[str, Any]], Analysis]
    index: Callable[[Dict[str, Any]], Dict[str, Any]]  # → {name, tax_id, number, amount}
    mock: Callable[[str], Dict[str, Any]]  # детермінований "розпізнавач" для демо/тестів
    view: str = "form"  # form | report

    @property
    def schema(self) -> dict:
        return obj(self.properties)

    @property
    def tool(self) -> dict:
        return {"type": "function", "name": "extract_document", "description": f"Витягти дані: {self.name}",
                "parameters": self.schema, "strict": True}

    def public(self) -> dict:
        return {"code": self.code, "module": self.module, "name": self.name, "fields": self.fields, "view": self.view}


REGISTRY: Dict[str, DocType] = {}


def register(dt: DocType) -> DocType:
    REGISTRY[dt.code] = dt
    return dt


def get(code: str) -> Optional[DocType]:
    return REGISTRY.get(code)


def for_module(module: str) -> List[DocType]:
    return [d for d in REGISTRY.values() if d.module == module]


def load_all() -> None:
    """Імпорт модулів реєструє їхні типи."""
    from .docs_extract import types as _a  # noqa: F401
    from .identity import types as _b  # noqa: F401
    from .reports import types as _c  # noqa: F401
