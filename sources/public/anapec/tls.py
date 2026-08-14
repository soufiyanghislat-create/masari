"""Strict native TLS transport for ANAPEC.

Masari never disables certificate verification. ANAPEC's certificate chain can
be completed by the macOS trust store even when certifi/OpenSSL alone cannot
complete it, so this source uses a ``truststore.SSLContext`` explicitly instead
of mutating Python's global ``ssl`` module.
"""
from __future__ import annotations

import ssl


def create_native_ssl_context() -> ssl.SSLContext:
    """Return a system-trust SSL context that requires certificate verification."""
    import truststore

    ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


def native_tls_available() -> bool:
    """Return True only when a strict native context can be constructed."""
    try:
        ctx = create_native_ssl_context()
    except Exception:
        return False
    return bool(ctx.check_hostname and ctx.verify_mode == ssl.CERT_REQUIRED)
