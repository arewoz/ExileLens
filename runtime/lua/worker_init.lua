-- Persistent worker entrypoint. Loaded once by the Python host after HeadlessWrapper boot.

local original_require = require
assert(POE2VALUE_HEADLESS_WRAPPER, "POE2VALUE_HEADLESS_WRAPPER is required")
dofile(POE2VALUE_HEADLESS_WRAPPER)
require = original_require

local bridge_path = POE2VALUE_BRIDGE or os.getenv("POE2VALUE_BRIDGE")
assert(bridge_path, "POE2VALUE_BRIDGE is required")
local bridge = dofile(bridge_path)

function poe2value_dispatch(json_text)
	return bridge.handle_json(json_text)
end

function poe2value_ping()
	return bridge.handle_json('{"id":0,"method":"ping","params":{}}')
end

return true
