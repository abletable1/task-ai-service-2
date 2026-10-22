"""Verified client TLS without inheriting process-wide SSL key logging."""

import ssl
from pathlib import Path


def create_tls_context(ca_bundle: Path | None = None) -> ssl.SSLContext:
    # create_default_context() also opens SSLKEYLOGFILE from the process environment.
    # That optional debug output must not affect startup or expose session keys.
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_default_certs(ssl.Purpose.SERVER_AUTH)
    if ca_bundle is not None:
        context.load_verify_locations(cafile=str(ca_bundle))
    return context
