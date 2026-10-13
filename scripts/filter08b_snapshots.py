"""Measure builds with PRODUCTION Build Intelligence and store filter-oriented needs snapshots (FILTER-08B).

Usage (needs a local PoB2 checkout; this is the only step that touches PoB):
  python scripts/filter08b_snapshots.py --pob2 <pob2-directory> --out <needs-directory>
      --build path/a.xml --build path/b.xml ...

Each build is analysed with ``exilelens.analysis.pipeline.analyze_build`` (the same call the product uses),
then projected by ``BuildNeedsSnapshot.from_analysis``. Snapshots contain measurements, a skill id, observed
gear base names and observed defence totals: no build XML, no absolute paths and no personal data.
Generation and benchmarks then run OFFLINE from these files.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from exilelens.analysis.pipeline import analyze_build  # noqa: E402
from exilelens.config import PobConfig  # noqa: E402
from exilelens.engine import Engine  # noqa: E402
from exilelens.filters.build_needs import BuildNeedsSnapshot  # noqa: E402
from exilelens.filters.fingerprint import BuildFingerprintExtractor  # noqa: E402
from exilelens.filters.probe_policy import FilterProbeCatalog  # noqa: E402


def snapshot_one(engine: Engine, path: Path) -> tuple[BuildNeedsSnapshot, dict]:
    started = time.perf_counter()
    result = analyze_build(engine, build_path=str(path), context="MAP", catalog=FilterProbeCatalog())
    fingerprint = BuildFingerprintExtractor(engine).extract(context="MAP", build_path=str(path))
    equipped = {slot.value: item.base_type for slot, item in fingerprint.equipped.items() if item.base_type}
    needs = BuildNeedsSnapshot.from_analysis(result, label=path.stem, equipped=equipped)
    meta = {"class": fingerprint.class_name, "ascendancy": fingerprint.ascendancy,
            "seconds": round(time.perf_counter() - started, 1)}
    return needs, meta


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pob2", type=Path, required=True)
    parser.add_argument("--build", type=Path, action="append", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--force", action="store_true", help="re-measure builds that already have a snapshot")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    failures = 0
    with Engine(PobConfig(args.pob2), use_subprocess=True) as engine:
        for path in args.build:
            target = args.out / f"{path.stem}.json"
            if target.exists() and not args.force:
                print(f"skip {path.stem} (snapshot exists)")
                continue
            try:
                needs, meta = snapshot_one(engine, path)
            except Exception as exc:  # one failing build must not hide the others
                failures += 1
                (args.out / f"{path.stem}.error.json").write_text(
                    json.dumps({"build": path.stem, "error": f"{type(exc).__name__}: {exc}"}, indent=1) + "\n", encoding="utf-8")
                print(f"FAIL {path.stem}: {type(exc).__name__}: {exc}")
                continue
            payload = needs.to_dict()
            payload["meta"] = meta
            target.write_text(json.dumps(payload, indent=1, sort_keys=True, default=list) + "\n", encoding="utf-8")
            print(f"ok   {path.stem}: {needs.coverage.value}, {sum(s.status == 'MEASURED' for s in needs.signals)} measured, {meta['seconds']}s")
    return int(failures > 0)


if __name__ == "__main__":
    raise SystemExit(main())
