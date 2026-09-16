# Live Tree Overlay

> **EXPERIMENTAL — HUMAN VALIDATION INCOMPLETE / PARKED**  
> Not a primary product workflow after UX-01. Access via tray → Live Tree Overlay [Experimental] or Dashboard TREE → Advanced / Experimental.

Click-through **guidance** drawn over Path of Exile 2's own passive tree art. The overlay never copies node art, edges, or backgrounds.

Default mode is **PoB BUILD PATH**: the selected Path of Building allocation, not live in-game points and not a value heatmap.

## Modes

1. BUILD PATH — snapshot allocated nodes + edges (no PoB node-value evals)
2. NEXT POINTS — evaluated legal frontier from cache
3. VALUE HEATMAP — evaluated nearby/frontier targets by existing Build Value bands

## Window policy

`PERSISTENT_TREE_OVERLAY`

- transparent, click-through, no focus
- ordinary clicks go to the game and do **not** dismiss the overlay
- bound to the PoE **client area** via Win32 window geometry (not game memory)
- item evaluation overlay is raised above it

Interactive controls live in Dashboard TREE → Advanced / Experimental and the tray experimental submenu, never on the click-through surface. Calibration capture is a temporary `INTERACTIVE_TRANSPARENT_CAPTURE` layer (Esc cancels).

## Visibility diagnostics

Show Overlay Test Pattern and Overlay Debug exist specifically because 5A.6B failed the human gate (overlay effectively invisible). If the test pattern cannot be seen over PoE, stop and fix z-order/geometry before trusting transforms.

## Honesty

This overlay cannot see PoE pan/zoom. Calibration is one viewport. After pan: Quick Re-align. After zoom: Recalibrate Scale. There is no OCR, computer vision, or game memory.
