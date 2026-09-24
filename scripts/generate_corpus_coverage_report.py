"""Generate the M1.1 Corpus Coverage Matrix/Report.

Runs the existing targeted corpus/regression suites (build_corpus, real_pob, the
CORE-04 adversarial policy unit tests), grades each known coverage case in
`tests/corpus_coverage/registry.py` against the result, and writes:

  docs/corpus_coverage/COVERAGE_REPORT.md   (human-readable, generated — do not hand-edit)
  docs/corpus_coverage/coverage_report.json (machine-readable, same data)

Usage:
    python scripts/generate_corpus_coverage_report.py
    python scripts/generate_corpus_coverage_report.py --skip-engine
        (grades only the engine-free policy-unit suite; build_corpus/real_pob cases
        report as NOT_RUN — use when no local PoB2 install is available)

Requires a local PoB2 install (via POB2_PATH or auto-detection) for the build_corpus
and real_pob suites, same as running them directly with pytest -m build_corpus /
pytest -m real_pob. See docs/BUILD_CORPUS_SOURCES.md.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.corpus_coverage.junit import JUnitOutcome, read_junit_outcomes  # noqa: E402
from tests.corpus_coverage.report import build_report, render_markdown, to_json_dict  # noqa: E402

SUITES: tuple[tuple[str, str], ...] = (
    ("tests/integration/test_public_build_corpus.py", "build_corpus"),
    ("tests/integration/test_public_real_pob.py", "real_pob"),
    ("tests/integration/test_weapon_set_component_contexts.py", "real_pob"),
    ("tests/integration/test_contextual_incompatible_placement_real_pob.py", "real_pob"),
    ("tests/integration/test_contextual_diagnostic_real_pob.py", "real_pob"),
    ("tests/integration/test_effect_level_enumeration.py", "real_pob"),
    ("tests/test_core_04_adversarial_item_check.py", "itemcheck"),
)


def _run_suite(test_file: str, marker: str, junit_path: Path) -> None:
    subprocess.run(
        [sys.executable, "-m", "pytest", test_file, "-m", marker, f"--junitxml={junit_path}", "-q"],
        cwd=ROOT,
        check=False,
    )


def collect_outcomes(*, skip_engine: bool) -> list[JUnitOutcome]:
    outcomes: list[JUnitOutcome] = []
    with tempfile.TemporaryDirectory() as tmp:
        for index, (test_file, marker) in enumerate(SUITES):
            if skip_engine and marker in ("build_corpus", "real_pob"):
                continue
            junit_path = Path(tmp) / f"junit_{index}.xml"
            _run_suite(test_file, marker, junit_path)
            if junit_path.exists():
                outcomes.extend(read_junit_outcomes(junit_path))
    return outcomes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-engine",
        action="store_true",
        help="Skip build_corpus/real_pob suites (no local PoB2 install available).",
    )
    args = parser.parse_args()

    outcomes = collect_outcomes(skip_engine=args.skip_engine)
    report = build_report(outcomes)

    out_dir = ROOT / "docs" / "corpus_coverage"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "COVERAGE_REPORT.md").write_text(render_markdown(report), encoding="utf-8")

    import json

    (out_dir / "coverage_report.json").write_text(
        json.dumps(to_json_dict(report), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print(f"Wrote {out_dir / 'COVERAGE_REPORT.md'}")
    print(f"Wrote {out_dir / 'coverage_report.json'}")
    print(f"Supported: {report.supported_count}/{report.total_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
