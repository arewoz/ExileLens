"""Persistent item evaluation history with dedupe and stale labeling."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from poe2value.app.settings import app_data_dir
from poe2value.items.history import ResultHistory, baseline_identity
from poe2value.items.upgrade_path import history_upgrade_path_hint

DEFAULT_HISTORY_LIMIT = 50
HISTORY_FILENAME = "item_history.json"


def history_store_path() -> Path:
    return app_data_dir() / HISTORY_FILENAME


class PersistentItemHistory(ResultHistory):
    def __init__(self, limit: int = DEFAULT_HISTORY_LIMIT, *, path: Path | None = None) -> None:
        super().__init__(limit=limit)
        self.path = path or history_store_path()
        self._seen: dict[str, int] = {}
        self._load()

    def record(self, result: dict[str, Any], *, identity: str, current: bool = True) -> dict[str, Any]:
        content_hash = str((result.get("raw_input") or {}).get("content_hash") or "")
        recommendation = result.get("recommendation") or {}
        outcome = recommendation.get("evaluation_outcome") or {}
        dedupe_key = f"{content_hash}|{identity}"
        seen_count = self._seen.get(dedupe_key, 0) + 1
        self._seen[dedupe_key] = seen_count
        entry = {
            "id": f"{content_hash[:12]}-{int(time.time() * 1000)}",
            "recorded_at": time.time(),
            "status": "CURRENT" if current else "HISTORICAL",
            "baseline_identity": identity,
            "evaluation_context": dict(result.get("evaluation_context") or {}),
            "evaluation_identity": dict(result.get("evaluation_identity") or {}),
            "content_hash": content_hash,
            "item_name": (result.get("pob_parse") or {}).get("display_name"),
            # Persist the player-facing verdict, not Ranking V2's compatibility
            # verdict. Older stored payloads still fall back to that field.
            "verdict": outcome.get("verdict") or recommendation.get("verdict"),
            "best_slot": (result.get("best_slot") or {}).get("label"),
            "upgrade_path_hint": history_upgrade_path_hint(result),
            "seen_count": seen_count,
            "stale": False,
            "result": result,
        }
        self._entries = [item for item in self._entries if not (item.get("content_hash") == content_hash and item.get("baseline_identity") == identity)]
        self._entries.append(entry)
        self._entries = self._entries[-self.limit :]
        self._persist()
        return entry

    def mark_historical(self, except_identity: str | None = None) -> None:
        for entry in self._entries:
            if except_identity is None or entry.get("baseline_identity") != except_identity:
                entry["status"] = "HISTORICAL"
                entry["stale"] = True
        self._persist()

    def mark_stale_for_identity(self, identity: str) -> None:
        for entry in self._entries:
            if entry.get("baseline_identity") != identity:
                entry["stale"] = True
                entry["status"] = "HISTORICAL"
        self._persist()

    def find_by_content(self, content_hash: str, identity: str) -> dict[str, Any] | None:
        for entry in reversed(self._entries):
            if entry.get("content_hash") == content_hash and entry.get("baseline_identity") == identity:
                return entry
        return None

    def _persist(self) -> None:
        payload = {
            "limit": self.limit,
            "seen": self._seen,
            "entries": [
                {
                    "id": item.get("id"),
                    "recorded_at": item.get("recorded_at"),
                    "status": item.get("status"),
                    "baseline_identity": item.get("baseline_identity"),
                    "evaluation_context": item.get("evaluation_context") or {},
                    "evaluation_identity": item.get("evaluation_identity") or {},
                    "content_hash": item.get("content_hash"),
                    "item_name": item.get("item_name"),
                    "verdict": item.get("verdict"),
                    "best_slot": item.get("best_slot"),
                    "seen_count": item.get("seen_count"),
                    "stale": item.get("stale"),
                }
                for item in self._entries
            ],
        }
        try:
            self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return
        self.limit = int(data.get("limit") or self.limit)
        self._seen = dict(data.get("seen") or {})
        self._entries = list(data.get("entries") or [])


def make_baseline_identity_from_controller(
    *,
    fingerprint: str,
    build_path: str,
    loadout: str,
    item_set: str,
    context: str,
    generation: int,
) -> str:
    return baseline_identity(
        fingerprint=fingerprint,
        build_path=build_path,
        loadout=loadout,
        item_set=item_set,
        context=context,
        generation=generation,
    )
