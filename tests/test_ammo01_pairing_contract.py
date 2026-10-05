"""AMMO-01 — Lua-level contract of the ammo pairing core and the damage-target rule (no PoB, LuaJIT only).

The real-PoB counterparts are tests/integration/test_ammo01_family_contract.py (every ammo gem in PoB's data) and
tests/integration/test_ammo01_state_matrix.py. This file covers what real data cannot: malformed and ambiguous shapes.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "runtime" / "lua" / "bridge.lua"
pytestmark = pytest.mark.itemcheck

HARNESS = r'''
package.preload.dkjson = function() return { decode = function() end, encode = function() end } end
SkillType = { CrossbowAmmoSkill = 1, CrossbowSkill = 2, Attack = 3 }
local bridge = dofile(arg[1])

local NODMG = { stats = { "base_deal_no_damage" }, baseFlags = {} }
local PLAIN = { stats = {}, baseFlags = { attack = true } }
local function fired(instance) return { granted = { skillTypes = { [2] = true, [3] = true } }, instance = instance, stat_data = PLAIN } end
local function load(instance, stat) return { granted = { skillTypes = { [1] = true, [3] = true } }, instance = instance, stat_data = stat or NODMG } end
local function check(entries, selector, want_target, want_status, label)
  local target, status = bridge.pair_ammo_effects(entries, selector)
  assert(target == want_target and status == want_status,
    label .. ": got " .. tostring(target) .. "/" .. tostring(status) .. ", wanted " .. tostring(want_target) .. "/" .. want_status)
end

local A, B = {}, {}

-- 1. the shape PoB's data has for every ammo gem: [fired, load] of one instance
check({ fired(A), load(A) }, 2, 1, "OK", "load -> fired")
-- 2. selecting the fired effect directly is never touched
check({ fired(A), load(A) }, 1, nil, "NOT_AMMO_LOAD", "fired selected")
-- 3. two ammo gems in one group: each load pairs with ITS OWN fired effect
check({ fired(A), load(A), fired(B), load(B) }, 2, 1, "OK", "gem A load")
check({ fired(A), load(A), fired(B), load(B) }, 4, 3, "OK", "gem B load")
-- 4. never a fired effect of another gem instance, even when it is the only candidate
check({ load(A), fired(B) }, 1, nil, "NO_FIRED_SIBLING", "cross-instance")
-- 5. ambiguity is never guessed
check({ fired(A), fired(A), load(A) }, 3, nil, "AMBIGUOUS_FIRED_SIBLINGS", "two fired siblings")
-- 6. malformed: an ammo-typed effect without the no-damage declaration is not a load action
check({ fired(A), load(A, PLAIN) }, 2, nil, "NOT_AMMO_LOAD", "no base_deal_no_damage")
-- 7. a sibling that is itself ammo-typed is not a fired candidate
check({ load(A), load(A) }, 1, nil, "NO_FIRED_SIBLING", "ammo sibling")
-- 8. out-of-range / empty
check({ fired(A), load(A) }, 5, nil, "NOT_AMMO_LOAD", "selector out of range")
check({}, 1, nil, "NOT_AMMO_LOAD", "empty list")
-- 9. no generalisation: a declared-no-damage effect that is not an ammo load is never paired
local plain_nodmg = { granted = { skillTypes = { [3] = true } }, instance = A, stat_data = NODMG }
check({ fired(A), plain_nodmg }, 2, nil, "NOT_AMMO_LOAD", "non-ammo no-damage effect")

-- damage-target rule: evidence only (stat flags, skill types, selected minion)
local function target(granted, stat, src)
  local ok, reason = bridge.damage_target_state(granted, stat, src)
  return ok, reason
end
local ammo_granted = { skillTypes = { [1] = true } }
local ok, why = target(ammo_granted, NODMG)
assert(ok == false and why == "AMMO_LOAD_DEALS_NO_DAMAGE", "ammo load must not be a target")
ok, why = target({ skillTypes = {} }, NODMG)
assert(ok == false and why == "DECLARES_NO_DAMAGE", "declared no damage without a damage flag")
ok, why = target({ skillTypes = {} }, { stats = { "base_deal_no_damage" }, baseFlags = { attack = true } })
assert(ok == true and why == "", "a damage flag keeps a no-damage-declared effect measurable")
ok, why = target({ skillTypes = {} }, { stats = { "base_deal_no_damage" }, baseFlags = { totem = true, duration = true } })
assert(ok == false and why == "DECLARES_NO_DAMAGE", "non-damage flags do not count")
ok, why = target({ skillTypes = {} }, NODMG, { skillMinion = "Spectre" })
assert(ok == true, "a selected minion actor keeps its effect a target")
ok, why = target({ skillTypes = {} }, PLAIN)
assert(ok == true and why == "", "an ordinary effect is a target")
ok, why = target({ skillTypes = {} }, nil)
assert(ok == true, "unknown stat set never refuses")
print("ok")
'''


def test_ammo_pairing_core_and_damage_target_rule(tmp_path: Path) -> None:
    lua = shutil.which("luajit") or shutil.which("lua")
    if not lua:
        pytest.skip("Lua interpreter is required for bridge contract coverage")
    harness = tmp_path / "ammo01_contract.lua"
    harness.write_text(HARNESS, encoding="utf-8")
    result = subprocess.run([lua, str(harness), str(BRIDGE)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr + result.stdout
    assert result.stdout.strip().endswith("ok")
