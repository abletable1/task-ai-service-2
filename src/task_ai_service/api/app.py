import logging
import time
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import uuid4

import httpx
from fastapi import Body, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from task_ai_service.config import Settings, load_settings
from task_ai_service.llm.gigachat import GigaChatClient
from task_ai_service.llm.tls import create_tls_context
from task_ai_service.logging import configure_logging, request_id
from task_ai_service.models import ErrorResponse, ProcessRequest, ProcessResponse
from task_ai_service.services.cache import SummaryCache
from task_ai_service.services.summarizer import Summarizer

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configure_logging(settings.log_level)
        tls = create_tls_context(settings.gigachat_ca_bundle)
        timeout = httpx.Timeout(
            settings.llm_read_timeout_seconds, connect=settings.llm_connect_timeout_seconds
        )
        async with httpx.AsyncClient(verify=tls, timeout=timeout, trust_env=False) as http:
            app.state.summarizer = Summarizer(
                GigaChatClient(settings, http),
                SummaryCache(settings.cache_ttl_seconds, settings.cache_max_entries),
                settings,
            )
            logger.info("service_started", extra={"fields": {"environment": settings.app_env}})
            yield
            logger.info("service_stopped")

    app = FastAPI(
        title="GigaChat Summary API",
        version="0.1.0",
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def trace_request(request: Request, call_next):
        current_id = str(uuid4())
        context_token = request_id.set(current_id)
        started = time.perf_counter()
        try:
            logger.info("request_received", extra={"fields": {"method": request.method}})
            try:
                response = await call_next(request)
            except Exception as exc:
                logger.error(
                    "internal_error", extra={"fields": {"exception_type": type(exc).__name__}}
                )
                response = JSONResponse(
                    status_code=500,
                    content={"error": "Внутренняя ошибка сервиса", "request_id": current_id},
                )
            response.headers["X-Request-ID"] = current_id
            logger.info(
                "request_completed",
                extra={
                    "fields": {
                        "status": response.status_code,
                        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                    }
                },
            )
            return response
        finally:
            request_id.reset(context_token)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        # Pydantic's default error contains the input: do not echo personal data.
        errors = [{"loc": error["loc"], "type": error["type"]} for error in exc.errors()]
        error_message = "Некорректные входные данные"
        if any(error["type"] == "json_invalid" for error in errors):
            error_message = (
                "Некорректный JSON: переносы строк внутри text нужно записывать как \\n. "
                "Для текста с абзацами используйте POST /process/text "
                "с Content-Type: text/plain."
            )
        logger.warning("validation_failed", extra={"fields": {"error_count": len(errors)}})
        return JSONResponse(
            status_code=422,
            content={
                "error": error_message,
                "details": errors,
                "request_id": request_id.get(),
            },
        )

    @app.get("/health", tags=["health"])
    async def health():
        return {"status": "ok", "environment": settings.app_env}

    async def summarize_payload(payload: ProcessRequest, request: Request) -> ProcessResponse:
        if len(payload.text) > settings.max_input_chars:
            raise RequestValidationError([{"loc": ("body", "text"), "type": "string_too_long"}])
        result = await request.app.state.summarizer.process(payload.text, payload.max_sentences)
        return ProcessResponse(
            summary=result.summary,
            source=result.source,
            cached=result.cached,
            warning=result.warning,
            request_id=request_id.get(),
        )

    @app.post(
        "/process",
        response_model=ProcessResponse,
        responses={422: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
        tags=["summarization"],
    )
    async def process(payload: ProcessRequest, request: Request):
        return await summarize_payload(payload, request)

    @app.post(
        "/process/text",
        response_model=ProcessResponse,
        responses={422: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
        tags=["summarization"],
        summary="Обработать обычный текст с абзацами",
    )
    async def process_text(
        request: Request,
        text: Annotated[
            str,
            Body(
                media_type="text/plain",
                description="Текст UTF-8; переносы строк и пустые строки можно вставлять напрямую.",
                examples=["Команда завершила разработку сервиса.\n\nТесты прошли успешно."],
            ),
        ],
        max_sentences: Annotated[int, Query(ge=1, le=10)] = 3,
    ):
        try:
            payload = ProcessRequest(text=text, max_sentences=max_sentences)
        except ValidationError as exc:
            raise RequestValidationError(
                [{**error, "loc": ("body", *error["loc"])} for error in exc.errors()]
            ) from exc
        return await summarize_payload(payload, request)

    return app
