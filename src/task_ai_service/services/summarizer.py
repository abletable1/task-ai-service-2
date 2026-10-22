import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Protocol

from task_ai_service.config import Settings
from task_ai_service.llm.errors import LLMError
from task_ai_service.llm.prompts import PROMPT_VERSION, build_messages
from task_ai_service.postprocessing import clean_summary, fallback_summary, normalize_text
from task_ai_service.services.cache import SummaryCache

logger = logging.getLogger(__name__)
FALLBACK_WARNING = "GigaChat недоступен. Возвращены первые предложения исходного текста."


class LLM(Protocol):
    async def summarize(self, messages: list[dict[str, str]]) -> str: ...


@dataclass(frozen=True)
class SummaryResult:
    summary: str
    source: str
    cached: bool = False
    warning: str | None = None


class Summarizer:
    def __init__(self, llm: LLM, cache: SummaryCache, settings: Settings):
        self.llm, self.cache, self.settings = llm, cache, settings

    async def process(self, text: str, max_sentences: int) -> SummaryResult:
        text = normalize_text(text)
        settings = self.settings
        key_data = [
            text,
            max_sentences,
            settings.gigachat_model,
            settings.llm_temperature,
            settings.llm_max_tokens,
            settings.max_summary_chars,
            PROMPT_VERSION,
        ]
        key = hashlib.sha256(json.dumps(key_data, ensure_ascii=False).encode()).hexdigest()
        cached = self.cache.get(key)
        if cached is not None:
            logger.info("cache_hit")
            return SummaryResult(cached, "gigachat", cached=True)
        logger.info("cache_miss")
        messages = build_messages(text, max_sentences)
        logger.info(
            "prompt_built",
            extra={"fields": {"input_chars": len(text), "prompt_version": PROMPT_VERSION}},
        )
        try:
            raw = await self.llm.summarize(messages)
            summary = clean_summary(raw, max_sentences, settings.max_summary_chars)
        except LLMError as exc:
            logger.error("llm_failed", extra={"fields": {"reason": exc.reason}})
            summary = fallback_summary(text, max_sentences, settings.max_summary_chars)
            return SummaryResult(summary, "fallback", warning=FALLBACK_WARNING)
        self.cache.set(key, summary)
        logger.info("summary_ready", extra={"fields": {"summary_chars": len(summary)}})
        return SummaryResult(summary, "gigachat")
