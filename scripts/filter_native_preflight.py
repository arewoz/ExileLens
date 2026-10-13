"""Exhaustive native BaseType preflight: 5 profiles x builds x 8 themes, one union, validated once.

    python scripts/filter_native_preflight.py [--out artifacts/filter_native_basetype] [--workers 8]
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(ROOT / "artifacts" / "filter_native_basetype"))
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    from exilelens.filters import native_bases as nb
    from exilelens.filters import native_preflight as pf
    from exilelens.filters import profile_policy as pp
    from exilelens.filters import profile_report as pr
    from exilelens.filters.profiles import FilterThemeName
    builds = pr.load_builds(ROOT)
    jobs = [(key, needs, level, theme.value) for key, needs in builds.items() for level in pp.LEVELS for theme in FilterThemeName]
    with ProcessPoolExecutor(args.workers) as pool:
        results = list(pool.map(pf.collect_job, jobs))
    report = pf.evaluate(results)
    report["registry"] = nb.summary()
    report["registry_audit"] = pf.registry_audit()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    names = report.pop("emitted_names")
    (out / "emitted_base_types.txt").write_text(chr(10).join(names) + chr(10), encoding="utf-8")
    (out / "preflight.json").write_text(json.dumps(report, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in ("rejected", "registry", "registry_audit")}, indent=1, ensure_ascii=False))
    return 0 if report["all_emitted_ground_valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
