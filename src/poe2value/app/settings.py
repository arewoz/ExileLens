from __future__ import annotations

import json
import logging
import os
import shutil
import time
from dataclasses import asdict, dataclass, field, fields
from enum import Enum
from pathlib import Path
from typing import Any


CURRENT_SCHEMA_VERSION = 20
DEFAULT_PRICE_CHECK_HOTKEY = "shift+c"
DEFAULT_REFINE_PRICE_HOTKEY = "ctrl+shift+r"
DEFAULT_POB_PATH = (os.environ.get("POB2_PATH") or "").strip()


class BaselineMode(str, Enum):
    POB_BUILD_GEAR = "POB_BUILD_GEAR"


class OverlayPositionMode(str, Enum):
    NEAR_ITEM = "near_item"
    FIXED_CORNER = "fixed_corner"


def app_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())
    path = Path(base) / "poe2-value-overlay"
    path.mkdir(parents=True, exist_ok=True)
    return path


def settings_path() -> Path:
    return app_data_dir() / "settings.json"


def _resolve_pob_path(raw: str | None) -> str:
    candidate = str(raw or "").strip()
    if not candidate:
        return DEFAULT_POB_PATH
    path = Path(candidate)
    parts_lower = [part.lower() for part in path.parts]
    if "temp" in parts_lower and any("pytest" in part for part in parts_lower):
        return DEFAULT_POB_PATH
    return candidate


@dataclass
class OverlayPosition:
    corner: str = "top_right"
    x: int | None = None
    y: int | None = None


@dataclass
class AppSettings:
    schema_version: int = CURRENT_SCHEMA_VERSION
    pob_path: str = field(default_factory=lambda: DEFAULT_POB_PATH)
    build_path: str = ""
    context: str = "MAP"
    overlay_enabled: bool = True
    overlay_position: OverlayPosition = field(default_factory=OverlayPosition)
    overlay_position_mode: str = OverlayPositionMode.NEAR_ITEM.value
    overlay_near_offset_px: int = 40
    overlay_auto_hide_seconds: float = 0.0
    dedup_window_seconds: float = 3.0
    debug: bool = False
    first_run_complete: bool = False
    selected_loadout: str = ""
    item_set_follow_loadout: bool = True
    selected_item_set_id: str = ""
    baseline_mode: str = BaselineMode.POB_BUILD_GEAR.value
    value_profile: str = "BALANCED"
    tree_heatmap_metric: str = "value_per_point"
    tree_ranking_mode: str = "efficiency"
    tree_analysis_radius: int = 1
    tree_show_allocated: bool = True
    tree_show_frontier: bool = True
    tree_show_evaluated: bool = True
    tree_show_unevaluated: bool = True
    tree_show_notables: bool = True
    tree_show_keystones: bool = True
    tree_show_small: bool = True
    tree_overlay_enabled: bool = False
    tree_overlay_calibration: dict[str, Any] = field(default_factory=dict)
    tree_overlay_mode: str = "BUILD_PATH"
    tree_overlay_debug: bool = False
    tree_overlay_opacity: float = 0.95
    tree_overlay_marker_size: float = 1.0
    tree_overlay_line_width: float = 3.0
    tracked_build_path: str = ""
    tracked_tree_set_id: str = ""
    dashboard_x: int | None = None
    dashboard_y: int | None = None
    dashboard_width: int = 1280
    dashboard_height: int = 860
    dashboard_last_page: str = "build"
    settings_dialog_x: int | None = None
    settings_dialog_y: int | None = None
    settings_dialog_width: int = 560
    settings_dialog_height: int = 420
    item_check_pro: dict[str, Any] = field(default_factory=dict)
    market_assist: dict[str, Any] = field(default_factory=dict)
    market_assist_overlay_x: int | None = None
    market_assist_overlay_y: int | None = None
    market_assist_overlay_width: int = 360
    market_assist_overlay_height: int = 420
    pinned_overlays: dict[str, Any] = field(default_factory=dict)
    market_league: str = ""
    market_league_mode: str = "AUTO"
    market_league_cache: list[str] = field(default_factory=list)
    market_league_cache_at: float = 0.0
    live_market_mode: str = "auto"
    strict_live: bool = True
    price_check_enabled: bool = True
    price_check_hotkey: str = DEFAULT_PRICE_CHECK_HOTKEY
    price_check_refine_hotkey: str = DEFAULT_REFINE_PRICE_HOTKEY
    price_check_capture_timeout_ms: int = 600
    price_check_release_wait_ms: int = 500
    price_check_diagnostic_mode: str = ""
    ui_scale: float = 1.0
    show_hotkey_hints: bool = True
    hotkey_hints_dismissed: bool = False
    hotkey_hints_success_count: int = 0
    update_last_check_at: float = 0.0
    update_latest_version: str = ""
    update_notified_version: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AppSettings:
        version = int(data.get("schema_version", 1))
        if version > CURRENT_SCHEMA_VERSION:
            data = {**data, "schema_version": CURRENT_SCHEMA_VERSION}
        pos = data.get("overlay_position") or {}
        overlay_position = OverlayPosition(
            corner=pos.get("corner", "top_right"),
            x=pos.get("x"),
            y=pos.get("y"),
        )
        return cls(
            schema_version=version,
            pob_path=_resolve_pob_path(data.get("pob_path")),
            build_path=str(data.get("build_path") or ""),
            context=str(data.get("context") or "MAP"),
            overlay_enabled=bool(data.get("overlay_enabled", True)),
            overlay_position=overlay_position,
            overlay_position_mode=str(
                data.get("overlay_position_mode") or OverlayPositionMode.NEAR_ITEM.value
            ),
            overlay_near_offset_px=int(data.get("overlay_near_offset_px", 40)),
            overlay_auto_hide_seconds=float(data.get("overlay_auto_hide_seconds", 0.0)),
            dedup_window_seconds=float(data.get("dedup_window_seconds", 3.0)),
            debug=bool(data.get("debug", False)),
            first_run_complete=bool(data.get("first_run_complete", False)),
            selected_loadout=str(data.get("selected_loadout") or ""),
            item_set_follow_loadout=bool(data.get("item_set_follow_loadout", True)),
            selected_item_set_id=str(data.get("selected_item_set_id") or ""),
            baseline_mode=_normalize_baseline_mode(data.get("baseline_mode")),
            value_profile=str(data.get("value_profile") or "BALANCED"),
            tree_heatmap_metric=str(data.get("tree_heatmap_metric") or "value_per_point"),
            tree_ranking_mode=str(data.get("tree_ranking_mode") or "efficiency"),
            tree_analysis_radius=int(data.get("tree_analysis_radius", 1)),
            tree_show_allocated=bool(data.get("tree_show_allocated", True)),
            tree_show_frontier=bool(data.get("tree_show_frontier", True)),
            tree_show_evaluated=bool(data.get("tree_show_evaluated", True)),
            tree_show_unevaluated=bool(data.get("tree_show_unevaluated", True)),
            tree_show_notables=bool(data.get("tree_show_notables", True)),
            tree_show_keystones=bool(data.get("tree_show_keystones", True)),
            tree_show_small=bool(data.get("tree_show_small", True)),
            tree_overlay_enabled=bool(data.get("tree_overlay_enabled", False)),
            tree_overlay_calibration=dict(data.get("tree_overlay_calibration") or {}),
            tree_overlay_mode=str(data.get("tree_overlay_mode") or "BUILD_PATH"),
            tree_overlay_debug=bool(data.get("tree_overlay_debug", False)),
            tree_overlay_opacity=float(data.get("tree_overlay_opacity", 0.95)),
            tree_overlay_marker_size=float(data.get("tree_overlay_marker_size", 1.0)),
            tree_overlay_line_width=float(data.get("tree_overlay_line_width", 3.0)),
            tracked_build_path=str(data.get("tracked_build_path") or ""),
            tracked_tree_set_id=str(data.get("tracked_tree_set_id") or ""),
            dashboard_x=int(data["dashboard_x"]) if data.get("dashboard_x") is not None else None,
            dashboard_y=int(data["dashboard_y"]) if data.get("dashboard_y") is not None else None,
            dashboard_width=int(data.get("dashboard_width", 1280)),
            dashboard_height=int(data.get("dashboard_height", 860)),
            dashboard_last_page=_normalize_dashboard_page(data.get("dashboard_last_page")),
            settings_dialog_x=int(data["settings_dialog_x"]) if data.get("settings_dialog_x") is not None else None,
            settings_dialog_y=int(data["settings_dialog_y"]) if data.get("settings_dialog_y") is not None else None,
            settings_dialog_width=int(data.get("settings_dialog_width", 560)),
            settings_dialog_height=int(data.get("settings_dialog_height", 420)),
            item_check_pro=dict(data.get("item_check_pro") or {}),
            market_assist=dict(data.get("market_assist") or {}),
            market_assist_overlay_x=int(data["market_assist_overlay_x"]) if data.get("market_assist_overlay_x") is not None else None,
            market_assist_overlay_y=int(data["market_assist_overlay_y"]) if data.get("market_assist_overlay_y") is not None else None,
            market_assist_overlay_width=int(data.get("market_assist_overlay_width", 360)),
            market_assist_overlay_height=int(data.get("market_assist_overlay_height", 420)),
            pinned_overlays=dict(data.get("pinned_overlays") or {}),
            market_league=str(data.get("market_league") or ""),
            market_league_mode=_normalize_league_mode(data.get("market_league_mode")),
            market_league_cache=[str(row) for row in (data.get("market_league_cache") or []) if str(row).strip()],
            market_league_cache_at=float(data.get("market_league_cache_at") or 0.0),
            live_market_mode=str(data.get("live_market_mode") or "auto"),
            strict_live=bool(data.get("strict_live", True)),
            price_check_enabled=bool(data.get("price_check_enabled", True)),
            price_check_hotkey=_normalize_price_check_hotkey(data.get("price_check_hotkey"), version=version),
            price_check_refine_hotkey=_normalize_refine_price_hotkey(data.get("price_check_refine_hotkey")),
            price_check_capture_timeout_ms=int(data.get("price_check_capture_timeout_ms", 600)),
            price_check_release_wait_ms=int(data.get("price_check_release_wait_ms", 500)),
            price_check_diagnostic_mode=str(data.get("price_check_diagnostic_mode") or ""),
            ui_scale=_normalize_ui_scale(data.get("ui_scale")),
            show_hotkey_hints=bool(data.get("show_hotkey_hints", True)),
            hotkey_hints_dismissed=bool(data.get("hotkey_hints_dismissed", False)),
            hotkey_hints_success_count=int(data.get("hotkey_hints_success_count", 0) or 0),
            update_last_check_at=float(data.get("update_last_check_at") or 0.0),
            update_latest_version=str(data.get("update_latest_version") or ""),
            update_notified_version=str(data.get("update_notified_version") or ""),
        )


class MarketLeagueMode(str, Enum):
    """AUTO follows build/character then the live active league; PINNED is the user's choice."""

    AUTO = "AUTO"
    PINNED = "PINNED"


def _normalize_baseline_mode(raw: Any) -> str:
    value = str(raw or "").strip().upper()
    if value == "LIVE_CHARACTER_GEAR":
        return BaselineMode.POB_BUILD_GEAR.value
    if value == BaselineMode.POB_BUILD_GEAR.value:
        return BaselineMode.POB_BUILD_GEAR.value
    return BaselineMode.POB_BUILD_GEAR.value


def _normalize_dashboard_page(raw: Any) -> str:
    value = str(raw or "").strip()
    if value in {"", "overview", "items", "character"}:
        return "build"
    return value


def _normalize_ui_scale(raw: Any) -> float:
    choices = (0.8, 1.0, 1.2, 1.4, 1.6)
    try:
        scale = float(raw)
    except (TypeError, ValueError):
        return 1.0
    return float(min(choices, key=lambda choice: abs(choice - scale)))


def _normalize_league_mode(raw: Any) -> str:
    value = str(raw or "").strip().upper()
    if value == MarketLeagueMode.PINNED.value:
        return MarketLeagueMode.PINNED.value
    return MarketLeagueMode.AUTO.value


def _normalize_refine_price_hotkey(raw: Any) -> str:
    """Refuse plain single-letter global hotkeys; default is Ctrl+Shift+R."""
    if raw is None or str(raw).strip() == "":
        return DEFAULT_REFINE_PRICE_HOTKEY
    normalized = str(raw).strip().lower()
    parts = [part.strip() for part in normalized.split("+") if part.strip()]
    if len(parts) < 2:
        return DEFAULT_REFINE_PRICE_HOTKEY
    return str(raw).strip().lower()


def _normalize_price_check_hotkey(raw: Any, *, version: int) -> str:
    """Migrate the old default and reject unsafe or malformed stored bindings."""
    if raw is None or str(raw).strip() == "":
        return DEFAULT_PRICE_CHECK_HOTKEY
    normalized = str(raw).strip().lower()
    if normalized in ("ctrl+d", "control+d"):
        return DEFAULT_PRICE_CHECK_HOTKEY
    from poe2value.platform.windows.hotkey_binding import validate_hotkey

    canonical, error = validate_hotkey(normalized, refine_hotkey=DEFAULT_REFINE_PRICE_HOTKEY)
    if error:
        logging.getLogger(__name__).warning(
            "invalid stored Item Check hotkey %r; using %s: %s",
            raw,
            DEFAULT_PRICE_CHECK_HOTKEY,
            error,
        )
        return DEFAULT_PRICE_CHECK_HOTKEY
    return canonical


@dataclass(frozen=True)
class SettingsLoadResult:
    settings: AppSettings
    loaded_from_disk: bool = False
    load_error: bool = False


def load_settings_result() -> SettingsLoadResult:
    path = settings_path()
    if not path.exists():
        return SettingsLoadResult(AppSettings(), loaded_from_disk=False)
    try:
        # utf-8-sig: Notepad and Windows PowerShell write a BOM, which plain utf-8 json
        # rejects -- that silently turned a hand-edited file into "corrupt, use defaults".
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            return SettingsLoadResult(AppSettings(), loaded_from_disk=True, load_error=True)
        return SettingsLoadResult(AppSettings.from_dict(data), loaded_from_disk=True)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return SettingsLoadResult(AppSettings(), loaded_from_disk=True, load_error=True)


def load_settings() -> AppSettings:
    return load_settings_result().settings


def save_settings(settings: AppSettings) -> None:
    path = settings_path()
    settings.schema_version = CURRENT_SCHEMA_VERSION
    payload = json.dumps(settings.to_dict(), indent=2)
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(payload, encoding="utf-8")
    tmp_path.replace(path)


_BACKUPS_KEPT = 5
_log = logging.getLogger(__name__)


def backup_settings_file(tag: str) -> Path | None:
    """Copy settings.json aside (``settings.json.<tag>-<timestamp>``); keep the newest few."""
    path = settings_path()
    if not path.exists():
        return None
    target = path.with_name(f"{path.name}.{tag}-{time.strftime('%Y%m%d-%H%M%S')}")
    try:
        shutil.copy2(path, target)
    except OSError:
        _log.exception("settings_backup_failed tag=%s", tag)
        return None
    backups = sorted(path.parent.glob(f"{path.name}.{tag}-*"), key=lambda p: p.stat().st_mtime, reverse=True)
    for stale in backups[_BACKUPS_KEPT:]:
        try:
            stale.unlink()
        except OSError:
            pass
    _log.info("settings_backup_written path=%s", target)
    return target


def reset_settings(settings: AppSettings) -> Path | None:
    """Restore defaults in place (the object is shared app-wide) after backing up the file.

    Only ExileLens's own settings file is touched: never PoB, builds or game files.
    """
    backup = backup_settings_file("bak")
    defaults = AppSettings()
    for item in fields(AppSettings):
        setattr(settings, item.name, getattr(defaults, item.name))
    save_settings(settings)
    _log.warning("settings_reset backup=%s", backup)
    return backup
