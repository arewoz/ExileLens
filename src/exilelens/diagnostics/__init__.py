"""Diagnostics 2.0 — local support summaries, event history, and bundles."""

from exilelens.diagnostics.bundle import SupportBundleError, build_support_bundle_bytes, write_support_bundle
from exilelens.diagnostics.events import (
    clear_event_history,
    enable_verbose_mode,
    event_buffer,
    record_event,
    support_session_id,
    verbose_mode_active,
)
from exilelens.diagnostics.summary import build_extended_summary, render_extended_summary_text

__all__ = [
    "SupportBundleError",
    "build_extended_summary",
    "build_support_bundle_bytes",
    "clear_event_history",
    "enable_verbose_mode",
    "event_buffer",
    "record_event",
    "render_extended_summary_text",
    "support_session_id",
    "verbose_mode_active",
    "write_support_bundle",
]
