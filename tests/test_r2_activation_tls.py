"""The cloud client TLS context stays strict and falls back safely (activation fix)."""

from __future__ import annotations

import ssl
import sys

import pytest

from exilelens.cloud import tls


def _assert_strict(context: ssl.SSLContext) -> None:
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    assert context.minimum_version >= ssl.TLSVersion.TLSv1_2


def test_client_context_is_always_verifying() -> None:
    _assert_strict(tls.client_context())


def test_non_windows_has_no_root_store_context(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tls.sys, "platform", "linux")
    assert tls.windows_root_store_context() is None


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ROOT store")
def test_windows_root_store_context_is_strict() -> None:
    context = tls.windows_root_store_context()
    if context is None:  # store unreadable on this machine: the fallback is covered below
        pytest.skip("ROOT store not usable")
    _assert_strict(context)
    assert context.cert_store_stats()["x509_ca"] >= tls.MIN_EXPECTED_ROOTS


def test_too_small_store_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tls.sys, "platform", "win32")
    monkeypatch.setattr(ssl, "enum_certificates", lambda store: [], raising=False)
    assert tls.windows_root_store_context() is None
    monkeypatch.undo()
    monkeypatch.setattr(tls, "windows_root_store_context", lambda: None)
    _assert_strict(tls.client_context())


def test_store_error_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(store: str):
        raise OSError("store unavailable")

    monkeypatch.setattr(tls.sys, "platform", "win32")
    monkeypatch.setattr(ssl, "enum_certificates", boom, raising=False)
    assert tls.windows_root_store_context() is None
    monkeypatch.undo()  # stdlib would otherwise re-read the broken store
    monkeypatch.setattr(tls, "windows_root_store_context", lambda: None)
    _assert_strict(tls.client_context())


def test_default_opener_is_cached_callable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tls, "_opener", None)
    first = tls.default_opener()
    second = tls.default_opener()
    assert callable(first)
    assert first.__self__ is second.__self__
