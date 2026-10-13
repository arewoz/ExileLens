"""Local, privacy-safe filter feedback capture and replay (FILTER-08D). No telemetry, no network.

A ``FeedbackCase`` records "for this build, this profile and this item I expected SHOW / HIDE / UNSURE". It stores:
  * the item's observable properties (base, class, rarity, item level, quality, tier) — never an account, character or file path;
  * a one-way hash of the needs snapshot (build identity) and, optionally, the build label;
  * the rules SHA (header-independent) the user saw, so a replay can say whether the filter changed since;
  * the decision observed at capture time and the user's expectation.

Cases live in the local app-data directory (``filter_feedback/``) as one JSON file each, or in any directory you point at (a test
fixture directory turns a case into a permanent regression). Nothing leaves the machine unless the user copies the file.
``replay`` regenerates the filter for a needs snapshot and reports MATCHES / MISMATCH / UNSURE_RECORDED plus whether the rules changed.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from exilelens.filters.build_needs import BuildNeedsSnapshot
from exilelens.filters.intel_generate import filter_body_sha256, generate
from exilelens.filters.preview import PreviewItem, preview_decision

EXPECTATIONS = ("SHOW", "HIDE", "UNSURE")
# FILTER-08E: the five labels a player gives a natural drop. Each maps onto the SHOW / HIDE / UNSURE expectation used for replay.
ANNOTATIONS = {"SHOULD SHOW": "SHOW", "SHOULD HIDE": "HIDE", "UNSURE": "UNSURE", "VALUABLE MISS": "SHOW", "NOISE": "HIDE"}
ITEM_FIELDS = ("name", "category", "item_class", "base_type", "rarity", "item_level", "quality", "unidentified_item_tier", "waystone_tier",
               "base_energy_shield", "base_armour", "base_evasion")
SCHEMA = 2
SUPPORTED_SCHEMAS = (1, 2)


def feedback_dir() -> Path:
    """EXILELENS_FEEDBACK_DIR when set, otherwise ``<app data>/filter_feedback`` (created only when a case is saved)."""
    explicit = os.environ.get("EXILELENS_FEEDBACK_DIR")
    if explicit:
        return Path(explicit)
    from exilelens.app.settings import app_data_dir
    return app_data_dir() / "filter_feedback"


def needs_identity(needs: BuildNeedsSnapshot) -> str:
    return hashlib.sha256(needs.to_json().encode("utf-8")).hexdigest()[:24]


@dataclass(frozen=True)
class FeedbackCase:
    id: str
    schema: int
    captured_at: str
    profile: str
    needs_identity: str
    item: dict
    expected: str
    observed: str
    observed_rule: str
    rules_sha: str
    note: str = ""
    build_label: str = ""
    # schema 2 (FILTER-08E natural-drop logging): what the user saw and how they labelled it. Still local; nothing here identifies a person.
    annotation: str = ""            # one of ANNOTATIONS (empty for schema-1 cases)
    provenance: str = ""            # the rule's own explanation shown for the item
    needs_sha256: str = ""          # full hash of the Build Intelligence snapshot the filter was generated from
    data_state: str = ""            # CURRENT / STALE SNAPSHOT / ... at capture time
    coverage: str = ""              # personalization coverage of the snapshot

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=1, sort_keys=True) + "\n"

    @staticmethod
    def from_json(text: str) -> "FeedbackCase":
        data = json.loads(text)
        if data.get("schema") not in SUPPORTED_SCHEMAS:
            raise ValueError(f"unsupported feedback schema {data.get('schema')!r}")
        return FeedbackCase(**data)

    def preview_item(self) -> PreviewItem:
        return PreviewItem(**self.item)


def capture(needs: BuildNeedsSnapshot, profile: str, item: PreviewItem, expected: str, *, note: str = "", include_label: bool = False,
            now: datetime | None = None) -> FeedbackCase:
    """``expected`` is SHOW / HIDE / UNSURE, or one of the five ANNOTATIONS (which also sets the expectation)."""
    annotation = expected if expected in ANNOTATIONS else ""
    expected = ANNOTATIONS.get(expected, expected)
    if expected not in EXPECTATIONS:
        raise ValueError(f"expected must be one of {EXPECTATIONS} or an annotation {tuple(ANNOTATIONS)}")
    result = generate(needs, profile, intel=True)
    decision = preview_decision(result.rules, item)
    fields = {name: getattr(item, name) for name in ITEM_FIELDS}
    identity = needs_identity(needs)
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    digest = hashlib.sha1(json.dumps([identity, profile, fields, expected], sort_keys=True).encode("utf-8")).hexdigest()[:8]
    return FeedbackCase(f"{stamp}-{digest}", SCHEMA, stamp, profile, identity, fields, expected, "HIDE" if decision.hidden else "SHOW",
                        decision.rule_name, filter_body_sha256(result.text), note.strip()[:500], needs.label if include_label else "",
                        annotation, decision.provenance, hashlib.sha256(needs.to_json().encode("utf-8")).hexdigest(),
                        result.data_status.state.value if result.data_status else "", needs.coverage.value)


def save(case: FeedbackCase, directory: Path | None = None) -> Path:
    target = Path(directory) if directory else feedback_dir()
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"{case.id}.json"
    path.write_text(case.to_json(), encoding="utf-8")
    return path


def load_all(directory: Path | None = None) -> list[FeedbackCase]:
    target = Path(directory) if directory else feedback_dir()
    if not target.exists():
        return []
    return [FeedbackCase.from_json(p.read_text(encoding="utf-8")) for p in sorted(target.glob("*.json"))]


@dataclass(frozen=True)
class Replay:
    case_id: str
    verdict: str                 # MATCHES | MISMATCH | UNSURE_RECORDED | WRONG_BUILD
    expected: str
    now: str                     # SHOW | HIDE
    rule: str
    rules_changed: bool          # the filter rules differ from the ones the user saw
    explanation: str


def replay(case: FeedbackCase, needs: BuildNeedsSnapshot) -> Replay:
    if needs_identity(needs) != case.needs_identity:
        return Replay(case.id, "WRONG_BUILD", case.expected, "", "", False,
                      "The supplied needs snapshot is not the build this case was captured for (identity hash differs).")
    result = generate(needs, case.profile, intel=True)
    decision = preview_decision(result.rules, case.preview_item())
    now = "HIDE" if decision.hidden else "SHOW"
    changed = filter_body_sha256(result.text) != case.rules_sha
    if case.expected == "UNSURE":
        verdict, why = "UNSURE_RECORDED", "recorded as unsure: shown for review, never a pass/fail"
    elif now == case.expected:
        verdict, why = "MATCHES", "the filter now behaves as expected"
    else:
        verdict, why = "MISMATCH", f"expected {case.expected} but the filter {now}s it (rule {decision.rule_name})"
    return Replay(case.id, verdict, case.expected, now, decision.rule_name, changed, why)


def replay_all(cases: Iterable[FeedbackCase], snapshots: dict[str, BuildNeedsSnapshot]) -> list[Replay]:
    by_identity = {needs_identity(n): n for n in snapshots.values()}
    out = []
    for case in cases:
        needs = by_identity.get(case.needs_identity)
        out.append(replay(case, needs) if needs else Replay(case.id, "WRONG_BUILD", case.expected, "", "", False,
                                                           "no stored needs snapshot has this identity"))
    return out


def natural_drop_corpus(cases: Iterable[FeedbackCase]) -> list[dict]:
    """The labelled items as a build-independent corpus row list (input to a later natural-drop corpus). Local; contains no build identity
    beyond the one-way hash, so rows can be pooled across sessions without exposing a build."""
    rows = []
    for case in cases:
        if case.expected == "UNSURE":
            continue
        rows.append({"item": case.item, "expected": case.expected, "annotation": case.annotation or case.expected, "profile": case.profile,
                     "observed": case.observed, "matched_rule": case.observed_rule, "rules_sha": case.rules_sha, "needs_identity": case.needs_identity})
    return rows
