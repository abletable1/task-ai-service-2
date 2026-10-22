"""Small async REST adapter with OAuth refresh, bounded retries and total deadline."""

import asyncio
import logging
import math
import time
from uuid import uuid4

import httpx

from task_ai_service.config import Settings
from task_ai_service.llm.errors import LLMError

logger = logging.getLogger(__name__)


class GigaChatClient:
    def __init__(self, settings: Settings, http: httpx.AsyncClient):
        self.settings = settings
        self.http = http
        self._token: str | None = None
        self._expires_at = 0.0
        self._token_lock = asyncio.Lock()

    async def _post(self, url: str, **kwargs: object) -> dict:
        try:
            response = await self.http.post(url, **kwargs)
        except httpx.TimeoutException as exc:
            raise LLMError("timeout", retryable=True) from exc
        except httpx.RequestError as exc:
            raise LLMError("network", retryable=True) from exc
        if response.status_code >= 400:
            status = response.status_code
            try:
                retry_after = float(response.headers.get("Retry-After", "0"))
            except ValueError:
                retry_after = 0
            if not math.isfinite(retry_after):
                retry_after = 0
            raise LLMError(
                f"http_{status}",
                retryable=status in {408, 429} or status >= 500,
                retry_after=min(max(retry_after, 0), 5),
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise LLMError("invalid_json") from exc
        if not isinstance(data, dict):
            raise LLMError("invalid_payload")
        return data

    async def _get_token(self) -> str:
        async with self._token_lock:
            if self._token and time.time() < self._expires_at - 30:
                return self._token
            credentials = self.settings.gigachat_credentials.get_secret_value().strip()
            if not credentials:
                raise LLMError("missing_credentials")
            data = await self._post(
                str(self.settings.gigachat_auth_url),
                headers={"Authorization": f"Basic {credentials}", "RqUID": str(uuid4())},
                data={"scope": self.settings.gigachat_scope},
            )
            try:
                token = data["access_token"]
                expiration = float(data["expires_at"])
                # GigaChat returns Unix milliseconds; also tolerate Unix seconds.
                if expiration > 100_000_000_000:
                    expiration /= 1000
                if (
                    not isinstance(token, str)
                    or not token.strip()
                    or not token.isascii()
                    or any(char.isspace() for char in token)
                    or not math.isfinite(expiration)
                    or expiration <= time.time()
                ):
                    raise ValueError("Invalid token metadata")
            except (KeyError, TypeError, ValueError) as exc:
                raise LLMError("invalid_token") from exc
            self._token, self._expires_at = token, expiration
            logger.info("oauth_token_refreshed")
            return token

    async def _complete(self, messages: list[dict[str, str]]) -> str:
        # A rejected cached token gets one refresh, independently of transient retries.
        for refresh in range(2):
            token = await self._get_token()
            try:
                data = await self._post(
                    f"{str(self.settings.gigachat_base_url).rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {token}"},
                    json={
                        "model": self.settings.gigachat_model,
                        "messages": messages,
                        "temperature": self.settings.llm_temperature,
                        "max_tokens": self.settings.llm_max_tokens,
                        "stream": False,
                    },
                )
            except LLMError as exc:
                if exc.reason == "http_401" and refresh == 0:
                    # Do not invalidate a newer token obtained by another request.
                    if self._token == token:
                        self._token = None
                    continue
                raise
            try:
                choice = data["choices"][0]
                if choice.get("finish_reason") in {"blacklist", "content_filter", "length"}:
                    raise LLMError("unusable_completion")
                content = choice["message"]["content"]
                if not isinstance(content, str) or not content.strip():
                    raise ValueError("Empty completion")
            except (KeyError, IndexError, TypeError, AttributeError, ValueError) as exc:
                raise LLMError("invalid_completion") from exc
            logger.info("llm_response_received", extra={"fields": {"response_chars": len(content)}})
            return content
        raise LLMError("http_401")

    async def summarize(self, messages: list[dict[str, str]]) -> str:
        try:
            async with asyncio.timeout(self.settings.llm_total_timeout_seconds):
                for attempt in range(self.settings.llm_max_retries + 1):
                    try:
                        return await self._complete(messages)
                    except LLMError as exc:
                        if not exc.retryable or attempt == self.settings.llm_max_retries:
                            raise
                        delay = max(
                            self.settings.llm_retry_backoff_seconds * (2**attempt),
                            exc.retry_after,
                        )
                        logger.warning(
                            "llm_retry",
                            extra={"fields": {"reason": exc.reason, "attempt": attempt + 1}},
                        )
                        await asyncio.sleep(delay)
        except TimeoutError as exc:
            raise LLMError("total_timeout") from exc
        raise LLMError("retry_exhausted")
