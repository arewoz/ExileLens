from __future__ import annotations

import json
import logging
import math
import os
import shutil
import time
from dataclasses import asdict, dataclass, field, fields
from enum import Enum
from pathlib import Path
from typing import Any


CURRENT_SCHEMA_VERSION = 25
ONBOARDING_VERSION = 1
DEFAULT_PRICE_CHECK_HOTKEY = "shift+c"
DEFAULT_REFINE_PRICE_HOTKEY = "ctrl+shift+r"
DEFAULT_POB_PATH = (os.environ.get("POB2_PATH") or "").strip()
APP_DATA_DIRECTORY = "ExileLens"
LEGACY_APP_DATA_DIRECTORY = "poe2-value-overlay"
_MIGRATED_PERSISTENT_FILES = (
    "settings.json", "active_character.json", "market_signatures.json",
    "item_history.json", "trade2_policy.json",
)
_MIGRATED_PERSISTENT_DIRECTORIES = ("build-cache",)


class BaselineMode(str, Enum):
    POB_BUILD_GEAR = "POB_BUILD_GEAR"


class OverlayPositionMode(str, Enum):
    NEAR_ITEM = "near_item"
    FIXED_CORNER = "fixed_corner"


def _app_data_root() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())
    return Path(base)


def legacy_app_data_dir() -> Path:
    return _app_data_root() / LEGACY_APP_DATA_DIRECTORY


def _migrate_legacy_app_data(destination: Path, legacy: Path) -> None:
    """Copy only durable user state once; never remove or merge legacy data."""
    if destination.exists() or not legacy.is_dir():
        return
    try:
        destination.mkdir(parents=True, exist_ok=False)
        for name in _MIGRATED_PERSISTENT_FILES:
            source, target = legacy / name, destination / name
            if source.is_file() and not target.exists():
                shutil.copy2(source, target)
        for name in _MIGRATED_PERSISTENT_DIRECTORIES:
            source, target = legacy / name, destination / name
            if source.is_dir() and not target.exists():
                shutil.copytree(source, target)
        _log.info("settings_directory_migrated legacy=%s destination=%s", legacy, destination)
    except OSError:
        # Preserve both the old directory and any successfully copied data. A later
        # launch uses the new directory if it now exists; nothing is overwritten.
        _log.exception("settings_directory_migration_failed legacy=%s", legacy)


def app_data_dir() -> Path:
    path = _app_data_root() / APP_DATA_DIRECTORY
    _migrate_legacy_app_data(path, legacy_app_data_dir())
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
    debug: bool = False
    first_run_complete: bool = False
    # Versioned separately from the settings schema: an app update does not replay setup.
    onboarding_version_completed: int = 0
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
    # Legacy, IGNORED since R5-A: market networking is decided only by `market_prices_enabled` + consent via
    # price_check.market_policy.resolve_market_access. Kept so old settings files still load.
    live_market_mode: str = "disabled"
    # R5-A: market prices are OFF by default and need an explicit opt-in recorded with the consent version the user saw.
    market_prices_enabled: bool = False
    market_consent_version: int = 0
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
    # Which GitHub releases the update check offers (UpdateService.channel()). "stable" (the default) offers final, non-prerelease
    # versions only. There is no user-facing beta opt-in and no public prerelease channel, so a stored "beta" (the old automatic
    # default, never a user choice) is normalized to "stable" on load (see _normalize_update_channel). An installed pre-release
    # build (for example 0.7.0b1) still sees the newer final 1.0.0.
    update_channel: str = "stable"
    update_last_error: str = ""
    diagnostic_verbose_until: float = 0.0
    # R2 optional cloud services. Two independent opt-ins, both OFF by default. Neither implies the other,
    # and neither is required for any ExileLens feature.
    send_usage_stats: bool = False
    send_error_reports: bool = False
    # Contract consent_version the user last confirmed; a higher contract version re-asks (treated as OFF).
    privacy_consent_version: int = 0
    privacy_card_resolved: bool = False
    # R2 supporter updates: honoured only while a verified lease grants seamless_updates. Defaults ON because
    # they do nothing for free installs; the user can turn either off.
    updates_auto_download: bool = True
    updates_install_on_exit: bool = True
    # The installed version whose release notes the player last dismissed. Empty on a profile that predates What's New.
    last_seen_release_notes_version: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        return payload

    @classmethod
    def from_dict(cls, data: Any) -> AppSettings:
        """Build settings from a stored dict, one field at a time.

        A valid value is kept; a missing or unusable one (wrong type, bad number, unknown mode) falls back to that field's
        default and never affects the other fields. Persisted booleans must be real JSON booleans. A non-object input
        yields the defaults. A newer ``schema_version`` is read as far as this build understands it and is stamped current
        only on the next normal save.
        """
        if not isinstance(data, dict):
            return cls()
        version = _as_int(data.get("schema_version"), 1)
        if version > CURRENT_SCHEMA_VERSION:
            version = CURRENT_SCHEMA_VERSION
        pos = _as_dict(data.get("overlay_position"))
        overlay_position = OverlayPosition(
            corner=_as_str(pos.get("corner"), "top_right") or "top_right",
            x=_as_opt_int(pos.get("x")),
            y=_as_opt_int(pos.get("y")),
        )
        completed = _as_int(data.get("onboarding_version_completed"), 0, minimum=0)
        # Existing configured installations have already passed the old setup gate.
        # Do not interrupt them solely because this field was introduced.
        if version < 21 and not completed and (data.get("first_run_complete") is True or (data.get("pob_path") and data.get("build_path"))):
            completed = ONBOARDING_VERSION
        return cls(
            schema_version=version,
            pob_path=_resolve_pob_path(_as_str(data.get("pob_path"), "")),
            build_path=_as_str(data.get("build_path"), ""),
            context=_as_str(data.get("context"), "MAP") or "MAP",
            overlay_enabled=_as_bool(data.get("overlay_enabled"), True),
            overlay_position=overlay_position,
            overlay_position_mode=_normalize_overlay_position_mode(data.get("overlay_position_mode")),
            overlay_near_offset_px=_as_int(data.get("overlay_near_offset_px"), 40, minimum=0),
            overlay_auto_hide_seconds=_as_float(data.get("overlay_auto_hide_seconds"), 0.0, minimum=0.0),
            debug=_as_bool(data.get("debug"), False),
            first_run_complete=_as_bool(data.get("first_run_complete"), False),
            onboarding_version_completed=completed,
            selected_loadout=_as_str(data.get("selected_loadout"), ""),
            item_set_follow_loadout=_as_bool(data.get("item_set_follow_loadout"), True),
            selected_item_set_id=_as_str(data.get("selected_item_set_id"), ""),
            baseline_mode=_normalize_baseline_mode(data.get("baseline_mode")),
            value_profile=_normalize_value_profile(data.get("value_profile")),
            tree_heatmap_metric=_as_str(data.get("tree_heatmap_metric"), "value_per_point") or "value_per_point",
            tree_ranking_mode=_as_str(data.get("tree_ranking_mode"), "efficiency") or "efficiency",
            tree_analysis_radius=_as_int(data.get("tree_analysis_radius"), 1, minimum=0),
            tree_show_allocated=_as_bool(data.get("tree_show_allocated"), True),
            tree_show_frontier=_as_bool(data.get("tree_show_frontier"), True),
            tree_show_evaluated=_as_bool(data.get("tree_show_evaluated"), True),
            tree_show_unevaluated=_as_bool(data.get("tree_show_unevaluated"), True),
            tree_show_notables=_as_bool(data.get("tree_show_notables"), True),
            tree_show_keystones=_as_bool(data.get("tree_show_keystones"), True),
            tree_show_small=_as_bool(data.get("tree_show_small"), True),
            tree_overlay_enabled=_as_bool(data.get("tree_overlay_enabled"), False),
            tree_overlay_calibration=_as_dict(data.get("tree_overlay_calibration")),
            tree_overlay_mode=_normalize_tree_overlay_mode(data.get("tree_overlay_mode")),
            tree_overlay_debug=_as_bool(data.get("tree_overlay_debug"), False),
            tree_overlay_opacity=_as_float(data.get("tree_overlay_opacity"), 0.95, minimum=0.0),
            tree_overlay_marker_size=_as_float(data.get("tree_overlay_marker_size"), 1.0, minimum=0.0),
            tree_overlay_line_width=_as_float(data.get("tree_overlay_line_width"), 3.0, minimum=0.0),
            tracked_build_path=_as_str(data.get("tracked_build_path"), ""),
            tracked_tree_set_id=_as_str(data.get("tracked_tree_set_id"), ""),
            dashboard_x=_as_opt_int(data.get("dashboard_x")),
            dashboard_y=_as_opt_int(data.get("dashboard_y")),
            dashboard_width=_as_int(data.get("dashboard_width"), 1280, minimum=1),
            dashboard_height=_as_int(data.get("dashboard_height"), 860, minimum=1),
            dashboard_last_page=_normalize_dashboard_page(data.get("dashboard_last_page")),
            settings_dialog_x=_as_opt_int(data.get("settings_dialog_x")),
            settings_dialog_y=_as_opt_int(data.get("settings_dialog_y")),
            settings_dialog_width=_as_int(data.get("settings_dialog_width"), 560, minimum=1),
            settings_dialog_height=_as_int(data.get("settings_dialog_height"), 420, minimum=1),
            item_check_pro=_as_dict(data.get("item_check_pro")),
            market_assist=_as_dict(data.get("market_assist")),
            market_assist_overlay_x=_as_opt_int(data.get("market_assist_overlay_x")),
            market_assist_overlay_y=_as_opt_int(data.get("market_assist_overlay_y")),
            market_assist_overlay_width=_as_int(data.get("market_assist_overlay_width"), 360, minimum=1),
            market_assist_overlay_height=_as_int(data.get("market_assist_overlay_height"), 420, minimum=1),
            pinned_overlays=_as_dict(data.get("pinned_overlays")),
            market_league=_as_str(data.get("market_league"), ""),
            market_league_mode=_normalize_league_mode(data.get("market_league_mode")),
            market_league_cache=_as_str_list(data.get("market_league_cache")),
            market_league_cache_at=_as_float(data.get("market_league_cache_at"), 0.0, minimum=0.0),
            live_market_mode=_as_str(data.get("live_market_mode"), "disabled") or "disabled",
            market_prices_enabled=data.get("market_prices_enabled") is True,
            market_consent_version=_as_int(data.get("market_consent_version"), 0, minimum=0),
            strict_live=_as_bool(data.get("strict_live"), True),
            price_check_enabled=_as_bool(data.get("price_check_enabled"), True),
            price_check_hotkey=_normalize_price_check_hotkey(data.get("price_check_hotkey"), version=version),
            price_check_refine_hotkey=_normalize_refine_price_hotkey(data.get("price_check_refine_hotkey")),
            price_check_capture_timeout_ms=_as_int(data.get("price_check_capture_timeout_ms"), 600, minimum=0),
            price_check_release_wait_ms=_as_int(data.get("price_check_release_wait_ms"), 500, minimum=0),
            price_check_diagnostic_mode=_as_str(data.get("price_check_diagnostic_mode"), ""),
            ui_scale=_normalize_ui_scale(data.get("ui_scale")),
            show_hotkey_hints=_as_bool(data.get("show_hotkey_hints"), True),
            hotkey_hints_dismissed=_as_bool(data.get("hotkey_hints_dismissed"), False),
            hotkey_hints_success_count=_as_int(data.get("hotkey_hints_success_count"), 0, minimum=0),
            update_last_check_at=_as_float(data.get("update_last_check_at"), 0.0, minimum=0.0),
            update_latest_version=_as_str(data.get("update_latest_version"), ""),
            update_notified_version=_as_str(data.get("update_notified_version"), ""),
            update_channel=_normalize_update_channel(data.get("update_channel")),
            update_last_error=_as_str(data.get("update_last_error"), ""),
            diagnostic_verbose_until=_as_float(data.get("diagnostic_verbose_until"), 0.0, minimum=0.0),
            send_usage_stats=data.get("send_usage_stats") is True,
            send_error_reports=data.get("send_error_reports") is True,
            privacy_consent_version=_as_int(data.get("privacy_consent_version"), 0, minimum=0),
            privacy_card_resolved=_as_bool(data.get("privacy_card_resolved"), False),
            updates_auto_download=data.get("updates_auto_download", True) is not False,
            updates_install_on_exit=data.get("updates_install_on_exit", True) is not False,
            last_seen_release_notes_version=_as_str(data.get("last_seen_release_notes_version"), "").strip(),
        )


class MarketLeagueMode(str, Enum):
    """AUTO follows build/character then the live active league; PINNED is the user's choice."""

    AUTO = "AUTO"
    PINNED = "PINNED"


# --- typed reads: a stored value that is not the expected type becomes the field's default ---------------------------------


def _as_bool(raw: Any, default: bool) -> bool:
    """Only a real JSON boolean counts: ``"false"``, ``0`` and ``"no"`` must not turn into True (or False)."""
    return raw if isinstance(raw, bool) else default


def _as_int(raw: Any, default: int, *, minimum: int | None = None) -> int:
    value: int | None = None
    if isinstance(raw, bool):
        value = None
    elif isinstance(raw, int):
        value = raw
    elif isinstance(raw, float) and math.isfinite(raw) and raw == int(raw):
        value = int(raw)
    elif isinstance(raw, str):
        try:
            value = int(raw.strip())
        except ValueError:
            value = None
    if value is None or (minimum is not None and value < minimum):
        return default
    return value


def _as_opt_int(raw: Any) -> int | None:
    """A coordinate: absent or unusable means "not stored" (None)."""
    return None if raw is None else _as_int(raw, None)  # type: ignore[arg-type]


def _as_float(raw: Any, default: float, *, minimum: float | None = None) -> float:
    value: float | None = None
    if isinstance(raw, bool):
        value = None
    elif isinstance(raw, (int, float)):
        value = float(raw)
    elif isinstance(raw, str):
        try:
            value = float(raw.strip())
        except ValueError:
            value = None
    if value is None or not math.isfinite(value) or (minimum is not None and value < minimum):
        return default
    return value


def _as_str(raw: Any, default: str) -> str:
    return raw if isinstance(raw, str) else default


def _as_dict(raw: Any) -> dict[str, Any]:
    return dict(raw) if isinstance(raw, dict) else {}


def _as_str_list(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [row for row in raw if isinstance(row, str) and row.strip()]


def _normalize_overlay_position_mode(raw: Any) -> str:
    value = _as_str(raw, "").strip()
    valid = {mode.value for mode in OverlayPositionMode}
    return value if value in valid else OverlayPositionMode.NEAR_ITEM.value


def _normalize_value_profile(raw: Any) -> str:
    value = _as_str(raw, "").strip().upper()
    if not value:
        return "BALANCED"
    try:
        from exilelens.items.value_profiles import ValueProfile

        return ValueProfile(value).value
    except ValueError:
        return "BALANCED"


def _normalize_tree_overlay_mode(raw: Any) -> str:
    value = _as_str(raw, "").strip()
    from exilelens.tree.overlay_mode import OverlayMode

    return value if value in {mode.value for mode in OverlayMode} else OverlayMode.BUILD_PATH.value


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
    scale = _as_float(raw, 1.0)
    return float(min(choices, key=lambda choice: abs(choice - scale)))


def _normalize_update_channel(raw: Any) -> str:
    """Every stored value becomes "stable". "beta" was the automatic default of every profile, never an explicit choice (nothing in
    the product ever offered one), so it is migrated rather than honoured; an unknown or empty value is stable too. In memory only:
    loading never writes the file, starts a check, or enables anything."""
    return "stable"


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
    from exilelens.platform.windows.hotkey_binding import validate_hotkey

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
    # Whole-file recovery only: where the unreadable original was preserved (None if it could not be copied).
    recovery_backup: Path | None = None


# Set when settings.json was unreadable and its bytes could not be preserved: nothing may overwrite it until a backup exists.
_unbacked_unreadable_file = False


def _write_recovery_backup(path: Path, raw: bytes | None) -> Path | None:
    """Preserve the unreadable original byte-for-byte at ``settings.json.corrupt-<time>[-n]``. Never overwrites a backup."""
    try:
        if raw is None:
            raw = path.read_bytes()
        stamp = time.strftime("%Y%m%d-%H%M%S")
        for attempt in range(100):
            suffix = "" if attempt == 0 else f"-{attempt}"
            target = path.with_name(f"{path.name}.corrupt-{stamp}{suffix}")
            try:
                handle = open(target, "xb")
            except FileExistsError:
                continue
            with handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            _prune_backups(path, "corrupt", keep=target)
            _log.info("settings_backup_written path=%s", target)
            return target
    except OSError:
        _log.exception("settings_recovery_backup_failed")
    return None


def _recover_unreadable(path: Path, raw: bytes | None) -> SettingsLoadResult:
    """settings.json exists but is not a usable settings object: keep the original, run on defaults, write nothing over it."""
    global _unbacked_unreadable_file
    backup = _write_recovery_backup(path, raw)
    _unbacked_unreadable_file = backup is None
    return SettingsLoadResult(AppSettings(), loaded_from_disk=True, load_error=True, recovery_backup=backup)


def recovery_notice_text(result: SettingsLoadResult) -> str | None:
    """Quiet, actionable copy for a whole-file reset (never for field-level normalization or schema migration)."""
    if not result.load_error:
        return None
    if result.recovery_backup is not None:
        return (
            "Your ExileLens settings file could not be read, so ExileLens started with default settings. "
            "A copy of the old file was kept in the ExileLens data folder (settings.json.corrupt-...)."
        )
    return (
        "Your ExileLens settings file could not be read, so ExileLens started with default settings. "
        "The old file could not be backed up and was left untouched; settings changed in this session will not be saved."
    )


def load_settings_result() -> SettingsLoadResult:
    path = settings_path()
    if not path.exists():
        return SettingsLoadResult(AppSettings(), loaded_from_disk=False)
    try:
        raw = path.read_bytes()
    except OSError:
        return _recover_unreadable(path, None)
    try:
        # utf-8-sig: Notepad and Windows PowerShell write a BOM, which plain utf-8 json
        # rejects -- that silently turned a hand-edited file into "corrupt, use defaults".
        data = json.loads(raw.decode("utf-8-sig"))
    except (ValueError, RecursionError):  # UnicodeDecodeError and JSONDecodeError are ValueErrors
        return _recover_unreadable(path, raw)
    if not isinstance(data, dict):
        return _recover_unreadable(path, raw)
    try:
        return SettingsLoadResult(AppSettings.from_dict(data), loaded_from_disk=True)
    except Exception:  # noqa: BLE001 - from_dict is field-by-field safe; this is the last resort, not a normal path
        _log.exception("settings_from_dict_failed")
        return _recover_unreadable(path, raw)


def load_settings() -> AppSettings:
    return load_settings_result().settings


def save_settings(settings: AppSettings) -> None:
    """Atomic: the new content is fully written and flushed to a sibling temp file, then swapped in with one ``replace``."""
    global _unbacked_unreadable_file
    path = settings_path()
    if _unbacked_unreadable_file:
        # The unreadable original was never preserved. Retry the backup; if it still fails, do not destroy the original.
        if not path.exists() or _write_recovery_backup(path, None) is not None:
            _unbacked_unreadable_file = False
        else:
            _log.error("settings_save_skipped unreadable_file_not_backed_up")
            return
    settings.schema_version = CURRENT_SCHEMA_VERSION
    payload = json.dumps(settings.to_dict(), indent=2)
    tmp_path = path.with_suffix(".json.tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        tmp_path.replace(path)
    except Exception:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise


def onboarding_required(settings: AppSettings) -> bool:
    return int(getattr(settings, "onboarding_version_completed", 0) or 0) < ONBOARDING_VERSION


def complete_onboarding(settings: AppSettings) -> None:
    """Persist an explained/dismissed setup flow without changing actual readiness."""
    settings.onboarding_version_completed = ONBOARDING_VERSION
    settings.first_run_complete = True  # compatibility with pre-v21 profiles
    save_settings(settings)


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
    _prune_backups(path, tag, keep=target)
    _log.info("settings_backup_written path=%s", target)
    return target


def _prune_backups(path: Path, tag: str, *, keep: Path) -> None:
    """Keep the newest few ``settings.json.<tag>-*`` copies; the one just written is never removed."""
    try:
        backups = sorted(path.parent.glob(f"{path.name}.{tag}-*"), key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return
    for stale in backups[_BACKUPS_KEPT:]:
        if stale == keep:
            continue
        try:
            stale.unlink()
        except OSError:
            pass


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
