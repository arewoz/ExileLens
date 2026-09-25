"""Central sanitization for exported diagnostic material."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

_WINDOWS_PATH = re.compile(
    r"(?i)([A-Z]:\\(?:[^\\\r\n<>\"|?*]+\\)*[^\\\r\n<>\"|?*]+|\\\\[^\\\r\n]+\\[^\\\r\n]+)"
)
_HOME_UNIX = re.compile(r"(?i)(/home/[^/\s]+|/Users/[^/\s]+)")
_USERPROFILE = re.compile(r"(?i)\bUsers\\[^\\\r\n]+")
_TOKEN_LIKE = re.compile(
    r"(?i)\b(?:bearer\s+[a-z0-9._\-]+|ghp_[a-z0-9]{20,}|github_pat_[a-z0-9_]{20,}|"
    r"sk-[a-z0-9]{20,}|api[_-]?key\s*[:=]\s*['\"]?[a-z0-9._\-]{8,})"
)
_XML_DECL = re.compile(r"(?i)<\?xml\b.*?\?>|<(?:Item|Build|PathOfBuilding|PoB)[\s>]")


def _redact_path(match: re.Match[str]) -> str:
    return "<path>"


def sanitize_text(value: str, *, max_len: int = 4000) -> str:
    text = str(value or "")
    if not text:
        return ""
    text = _WINDOWS_PATH.sub(_redact_path, text)
    text = _HOME_UNIX.sub("<home>", text)
    text = _USERPROFILE.sub("Users\\<user>", text)
    text = _TOKEN_LIKE.sub("<redacted-token>", text)
    if _XML_DECL.search(text):
        return "<redacted-xml>"
    if len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text


def _sanitize_url(value: str) -> str:
    try:
        parts = urlsplit(value)
    except Exception:  # noqa: BLE001
        return "<url>"
    if parts.username or parts.password:
        host = parts.hostname or ""
        return urlunsplit((parts.scheme, f"<credentials>@{host}", parts.path, parts.query, parts.fragment))
    return sanitize_text(value, max_len=512)


def sanitize_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 8:
        return "<truncated>"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if value.startswith(("http://", "https://")):
            return _sanitize_url(value)
        return sanitize_text(value)
    if isinstance(value, (list, tuple)):
        return [sanitize_value(item, depth=depth + 1) for item in value[:64]]
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 64:
                out["<truncated>"] = True
                break
            safe_key = sanitize_text(str(key), max_len=120)
            if safe_key.lower() in {"password", "token", "secret", "authorization"}:
                out[safe_key] = "<redacted>"
            else:
                out[safe_key] = sanitize_value(item, depth=depth + 1)
        return out
    return sanitize_text(str(value), max_len=256)


def _sanitize_log_line(line: str) -> str:
    stripped = line.strip()
    if not stripped:
        return ""
    if re.search(r"(?i)\b(rarity:|item class:|<item>|clipboard=)", line):
        return "<redacted-item-or-clipboard>"
    if "=" not in stripped and re.search(r"[A-Za-z]{3,}", stripped):
        return "<redacted-log-line>"
    return sanitize_text(line.rstrip("\n"), max_len=2000)


def sanitize_log_lines(lines: list[str]) -> list[str]:
    sanitized: list[str] = []
    for line in lines:
        clean = _sanitize_log_line(line)
        if clean:
            sanitized.append(clean)
    return sanitized
