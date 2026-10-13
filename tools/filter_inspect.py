"""Explain why an item is shown or hidden by the build-aware filter, for every profile (offline, from a stored needs snapshot).

    python tools/filter_inspect.py --needs artifacts/filter08c/needs/blood_mage_spark_urka.json --base "Voltaic Staff" --rarity Rare --ilvl 84
    python tools/filter_inspect.py --needs A.json --compare B.json --base "Plated Greaves" --rarity Magic --ilvl 88 --profiles Strict Endgame
    python tools/filter_inspect.py --needs A.json --base "Plated Greaves" --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from exilelens.filters import inspector  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--needs", required=True, help="stored BuildNeedsSnapshot JSON")
    parser.add_argument("--compare", help="a second needs snapshot to compare against")
    parser.add_argument("--base", required=True, help="item base type, e.g. 'Plated Greaves'")
    parser.add_argument("--rarity", default="Rare", choices=("Normal", "Magic", "Rare", "Unique"))
    parser.add_argument("--ilvl", type=int, default=82)
    parser.add_argument("--quality", type=int, default=0)
    parser.add_argument("--unid-tier", type=int, default=0)
    parser.add_argument("--profiles", nargs="*", default=list(inspector.PROFILE_NAMES))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    needs = inspector.load_needs(args.needs)
    other = inspector.load_needs(args.compare) if args.compare else None
    item = inspector.make_item(args.base, rarity=args.rarity, item_level=args.ilvl, quality=args.quality, unidentified_tier=args.unid_tier)
    inspection = inspector.inspect(needs, item, profiles=args.profiles, compare=other)
    print(json.dumps(inspection.to_dict(), indent=1, sort_keys=True, default=str) if args.json else inspector.render(inspection))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
