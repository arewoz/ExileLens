"""Generate Windows version resources from the canonical ``exilelens._version``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from exilelens._version import __version__  # noqa: E402
from exilelens.ops.packaging_version import render_version_info  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "packaging" / "version_info.txt",
        help="path to write (default: packaging/version_info.txt)",
    )
    parser.add_argument("--check", action="store_true", help="exit 1 when output would change")
    args = parser.parse_args(argv)
    rendered = render_version_info()
    target = args.output.resolve()
    if args.check:
        current = target.read_text(encoding="utf-8") if target.is_file() else ""
        if current != rendered:
            print(f"version resource stale: {target}", file=sys.stderr)
            return 1
        return 0
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(rendered, encoding="utf-8")
    print(f"wrote {target} ({__version__})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
