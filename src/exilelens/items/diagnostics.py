"""Stable, privacy-safe diagnostics for one Item Check evaluation.

The serializer is deliberately allowlist based. It never walks application
settings, process state, or the environment, and it only selects fields that
are useful when investigating an incorrect evaluation.
"""

from __future__ import annotations

import json
import hashlib
import re
from typing import Any, Mapping

from exilelens import SUPPORTED_POB_HEAD, __version__
from exilelens._version import git_commit
from exilelens.items.offense_coverage import selected_part_guard_state

DIAGNOSTICS_SCHEMA_VERSION = 1

_SENSITIVE_KEY_PARTS = (
    "authorization",
    "cookie",
    "credential",
    "password",
    "poesessid",
    "refresh_token",
    "secret",
    "session_token",
    "token",
)
_ASSIGNMENT_SECRET = re.compile(
    r"(?i)\b(POESESSID|Authorization|password|refresh[_ -]?token|access[_ -]?token|"
    r"id_token|api[_ -]?key|client[_ -]?secret|token)"
    r"\s*[:=]\s*(?:Bearer\s+)?[^\s,;\]}'\"]+"
)
_BEARER_SECRET = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_QUOTED_DICT_SECRET = re.compile(
    r"(?i)(['\"])(POESESSID|Authorization|password|refresh[_ -]?token|access[_ -]?token|"
    r"id_token|api[_ -]?key|client[_ -]?secret|token)\1\s*:\s*"
    r"(['\"])(?:Bearer\s+)?(?:\\.|(?!\3).)*\3"
)

_OUTCOME_FIELDS = (
    "evaluation_quality",
    "evaluation_quality_reasons",
    "final_score",
    "raw_score",
    "pre_guardrail_score",
    "verdict",
    "verdict_label",
    "verdict_reason",
    "guardrails_applied",
    "primary_deltas",
    "all_deltas",
    "score_contributors",
    "critical_tradeoffs",
    "unsupported_or_unmodeled",
    "resistances",
    "source_slot",
    "replacement_slot",
    "replacing_item",
    "replacing_empty_slot",
    "baseline_metrics",
    "candidate_metrics",
    "profile",
    "timings",
)


def _sensitive_key(key: object) -> bool:
    normalized = str(key or "").strip().lower().replace("-", "_").replace(" ", "_")
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def _redact_text(value: str) -> str:
    value = _QUOTED_DICT_SECRET.sub(lambda match: f"{match.group(1)}{match.group(2)}{match.group(1)}: {match.group(3)}[REDACTED]{match.group(3)}", value)
    value = _ASSIGNMENT_SECRET.sub(lambda match: f"{match.group(1)}=[REDACTED]", value)
    return _BEARER_SECRET.sub("Bearer [REDACTED]", value)


def _safe(value: Any) -> Any:
    """Return JSON-safe data while removing secrets even from allowed free text."""
    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]" if _sensitive_key(key) else _safe(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _redact_text(str(value))


def _pick(source: Mapping[str, Any] | None, fields: tuple[str, ...]) -> dict[str, Any]:
    source = source or {}
    return {
        field: _safe(source[field])
        for field in fields
        if field in source and source[field] not in (None, "", [], {})
    }


def _legal_slots(result: Mapping[str, Any], model: Mapping[str, Any]) -> list[str]:
    slots: list[str] = []
    for comparison in result.get("slot_comparisons") or []:
        slot = str((comparison or {}).get("pob_slot") or "").strip()
        if slot and slot not in slots:
            slots.append(slot)
    for choice in model.get("replacement_choices") or []:
        slot = str((choice or {}).get("slot") or "").strip()
        if slot and slot not in slots:
            slots.append(slot)
    outcome = model.get("evaluation_outcome") or {}
    slot = str(outcome.get("replacement_slot") or "").strip()
    if slot and slot not in slots:
        slots.append(slot)
    return slots


def _candidate_primary_skill(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """The main skill PoB measured with the candidate equipped (compact identity)."""
    identity = candidate.get("primary_skill") or {}
    if not isinstance(identity, Mapping) or not identity:
        return {}
    row = {
        "name": identity.get("skill_name") or "",
        "skill_id": identity.get("skill_id") or "",
        "group": identity.get("index"),
        "source": identity.get("source") or "gem",
        "damage_owner": identity.get("damage_owner") or "PLAYER",
        "output_table": identity.get("output_table") or "mainOutput",
        "actor_id": identity.get("actor_id") or "",
        "actor_skill": identity.get("actor_skill") or "",
    }
    if candidate.get("primary_skill_repinned"):
        row["repinned"] = True
    if candidate.get("primary_skill_changed"):
        row["changed"] = True
    return row


def _offense_measurement_state(recommendation: Mapping[str, Any], outcome: Mapping[str, Any]) -> str:
    """MEASURED / MEASURED_ZERO / ESTIMATED / UNMEASURED / ... for the primary damage axis."""
    profile = recommendation.get("metric_profile") or {}
    offense = profile.get("primary_offense") if isinstance(profile, Mapping) else None
    if isinstance(offense, Mapping) and offense.get("delta_kind"):
        return str(offense["delta_kind"])
    for row in outcome.get("primary_deltas") or []:
        if isinstance(row, Mapping) and row.get("key") == "primary_offense":
            return str(row.get("delta_kind") or "MEASURED")
    return ""


def _identity_row(identity: Mapping[str, Any]) -> dict[str, Any]:
    if not identity:
        return {}
    return {
        "name": identity.get("skill_name") or identity.get("name") or "",
        "skill_id": identity.get("skill_id") or "",
        "group": identity.get("index", identity.get("group")),
        "source": identity.get("source") or "gem",
        "stat_set": identity.get("stat_set") or "",
        "stat_set_index": identity.get("stat_set_index"),
        "stat_set_count": identity.get("stat_set_count"),
        "stat_set_key_hash": _key_hash(identity.get("stat_set_key")),
        "part_name": identity.get("part_name") or "",
        "part_index": identity.get("part_index"),
        "part_count": identity.get("part_count"),
        "part_key_hash": _key_hash(identity.get("part_key")),
        "stage_count": identity.get("stage_count"),
        "stage_explicit": bool(identity.get("stage_explicit")),
        "calculation_mode": identity.get("calculation_mode") or "",
        "damage_owner": identity.get("damage_owner") or "PLAYER",
        "output_table": identity.get("output_table") or "mainOutput",
        "actor_id": identity.get("actor_id") or "",
        "actor_skill": identity.get("actor_skill") or "",
    }


def _skill_key(identity: Mapping[str, Any]) -> tuple:
    source = str(identity.get("source") or "")
    item_kind = bool(source) and source != "gem"
    return (
        identity.get("skill_id"),
        item_kind,
        identity.get("slot") or "",
        identity.get("stat_set_key") or identity.get("stat_set") or "",
        identity.get("damage_owner") or "PLAYER",
        identity.get("output_table") or "mainOutput",
        identity.get("actor_id") or "",
        identity.get("actor_skill") or "",
    )


def _key_hash(value: Any) -> str:
    text = str(value or "")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16] if text else ""


def _comparison_identity(
    recommendation: Mapping[str, Any],
    primary: Mapping[str, Any],
    outcome: Mapping[str, Any],
) -> dict[str, Any]:
    """Which skill was measured before/after, whether they are the same, and why not measured."""
    baseline = (recommendation.get("baseline") or {}).get("primary_skill") or {}
    candidate_block = recommendation.get("candidate") or {}
    candidate = candidate_block.get("primary_skill") or {}
    if not baseline and not candidate:
        return {}
    field_before = str(primary.get("pob_field") or recommendation.get("primary_metric_field") or "")
    candidate_primary_metric = recommendation.get("candidate_primary_metric") or {}
    field_after = str(candidate_primary_metric.get("pob_field") or recommendation.get("primary_metric_field") or field_before)
    offense = (recommendation.get("metric_profile") or {}).get("primary_offense") or {}
    part_guard = selected_part_guard_state(dict(baseline), dict(candidate))
    return {
        "baseline_skill": _identity_row(baseline),
        "candidate_skill": _identity_row(candidate),
        "semantic_identity_same": bool(
            baseline
            and candidate
            and _skill_key(baseline) == _skill_key(candidate)
            and not part_guard
            and not candidate_block.get("primary_skill_changed")
        ),
        "part_before": baseline.get("part_name") or ("WHOLE" if baseline.get("part_count") == 0 else ""),
        "part_after": candidate.get("part_name") or ("WHOLE" if candidate.get("part_count") == 0 else ""),
        "same_semantic_part": bool(baseline and candidate and not part_guard
                                   and _skill_key(baseline) == _skill_key(candidate)
                                   and not candidate_block.get("primary_skill_changed")),
        "part_guard_state": part_guard,
        "stat_set_before": baseline.get("stat_set") or "",
        "stat_set_after": candidate.get("stat_set") or "",
        "stat_set_key_before": _key_hash(baseline.get("stat_set_key")),
        "stat_set_key_after": _key_hash(candidate.get("stat_set_key")),
        "stage_config_before": {"count": baseline.get("stage_count"), "explicit": bool(baseline.get("stage_explicit"))},
        "stage_config_after": {"count": candidate.get("stage_count"), "explicit": bool(candidate.get("stage_explicit"))},
        "calculation_mode_before": baseline.get("calculation_mode") or "",
        "calculation_mode_after": candidate.get("calculation_mode") or "",
        "primary_skill_repinned": bool(candidate_block.get("primary_skill_repinned")),
        "metric_field_before": field_before,
        "metric_field_after": field_after,
        "damage_owner_before": baseline.get("damage_owner") or primary.get("metric_source") or "PLAYER",
        "damage_owner_after": candidate.get("damage_owner") or "PLAYER",
        "output_table_before": baseline.get("output_table") or primary.get("output_table") or "mainOutput",
        "output_table_after": candidate.get("output_table") or "mainOutput",
        "semantic_quantity_before": primary.get("semantic_quantity") or "",
        "semantic_quantity_after": candidate_primary_metric.get("semantic_quantity") or primary.get("semantic_quantity") or "",
        "metric_scope_before": primary.get("metric_scope") or "",
        "metric_scope_after": candidate_primary_metric.get("metric_scope") or primary.get("metric_scope") or "",
        "metric_identity_same": bool(field_before) and field_before == field_after and all(
            not candidate_primary_metric or primary.get(k) == candidate_primary_metric.get(k)
            for k in ("metric_source", "output_table", "semantic_quantity", "metric_scope", "ailment")
        ),
        "confidence": primary.get("confidence") or "",
        "measurement_state": offense.get("delta_kind") or "",
        "coverage_state": offense.get("coverage_state") or "",
        "fallback_reason": primary.get("reason") or "",
        "uncertainty_reasons": [
            item.get("code") for item in outcome.get("evaluation_quality_reasons") or [] if isinstance(item, Mapping)
        ],
    }


def _state_integrity(result: Mapping[str, Any], recommendation: Mapping[str, Any]) -> dict[str, Any]:
    """Candidate-transaction integrity: which skill/loadout was measured at each phase."""
    phases = {name: recommendation.get(name) or {} for name in ("baseline", "candidate", "restored")}
    if not any(phase.get("semantic") or phase.get("primary_skill") for phase in phases.values()):
        return {}
    row: dict[str, Any] = {}
    for name, phase in phases.items():
        semantic = phase.get("semantic") or {}
        row[f"{name}_primary_identity"] = _identity_row(phase.get("primary_skill") or {})
        row[f"{name}_loadout"] = semantic.get("loadout") or ""
        row[f"{name}_item_set"] = semantic.get("item_set") or ""
        row[f"stat_set_{name}"] = semantic.get("stat_set") or ""
    row["full_dps_state_before"] = list((phases["baseline"].get("semantic") or {}).get("full_dps") or [])
    row["full_dps_state_restore"] = list((phases["restored"].get("semantic") or {}).get("full_dps") or [])
    restore = recommendation.get("restore") or {}
    restore_pass = restore.get("pass")
    if restore_pass is True:
        row["restore_status"] = "OK"
    elif restore_pass is False:
        row["restore_status"] = "FAILED"
    else:
        row["restore_status"] = str(restore.get("status") or "DEFERRED")
    row["recovery_used"] = bool((result.get("state_integrity") or {}).get("recovery_used"))
    return row


def build_item_diagnostics(
    result: Mapping[str, Any] | None,
    model: Mapping[str, Any] | None,
    *,
    selected_outcome: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the public CP-07 diagnostic payload from explicit fields only."""
    result = result or {}
    model = model or {}
    recommendation = result.get("recommendation") or {}
    outcome = selected_outcome or model.get("evaluation_outcome") or recommendation.get("evaluation_outcome") or {}
    raw_input = result.get("raw_input") or {}
    metadata = result.get("metadata") or {}
    request_meta = result.get("request_meta") or {}
    primary = result.get("primary_metric") or {}
    baseline = recommendation.get("baseline") or {}

    request = _pick(
        request_meta,
        ("request_id", "kind", "generation", "cache_hit", "lifecycle_terminal_state", "terminal_state"),
    )
    timings = request_meta.get("timings") or result.get("timings") or outcome.get("timings") or {}
    if timings:
        request["timings"] = _safe(timings)

    build = {
        "fingerprint": _safe(
            baseline.get("fingerprint_hash")
            or recommendation.get("baseline_fingerprint")
            or request_meta.get("build_fingerprint")
            or ""
        ),
        "config": _pick(
            {**model, **request_meta},
            ("context", "loadout_name", "item_set_name", "value_profile", "profile_indicator"),
        ),
        "selected_main_skill": _safe(
            primary.get("skill_name") or primary.get("selected_skill") or result.get("selected_main_skill") or ""
        ),
        "primary_metric": _pick(
            primary,
            ("pob_field", "source_field", "metric_source", "output_table", "metric_path",
             "semantic_quantity", "metric_scope", "value_type", "ailment", "raw_source_fields",
             "label", "confidence", "reason", "provenance", "full_dps_status"),
        ),
        "native_damage_discovery": _safe(recommendation.get("native_damage_discovery") or result.get("native_damage_discovery") or {}),
        "metric_selection_reason": _safe(primary.get("reason") or ""),
        "primary_skill": _safe(primary.get("primary_skill") or {}),
        "candidate_primary_skill": _safe(
            _candidate_primary_skill(recommendation.get("candidate") or {})
        ),
        "offense_measurement_state": _safe(_offense_measurement_state(recommendation, outcome)),
        "comparison": _safe(_comparison_identity(recommendation, primary, outcome)),
        "state_integrity": _safe(_state_integrity(result, recommendation)),
        "socket_normalization": _safe(
            _pick(
                result.get("socket_normalization") or {},
                (
                    "enabled",
                    "candidate_normalized",
                    "candidate_removed_count",
                    "baseline_normalized_slots",
                    "baseline_removed_counts",
                ),
            )
        ),
    }
    build = {key: value for key, value in build.items() if value not in (None, "", [], {})}

    item = {
        "raw_text": _safe(raw_input.get("raw_text") or raw_input.get("text") or ""),
        "content_hash": _safe(raw_input.get("content_hash") or ""),
        "parsed": _pick(metadata, ("name", "base_type", "rarity", "item_class", "type")),
        "legal_replacement_slots": _legal_slots(result, model),
        "selected_replacement_slot": _safe(outcome.get("replacement_slot") or ""),
        "replacing_item": _safe(outcome.get("replacing_item") or ""),
        "replacing_empty_slot": bool(outcome.get("replacing_empty_slot", False)),
    }
    item = {
        key: value
        for key, value in item.items()
        if value not in (None, "", [], {}) or key == "replacing_empty_slot"
    }

    evaluation = _pick(outcome, _OUTCOME_FIELDS)
    resistances = evaluation.pop("resistances", None)
    gaps = {
        "warnings": _safe(result.get("warnings") or recommendation.get("warnings") or []),
        "unsupported_or_unmodeled": _safe(outcome.get("unsupported_or_unmodeled") or []),
    }
    gaps = {key: value for key, value in gaps.items() if value}

    error_source = result.get("error") or {}
    if not isinstance(error_source, Mapping):
        error_source = {"message": str(error_source)}
    error = _pick(error_source, ("code", "type", "error_type", "message", "timeout_ms"))

    payload: dict[str, Any] = {
        "diagnostics_schema_version": DIAGNOSTICS_SCHEMA_VERSION,
        "exilelens": {"version": __version__, "git_commit": git_commit()},
        "pob": {"supported_commit": SUPPORTED_POB_HEAD},
        "request": request,
        "build": build,
        "item": item,
        "evaluation": evaluation,
        "resistances": _safe(resistances or []),
        "model_gaps": gaps,
    }
    if error:
        payload["error"] = error
    return _safe(payload)


def serialize_item_diagnostics(
    result: Mapping[str, Any] | None,
    model: Mapping[str, Any] | None,
    *,
    selected_outcome: Mapping[str, Any] | None = None,
) -> str:
    return json.dumps(
        build_item_diagnostics(result, model, selected_outcome=selected_outcome),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
