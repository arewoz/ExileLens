"""Generate the M1.1 Corpus Coverage Matrix/Report (and, since R4, evaluate the 1.0 reliability gate).

Runs the existing targeted corpus/regression suites (build_corpus, real_pob, the
CORE-04 adversarial policy unit tests), grades each known coverage case in
`tests/corpus_coverage/registry.py` against the result, and writes:

  docs/corpus_coverage/COVERAGE_REPORT.md   (human-readable, generated — do not hand-edit)
  docs/corpus_coverage/coverage_report.json (machine-readable, same data)

Usage:
    python scripts/generate_corpus_coverage_report.py
    python scripts/generate_corpus_coverage_report.py --check-gate
        (also exit non-zero when the R4 coverage gate blocks; use in release verification)
    python scripts/generate_corpus_coverage_report.py --skip-engine
        (grades only the engine-free policy-unit suite; build_corpus/real_pob cases
        report as NOT_RUN and the gate is not evaluable — use when no local PoB2 install is available)

Requires a local PoB2 install (via POB2_PATH or auto-detection) for the build_corpus
and real_pob suites, same as running them directly with pytest -m build_corpus /
pytest -m real_pob. See docs/BUILD_CORPUS_SOURCES.md. The report records which PoB runtime it was measured on: the
installed PoB Community PoE2 release (what users run) and a development git checkout of the same head can produce
slightly different numbers, and the committed report is the installed-release one (leave POB2_PATH unset).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from tests.corpus_coverage.gate import evaluate_gate, render_gate  # noqa: E402
from tests.corpus_coverage.junit import JUnitOutcome, read_junit_outcomes  # noqa: E402
from tests.corpus_coverage.report import build_report, render_markdown, to_json_dict  # noqa: E402

SUITES: tuple[tuple[str, str], ...] = (
    ("tests/integration/test_public_build_corpus.py", "build_corpus"),
    ("tests/integration/test_public_real_pob.py", "real_pob"),
    ("tests/integration/test_weapon_set_component_contexts.py", "real_pob"),
    ("tests/integration/test_contextual_incompatible_placement_real_pob.py", "real_pob"),
    ("tests/integration/test_contextual_diagnostic_real_pob.py", "real_pob"),
    ("tests/integration/test_effect_level_enumeration.py", "real_pob"),
    ("tests/integration/test_corpus02_giants_blood_shield.py", "real_pob"),
    ("tests/integration/test_corpus02b_minion_djinn.py", "real_pob"),
    ("tests/integration/test_corpus02c_stonefist.py", "real_pob"),
    ("tests/integration/test_corpus02d1_poison_ailment.py", "real_pob"),
    ("tests/integration/test_corpus02d2_voltaic_barrier.py", "real_pob"),
    ("tests/integration/test_main_skill_01_real_pob.py", "real_pob"),
    ("tests/integration/test_corpus02e_spell_totem.py", "real_pob"),
    ("tests/integration/test_corpus02f_mortar_ballista.py", "real_pob"),
    ("tests/integration/test_corpus02g_attribute_stacking.py", "real_pob"),
    ("tests/integration/test_corpus02h_energy_shield_mana.py", "real_pob"),
    # R4: real-PoB suites that existed but were never part of the report (LIFE-01 was registered yet always NOT_RUN).
    ("tests/integration/test_life01_blood_mage.py", "real_pob"),
    ("tests/integration/test_recovery02a_es_regen.py", "real_pob"),
    ("tests/integration/test_jewel_real_pob.py", "real_pob"),
    ("tests/integration/test_jewel_restore_remediation.py", "real_pob"),
    ("tests/integration/test_trust01a_equipability_real_pob.py", "real_pob"),
    ("tests/integration/test_item_check_socket_normalization.py", "real_pob"),
    ("tests/integration/test_m5_1_build_fingerprint_real_pob.py", "real_pob"),
    ("tests/integration/test_m5_2_sensitivity_real_pob.py", "real_pob"),
    ("tests/integration/test_r4_reliability_gate.py", "real_pob"),
    ("tests/test_core_04_adversarial_item_check.py", "itemcheck"),
    ("tests/test_item_transform_guard.py", "itemcheck"),
    ("tests/test_stonefist_transform.py", "itemcheck"),
    ("tests/test_corpus02d1_ailment_intel.py", "itemcheck"),
    ("tests/test_main_skill_diagnostics.py", "itemcheck"),
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


def pob_runtime() -> dict[str, str]:
    """The PoB runtime the engine suites run against (version and layout only; never a path)."""
    from exilelens.config import PobConfig, detect_common_pob_installation, detect_pob_identity

    explicit = os.environ.get("POB2_PATH", "").strip()
    path = Path(explicit).expanduser().resolve() if explicit else detect_common_pob_installation()
    if path is None:
        return {}
    config = PobConfig(path)
    try:
        version = detect_pob_identity(path).version
    except Exception:  # noqa: BLE001 - identity is descriptive; never block the report on it
        version = "unknown"
    return {"pob_version": str(version or "unknown"), "pob_layout": str(getattr(config, "layout", "") or "unknown")}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--skip-engine",
        action="store_true",
        help="Skip build_corpus/real_pob suites (no local PoB2 install available).",
    )
    parser.add_argument(
        "--check-gate",
        action="store_true",
        help="Exit non-zero when the R4 coverage gate does not pass.",
    )
    args = parser.parse_args()

    outcomes = collect_outcomes(skip_engine=args.skip_engine)
    runtime = {} if args.skip_engine else pob_runtime()
    report = build_report(outcomes, runtime=runtime)
    gate = evaluate_gate(report)
    gate_text = render_gate(gate)

    out_dir = ROOT / "docs" / "corpus_coverage"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "COVERAGE_REPORT.md").write_text(render_markdown(report, gate_text), encoding="utf-8")

    import json

    (out_dir / "coverage_report.json").write_text(
        json.dumps({**to_json_dict(report), "gate": {"verdict": gate.verdict, "blockers": [c.name for c in gate.blockers]}},
                   indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print(f"Wrote {out_dir / 'COVERAGE_REPORT.md'}")
    print(f"Wrote {out_dir / 'coverage_report.json'}")
    print(f"Supported: {report.supported_count}/{report.total_count}")
    print(gate_text)
    if args.check_gate and not gate.passed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
