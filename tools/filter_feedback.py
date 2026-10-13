"""Local natural-drop logging (no telemetry, no network). Cases are written to the local feedback directory only.

    python tools/filter_feedback.py capture --needs build_needs.json --profile Recommended --base "Plated Greaves" --rarity Magic --ilvl 88 \
        --annotation "VALUABLE MISS" [--note "text"] [--dir DIR]
    python tools/filter_feedback.py replay --needs build_needs.json [--dir DIR]
    python tools/filter_feedback.py export [--dir DIR]          # labelled items as a build-independent corpus (JSON on stdout)

Annotations: SHOULD SHOW | SHOULD HIDE | UNSURE | VALUABLE MISS | NOISE
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from exilelens.filters import feedback, inspector  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    cap = sub.add_parser("capture")
    cap.add_argument("--needs", required=True)
    cap.add_argument("--profile", default="Recommended")
    cap.add_argument("--base", required=True)
    cap.add_argument("--rarity", default="Rare", choices=("Normal", "Magic", "Rare", "Unique"))
    cap.add_argument("--ilvl", type=int, default=82)
    cap.add_argument("--quality", type=int, default=0)
    cap.add_argument("--unid-tier", type=int, default=0)
    cap.add_argument("--annotation", required=True, choices=tuple(feedback.ANNOTATIONS))
    cap.add_argument("--note", default="")
    cap.add_argument("--include-label", action="store_true")
    rep = sub.add_parser("replay")
    rep.add_argument("--needs", required=True)
    for p in (cap, rep, sub.add_parser("export")):
        p.add_argument("--dir", default=None)
    args = parser.parse_args(argv)
    directory = Path(args.dir) if args.dir else None
    if args.command == "capture":
        needs = inspector.load_needs(args.needs)
        item = inspector.make_item(args.base, rarity=args.rarity, item_level=args.ilvl, quality=args.quality, unidentified_tier=args.unid_tier)
        case = feedback.capture(needs, args.profile, item, args.annotation, note=args.note, include_label=args.include_label)
        path = feedback.save(case, directory)
        print(f"saved {path.name}: observed {case.observed} via {case.observed_rule}; labelled {case.annotation}")
    elif args.command == "replay":
        needs = inspector.load_needs(args.needs)
        for case in feedback.load_all(directory):
            result = feedback.replay(case, needs)
            print(f"{result.case_id}: {result.verdict} (expected {result.expected}, now {result.now or '-'}, rules changed: {result.rules_changed})")
    else:
        print(json.dumps(feedback.natural_drop_corpus(feedback.load_all(directory)), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
