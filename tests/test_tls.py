import os
import ssl
from pathlib import Path

import certifi
import httpx
import pytest

from task_ai_service.api.app import create_app
from task_ai_service.llm.tls import create_tls_context


@pytest.mark.parametrize("missing_parent", [False, True])
def test_keylog_environment_is_ignored_without_disabling_verification(
    tmp_path, monkeypatch, missing_parent
):
    target = tmp_path / "missing" / "sslkeys.log" if missing_parent else tmp_path / "sslkeys.log"
    monkeypatch.setenv("SSLKEYLOGFILE", str(target))

    context = create_tls_context()

    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    assert context.minimum_version >= ssl.TLSVersion.TLSv1_2
    assert context.cert_store_stats()["x509_ca"] > 0
    assert context.keylog_filename is None
    assert not target.exists()
    assert os.environ["SSLKEYLOGFILE"] == str(target)


def test_additional_ca_bundle_preserves_verification():
    context = create_tls_context(Path(certifi.where()))
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    assert context.cert_store_stats()["x509_ca"] > 0


def test_invalid_ca_bundle_is_not_silently_ignored(tmp_path):
    bundle = tmp_path / "invalid.pem"
    bundle.write_text("not a certificate", encoding="utf-8")
    with pytest.raises(ssl.SSLError):
        create_tls_context(bundle)


async def test_service_starts_with_unwritable_sslkeylogfile(settings, tmp_path, monkeypatch):
    target = tmp_path / "missing" / "sslkeys.log"
    monkeypatch.setenv("SSLKEYLOGFILE", str(target))
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/health")
            assert response.status_code == 200
            assert response.json()["status"] == "ok"
    assert not target.exists()
    assert os.environ["SSLKEYLOGFILE"] == str(target)
