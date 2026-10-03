"""Where (and whether) ExileLens may talk to the ExileLens cloud service.

The cloud service is optional infrastructure. Everything here fails closed: with no explicit,
valid https endpoint, ``cloud_base_url()`` is ``None`` and every cloud feature stays off while the
rest of ExileLens is unaffected.

* Packaged builds read ``release_config.json`` (generated for a release from an explicit repository
  variable; committed empty). A ``*.workers.dev`` development host is refused in packaged builds so a
  temporary staging URL cannot be shipped by accident (the release gate checks this too).
* Source runs may use ``EXILELENS_CLOUD_URL`` for local/staging development (``http://127.0.0.1`` is
  allowed for ``wrangler dev``).
* ``security_audit.network_disabled()`` switches all cloud traffic off.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

CONFIG_FILE = "release_config.json"
ENV_OVERRIDE = "EXILELENS_CLOUD_URL"
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]"}


def _frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def normalize_base_url(value: object, *, allow_local: bool = False, allow_workers_dev: bool = False) -> str | None:
    text = str(value or "").strip().rstrip("/")
    if not text:
        return None
    parts = urlsplit(text)
    host = (parts.hostname or "").lower()
    if parts.username or parts.password or parts.query or parts.fragment or parts.path not in ("", "/"):
        return None
    if parts.scheme == "http":
        if not (allow_local and host in _LOCAL_HOSTS):
            return None
    elif parts.scheme != "https" or not host:
        return None
    if host.endswith(".workers.dev") and not allow_workers_dev:
        return None
    return f"{parts.scheme}://{parts.netloc}"


def release_config_url() -> str | None:
    try:
        payload = json.loads(Path(__file__).with_name(CONFIG_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return None
    if not isinstance(payload, dict) or payload.get("schema") != 1:
        return None
    return normalize_base_url(payload.get("api_base_url"))


def cloud_base_url() -> str | None:
    """The validated API origin, or ``None`` when cloud features must stay off."""
    try:
        from exilelens.security_audit import network_disabled

        if network_disabled():
            return None
    except Exception:  # noqa: BLE001 - an unreadable kill switch must not enable networking
        pass
    if _frozen():
        return release_config_url()
    override = os.environ.get(ENV_OVERRIDE, "").strip()
    if override:
        return normalize_base_url(override, allow_local=True, allow_workers_dev=True)
    return release_config_url()
