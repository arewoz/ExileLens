"""Reproducible PoB2 -> FILTER data snapshot (FILTER-08D).

One pass over a pinned PoB2 checkout produces every verified dataset the filter layer reads, validates the relationships between
them, writes a version manifest and reports the difference against the datasets currently checked in. Nothing is accepted
automatically: ``build()`` returns data, ``diff()`` classifies the change, and only an explicit ``accept()`` replaces files.

Datasets (all normalised, all derived from GGG-generated PoB2 data, never from memory):
  poe2_bases.json            base name -> PoB class
  poe2_base_properties.json  class, implicit, required level, intrinsic defences
  poe2_item_catalog.json     tags, handedness-bearing tags, sub type, quality, socket limit, attribute requirements, weapon stats
  poe2_affix_pools.json      per tag-signature modifier-family eligibility with tier item levels
  poe2_skill_facts.json      skill types and weapon requirements
  poe2_data_manifest.json    versions, hashes, counts, validation results
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Mapping
from xml.etree import ElementTree

from exilelens.filters._family_patterns import FAMILIES, normalise

SCHEMA_VERSION = 1
DATA_DIR = Path(__file__).with_name("data")
FILES = ("poe2_bases.json", "poe2_base_properties.json", "poe2_item_catalog.json", "poe2_affix_pools.json",
         "poe2_skill_facts.json")
MANIFEST = "poe2_data_manifest.json"
SOURCE = "https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2"

_MOD = re.compile(r'^\t\["([^"]+)"\] = \{ type = "(\w+)", affix = "([^"]*)", (.*?), statOrder', re.M)
_LEVEL = re.compile(r"\blevel = (\d+)")
_GROUP = re.compile(r'\bgroup = "([^"]+)"')
_WEIGHT_KEY = re.compile(r"weightKey = \{([^}]*)\}")
_WEIGHT_VAL = re.compile(r"weightVal = \{([^}]*)\}")
_BASE_ENTRY = re.compile(r'itemBases\["([^"\n]+)"\]\s*=\s*\{\s*\n(.*?)^\}', re.M | re.S)
_COMPILED = [(fid, probe, relation, [re.compile(p) for p in patterns]) for fid, probe, relation, patterns in FAMILIES]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# -- parsing --------------------------------------------------------------------------------------------------------------------
def _field(block: str, name: str) -> str:
    match = re.search(rf'^\s*{re.escape(name)} = "([^"\n]*)"', block, re.M)
    return match.group(1) if match else ""


def _table(block: str, name: str) -> str:
    match = re.search(rf'^\s*{re.escape(name)} = \{{([^\n]*)\}}', block, re.M)
    return match.group(1) if match else ""


def _num(raw: str, name: str) -> int:
    match = re.search(rf'\b{re.escape(name)} = (\d+)', raw)
    return int(match.group(1)) if match else 0


def parse_bases(pob_root: Path) -> dict[str, dict[str, Any]]:
    """Every base entry with its full verified record. A name defined twice with different classes is a hard error."""
    bases: dict[str, dict[str, Any]] = {}
    for source in sorted((pob_root / "src" / "Data" / "Bases").glob("*.lua")):
        for name, block in _BASE_ENTRY.findall(source.read_text(encoding="utf-8-sig")):
            item_class = _field(block, "type")
            if not item_class:
                continue
            sub = _field(block, "subType")
            if item_class == "Staff" and sub == "Warstaff":
                item_class = "Quarterstaff"          # same rule as the committed class snapshot
            req, armour = _table(block, "req"), _table(block, "armour")
            tags = sorted(re.findall(r"(\w+) = true", _table(block, "tags")))
            weapon = _table(block, "weapon")
            record = {
                "class": item_class, "sub_type": sub, "tags": tags,
                "implicit": _field(block, "implicit"), "required_level": _num(req, "level"),
                "req_str": _num(req, "str"), "req_dex": _num(req, "dex"), "req_int": _num(req, "int"),
                "armour": _num(armour, "Armour"), "evasion": _num(armour, "Evasion"),
                "energy_shield": _num(armour, "EnergyShield"), "ward": _num(armour, "Ward"),
                "quality": _num(block, "quality"), "socket_limit": _num(block, "socketLimit"),
                "weapon": {k: float(v) for k, v in re.findall(r"(\w+) = (\d+(?:\.\d+)?)", weapon)} if weapon else {},
            }
            previous = bases.get(name)
            if previous is not None and previous["class"] != item_class:
                raise ValueError(f"Conflicting PoB2 classes for {name}: {previous['class']}, {item_class}")
            bases[name] = record
    return bases


def parse_mods(path: Path, kind: str) -> list[dict]:
    data = path.read_text(encoding="utf-8-sig")
    mods = []
    for match in _MOD.finditer(data):
        mod_id, mod_type, _affix, body = match.groups()
        full = data[match.start():data.find("\n", match.start())]
        level, keys, vals = _LEVEL.search(full), _WEIGHT_KEY.search(full), _WEIGHT_VAL.search(full)
        if not (level and keys and vals):
            continue
        group = _GROUP.search(full)
        mods.append({"id": mod_id, "kind": kind, "type": mod_type, "level": int(level.group(1)),
                     "group": group.group(1) if group else mod_id, "keys": re.findall(r'"([^"]+)"', keys.group(1)),
                     "vals": [int(v) for v in re.findall(r"-?\d+", vals.group(1))],
                     "lines": [normalise(t) for t in re.findall(r'"([^"]+)"', body)]})
    return mods


def eligible(mod: dict, tags: set[str]) -> bool:
    """PoB's spawn-weight resolution: the first weight key the base carries decides."""
    for key, value in zip(mod["keys"], mod["vals"]):
        if key in tags or key == "default":
            return value > 0
    return False


def parse_skills(pob_root: Path) -> dict[str, dict]:
    skills = {}
    for source in sorted((pob_root / "src" / "Data" / "Skills").glob("*.lua")):
        data = source.read_text(encoding="utf-8-sig")
        matches = list(re.finditer(r'^skills\["([^"]+)"\] = \{', data, re.M))
        for index, match in enumerate(matches):
            body = data[match.end():matches[index + 1].start() if index + 1 < len(matches) else len(data)]
            name, types = re.search(r'\n\tname = "([^"]+)"', body), re.search(r"\n\tskillTypes = \{([^\n]*)\}", body)
            if not (name and types):
                continue
            weapons = re.search(r"\n\tweaponTypes = \{(.*?)\n\t\}", body, re.S)
            skills[match.group(1)] = {
                "name": name.group(1), "types": sorted(re.findall(r"SkillType\.(\w+)", types.group(1))),
                "weapon_types": sorted(re.findall(r'\["([^"]+)"\]', weapons.group(1))) if weapons else []}
    return skills


def build_pools(pob_root: Path, bases: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    mods = parse_mods(pob_root / "src" / "Data" / "ModItem.lua", "item")
    jewel = pob_root / "src" / "Data" / "ModJewel.lua"
    if jewel.exists():
        mods += parse_mods(jewel, "jewel")
    signatures: dict[str, list[str]] = {}
    base_signature: dict[str, str] = {}
    for name in sorted(bases):
        tags = list(bases[name]["tags"])
        key = ",".join(tags)
        signatures.setdefault(key, tags)
        base_signature[name] = key
    ordered = sorted(signatures)
    ids = {key: f"S{index:03d}" for index, key in enumerate(ordered)}
    pools = {}
    for key in ordered:
        tagset = set(signatures[key])
        families: dict[str, dict] = {}
        for mod in mods:
            if not eligible(mod, tagset):
                continue
            for fid, _probe, _relation, patterns in _COMPILED:
                if any(p.match(line) for line in mod["lines"] for p in patterns):
                    entry = families.setdefault(fid, {"levels": set(), "groups": set(), "kinds": set()})
                    entry["levels"].add(mod["level"]), entry["groups"].add(mod["group"]), entry["kinds"].add(mod["kind"])
        pools[ids[key]] = {"tags": signatures[key], "families": {
            fid: {"levels": sorted(e["levels"]), "groups": len(e["groups"]), "kinds": sorted(e["kinds"])}
            for fid, e in sorted(families.items())}}
    return {"families": {fid: {"probe_id": probe, "relation": relation} for fid, probe, relation, _ in FAMILIES},
            "pools": pools, "base_pool": {name: ids[key] for name, key in base_signature.items()}, "mod_count": len(mods)}


# -- build / validate / diff -------------------------------------------------------------------------------------------------------
def build(pob_root: Path) -> dict[str, Any]:
    """All datasets plus the manifest, in memory. Fails closed on any structural inconsistency."""
    version = ElementTree.parse(pob_root / "manifest.xml").find("Version").attrib["number"]
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=pob_root, text=True).strip()
    bases = parse_bases(pob_root)
    pools = build_pools(pob_root, bases)
    skills = parse_skills(pob_root)
    header = {"source": SOURCE, "pob_version": version, "pob_commit": commit}
    data = {
        "poe2_bases.json": {**header, "source_path": "src/Data/Bases/*.lua (generated from GGG item data)",
                            "bases": {n: r["class"] for n, r in sorted(bases.items())}},
        "poe2_base_properties.json": {**header, "bases": {n: {k: r[k] for k in ("class", "implicit", "required_level", "armour", "evasion", "energy_shield", "ward")}
                                                          for n, r in sorted(bases.items())}},
        "poe2_item_catalog.json": {**header, "schema_version": SCHEMA_VERSION, "bases": dict(sorted(bases.items()))},
        "poe2_affix_pools.json": {**header, "source_path": "src/Data/ModItem.lua, ModJewel.lua, Bases/*.lua",
                                  "semantics": ("A family is eligible on a base when PoB's first-matching weight key gives a positive "
                                                "weight; levels are the required item levels of the eligible tiers. Eligibility is not possession."),
                                  "families": pools["families"], "pools": pools["pools"], "base_pool": pools["base_pool"]},
        "poe2_skill_facts.json": {**header, "source_path": "src/Data/Skills/*.lua", "skills": dict(sorted(skills.items()))},
    }
    problems = validate(data)
    manifest = {"schema_version": SCHEMA_VERSION, "pob_version": version, "pob_commit": commit, "source": SOURCE,
                "game_version_hint": game_version_hint(pob_root),
                "counts": {"bases": len(bases), "classes": len({r["class"] for r in bases.values()}), "pool_signatures": len(pools["pools"]),
                           "mods": pools["mod_count"], "skills": len(skills), "families": len(pools["families"])},
                "validation": {"problems": problems, "passed": not problems}}
    data[MANIFEST] = manifest
    return data


def game_version_hint(pob_root: Path) -> str:
    """Newest PoE2 data generation PoB2 ships a passive tree for (e.g. TreeData/0_5 -> '0.5'). A hint, not a client version."""
    versions = []
    tree = pob_root / "src" / "TreeData"
    for child in tree.iterdir() if tree.exists() else ():
        match = re.fullmatch(r"(\d+)_(\d+)", child.name)
        if match:
            versions.append((int(match.group(1)), int(match.group(2))))
    return ".".join(map(str, max(versions))) if versions else ""


def manifest_for_dir(directory: Path = DATA_DIR, base: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Manifest describing the datasets exactly as checked in (hashes of the real bytes)."""
    manifest = dict(base or json.loads((directory / MANIFEST).read_text(encoding="utf-8")))
    manifest["files"] = {name: {"sha256": sha256_file(directory / name), "bytes": (directory / name).stat().st_size} for name in FILES}
    return manifest


def validate(data: Mapping[str, Any]) -> list[str]:
    """Internal relationships between the datasets. Empty list = consistent."""
    problems: list[str] = []
    bases = data["poe2_bases.json"]["bases"]
    props = data["poe2_base_properties.json"]["bases"]
    catalog = data["poe2_item_catalog.json"]["bases"]
    pools = data["poe2_affix_pools.json"]
    if len(bases) < 1000:
        problems.append(f"unexpectedly small base catalog: {len(bases)}")
    if set(bases) != set(props) or set(bases) != set(catalog) or set(bases) != set(pools["base_pool"]):
        problems.append("base name sets differ between bases / properties / catalog / pools")
    for name, record in props.items():
        if record["class"] != bases.get(name) or record["class"] != catalog.get(name, {}).get("class"):
            problems.append(f"class mismatch for {name}")
        if not isinstance(record["required_level"], int) or record["required_level"] < 0:
            problems.append(f"bad required level for {name}")
    for name, sig in pools["base_pool"].items():
        if sig not in pools["pools"]:
            problems.append(f"{name}: unknown pool signature {sig}")
            continue
        if sorted(pools["pools"][sig]["tags"]) != sorted(catalog[name]["tags"]):
            problems.append(f"{name}: pool tags differ from catalog tags")
    from exilelens.analysis.catalog import ProbeCatalog
    probe_ids = {d.probe_id for d in ProbeCatalog().all()}
    for family, definition in pools["families"].items():
        if definition["probe_id"] not in probe_ids:
            problems.append(f"family {family}: probe {definition['probe_id']} is not in the production probe catalog")
    skills = data["poe2_skill_facts.json"]["skills"]
    if len(skills) < 300:
        problems.append(f"unexpectedly small skill table: {len(skills)}")
    heads = {data[name]["pob_commit"] for name in FILES if name in data}
    if len(heads) != 1:
        problems.append(f"datasets disagree on the PoB2 commit: {sorted(heads)}")
    return problems


def diff(new: Mapping[str, Any], current_dir: Path = DATA_DIR) -> dict[str, list]:
    """Classify the change against the checked-in datasets. Breaking categories are never auto-accepted."""
    def load(name: str) -> dict:
        path = current_dir / name
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    old_props = load("poe2_base_properties.json").get("bases", {})
    new_props = new["poe2_base_properties.json"]["bases"]
    old_pool, new_pool = load("poe2_affix_pools.json"), new["poe2_affix_pools.json"]
    report: dict[str, list] = {k: [] for k in ("ADDED", "REMOVED", "RENAMED", "CLASS CHANGED", "MOD POOL CHANGED", "REQUIREMENT CHANGED",
                                               "CRAFT SUBSTRATE CHANGED", "UNKNOWN")}
    added, removed = sorted(set(new_props) - set(old_props)), sorted(set(old_props) - set(new_props))

    def fingerprint(record: Mapping) -> tuple:
        return (record["class"], record["required_level"], record["armour"], record["evasion"], record["energy_shield"], record["implicit"])
    gone = {fingerprint(old_props[n]): n for n in removed}
    for name in added:
        match = gone.pop(fingerprint(new_props[name]), None)
        if match:
            report["RENAMED"].append({"from": match, "to": name})
        else:
            report["ADDED"].append(name)
    renamed_from = {r["from"] for r in report["RENAMED"]}
    report["REMOVED"] = [n for n in removed if n not in renamed_from]
    for name in sorted(set(old_props) & set(new_props)):
        o, n = old_props[name], new_props[name]
        if o["class"] != n["class"]:
            report["CLASS CHANGED"].append({"base": name, "from": o["class"], "to": n["class"]})
        if (o["required_level"], o["armour"], o["evasion"], o["energy_shield"]) != (n["required_level"], n["armour"], n["evasion"], n["energy_shield"]):
            report["REQUIREMENT CHANGED"].append({"base": name, "from": [o["required_level"], o["armour"], o["evasion"], o["energy_shield"]],
                                                  "to": [n["required_level"], n["armour"], n["evasion"], n["energy_shield"]]})
        if o["implicit"] != n["implicit"]:
            # FILTER-09: the CRAFT lane classifies the implicit, so a text change that moves the classification is a reviewed change
            from exilelens.filters.crafting_intel import classify_implicit
            before, after = classify_implicit(o["implicit"]).value, classify_implicit(n["implicit"]).value
            if before != after:
                report["CRAFT SUBSTRATE CHANGED"].append({"base": name, "change": "implicit classification", "from": before, "to": after})
            else:
                report["UNKNOWN"].append({"base": name, "change": "implicit text", "from": o["implicit"], "to": n["implicit"]})
    if old_pool:
        for name in sorted(set(old_pool.get("base_pool", {})) & set(new_pool["base_pool"])):
            a = old_pool["pools"][old_pool["base_pool"][name]]["families"]
            b = new_pool["pools"][new_pool["base_pool"][name]]["families"]
            if a != b:
                report["MOD POOL CHANGED"].append({"base": name, "families_changed": sorted({k for k in {*a, *b} if a.get(k) != b.get(k)})})
    old_skills, new_skills = load("poe2_skill_facts.json").get("skills", {}), new["poe2_skill_facts.json"]["skills"]
    for sid in sorted(set(old_skills) & set(new_skills)):
        if old_skills[sid]["weapon_types"] != new_skills[sid]["weapon_types"]:
            report["UNKNOWN"].append({"skill": sid, "change": "weapon requirement", "from": old_skills[sid]["weapon_types"],
                                      "to": new_skills[sid]["weapon_types"]})
    for sid in sorted(set(old_skills) ^ set(new_skills)):
        report["UNKNOWN"].append({"skill": sid, "change": "skill added" if sid in new_skills else "skill removed"})
    return report


def breaking(report: Mapping[str, list]) -> bool:
    """Changes that can invalidate generated rules and therefore must be reviewed, never auto-accepted."""
    return any(report[k] for k in ("REMOVED", "RENAMED", "CLASS CHANGED", "MOD POOL CHANGED", "REQUIREMENT CHANGED", "CRAFT SUBSTRATE CHANGED"))


def write(data: Mapping[str, Any], out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    manifest = dict(data[MANIFEST])
    manifest["files"] = {}
    for name in FILES:
        path = out / name
        path.write_text(json.dumps(data[name], ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        manifest["files"][name] = {"sha256": sha256_file(path), "bytes": path.stat().st_size}
    (out / MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def accept(source: Path, destination: Path = DATA_DIR) -> None:
    """Explicit acceptance: copy a reviewed snapshot over the checked-in data."""
    for name in (*FILES, MANIFEST):
        (destination / name).write_bytes((source / name).read_bytes())
