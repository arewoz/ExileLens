from __future__ import annotations

from exilelens.error_catalog.session import StructuredErrorReport


def overlay_error_hint(report: StructuredErrorReport | None) -> str:
    if report is None:
        return ""
    return f"{report.code}: {report.recovery_action}"


def diagnostics_error_summary(report: StructuredErrorReport | None) -> str:
    if report is None:
        return ""
    return f"{report.code} — {report.title}. {report.recovery_action}"
