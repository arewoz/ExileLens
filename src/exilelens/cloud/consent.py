"""Consent logic, independent of any UI.

Two switches, both OFF until the user turns them on, neither implying the other, and no feature of
ExileLens depends on either. Choices are stored with the contract's ``consent_version``: if a later
release materially changes what can be collected, the version increases and older choices count as OFF
until the user confirms again.
"""

from __future__ import annotations

from typing import Any, Callable

from exilelens.cloud import contract


def current_consent_version() -> int:
    return int(contract.schema()["consent_version"])


def set_consent(
    settings: Any,
    *,
    usage: bool | None = None,
    errors: bool | None = None,
    cloud: Any | None = None,
    save: Callable[[Any], None] | None = None,
) -> None:
    """Record the user's choice(s) and make the running services match immediately."""
    if usage is not None:
        settings.send_usage_stats = bool(usage)
    if errors is not None:
        settings.send_error_reports = bool(errors)
    settings.privacy_consent_version = current_consent_version()
    settings.privacy_card_resolved = True
    if save is None:
        from exilelens.app.settings import save_settings as save
    save(settings)
    if cloud is not None:
        cloud.apply_consent()


def dismiss_card(settings: Any, *, save: Callable[[Any], None] | None = None) -> None:
    """"Not now": remember that the card was answered without changing either switch."""
    settings.privacy_card_resolved = True
    if save is None:
        from exilelens.app.settings import save_settings as save
    save(settings)


def should_show_card(settings: Any, cloud: Any | None, *, onboarding_pending: bool) -> bool:
    """One non-modal card after onboarding; never when this build has no cloud endpoint."""
    if cloud is None or not cloud.configured() or onboarding_pending:
        return False
    stale = int(getattr(settings, "privacy_consent_version", 0) or 0) < current_consent_version()
    if bool(getattr(settings, "privacy_card_resolved", False)) and not (
        stale and (settings.send_usage_stats or settings.send_error_reports)
    ):
        return False
    return True
