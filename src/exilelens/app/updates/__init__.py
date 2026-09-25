"""Secure in-app update pipeline (check, download, verify, hand off to updater)."""

from exilelens.app.updates.service import UpdateService
from exilelens.app.updates.version import ExileLensVersion, Release

__all__ = ["UpdateService", "ExileLensVersion", "Release"]
