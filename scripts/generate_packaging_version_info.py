"""Generate the Windows version resources (GUI and updater) from the canonical ``exilelens._version``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from exilelens._version import __version__  # noqa: E402
from exilelens.ops.packaging_version import EXECUTABLES, render_version_info  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="exit 1 when any resource would change")
    args = parser.parse_args(argv)
    stale = False
    for identity in EXECUTABLES:
        target = (ROOT / identity.version_file).resolve()
        rendered = render_version_info(identity=identity)
        if args.check:
            current = target.read_text(encoding="utf-8") if target.is_file() else ""
            if current != rendered:
                print(f"version resource stale: {identity.version_file}", file=sys.stderr)
                stale = True
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered, encoding="utf-8")
        print(f"wrote {identity.version_file} ({__version__})")
    return 1 if stale else 0


if __name__ == "__main__":
    raise SystemExit(main())
