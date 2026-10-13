"""CLI for FILTER-01 experimental filter generation.

Usage:
    python -m exilelens.filters.cli --build path/to/build.xml --profile Recommended --output filter.filter
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from datetime import datetime

from exilelens.engine import Engine
from exilelens.config import load_config
from exilelens.filters.fingerprint import BuildFingerprintExtractor
from exilelens.filters.priorities import SlotPriorityResolver
from exilelens.filters.rules import RuleGenerator
from exilelens.filters.serialize import FilterSerializer, create_metadata_from_fingerprint
from exilelens.filters.profiles import FilterProfile, FilterProfileName, FilterThemeName, get_profile, get_profile_with_theme, get_all_themes
from exilelens.filters.validation import validate_all


def main() -> int:
    parser = argparse.ArgumentParser(
        description="ExileLens FILTER-01: Build-Aware Loot Filter Generator (Experimental)"
    )
    parser.add_argument(
        "--build",
        required=True,
        help="Path to PoB2 build XML file",
    )
    parser.add_argument(
        "--profile",
        choices=[p.value for p in FilterProfileName],
        default="Recommended",
        help="Filter profile: Relaxed, Recommended, or Strict",
    )
    parser.add_argument(
        "--theme",
        choices=[t.value for t in FilterThemeName],
        default="Void Gold",
        help="Visual theme: Void Gold, Blood Sigil, or Arcane Prism",
    )
    parser.add_argument(
        "--output",
        "-o",
        required=True,
        help="Output .filter file path",
    )
    parser.add_argument(
        "--context",
        choices=["MAP", "BOSS"],
        default="MAP",
        help="PoB evaluation context",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Compatibility flag; validation always runs before output",
    )
    parser.add_argument(
        "--check-determinism",
        action="store_true",
        help="Generate twice and verify identical output",
    )
    parser.add_argument(
        "--analyze",
        action="store_true",
        help="FILTER-08B: measure the build with production Build Intelligence (slow, uses PoB) and generate build-aware rules",
    )
    parser.add_argument(
        "--needs",
        help="FILTER-08B: build-aware generation from a stored needs snapshot (offline measurement replay)",
    )
    parser.add_argument(
        "--save-needs",
        help="FILTER-08B: with --analyze, also write the measured needs snapshot to this JSON path",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output",
    )

    args = parser.parse_args()

    # Validate inputs
    build_path = Path(args.build)
    if not build_path.exists():
        print(f"Error: Build file not found: {build_path}", file=sys.stderr)
        return 1

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    profile = get_profile_with_theme(args.profile, args.theme)

    if args.verbose:
        print(f"Loading build: {build_path}")
        print(f"Profile: {profile.name.value}")
        print(f"Theme: {profile.theme.value}")
        print(f"Context: {args.context}")
        print(f"Output: {output_path}")

    # Initialize engine
    config = load_config()
    engine = Engine(config)

    try:
        # Load build
        if args.verbose:
            print("Loading build into PoB...")
        engine.load_build(str(build_path), context=args.context)

        # Extract fingerprint
        if args.verbose:
            print("Extracting build fingerprint...")
        extractor = BuildFingerprintExtractor(engine)
        fingerprint = extractor.extract(context=args.context)

        if args.verbose:
            print(f"Build: {fingerprint.build_name}")
            print(f"Class: {fingerprint.class_name} / {fingerprint.ascendancy}")
            print(f"Main Skill: {fingerprint.main_skill}")
            print(f"Defense Layer: {fingerprint.defense_layer.value}")
            print(f"Equipped slots: {len(fingerprint.equipped)}")

        # FILTER-08B: optional production Build Intelligence (measured needs). Default stays the legacy generator.
        needs = None
        if args.needs:
            from exilelens.filters.build_needs import BuildNeedsSnapshot
            needs = BuildNeedsSnapshot.from_json(Path(args.needs).read_text(encoding="utf-8"))
        elif args.analyze:
            from exilelens.analysis.pipeline import analyze_build
            from exilelens.filters.probe_policy import FilterProbeCatalog
            from exilelens.filters.build_needs import BuildNeedsSnapshot
            if args.verbose:
                print("Measuring build with production Build Intelligence...")
            equipped = {slot.value: item.base_type for slot, item in fingerprint.equipped.items() if item.base_type}
            needs = BuildNeedsSnapshot.from_analysis(
                analyze_build(engine, build_path=str(build_path), context=args.context, catalog=FilterProbeCatalog()),
                label=build_path.stem, equipped=equipped)
            if args.save_needs:
                Path(args.save_needs).write_text(needs.to_json() + "\n", encoding="utf-8")

        # Resolve slot priorities
        if args.verbose:
            print("Resolving slot priorities...")
        intel = None
        if needs is not None:
            from exilelens.filters.intel_resolver import BuildIntelSlotPriorityResolver
            priority_resolver = BuildIntelSlotPriorityResolver(fingerprint, needs)
            intel = priority_resolver.intel
            if args.verbose:
                print(f"Build intelligence: {needs.coverage.value} ({'; '.join(needs.coverage_reasons)})")
        else:
            priority_resolver = SlotPriorityResolver(fingerprint)
        slot_priorities = priority_resolver.resolve_all()

        if args.verbose:
            for slot, priority in slot_priorities.items():
                tier_counts = {}
                for base, tier in priority.base_tiers.items():
                    tier_counts[tier.value] = tier_counts.get(tier.value, 0) + 1
                print(f"  {slot.value}: {tier_counts}")

        # Generate rules
        if args.verbose:
            print("Generating filter rules...")
        rule_generator = RuleGenerator(
            slot_priorities=slot_priorities,
            profile=profile,
            main_skill=fingerprint.main_skill,
            defense_layer=fingerprint.defense_layer,
            intel=intel,
        )
        rules = rule_generator.generate_all()

        if args.verbose:
            print(f"Generated {len(rules)} rules")
            categories = {}
            for rule in rules:
                categories[rule.category] = categories.get(rule.category, 0) + 1
            for cat, count in sorted(categories.items()):
                print(f"  {cat}: {count} rules")

        # Serialize
        if args.verbose:
            print("Serializing filter...")
        metadata = create_metadata_from_fingerprint(fingerprint, profile)
        serializer = FilterSerializer(metadata)
        filter_text = serializer.serialize(rules)

        # Determinism check
        if args.check_determinism:
            if args.verbose:
                print("Checking determinism...")
            filter_text2 = serializer.serialize(rule_generator.generate_all())
            if filter_text != filter_text2:
                print("ERROR: Filter generation is not deterministic!", file=sys.stderr)
                return 1
            if args.verbose:
                print("Determinism check passed.")

        # Validation
        if args.verbose:
            print("Running static validation...")
        validation_result = validate_all(filter_text)
        if not validation_result.passed:
            print("VALIDATION FAILED:", file=sys.stderr)
            for err in validation_result.errors:
                print(f"  ERROR: {err}", file=sys.stderr)
            for warn in validation_result.warnings:
                print(f"  WARNING: {warn}", file=sys.stderr)
            return 1
        if args.verbose:
            print("Validation passed.")
            for warn in validation_result.warnings:
                print(f"  WARNING: {warn}")

        # Write output
        serializer.write_file(rules, str(output_path))

        if args.verbose:
            print(f"Filter written to: {output_path}")
            print(f"Size: {len(filter_text)} bytes, {len(filter_text.split(chr(10)))} lines")

        return 0

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1
    finally:
        engine.shutdown()


if __name__ == "__main__":
    sys.exit(main())
