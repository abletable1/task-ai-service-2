"""Validated configuration; OS environment overrides .env and profile defaults."""

from pathlib import Path
from typing import Literal

from pydantic import Field, HttpUrl, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_ignore_empty=True)

    app_env: Literal["dev", "prod"] = "dev"
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    docs_enabled: bool = False
    gigachat_credentials: SecretStr = SecretStr("")
    gigachat_scope: Literal["GIGACHAT_API_PERS", "GIGACHAT_API_B2B", "GIGACHAT_API_CORP"] = (
        "GIGACHAT_API_PERS"
    )
    gigachat_model: str = Field(default="GigaChat-2", min_length=1)
    gigachat_base_url: HttpUrl = HttpUrl("https://api.giga.chat/v1")
    gigachat_auth_url: HttpUrl = HttpUrl("https://ngw.devices.sberbank.ru:9443/api/v2/oauth")
    gigachat_ca_bundle: Path | None = None
    llm_connect_timeout_seconds: float = Field(default=5, gt=0, le=60)
    llm_read_timeout_seconds: float = Field(default=15, gt=0, le=300)
    llm_total_timeout_seconds: float = Field(default=40, gt=0, le=600)
    llm_max_retries: int = Field(default=2, ge=0, le=5)
    llm_retry_backoff_seconds: float = Field(default=0.5, ge=0, le=10)
    llm_temperature: float = Field(default=0.2, gt=0, le=2)
    llm_max_tokens: int = Field(default=700, ge=32, le=4096)
    cache_ttl_seconds: float = Field(default=300, ge=0, le=86400)
    cache_max_entries: int = Field(default=256, ge=1, le=10000)
    max_input_chars: int = Field(default=20000, ge=20, le=20000)
    max_summary_chars: int = Field(default=2000, ge=100, le=10000)

    @model_validator(mode="after")
    def validate_production(self) -> "Settings":
        if self.app_env == "prod":
            urls = (self.gigachat_base_url, self.gigachat_auth_url)
            if any(url.scheme != "https" for url in urls):
                raise ValueError("Production GigaChat URLs must use HTTPS")
        if self.gigachat_ca_bundle and not self.gigachat_ca_bundle.is_file():
            raise ValueError("GIGACHAT_CA_BUNDLE must point to an existing PEM file")
        return self


def load_settings() -> Settings:
    # APP_ENV can also be read from .env, before selecting the profile.
    environment = Settings().app_env
    return Settings(_env_file=(f"config/{environment}.env", ".env"))
