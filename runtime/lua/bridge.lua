-- Minimal PoB2 bridge for poe2-value-overlay (product core).
-- Adapted concepts from archived lab.lua + mut.lua; optimization logic excluded.

local json = require("dkjson")
local M = {}

local STATE = {
	loaded = false,
	healthy = true,
	build_path = nil,
	-- Revision token of the bytes last parsed (mtime:size:sha). The in-memory build is
	-- only reused when the caller asks for exactly this revision.
	revision = nil,
	context = "MAP",
	active_loadout = nil,
	active_item_set_id = nil,
	-- PERF-02: a transaction whose restore was deferred. Drained by M.dispatch before
	-- any other request reads or mutates the build.
	pending = nil,
}

local METRIC_FIELDS = {
	"CombinedDPS", "FullDPS", "TotalDPS", "TotalDot", "FullDotDPS", "AverageDamage", "Speed", "HitSpeed",
	"CritChance", "CritMultiplier", "ProjectileCount", "ProjectileSpeedMod", "Duration",
	"Life", "LifeUnreserved", "EnergyShield", "Mana", "ManaUnreserved", "Spirit", "SpiritUnreserved",
	"TotalEHP", "PhysicalMaximumHitTaken", "FireMaximumHitTaken", "ColdMaximumHitTaken",
	"LightningMaximumHitTaken", "ChaosMaximumHitTaken",
	"FireResist", "ColdResist", "LightningResist", "ChaosResist",
	"FireResistOverCap", "ColdResistOverCap", "LightningResistOverCap", "ChaosResistOverCap",
	"FireResistTotal", "ColdResistTotal", "LightningResistTotal", "ChaosResistTotal",
	"MissingFireResist", "MissingColdResist", "MissingLightningResist", "MissingChaosResist",
	"Armour", "Evasion", "BlockChance",
	"ManaCost", "ManaPerSecondCost", "ManaRegenRecovery",
	"LifeCost", "LifePerSecondCost", "LifeRegenRecovery",
	"MovementSpeedMod",
}

-- Offensive fields exposed by PoB for a selected non-player actor.  Keep this
-- allowlist intentionally small: Build Intelligence needs calculation results,
-- not the complete actor/Lua environment.
local ACTOR_OUTPUT_FIELDS = {
	"CombinedDPS", "TotalDPS", "FullDPS", "TotalDot", "TotalDotDPS", "FullDotDPS", "AverageDamage",
	"AverageHit", "Speed", "HitSpeed", "WithDotDPS", "WithBleedDPS", "WithIgniteDPS", "WithPoisonDPS",
	"PoisonDPS", "IgniteDPS", "BleedDPS", "DecayDPS", "CullingDPS",
}

-- Preserve the distinction between skill DoT and damaging ailments on the
-- selected player skill.  Missing PoB outputs stay absent, not fabricated 0s.
local PLAYER_AILMENT_FIELDS = {
	"IgniteDPS", "PoisonDPS", "BleedDPS", "TotalDotDPS",
	"WithIgniteDPS", "WithPoisonDPS", "WithBleedDPS", "WithDotDPS",
	"IgniteChancePerHit", "IgniteDamage", "IgniteDuration", "TotalIgniteDPS",
	"PoisonChance", "PoisonDamage", "PoisonDuration", "TotalPoisonDPS",
	"BleedChance", "BleedDamage", "BleedDuration", "TotalBleedDPS",
	"PoisonStacks", "MaxPoisonStacks", "PoisonApplicationRate",
}

local MODE_OUTPUT_FIELDS = { "ChannelTime", "Time" }

local CONTEXTS = {
	MAP = {
		enemyIsBoss = "None",
		enemyLevel = 82,
		enemyFireResist = 40, enemyColdResist = 40, enemyLightningResist = 40, enemyChaosResist = 20,
	},
	BOSS = {
		enemyIsBoss = "Boss",
		enemyLevel = 84,
		enemyFireResist = 50, enemyColdResist = 50, enemyLightningResist = 50, enemyChaosResist = 30,
	},
}

local function num(v)
	return type(v) == "number" and v or 0
end

local function read_file(path)
	local f, err = io.open(path, "r")
	if not f then
		error({ code = "BUILD_NOT_FOUND", message = "cannot open " .. tostring(path), details = { path = path, err = err } })
	end
	local s = f:read("*a")
	f:close()
	return s
end

local function apply_context(context_name)
	local overrides = CONTEXTS[context_name or STATE.context] or CONTEXTS.MAP
	for k, v in pairs(overrides) do
		build.configTab.input[k] = v
	end
	build.configTab:BuildModList()
	build.buildFlag = true
	runCallback("OnFrame")
end

-- One PoB frame runs BuildOutput, then RefreshStatList -> EstimatePlayerProgress, which
-- may change the auto character level (e.g. after a loadout/tree switch) WITHOUT setting
-- buildFlag. The first output after such a change is computed at the previous level, so
-- keep recalculating until the level (and buildFlag) are stable. Bounded; normally 1-2 frames.
local SETTLE_MAX_FRAMES = 4

-- TOOLTIP-PERF (diagnostic only): opt-in stage timing for the Item Check hot path.
-- PERF.on is set per request from params.perf, so the default path is unchanged
-- apart from one boolean test per timed stage.
local PERF = { on = false, marks = nil, frames = 0 }

local function perf_begin()
	PERF.marks = {}
	PERF.frames = 0
	PERF.frame_ms = nil
	PERF.frame_why = nil
	PERF.native_calls = nil
end

local function perf_now()
	return os.clock() * 1000
end

local function perf_add(name, started)
	if not PERF.on or not PERF.marks then return end
	PERF.marks[name] = (PERF.marks[name] or 0) + (perf_now() - started)
end

local function recalc()
	for _ = 1, SETTLE_MAX_FRAMES do
		local level = build.characterLevel
		build.buildFlag = true
		local t_frame = PERF.on and perf_now() or 0
		if PERF.on then PERF.frames = PERF.frames + 1 end
		runCallback("OnFrame")
		if PERF.on then
			PERF.frame_ms = PERF.frame_ms or {}
			PERF.frame_ms[#PERF.frame_ms + 1] = perf_now() - t_frame
			PERF.frame_why = PERF.frame_why or {}
			PERF.frame_why[#PERF.frame_why + 1] =
				(build.characterLevel ~= level and "level_changed") or (build.buildFlag and "build_flag_set") or "settled"
		end
		if build.characterLevel == level and not build.buildFlag then
			return
		end
	end
end

local function slot_names()
	local names = {}
	for name in pairs(build.itemsTab.slots) do
		names[#names + 1] = name
	end
	table.sort(names)
	return names
end

-- PoB's ItemsTab always keeps FOUR independent weapon-slot objects: "Weapon 1",
-- "Weapon 2", "Weapon 1 Swap", "Weapon 2 Swap". Which physical pair is the
-- player's actual equipped loadout is decided per active item set by
-- `activeItemSet.useSecondWeaponSet` -- PoB itself never renames or re-links the
-- slot objects; its own calc setup (CalcSetup.lua) instead skips slots whose
-- `weaponSet` doesn't match the active flag and strips " Swap" off the surviving
-- slot's name before feeding it to the calc environment. This mirrors that same
-- redirection at the one place ExileLens reads or writes a weapon slot, so every
-- other caller (Python's ProductSlot/compatible-slot resolution, the UI) can keep
-- reasoning about the player's logical "Weapon 1"/"Weapon 2" without ever knowing
-- PoB's physical storage slot names. A no-op for every non-weapon slot and for any
-- build using its primary weapon set (the common case).
local function active_weapon_slot(slot_name)
	if (slot_name == "Weapon 1" or slot_name == "Weapon 2") and build.itemsTab.activeItemSet.useSecondWeaponSet then
		return slot_name .. " Swap"
	end
	return slot_name
end

local function slot_item_raw(slot_name)
	local slot = build.itemsTab.slots[active_weapon_slot(slot_name)]
	if not slot then return nil end
	local item = slot.selItemId and build.itemsTab.items[slot.selItemId]
	return item and item.raw or nil
end

local EVALUABLE_SLOTS = {
	["Helmet"] = true,
	["Body Armour"] = true,
	["Gloves"] = true,
	["Boots"] = true,
	["Belt"] = true,
	["Amulet"] = true,
	["Ring 1"] = true,
	["Ring 2"] = true,
	["Weapon 1"] = true,
	["Weapon 2"] = true,
}

local function is_evaluable_slot(slot_name)
	return EVALUABLE_SLOTS[slot_name] == true
end

-- M1.3: Jewel sockets are not `itemsTab` equipment slots with a fixed name --
-- PoB creates one `ItemSlotControl` per passive-tree jewel-socket NODE (slot
-- name "Jewel <nodeId>", see PoB's ItemsTab.lua's `addSlot(socketControl)`
-- loop over `node.type == "Socket" or node.containJewelSocket`), and it also
-- creates ring/weapon/etc.-embedded cluster-jewel sockets named
-- "<parent slot> Jewel Socket <n>" (see `addJewelSockets`). Both are ordinary
-- entries in `build.itemsTab.slots`, so `slot_names()`/`set_item`/the tx_*
-- transaction machinery already work on them BY NAME with zero change -- the
-- only architectural gap is that jewel sockets are per-build and dynamic
-- (keyed by tree node id), so they cannot be listed in a static table like
-- EVALUABLE_SLOTS the way equipment slots are.
local function is_jewel_socket_slot_name(slot_name)
	return slot_name:match("^Jewel %d+$") ~= nil
end

-- Every allocated jewel-socket slot name, in deterministic (ascending node id)
-- order. An unallocated socket is excluded (`slot.inactive`, set by PoB's own
-- `ItemsTabClass:UpdateSockets` -- a socket node with no passive-tree
-- allocation is not a valid placement target; see Phase A audit q7) but an
-- ALLOCATED socket is included whether or not it currently holds a jewel
-- (q6: an empty socket is simply `selItemId == 0`, not a distinct type).
-- M1.3 restore-safety finding: a socket whose CURRENTLY EQUIPPED jewel makes
-- other allocated passives reachable without a connected path (PoE's
-- "Intuitive Leap"-like mechanic; the real corpus example is the unique
-- jewel "From Nothing", "Passives in Radius can be Allocated without being
-- connected") cannot be safely round-tripped through the ordinary
-- `slot:SetSelItemId(candidate) ... SetSelItemId(original)` transaction.
-- Proven on a real fixture (core04_skill_native_dot.xml, socket "Jewel
-- 26196" holding "From Nothing"): temporarily replacing that socket's jewel
-- deallocates the passives that jewel was making reachable (PoB's
-- `PassiveSpecClass` dependency tracking correctly reacts to the jewel's
-- absence during the candidate frame), but restoring the ORIGINAL jewel via
-- `SetSelItemId` does not automatically reinstate them the way PoB's own
-- `ItemsTabClass:DeleteItem` explicitly does when fully removing such a
-- jewel -- there is no equivalent "please recheck connectivity" step on a
-- same-item-id-back swap. The transaction's own restore verification
-- correctly catches this (`tree_nodes` fingerprint mismatch ->
-- RESTORE_FAILED -> engine invalidated, never a delivered wrong answer),
-- but the product answer is to never attempt the risky swap in the first
-- place.
--
-- First attempt used `node.depends` (PoB's own "something else's allocation
-- depends on this node" tracking) as the signal, but that field is a GENERAL
-- tree-pathing structure present on ordinary, non-jewel-related nodes too
-- (ordinary branch dependency, ipairs count > 1 for perfectly safe sockets --
-- empirically over-excluded 3 of core04_melee_weapon.xml's 5 sockets that an
-- earlier real-PoB run had already proven safe, correct, and restorable).
-- The precise signal is the EQUIPPED ITEM's own flag PoB sets when parsing
-- an Intuitive-Leap-like jewel: `item.jewelData.intuitiveLeapLike` (see
-- PoB's `PassiveSpec.lua:1344`, `:1503` -- gates exactly this mechanic).
-- Checking the item, not the tree topology, means only sockets that
-- ACTUALLY hold this specific jewel family are excluded.
local function jewel_socket_is_connectivity_risky(slot)
	local it = build.itemsTab
	if not slot.selItemId or slot.selItemId <= 0 then
		return false
	end
	local item = it.items[slot.selItemId]
	return item ~= nil and item.jewelData ~= nil and item.jewelData.intuitiveLeapLike == true
end

-- Every allocated jewel-socket slot name, in deterministic (ascending node id)
-- order. An unallocated socket is excluded (`slot.inactive`, set by PoB's own
-- `ItemsTabClass:UpdateSockets` -- a socket node with no passive-tree
-- allocation is not a valid placement target; see Phase A audit q7) but an
-- ALLOCATED socket is included whether or not it currently holds a jewel
-- (q6: an empty socket is simply `selItemId == 0`, not a distinct type).
-- Excludes connectivity-risky sockets (see
-- `jewel_socket_is_connectivity_risky` above) unless `include_risky` is true.
local function allocated_jewel_socket_slots(include_risky)
	local it = build.itemsTab
	local names = {}
	local excluded_risky = 0
	for name, slot in pairs(it.slots) do
		if is_jewel_socket_slot_name(name) and not slot.inactive then
			if include_risky or not jewel_socket_is_connectivity_risky(slot) then
				names[#names + 1] = name
			else
				excluded_risky = excluded_risky + 1
			end
		end
	end
	table.sort(names, function(a, b)
		return tonumber(a:match("%d+")) < tonumber(b:match("%d+"))
	end)
	return names, excluded_risky
end

-- Compatible-jewel-socket discovery for a Jewel candidate item. Reuses PoB's
-- own `IsItemValidForSlot` (the single source of truth for jewel-family
-- compatibility: sinister sockets, ascendancy-embedded sockets like Lich,
-- cluster/expansion-jewel size rules -- see Phase A audit q8/q9) against every
-- allocated jewel socket, occupied or empty alike. There is no jewel
-- equivalent of "weapon layout" (that concept is specific to
-- one/two-handed weapon slot occupancy), so `weapon_layout` is always
-- "SUPPORTED" here; callers must not read it as a jewel-specific signal.
local function resolve_compatible_jewel_sockets_for_item(item)
	local it = build.itemsTab
	local slots = {}
	local allocated, excluded_risky = allocated_jewel_socket_slots()
	for _, slot_name in ipairs(allocated) do
		if it:IsItemValidForSlot(item, slot_name) then
			slots[#slots + 1] = slot_name
		end
	end
	-- `allocated_jewel_socket_count` lets the Python layer distinguish "this
	-- build has zero allocated jewel sockets at all" from "it has sockets but
	-- none of them accept this particular jewel family" -- both surface as an
	-- empty `compatible_slots` list otherwise, but they are different truthful
	-- failure reasons (Phase spec: do not collapse jewel failures into one
	-- generic code). `excluded_connectivity_risky_socket_count` is the number
	-- of otherwise-allocated sockets left out because their current jewel
	-- affects other passives' tree connectivity (see
	-- `jewel_socket_is_connectivity_risky`) -- reported so a truthful "some
	-- sockets could not be safely evaluated" note is possible instead of a
	-- silently smaller list.
	return {
		compatible_slots = slots,
		weapon_layout = "SUPPORTED",
		weapon_layout_reason = nil,
		allocated_jewel_socket_count = #allocated + excluded_risky,
		excluded_connectivity_risky_socket_count = excluded_risky,
	}
end

local function item_summary(item)
	if not item or not item.base then
		return nil
	end
	local tags = {}
	if item.base.tags then
		for tag, enabled in pairs(item.base.tags) do
			if enabled then
				tags[#tags + 1] = tag
			end
		end
		table.sort(tags)
	end
	return {
		name = item.name,
		base_name = item.baseName,
		rarity = item.rarity,
		type = item.type,
		sub_type = item.base.subType,
		identified = item.name ~= "Unidentified item",
		corrupted = item.corrupted or false,
		quality = item.quality,
		ilvl = item.itemLevel,
		level_req = item.requirements and item.requirements.level or nil,
		primary_slot = item:GetPrimarySlot(),
		tags = tags,
		weapon = item.base.weapon and true or false,
		one_hand = item.base.tags and item.base.tags.onehand or false,
		two_hand = item.base.tags and item.base.tags.twohand or false,
	}
end

local function parse_item_object(item_raw)
	local item = new("Item")
	local ok, err = pcall(function() item:ParseRaw(item_raw) end)
	if not ok then
		error({ code = "ITEM_PARSE_FAILED", message = tostring(err) })
	end
	if not item.base then
		error({ code = "ITEM_UNSUPPORTED", message = "item base type could not be resolved", details = { base_name = item.baseName } })
	end
	return item
end

local function resolve_compatible_slots_for_item(item)
	if not STATE.loaded then
		error({ code = "NO_BUILD_LOADED", message = "load_build must be called first" })
	end
	if item.type == "Jewel" then
		return resolve_compatible_jewel_sockets_for_item(item)
	end
	local slots = {}
	local weapon_slots = {}
	for _, slot_name in ipairs(slot_names()) do
		if is_evaluable_slot(slot_name) then
			-- Check validity against the slot PoB is ACTUALLY using (see
			-- `active_weapon_slot`): e.g. PoB's own offhand-vs-twohand check for
			-- "Weapon 2 Swap" inspects "Weapon 1 Swap"'s selected item, not
			-- "Weapon 1"'s -- checking the untranslated logical name here would
			-- validate an offhand candidate against whichever weapon set is
			-- currently INACTIVE.
			local valid = build.itemsTab:IsItemValidForSlot(item, active_weapon_slot(slot_name))
			if valid then
				slots[#slots + 1] = slot_name
				if slot_name == "Weapon 1" or slot_name == "Weapon 2" then
					weapon_slots[#weapon_slots + 1] = slot_name
				end
			end
		end
	end
	local layout = "SUPPORTED"
	local layout_reason = nil
	if #weapon_slots > 1 then
		layout = "AMBIGUOUS_WEAPON_LAYOUT"
		layout_reason = "item is valid in multiple weapon slots; all will be evaluated"
	elseif item.base.tags and item.base.tags.twohand and #weapon_slots == 0 then
		layout = "UNSUPPORTED_EQUIPMENT_LAYOUT"
		layout_reason = "two-hand weapon is not compatible with the current weapon layout"
	elseif (item.type == "Shield" or item.type == "Focus" or item.type == "Quiver") and #weapon_slots == 0 then
		layout = "UNSUPPORTED_EQUIPMENT_LAYOUT"
		layout_reason = "off-hand item is not compatible with the current weapon layout"
	end
	return {
		compatible_slots = slots,
		weapon_layout = layout,
		weapon_layout_reason = layout_reason,
	}
end

local function slot_item_summary(slot_name)
	local slot = build.itemsTab.slots[active_weapon_slot(slot_name)]
	if not slot then return nil end
	local item = slot.selItemId and build.itemsTab.items[slot.selItemId]
	if not item then
		return { slot = slot_name, equipped = false }
	end
	return {
		slot = slot_name,
		equipped = true,
		item_id = item.id,
		base_name = item.baseName,
		name = item.name,
		rarity = item.rarity,
		raw = item.raw,
	}
end

local function collect_actor_output(out)
	if type(out) ~= "table" then return nil end
	local row = {}
	local present = false
	for _, k in ipairs(ACTOR_OUTPUT_FIELDS) do
		if type(out[k]) == "number" then
			row[k] = out[k]
			present = true
		end
	end
	return present and row or nil
end

local function collect_metrics()
	local out = build.calcsTab.mainOutput or {}
	local raw = {}
	for _, k in ipairs(METRIC_FIELDS) do
		-- Absence is not a measured zero. In particular, an invalid selected
		-- attack may have no DPS/Speed output at all.
		if type(out[k]) == "number" then raw[k] = out[k] end
	end
	for _, k in ipairs(PLAYER_AILMENT_FIELDS) do
		if type(out[k]) == "number" then raw[k] = out[k] end
	end
	for _, k in ipairs(MODE_OUTPUT_FIELDS) do
		if type(out[k]) == "number" then raw[k] = out[k] end
	end
	local minion = collect_actor_output(out.Minion)
	if minion then
		for k, value in pairs(minion) do
			raw["Minion." .. k] = value
		end
	end
	-- Effective cap = clamped resist + missing-to-cap. Overcap does not raise the cap.
	for _, elem in ipairs({"Fire", "Cold", "Lightning", "Chaos"}) do
		local resist = out[elem .. "Resist"]
		local missing = out["Missing" .. elem .. "Resist"]
		if type(resist) == "number" and type(missing) == "number" then
			raw[elem .. "ResistMax"] = resist + missing
		end
	end
	return raw
end

local function sorted_keys(t)
	local ids = {}
	for id in pairs(t or {}) do
		ids[#ids + 1] = id
	end
	table.sort(ids)
	return ids
end

local function tree_node_ids()
	return sorted_keys(build.spec.allocNodes)
end

local function active_tree_set()
	local tab = build.treeTab
	if not tab then
		return { index = 1, title = "Default", tree_version = nil, alloc_mode = 0 }
	end
	local index = tab.activeSpec or 1
	local spec = tab.specList and tab.specList[index] or build.spec
	return {
		index = index,
		title = spec and (spec.title or "Default") or "Default",
		tree_version = spec and spec.treeVersion or nil,
		alloc_mode = (build.spec and build.spec.allocMode) or 0,
	}
end

local function jewel_fingerprint()
	local out = {}
	for _, nid in ipairs(sorted_keys(build.spec.jewels or {})) do
		out[#out + 1] = { node_id = nid, item_id = build.spec.jewels[nid] }
	end
	return out
end

local function mastery_fingerprint()
	local out = {}
	for _, nid in ipairs(sorted_keys(build.spec.masterySelections or {})) do
		out[#out + 1] = { node_id = nid, effect = build.spec.masterySelections[nid] }
	end
	return out
end

local function override_fingerprint()
	return sorted_keys(build.spec.hashOverrides or {})
end

local function weapon_set_fingerprint()
	local out = {}
	for _, nid in ipairs(tree_node_ids()) do
		local node = build.spec.nodes[nid]
		local mode = node and (node.allocMode or 0) or 0
		if mode ~= 0 then
			out[#out + 1] = { node_id = nid, alloc_mode = mode }
		end
	end
	return out
end

local PRODUCT_TYPES = {
	Normal = "SMALL",
	Notable = "NOTABLE",
	Keystone = "KEYSTONE",
	Socket = "SOCKET",
	ClassStart = "CLASS_START",
	AscendClassStart = "ASCEND_START",
	Mastery = "MASTERY",
	OnlyImage = "OTHER",
}

local function classify_node(node)
	local ntype = node.type or "Normal"
	local product = PRODUCT_TYPES[ntype] or "OTHER"
	local support = "SUPPORTED"
	local reason = nil
	if ntype == "Socket" or ntype == "Mastery" or ntype == "ClassStart" or ntype == "AscendClassStart" or ntype == "OnlyImage" or node.containJewelSocket or node.isJewelSocket then
		support = "UNSUPPORTED_SPECIAL_NODE"
		reason = ntype
	elseif node.isMultipleChoice or node.isMultipleChoiceOption then
		support = "UNSUPPORTED_SPECIAL_NODE"
		reason = "multiple_choice"
	elseif node.expansionJewel then
		support = "UNSUPPORTED_SPECIAL_NODE"
		reason = "expansion_jewel"
	end
	return product, support, reason
end

local function neighbor_ids(node)
	local ids = {}
	local seen = {}
	if node.linkedId then
		for _, oid in ipairs(node.linkedId) do
			if build.spec.nodes[oid] and not seen[oid] then
				seen[oid] = true
				ids[#ids + 1] = oid
			end
		end
	end
	for _, other in ipairs(node.linked or {}) do
		local oid = other.id
		if oid and build.spec.nodes[oid] and not seen[oid] then
			seen[oid] = true
			ids[#ids + 1] = oid
		end
	end
	table.sort(ids)
	return ids
end

local function node_payload(id, node)
	local product, support, reason = classify_node(node)
	local path_dist = node.pathDist
	if type(path_dist) ~= "number" or path_dist >= 1000 then
		path_dist = nil
	end
	local x, y = node.x, node.y
	if type(x) ~= "number" then x = nil end
	if type(y) ~= "number" then y = nil end
	local constraints = nil
	if node.unlockConstraint and node.unlockConstraint.nodes then
		constraints = {}
		for _, cid in ipairs(node.unlockConstraint.nodes) do
			constraints[#constraints + 1] = cid
		end
	end
	return {
		id = id,
		name = node.dn or node.name or "",
		type = product,
		pob_type = node.type or "Normal",
		x = x,
		y = y,
		allocated = node.alloc and true or false,
		alloc_mode = node.allocMode or 0,
		ascendancy = node.ascendancyName or nil,
		is_attribute = node.isAttribute and true or false,
		is_free = node.isFreeAllocate and true or false,
		support = support,
		support_reason = reason,
		neighbors = neighbor_ids(node),
		path_dist = path_dist,
		unlock_constraint = constraints,
	}
end

local function collect_tree_snapshot()
	local spec = build.spec
	local nodes = {}
	local edges = {}
	local edge_seen = {}
	local type_counts = {}
	local support_counts = {}
	local allocated = 0
	for _, id in ipairs(sorted_keys(spec.nodes)) do
		local node = spec.nodes[id]
		if node and node.type ~= "OnlyImage" then
			local payload = node_payload(id, node)
			nodes[#nodes + 1] = payload
			type_counts[payload.type] = (type_counts[payload.type] or 0) + 1
			support_counts[payload.support] = (support_counts[payload.support] or 0) + 1
			if payload.allocated then
				allocated = allocated + 1
			end
			for _, oid in ipairs(payload.neighbors) do
				local a, b = id, oid
				if a > b then a, b = b, a end
				local key = tostring(a) .. ":" .. tostring(b)
				if not edge_seen[key] then
					edge_seen[key] = true
					edges[#edges + 1] = { a, b }
				end
			end
		end
	end
	local subgraph_count = 0
	for _ in pairs(spec.subGraphs or {}) do
		subgraph_count = subgraph_count + 1
	end
	local class_name, ascend_name
	if spec.tree and spec.curClassId and spec.tree.classes[spec.curClassId] then
		class_name = spec.tree.classes[spec.curClassId].name
		local asc = spec.tree.classes[spec.curClassId].classes
		if asc and spec.curAscendClassId and asc[spec.curAscendClassId] then
			ascend_name = asc[spec.curAscendClassId].name
		end
	end
	local set = active_tree_set()
	return {
		tree_set = set,
		class = class_name,
		ascendancy = ascend_name,
		nodes = nodes,
		edges = edges,
		jewels = jewel_fingerprint(),
		mastery = mastery_fingerprint(),
		stats = {
			node_count = #nodes,
			edge_count = #edges,
			allocated_count = allocated,
			types = type_counts,
			support = support_counts,
			subgraph_count = subgraph_count,
		},
	}
end

local function ids_to_nodes(ids)
	local spec = build.spec
	local path = {}
	for _, raw_id in ipairs(ids or {}) do
		local id = tonumber(raw_id)
		local node = id and spec.nodes[id]
		if not node then
			return nil, id or raw_id
		end
		path[#path + 1] = node
	end
	return path
end

local function sync_loadouts()
	if build and build.SyncLoadouts then
		build:SyncLoadouts(true)
	end
end

local function active_loadout_name()
	if not build or not build.treeTab then
		return nil
	end
	local spec = build.treeTab.specList[build.treeTab.activeSpec]
	return spec and (spec.title or "Default") or nil
end

-- PoB2 added GetLoadoutByName/SetActiveLoadout together with the managed
-- loadouts API (upstream 425f8a30). Older PoB2 builds expose the same
-- loadout semantics through the tab set lists and the link maps populated by
-- SyncLoadouts. Keep that implementation here rather than selecting a tree
-- alone: a loadout is only valid when its tree, item, skill, and config sets
-- all resolve together.
function M.resolve_loadout_compat(build_mode, name)
	if type(build_mode.GetLoadoutByName) == "function" and type(build_mode.SetActiveLoadout) == "function" then
		return build_mode:GetLoadoutByName(name), "native"
	end

	local tree_tab = build_mode.treeTab
	local items_tab = build_mode.itemsTab
	local skills_tab = build_mode.skillsTab
	local config_tab = build_mode.configTab
	if not (tree_tab and items_tab and skills_tab and config_tab
		and type(tree_tab.GetSpecList) == "function"
		and type(tree_tab.SetActiveSpec) == "function"
		and type(items_tab.SetActiveItemSet) == "function"
		and type(skills_tab.SetActiveSkillSet) == "function"
		and type(config_tab.SetActiveConfigSet) == "function") then
		return nil, "unsupported"
	end

	local function linked_set_id(special_links, value)
		local link_id = string.match(value, "%{(%w+)%}")
		local linked = link_id and special_links and special_links[link_id]
		return linked and linked.setId or nil
	end

	local function find_set_id(order_list, value, sets, special_links)
		for _, set_id in ipairs(order_list or {}) do
			local set = sets and sets[set_id]
			if set and value == (set.title or "Default") then
				return set_id
			end
		end
		return linked_set_id(special_links, value)
	end

	local function find_tree_id(tree_list, value, special_links)
		for id, title in ipairs(tree_list or {}) do
			if value == title then
				return id
			end
		end
		return linked_set_id(special_links, value)
	end

	local one_skill = #skills_tab.skillSetOrderList == 1
	local one_item = #items_tab.itemSetOrderList == 1
	local one_config = #config_tab.configSetOrderList == 1
	local spec_id = find_tree_id(tree_tab:GetSpecList(), name, build_mode.treeListSpecialLinks)
	local item_id = one_item and items_tab.itemSetOrderList[1]
		or find_set_id(items_tab.itemSetOrderList, name, items_tab.itemSets, build_mode.itemListSpecialLinks)
	local skill_id = one_skill and skills_tab.skillSetOrderList[1]
		or find_set_id(skills_tab.skillSetOrderList, name, skills_tab.skillSets, build_mode.skillListSpecialLinks)
	local config_id = one_config and config_tab.configSetOrderList[1]
		or find_set_id(config_tab.configSetOrderList, name, config_tab.configSets, build_mode.configListSpecialLinks)

	if not (spec_id and item_id and skill_id and config_id) then
		return nil, "not_found"
	end
	return {
		specId = spec_id,
		itemSetId = item_id,
		skillSetId = skill_id,
		configSetId = config_id,
	}, "legacy"
end

function M.activate_loadout_compat(build_mode, loadout, api)
	if api == "native" then
		build_mode:SetActiveLoadout(loadout)
		return
	end

	-- This is the pre-managed-loadouts selection sequence from PoB2 Build.lua.
	if loadout.specId ~= build_mode.treeTab.activeSpec then
		build_mode.treeTab:SetActiveSpec(loadout.specId)
	end
	if loadout.itemSetId ~= build_mode.itemsTab.activeItemSetId then
		build_mode.itemsTab:SetActiveItemSet(loadout.itemSetId)
	end
	if loadout.skillSetId ~= build_mode.skillsTab.activeSkillSetId then
		build_mode.skillsTab:SetActiveSkillSet(loadout.skillSetId)
	end
	if loadout.configSetId ~= build_mode.configTab.activeConfigSetId then
		build_mode.configTab:SetActiveConfigSet(loadout.configSetId)
	end
	if type(build_mode.SyncLoadouts) == "function" then
		build_mode:SyncLoadouts(true)
	end
end

local function legacy_loadouts()
	local loadouts = {}
	local seen = {}
	local controls = build.controls and build.controls.buildLoadouts
	for _, name in ipairs((controls and controls.list) or {}) do
		local loadout, api = M.resolve_loadout_compat(build, name)
		if loadout and api == "legacy" and not seen[name] then
			loadouts[#loadouts + 1] = { name = name, index = #loadouts + 1 }
			seen[name] = true
		end
	end
	return loadouts
end

local function list_tree_sets()
	local tab = build.treeTab
	local sets = {}
	local active = 1
	if tab then
		active = tab.activeSpec or 1
		for index, spec in ipairs(tab.specList or {}) do
			sets[#sets + 1] = {
				id = tostring(index),
				index = index,
				title = spec.title or ("Tree " .. tostring(index)),
				tree_version = spec.treeVersion,
				active = index == active,
			}
		end
	end
	return { tree_sets = sets, active_index = active }
end

local function set_active_tree_set(tree_set_id)
	local tab = build.treeTab
	if not tab then
		return list_tree_sets()
	end
	local index = tonumber(tree_set_id) or tab.activeSpec or 1
	if tab.specList[index] then
		tab:SetActiveSpec(index, true)
		build.spec = tab.specList[index]
		recalc()
	end
	return list_tree_sets()
end

local function list_loadouts()
	sync_loadouts()
	local loadouts = {}
	for index, spec in ipairs(build.loadoutsList or {}) do
		loadouts[#loadouts + 1] = {
			name = spec.title or "Default",
			index = index,
		}
	end
	if #loadouts == 0 then
		loadouts = legacy_loadouts()
	end
	local active = active_loadout_name()
	STATE.active_loadout = active
	return {
		loadouts = loadouts,
		active = active,
	}
end

local function coerce_item_set_id(item_set_id)
	if item_set_id == nil or item_set_id == "" then
		return nil
	end
	local sets = build.itemsTab.itemSets
	if sets[item_set_id] then
		return item_set_id
	end
	local numeric = tonumber(item_set_id)
	if numeric ~= nil and sets[numeric] then
		return numeric
	end
	local as_string = tostring(item_set_id)
	if sets[as_string] then
		return as_string
	end
	return nil
end

local function list_item_sets()
	local item_sets = {}
	for order, set_id in ipairs(build.itemsTab.itemSetOrderList) do
		local set = build.itemsTab.itemSets[set_id]
		item_sets[#item_sets + 1] = {
			id = set_id,
			title = set and set.title or "",
			order = order,
			active = set_id == build.itemsTab.activeItemSetId,
		}
	end
	STATE.active_item_set_id = build.itemsTab.activeItemSetId
	return {
		item_sets = item_sets,
		active_id = build.itemsTab.activeItemSetId,
		follow_loadout = true,
	}
end

local function set_active_loadout(name)
	if not name or name == "" then
		return list_loadouts()
	end
	sync_loadouts()
	local loadout, api = M.resolve_loadout_compat(build, name)
	if not loadout then
		if api == "unsupported" then
			error({
				code = "POB_LOADOUT_API_UNSUPPORTED",
				message = "Installed Path of Building version is incompatible with loadout switching. Update Path of Building and reload the build.",
			})
		end
		error({ code = "LOADOUT_NOT_FOUND", message = "unknown loadout: " .. tostring(name), details = { name = name } })
	end
	M.activate_loadout_compat(build, loadout, api)
	recalc()
	STATE.active_loadout = active_loadout_name()
	STATE.active_item_set_id = build.itemsTab.activeItemSetId
	return {
		active = STATE.active_loadout,
		active_item_set_id = STATE.active_item_set_id,
		fingerprint = M.fingerprint_components(),
		metrics = collect_metrics(),
	}
end

local function set_active_item_set(item_set_id)
	if not item_set_id or item_set_id == "" then
		return list_item_sets()
	end
	local resolved = coerce_item_set_id(item_set_id)
	if not resolved then
		error({ code = "ITEM_SET_NOT_FOUND", message = "unknown item set: " .. tostring(item_set_id), details = { item_set_id = item_set_id } })
	end
	build.itemsTab:SetActiveItemSet(resolved)
	recalc()
	STATE.active_item_set_id = resolved
	return {
		active_id = resolved,
		fingerprint = M.fingerprint_components(),
		metrics = collect_metrics(),
	}
end

-- Identity of a socket group's selected active skill. Stable across item swaps for
-- gem groups; item-granted groups carry `source` ("Item:<id>:<name>").
-- PoB stat-set labels and positions are display information, not semantic IDs.
-- Fingerprint the granted effect's machine stat IDs/flags instead, and refuse
-- ambiguous duplicate fingerprints on multi-set effects.
local STAT_SET_IDENTITY_CACHE = setmetatable({}, { __mode = "k" })

local function stat_set_signature(set)
	if type(set) ~= "table" then return "" end
	local ids = {}
	for _, id in ipairs(set.stats or {}) do
		if type(id) == "string" then ids[#ids + 1] = "s:" .. id end
	end
	for key, value in pairs(set.baseFlags or {}) do
		if value then ids[#ids + 1] = "f:" .. tostring(key) end
	end
	for key in pairs(set.statMap or {}) do
		ids[#ids + 1] = "m:" .. tostring(key)
	end
	for _, entry in ipairs(set.constantStats or {}) do
		if type(entry) == "table" and type(entry[1]) == "string" then
			ids[#ids + 1] = "c:" .. entry[1]
		end
	end
	table.sort(ids)
	return table.concat(ids, ";")
end

local function stat_set_catalog(granted)
	local cached = STAT_SET_IDENTITY_CACHE[granted]
	if cached then return cached end
	local sets = granted.statSets or {}
	local signatures, counts, catalog = {}, {}, {}
	for index, set in ipairs(sets) do
		local signature = stat_set_signature(set)
		signatures[index] = signature
		counts[signature] = (counts[signature] or 0) + 1
	end
	for index, set in ipairs(sets) do
		local signature = signatures[index]
		local unique = #sets == 1 or (signature ~= "" and counts[signature] == 1)
		catalog[index] = { set = set, key = unique and (granted.id .. ":" .. (#sets == 1 and "sole-set" or signature)) or "", resolved = unique }
	end
	STAT_SET_IDENTITY_CACHE[granted] = catalog
	return catalog
end

local function selected_stat_set(granted, src)
	if not granted then return 1, nil, "", false, 0 end
	local count = #(granted.statSets or {})
	local chosen = src and src.statSet and (src.statSet[granted.id] or src.statSet.index) or 1
	local entry = stat_set_catalog(granted)[chosen]
	if not entry then return chosen, nil, "", false, count end
	return chosen, entry.set, entry.key, entry.resolved, count
end

local PART_IDENTITY_CACHE = setmetatable({}, { __mode = "k" })

local function part_signature(part)
	local ids = {}
	for key, value in pairs(part) do
		if key ~= "name" and (type(value) == "boolean" or type(value) == "number") then
			ids[#ids + 1] = tostring(key) .. "=" .. tostring(value)
		end
	end
	for _, id in ipairs(part.stats or {}) do
		if type(id) == "string" then ids[#ids + 1] = "s:" .. id end
	end
	table.sort(ids)
	return table.concat(ids, ";")
end

local function part_catalog(granted)
	local cached = PART_IDENTITY_CACHE[granted]
	if cached then return cached end
	local parts = granted.parts or {}
	local signatures, counts, catalog = {}, {}, {}
	for index, part in ipairs(parts) do
		local signature = part_signature(part)
		signatures[index] = signature
		counts[signature] = (counts[signature] or 0) + 1
	end
	for index, part in ipairs(parts) do
		local signature = signatures[index]
		local unique = signature ~= "" and counts[signature] == 1
		catalog[index] = { part = part, key = unique and (granted.id .. ":" .. signature) or "", resolved = unique }
	end
	PART_IDENTITY_CACHE[granted] = catalog
	return catalog
end

local function selected_part(granted, src)
	local parts = granted and granted.parts or {}
	if #parts == 0 then return nil, "", (granted and granted.id or "") .. ":whole", true, 0 end
	if #parts == 1 then return 1, parts[1].name or "", granted.id .. ":sole-part", true, 1 end
	local index = src and src.skillPart or 1
	local entry = part_catalog(granted)[index]
	if not entry then return index, "", "", false, #parts end
	return index, entry.part.name or "", entry.key, entry.resolved, #parts
end

-- `override_env` lets a caller supply a different (already-computed) calc environment
-- to source the calc-derived fields (stage_count/calculation_mode/active_flags) from,
-- instead of the shared `build.calcsTab.mainEnv`. Used by cached_group_report (PERF-09)
-- to reconstruct identity from a GlobalCache-cached per-skill Env without requiring
-- `index` to actually be `build.mainSocketGroup`. Every existing caller omits it, which
-- reduces to exactly today's behaviour (`index == build.mainSocketGroup and ...`).
local function group_identity(index, group, override_env)
	local skill = group.displaySkillList and group.displaySkillList[group.mainActiveSkill or 1]
	local effect = skill and skill.activeEffect
	local granted = effect and effect.grantedEffect
	-- The selected stat set ("Projectile" vs "Damage over Time") decides what PoB's
	-- main output measures for multi-part skills; showAverage makes CombinedDPS per-hit.
	-- The gem instance stores the selection per granted effect (srcInstance.statSet[id]);
	-- display-list effects are not calculated skills, so read the label from the data.
	local src = effect and effect.srcInstance
	local stat_index, stat_data, stat_key, stat_resolved, stat_count = selected_stat_set(granted, src)
	local part_index, part_name, part_key, part_resolved, part_count = selected_part(granted, src)
	local flags = effect and effect.statSet and effect.statSet.skillFlags
	local env = override_env or (index == build.mainSocketGroup and build.calcsTab.mainEnv)
	local active = env and env.player and env.player.mainSkill
	local active_flags = active and active.skillFlags or flags or {}
	local staged = active_flags.multiStage or (part_count > 0 and granted.parts[part_index or 1] and granted.parts[part_index or 1].stages)
	local configured_stage = src and src.skillStageCount
	local stage_count = staged and (configured_stage or (active and active.skillData and active.skillData.stagesMin) or 1) or nil
	local calculation_mode = active_flags.channelRelease and "CHANNEL_RELEASE"
		or (active_flags.channel and "CHANNEL") or "DIRECT"
	return {
		index = index,
		stat_set = stat_data and stat_data.label or "",
		stat_set_index = stat_index,
		stat_set_count = stat_count,
		stat_set_key = stat_key,
		stat_set_resolved = stat_resolved,
		part_index = part_index,
		part_name = part_name,
		part_key = part_key,
		part_resolved = part_resolved,
		part_count = part_count,
		stage_count = stage_count,
		stage_explicit = configured_stage ~= nil,
		calculation_mode = calculation_mode,
		actor_id = src and tostring(src.skillMinionCalcs or src.skillMinion or "") or "",
		actor_skill = src and tostring(src.skillMinionSkillCalcs or src.skillMinionSkill or "") or "",
		show_average = (flags and flags.showAverage) and true or false,
		-- PoB flags are only a cheap discovery hint; a displayed component
		-- still requires a directly calculated output from skill_report.
		native_damage_candidate = (flags and (flags.hit or flags.dot or flags.minion)) and true or false,
		label = group.label or "",
		display_label = group.displayLabel or "",
		source = group.source or "",
		slot = group.slot or "",
		enabled = group.enabled and true or false,
		slot_enabled = group.slotEnabled ~= false,
		main_active_skill = group.mainActiveSkill or 1,
		skill_name = granted and granted.name or "",
		skill_id = granted and granted.id or "",
		skill_level = effect and effect.level or nil,
		is_main = index == build.mainSocketGroup,
		gems = (function()
			local names = {}
			for _, gem in ipairs(group.gemList or {}) do
				names[#names + 1] = gem.nameSpec or ""
			end
			return names
		end)(),
	}
end

-- `override_out` lets a caller supply a different output table (e.g. a GlobalCache-cached
-- skill's own `Env.player.output`) instead of the shared `build.calcsTab.mainOutput`. Every
-- existing caller omits it, which is exactly today's behaviour.
local function offense_output(override_out)
	local out = override_out or build.calcsTab.mainOutput or {}
	local row = {}
	for _, k in ipairs(ACTOR_OUTPUT_FIELDS) do
		row[k] = num(out[k])
	end
	for _, k in ipairs(PLAYER_AILMENT_FIELDS) do
		if type(out[k]) == "number" then row[k] = out[k] end
	end
	for _, k in ipairs(MODE_OUTPUT_FIELDS) do
		if type(out[k]) == "number" then row[k] = out[k] end
	end
	row.Minion = collect_actor_output(out.Minion)
	return row
end

local function per_hit_combined_signature(out)
	local combined, average, dps = out.CombinedDPS, out.AverageDamage, out.TotalDPS
	return type(combined) == "number" and type(average) == "number" and type(dps) == "number"
		and combined > 0 and dps > combined
		and math.abs(combined - average) <= math.max(0.000001, math.abs(average) * 0.000001)
end

local function attach_damage_owner(identity)
	if not identity then return nil end
	local out = build.calcsTab.mainOutput or {}
	-- Some display-list skillFlags are stale until skill_report forces another
	-- recalc. PoB's per-hit output signature is stable in the same calculation.
	identity.show_average = identity.show_average or per_hit_combined_signature(out)
	if collect_actor_output(out.Minion) then
		identity.damage_owner = "MINION"
		identity.output_table = "mainOutput.Minion"
	else
		identity.damage_owner = "PLAYER"
		identity.output_table = "mainOutput"
	end
	return identity
end

-- ===== PERF-09: GlobalCache-backed native discovery ==========================
-- A normal recalc() (Build:OnFrame -> CalcsTabClass:BuildOutput() ->
-- calcs.buildOutput(build, "MAIN")) unconditionally runs a full calcs.perform() pass for
-- EVERY active skill in the build -- not only build.mainSocketGroup's -- via its
-- buildActiveSkill loop (Modules/Calcs.lua), and caches each pass's complete environment
-- in GlobalCache.cachedData.MAIN[uuid] (Modules/Common.lua's cacheData, keyed by
-- cacheSkillUUID). This is unconditional, undocumented-but-load-bearing PoB behaviour
-- (PoB's own gem-swap/trigger/mirage DPS previews already depend on it) -- see the
-- PERF-08 research report for the full trace. skill_report's per-group loop below can
-- therefore often read a group's output straight out of that cache instead of switching
-- mainSocketGroup and paying another full recalc() for it.
--
-- Proven equivalence (PERF-08 research + PERF-09 identity-gate tests): both the output
-- metrics AND the full identity block (including the three calc-derived fields --
-- stage_count/calculation_mode/show_average -- that group_identity() can only source
-- from a live calc env) match exactly between this path and today's authoritative
-- switch-and-recalc path, for PLAYER and MINION groups, baseline and candidate-equipped
-- states. See tests/integration/test_perf09_native_cache_identity.py.
--
-- Lifetime: GlobalCache is candidate-state-local, not a new ExileLens cache. A report is
-- read and copied into plain Lua tables (row.output/row.* below) immediately after the
-- candidate slot's own mandatory recalc -- the same recalc(), not an extra one -- and
-- nothing here retains a reference to entry.Env past this function returning. The next
-- recalc() (next slot, or the transaction's own restore) is free to invalidate/overwrite
-- GlobalCache; nothing here assumes it survives that.
--
-- Fallback is mandatory and per-group: GlobalCache is undocumented PoB internal state,
-- not a stable API. cached_group_report returns nil for anything it cannot prove --
-- UUID not found, entry missing, or entry/Env malformed -- and skill_report's loop falls
-- back to today's switch-and-recalc path for exactly that group when it does. A cache
-- miss on one group never affects any other requested group's result.

-- Test-only fault injection, shared by the get_skill_report RPC and tx_measure's
-- component_keys block: JSON arrays decode as 1..N Lua arrays; cached_group_report's
-- opts want O(1) index sets. Every production caller passes indices=nil, which returns
-- nil unchanged (skill_report_opts_from_params below then omits the corresponding opts
-- field entirely).
local function to_index_set(indices)
	if type(indices) ~= "table" then return nil end
	local set = {}
	for _, index in ipairs(indices) do
		set[tonumber(index)] = true
	end
	return set
end

-- Build cached_group_report's test-only opts table from an RPC params table. Every
-- production call site's params never sets these three fields, so this is nil/false for
-- everything except the PERF-09 identity-gate and fallback tests.
local function skill_report_opts_from_params(params)
	return {
		force_cache_miss_indices = to_index_set(params.force_cache_miss_indices),
		force_native_cache_unavailable = params.force_native_cache_unavailable and true or nil,
		corrupt_cache_indices = to_index_set(params.corrupt_cache_indices),
	}
end

-- Match group.displaySkillList's selected skill to its calc-time counterpart in
-- env.player.activeSkillList. These are NOT the same table objects (display-list rows are
-- rebuilt separately from the calc pass), so identity must go through the stable
-- gem/item source instance, not table equality on the display-list's `.activeEffect`.
local function resolve_group_active_skill(group, env)
	if not (env and env.player and env.player.activeSkillList) then
		return nil
	end
	local skill = group.displaySkillList and group.displaySkillList[group.mainActiveSkill or 1]
	local wanted_src = skill and skill.activeEffect and skill.activeEffect.srcInstance
	if not wanted_src then
		return nil
	end
	for _, active_skill in ipairs(env.player.activeSkillList) do
		if active_skill.socketGroup == group and active_skill.activeEffect
			and active_skill.activeEffect.srcInstance == wanted_src then
			return active_skill
		end
	end
	return nil
end

-- Build one skill_report() row for `index` entirely from GlobalCache -- zero PoB frames.
-- Returns nil (never errors) for anything that isn't provably available, so the caller's
-- fallback is always "did this return a row", never a try/catch around calc code.
-- `opts` (test-only; every production call site omits it, see skill_report):
--   force_cache_miss_indices  {[index]=true,...}  pretend this group's entry is absent
--   force_native_cache_unavailable  true           pretend GlobalCache.cachedData.MAIN itself is gone
--   corrupt_cache_indices     {[index]=true,...}  overwrite this group's real cache entry
--                                                  with a malformed table first, to prove the
--                                                  defensive checks below (not a crash) are
--                                                  what actually runs, not merely unit logic
local function cached_group_report(index, group, opts)
	opts = opts or {}
	if opts.force_native_cache_unavailable then
		return nil
	end
	if opts.force_cache_miss_indices and opts.force_cache_miss_indices[index] then
		return nil
	end
	local main_env = build.calcsTab.mainEnv
	local matched = resolve_group_active_skill(group, main_env)
	if not matched then
		return nil
	end
	local cached = GlobalCache and GlobalCache.cachedData and GlobalCache.cachedData.MAIN
	if not cached then
		return nil
	end
	local ok, uuid = pcall(cacheSkillUUID, matched, main_env)
	if not ok or not uuid then
		return nil
	end
	if opts.corrupt_cache_indices and opts.corrupt_cache_indices[index] then
		-- Test-only: simulate a malformed entry (UUID present, expected shape missing) to
		-- exercise the defensive checks below for real, not just by code inspection.
		cached[uuid] = { Name = "corrupted-for-test" }
	end
	local entry = cached[uuid]
	if type(entry) ~= "table" or type(entry.Env) ~= "table"
		or type(entry.Env.player) ~= "table" or type(entry.Env.player.output) ~= "table" then
		return nil
	end
	local env = entry.Env
	local row = group_identity(index, group, env)
	row.output = offense_output(env.player.output)
	row.show_average = row.show_average or per_hit_combined_signature(env.player.output)
	row.damage_owner = row.output.Minion and "MINION" or "PLAYER"
	row.output_table = row.output.Minion and "mainOutput.Minion" or "mainOutput"
	return row
end

-- Per-group PoB output: make each enabled group main in turn, recalc, capture, restore.
-- Read-only with respect to the build (mainSocketGroup is restored before return).
--
-- PERF-03 (diagnostic only, opt-in under params.perf): one recalc per requested group
-- plus one trailing recalc to restore mainSocketGroup -- both counted here as they run,
-- attributed to this call so a caller can tell native discovery's frame cost apart from
-- the candidate/restore frames around it.
--
-- PERF-04: `defer_restore_frame` restores mainSocketGroup (the property write) but skips
-- the trailing recalc(). Safe ONLY when the caller guarantees a recalculation happens
-- before mainOutput/mainEnv are read again for any purpose -- see tx_measure, which uses
-- this exclusively for the LAST slot of a batched item-slot transaction, where the very
-- next recalc is tx_finish's own (never an intermediate frame-free check that would read
-- stale calc state). Not used by any other caller.
local function skill_report(indices, defer_restore_frame, opts)
	local t_report = PERF.on and perf_now() or 0
	local frames_before = PERF.frames
	local original = build.mainSocketGroup
	local groups = {}
	local selected = nil
	local requested = 0
	local cache_hits, cache_misses = 0, 0
	if type(indices) == "table" then
		selected = {}
		for _, index in ipairs(indices) do
			selected[tonumber(index)] = true
			requested = requested + 1
		end
	end
	local ok, err = pcall(function()
		for index, group in ipairs(build.skillsTab.socketGroupList) do
			local applicable = (not selected or selected[index]) and group.enabled and group.slotEnabled ~= false
				and group.displaySkillList and #group.displaySkillList > 0
			local row
			if applicable then
				-- PERF-09: try the zero-frame GlobalCache path first. A nil result means
				-- "not provably available for this group" (never partial/wrong data), so
				-- the switch-and-recalc fallback below is the only path that ever runs
				-- when the cache can't answer -- exactly today's behaviour for that group.
				row = cached_group_report(index, group, opts)
				if row then
					cache_hits = cache_hits + 1
				else
					cache_misses = cache_misses + 1
					row = group_identity(index, group)
					build.mainSocketGroup = index
					recalc()
					row.output = offense_output()
					-- displaySkillList is rebuilt by the recalc; refresh identity from it.
					local refreshed = group_identity(index, group)
					row.skill_name, row.skill_id, row.skill_level = refreshed.skill_name, refreshed.skill_id, refreshed.skill_level
					for _, field in ipairs({ "stat_set", "stat_set_index", "stat_set_count", "stat_set_key", "stat_set_resolved",
						"part_index", "part_name", "part_key", "part_resolved", "part_count", "stage_count",
						"stage_explicit", "calculation_mode" }) do
						row[field] = refreshed[field]
					end
					row.show_average = refreshed.show_average or per_hit_combined_signature(build.calcsTab.mainOutput or {})
					row.damage_owner = row.output.Minion and "MINION" or "PLAYER"
					row.output_table = row.output.Minion and "mainOutput.Minion" or "mainOutput"
				end
			else
				row = group_identity(index, group)
			end
			row.is_main = index == original
			groups[#groups + 1] = row
		end
	end)
	build.mainSocketGroup = original
	if not defer_restore_frame then
		recalc()
	end
	if PERF.on then
		PERF.marks.native_discovery_ms = (PERF.marks.native_discovery_ms or 0) + (perf_now() - t_report)
		PERF.marks.native_discovery_calls = (PERF.marks.native_discovery_calls or 0) + 1
		PERF.marks.native_discovery_frames = (PERF.marks.native_discovery_frames or 0) + (PERF.frames - frames_before)
		PERF.marks.native_cache_hits = (PERF.marks.native_cache_hits or 0) + cache_hits
		PERF.marks.native_cache_misses = (PERF.marks.native_cache_misses or 0) + cache_misses
		PERF.native_calls = PERF.native_calls or {}
		PERF.native_calls[#PERF.native_calls + 1] = {
			requested_groups = requested,
			frames = PERF.frames - frames_before,
			ms = perf_now() - t_report,
			cache_hits = cache_hits,
			cache_misses = cache_misses,
		}
	end
	if not ok then
		error({ code = "CALC_FAILED", message = "skill report failed: " .. tostring(err) })
	end
	-- collect_metrics() here means "original's own output, freshly recalculated" -- true
	-- only when the trailing recalc actually ran. In deferred mode mainOutput still
	-- reflects whichever group's read happened last, so returning it would silently hand
	-- a caller data that looks like `original`'s but isn't. Nothing reads this field today
	-- (component_report is only ever consumed via .groups, never .metrics -- see
	-- native_metric_discovery.compare_native_components), so nil rather than a plausible-
	-- looking wrong value is the safe contract for a future caller.
	local report_metrics = nil
	if not defer_restore_frame then
		report_metrics = collect_metrics()
	end
	return {
		main_socket_group = original,
		groups = groups,
		metrics = report_metrics,
		-- Always populated (unlike the PERF.marks.native_cache_* counters, which only
		-- accumulate when params.perf is set): cheap, and tests/observability should not
		-- need the diagnostic flag on just to see hit/miss counts.
		cache_stats = { hits = cache_hits, misses = cache_misses },
	}
end

-- Read-only evidence for composition research.  This exposes PoB's own
-- FullDPS membership/results; it does not recalculate, select or score skills.
local function composition_audit()
	local out = build.calcsTab.mainOutput or {}
	local entries = {}
	for _, entry in ipairs(out.SkillDPS or {}) do
		entries[#entries + 1] = {
			name = entry.name or "",
			dps = type(entry.dps) == "number" and entry.dps or nil,
			count = type(entry.count) == "number" and entry.count or nil,
			trigger = entry.trigger or "",
			source = entry.source or "",
			skill_part = entry.skillPart or "",
		}
	end
	local included = {}
	for index, group in ipairs(build.skillsTab.socketGroupList) do
		if group.includeInFullDPS then
			local identity = group_identity(index, group)
			included[#included + 1] = {
				index = index, skill_id = identity.skill_id, skill_name = identity.skill_name,
				stat_set_key = identity.stat_set_key, part_key = identity.part_key,
				group_count = group.groupCount, enabled = group.enabled and true or false,
			}
		end
	end
	return { full_dps = num(out.FullDPS), full_dot_dps = num(out.FullDotDPS), entries = entries, included = included }
end

local function main_skill_identity()
	local index = build.mainSocketGroup
	local group = build.skillsTab.socketGroupList[index]
	if not group then
		return nil
	end
	return attach_damage_owner(group_identity(index, group))
end

local function listed_full_dps_skills()
	local names = {}
	for index, group in ipairs(build.skillsTab.socketGroupList) do
		if group.includeInFullDPS and group.enabled and group.slotEnabled ~= false then
			local identity = group_identity(index, group)
			local name = identity.skill_name ~= "" and identity.skill_name or identity.display_label
			if name ~= "" then
				names[#names + 1] = name
			end
		end
	end
	table.sort(names)
	return names
end

local function build_info()
	local spec = build.spec
	local class_name = nil
	local ascend_name = nil
	if spec.tree and spec.curClassId and spec.tree.classes[spec.curClassId] then
		class_name = spec.tree.classes[spec.curClassId].name
		local asc = spec.tree.classes[spec.curClassId].classes
		if asc and spec.curAscendClassId and asc[spec.curAscendClassId] then
			ascend_name = asc[spec.curAscendClassId].name
		end
	end
	local main_group = build.skillsTab.socketGroupList[build.mainSocketGroup]
	local native_damage_groups = {}
	for index, group in ipairs(build.skillsTab.socketGroupList) do
		if group.enabled and group.slotEnabled ~= false then
			local identity = group_identity(index, group)
			if identity.native_damage_candidate then native_damage_groups[#native_damage_groups + 1] = index end
		end
	end
	return {
		build_name = build.buildName,
		class = class_name,
		ascendancy = ascend_name,
		main_skill = main_group and main_group.label or nil,
		main_skill_identity = main_skill_identity(),
		main_socket_group = build.mainSocketGroup,
		full_dps_skills = listed_full_dps_skills(),
		native_damage_group_indices = native_damage_groups,
		skill_group_count = #build.skillsTab.socketGroupList,
		passive_nodes = select(1, build.spec:CountAllocNodes()),
		ascendancy_nodes = select(2, build.spec:CountAllocNodes()),
		active_loadout = STATE.active_loadout or active_loadout_name(),
		active_item_set_id = STATE.active_item_set_id or build.itemsTab.activeItemSetId,
	}
end

-- Semantic identity of a skill group for one comparison: the same granted skill, from
-- the same kind of source (gem vs item) in the same slot, measuring the same stat set,
-- with the same gem/support setup. Never the list position, never the free-text label.
local function skill_key(identity)
	if not identity then
		return ""
	end
	local kind = (identity.source ~= "" and "item") or "gem"
	return table.concat({
		identity.skill_id or "",
		kind,
		identity.slot or "",
		identity.stat_set_key or "",
		identity.actor_id or "",
		identity.actor_skill or "",
		table.concat(identity.gems or {}, ","),
	}, "|")
end

-- After an item swap, keep PoB's main skill pointing at the same skill as the baseline.
-- Returns the candidate identity plus whether it had to be re-pinned or was lost.
local function pin_main_skill(baseline_identity)
	local current = main_skill_identity()
	local wanted = skill_key(baseline_identity)
	if wanted == "" or skill_key(current) == wanted then
		return current, false, false
	end
	for index, group in ipairs(build.skillsTab.socketGroupList) do
		local identity = group_identity(index, group)
		if skill_key(identity) == wanted then
			build.mainSocketGroup = index
			recalc()
			return main_skill_identity(), true, false
		end
	end
	return current, false, true
end

function M.fingerprint_components()
	local equipment = {}
	for _, slot_name in ipairs(slot_names()) do
		equipment[slot_name] = slot_item_raw(slot_name) or ""
	end
	local config = {}
	for k, v in pairs(CONTEXTS[STATE.context] or CONTEXTS.MAP) do
		config[k] = build.configTab.input[k]
	end
	local main_group = build.skillsTab.socketGroupList[build.mainSocketGroup]
	local main_identity = main_skill_identity()
	local set = active_tree_set()
	return {
		build_name = build.buildName,
		build_path = STATE.build_path,
		context = STATE.context,
		equipment = equipment,
		tree_nodes = tree_node_ids(),
		tree_set_index = set.index,
		tree_set_title = set.title,
		tree_version = set.tree_version,
		alloc_mode = set.alloc_mode,
		jewels = jewel_fingerprint(),
		mastery = mastery_fingerprint(),
		hash_overrides = override_fingerprint(),
		weapon_set_alloc = weapon_set_fingerprint(),
		config = config,
		main_skill = main_group and main_group.label or nil,
		main_socket_group = build.mainSocketGroup,
		main_skill_id = main_identity and main_identity.skill_id or "",
		main_skill_name = main_identity and main_identity.skill_name or "",
		main_stat_set = main_identity and main_identity.stat_set or "",
		main_stat_set_key = main_identity and main_identity.stat_set_key or "",
		main_part_index = main_identity and main_identity.part_index or nil,
		main_part_name = main_identity and main_identity.part_name or "",
		main_part_key = main_identity and main_identity.part_key or "",
		main_stage_count = main_identity and main_identity.stage_count or nil,
		main_calculation_mode = main_identity and main_identity.calculation_mode or "DIRECT",
		main_actor_id = main_identity and main_identity.actor_id or "",
		main_actor_skill = main_identity and main_identity.actor_skill or "",
		main_damage_owner = main_identity and main_identity.damage_owner or "PLAYER",
		main_output_table = main_identity and main_identity.output_table or "mainOutput",
		active_loadout = STATE.active_loadout or active_loadout_name(),
		active_item_set_id = STATE.active_item_set_id or (build.itemsTab and build.itemsTab.activeItemSetId or nil),
	}
end

local function set_item(slot_name, raw)
	local it = build.itemsTab
	local slot = it.slots[active_weapon_slot(slot_name)]
	if not slot then
		error({ code = "SLOT_INVALID", message = "unknown slot: " .. tostring(slot_name), details = { slot = slot_name } })
	end
	if not raw then
		slot:SetSelItemId(0)
		it:PopulateSlots()
		build.buildFlag = true
		return nil
	end
	local item = new("Item")
	local ok, err = pcall(function() item:ParseRaw(raw) end)
	if not ok then
		error({ code = "ITEM_PARSE_FAILED", message = tostring(err), details = { slot = slot_name } })
	end
	-- ParseRaw accepts garbage without raising and leaves no base type; such an item
	-- must never enter the build (slot population indexes item.base).
	if not item.base then
		error({ code = "ITEM_PARSE_FAILED", message = "item has no recognised base type", details = { slot = slot_name } })
	end
	it:AddItem(item, true)
	ok, err = pcall(function()
		slot:SetSelItemId(item.id)
		it:PopulateSlots()
	end)
	if not ok then
		it.items[item.id] = nil
		for index, id in ipairs(it.itemOrderList) do
			if id == item.id then
				table.remove(it.itemOrderList, index)
				break
			end
		end
		error({ code = "ITEM_INCOMPATIBLE", message = tostring(err), details = { slot = slot_name } })
	end
	build.buildFlag = true
	return item.id
end

local function normalize_raw(s)
	if not s then return "" end
	return (s:gsub("\r\n", "\n"):gsub("\r", "\n"))
end

local function floats_close(a, b, tol)
	if (a == nil) ~= (b == nil) then return false end
	a = num(a)
	b = num(b)
	if a == b then return true end
	return math.abs(a - b) <= tol
end

local function metrics_equal(a, b, tol)
	for _, k in ipairs(METRIC_FIELDS) do
		if not floats_close(a[k], b[k], tol) then
			return false, k, a[k], b[k]
		end
	end
	for _, field in ipairs(ACTOR_OUTPUT_FIELDS) do
		local k = "Minion." .. field
		if not floats_close(a[k], b[k], tol) then
			return false, k, a[k], b[k]
		end
	end
	for _, k in ipairs(PLAYER_AILMENT_FIELDS) do
		if not floats_close(a[k], b[k], tol) then
			return false, k, a[k], b[k]
		end
	end
	for _, k in ipairs(MODE_OUTPUT_FIELDS) do
		if not floats_close(a[k], b[k], tol) then
			return false, k, a[k], b[k]
		end
	end
	return true
end

local function equipment_equal(a, b)
	for slot, raw in pairs(a) do
		if (b[slot] or "") ~= (raw or "") then
			return false, slot
		end
	end
	for slot, raw in pairs(b) do
		if (a[slot] or "") ~= (raw or "") then
			return false, slot
		end
	end
	return true
end

-- ===== Candidate-state transaction ==========================================
-- PoB matches an item-granted socket group to its item by source "Item:<id>:<name>".
-- Swapping an item removes that group and appends a fresh default one, so list order,
-- mainSocketGroup and per-group calc state (includeInFullDPS, ...) do not survive a
-- swap. One comparison is therefore a transaction: snapshot the skill state, apply,
-- measure the SAME main skill (by identity), then restore the original item ids and
-- the original group tables (which PoB re-matches), and verify semantic equality.

-- Per-group state that changes what PoB calculates.
local GROUP_STATE_FIELDS = { "enabled", "includeInFullDPS", "label", "mainActiveSkill", "mainActiveSkillCalcs", "groupCount" }

local function snapshot_skill_state()
	local list = build.skillsTab.socketGroupList
	local groups, states = {}, {}
	for i, group in ipairs(list) do
		groups[i] = group
		local state = {}
		for _, field in ipairs(GROUP_STATE_FIELDS) do
			state[field] = group[field]
		end
		states[i] = state
	end
	return {
		list = list,
		groups = groups,
		states = states,
		main_index = build.mainSocketGroup,
		main_identity = main_skill_identity(),
	}
end

-- Put the original group tables back, in their original order, with their original
-- calc state. Must run before the recalc that follows re-equipping the original items.
local function restore_skill_state(snap)
	local list = snap.list
	for i = #list, 1, -1 do
		list[i] = nil
	end
	for i, group in ipairs(snap.groups) do
		list[i] = group
		for _, field in ipairs(GROUP_STATE_FIELDS) do
			group[field] = snap.states[i][field]
		end
	end
	build.mainSocketGroup = snap.main_index
end

-- Order-independent calculation state used to verify a restore.
local function semantic_state()
	local main = main_skill_identity()
	local groups, full_dps, full_dps_config = {}, {}, {}
	for i, group in ipairs(build.skillsTab.socketGroupList) do
		local identity = group_identity(i, group)
		local signature = table.concat({
			skill_key(identity),
			tostring(group.enabled and true or false),
			tostring(group.includeInFullDPS and true or false),
			tostring(group.mainActiveSkill or 1),
			tostring(group.groupCount or 1),
		}, "#")
		groups[signature] = (groups[signature] or 0) + 1
		if group.includeInFullDPS then
			full_dps[#full_dps + 1] = identity.skill_name ~= "" and identity.skill_name or identity.display_label
			full_dps_config[#full_dps_config + 1] = table.concat({
				skill_key(identity), identity.part_key or "", tostring(identity.stage_count or ""),
				identity.calculation_mode or "", tostring(group.enabled and true or false),
				tostring(group.mainActiveSkill or 1), tostring(group.groupCount or 1),
			}, "#")
		end
	end
	table.sort(full_dps)
	table.sort(full_dps_config)
	return {
		main_key = skill_key(main),
		main_skill = main and main.skill_name or "",
		stat_set = main and main.stat_set or "",
		stat_set_key = main and main.stat_set_key or "",
		part_key = main and main.part_key or "",
		stage_count = main and main.stage_count or nil,
		calculation_mode = main and main.calculation_mode or "",
		damage_owner = main and main.damage_owner or "PLAYER",
		output_table = main and main.output_table or "mainOutput",
		groups = groups,
		full_dps = full_dps,
		full_dps_config = full_dps_config,
		loadout = active_loadout_name(),
		item_set = build.itemsTab.activeItemSetId,
		tree_set = build.treeTab and build.treeTab.activeSpec or nil,
	}
end

-- Compact, JSON-friendly view of a semantic state (the group multiset is omitted).
local function semantic_summary(state)
	return {
		main_skill = state.main_skill,
		stat_set = state.stat_set,
		stat_set_key = state.stat_set_key,
		part_key = state.part_key,
		stage_count = state.stage_count,
		calculation_mode = state.calculation_mode,
		damage_owner = state.damage_owner,
		output_table = state.output_table,
		full_dps = state.full_dps,
		full_dps_config = state.full_dps_config,
		loadout = state.loadout,
		item_set = state.item_set,
	}
end

local function compare_semantic(a, b)
	if a.loadout ~= b.loadout or tostring(a.item_set) ~= tostring(b.item_set) or a.tree_set ~= b.tree_set then
		return "RESTORE_LOADOUT_MISMATCH"
	end
	if a.main_key ~= b.main_key then
		if a.main_skill == b.main_skill and a.stat_set_key ~= b.stat_set_key then
			return "RESTORE_STAT_SET_MISMATCH"
		end
		return "RESTORE_PRIMARY_SKILL_MISMATCH"
	end
	if a.part_key ~= b.part_key then return "RESTORE_SKILL_PART_MISMATCH" end
	if a.stage_count ~= b.stage_count then return "RESTORE_STAGE_CONFIGURATION_MISMATCH" end
	if a.calculation_mode ~= b.calculation_mode then return "RESTORE_CALCULATION_MODE_MISMATCH" end
	if a.damage_owner ~= b.damage_owner or a.output_table ~= b.output_table then
		return "RESTORE_DAMAGE_OWNER_MISMATCH"
	end
	if table.concat(a.full_dps, "|") ~= table.concat(b.full_dps, "|") then
		return "RESTORE_FULLDPS_MISMATCH"
	end
	if table.concat(a.full_dps_config, "|") ~= table.concat(b.full_dps_config, "|") then
		return "RESTORE_FULLDPS_CONFIG_MISMATCH"
	end
	for signature, count in pairs(a.groups) do
		if b.groups[signature] ~= count then
			return "RESTORE_SKILL_GROUPS_MISMATCH"
		end
	end
	for signature, count in pairs(b.groups) do
		if a.groups[signature] ~= count then
			return "RESTORE_SKILL_GROUPS_MISMATCH"
		end
	end
	return nil
end

-- PERF-06: the structural half of compare_semantic -- everything in a semantic_state()
-- snapshot that PERF-05's research proved is fresh (rebuilt every recalc, for every
-- enabled group, regardless of which one is mainSocketGroup) or independent of recalc
-- entirely (declarative config PoB's calc engine only ever reads, never writes):
-- main/part identity (skill_id, source, slot, stat_set_key, actor_id, actor_skill --
-- actor_id/actor_skill specifically come from srcInstance.skillMinionCalcs, a gem-
-- instance field the calc engine never touches), loadout/item_set/tree_set, the
-- skill-groups multiset (same identity fields plus declarative group config), and
-- full_dps (skill names/labels only -- also rebuilt every recalc regardless of which
-- group is active).
--
-- Intentionally NOT checked here -- see the PERF-06 report for the full trace:
-- stage_count and calculation_mode (both flow through group_identity's `active_flags`,
-- which trusts calcsTab.mainEnv.player.mainSkill whenever the group's own index happens
-- to equal build.mainSocketGroup -- an index match that does not imply mainEnv actually
-- describes that group after a property-only restore); damage_owner and output_table
-- (read directly from calcsTab.mainOutput/mainOutput.Minion, which describes whichever
-- group was mainSocketGroup during the LAST recalc, not necessarily the one being
-- verified); and full_dps_config, which embeds calculation_mode/stage_count per FullDPS
-- group and so inherits the same risk for any group that happens to be the current
-- mainSocketGroup.
--
-- These calc-derived fields remain tx_finish's responsibility: it always runs its own
-- recalc before its own full compare_semantic, so by the time they are actually checked,
-- they are guaranteed fresh. This function must never be used as a substitute for that
-- final check -- only to let an intermediate slot skip a frame it does not need.
local function compare_semantic_structural(a, b)
	if a.loadout ~= b.loadout or tostring(a.item_set) ~= tostring(b.item_set) or a.tree_set ~= b.tree_set then
		return "RESTORE_LOADOUT_MISMATCH"
	end
	if a.main_key ~= b.main_key then
		if a.main_skill == b.main_skill and a.stat_set_key ~= b.stat_set_key then
			return "RESTORE_STAT_SET_MISMATCH"
		end
		return "RESTORE_PRIMARY_SKILL_MISMATCH"
	end
	if a.part_key ~= b.part_key then return "RESTORE_SKILL_PART_MISMATCH" end
	if table.concat(a.full_dps, "|") ~= table.concat(b.full_dps, "|") then
		return "RESTORE_FULLDPS_MISMATCH"
	end
	for signature, count in pairs(a.groups) do
		if b.groups[signature] ~= count then
			return "RESTORE_SKILL_GROUPS_MISMATCH"
		end
	end
	for signature, count in pairs(b.groups) do
		if a.groups[signature] ~= count then
			return "RESTORE_SKILL_GROUPS_MISMATCH"
		end
	end
	return nil
end

-- Remove a throw-away candidate item once nothing references it.
local function discard_item(item_id)
	local it = build.itemsTab
	if not item_id or not it.items[item_id] then
		return
	end
	for _, slot in pairs(it.slots) do
		if slot.selItemId == item_id then
			return
		end
	end
	for _, item_set in pairs(it.itemSets or {}) do
		for _, entry in pairs(item_set) do
			if type(entry) == "table" and entry.selItemId == item_id then
				return
			end
		end
	end
	it.items[item_id] = nil
	for index, id in ipairs(it.itemOrderList) do
		if id == item_id then
			table.remove(it.itemOrderList, index)
			break
		end
	end
end

-- Apply `changes` ({ slot, raw } with raw=nil clearing the slot), measure, restore, verify.
-- Returns baseline / candidate / restored blocks; raises RESTORE_FAILED (worker marked
-- unhealthy) with a precise reason when the restored state is not the baseline.
local function component_indices_for_keys(keys)
	local indices = {}
	for _, key in ipairs(keys) do
		local matches = {}
		for index, group in ipairs(build.skillsTab.socketGroupList) do
			if group.enabled and group.slotEnabled ~= false and skill_key(group_identity(index, group)) == key then
				matches[#matches + 1] = index
			end
		end
		-- An ambiguous or removed group is not substituted with another one.
		if #matches == 1 then indices[#indices + 1] = matches[1] end
	end
	return indices
end

-- PERF-02: one item comparison is still one transaction, but a transaction can now
-- cover several candidate slots and can defer its restore.
--
--   baseline A -> measure slot 1 -> revert+measure slot 2 -> ... -> restore -> verify A
--
-- Two costs leave the user-visible path:
--
--   * the per-slot restore recalculation. Reverting the previous slot mutation and
--     applying the next one both happen before a single recalculation, so N slots cost
--     N candidate frames instead of 2N. Reverting without a frame of its own is sound
--     because recalc() recomputes the whole build from current state; it never
--     accumulates. What a revert cannot prove without a frame is metric equality, so
--     the cheap half of the verification -- equipment and the structural (non-calc-
--     derived) half of semantic state, both pure reads -- still runs between slots
--     (tx_assert_reverted_structural; see PERF-06 for why it is the structural half,
--     not the full one).
--
--   * the final restore + verification, which prepares the NEXT comparison and is not
--     needed to produce this one. Under params.defer_restore it is parked in
--     STATE.pending and drained by M.dispatch before anything else reads or mutates the
--     build, so no request can ever start from an unverified candidate state.
--
-- The integrity contract is unchanged: every candidate is measured from a baseline some
-- earlier transaction verified, and a failed restore still marks the worker unhealthy so
-- no later request runs on a corrupt state.

-- ITEM-CHECK-SOCKET-NORM: `params.baseline_overrides` (slot -> raw item text) lets
-- the "ignore socketed modifiers" Item Check setting substitute a normalized
-- version of the currently equipped item for BASELINE MEASUREMENT ONLY. The
-- override is applied here, once, right after the true pre-mutation state is
-- captured (`true_baseline_*`) and before `ctx.baseline_*` -- the values every
-- candidate delta and the returned "baseline" block are computed against -- are
-- read. `ctx.working_selection` is the item-id set the batch reverts to BETWEEN
-- slot measurements (tx_revert); it includes the override items so they stay
-- equipped for every slot in this transaction. `ctx.original_selection` (the
-- true, un-overridden ids) and `ctx.true_baseline_*` are untouched by any of this
-- and are what the FINAL restore (tx_finish) reverts to and verifies against --
-- the build is always left exactly as it truly was, override or not.
local function tx_begin(params)
	local it = build.itemsTab
	-- M1.3: settle the calc engine before trusting it as "the baseline", rather
	-- than reading `collect_metrics()` straight off whatever
	-- `build.calcsTab.mainOutput` already held. This is defensive, not a
	-- complete fix: a real public fixture (core04_minion_actor.xml, a
	-- minion-actor build with count-based unique jewels) was observed to
	-- capture a `true_baseline_metrics` reading (Minion.CombinedDPS=64539.5)
	-- that disagreed with every OTHER read of the same untouched build
	-- (repeated `get_metrics`, and this same transaction's own later
	-- recalculated restore, both converging on 67033.8) even with this
	-- `recalc()` already in place -- so the root cause is not simply "not yet
	-- settled" and remains only partially understood (see
	-- `docs/POB2_ENGINE_CONTRACT.md`'s Jewel section, "stateful/accumulating
	-- main skills"). This call is kept because it is cheap (a settle loop that
	-- returns immediately once already-converged, see `SETTLE_MAX_FRAMES`) and
	-- is provably harmless, but it must not be read as having resolved that
	-- finding.
	recalc()
	local ctx = {
		tolerance = params.tolerance or 0.5,
		test_fault = params.test_fault,
		created = {},
		baseline_created = {},
		true_baseline_fp = M.fingerprint_components(),
		true_baseline_metrics = collect_metrics(),
		true_baseline_semantic = semantic_state(),
	}
	ctx.snap = snapshot_skill_state()
	-- Every slot, not only the changed ones: equipping one item can unequip another
	-- (two-handers vs off-hand). M1.3: this MUST also include jewel-socket slots
	-- (`slot.nodeId` set) -- they used to be filtered out here because nothing
	-- wrote to them, but `set_item`/`ItemSlotClass:SetSelItemId` already handles
	-- them correctly (writes `spec.jewels[nodeId]` instead of
	-- `activeItemSet[slotName].selItemId`, see Phase A audit q2/q10), so the
	-- ONLY thing standing between a jewel evaluation and a corrupted build was
	-- this transaction never tracking (and therefore never restoring) the
	-- jewel-socket slots it touched.
	ctx.original_selection = {}
	for slot_name, slot in pairs(it.slots) do
		ctx.original_selection[slot_name] = slot.selItemId or 0
	end
	ctx.working_selection = {}
	for slot_name, item_id in pairs(ctx.original_selection) do
		ctx.working_selection[slot_name] = item_id
	end

	local overrides = params.baseline_overrides
	if type(overrides) == "table" and next(overrides) ~= nil then
		-- Applying an override mutates the build (set_item adds/selects an item), so a
		-- failure partway through -- e.g. a second overridden slot whose normalized
		-- text fails to parse, after a first slot's override already landed -- must
		-- not leave that partial mutation in place. tx_begin itself is never called
		-- under pcall by its callers (it used to be pure reads, so nothing could ever
		-- need rolling back); now that it can mutate, it must be exception-safe on
		-- its own. On failure this rolls back to the TRUE original selection created
		-- above and discards any override items already created, before re-raising.
		local override_ok, override_err = pcall(function()
			for slot_name, raw in pairs(overrides) do
				if not it.slots[slot_name] then
					error({ code = "SLOT_INVALID", message = "unknown slot: " .. tostring(slot_name), details = { slot = slot_name } })
				end
				local item_id = set_item(slot_name, raw)
				if item_id then
					ctx.baseline_created[#ctx.baseline_created + 1] = item_id
					-- Must key by the PHYSICAL slot `set_item` actually wrote to (see
					-- `active_weapon_slot`), not the logical name: this dict is what
					-- `tx_revert`/`tx_revert_final` use to decide which physical slot
					-- to restore. Keying it by the logical name here would corrupt the
					-- primary slot's own (untouched) restore record -- see the
					-- weapon-swap defect this guards against.
					ctx.working_selection[active_weapon_slot(slot_name)] = item_id
				end
			end
		end)
		if not override_ok then
			local cleanup_ok = pcall(function()
				for slot_name, item_id in pairs(ctx.original_selection) do
					local slot = it.slots[slot_name]
					if slot.selItemId ~= item_id then
						slot:SetSelItemId(item_id)
					end
				end
				for _, item_id in ipairs(ctx.baseline_created) do
					discard_item(item_id)
				end
				ctx.baseline_created = {}
				it:PopulateSlots()
			end)
			if not cleanup_ok then
				-- The build may still be holding a partial override; never let a later
				-- request treat it as trustworthy.
				STATE.healthy = false
			end
			if type(override_err) == "table" and override_err.code then error(override_err) end
			error({ code = "ITEM_INCOMPATIBLE", message = tostring(override_err), details = { slots = overrides } })
		end
		recalc()
		ctx.baseline_fp = M.fingerprint_components()
		ctx.baseline_metrics = collect_metrics()
		ctx.baseline_semantic = semantic_state()
		ctx.baseline_overridden = true
	else
		ctx.baseline_fp = ctx.true_baseline_fp
		ctx.baseline_metrics = ctx.true_baseline_metrics
		ctx.baseline_semantic = ctx.true_baseline_semantic
		ctx.baseline_overridden = false
	end
	return ctx
end

local function tx_baseline_block(ctx)
	return {
		fingerprint = ctx.baseline_fp,
		metrics = ctx.baseline_metrics,
		equipment = ctx.baseline_fp.equipment,
		primary_skill = ctx.snap.main_identity,
		semantic = semantic_summary(ctx.baseline_semantic),
		overridden = ctx.baseline_overridden or false,
	}
end

-- Put the batch's working items and skill groups back WITHOUT recalculating. Used
-- BETWEEN slot measurements (and, when there is no baseline override, at the very
-- end too): reverts to `ctx.working_selection`, which is the true original items
-- unless a baseline override is active, in which case it is the override items --
-- either way, exactly what this transaction's shared baseline measures. Discards
-- only `ctx.created` (throw-away candidate items); override items are not
-- throw-away for the life of the transaction and must survive every inter-slot
-- revert. See `tx_revert_final` for the transaction-closing revert to the TRUE
-- pre-override state.
local function tx_revert(ctx)
	local it = build.itemsTab
	for slot_name, item_id in pairs(ctx.working_selection) do
		local slot = it.slots[slot_name]
		if slot.selItemId ~= item_id then
			slot:SetSelItemId(item_id)
		end
	end
	-- Drop throw-away candidate items before PopulateSlots: a malformed candidate
	-- (e.g. no base type) would otherwise break slot population during the restore.
	for _, item_id in ipairs(ctx.created) do
		discard_item(item_id)
	end
	ctx.created = {}
	it:PopulateSlots()
	restore_skill_state(ctx.snap)
end

-- The transaction-closing revert: always the TRUE, un-overridden equipped items,
-- regardless of any baseline override -- the build must never be left holding a
-- baseline-override item once evaluation is done. Discards both the transient
-- candidate items and any baseline-override items created in `tx_begin`.
local function tx_revert_final(ctx)
	local it = build.itemsTab
	for slot_name, item_id in pairs(ctx.original_selection) do
		local slot = it.slots[slot_name]
		if slot.selItemId ~= item_id then
			slot:SetSelItemId(item_id)
		end
	end
	for _, item_id in ipairs(ctx.created) do
		discard_item(item_id)
	end
	for _, item_id in ipairs(ctx.baseline_created) do
		discard_item(item_id)
	end
	ctx.created = {}
	ctx.baseline_created = {}
	it:PopulateSlots()
	restore_skill_state(ctx.snap)
end

-- The frame-free half of the restore verification, run between slots so a corrupted
-- revert can never become the baseline for the next slot measurement. Both reads are
-- pure (no recalc); this is why it can only use compare_semantic_STRUCTURAL, not the
-- full comparator -- see that function's comment for exactly which fields are excluded
-- and why. tx_finish is the other half: it always recalculates before its own full
-- compare_semantic, so the calc-derived fields this function skips are still verified,
-- just at the end of the transaction rather than at every inter-slot boundary. PERF-04
-- already shipped this exact tradeoff for the last slot (skill_report's own restore
-- frame); PERF-06 extends it to every slot, per the PERF-05 research spike.
local function tx_assert_reverted_structural(ctx, next_slot)
	local fp = M.fingerprint_components()
	local eq_ok, bad_slot = equipment_equal(fp.equipment, ctx.baseline_fp.equipment)
	local reason
	if not eq_ok then
		reason = "RESTORE_EQUIPMENT_MISMATCH"
	else
		reason = compare_semantic_structural(ctx.baseline_semantic, semantic_state())
	end
	if reason then
		STATE.healthy = false
		error({
			code = "RESTORE_FAILED",
			message = "inter-slot revert does not match baseline (" .. reason .. ")",
			details = { reason = reason, equipment_match = eq_ok, bad_slot = bad_slot, next_slot = next_slot },
		})
	end
end

-- M1.3: the RECALCULATING half of the inter-slot check, used for jewel-socket
-- batches instead of `tx_assert_reverted_structural`. Unlike ordinary
-- equipment, a jewel can change which tree-granted skill groups exist (e.g. a
-- Timeless Jewel's Conquered/Desecrated-passive transformation, or a cluster
-- jewel's own granted notables -- see Phase A audit q13 and
-- `PassiveSpecClass:BuildClusterJewelGraphs`, which `ItemSlotClass:SetSelItemId`
-- already calls on every jewel-socket change). `compare_semantic_STRUCTURAL`
-- trusts calc-derived fields (including which "Tree:<node>" skill groups are
-- currently pinned) without a recalc -- proven UNSAFE for jewels empirically:
-- reverting a Timeless-Jewel-socket swap and immediately reading
-- `snapshot_skill_state()` without recalculating first can observe the
-- CANDIDATE frame's stale tree-granted group set, which correctly does not
-- match the true (Timeless-Jewel-holding) baseline -- a false-positive
-- RESTORE_FAILED, not a real corruption (proven by the fact the exact same
-- socket passes both the single-slot case and "timeless jewel measured last"
-- case, where no frame-skipped structural check ever runs against it). This
-- function pays for one recalculation per jewel-socket transition instead of
-- risking that false failure (and the `STATE.healthy = false` fail-closed
-- lockout a real one would trigger).
local function tx_assert_reverted_full(ctx, next_slot)
	recalc()
	local fp = M.fingerprint_components()
	local eq_ok, bad_slot = equipment_equal(fp.equipment, ctx.baseline_fp.equipment)
	local reason, bad_metric, bad_a, bad_b
	if not eq_ok then
		reason = "RESTORE_EQUIPMENT_MISMATCH"
	else
		reason = compare_semantic(ctx.baseline_semantic, semantic_state())
	end
	if not reason then
		local metric_ok
		metric_ok, bad_metric, bad_a, bad_b = metrics_equal(collect_metrics(), ctx.baseline_metrics, ctx.tolerance)
		if not metric_ok then
			reason = "RESTORE_METRICS_MISMATCH"
		end
	end
	if reason then
		STATE.healthy = false
		error({
			code = "RESTORE_FAILED",
			message = "inter-slot revert does not match baseline (" .. reason .. ")",
			details = {
				reason = reason, equipment_match = eq_ok, bad_slot = bad_slot, next_slot = next_slot,
				bad_metric = bad_metric, baseline_value = bad_a, restored_value = bad_b,
			},
		})
	end
end

-- M1.3: cheap-first, recalc-only-on-suspicion inter-slot check for jewel
-- batches. Empirically, unconditionally recalculating on EVERY jewel-socket
-- transition (`tx_assert_reverted_full` on every slot) is itself risky for a
-- different reason than the one it was built to fix: on public fixtures whose
-- main skill accumulates state across calc passes (stage-based skills,
-- ailment/DoT stacking, some minion actor chains -- proven on
-- core04_mixed_hit_ailment.xml and core04_stage_context.xml), MORE
-- recalculations of an unchanged build produce a MEASURABLY DIFFERENT number
-- than fewer would, so paying for a recalculation at every one of a jewel
-- batch's (potentially 5-19) inter-slot transitions can itself manufacture a
-- false RESTORE_FAILED that a cheaper, equipment-style check would never have
-- triggered. Ordinary jewels never change tree-granted skill groups, so the
-- cheap structural check (no recalc, matches equipment's own inter-slot path)
-- passes them with zero extra cost. Only a socket that ALREADY looks
-- suspicious under the cheap check (in practice: a Timeless Jewel changing
-- which "Tree:<node>" skill groups exist, per Phase A audit q13) pays for one
-- confirming recalculation before being called a real restore failure -- and
-- that confirming recalculation is exactly `tx_assert_reverted_full` above.
local function tx_assert_reverted_jewel_batch(ctx, next_slot)
	local fp = M.fingerprint_components()
	local eq_ok, bad_slot = equipment_equal(fp.equipment, ctx.baseline_fp.equipment)
	if eq_ok then
		local structural_reason = compare_semantic_structural(ctx.baseline_semantic, semantic_state())
		if not structural_reason then
			return
		end
	end
	tx_assert_reverted_full(ctx, next_slot)
end

-- Measure one candidate state: the baseline with `changes` applied. One recalculation.
--
-- PERF-04/PERF-06: `in_batch` lets native component discovery (if any) skip its own
-- trailing restore recalc -- see the integrity-design note above skill_report's call
-- below. Pass it only from the batched item-slot path (run_item_slot_evaluation), for
-- every slot: the inter-slot check that follows a non-last slot is now
-- tx_assert_reverted_STRUCTURAL, which -- unlike the full check -- never reads the
-- calc-derived state this skips refreshing, so it is safe for every slot in the batch,
-- not only the last one. run_equipment_transaction never passes it, so its behaviour
-- (and frame count) is exactly what it was before PERF-04.
local function tx_measure(ctx, changes, params, in_batch)
	local candidate = {}
	local t = perf_now()
	for _, change in ipairs(changes) do
		local item_id = set_item(change.slot, change.raw)
		if item_id then
			ctx.created[#ctx.created + 1] = item_id
		end
	end
	perf_add("candidate_set_item_ms", t)
	t = perf_now()
	recalc()
	perf_add("candidate_recalc_ms", t)
	t = perf_now()
	local skill, repinned, changed = pin_main_skill(ctx.snap.main_identity)
	perf_add("candidate_pin_skill_ms", t)
	t = perf_now()
	candidate.primary_skill = skill
	candidate.primary_skill_repinned = repinned
	candidate.primary_skill_changed = changed
	candidate.metrics = collect_metrics()
	candidate.fingerprint = M.fingerprint_components()
	candidate.semantic = semantic_summary(semantic_state())
	perf_add("candidate_read_ms", t)
	if type(params.component_keys) == "table" and #params.component_keys > 0 then
		-- Optional, bounded PoB component reads inside the *same* item transaction.
		-- No ExileLens damage formula and no second candidate item evaluation.
		-- Deliberately outside candidate_read_ms: this is an optional extra PoB
		-- read (skill_report) gated on native-damage-discovery being applicable,
		-- not part of the baseline candidate measurement TOOLTIP-PERF times.
		--
		-- PERF-04/PERF-06 integrity design: skill_report switches mainSocketGroup across
		-- other groups and back; `candidate.metrics`/`.fingerprint`/`.semantic` above were
		-- all captured BEFORE it ran, so they are immutable and correct regardless of what
		-- happens next -- nothing native discovery does can retroactively change what this
		-- slot already measured. The `metrics_equal` check below is therefore not
		-- protecting the delivered data; it is a defensive tripwire against PoB's calc
		-- engine being non-deterministic across a mainSocketGroup round-trip (recalc for
		-- group B, then back to A, giving a different answer for A than a direct recalc
		-- would).
		--
		-- Skipping this call's own trailing recalc (and this specific check) is safe when
		-- we are in the batched item-slot path (`in_batch`), for every slot, not only the
		-- last: whatever runs next -- tx_assert_reverted_structural for a non-last slot,
		-- tx_finish for the last one -- either does not read the calc-derived state this
		-- skips refreshing (the structural check), or refreshes it itself before reading
		-- it (tx_finish's own recalc). PERF-05's research proved the risk this used to
		-- guard against: an inter-slot check that DOES trust stale calc-derived state
		-- (damage_owner, output_table, calculation_mode, stage_count, and skill_key's
		-- actor_id/actor_skill IF read the wrong way -- see compare_semantic_structural's
		-- comment) would spuriously fail any multi-slot item whose discovered secondary
		-- component differs from the primary in those fields, which is a real build shape,
		-- not a hypothetical one. tx_assert_reverted_structural never reads them, so it
		-- cannot be fooled by them, and cannot spuriously fail because of them either.
		-- run_equipment_transaction (direct/general callers) never passes `in_batch`, so
		-- their behaviour is exactly what it was before PERF-04.
		-- Test-only fault injection params (force_cache_miss_indices etc.) flow through
		-- exactly like any other transaction param; every production caller's params
		-- table never sets them, so this is a no-op opts table in normal operation.
		local cache_opts = skill_report_opts_from_params(params)
		if in_batch then
			candidate.component_report = skill_report(component_indices_for_keys(params.component_keys), true, cache_opts)
			if PERF.on and PERF.native_calls then
				PERF.native_calls[#PERF.native_calls].slot = changes[1] and changes[1].slot or nil
			end
		else
			candidate.component_report = skill_report(component_indices_for_keys(params.component_keys), false, cache_opts)
			if PERF.on and PERF.native_calls then
				-- Tag the call this block just produced with the slot it measured, so a
				-- multi-slot transaction's per-slot native-discovery cost is visible.
				PERF.native_calls[#PERF.native_calls].slot = changes[1] and changes[1].slot or nil
			end
			local unchanged = metrics_equal(collect_metrics(), candidate.metrics, ctx.tolerance)
			if not unchanged then
				error({ code = "CALC_FAILED", message = "component report changed selected candidate output" })
			end
		end
	end
	return candidate
end

-- Restore the TRUE baseline (discarding any socket-normalization override along
-- with the candidate) and prove it: equipment, semantic calc state, then metrics
-- -- always against `ctx.true_baseline_*`, never the (possibly overridden)
-- `ctx.baseline_*` used for candidate deltas. Raises RESTORE_FAILED (worker marked
-- unhealthy) when the restored state does not match.
local function tx_finish(ctx)
	local t_restore = perf_now()
	local restore_ok, restore_err = pcall(function()
		tx_revert_final(ctx)
		if ctx.test_fault == "corrupt_restore" then
			-- Test hook: simulate a restore that lands on another skill.
			build.mainSocketGroup = (ctx.snap.main_index % #ctx.snap.list) + 1
		end
		perf_add("restore_apply_ms", t_restore)
		local t = perf_now()
		recalc()
		perf_add("restore_recalc_ms", t)
	end)
	if not restore_ok then
		STATE.healthy = false
		error({ code = "RESTORE_FAILED", message = tostring(restore_err), details = { reason = "RESTORE_EXCEPTION" } })
	end

	local t_verify = perf_now()
	local restored_metrics = collect_metrics()
	local restored_fp = M.fingerprint_components()
	local restored_semantic = semantic_state()
	local reason, bad_metric, bad_a, bad_b
	local eq_ok, bad_slot = equipment_equal(restored_fp.equipment, ctx.true_baseline_fp.equipment)
	if not eq_ok then
		reason = "RESTORE_EQUIPMENT_MISMATCH"
	else
		reason = compare_semantic(ctx.true_baseline_semantic, restored_semantic)
	end
	if not reason then
		local metric_ok
		metric_ok, bad_metric, bad_a, bad_b = metrics_equal(restored_metrics, ctx.true_baseline_metrics, ctx.tolerance)
		if not metric_ok then
			reason = "RESTORE_METRICS_MISMATCH"
		end
	end
	if reason then
		STATE.healthy = false
		error({
			code = "RESTORE_FAILED",
			message = "restored state does not match baseline (" .. reason .. ")",
			details = {
				reason = reason,
				equipment_match = eq_ok,
				bad_slot = bad_slot,
				bad_metric = bad_metric,
				baseline_value = bad_a,
				restored_value = bad_b,
				baseline = semantic_summary(ctx.true_baseline_semantic),
				restored = semantic_summary(restored_semantic),
			},
		})
	end
	perf_add("verify_ms", t_verify)
	return {
		fingerprint = restored_fp,
		metrics = restored_metrics,
		equipment = restored_fp.equipment,
		primary_skill = main_skill_identity(),
		semantic = semantic_summary(restored_semantic),
		restore_ok = true,
	}
end

local function perf_payload_now(t_perf)
	if not PERF.on then return nil end
	PERF.marks.total_ms = perf_now() - t_perf
	PERF.marks.recalc_frames = PERF.frames
	PERF.marks.frame_ms = PERF.frame_ms
	PERF.marks.frame_why = PERF.frame_why
	PERF.marks.native_calls = PERF.native_calls
	local payload = PERF.marks
	PERF.on = false
	PERF.native_calls = nil
	return payload
end

local function run_equipment_transaction(changes, params)
	params = params or {}
	PERF.on = params.perf and true or false
	if PERF.on then perf_begin() end
	local t_perf = perf_now()
	local it = build.itemsTab
	for _, change in ipairs(changes) do
		if not it.slots[change.slot] then
			error({ code = "SLOT_INVALID", message = "unknown slot: " .. tostring(change.slot), details = { slot = change.slot } })
		end
	end

	local ctx = tx_begin(params)
	perf_add("baseline_read_ms", t_perf)

	local candidate
	local ok, err = pcall(function()
		candidate = tx_measure(ctx, changes, params)
	end)

	-- The restore runs even when the measurement failed: the build must never be left
	-- holding a candidate item.
	local restored = tx_finish(ctx)

	if not ok then
		if type(err) == "table" and err.code then error(err) end
		error({ code = "ITEM_INCOMPATIBLE", message = tostring(err), details = { changes = changes } })
	end

	return {
		perf = perf_payload_now(t_perf),
		baseline = tx_baseline_block(ctx),
		candidate = candidate,
		restored = restored,
		restore = { status = "OK" },
	}
end

-- PERF-02: every compatible slot for one item, measured inside a single transaction.
-- One baseline read, N candidate frames, one restore -- instead of N independent
-- transactions costing 2N frames.
local function run_item_slot_evaluation(slots, item_raw, params)
	params = params or {}
	PERF.on = params.perf and true or false
	if PERF.on then perf_begin() end
	local t_perf = perf_now()
	local it = build.itemsTab
	if type(slots) ~= "table" or #slots == 0 then
		error({ code = "SLOT_INVALID", message = "at least one slot is required" })
	end
	for _, slot in ipairs(slots) do
		if it.slots[slot] == nil then
			error({ code = "SLOT_INVALID", message = "slot not present in build", details = { slot = slot } })
		end
	end

	-- Baseline item summaries must be read before anything is mutated.
	local slot_items = {}
	for _, slot in ipairs(slots) do
		slot_items[slot] = slot_item_summary(slot)
	end

	-- M1.3: a jewel-socket batch cannot safely use the PERF-06 frame-skipped
	-- structural-only inter-slot check -- see `tx_assert_reverted_full`'s
	-- comment for the empirically-proven false-positive RESTORE_FAILED this
	-- avoids (a Timeless Jewel socket transition can change which tree-granted
	-- skill groups exist, which the structural check cannot see without a
	-- recalc). Mixed batches do not occur in practice (one item's compatible
	-- slots are either all equipment or all jewel sockets, never both -- see
	-- `resolve_compatible_slots_for_item`), so "any slot in this batch is a
	-- jewel socket" is an unambiguous, cheap batch-level classification.
	local is_jewel_batch = false
	for _, slot in ipairs(slots) do
		if is_jewel_socket_slot_name(slot) then
			is_jewel_batch = true
			break
		end
	end

	local ctx = tx_begin(params)
	perf_add("baseline_read_ms", t_perf)

	local measured = {}
	for index, slot in ipairs(slots) do
		if index > 1 then
			-- Back to baseline equipment and groups. The measurement below recalculates
			-- once, so this needs no frame; the frame-free half of the verification that
			-- a frame would give us runs here (equipment), or a full recalculating check
			-- (jewel sockets -- see `is_jewel_batch` above).
			local reverted, revert_err = pcall(tx_revert, ctx)
			if not reverted then
				STATE.healthy = false
				error({
					code = "RESTORE_FAILED",
					message = tostring(revert_err),
					details = { reason = "REVERT_EXCEPTION", next_slot = slot },
				})
			end
			if is_jewel_batch then
				tx_assert_reverted_jewel_batch(ctx, slot)
			else
				tx_assert_reverted_structural(ctx, slot)
			end
		end
		-- PERF-06: every slot in the batch lets native component discovery (if any) skip
		-- its own trailing restore recalc -- see tx_measure's integrity-design note. The
		-- inter-slot check above is the structural half specifically because it must
		-- tolerate this; tx_finish (after the last slot) is the calc-derived-inclusive
		-- half, and it always recalculates first. A jewel batch already pays for a full
		-- recalculating inter-slot check above, so it gets no benefit from (and does not
		-- request) the frame-skip here either.
		local ok, result = pcall(tx_measure, ctx, { { slot = slot, raw = item_raw } }, params, not is_jewel_batch)
		if ok then
			local candidate = result
			candidate.equipment = candidate.fingerprint.equipment
			candidate.item_present = normalize_raw(candidate.equipment[slot]) == normalize_raw(item_raw)
			measured[#measured + 1] = { slot = slot, candidate = candidate, slot_item = slot_items[slot] }
		else
			-- A legal slot whose measurement raised is reported as a failed slot, not a
			-- silent drop. RESTORE_FAILED is never swallowed: the build state is then in
			-- doubt, so the whole transaction stops here.
			if type(result) == "table" and result.code == "RESTORE_FAILED" then
				error(result)
			end
			local code = (type(result) == "table" and result.code) or "SLOT_EVALUATION_FAILED"
			local message = (type(result) == "table" and result.message) or tostring(result)
			measured[#measured + 1] = {
				slot = slot,
				slot_item = slot_items[slot],
				error = { code = code, message = message, details = (type(result) == "table" and result.details) or nil },
			}
		end
	end

	if params.defer_restore then
		STATE.pending = ctx
		return {
			perf = perf_payload_now(t_perf),
			context = STATE.context,
			baseline = tx_baseline_block(ctx),
			true_baseline = { fingerprint = ctx.true_baseline_fp, metrics = ctx.true_baseline_metrics },
			slots = measured,
			restore = { status = "DEFERRED" },
		}
	end

	local restored = tx_finish(ctx)
	return {
		perf = perf_payload_now(t_perf),
		context = STATE.context,
		baseline = tx_baseline_block(ctx),
		true_baseline = { fingerprint = ctx.true_baseline_fp, metrics = ctx.true_baseline_metrics },
		slots = measured,
		restored = restored,
		restore = { status = "OK" },
	}
end

local function evaluate_tree_path(params)
	local spec = build.spec
	local target_id = tonumber(params.target_id or (params.node_ids and params.node_ids[#params.node_ids]))
	local provided = params.node_ids
	local status = "VALID"
	local path_ids = {}
	local undo = spec:CreateUndoState()
	-- Tree nodes can grant skills ("Tree:<node>" groups) just like items do.
	local skill_snapshot = snapshot_skill_state()
	local baseline_fp = M.fingerprint_components()
	local baseline_metrics = collect_metrics()
	local mutated = false
	local candidate_metrics = nil
	local candidate_fp = nil

	local function restore()
		spec:RestoreUndoState(undo)
		restore_skill_state(skill_snapshot)
		recalc()
	end

	local function fail_restore(err)
		STATE.healthy = false
		error({
			code = "RESTORE_FAILED",
			message = tostring(err or "tree restore failed"),
			details = { target_id = target_id },
		})
	end

	local ok, err = pcall(function()
		if not target_id then
			status = "INVALID_NODE"
			return
		end
		local target = spec.nodes[target_id]
		if not target then
			status = "INVALID_NODE"
			return
		end
		local _product, support = classify_node(target)
		if support == "UNSUPPORTED_SPECIAL_NODE" then
			status = "UNSUPPORTED_SPECIAL_NODE"
			path_ids = { target_id }
			return
		end
		if target.alloc then
			status = "ALREADY_ALLOCATED"
			path_ids = {}
			return
		end
		local path_nodes
		if provided and #provided > 0 then
			local converted = ids_to_nodes(provided)
			if not converted then
				status = "INVALID_NODE"
				return
			end
			path_nodes = converted
		else
			path_nodes = spec:GetAllocationPath(target, spec.allocMode or 0) or target.path
		end
		if not path_nodes or #path_nodes == 0 then
			status = "UNREACHABLE"
			return
		end
		for _, n in ipairs(path_nodes) do
			if not n.alloc then
				path_ids[#path_ids + 1] = n.id
			end
		end
		if #path_ids == 0 then
			status = "ALREADY_ALLOCATED"
			return
		end
		if not target.path then
			target.path = path_nodes
		end
		mutated = true
		spec:AllocNode(target, path_nodes)
		recalc()
		candidate_metrics = collect_metrics()
		candidate_fp = M.fingerprint_components()
	end)

	if not ok then
		local restored, restore_err = pcall(restore)
		if not restored then
			fail_restore(restore_err)
		end
		local restored_metrics = collect_metrics()
		local metric_ok = metrics_equal(restored_metrics, baseline_metrics, params.tolerance or 0.5)
		if not metric_ok then
			STATE.healthy = false
			error({
				code = "RESTORE_FAILED",
				message = "restored metrics do not match baseline after tree error",
				details = { target_id = target_id },
			})
		end
		if type(err) == "table" and err.code then
			error(err)
		end
		error({ code = "CALC_FAILED", message = tostring(err), details = { target_id = target_id } })
	end

	local restored, restore_err = pcall(restore)
	if not restored then
		fail_restore(restore_err)
	end
	local restored_metrics = collect_metrics()
	local restored_fp = M.fingerprint_components()
	local eq_ok = equipment_equal(restored_fp.equipment, baseline_fp.equipment)
	local metric_ok, bad_key, bad_a, bad_b = metrics_equal(restored_metrics, baseline_metrics, params.tolerance or 0.5)
	local tree_ok = true
	local bnodes = baseline_fp.tree_nodes or {}
	local rnodes = restored_fp.tree_nodes or {}
	if #bnodes ~= #rnodes then
		tree_ok = false
	else
		for i = 1, #bnodes do
			if bnodes[i] ~= rnodes[i] then
				tree_ok = false
				break
			end
		end
	end
	local restore_ok = eq_ok and metric_ok and tree_ok
	if not restore_ok then
		STATE.healthy = false
		error({
			code = "RESTORE_FAILED",
			message = "restored tree state does not match baseline",
			details = {
				equipment_match = eq_ok,
				metric_match = metric_ok,
				tree_match = tree_ok,
				bad_metric = bad_key,
				baseline_value = bad_a,
				restored_value = bad_b,
				target_id = target_id,
				mutated = mutated,
			},
		})
	end

	return {
		status = status,
		target_id = target_id,
		path = path_ids,
		cost = #path_ids,
		context = STATE.context,
		baseline = {
			fingerprint = baseline_fp,
			metrics = baseline_metrics,
			equipment = baseline_fp.equipment,
		},
		candidate = {
			fingerprint = candidate_fp or baseline_fp,
			metrics = candidate_metrics or baseline_metrics,
			equipment = (candidate_fp and candidate_fp.equipment) or baseline_fp.equipment,
		},
		restored = {
			fingerprint = restored_fp,
			metrics = restored_metrics,
			equipment = restored_fp.equipment,
			restore_ok = restore_ok,
		},
	}
end

function M.dispatch(req)
	local method = req.method
	local params = req.params or {}
	-- TOOLTIP-PERF: every request starts with timing off, so a transaction that
	-- errors out cannot leave it collecting frames for unrelated later calls.
	PERF.on = false

	-- PERF-02: settle a deferred restore before anything else can read or mutate the
	-- build. This is the guarantee that no request ever starts from an unverified
	-- candidate state, and it is held here -- by the component that owns the state --
	-- rather than by any caller. finalize_transaction settles it itself; shutdown does
	-- not care.
	--
	-- load_build does not run the deferred restore: the build is about to be replaced, so
	-- recalculating and verifying a state we are throwing away is wasted work and the
	-- riskiest thing we could do to an already-suspect build. It does put the baseline
	-- items and skill groups back, which is frame-free and cannot fail a verification,
	-- so PoB never re-parses a build that is still holding a candidate item. Clearing
	-- STATE.revision additionally forces the full re-parse, so load_build can never take
	-- its reuse path and hand back a dirty build. Together this is what makes load_build
	-- a reliable recovery path.
	if STATE.pending and method ~= "finalize_transaction" and method ~= "shutdown" then
		local ctx = STATE.pending
		STATE.pending = nil
		if method == "load_build" then
			pcall(tx_revert_final, ctx)
			STATE.revision = nil
		else
			tx_finish(ctx)
		end
	end

	if method == "ping" then
		return { pong = true, healthy = STATE.healthy, loaded = STATE.loaded }
	end

	if method == "engine_info" then
		return {
			loaded = STATE.loaded,
			healthy = STATE.healthy,
			build_path = STATE.build_path,
			context = STATE.context,
			slots = STATE.loaded and slot_names() or {},
		}
	end

	if method == "shutdown" then
		return { shutting_down = true }
	end

	-- PERF-02: complete a deferred restore. Returns IDLE when the dispatch drain above
	-- already finished it, so the caller can always ask without tracking who got there
	-- first. Placed before the loaded/healthy guards: it finishes work already begun.
	if method == "finalize_transaction" then
		local ctx = STATE.pending
		if not ctx then
			return { status = "IDLE" }
		end
		STATE.pending = nil
		local restored = tx_finish(ctx)
		return { status = "OK", restored = restored, restore = { status = "OK" } }
	end

	if method == "unload_build" then
		STATE.pending = nil
		STATE.loaded = false
		STATE.build_path = nil
		STATE.revision = nil
		STATE.healthy = true
		return { unloaded = true }
	end

	if method == "load_build" then
		local path = params.path
		if not path then
			error({ code = "BUILD_NOT_FOUND", message = "path is required" })
		end
		local requested_context = params.context or STATE.context
		local requested_revision = params.revision
		-- Reuse the parsed build only for the same file AND the same bytes. A path match
		-- alone used to return the pre-save build forever (stale equipment after a PoB save).
		-- Never reuse a build whose restore failed: recovery must re-parse the bytes.
		if STATE.loaded and STATE.healthy and STATE.build_path == path and requested_revision ~= nil and STATE.revision == requested_revision then
			if requested_context ~= STATE.context then
				STATE.context = requested_context
				apply_context(STATE.context)
				recalc()
			end
			STATE.active_loadout = active_loadout_name()
			STATE.active_item_set_id = build.itemsTab.activeItemSetId
			return {
				build = build_info(),
				fingerprint = M.fingerprint_components(),
				metrics = collect_metrics(),
				equipment = M.get_equipment(),
				reloaded = false,
				revision = STATE.revision,
			}
		end
		-- xml_path: a snapshot of the exact bytes the caller hashed (see build_source.py).
		local xml = read_file(params.xml_path or path)
		local ok, err = pcall(function()
			loadBuildFromXML(xml, path)
			runCallback("OnFrame")
		end)
		if not ok then
			-- The previous build may be half-replaced: never reuse it. The caller reloads
			-- its last known-good bytes explicitly.
			STATE.loaded = false
			STATE.healthy = false
			STATE.build_path = nil
			STATE.revision = nil
			error({ code = "BUILD_PARSE_FAILED", message = tostring(err), details = { path = path } })
		end
		STATE.loaded = true
		STATE.healthy = true
		STATE.build_path = path
		STATE.revision = requested_revision
		STATE.context = requested_context
		apply_context(STATE.context)
		recalc()
		STATE.active_loadout = active_loadout_name()
		STATE.active_item_set_id = build.itemsTab.activeItemSetId
		return {
			build = build_info(),
			fingerprint = M.fingerprint_components(),
			metrics = collect_metrics(),
			equipment = M.get_equipment(),
			reloaded = true,
			revision = STATE.revision,
		}
	end

	if not STATE.loaded then
		error({ code = "NO_BUILD_LOADED", message = "load_build must be called first" })
	end
	if not STATE.healthy then
		error({ code = "WORKER_UNHEALTHY", message = "worker session is unhealthy; reload build" })
	end

	if method == "set_context" then
		local ctx = params.context or "MAP"
		if not CONTEXTS[ctx] then
			error({ code = "CALC_FAILED", message = "unknown context: " .. tostring(ctx) })
		end
		STATE.context = ctx
		apply_context(ctx)
		recalc()
		return { context = ctx, metrics = collect_metrics() }
	end

	if method == "get_build_info" then
		return { build = build_info(), fingerprint = M.fingerprint_components(), metrics = collect_metrics() }
	end

	if method == "list_loadouts" then
		return list_loadouts()
	end

	if method == "list_item_sets" then
		return list_item_sets()
	end

	if method == "set_active_loadout" then
		return set_active_loadout(params.name)
	end

	if method == "set_active_item_set" then
		return set_active_item_set(params.item_set_id)
	end

	if method == "list_tree_sets" then
		return list_tree_sets()
	end

	if method == "set_active_tree_set" then
		return set_active_tree_set(params.tree_set_id)
	end

	if method == "get_equipment" then
		return { equipment = M.get_equipment(), slots = slot_names() }
	end

	if method == "get_skill_report" then
		-- Test-only fault injection (PERF-09 identity-gate / fallback tests; every
		-- production caller omits these params, see cached_group_report's doc comment).
		-- PERF tracking mirrors run_equipment_transaction/run_item_slot_evaluation: opt-in
		-- under params.perf, inert (and costing nothing beyond skill_report's own
		-- always-on cache_stats) otherwise.
		PERF.on = params.perf and true or false
		if PERF.on then perf_begin() end
		local t_perf = perf_now()
		local report = skill_report(params.indices, false, skill_report_opts_from_params(params))
		report.perf = perf_payload_now(t_perf)
		return report
	end

	-- PERF-06 regression tooling (diagnostic; not on any product path): pins the exact
	-- field-inclusion contract between compare_semantic and compare_semantic_structural
	-- as a pure-function test -- given two semantic-state-shaped tables, what does each
	-- comparator say? This is how the tests prove the structural check tolerates a
	-- damage_owner/output_table/calculation_mode/stage_count-only difference (the PERF-05
	-- "bounded gap") while the full comparator still catches it, without needing to
	-- reproduce real PoB calc staleness to exercise that specific contract.
	if method == "debug_compare_semantic" then
		return {
			structural = compare_semantic_structural(params.a, params.b),
			full = compare_semantic(params.a, params.b),
		}
	end
	if method == "get_composition_audit" then
		return composition_audit()
	end

	if method == "get_metrics" then
		if params.context and params.context ~= STATE.context then
			STATE.context = params.context
			apply_context(params.context)
			recalc()
		end
		return { context = STATE.context, raw = collect_metrics(), fingerprint = M.fingerprint_components() }
	end

	if method == "apply_live_equipment" then
		-- Persistent (not a transaction), but the main skill must still follow its
		-- identity when PoB re-appends item-granted groups.
		local main_identity = main_skill_identity()
		local equipment = params.equipment or {}
		for _, entry in ipairs(equipment) do
			local slot = entry.slot
			local raw = entry.item_raw
			if slot and raw and raw ~= "" then
				set_item(slot, raw)
			end
		end
		recalc()
		pin_main_skill(main_identity)
		return {
			applied = true,
			equipment = M.get_equipment(),
			fingerprint = M.fingerprint_components(),
			metrics = collect_metrics(),
		}
	end

	if method == "parse_item" then
		local item_raw = params.item_raw
		if not item_raw then
			error({ code = "ITEM_PARSE_FAILED", message = "item_raw is required" })
		end
		local item = parse_item_object(item_raw)
		local summary = item_summary(item)
		local slot_resolution = STATE.loaded and resolve_compatible_slots_for_item(item) or nil
		return {
			parse_ok = true,
			identity = {
				name = summary.name,
				base_name = summary.base_name,
				rarity = summary.rarity,
				type = summary.type,
				sub_type = summary.sub_type,
			},
			category = summary.type,
			display_name = summary.name ~= "?" and summary.name or summary.base_name,
			valid_slot_families = { summary.primary_slot },
			primary_slot = summary.primary_slot,
			item = summary,
			compatible_slots = slot_resolution and slot_resolution.compatible_slots or {},
			weapon_layout = slot_resolution and slot_resolution.weapon_layout or nil,
			weapon_layout_reason = slot_resolution and slot_resolution.weapon_layout_reason or nil,
			allocated_jewel_socket_count = slot_resolution and slot_resolution.allocated_jewel_socket_count or nil,
			excluded_connectivity_risky_socket_count = slot_resolution and slot_resolution.excluded_connectivity_risky_socket_count or nil,
		}
	end

	if method == "resolve_compatible_slots" then
		local item_raw = params.item_raw
		if not item_raw then
			error({ code = "ITEM_PARSE_FAILED", message = "item_raw is required" })
		end
		local item = parse_item_object(item_raw)
		local resolution = resolve_compatible_slots_for_item(item)
		return {
			item = item_summary(item),
			compatible_slots = resolution.compatible_slots,
			weapon_layout = resolution.weapon_layout,
			weapon_layout_reason = resolution.weapon_layout_reason,
			allocated_jewel_socket_count = resolution.allocated_jewel_socket_count,
			excluded_connectivity_risky_socket_count = resolution.excluded_connectivity_risky_socket_count,
		}
	end

	if method == "evaluate_gear_plan" then
		local replacements = params.replacements or {}
		if params.context and params.context ~= STATE.context then
			STATE.context = params.context
			apply_context(params.context)
		end

		local changes = {}
		for _, entry in ipairs(replacements) do
			if entry.slot and entry.item_raw and entry.item_raw ~= "" then
				changes[#changes + 1] = { slot = entry.slot, raw = entry.item_raw }
			end
		end
		local tx = run_equipment_transaction(changes, params)
		local final = tx.candidate
		final.equipment = final.fingerprint.equipment
		return {
			context = STATE.context,
			baseline = tx.baseline,
			final = final,
			restored = tx.restored,
			restore = {
				equipment_match = true,
				fingerprint_match = true,
				metrics_match = true,
				pass = true,
			},
			restore_status = tx.restore,
		}
	end

	if method == "evaluate_item_slots" then
		if params.context and params.context ~= STATE.context then
			STATE.context = params.context
			apply_context(params.context)
		end
		if not params.item_raw then error({ code = "ITEM_PARSE_FAILED", message = "item_raw is required" }) end
		return run_item_slot_evaluation(params.slots, params.item_raw, params)
	end

	if method == "evaluate_candidate" then
		local slot = params.slot
		local item_raw = params.item_raw
		if not slot then error({ code = "SLOT_INVALID", message = "slot is required" }) end
		if not item_raw then error({ code = "ITEM_PARSE_FAILED", message = "item_raw is required" }) end
		if params.context and params.context ~= STATE.context then
			STATE.context = params.context
			apply_context(params.context)
		end

		-- PERF-01: this used to also test fingerprint_components().equipment[slot], which
		-- serialised every slot's raw item text and the whole allocated tree just to
		-- answer one nil question. That test could never fire independently: the
		-- equipment table is built from slot_names(), i.e. exactly the keys of
		-- build.itemsTab.slots, and an empty slot is stored as "" rather than nil. So
		-- equipment[slot] == nil holds if and only if slots[slot] == nil. Same
		-- "slot populated / slot missing" semantics, no serialisation.
		if build.itemsTab.slots[slot] == nil then
			error({ code = "SLOT_INVALID", message = "slot not present in build", details = { slot = slot } })
		end
		local slot_item = slot_item_summary(slot)
		local tx = run_equipment_transaction({ { slot = slot, raw = item_raw } }, params)
		local candidate = tx.candidate
		candidate.equipment = candidate.fingerprint.equipment
		candidate.item_present = normalize_raw(candidate.equipment[slot]) == normalize_raw(item_raw)
		tx.baseline.slot_item = slot_item
		return {
			slot = slot,
			context = STATE.context,
			perf = tx.perf,
			baseline = tx.baseline,
			candidate = candidate,
			restored = tx.restored,
			restore_status = tx.restore,
		}
	end

	if method == "evaluate_slot_cleared" then
		local slot = params.slot
		if not slot then error({ code = "SLOT_INVALID", message = "slot is required" }) end
		if params.context and params.context ~= STATE.context then
			STATE.context = params.context
			apply_context(params.context)
		end

		if build.itemsTab.slots[slot] == nil or M.fingerprint_components().equipment[slot] == nil then
			error({ code = "SLOT_INVALID", message = "slot not present in build", details = { slot = slot } })
		end
		local slot_item = slot_item_summary(slot)
		local tx = run_equipment_transaction({ { slot = slot, raw = nil } }, params)
		local cleared = tx.candidate
		cleared.equipment = cleared.fingerprint.equipment
		tx.baseline.slot_item = slot_item
		return {
			slot = slot,
			context = STATE.context,
			baseline = tx.baseline,
			cleared = cleared,
			restored = tx.restored,
			restore = {
				equipment_match = true,
				fingerprint_match = true,
				metrics_match = true,
				pass = true,
			},
			restore_status = tx.restore,
		}
	end

	if method == "get_tree_snapshot" then
		return collect_tree_snapshot()
	end

	if method == "evaluate_tree_path" then
		return evaluate_tree_path(params)
	end

	error({ code = "CALC_FAILED", message = "unknown method: " .. tostring(method) })
end

function M.get_equipment()
	local equipment = {}
	for _, slot_name in ipairs(slot_names()) do
		equipment[#equipment + 1] = slot_item_summary(slot_name)
	end
	return equipment
end

function M.handle_json(json_text)
	local req = json.decode(json_text)
	local ok, result = xpcall(function()
		return M.dispatch(req)
	end, function(err)
		if type(err) == "table" and err.code then return err end
		return { code = "CALC_FAILED", message = tostring(err) }
	end)
	if ok then
		return json.encode({ id = req.id, ok = true, result = result })
	end
	return json.encode({ id = req.id, ok = false, error = result })
end

return M
