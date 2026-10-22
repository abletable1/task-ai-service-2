"""Normalize plain text and bound sentences/length, shared with the extractive fallback."""

import re
import unicodedata

from task_ai_service.llm.errors import LLMError


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = "".join(
        " " if char.isspace() else char
        for char in text
        if char.isspace() or not unicodedata.category(char).startswith("C")
    )
    return " ".join(text.split())


def clean_summary(text: str, max_sentences: int, max_chars: int) -> str:
    text = text.strip()
    text = re.sub(r"\A```(?:\w+)?\s*\n?", "", text)
    text = re.sub(r"\s*```\Z", "", text)
    text = normalize_text(text)
    if not text:
        raise LLMError("empty_summary")
    return limit_summary(text, max_sentences, max_chars)


def limit_summary(text: str, max_sentences: int, max_chars: int) -> str:
    sentences = re.split(r"(?<=[.!?…])\s+", text)
    text = " ".join(sentences[:max_sentences])
    if len(text) > max_chars:
        text = text[: max_chars - 1].rstrip() + "…"
    return text


def fallback_summary(text: str, max_sentences: int, max_chars: int) -> str:
    # Deterministic extract: available offline, without claiming semantic generation.
    return limit_summary(normalize_text(text), max_sentences, max_chars)
