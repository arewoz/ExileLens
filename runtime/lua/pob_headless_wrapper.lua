-- ExileLens headless bootstrap for Path of Building Community (PoE2).
-- Adapted from PoB's MIT-licensed src/HeadlessWrapper.lua; see
-- packaging/THIRD_PARTY_NOTICES.txt for copyright and license details.

assert(POE2VALUE_SIMPLEGRAPHIC_DEF, "POE2VALUE_SIMPLEGRAPHIC_DEF is required")
assert(POE2VALUE_POB_PROGRAM, "POE2VALUE_POB_PROGRAM is required")
dofile(POE2VALUE_SIMPLEGRAPHIC_DEF)

function GetVirtualScreenSize()
	return 1920, 1080
end

__callbackTable__ = { }

function runCallback(name, ...)
	if __callbackTable__[name] then
		return __callbackTable__[name](...)
	elseif __mainObject__ and __mainObject__[name] then
		return __mainObject__[name](__mainObject__, ...)
	end
end

local l_require = require
function require(name)
	-- The headless worker does not use PoB's update/network UI.
	if name == "lcurl.safe" then
		return
	end
	return l_require(name)
end

dofile(POE2VALUE_POB_PROGRAM .. "/Launch.lua")

-- Prevent loading ModCache, matching PoB's upstream headless wrapper.
__mainObject__.continuousIntegrationMode = os.getenv("CI")
-- ExileLens must never update or mutate the user's installed PoB directory.
__mainObject__.CheckForUpdate = function() end

runCallback("OnInit")
runCallback("OnFrame")

if __mainObject__.promptMsg then
	error("Path of Building startup failed: " .. tostring(__mainObject__.promptMsg))
end

build = __mainObject__.main.modes["BUILD"]

function newBuild()
	if GlobalCache and GlobalCache.cachedData then
		wipeGlobalCache()
	end
	__mainObject__.main:SetMode("BUILD", false, "ExileLens headless build")
	runCallback("OnFrame")
end

function loadBuildFromXML(xmlText, name)
	__mainObject__.main:SetMode("BUILD", false, name or "", xmlText)
	runCallback("OnFrame")
end

function loadBuildFromJSON(characterJSON)
	__mainObject__.main:SetMode("BUILD", false, "")
	runCallback("OnFrame")
	local dkjson = require "dkjson"
	local input = dkjson.decode(characterJSON)
	build.importTab:ImportItemsAndSkills(input)
	build.importTab:ImportPassiveTreeAndJewels(input)
end
