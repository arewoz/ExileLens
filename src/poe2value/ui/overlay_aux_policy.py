"""Seam between the committed overlay core and the in-progress ITEM_PRO companion UX.

MARKET-01B9A. `ui/overlay.py` hosts both the build-evaluation surface and the Price
Check surface. Its build-evaluation branch grew hard imports of ITEM_PRO presentation
policy that was never committed, which made the whole module — and therefore Price
Check — unimportable from a clean checkout.

Price Check uses none of that policy. So the committed overlay depends on *this*
module, which resolves the policy at import time: the ITEM_PRO implementation when it
is present, otherwise committed defaults that simply never show the companion card.

The companion widget itself (`overlay_aux_companion.AuxEdgeCompanion`) is a generic
titled side card and is committed. What lives here is only the decision of *whether*
to show it and *what* to put in it.

ITEM-UX-COMPRESS: that decision now lives on main, in `items.presentation` and
`items.presentation_copy`, so `_resolve()` binds to `item_pro` and the Companion is
available again. The committed defaults below stay as the seam's floor: if those
modules ever lose the policy, Price Check and the overlay still import, and the card
simply does not appear.
"""

from __future__ import annotations

from typing import Any, Callable

__all__ = [
    "aux_policy_source",
    "apply_aux_companion_policy",
    "build_aux_trace",
    "build_surface_presentation",
    "should_show_aux_companion",
    "sync_current_edge",
]


def _default_should_show_aux_companion(presentation: dict[str, Any]) -> bool:
    """Committed default: the companion card is an ITEM_PRO feature, so never shown."""
    return False


def _default_apply_aux_companion_policy(presentation: dict[str, Any]) -> None:
    """Committed default: no companion copy policy to apply."""
    return None


def _default_sync_current_edge(presentation: dict[str, Any], result: dict[str, Any]) -> None:
    """Committed default: no current-edge enrichment."""
    return None


def _default_build_aux_trace(
    presentation: dict[str, Any],
    result: dict[str, Any],
    *,
    overlay_generation: int,
    aux_visible: bool,
    aux_show_called: bool,
    aux_visible_after_show: bool,
) -> dict[str, Any]:
    return {
        "aux_policy": "committed_default",
        "overlay_generation": overlay_generation,
        "aux_visible": aux_visible,
        "aux_show_called": aux_show_called,
        "aux_visible_after_show": aux_visible_after_show,
    }


def _default_build_surface_presentation(result: dict[str, Any], **kwargs: Any) -> dict[str, Any] | None:
    """Committed default: no surface-specific builder — caller falls back."""
    return None


def _resolve() -> tuple[str, dict[str, Callable[..., Any]]]:
    """Bind to the ITEM_PRO implementation when present, else committed defaults."""
    resolved: dict[str, Callable[..., Any]] = {
        "should_show_aux_companion": _default_should_show_aux_companion,
        "apply_aux_companion_policy": _default_apply_aux_companion_policy,
        "sync_current_edge": _default_sync_current_edge,
        "build_aux_trace": _default_build_aux_trace,
        "build_surface_presentation": _default_build_surface_presentation,
    }

    try:
        from poe2value.items import presentation as _presentation
        from poe2value.items import presentation_copy as _presentation_copy
    except Exception:  # pragma: no cover - core modules always import
        return "committed_default", resolved

    mapping = (
        ("should_show_aux_companion", _presentation, "should_show_passive_aux_companion"),
        ("sync_current_edge", _presentation, "sync_presentation_current_edge"),
        ("build_aux_trace", _presentation, "build_passive_aux_trace"),
        ("build_surface_presentation", _presentation, "build_presentation_for_surface"),
        ("apply_aux_companion_policy", _presentation_copy, "apply_passive_aux_companion_policy"),
    )
    found = 0
    for key, module, attr in mapping:
        impl = getattr(module, attr, None)
        if callable(impl):
            resolved[key] = impl
            found += 1

    if found == len(mapping):
        return "item_pro", resolved
    if found == 0:
        return "committed_default", resolved
    return "partial", resolved


_SOURCE, _IMPL = _resolve()


def aux_policy_source() -> str:
    """`item_pro`, `committed_default`, or `partial` — logged at overlay construction."""
    return _SOURCE


def should_show_aux_companion(presentation: dict[str, Any]) -> bool:
    return bool(_IMPL["should_show_aux_companion"](presentation))


def apply_aux_companion_policy(presentation: dict[str, Any]) -> None:
    _IMPL["apply_aux_companion_policy"](presentation)


def sync_current_edge(presentation: dict[str, Any], result: dict[str, Any]) -> None:
    _IMPL["sync_current_edge"](presentation, result)


def build_aux_trace(
    presentation: dict[str, Any],
    result: dict[str, Any],
    *,
    overlay_generation: int,
    aux_visible: bool,
    aux_show_called: bool,
    aux_visible_after_show: bool,
) -> dict[str, Any]:
    return _IMPL["build_aux_trace"](
        presentation,
        result,
        overlay_generation=overlay_generation,
        aux_visible=aux_visible,
        aux_show_called=aux_show_called,
        aux_visible_after_show=aux_visible_after_show,
    )


def build_surface_presentation(result: dict[str, Any], **kwargs: Any) -> dict[str, Any] | None:
    """Surface-aware presentation, or None when the caller should use the base builder."""
    return _IMPL["build_surface_presentation"](result, **kwargs)
