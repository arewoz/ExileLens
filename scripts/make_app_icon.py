"""Generate the multi-resolution Windows ICO from the ExileLens source PNG.

    python scripts/make_app_icon.py

Reads ``assets/app/exilelens.png`` (the canonical high-resolution source, which
is never modified) and writes ``assets/app/exilelens.ico`` containing every size
Windows asks for, with transparency preserved.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_PNG = REPO_ROOT / "assets" / "app" / "exilelens.png"
TARGET_ICO = REPO_ROOT / "assets" / "app" / "exilelens.ico"
SIZES = (16, 24, 32, 48, 64, 128, 256)


def build_ico(source: Path = SOURCE_PNG, target: Path = TARGET_ICO) -> Path:
    if not source.is_file():
        raise SystemExit(f"Source icon not found: {source}")

    with Image.open(source) as img:
        img = img.convert("RGBA")
        # Square the canvas without cropping, so no size in the ICO is distorted.
        side = max(img.size)
        if img.size != (side, side):
            canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
            canvas.paste(img, ((side - img.width) // 2, (side - img.height) // 2))
            img = canvas
        # Downsample each size explicitly with LANCZOS; Pillow's ICO writer would
        # otherwise resize with the lower-quality default filter, which turns the
        # fine gold filigree to mush at 16x16 and 24x24.
        frames = [img.resize((s, s), Image.LANCZOS) for s in sorted(SIZES, reverse=True)]
        target.parent.mkdir(parents=True, exist_ok=True)
        frames[0].save(
            target,
            format="ICO",
            sizes=[(s, s) for s in SIZES],
            append_images=frames[1:],
        )

    return target


def main() -> int:
    target = build_ico()
    with Image.open(target) as ico:
        found = sorted(ico.info.get("sizes", ()))
    print(f"Wrote {target} ({target.stat().st_size} bytes)")
    print("Sizes: " + ", ".join(f"{w}x{h}" for w, h in found))
    missing = {s for s in SIZES} - {w for w, _ in found}
    if missing:
        print(f"WARNING: missing sizes {sorted(missing)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
