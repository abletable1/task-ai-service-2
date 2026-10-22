import pytest
from pydantic import ValidationError

from task_ai_service.config import Settings, load_settings


def test_environment_overrides_dotenv_and_profile(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "prod.env").write_text("LOG_LEVEL=WARNING\nDOCS_ENABLED=false\n")
    (tmp_path / ".env").write_text("APP_ENV=prod\nLOG_LEVEL=ERROR\n")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    settings = load_settings()
    assert settings.app_env == "prod" and settings.log_level == "DEBUG"
    assert not settings.docs_enabled
    monkeypatch.delenv("LOG_LEVEL")
    assert load_settings().log_level == "ERROR"


@pytest.mark.parametrize(
    "parameters",
    [
        {"llm_max_retries": -1},
        {"llm_read_timeout_seconds": 0},
        {"cache_ttl_seconds": -1},
        {"app_env": "invalid"},
        {"gigachat_ca_bundle": "missing.pem"},
        {"app_env": "prod", "gigachat_base_url": "http://provider.test/v1"},
    ],
)
def test_invalid_configuration(parameters):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **parameters)


def test_secret_repr_does_not_leak():
    settings = Settings(_env_file=None, gigachat_credentials="sensitive-value")
    assert "sensitive-value" not in repr(settings)
