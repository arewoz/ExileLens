"""Developer operations CLI: `python -m poe2value ops <command>`."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from poe2value.ops.paths import repo_root


def _print(payload: Any, *, as_json: bool, text: str | None = None) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, default=str))
        return
    if text:
        print(text)
        return
    print(json.dumps(payload, indent=2, default=str))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="poe2value ops")
    parser.add_argument("--json", action="store_true", help="machine-readable JSON")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("project-health", help="aggregate repo/app health")

    rg = sub.add_parser("release-gate", help="PASS/BLOCKED release decision")
    rg.add_argument("--allow-dirty", action="store_true")
    rg.add_argument("--require-artifact", action="store_true")
    rg.add_argument("--run-smoke", action="store_true")

    gu = sub.add_parser("game-update", help="classify patch notes and select tests")
    gu.add_argument("--notes", type=Path)
    gu.add_argument("--version", dest="game_version")
    gu.add_argument("--run-tests", action="store_true")

    pc = sub.add_parser("pob-compatibility", help="compare PoB revision to verified commit")
    pc.add_argument("--pob-path", type=Path)
    pc.add_argument("--fetch", action="store_true")

    ra = sub.add_parser("regression-audit", help="known failure modes + suggested tests")
    ra.add_argument("--changed", nargs="*", default=())
    ra.add_argument("--subsystem", action="append", default=())

    mh = sub.add_parser("market-health", help="offline market funnel diagnosis")
    mh.add_argument("--item", type=Path)
    mh.add_argument("--listings", type=Path)

    bsa = sub.add_parser("build-source-audit", help="configured vs loaded build identity")
    bsa.add_argument("--build", type=Path)
    bsa.add_argument("--settings", type=Path)
    bsa.add_argument("--cache-root", type=Path)

    sub.add_parser("fixture-audit", help="check compact fixture corpus paths")
    rn = sub.add_parser("release-notes", help="user-facing notes since last tag/changelog")
    rn.add_argument("--since")

    sub.add_parser("smoke", help="deterministic offline smoke suite")
    canary = sub.add_parser("market-canary", help="opt-in live trade2 canary")
    canary.add_argument("--live", action="store_true")

    wp = sub.add_parser("watch-patch", help="detect a new PoE2 version/notes (no code rewrite)")
    wp.add_argument("--version")
    wp.add_argument("--notes", type=Path)
    wp.add_argument("--fetch-url")

    wpb = sub.add_parser("watch-pob", help="detect a new PathOfBuilding-PoE2 revision")
    wpb.add_argument("--pob-path", type=Path)
    wpb.add_argument("--fetch", action="store_true")

    bt = sub.add_parser("bug-triage", help="structure a raw user report")
    bt.add_argument("--text")
    bt.add_argument("--file", type=Path)
    bt.add_argument("--environment", default="unspecified")

    sub.add_parser("validate-manifest", help="parse and validate ops/compatibility.json")

    args = parser.parse_args(argv)
    as_json = bool(args.json)
    root = repo_root()

    if args.command == "validate-manifest":
        from poe2value.ops.compatibility import load_manifest, validate_against_code

        manifest = load_manifest()
        warnings = validate_against_code(manifest, root=root)
        payload = {"ok": True, "manifest": manifest.to_dict(), "warnings": warnings}
        _print(payload, as_json=as_json)
        return 0

    if args.command == "project-health":
        from poe2value.ops.project_health import evaluate_project_health

        report = evaluate_project_health(root=root, allow_dirty=True)
        _print(report.to_dict(), as_json=as_json, text=report.format_text())
        return 0 if report.verdict.value != "BLOCKED" else 2

    if args.command == "release-gate":
        from poe2value.ops.models import CheckResult, GateVerdict, Severity
        from poe2value.ops.release_gate import evaluate_release_gate
        from poe2value.ops.smoke import run_smoke

        smoke_result = None
        if args.run_smoke:
            smoke = run_smoke(root=root)
            smoke_result = CheckResult(
                "smoke",
                GateVerdict.PASS if smoke["ok"] else GateVerdict.BLOCKED,
                None if smoke["ok"] else Severity.P0,
                "smoke passed" if smoke["ok"] else "smoke failed",
                data=smoke,
            )
        report = evaluate_release_gate(
            root=root,
            allow_dirty=args.allow_dirty,
            require_artifact=args.require_artifact,
            smoke_result=smoke_result,
        )
        _print(report.to_dict(), as_json=as_json, text=report.format_text())
        return 0 if report.verdict is GateVerdict.PASS else 2

    if args.command == "game-update":
        from poe2value.ops.game_update import run_game_update

        if not args.notes:
            print("game-update requires --notes <file>", file=sys.stderr)
            return 2
        payload = run_game_update(
            notes_path=args.notes,
            game_version=args.game_version,
            run_tests=args.run_tests,
            root=root,
        )
        _print(payload, as_json=as_json)
        return 0

    if args.command == "pob-compatibility":
        from poe2value.ops.pob_compat import inspect_pob_compatibility

        payload = inspect_pob_compatibility(pob_path=args.pob_path, fetch_remote=args.fetch).to_dict()
        _print(payload, as_json=as_json)
        return 0

    if args.command == "regression-audit":
        from poe2value.ops.regression import load_registry, select_for_changed_paths, select_for_subsystems, paths_for_entries

        entries = load_registry()
        if args.changed:
            entries = select_for_changed_paths(entries, args.changed)
        elif args.subsystem:
            entries = select_for_subsystems(entries, args.subsystem)
        payload = {
            "entries": [entry.to_dict() for entry in entries],
            "tests": paths_for_entries(entries),
        }
        _print(payload, as_json=as_json)
        return 0

    if args.command == "market-health":
        from poe2value.ops.market_health import diagnose_offline

        item_raw = args.item.read_text(encoding="utf-8") if args.item else None
        listings = json.loads(args.listings.read_text(encoding="utf-8")).get("listings") if args.listings else None
        report = diagnose_offline(item_raw, listings, root=root)
        _print(report.to_dict(), as_json=as_json)
        return 0 if report.overall != "FAIL" else 2

    if args.command == "build-source-audit":
        from poe2value.ops.build_source_audit import audit_build_source

        report = audit_build_source(
            build_path=args.build,
            settings_path=args.settings,
            cache_root=args.cache_root,
        )
        _print(report.to_dict(), as_json=as_json)
        return 0 if report.status.value in {"CURRENT", "STALE", "MISMATCH"} else 2

    if args.command == "fixture-audit":
        from poe2value.ops.fixture_audit import audit_fixture_corpus

        report = audit_fixture_corpus(root=root)
        _print(report.to_dict(), as_json=as_json)
        return 0 if report.to_dict()["ok"] else 2

    if args.command == "release-notes":
        from poe2value.ops.release_notes import collect_release_notes

        notes = collect_release_notes(root=root, since_ref=args.since)
        _print(notes.to_dict(), as_json=as_json, text=notes.format_text())
        return 0

    if args.command == "smoke":
        from poe2value.ops.smoke import run_smoke

        result = run_smoke(root=root)
        _print(result, as_json=as_json)
        return 0 if result["ok"] else 1

    if args.command == "market-canary":
        from poe2value.ops.market_canary import run_market_canary

        report = run_market_canary(force=args.live)
        _print(report.to_dict(), as_json=as_json)
        return 0 if (not report.ran) or report.stages.get("query_accepted") != "FAIL" else 2

    if args.command == "watch-patch":
        from poe2value.ops.watchers import watch_patch

        report = watch_patch(version=args.version, notes_path=args.notes, fetch_url=args.fetch_url)
        _print(report.to_dict(), as_json=as_json)
        return 0

    if args.command == "watch-pob":
        from poe2value.ops.watchers import watch_pob

        _print(watch_pob(pob_path=args.pob_path, fetch_remote=args.fetch), as_json=as_json)
        return 0

    if args.command == "bug-triage":
        from poe2value.ops.bug_triage import triage_text

        text = args.text or (args.file.read_text(encoding="utf-8") if args.file else None)
        if not text:
            text = sys.stdin.read()
        if not text.strip():
            print("bug-triage requires --text, --file, or stdin", file=sys.stderr)
            return 2
        report = triage_text(text, environment=args.environment)
        _print(report.to_dict(), as_json=as_json, text=report.format_text())
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
