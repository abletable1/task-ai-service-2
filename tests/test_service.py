import pytest

from task_ai_service.llm.errors import LLMError
from task_ai_service.postprocessing import clean_summary, fallback_summary, normalize_text
from task_ai_service.services.cache import SummaryCache
from task_ai_service.services.summarizer import Summarizer

TEXT = "Команда завершила разработку сервиса. Тесты прошли успешно. Релиз будет в пятницу."


class FakeLLM:
    def __init__(self, failure=None, result="```text\nСервис готов. Тесты прошли. Третье.\n```"):
        self.calls = []
        self.failure, self.result = failure, result

    async def summarize(self, messages):
        self.calls.append(messages)
        if self.failure:
            raise self.failure
        return self.result


async def test_pipeline_cleans_and_caches_success(settings):
    llm = FakeLLM()
    service = Summarizer(llm, SummaryCache(300, 2), settings)
    result = await service.process(TEXT, 2)
    repeated = await service.process(TEXT, 2)
    assert result.summary == "Сервис готов. Тесты прошли."
    assert result.source == "gigachat" and not result.cached
    assert repeated.summary == result.summary and repeated.cached
    assert len(llm.calls) == 1
    assert llm.calls[0][0]["role"] == "system"
    assert llm.calls[0][1] == {"role": "user", "content": TEXT}


async def test_cache_normalizes_whitespace_and_separates_parameters(settings):
    llm = FakeLLM()
    service = Summarizer(llm, SummaryCache(300, 10), settings)
    await service.process(TEXT, 2)
    assert (await service.process(TEXT.replace(" ", "  \n"), 2)).cached
    await service.process(TEXT, 1)
    settings.gigachat_model = "different-model"
    await service.process(TEXT, 2)
    assert len(llm.calls) == 3


@pytest.mark.parametrize("failure", [LLMError("timeout"), LLMError("http_503")])
async def test_fallback_is_explicit_and_never_cached(settings, failure):
    llm = FakeLLM(failure=failure)
    service = Summarizer(llm, SummaryCache(300, 2), settings)
    for _ in range(2):
        result = await service.process(TEXT, 2)
        assert result.summary == "Команда завершила разработку сервиса. Тесты прошли успешно."
        assert result.source == "fallback" and not result.cached and result.warning
    assert len(llm.calls) == 2


async def test_empty_postprocessed_response_uses_fallback(settings):
    service = Summarizer(FakeLLM(result="\x00\u200b"), SummaryCache(300, 2), settings)
    assert (await service.process(TEXT, 1)).source == "fallback"


async def test_programming_error_is_not_swallowed(settings):
    service = Summarizer(FakeLLM(failure=RuntimeError("bug")), SummaryCache(300, 2), settings)
    with pytest.raises(RuntimeError):
        await service.process(TEXT, 2)


def test_cache_ttl_and_lru():
    now = [0]
    cache = SummaryCache(10, 2, clock=lambda: now[0])
    cache.set("a", "A")
    cache.set("b", "B")
    assert cache.get("a") == "A"
    cache.set("c", "C")
    assert cache.get("b") is None
    now[0] = 10
    assert cache.get("a") is None and cache.get("c") is None


def test_cache_ttl_zero_disables_storage():
    cache = SummaryCache(0, 2)
    cache.set("a", "A")
    assert cache.get("a") is None


def test_postprocessing_limits_and_controls():
    assert clean_summary("```text\nПервое.\nВторое. Третье.\n```", 2, 100) == "Первое. Второе."
    assert normalize_text("слово\nслово\x00\u200b") == "слово слово"
    assert len(clean_summary("Длинное предложение без точки " * 10, 1, 100)) == 100
    with pytest.raises(LLMError, match="empty_summary"):
        clean_summary("\x00", 1, 100)


def test_fallback_preserves_source_that_looks_like_code_fence():
    text = "```abcdefghijklmnopqrstuvwxyz```"
    assert fallback_summary(text, 1, 100) == text
