"""Build an exact offline PoE2 acceptance package; never install or claim native acceptance."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


def main():
    from exilelens.filters.build_needs import BuildNeedsSnapshot
    from exilelens.filters.intel_generate import generate, filter_body_sha256
    from exilelens.filters.profiles import FilterProfileName, FilterThemeName
    from exilelens.filters.native_preflight import evaluate, collect_job, registry_audit
    from exilelens.filters.style_coverage import has_required_style
    from exilelens.filters.serialize import FilterMetadata, FilterSerializer
    from exilelens.filters.rules import GeneratedRule
    from exilelens.filters.native_bases import load_registry
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / '.run/native-acceptance')
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    builds = {'general': BuildNeedsSnapshot.unavailable('General', 'no build connected'),
              'synthetic_spark': BuildNeedsSnapshot.from_json((ROOT / 'tests/fixtures/filter_needs/filter08c/spark_fixture.json').read_text(encoding='utf-8'))}
    manifest = {'schema_version': 1, 'native_client_acceptance': 'UNVERIFIED', 'installed': False, 'filters': []}
    jobs = []
    for mode, needs in builds.items():
        for profile in FilterProfileName:
            for theme in FilterThemeName:
                result = generate(needs, profile, theme)
                if not result.valid:
                    raise ValueError(result.errors)
                assert all(has_required_style(r) for r in result.rules if 'Show' in [line.strip() for line in r.lines])
                filename = f'ExileLens_{profile.value}_{theme.value}_{mode}.filter'.replace(' ', '_')
                raw = result.text.encode('utf-8')
                (args.out / filename).write_bytes(raw)
                manifest['filters'].append({'file': filename, 'mode': mode, 'profile': profile.value, 'theme': theme.value,
                                            'sha256': hashlib.sha256(raw).hexdigest(), 'rules_sha256': filter_body_sha256(result.text),
                                            'static_validation': 'PASS', 'native_load': 'UNVERIFIED', 'native_gameplay': 'UNVERIFIED'})
                jobs.append(collect_job((mode, needs, profile.value, theme.value)))
    preflight = evaluate(jobs)
    preflight['registry_audit'] = registry_audit()
    assert preflight['all_emitted_ground_valid']
    (args.out / 'preflight.json').write_text(json.dumps(preflight, indent=2) + '\n', encoding='utf-8')
    # A single exhaustive parser check for every evidence-backed ground name and class.
    registry = load_registry()
    grouped = {}
    for name, entry in registry.items():
        if entry.ground_valid:
            grouped.setdefault(entry.native_class, []).append(name)
    rules = []
    for cls, names in sorted(grouped.items()):
        body = ['Show', f'\tClass "{cls}"', '\tBaseType == ' + ' '.join('"' + name + '"' for name in sorted(names)),
                '\tSetFontSize 30', '\tSetTextColor 230 230 230', '\tSetBorderColor 100 100 100', '\tSetBackgroundColor 20 20 20']
        rules.append(GeneratedRule('ACCEPTANCE', cls, body, 0))
    # Native parser check file intentionally uses restrained styling; not intended for normal play.
    exhaustive = '\n\n'.join('\n'.join(r.lines) for r in rules) + '\n'
    (args.out / 'MUST_LOAD_ALL_GROUND_BASES.filter').write_text(exhaustive, encoding='utf-8')
    manifest['exhaustive_parser_check'] = {'file': 'MUST_LOAD_ALL_GROUND_BASES.filter', 'names': sum(map(len, grouped.values())),
                                          'sha256': hashlib.sha256(exhaustive.encode()).hexdigest(), 'native_load': 'UNVERIFIED'}
    (args.out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    (args.out / 'MANUAL_ACCEPTANCE.md').write_text('''# Native PoE2 acceptance — UNVERIFIED

This package was generated from the production integration code. Static checks passed; no native acceptance is implied.
Record the integration commit, client version, date, tested filenames and their manifest SHA-256 values.

1. Copy MUST_LOAD_ALL_GROUND_BASES.filter to your PoE2 filter folder and select it in the client. Record whether it loads without errors. In particular, no synthetic Energy Blade names are present.
2. Load each of the 80 generated profile/theme/mode files. A successful load proves parser acceptance for those exact bytes, not gameplay quality.
3. Play with Recommended/general and Recommended/synthetic_spark, then Relaxed, Strict, Very Strict and Uber Strict. The synthetic build checks filter bytes only; use your current build through the app for actual personalization acceptance.
4. Check Rare unidentified tier-2 body armour and several weapon/armour classes in campaign and maps. Visible known equipment must carry a theme frame and background. Hidden items must follow the profile. Unknown items have a separate safety treatment. Do not treat a single Soldier Cuirass observation as complete coverage.
5. Compare all eight themes on a dense floor, including long names and light ground. Confirm hero plaque/red text, restrained ordinary equipment, quiet lower tiers and Unique safety.
6. Confirm Mythic and Divine-tier beams persist while drops remain on the ground. Confirm ordinary equipment has no jackpot sound or beam. Confirm sounds/icons/beams decrease with stricter profiles.
7. Generate & Install from the application with no connected PoB build, then with a current analysis. Check installation, select/refresh the file in PoE2 yourself and record that action. App verification alone never proves a game reload.
8. Report suspicious decisions with base, class, rarity, item level, area level, profile/theme, connected build state and the first matching rule from the preview tooltip. Share rule/file hashes; omit private build exports and local paths.

Result: UNVERIFIED. Add real observations, client load errors and screenshots before changing this result. All merge gates, including protected GitHub checks, must pass before merge.
''', encoding='utf-8')
    print(json.dumps({'files': len(manifest['filters']), 'static_preflight': 'PASS', 'native_client_acceptance': 'UNVERIFIED'}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
