import pytest

from task_ai_service.config import Settings


@pytest.fixture
def settings():
    return Settings(
        _env_file=None,
        gigachat_credentials="test-authorization-key",
        gigachat_base_url="https://provider.test/v1",
        gigachat_auth_url="https://oauth.test/token",
        llm_retry_backoff_seconds=0,
        docs_enabled=True,
    )
