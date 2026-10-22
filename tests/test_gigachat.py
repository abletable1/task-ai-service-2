import asyncio
import json
import time
from uuid import UUID

import httpx
import pytest

from task_ai_service.llm.errors import LLMError
from task_ai_service.llm.gigachat import GigaChatClient

MESSAGES = [{"role": "user", "content": "Текст для теста"}]


def token_response(token="access-token", expiration=None):
    return httpx.Response(
        200,
        json={
            "access_token": token,
            "expires_at": expiration or (time.time() + 1800) * 1000,
        },
    )


def completion(content="Краткое резюме.", finish_reason="stop"):
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {"content": content},
                    "finish_reason": finish_reason,
                }
            ]
        },
    )


async def test_oauth_contract_and_token_reuse(settings):
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.host == "oauth.test":
            assert request.headers["Authorization"] == "Basic test-authorization-key"
            assert UUID(request.headers["RqUID"]).version == 4
            assert request.content == b"scope=GIGACHAT_API_PERS"
            return token_response()
        assert str(request.url) == "https://provider.test/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer access-token"
        payload = json.loads(request.content)
        assert payload["messages"] == MESSAGES
        assert payload["model"] == settings.gigachat_model
        assert payload["stream"] is False
        return completion()

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = GigaChatClient(settings, http)
        assert await client.summarize(MESSAGES) == "Краткое резюме."
        assert await client.summarize(MESSAGES) == "Краткое резюме."
    assert len(requests) == 3


async def test_token_refresh_is_serialized(settings):
    auth_calls = 0

    async def handler(request):
        nonlocal auth_calls
        if request.url.host == "oauth.test":
            auth_calls += 1
            await asyncio.sleep(0)
            return token_response()
        return completion()

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = GigaChatClient(settings, http)
        await asyncio.gather(*(client.summarize(MESSAGES) for _ in range(5)))
    assert auth_calls == 1


@pytest.mark.parametrize("expiration", [time.time() + 10, (time.time() + 10) * 1000])
async def test_nearly_expired_token_is_refreshed(settings, expiration):
    auth_calls = 0

    def handler(request):
        nonlocal auth_calls
        if request.url.host == "oauth.test":
            auth_calls += 1
            return token_response(expiration=expiration)
        return completion()

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = GigaChatClient(settings, http)
        await client.summarize(MESSAGES)
        await client.summarize(MESSAGES)
    assert auth_calls == 2


async def test_401_refreshes_token_once(settings):
    auth_calls, chat_calls = 0, 0

    def handler(request):
        nonlocal auth_calls, chat_calls
        if request.url.host == "oauth.test":
            auth_calls += 1
            return token_response(token=f"token-{auth_calls}")
        chat_calls += 1
        if chat_calls == 1:
            return httpx.Response(401)
        assert request.headers["Authorization"] == "Bearer token-2"
        return completion()

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        assert await GigaChatClient(settings, http).summarize(MESSAGES) == "Краткое резюме."
    assert (auth_calls, chat_calls) == (2, 2)


@pytest.mark.parametrize("status", [408, 429, 500, 503])
async def test_transient_status_is_retried(settings, status):
    chats = 0

    def handler(request):
        nonlocal chats
        if request.url.host == "oauth.test":
            return token_response()
        chats += 1
        return httpx.Response(status) if chats < 3 else completion()

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        assert await GigaChatClient(settings, http).summarize(MESSAGES) == "Краткое резюме."
    assert chats == 3


@pytest.mark.parametrize(
    "failure,reason",
    [
        (httpx.ConnectError, "network"),
        (httpx.ReadTimeout, "timeout"),
    ],
)
async def test_network_failures_exhaust_retries(settings, failure, reason):
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        raise failure("sensitive upstream details", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(LLMError, match=reason):
            await GigaChatClient(settings, http).summarize(MESSAGES)
    assert calls == 3


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
async def test_oauth_permanent_errors_are_not_retried(settings, status):
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(status)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(LLMError, match=f"http_{status}"):
            await GigaChatClient(settings, http).summarize(MESSAGES)
    assert calls == 1


@pytest.mark.parametrize(
    "response,reason",
    [
        (httpx.Response(200, text="not json"), "invalid_json"),
        (httpx.Response(200, json=[]), "invalid_payload"),
        (httpx.Response(200, json={}), "invalid_completion"),
        (httpx.Response(200, json={"choices": []}), "invalid_completion"),
        (completion(" "), "invalid_completion"),
        (completion(123), "invalid_completion"),
        (completion(finish_reason="blacklist"), "unusable_completion"),
        (completion(finish_reason="length"), "unusable_completion"),
    ],
)
async def test_invalid_completions(settings, response, reason):
    def handler(request):
        return token_response() if request.url.host == "oauth.test" else response

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(LLMError, match=reason):
            await GigaChatClient(settings, http).summarize(MESSAGES)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"access_token": "x", "expires_at": 1},
        {"access_token": None, "expires_at": 9999999999999},
        {"access_token": "x", "expires_at": "invalid"},
        {"access_token": "x", "expires_at": "NaN"},
    ],
)
async def test_invalid_tokens(settings, payload):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    ) as http:
        with pytest.raises(LLMError, match="invalid_token"):
            await GigaChatClient(settings, http).summarize(MESSAGES)


async def test_missing_credentials_never_calls_network(settings):
    settings = type(settings)(_env_file=None, gigachat_credentials="")
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: pytest.fail("Network must not be called"))
    ) as http:
        with pytest.raises(LLMError, match="missing_credentials"):
            await GigaChatClient(settings, http).summarize(MESSAGES)


async def test_total_deadline_includes_oauth(settings):
    settings.llm_total_timeout_seconds = 0.01

    async def handler(request):
        await asyncio.sleep(1)
        return token_response()

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(LLMError, match="total_timeout"):
            await GigaChatClient(settings, http).summarize(MESSAGES)


@pytest.mark.parametrize("header,expected", [("2", 2), ("99", 5), ("bad", 0), ("NaN", 0)])
async def test_retry_after_is_bounded(settings, monkeypatch, header, expected):
    pauses = []
    calls = 0

    async def fake_sleep(delay):
        pauses.append(delay)

    def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": header})
        return token_response() if request.url.host == "oauth.test" else completion()

    monkeypatch.setattr("task_ai_service.llm.gigachat.asyncio.sleep", fake_sleep)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        await GigaChatClient(settings, http).summarize(MESSAGES)
    assert pauses == [expected]
