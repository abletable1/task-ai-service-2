import json
import logging
from io import StringIO

import httpx
import pytest
from test_service import TEXT, FakeLLM

from task_ai_service.api.app import create_app
from task_ai_service.llm.errors import LLMError
from task_ai_service.logging import JsonFormatter, request_id
from task_ai_service.postprocessing import normalize_text


@pytest.fixture
async def client(settings):
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            client.app = app
            app.state.summarizer.llm = FakeLLM()
            yield client


async def test_health_and_docs(client):
    assert (await client.get("/health")).json() == {"status": "ok", "environment": "dev"}
    assert (await client.get("/docs")).status_code == 200
    assert (await client.get("/openapi.json")).status_code == 200


async def test_success_and_cache_over_http(client):
    first = await client.post("/process", json={"text": TEXT, "max_sentences": 2})
    repeated = await client.post("/process", json={"text": TEXT, "max_sentences": 2})
    assert first.status_code == repeated.status_code == 200
    assert first.json()["source"] == "gigachat"
    assert first.json()["cached"] is False
    assert repeated.json()["cached"] is True
    assert first.json()["request_id"] == first.headers["X-Request-ID"]
    assert first.json()["request_id"] != repeated.json()["request_id"]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"text": "short"},
        {"text": " " * 30},
        {"text": "\x00" * 30},
        {"text": 123},
        {"text": "A" * 20001},
        {"text": TEXT, "max_sentences": 0},
        {"text": TEXT, "max_sentences": 11},
        {"text": TEXT, "max_sentences": True},
        {"text": TEXT, "max_sentences": "2"},
        {"text": TEXT, "unknown": "sensitive"},
    ],
)
async def test_invalid_input(client, payload):
    response = await client.post("/process", json=payload)
    assert response.status_code == 422
    assert response.json()["error"] == "Некорректные входные данные"
    assert all("input" not in error for error in response.json()["details"])
    assert not client.app.state.summarizer.llm.calls


async def test_invalid_json(client):
    response = await client.post(
        "/process", content=b'{"text":', headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422


async def test_configurable_input_limit(client):
    client.app.state.summarizer.settings.max_input_chars = 20
    assert (await client.post("/process", json={"text": TEXT})).status_code == 422


async def test_provider_error_returns_explicit_fallback(client):
    client.app.state.summarizer.llm = FakeLLM(failure=LLMError("http_503"))
    response = await client.post("/process", json={"text": TEXT})
    assert response.status_code == 200
    assert response.json()["source"] == "fallback"
    assert response.json()["warning"]


async def test_unexpected_error_returns_500_without_leaking_details(client):
    client.app.state.summarizer.llm = FakeLLM(failure=RuntimeError("secret upstream body"))
    response = await client.post("/process", json={"text": TEXT})
    assert response.status_code == 500
    assert "secret" not in response.text
    assert response.json()["request_id"] == response.headers["X-Request-ID"]


async def test_production_disables_docs(settings):
    settings.app_env, settings.docs_enabled = "prod", False
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings)), base_url="http://test"
    ) as client:
        assert (await client.get("/docs")).status_code == 404
        assert (await client.get("/openapi.json")).status_code == 404


async def test_logs_are_structured_and_do_not_contain_sensitive_data(client, monkeypatch):
    stream = StringIO()
    monkeypatch.setattr(logging.getLogger("task_ai_service").handlers[0], "stream", stream)
    await client.post("/process", json={"text": TEXT})
    await client.post("/process", json={"text": TEXT})
    output = stream.getvalue()
    events = [json.loads(line) for line in output.splitlines()]
    names = {event["event"] for event in events}
    assert {"request_received", "cache_miss", "cache_hit", "prompt_built", "summary_ready"} <= names
    assert all(event["request_id"] != "-" for event in events)
    assert TEXT not in output and "test-authorization-key" not in output


def test_formatter_attaches_request_id():
    token = request_id.set("test-id")
    try:
        record = logging.LogRecord("test", logging.INFO, "", 0, "event", (), None)
        assert json.loads(JsonFormatter().format(record))["request_id"] == "test-id"
    finally:
        request_id.reset(token)


@pytest.mark.parametrize("separator", ["\n\n", "\r\n\r\n", "\r\r"])
async def test_json_accepts_paragraphs(client, separator):
    text = f"Команда завершила разработку сервиса.{separator}Тесты прошли успешно."
    response = await client.post("/process", json={"text": text})
    assert response.status_code == 200
    assert response.json()["source"] == "gigachat"
    assert client.app.state.summarizer.llm.calls[0][1]["content"] == normalize_text(text)


@pytest.mark.parametrize("separator", ["\n\n", "\r\n\r\n", "\r\r"])
async def test_plain_text_accepts_paragraphs(client, separator):
    text = f"Команда завершила разработку сервиса.{separator}Тесты прошли успешно."
    response = await client.post(
        "/process/text?max_sentences=2",
        content=text.encode("utf-8"),
        headers={"Content-Type": "text/plain; charset=utf-8"},
    )
    assert response.status_code == 200
    assert response.json()["source"] == "gigachat"
    assert response.json()["summary"] == "Сервис готов. Тесты прошли."
    assert response.json()["request_id"] == response.headers["X-Request-ID"]
    assert client.app.state.summarizer.llm.calls[0][1]["content"] == normalize_text(text)


@pytest.mark.parametrize("text", ["", "short", " " * 30, "\x00" * 30, "a" * 20001])
async def test_plain_text_validation(client, text):
    response = await client.post(
        "/process/text", content=text.encode(), headers={"Content-Type": "text/plain"}
    )
    assert response.status_code == 422
    assert not client.app.state.summarizer.llm.calls
    assert all("input" not in error for error in response.json()["details"])


@pytest.mark.parametrize("limit", ["0", "11", "invalid"])
async def test_plain_text_validates_sentence_limit(client, limit):
    response = await client.post(
        f"/process/text?max_sentences={limit}",
        content=TEXT.encode("utf-8"),
        headers={"Content-Type": "text/plain"},
    )
    assert response.status_code == 422
    assert not client.app.state.summarizer.llm.calls


async def test_plain_text_rejects_invalid_utf8(client):
    response = await client.post(
        "/process/text", content=b"\xff" * 30, headers={"Content-Type": "text/plain"}
    )
    assert response.status_code == 422
    assert not client.app.state.summarizer.llm.calls


async def test_plain_text_honors_configured_input_limit(client):
    client.app.state.summarizer.settings.max_input_chars = 20
    response = await client.post(
        "/process/text", content=TEXT.encode("utf-8"), headers={"Content-Type": "text/plain"}
    )
    assert response.status_code == 422
    assert not client.app.state.summarizer.llm.calls


async def test_json_and_plain_text_share_normalized_cache(client):
    text = "Команда завершила разработку сервиса.\n\nТесты прошли успешно."
    first = await client.post(
        "/process/text", content=text.encode("utf-8"), headers={"Content-Type": "text/plain"}
    )
    second = await client.post("/process", json={"text": normalize_text(text)})
    assert first.status_code == second.status_code == 200
    assert not first.json()["cached"] and second.json()["cached"]
    assert len(client.app.state.summarizer.llm.calls) == 1


async def test_plain_text_paragraphs_use_fallback(client):
    client.app.state.summarizer.llm = FakeLLM(failure=LLMError("timeout"))
    text = "Команда завершила разработку сервиса.\n\nТесты прошли успешно."
    response = await client.post(
        "/process/text?max_sentences=2",
        content=text.encode("utf-8"),
        headers={"Content-Type": "text/plain"},
    )
    assert response.status_code == 200
    assert response.json()["source"] == "fallback"
    assert response.json()["summary"] == normalize_text(text)


async def test_raw_newlines_in_json_return_actionable_error(client):
    body = '{"text": "Первый абзац текста.\n\nВторой абзац текста."}'
    response = await client.post(
        "/process", content=body.encode("utf-8"), headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422
    assert "\\n" in response.json()["error"]
    assert "/process/text" in response.json()["error"]
    assert "Первый абзац" not in response.text
    assert not client.app.state.summarizer.llm.calls


async def test_openapi_advertises_plain_text_input(client):
    schema = (await client.get("/openapi.json")).json()
    operation = schema["paths"]["/process/text"]["post"]
    assert "text/plain" in operation["requestBody"]["content"]
    assert any(parameter["name"] == "max_sentences" for parameter in operation["parameters"])
