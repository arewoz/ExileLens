"""Per-category local state: a random install ID and a small bounded disk queue.

Usage statistics and error reports each own a separate directory, so deleting one category (opt-out)
cannot touch the other, and the two IDs are never derived from or stored next to each other.

    %LOCALAPPDATA%\\ExileLens\\cloud\\telemetry\\{id, queue.jsonl}
    %LOCALAPPDATA%\\ExileLens\\cloud\\errors\\{id, queue.jsonl}

Nothing is created until a category is turned on and has something to say; turning it off removes the
whole directory.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from exilelens.cloud import contract

logger = logging.getLogger(__name__)

_UUID_RE = contract._compile(contract.schema()["types"]["uuid"]["regex"])


def cloud_dir() -> Path:
    from exilelens.app.settings import app_data_dir

    return app_data_dir() / "cloud"


class CategoryStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.id_path = root / "id"
        self.queue_path = root / "queue.jsonl"

    # -- identity -------------------------------------------------------------------------------
    def read_id(self) -> str | None:
        try:
            value = self.id_path.read_text(encoding="ascii").strip()
        except (OSError, UnicodeError):
            return None
        return value if _UUID_RE.fullmatch(value) else None

    def get_or_create_id(self) -> str:
        existing = self.read_id()
        if existing:
            return existing
        # uuid4: 122 random bits, no hardware/user/network derived component.
        value = str(uuid.uuid4())
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.id_path.with_name("id.tmp")
        tmp.write_text(value, encoding="ascii")
        os.replace(tmp, self.id_path)
        return value

    # -- queue ----------------------------------------------------------------------------------
    def load_queue(self, now: float | None = None) -> list[dict[str, Any]]:
        """Entries ``{"q": enqueued_epoch, "item": {...}}``; expired, corrupt or oversized data is dropped."""
        limits = contract.limits()
        now = time.time() if now is None else now
        ttl = limits["client_queue_ttl_hours"] * 3600
        entries: list[dict[str, Any]] = []
        try:
            if not self.queue_path.is_file() or self.queue_path.stat().st_size > 4 * limits["client_queue_max_bytes"]:
                return []
            lines = self.queue_path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            return []
        for line in lines:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if (
                isinstance(row, dict)
                and set(row) == {"q", "item"}
                and isinstance(row["item"], dict)
                and isinstance(row["q"], (int, float))
                and 0 <= now - row["q"] <= ttl
            ):
                entries.append(row)
        return self.bound(entries)

    @staticmethod
    def bound(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Newest entries that fit the event and byte caps (oldest are dropped first)."""
        limits = contract.limits()
        kept = entries[-limits["client_queue_max_events"] :]
        total = 0
        result: list[dict[str, Any]] = []
        for row in reversed(kept):
            size = len(json.dumps(row, separators=(",", ":"))) + 1
            if total + size > limits["client_queue_max_bytes"]:
                break
            total += size
            result.append(row)
        result.reverse()
        return result

    def save_queue(self, entries: list[dict[str, Any]]) -> None:
        entries = self.bound(entries)
        if not entries:
            self.queue_path.unlink(missing_ok=True)
            return
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.queue_path.with_name("queue.jsonl.tmp")
        tmp.write_text("\n".join(json.dumps(row, separators=(",", ":")) for row in entries), encoding="utf-8")
        os.replace(tmp, self.queue_path)

    # -- deletion -------------------------------------------------------------------------------
    def purge(self) -> None:
        """Delete the ID and the queue (the whole category directory)."""
        try:
            shutil.rmtree(self.root)
        except FileNotFoundError:
            pass
        except OSError:
            logger.warning("cloud_purge_incomplete category=%s", self.root.name)
            for path in (self.id_path, self.queue_path, self.id_path.with_name("id.tmp"), self.queue_path.with_name("queue.jsonl.tmp")):
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass

    def exists(self) -> bool:
        return self.root.exists()
