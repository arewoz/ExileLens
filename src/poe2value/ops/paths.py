"""Repo-root helpers for developer ops commands."""

from __future__ import annotations

from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def ops_dir(root: Path | None = None) -> Path:
    return (root or repo_root()) / "ops"


def compatibility_path(root: Path | None = None) -> Path:
    return ops_dir(root) / "compatibility.json"


def regression_registry_path(root: Path | None = None) -> Path:
    return ops_dir(root) / "regression_registry.json"


def fixture_corpus_path(root: Path | None = None) -> Path:
    return ops_dir(root) / "fixture_corpus.json"


def patch_test_map_path(root: Path | None = None) -> Path:
    return ops_dir(root) / "patch_test_map.json"
