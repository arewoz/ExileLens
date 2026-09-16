"""Versioned on-disk MarketSignature store.

Atomic writes. Corruption never prevents Price Check startup. Unit tests must pass
an explicit path — the default file is the owner's app-data store.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from threading import Lock
from typing import Any

from poe2value.app.settings import app_data_dir
from poe2value.price_check.market_signatures import (
    QUERY_VOCABULARY_VERSION,
    SIGNATURE_SCHEMA_VERSION,
    MarketSignature,
    SignatureMaturity,
    SignatureMetrics,
)
from poe2value.price_check.stat_registry import STAT_REGISTRY_VERSION

logger = logging.getLogger(__name__)

SIGNATURE_FILENAME = "market_signatures.json"


def default_signature_store_path() -> Path:
    return app_data_dir() / SIGNATURE_FILENAME


class MarketSignatureStore:
    def __init__(self, path: Path | None = None, *, persist: bool = True) -> None:
        self.path = path
        self.persist = bool(persist) and path is not None
        self.metrics = SignatureMetrics()
        self._lock = Lock()
        self._signatures: dict[str, MarketSignature] = {}
        self._quarantined = False
        if self.path is not None:
            self.load()

    def get(self, signature_id: str) -> MarketSignature | None:
        with self._lock:
            return self._signatures.get(signature_id)

    def blocks_synthetic_persist(self) -> bool:
        """Synthetic/test learning must never mutate the owner's app-data store."""
        if not self.persist or self.path is None:
            return False
        try:
            return self.path.resolve() == default_signature_store_path().resolve()
        except OSError:
            return True

    def put(self, signature: MarketSignature, *, synthetic: bool = False) -> None:
        if synthetic and self.blocks_synthetic_persist():
            return
        with self._lock:
            self._signatures[signature.signature_id] = signature
        self._save()

    def all(self) -> tuple[MarketSignature, ...]:
        with self._lock:
            return tuple(self._signatures.values())

    def clear(self) -> None:
        with self._lock:
            self._signatures.clear()
            self.metrics = SignatureMetrics()

    def load(self) -> None:
        if self.path is None or not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.warning("market signature store unreadable; quarantining: %s", exc)
            self._quarantine()
            return
        if not isinstance(payload, dict):
            self._quarantine()
            return
        schema = int(payload.get("schema_version") or 0)
        if schema != SIGNATURE_SCHEMA_VERSION:
            logger.warning("market signature schema %s incompatible; ignoring AUTO authority", schema)
        vocab = str(payload.get("vocabulary_version") or "")
        registry = str(payload.get("registry_version") or "")
        loaded: dict[str, MarketSignature] = {}
        for row in payload.get("signatures") or []:
            if not isinstance(row, dict):
                continue
            try:
                signature = MarketSignature.from_dict(row)
            except (TypeError, ValueError, KeyError) as exc:
                logger.warning("skipped invalid market signature: %s", exc)
                continue
            if not signature.signature_id:
                continue
            incompatible = (
                signature.schema_version != SIGNATURE_SCHEMA_VERSION
                or vocab != QUERY_VOCABULARY_VERSION
                or registry != STAT_REGISTRY_VERSION
                or signature.vocabulary_version != QUERY_VOCABULARY_VERSION
                or signature.registry_version != STAT_REGISTRY_VERSION
            )
            if incompatible:
                signature.maturity = SignatureMaturity.DEGRADED
            loaded[signature.signature_id] = signature
        with self._lock:
            self._signatures = loaded

    def _quarantine(self) -> None:
        self._quarantined = True
        with self._lock:
            self._signatures = {}
        if self.path is None or not self.path.exists():
            return
        try:
            corrupt = self.path.with_name(self.path.name + ".corrupt")
            os.replace(self.path, corrupt)
        except OSError:
            logger.warning("could not quarantine corrupt signature store at %s", self.path)

    def _save(self) -> None:
        if not self.persist or self.path is None:
            return
        with self._lock:
            payload: dict[str, Any] = {
                "schema_version": SIGNATURE_SCHEMA_VERSION,
                "vocabulary_version": QUERY_VOCABULARY_VERSION,
                "registry_version": STAT_REGISTRY_VERSION,
                "signatures": [row.to_dict() for row in self._signatures.values()],
            }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            encoded = json.dumps(payload, indent=2)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(encoded, encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:
            logger.warning("could not persist market signatures to %s", self.path)


_SHARED: MarketSignatureStore | None = None
_SHARED_LOCK = Lock()


def shared_signature_store() -> MarketSignatureStore:
    global _SHARED
    with _SHARED_LOCK:
        if _SHARED is None:
            _SHARED = MarketSignatureStore(default_signature_store_path(), persist=True)
        return _SHARED


def reset_shared_signature_store(store: MarketSignatureStore | None = None) -> None:
    global _SHARED
    with _SHARED_LOCK:
        if store is None:
            _SHARED = MarketSignatureStore(path=None, persist=False)
        else:
            _SHARED = store
