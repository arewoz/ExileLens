"""Focused Lua-level regression coverage for managed and legacy PoB2 loadouts."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "runtime" / "lua" / "bridge.lua"


def _local_errors_module():
    spec = importlib.util.spec_from_file_location("public_poe2value_errors", ROOT / "src" / "exilelens" / "errors.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_loadout_api_unsupported_payload_is_typed() -> None:
    errors = _local_errors_module()
    with pytest.raises(errors.PobLoadoutApiUnsupported, match="incompatible"):
        errors.raise_from_payload(
            {
                "code": "POB_LOADOUT_API_UNSUPPORTED",
                "message": "Installed Path of Building version is incompatible with loadout switching.",
            }
        )


def test_loadout_api_compatibility_paths(tmp_path: Path) -> None:
    lua = shutil.which("luajit") or shutil.which("lua")
    if not lua:
        pytest.skip("Lua interpreter is required for bridge compatibility coverage")

    harness = tmp_path / "loadout_api_compat.lua"
    harness.write_text(
        r'''
package.preload.dkjson = function()
  return { decode = function() end, encode = function() end }
end
local bridge = dofile(arg[1])

-- Current managed-loadouts API: use its native resolver and activator unchanged.
local native_selected
local native = {
  GetLoadoutByName = function(_, name)
    if name == "Boss" then return { specId = 2, itemSetId = 20, skillSetId = 30, configSetId = 40 } end
  end,
  SetActiveLoadout = function(_, loadout) native_selected = loadout end,
}
local loadout, api = bridge.resolve_loadout_compat(native, "Boss")
assert(api == "native")
assert(loadout.specId == 2 and loadout.itemSetId == 20)
bridge.activate_loadout_compat(native, loadout, api)
assert(native_selected == loadout)

-- Pre-managed-loadouts API: resolve the same linked set semantics PoB2 used
-- before GetLoadoutByName/SetActiveLoadout were introduced.
local legacy = {
  treeListSpecialLinks = { x = { setId = 2 } },
  itemListSpecialLinks = { x = { setId = 20 } },
  skillListSpecialLinks = { x = { setId = 30 } },
  configListSpecialLinks = { x = { setId = 40 } },
  SyncLoadouts = function(self) self.synced = true end,
  treeTab = {
    activeSpec = 1,
    GetSpecList = function() return { "Default", "Boss {x}" } end,
    SetActiveSpec = function(self, id) self.activeSpec = id end,
  },
  itemsTab = {
    activeItemSetId = 10, itemSetOrderList = { 10, 20 },
    itemSets = { [10] = { title = "Default" }, [20] = { title = "Boss {x}" } },
    SetActiveItemSet = function(self, id) self.activeItemSetId = id end,
  },
  skillsTab = {
    activeSkillSetId = 11, skillSetOrderList = { 11, 30 },
    skillSets = { [11] = { title = "Default" }, [30] = { title = "Boss {x}" } },
    SetActiveSkillSet = function(self, id) self.activeSkillSetId = id end,
  },
  configTab = {
    activeConfigSetId = 12, configSetOrderList = { 12, 40 },
    configSets = { [12] = { title = "Default" }, [40] = { title = "Boss {x}" } },
    SetActiveConfigSet = function(self, id) self.activeConfigSetId = id end,
  },
}
loadout, api = bridge.resolve_loadout_compat(legacy, "Boss {x}")
assert(api == "legacy")
assert(loadout.specId == 2 and loadout.itemSetId == 20 and loadout.skillSetId == 30 and loadout.configSetId == 40)
bridge.activate_loadout_compat(legacy, loadout, api)
assert(legacy.treeTab.activeSpec == 2 and legacy.itemsTab.activeItemSetId == 20)
assert(legacy.skillsTab.activeSkillSetId == 30 and legacy.configTab.activeConfigSetId == 40 and legacy.synced)

-- A partial/unknown legacy representation cannot select a tree alone.
loadout, api = bridge.resolve_loadout_compat(legacy, "Unknown")
assert(loadout == nil and api == "not_found")
loadout, api = bridge.resolve_loadout_compat({}, "Boss")
assert(loadout == nil and api == "unsupported")

-- Unsupported shapes return the bridge's controlled compatibility result,
-- not a Lua method-call traceback.
local function upvalue(fn, wanted)
  for i = 1, 100 do
    local name, value = debug.getupvalue(fn, i)
    if name == wanted then return value end
  end
end
build = {}
local set_active_loadout = upvalue(bridge.dispatch, "set_active_loadout")
local ok, err = pcall(set_active_loadout, "Boss")
assert(not ok and err.code == "POB_LOADOUT_API_UNSUPPORTED")
assert(not tostring(err.message):find("bridge.lua", 1, true))
''',
        encoding="utf-8",
    )
    result = subprocess.run([lua, str(harness), str(BRIDGE)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr or result.stdout
