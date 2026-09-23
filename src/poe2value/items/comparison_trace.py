from __future__ import annotations

from typing import Any

from poe2value.items.evaluation_outcome import authoritative_public_verdict, authoritative_verdict_reason


def build_comparison_trace(result: dict[str, Any]) -> dict[str, Any]:
    rec = result.get("recommendation") or {}
    baseline_item = rec.get("baseline_item") or {}
    candidate_item = rec.get("candidate_item") or result.get("candidate_item") or {}
    metrics = rec.get("metric_profile") or rec.get("normalized_metrics") or {}
    resist = rec.get("resist_caps") or {}
    restore = rec.get("restore") or {}
    build = result.get("build") or {}
    return {
        "baseline": {
            "build": build.get("build_name") or (result.get("request_meta") or {}).get("build_name"),
            "loadout": baseline_item.get("loadout_name") or build.get("active_loadout"),
            "item_set_id": baseline_item.get("item_set_id"),
            "item_set_name": baseline_item.get("item_set_name"),
            "slot": rec.get("pob_slot") or baseline_item.get("slot"),
            "item_id": baseline_item.get("item_id"),
            "item_name": baseline_item.get("display_name") or baseline_item.get("name"),
            "base_type": baseline_item.get("base_type"),
            "metrics": {
                "primary_offense": (metrics.get("primary_offense") or {}).get("current"),
                "ehp": (metrics.get("ehp") or {}).get("current"),
                "worst_max_hit": (metrics.get("worst_max_hit") or {}).get("current"),
                "life": (metrics.get("life") or {}).get("current"),
                "energy_shield": (metrics.get("energy_shield") or {}).get("current"),
                "fire_res": (metrics.get("fire_res") or {}).get("current"),
                "cold_res": (metrics.get("cold_res") or {}).get("current"),
                "lightning_res": (metrics.get("lightning_res") or {}).get("current"),
                "chaos_res": (metrics.get("chaos_res") or {}).get("current"),
            },
            "fingerprint": ((rec.get("baseline") or {}).get("fingerprint_hash")),
        },
        "candidate": {
            "name": candidate_item.get("name") or (result.get("metadata") or {}).get("name"),
            "base_type": candidate_item.get("base_type"),
            "parsed": candidate_item.get("pob_parsed"),
            "target_slot": candidate_item.get("target_slot") or rec.get("pob_slot"),
            "metrics": {
                "primary_offense": (metrics.get("primary_offense") or {}).get("candidate"),
                "ehp": (metrics.get("ehp") or {}).get("candidate"),
                "worst_max_hit": (metrics.get("worst_max_hit") or {}).get("candidate"),
                "life": (metrics.get("life") or {}).get("candidate"),
                "energy_shield": (metrics.get("energy_shield") or {}).get("candidate"),
                "fire_res": (metrics.get("fire_res") or {}).get("candidate"),
                "cold_res": (metrics.get("cold_res") or {}).get("candidate"),
                "lightning_res": (metrics.get("lightning_res") or {}).get("candidate"),
                "chaos_res": (metrics.get("chaos_res") or {}).get("candidate"),
            },
        },
        "delta": {
            "warnings": rec.get("warnings") or [],
            "guardrails": ((rec.get("value") or {}).get("guardrails")) or [],
            "consequences": resist,
            "score": rec.get("value"),
            "verdict": authoritative_public_verdict(rec),
            "explanation": authoritative_verdict_reason(rec),
        },
        "restore": {
            "pass": restore.get("pass"),
            "fingerprint_match": restore.get("fingerprint_match"),
            "equipment_match": restore.get("equipment_match"),
        },
    }


def format_comparison_trace(trace: dict[str, Any]) -> str:
    baseline = trace.get("baseline") or {}
    candidate = trace.get("candidate") or {}
    delta = trace.get("delta") or {}
    restore = trace.get("restore") or {}
    lines = [
        "CANDIDATE",
        f"  {candidate.get('name')} ({candidate.get('base_type')})",
        f"  slot {candidate.get('target_slot')}",
        "BASELINE ITEM",
        f"  {baseline.get('item_name')} ({baseline.get('base_type')})",
        f"  {baseline.get('slot')} · {baseline.get('item_set_name')} · {baseline.get('loadout')}",
        f"  build {baseline.get('build')}",
        "RAW METRICS",
        f"  current {baseline.get('metrics')}",
        f"  candidate {candidate.get('metrics')}",
        "CONSEQUENCES",
        f"  {(delta.get('consequences') or {}).get('elements')}",
        "SCORE",
        f"  {delta.get('score')}",
        "VERDICT",
        f"  {delta.get('verdict')} — {delta.get('explanation')}",
        "RESTORE",
        f"  {'PASS' if restore.get('pass') else 'FAIL'} fingerprint={restore.get('fingerprint_match')}",
    ]
    return "\n".join(lines)
