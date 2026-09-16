# Tree overlay calibration

Two-surface workflow. Alignment is **manual**. Coordinates are Qt logical pixels relative to the **PoE client area**.

## Flow

1. In Tree Coach, click a recognizable allocated notable/keystone → **Use as Anchor A**.
2. Click a distant node → **Use as Anchor B**. (Suggest Anchors is optional.)
3. **Capture A** then **Capture B**: click the matching in-game node centers.
4. Fit a **2-point similarity** transform (translation, uniform scale, rotation). BUILD PATH preview appears immediately.
5. Looks Good / Fine Tune (X ±1/±10, Y ±1/±10, Scale ±0.1%/±1%) / Recalibrate.
6. Optional: verify with a third node (reprojection error). Not required.

## Recovery

- Pan: **Quick Re-align** — one click, translation only, scale kept.
- Zoom: **Recalibrate Scale** — two clicks on the same PoB anchors.
- Window move: overlay follows the client rectangle; client-local transform stays valid.
- Window resize / DPI / layout identity change: calibration may be **STALE**.

## Out of scope

OCR, screenshots, template matching, game process memory, DLL injection, synthetic input into Path of Exile 2.
