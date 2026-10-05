"""Generate a 0.6.0 profile with 0.6.0's own settings/history code. Run with PYTHONPATH=<v0.6.0 worktree>/src."""
import os
import shutil
import sys
import tempfile
from pathlib import Path

tmp = Path(tempfile.mkdtemp(prefix="el060-"))
os.environ["LOCALAPPDATA"] = str(tmp)
os.environ.pop("POB2_PATH", None)
os.environ.pop("APPDATA", None)

import exilelens  # noqa: E402
from exilelens.app import settings as S  # noqa: E402
from exilelens.items.persistent_history import PersistentItemHistory  # noqa: E402

assert str(Path(exilelens.__file__)).replace("\\", "/").count("wt060"), exilelens.__file__
assert S.CURRENT_SCHEMA_VERSION == 23

s = S.AppSettings()
s.pob_path = r"C:\Users\Player\AppData\Roaming\Path of Building Community (PoE2)"
s.build_path = r"C:\Users\Player\AppData\Roaming\Path of Building Community (PoE2)\Builds\Example Witch.xml"
s.context = "MAP"
s.first_run_complete = True
s.onboarding_version_completed = 1
s.price_check_hotkey = "ctrl+shift+x"
s.live_market_mode = "auto"
s.dedup_window_seconds = 5.0
s.update_channel = "beta"
s.selected_loadout = "Mapping"
s.selected_item_set_id = "2"
s.item_set_follow_loadout = False
s.value_profile = "DEFENSIVE"
s.overlay_position_mode = "fixed_corner"
s.overlay_position = S.OverlayPosition(corner="top_left", x=24, y=96)
s.overlay_near_offset_px = 52
s.overlay_auto_hide_seconds = 12.0
s.dashboard_x, s.dashboard_y, s.dashboard_width, s.dashboard_height = 140, 80, 1360, 900
s.dashboard_last_page = "settings"
s.settings_dialog_x, s.settings_dialog_y, s.settings_dialog_width, s.settings_dialog_height = 300, 200, 600, 460
s.market_league = "Fate of the Vaal"
s.market_league_mode = "PINNED"
s.market_league_cache = ["Standard", "Fate of the Vaal"]
s.market_league_cache_at = 1760000000.0
s.pinned_overlays = {"slot-0": {"x": 1500, "y": 120, "width": 360, "height": 420}, "slot-1": {"x": 1500, "y": 560, "width": 360, "height": 420}}
s.update_last_check_at = 1760000000.0
s.update_latest_version = "0.6.0"
s.update_notified_version = "0.6.0"
s.ui_scale = 1.2
s.hotkey_hints_dismissed = True
s.hotkey_hints_success_count = 7
S.save_settings(s)

h = PersistentItemHistory()
result = {
    "raw_input": {"content_hash": "0123456789abcdef0123456789abcdef"},
    "evaluation_context": {"context": "MAP", "profile": "DEFENSIVE"},
    "evaluation_identity": {"schema": 1},
    "pob_parse": {"display_name": "Example Rare Helmet"},
    "best_slot": {"label": "Helmet"},
    "recommendation": {"verdict": "UPGRADE", "evaluation_outcome": {"verdict": "UPGRADE"}},
}
h.record(result, identity="fp|Example Witch.xml|Mapping|2|MAP|1")

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
for name in ("settings.json", "item_history.json"):
    shutil.copy2(tmp / "ExileLens" / name, out / name)
print("generated", sorted(p.name for p in (tmp / "ExileLens").iterdir()))
shutil.rmtree(tmp, ignore_errors=True)
