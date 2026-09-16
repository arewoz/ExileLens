from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from poe2value.config import load_config, validate_pob_path
from poe2value.engine import Engine
from poe2value.errors import EngineError
from poe2value.items.evaluation import evaluate_item
from poe2value.items.raw_input import ItemInputSource


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _print_human_evaluation(result: dict) -> None:
    build = result.get("build") or {}
    print("BUILD")
    print(json.dumps(build, indent=2) if isinstance(build, dict) else build)
    baseline = result["baseline"]["normalized"]
    candidate = result["candidate"]["normalized"]
    delta = result["delta"]
    print("\nCURRENT")
    print(json.dumps(baseline, indent=2))
    print("\nCANDIDATE")
    print(json.dumps(candidate, indent=2))
    print("\nDELTA")
    print(json.dumps(delta, indent=2))
    offense = delta.get("offense", {}).get("primary_dps")
    defense = delta.get("defense", {}).get("ehp")
    if offense:
        print(
            f"\nDPS\n{offense['current']}\n->\n{offense['candidate']}\n"
            f"{offense['absolute']:+.1f}\n{offense['percent']:+.2f}%"
        )
    if defense:
        print(
            f"\nEHP\n{defense['current']}\n->\n{defense['candidate']}\n"
            f"{defense['absolute']:+.1f}\n{defense['percent']:+.2f}%"
        )
    print("\nRESTORE")
    print("PASS" if result["restore"]["pass"] else "FAIL")


def _print_human_item_evaluation(result: dict) -> None:
    print("ITEM")
    print(result["pob_parse"]["display_name"])
    print(f"Classification: {result['recognition']['classification']}")
    print(f"Compatible slots: {', '.join(slot['pob_slot'] for slot in result['compatible_slots'])}")
    print(f"Primary metric: {result['primary_metric']['pob_field']} ({result['primary_metric']['confidence']})")
    print("\nSLOT COMPARISONS")
    for comparison in result["slot_comparisons"]:
        profile = comparison["metric_profile"]
        offense = profile["primary_offense"]
        defense = profile["ehp"]
        baseline_item = comparison.get("baseline_item") or {}
        print(
            f"- {comparison['product_slot']} ({comparison['pob_slot']}): "
            f"vs {baseline_item.get('display_name') or baseline_item.get('name') or 'baseline'} | "
            f"{comparison['verdict']} | DPS {offense['current']:.1f} -> {offense['candidate']:.1f} "
            f"({offense['absolute_delta']:+.1f}) | EHP {defense['current']:.1f} -> {defense['candidate']:.1f} "
            f"({defense['absolute_delta']:+.1f}) | restore {'PASS' if comparison['restore']['pass'] else 'FAIL'}"
        )
    recommendation = result.get("recommendation") or {}
    if recommendation:
        print("\nRECOMMENDATION")
        print(
            f"{recommendation.get('product_slot')} -> {recommendation.get('verdict')} "
            f"({result['pareto'].get('status')})"
        )
    print("\nTIMINGS (ms)")
    print(json.dumps(result.get("timings", {}), indent=2))


def _read_item_text(item_path: Path | None) -> tuple[str, ItemInputSource]:
    if item_path:
        return item_path.read_text(encoding="utf-8"), ItemInputSource.FILE
    if not sys.stdin.isatty():
        return sys.stdin.read(), ItemInputSource.STDIN
    raise SystemExit("item input required via --item or stdin")


def _print_tree_human(command: str, result: dict) -> None:
    if command == "tree-info":
        stats = result.get("stats") or {}
        tree_set = result.get("tree_set") or {}
        print(f"TREE SET  {tree_set.get('title') or 'Default'}  (index {tree_set.get('index')})")
        print(f"CLASS     {result.get('class')} / {result.get('ascendancy')}")
        print(f"NODES     {stats.get('node_count')}  EDGES {stats.get('edge_count')}  ALLOCATED {stats.get('allocated_count')}")
        frontier = result.get("frontier") or []
        print(f"FRONTIER  {len(frontier)} supported-adjacent nodes")
        return
    if command == "evaluate-node":
        target = result.get("target") or {}
        print(f"{result.get('status')}  {target.get('name')} ({target.get('node_id')})  cost {result.get('cost')}")
        print(f"Build Value {result.get('build_value_delta')}  /pt {result.get('value_per_point')}")
        print("RESTORE", "PASS" if result.get("restore_verified") else "FAIL")
        return
    rows = ((result.get("next_passive") or result.get("targets") or {}).get("recommendations")) or []
    title = "NEXT PASSIVE POINT" if command == "next-passive" else "NEARBY TARGETS"
    print(title)
    baseline = result.get("baseline") or {}
    print(f"{baseline.get('build_name')} · {baseline.get('context')} · {baseline.get('profile')}")
    for row in rows[:10]:
        print(
            f"{row.get('rank')}. {row.get('name')}  cost {row.get('cost')}  "
            f"Build Value {row.get('build_value_delta')}  /pt {row.get('value_per_point')}"
        )


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "ops":
        from poe2value.ops.cli import main as ops_main

        return ops_main(argv[1:])

    parser = argparse.ArgumentParser(prog="poe2value")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("engine-info", help="show PoB engine configuration and revision")

    load_p = sub.add_parser("load-build", help="load a build and print summary")
    load_p.add_argument("path", type=Path)

    inspect_p = sub.add_parser("inspect-build", help="inspect a build without keeping session alive")
    inspect_p.add_argument("path", type=Path)

    eval_p = sub.add_parser("evaluate", help="evaluate one candidate item against a build")
    eval_p.add_argument("--build", required=True, type=Path)
    eval_p.add_argument("--item", required=True, type=Path)
    eval_p.add_argument("--slot", required=True)
    eval_p.add_argument("--context", default="MAP")

    eval_item_p = sub.add_parser("evaluate-item", help="evaluate clipboard-style item text against a build")
    eval_item_p.add_argument("--build", required=True, type=Path)
    eval_item_p.add_argument("--item", type=Path, help="item text file; omit to read stdin")
    eval_item_p.add_argument("--context", default="MAP")
    eval_item_p.add_argument("--debug", action="store_true")
    eval_item_p.add_argument("--debug-comparison", action="store_true", help="print CANDIDATE/BASELINE/metrics/verdict trace")

    analyze_p = sub.add_parser("analyze-build", help="reverse-analyze the current build (Phase 5A)")
    analyze_p.add_argument("--build", required=True, type=Path)
    analyze_p.add_argument("--profile", default="BALANCED")
    analyze_p.add_argument("--context", default="MAP")
    analyze_p.add_argument("--loadout", default="")
    analyze_p.add_argument("--item-set", default="")

    slot_p = sub.add_parser("analyze-slot", help="analyze one equipped slot")
    slot_p.add_argument("--build", required=True, type=Path)
    slot_p.add_argument("--slot", required=True)
    slot_p.add_argument("--profile", default="BALANCED")
    slot_p.add_argument("--context", default="MAP")
    slot_p.add_argument("--loadout", default="")
    slot_p.add_argument("--item-set", default="")

    intent_p = sub.add_parser("search-intent", help="emit Search Intent JSON for a slot")
    intent_p.add_argument("--build", required=True, type=Path)
    intent_p.add_argument("--slot", required=True)
    intent_p.add_argument("--profile", default="BALANCED")
    intent_p.add_argument("--context", default="MAP")
    intent_p.add_argument("--json", action="store_true")
    intent_p.add_argument("--loadout", default="")
    intent_p.add_argument("--item-set", default="")

    market_p = sub.add_parser("market-search", help="run Phase 5B market candidate search (fixture/import)")
    market_p.add_argument("--build", required=True, type=Path)
    market_p.add_argument("--slot", required=True)
    market_p.add_argument("--profile", default="BALANCED")
    market_p.add_argument("--context", default="MAP")
    market_p.add_argument("--depth", default="BALANCED", choices=["FAST", "BALANCED", "DEEP"])
    market_p.add_argument("--corpus", type=Path, help="fixture corpus JSON path")
    market_p.add_argument("--import", dest="import_path", type=Path, help="imported listings JSON/NDJSON")
    market_p.add_argument("--budget", type=float, default=0)
    market_p.add_argument("--currency", default="Divine")
    market_p.add_argument("--loadout", default="")
    market_p.add_argument("--item-set", default="")

    gear_p = sub.add_parser("gear-optimize", help="run Phase 5C budget gear optimizer (requires 5B pools)")
    gear_p.add_argument("--build", required=True, type=Path)
    gear_p.add_argument("--budget", type=float, required=True)
    gear_p.add_argument("--currency", default="Divine")
    gear_p.add_argument("--profile", default="BALANCED")
    gear_p.add_argument("--context", default="MAP")
    gear_p.add_argument("--preset", default="BALANCED", choices=["FAST", "BALANCED", "DEEP"])
    gear_p.add_argument("--slots", default="RING_1,RING_2", help="comma-separated product slots")
    gear_p.add_argument("--ring-corpus", type=Path, help="fixture corpus for ring pools")
    gear_p.add_argument("--helmet-corpus", type=Path, help="fixture corpus for helmet pool")
    gear_p.add_argument("--loadout", default="")
    gear_p.add_argument("--item-set", default="")
    gear_p.add_argument("--json", action="store_true")

    tree_info_p = sub.add_parser("tree-info", help="export passive tree graph + allocation (Phase 5A.5)")
    tree_info_p.add_argument("--build", required=True, type=Path)
    tree_info_p.add_argument("--context", default="MAP")
    tree_info_p.add_argument("--loadout", default="")
    tree_info_p.add_argument("--item-set", default="")

    next_p = sub.add_parser("next-passive", help="rank direct frontier next passive points")
    next_p.add_argument("--build", required=True, type=Path)
    next_p.add_argument("--profile", default="BALANCED")
    next_p.add_argument("--context", default="MAP")
    next_p.add_argument("--loadout", default="")
    next_p.add_argument("--item-set", default="")
    next_p.add_argument("--limit", type=int, default=10)

    targets_p = sub.add_parser("tree-targets", help="rank notables/keystones within a point budget")
    targets_p.add_argument("--build", required=True, type=Path)
    targets_p.add_argument("--profile", default="BALANCED")
    targets_p.add_argument("--context", default="MAP")
    targets_p.add_argument("--max-points", type=int, default=5)
    targets_p.add_argument("--mode", default="total", choices=["total", "efficiency"])
    targets_p.add_argument("--loadout", default="")
    targets_p.add_argument("--item-set", default="")

    eval_node_p = sub.add_parser("evaluate-node", help="evaluate one node/path through real PoB")
    eval_node_p.add_argument("--build", required=True, type=Path)
    eval_node_p.add_argument("--node-id", required=True, type=int)
    eval_node_p.add_argument("--profile", default="BALANCED")
    eval_node_p.add_argument("--context", default="MAP")
    eval_node_p.add_argument("--loadout", default="")
    eval_node_p.add_argument("--item-set", default="")

    args = parser.parse_args(argv)
    config = load_config()
    repo_root = _repo_root()

    def resolve_repo_path(path: Path) -> Path:
        path = Path(path)
        if path.is_absolute():
            return path
        return (repo_root / path).resolve()

    try:
        if args.command == "engine-info":
            info = validate_pob_path(config)
            payload = {"engine": info}
            if args.json:
                print(json.dumps(payload, indent=2))
            else:
                for key, value in info.items():
                    print(f"{key}: {value}")
            return 0

        if args.command == "evaluate":
            build_path = resolve_repo_path(args.build)
            item_path = resolve_repo_path(args.item)
            item_raw = item_path.read_text(encoding="utf-8")

        if args.command == "evaluate-item":
            build_path = resolve_repo_path(args.build)
            item_raw, source = _read_item_text(resolve_repo_path(args.item) if args.item else None)

        with Engine(config) as engine:
            if args.command == "load-build":
                result = engine.load_build(resolve_repo_path(args.path))
                payload = result
                if args.json:
                    print(json.dumps(payload, indent=2))
                else:
                    print(json.dumps(payload, indent=2))
                return 0

            if args.command == "inspect-build":
                result = engine.load_build(resolve_repo_path(args.path))
                equipment = engine.get_equipment()
                metrics = engine.get_metrics()
                payload = {
                    "build": result.get("build"),
                    "equipment": equipment,
                    "metrics": metrics,
                }
                print(json.dumps(payload, indent=2))
                return 0

            if args.command == "evaluate":
                engine.load_build(build_path, context=args.context)
                result = engine.evaluate_candidate(args.slot, item_raw, context=args.context)
                if args.json:
                    print(json.dumps(result, indent=2))
                else:
                    _print_human_evaluation(result)
                return 0

            if args.command == "evaluate-item":
                result = evaluate_item(
                    item_raw,
                    engine,
                    build_path=str(build_path),
                    context=args.context,
                    source=source,
                    debug=bool(args.debug or getattr(args, "debug_comparison", False)),
                )
                if getattr(args, "debug_comparison", False) and not args.json:
                    from poe2value.items.comparison_trace import format_comparison_trace

                    print(format_comparison_trace(result.get("comparison_trace") or {}))
                    print()
                if args.json:
                    print(json.dumps(result, indent=2))
                else:
                    _print_human_item_evaluation(result)
                return 0

            if args.command in {"analyze-build", "analyze-slot", "search-intent"}:
                from poe2value.analysis.pipeline import analyze_build, analyze_slot, search_intent_for_slot

                build_path = resolve_repo_path(args.build)
                common = {
                    "build_path": str(build_path),
                    "context": args.context,
                    "profile": args.profile,
                    "loadout": args.loadout,
                    "item_set": getattr(args, "item_set", ""),
                    "pob_path": str(config.pob_path),
                }
                if args.command == "analyze-build":
                    result = analyze_build(engine, **common)
                elif args.command == "analyze-slot":
                    result = analyze_slot(engine, slot=args.slot, **common)
                else:
                    result = search_intent_for_slot(engine, slot=args.slot, **common)
                print(json.dumps(result, indent=2, default=str))
                return 0

            if args.command == "market-search":
                from poe2value.market.engine import run_market_search
                from poe2value.market.models import MarketSearchRequest, SearchDepth

                build_path = resolve_repo_path(args.build)
                source = "import" if args.import_path else "fixture"
                request = MarketSearchRequest(
                    slot=args.slot,
                    profile=args.profile,
                    budget_amount=args.budget if args.budget > 0 else None,
                    budget_currency=args.currency if args.budget > 0 else None,
                    depth=SearchDepth(args.depth),
                    source=source,
                    fixture_corpus=str(args.corpus) if args.corpus else None,
                    import_path=str(args.import_path) if args.import_path else None,
                )
                result = run_market_search(
                    engine,
                    request,
                    build_path=str(build_path),
                    context=args.context,
                    loadout=args.loadout,
                    item_set=args.item_set,
                    pob_path=str(config.pob_path),
                )
                print(json.dumps(result.to_dict(), indent=2, default=str))
                return 0

            if args.command == "gear-optimize":
                from poe2value.gear.engine import run_gear_optimization
                from poe2value.gear.models import GearOptimizationRequest, GearSearchPreset
                from poe2value.market.engine import run_market_search
                from poe2value.market.models import MarketSearchRequest, SearchDepth

                build_path = resolve_repo_path(args.build)
                engine.load_build(build_path, context=args.context)
                fp = engine.get_metrics(args.context)["fingerprint_hash"]
                slots = tuple(s.strip().upper() for s in args.slots.split(",") if s.strip())
                repo = _repo_root()
                ring_corpus = args.ring_corpus or repo / "fixtures" / "market" / "ring_corpus.json"
                pools = {}
                for slot in slots:
                    corpus = ring_corpus
                    if slot == "HELMET" and args.helmet_corpus:
                        corpus = args.helmet_corpus
                    elif slot == "HELMET":
                        corpus = repo / "fixtures" / "market" / "helmet_corpus.json"
                    result = run_market_search(
                        engine,
                        MarketSearchRequest(slot=slot, depth=SearchDepth.FAST, fixture_corpus=str(corpus)),
                        build_path=str(build_path),
                        context=args.context,
                    )
                    pools[slot] = result.pool
                request = GearOptimizationRequest(
                    baseline_fingerprint=fp,
                    baseline_generation=1,
                    pools=pools,
                    budget_amount=float(args.budget),
                    budget_currency=args.currency,
                    profile=args.profile,
                    context=args.context,
                    search_preset=GearSearchPreset(args.preset),
                    enabled_slots=slots,
                )
                outcome = run_gear_optimization(
                    engine,
                    request,
                    build_path=str(build_path),
                    context=args.context,
                    loadout=args.loadout,
                    item_set=args.item_set,
                )
                print(json.dumps(outcome.to_dict(), indent=2, default=str))
                return 0

            if args.command in {"tree-info", "next-passive", "tree-targets", "evaluate-node"}:
                from poe2value.tree.mutations import TreeProbeEngine, load_tree_snapshot, primary_from_engine
                from poe2value.tree.pipeline import tree_info_payload
                from poe2value.tree.ranking import rank_next_passive_points, rank_targets

                build_path = resolve_repo_path(args.build)
                common = {
                    "build_path": str(build_path),
                    "context": args.context,
                    "profile": getattr(args, "profile", "BALANCED"),
                    "loadout": getattr(args, "loadout", ""),
                    "item_set": getattr(args, "item_set", ""),
                    "generation": 0,
                }
                if args.command == "tree-info":
                    result = tree_info_payload(engine, **common)
                elif args.command == "next-passive":
                    snapshot = load_tree_snapshot(engine, **common)
                    field, conf = primary_from_engine(engine)
                    ranked = rank_next_passive_points(
                        snapshot,
                        TreeProbeEngine(engine),
                        profile=args.profile,
                        primary_field=field,
                        primary_confidence=conf,
                        limit=args.limit,
                    )
                    result = {"baseline": snapshot.baseline.to_dict(), "next_passive": ranked}
                elif args.command == "tree-targets":
                    snapshot = load_tree_snapshot(engine, **common)
                    field, conf = primary_from_engine(engine)
                    ranked = rank_targets(
                        snapshot,
                        TreeProbeEngine(engine),
                        max_points=args.max_points,
                        profile=args.profile,
                        mode=args.mode,
                        primary_field=field,
                        primary_confidence=conf,
                    )
                    result = {"baseline": snapshot.baseline.to_dict(), "targets": ranked}
                else:
                    snapshot = load_tree_snapshot(engine, **common)
                    field, conf = primary_from_engine(engine)
                    result = TreeProbeEngine(engine).evaluate_node(
                        snapshot,
                        args.node_id,
                        profile=args.profile,
                        primary_field=field,
                        primary_confidence=conf,
                        context=args.context,
                    )
                if args.json:
                    print(json.dumps(result, indent=2, default=str))
                else:
                    _print_tree_human(args.command, result)
                return 0
    except EngineError as exc:
        payload = {"ok": False, "error": exc.to_dict()}
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(f"ERROR {exc.code}: {exc.message}", file=sys.stderr)
        return 1
    except Exception as exc:  # pragma: no cover
        if args.json:
            print(json.dumps({"ok": False, "error": {"code": "CALC_FAILED", "message": str(exc)}}))
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
