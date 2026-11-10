"""Абстракція над провайдером LLM. Бізнес-логіка про провайдера нічого не знає."""

import base64
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol

from ...config import get_settings
from .. import registry
from .parser import is_text_document, parse_document_to_text

logger = logging.getLogger(__name__)


class ExtractionError(Exception):
    pass


@dataclass
class InputFile:
    filename: str
    media_type: str
    data: bytes


@dataclass
class LLMResult:
    data: Dict[str, Any]
    tokens_in: int = 0
    tokens_out: int = 0
    meta: Dict[str, Any] = field(default_factory=dict)


class LLMProvider(Protocol):
    def extract(self, files: List[InputFile], doc_type: str, context: str) -> LLMResult: ...

    def chat(self, system: str, user: str) -> Optional[str]: ...


def files_text(files: List[InputFile]) -> str:
    return "\n".join(parse_document_to_text(f.filename, f.data) if is_text_document(f.filename) else "" for f in files)


class OpenAIProvider:
    def __init__(self) -> None:
        import openai

        s = get_settings()
        if not s.openai_api_key:
            raise ExtractionError("OPENAI_API_KEY не налаштовано")
        self._openai = openai
        self._client = openai.OpenAI(api_key=s.openai_api_key)
        self._model = s.openai_vision_model

    @staticmethod
    def _block(f: InputFile) -> Dict[str, Any]:
        if is_text_document(f.filename):
            text = parse_document_to_text(f.filename, f.data)
            return {"type": "input_text", "text": f"--- Документ '{f.filename}' ---\n{text}\n--- Кінець '{f.filename}' ---"}
        b64 = base64.b64encode(f.data).decode("ascii")
        if f.media_type == "application/pdf":
            return {"type": "input_file", "filename": f.filename, "file_data": f"data:application/pdf;base64,{b64}"}
        return {"type": "input_image", "image_url": f"data:{f.media_type};base64,{b64}"}

    def extract(self, files: List[InputFile], doc_type: str, context: str) -> LLMResult:
        dt = registry.get(doc_type)
        if dt is None:
            raise ExtractionError(f"Невідомий тип документа: {doc_type}")
        content = [self._block(f) for f in files]
        if context.strip():
            content.append({"type": "input_text", "text": f"Додатковий контекст від користувача:\n{context}"})
        content.append({"type": "input_text", "text": f"Очікуваний тип: {dt.hint}\n\n{dt.prompt}"})
        try:
            resp = self._client.responses.create(
                model=self._model, max_output_tokens=16000, tools=[dt.tool],
                tool_choice={"type": "function", "name": dt.tool["name"]},
                input=[{"role": "user", "content": content}],
            )
        except self._openai.APIError as e:
            logger.exception("OpenAI call failed")
            raise ExtractionError(f"Помилка LLM-провайдера: {e}") from e
        call = next((i for i in resp.output if i.type == "function_call" and i.name == dt.tool["name"]), None)
        if call is None:
            raise ExtractionError(f"Модель не повернула результат (status={resp.status})")
        try:
            data = json.loads(call.arguments)
        except json.JSONDecodeError as e:
            raise ExtractionError(f"Некоректна відповідь моделі: {e}") from e
        usage = getattr(resp, "usage", None)
        return LLMResult(data, getattr(usage, "input_tokens", 0) or 0, getattr(usage, "output_tokens", 0) or 0)

    def chat(self, system: str, user: str) -> Optional[str]:
        try:
            resp = self._client.responses.create(
                model=self._model, max_output_tokens=1500,
                input=[{"role": "system", "content": system}, {"role": "user", "content": user}])
        except self._openai.APIError as e:
            logger.exception("OpenAI chat failed")
            raise ExtractionError(f"Помилка LLM-провайдера: {e}") from e
        return resp.output_text


class MockProvider:
    """Детермінований провайдер для розробки/демо/тестів без ключа."""

    def extract(self, files: List[InputFile], doc_type: str, context: str) -> LLMResult:
        dt = registry.get(doc_type)
        if dt is None:
            raise ExtractionError(f"Невідомий тип документа: {doc_type}")
        data = dt.mock(files_text(files) + "\n" + context)
        if doc_type != "other" and "detected_type" in data:
            data["detected_type"] = doc_type
        return LLMResult(data, 0, 0, {"mock": True})

    def chat(self, system: str, user: str) -> Optional[str]:
        return None  # виклик має скористатись екстрактивною відповіддю


def get_provider() -> LLMProvider:
    return OpenAIProvider() if get_settings().llm_provider == "openai" else MockProvider()
