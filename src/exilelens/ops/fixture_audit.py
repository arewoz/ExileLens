"""Inventory existing fixtures. Do not rewrite the corpus."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from exilelens.ops.paths import fixture_corpus_path, repo_root


@dataclass
class FixtureAudit:
    missing: list[str] = field(default_factory=list)
    present: list[str] = field(default_factory=list)
    roles: dict[str, str] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        return {
            "present": len(self.present),
            "missing": list(self.missing),
            "roles": dict(self.roles),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "present": self.present,
            "missing": self.missing,
            "roles": self.roles,
            "ok": not self.missing,
        }


def _walk_roles(prefix: str, node: Any, roles: dict[str, str]) -> None:
    if isinstance(node, str):
        roles[prefix] = node
        return
    if isinstance(node, dict):
        for key, value in node.items():
            if key in {"version", "keep_small"}:
                continue
            child = f"{prefix}.{key}" if prefix else str(key)
            _walk_roles(child, value, roles)


def audit_fixture_corpus(root: Path | None = None) -> FixtureAudit:
    base = root or repo_root()
    data = json.loads(fixture_corpus_path(base).read_text(encoding="utf-8"))
    roles: dict[str, str] = {}
    _walk_roles("", data, roles)
    present: list[str] = []
    missing: list[str] = []
    for role, rel in roles.items():
        path = base / rel
        if path.is_file():
            present.append(f"{role}={rel}")
        else:
            missing.append(f"{role}={rel}")
    return FixtureAudit(missing=missing, present=present, roles=roles)
