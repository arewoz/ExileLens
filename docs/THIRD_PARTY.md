# Third-party components

## Path of Building 2 (external engine)

| Field | Value |
|---|---|
| Source | https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2 |
| License | MIT (see `LICENSE.md` in engine checkout) |
| Usage | Normal installed distribution or developer checkout invoked headlessly |
| Tested revision | `97cb973f8a114d32010bc1a4195c170628771714` |

PoB ships `lua51.dll` (PUC-Rio Lua / LuaJIT-compatible runtime). This product loads that DLL, PoB's Lua modules, data, and assets from the configured installation at runtime; those components are not copied into ExileLens.

PoB's installer intentionally excludes `src/HeadlessWrapper.lua` and `src/_SimpleGraphic.def.lua`. ExileLens therefore ships an adapted headless bootstrap and a vendored copy of the SimpleGraphic headless API definitions from the tested upstream revision. PoB is MIT-licensed, permitting use, modification, and redistribution provided the copyright and permission notice is included. The release package includes that notice in `THIRD_PARTY_NOTICES.txt`.

## Archived local tooling

Stormweaver optimization scripts under `pob2-local-artifacts/tooling-archive/tools/` are local research artifacts. Phase 1 **adapted concepts** from `run.py`, `lab.lua`, and `mut.lua` into new files in this repository (`src/exilelens/pob/lua_host.py`, `runtime/lua/bridge.lua`). No bulk copy of the archive.

## External references consulted (secondary)

- PathOfBuildingCommunity/PathOfBuilding-PoE2 headless wrapper pattern
- Community MCP-style PoB2 wrappers (architecture validation only; not used as primary implementation)

No third-party code was vendored into this repository in Phase 1. Installed-PoB support subsequently added only the two small headless support files described above; it does not redistribute the PoB application, runtime DLLs, modules, data, or assets.
