"""Native ground-base registry: refresh the evidence (network) and rebuild / verify the registry (offline).

    python scripts/filter_native_registry.py fetch --cache <dir>   # PoE2DB item-class listings + item pages -> data/poe2_native_base_evidence.json
    python scripts/filter_native_registry.py build                 # evidence + pinned PoB2 catalog -> data/poe2_native_ground_bases.json
    python scripts/filter_native_registry.py check                 # exit 1 when the committed registry differs from a rebuild

`fetch` is the only step that touches the network; `build` and `check` are deterministic and offline. See
docs/FILTER-PROD-01.md for the evidence hierarchy.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

DATA = ROOT / "src" / "exilelens" / "filters" / "data"
BASE_URL = "https://poe2db.tw/us/"
CLASS_PAGES = ("Amulets", "Belts", "Body_Armours", "Boots", "Bows", "Bucklers", "Charms", "Claws", "Crossbows", "Daggers", "Flails", "Flasks",
               "Foci", "Gloves", "Helmets", "Jewels", "One_Hand_Axes", "One_Hand_Maces", "One_Hand_Swords", "Quarterstaves", "Quivers", "Rings",
               "Sceptres", "Shields", "Spears", "Staves", "Talismans", "Traps", "Two_Hand_Axes", "Two_Hand_Maces", "Two_Hand_Swords", "Wands",
               "Life_Flasks", "Mana_Flasks", "Stackable_Currency", "Abyss", "Essence", "Incubators")
_ANCHOR = re.compile(r'class="whiteitem[^"]*"[^>]*href="([^"]+)">([^<]+)<')
# currency-like pages do not use the equipment anchor class; their item anchors are matched by text against the item pages instead
_GENERIC_ANCHOR = re.compile(r'<a[^>]*Poe_Data_BaseItemTypes_hover[^>]*href="([^"#?/][^"]*)"[^>]*>(?:<img[^>]*>)?([^<]+)</a>')
_CURRENCY_PAGES = ("Stackable_Currency", "Abyss", "Essence", "Incubators")


def _curl(url: str, target: Path) -> None:
    for _ in range(3):
        subprocess.run(["curl", "-s", "-m", "60", "-A", "Mozilla/5.0", "-o", str(target), url], check=False)
        if target.exists() and target.stat().st_size > 300:
            return


def _page_text(path: Path) -> str:
    raw = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    raw = re.sub(r"<script.*?</script>|<style.*?</style>", "", raw, flags=re.S)
    text = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "|", raw)))
    return re.sub(r"\|[\s|]*\|", "|", text)


def _item_record(text: str, name: str) -> dict | None:
    """The BaseItemTypes block(s) of an item page for exactly `name` (a page may carry several variants of the same base name)."""
    records = []
    for block in re.split(r"(?=\|Name\|Show Full)", text):
        match = re.search(r"\|BaseType \|([^|]+)\|", block)
        if not match or match.group(1).strip() != name:
            continue

        def field(key: str, block: str = block) -> str | None:
            found = re.search(r"\|" + key + r" ?\|([^|]+)\|", block)
            return found.group(1).strip() if found else None

        records.append({"class": field("Class"), "drop_level": int(field("DropLevel") or 0), "acquisition": field("Acquisition"),
                        "tags": [t.strip() for t in (field("Tags") or "").split(",") if t.strip()], "generation_type": field("GenerationType")})
    if not records:
        return None
    unique = [r for i, r in enumerate(records) if r not in records[:i]]
    return {**unique[0], **({"variants": unique} if len(unique) > 1 else {})}


def fetch(cache: Path, retrieved: str, extra_names: list[str]) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    listing: dict[str, list[str]] = {}
    slugs: dict[str, str] = {}
    for page in CLASS_PAGES:
        target = cache / f"class_{page}.html"
        if not target.exists() or target.stat().st_size < 1000:
            _curl(BASE_URL + page, target)
        text = target.read_text(encoding="utf-8", errors="replace")
        pattern = _GENERIC_ANCHOR if page in _CURRENCY_PAGES else _ANCHOR
        found = [(html.unescape(n).strip(), href) for href, n in pattern.findall(text)]
        listing[page] = sorted({n for n, _ in found})
        for name, href in found:
            slugs.setdefault(name, href)
    names = sorted(set(slugs) | set(extra_names))
    for name in names:
        slugs.setdefault(name, name.replace(" ", "_"))

    def get(name: str) -> None:
        target = cache / (re.sub(r"[^A-Za-z0-9]+", "_", name) + ".html")
        if not target.exists() or target.stat().st_size < 300:
            _curl(BASE_URL + slugs[name], target)

    with ThreadPoolExecutor(8) as pool:
        list(pool.map(get, names))
    listed = {n for v in listing.values() for n in v}
    items: dict[str, dict] = {}
    for name in names:
        target = cache / (re.sub(r"[^A-Za-z0-9]+", "_", name) + ".html")
        record = _item_record(_page_text(target), name)
        items[name] = {"slug": slugs[name], "listed": name in listed,
                       "listed_in": sorted(p for p, v in listing.items() if name in v), **(record or {"page": "absent"})}
    evidence = {"source": BASE_URL, "retrieved": retrieved, "kind": "PoE2DB item-class listings + item pages (game BaseItemTypes)",
                "class_pages": list(CLASS_PAGES), "items": items}
    (DATA / "poe2_native_base_evidence.json").write_text(json.dumps(evidence, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"evidence: {len(items)} names, {sum(1 for v in items.values() if v.get('page') == 'absent')} absent")


def build() -> dict:
    from exilelens.filters import native_bases as nb
    from exilelens.filters.verified_bases import raw_special_names
    pob = json.loads((DATA / "poe2_bases.json").read_text(encoding="utf-8"))
    catalog = json.loads((DATA / "poe2_item_catalog.json").read_text(encoding="utf-8"))["bases"]
    evidence = json.loads((DATA / "poe2_native_base_evidence.json").read_text(encoding="utf-8"))
    return nb.build_registry(pob["bases"], {n: r.get("tags", []) for n, r in catalog.items()}, sorted(set(raw_special_names()) | set(nb.HISTORICAL_SPECIAL_NAMES)), evidence,
                             {k: pob[k] for k in ("pob_version", "pob_commit", "source")})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--cache", required=True)
    f.add_argument("--retrieved", required=True)
    sub.add_parser("build")
    sub.add_parser("check")
    args = parser.parse_args()
    if args.cmd == "fetch":
        from exilelens.filters.verified_bases import raw_special_names
        pob = json.loads((DATA / "poe2_bases.json").read_text(encoding="utf-8"))["bases"]
        from exilelens.filters import native_bases as nb
        extra = sorted(set(pob) | set(raw_special_names()) | set(nb.HISTORICAL_SPECIAL_NAMES) | set(nb.NON_GROUND) | {e for e, _ in nb.POB_SYNTHETIC.values()})
        fetch(Path(args.cache), args.retrieved, extra)
        return 0
    registry = build()
    text = json.dumps(registry, indent=1, ensure_ascii=False) + "\n"
    target = DATA / "poe2_native_ground_bases.json"
    if args.cmd == "build":
        target.write_text(text, encoding="utf-8")
        from collections import Counter
        print(Counter(e["status"] for e in registry["entries"].values()))
        return 0
    same = target.exists() and target.read_text(encoding="utf-8") == text
    print("registry is up to date" if same else "registry differs from a rebuild of the committed evidence")
    return 0 if same else 1


if __name__ == "__main__":
    raise SystemExit(main())
