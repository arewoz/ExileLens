"""M5.5: before/after comparison of the M5.4 and M5.5 validation artifacts (prints markdown)."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
before = {b["id"]: b for b in json.loads((ROOT / "artifacts" / "m5_4_priorities_validation.json").read_text())["builds"]}
after = {b["id"]: b for b in json.loads((ROOT / "artifacts" / "m5_5_priorities_validation.json").read_text())["builds"]}
LANES = ("offense", "ehp", "max_hit", "mobility", "multi_axis")


def lane_flags(b: dict) -> str:
    p = b["priorities"]
    return "".join(k[0].upper() if p[k] else "-" for k in ("offense", "ehp", "max_hit", "mobility", "multi_axis"))


def fix(b: dict) -> str:
    return ", ".join(r["title"] for r in b["priorities"]["fix_first"]) or "-"


rows = []
for name, a in after.items():
    b = before[name]
    pb, pa = b["priorities"]["coverage"], a["priorities"]["coverage"]
    rows.append(
        f"| {name} | {lane_flags(b)} → {lane_flags(a)} | {fix(b)} → {fix(a)} | "
        f"{pb['counts'].get('MEASURED', 0)}/{pb['counts'].get('NO_SIGNAL', 0)}/{len(pb['not_established'])} → "
        f"{pa['counts'].get('MEASURED', 0)}/{pa['counts'].get('NO_SIGNAL', 0)}/{len(pa['not_established'])} | {b['pob_recalcs']} → {a['pob_recalcs']} |"
    )
print("| Build | Lanes D/E/M/V/X before → after | FIX FIRST before → after | measured/no-signal/not-established | recalcs |")
print("|---|---|---|---|---|")
print("\n".join(rows))


def total(d: dict, f) -> int:
    return sum(f(b) for b in d.values())


print()
for label, f in (
    ("builds with non-empty DAMAGE", lambda b: bool(b["priorities"]["offense"])),
    ("non-empty EHP", lambda b: bool(b["priorities"]["ehp"])),
    ("non-empty MAX HIT", lambda b: bool(b["priorities"]["max_hit"])),
    ("non-empty MOVEMENT", lambda b: bool(b["priorities"]["mobility"])),
    ("with FIX FIRST", lambda b: bool(b["priorities"]["fix_first"])),
    ("with MULTI-IMPACT", lambda b: bool(b["priorities"]["multi_axis"])),
    ("FIX FIRST containing mana", lambda b: any(r["kind"] == "RESOURCE" for r in b["priorities"]["fix_first"])),
    ("FIX FIRST containing chaos", lambda b: any(r["title"].startswith("Chaos") for r in b["priorities"]["fix_first"])),
    ("MEASURED signals", lambda b: b["priorities"]["coverage"]["counts"].get("MEASURED", 0)),
    ("NO_SIGNAL signals", lambda b: b["priorities"]["coverage"]["counts"].get("NO_SIGNAL", 0)),
    ("not established", lambda b: len(b["priorities"]["coverage"]["not_established"])),
    ("PoB recalculations", lambda b: b["pob_recalcs"]),
    ("builds where all signals NO_SIGNAL", lambda b: b["priorities"]["coverage"]["signals_considered"] == 0),
):
    print(f"- {label}: {total(before, f)} → {total(after, f)}")
print("- profile checks:", [(n, a.get("profile_identical")) for n, a in after.items() if "profile_identical" in a])
