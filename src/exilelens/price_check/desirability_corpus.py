"""MARKET-03 — the human desirability corpus, and the metrics that grade against it.

The MARKET-02F truth file labelled at most three ``expected_drivers`` per item. That
schema encodes the very cap MARKET-03 removes, so it cannot grade anchor/flexible/dead
roles and is retired for MARKET-03 grading.

This module owns the replacement. Two rules govern it, and both are enforced in code
rather than by convention:

**Proposed labels are not authority.** The agent may prepare labels from raw item text
and domain knowledge, but they carry ``review_status = PROPOSED`` until a human
reviews them. :func:`gate_metrics` refuses to score anything but ``APPROVED`` rows, so
an unreviewed corpus produces "not yet gradeable", never a passing grade.

**Labels are never derived from implementation output.** Nothing in this module reads
the desirability engine; it only compares an engine result handed to it against labels
written independently.

Offline only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

CORPUS_DIR = Path("fixtures/market/corpus_03")

#: Roles a human may assign. Same vocabulary as the engine's MarketRole, deliberately
#: re-declared so a change to the engine cannot silently redefine the ground truth.
LABEL_ROLES = ("ANCHOR", "FLEXIBLE", "OPTIONAL", "INFORMATIONAL", "DEAD")
LABEL_BASE_ROLES = ("NONE", "CATEGORY", "FAMILY", "EXACT")
LABEL_DIRECTIONS = ("HIGHER_BETTER", "LOWER_BETTER", "EXACT", "BOOLEAN")
LABEL_RANGE_POLICIES = (
    "TIER_FLOOR",
    "ROLL_SENSITIVE",
    "BREAKPOINT",
    "EXACT",
    "PSEUDO_AGGREGATE",
    "DEGRADED_NO_TIER",
)

#: Roles that assert the characteristic is worth money. Used by the recall metric.
MATERIAL_ROLES = frozenset({"ANCHOR", "FLEXIBLE"})


class ReviewStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class ModLabel:
    text: str
    family: str
    role: str
    direction: str = "HIGHER_BETTER"
    range_policy: str = "DEGRADED_NO_TIER"
    reason: str = ""

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ModLabel:
        return cls(
            text=str(payload.get("text") or ""),
            family=str(payload.get("family") or ""),
            role=str(payload.get("role") or ""),
            direction=str(payload.get("direction") or "HIGHER_BETTER"),
            range_policy=str(payload.get("range_policy") or "DEGRADED_NO_TIER"),
            reason=str(payload.get("reason") or ""),
        )


@dataclass(frozen=True)
class ItemLabel:
    item_id: str
    cohort: int
    review_status: ReviewStatus
    item_class: str
    base_role: str
    mods: tuple[ModLabel, ...]
    base_role_reason: str = ""
    pseudo_preference: Mapping[str, str] = field(default_factory=dict)
    proposed_by: str = ""
    reviewed_by: str = ""
    notes: str = ""

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ItemLabel:
        return cls(
            item_id=str(payload.get("id") or ""),
            cohort=int(payload.get("cohort") or 0),
            review_status=ReviewStatus(str(payload.get("review_status") or "PROPOSED")),
            item_class=str(payload.get("item_class") or ""),
            base_role=str(payload.get("base_role") or ""),
            base_role_reason=str(payload.get("base_role_reason") or ""),
            mods=tuple(ModLabel.from_dict(row) for row in payload.get("mods") or ()),
            pseudo_preference=dict(payload.get("pseudo_preference") or {}),
            proposed_by=str(payload.get("proposed_by") or ""),
            reviewed_by=str(payload.get("reviewed_by") or ""),
            notes=str(payload.get("notes") or ""),
        )

    def families_with_role(self, *roles: str) -> frozenset[str]:
        wanted = set(roles)
        return frozenset(row.family for row in self.mods if row.role in wanted and row.family)


class CorpusValidationError(ValueError):
    """A label file is malformed. Raised eagerly — a bad label silently skewing a gate
    is worse than a failed load."""


def validate_label(payload: Mapping[str, Any]) -> list[str]:
    """Structural problems with one label row, as human-readable strings."""
    problems: list[str] = []
    if not str(payload.get("id") or "").strip():
        problems.append("missing id")
    status = str(payload.get("review_status") or "")
    if status not in {row.value for row in ReviewStatus}:
        problems.append(f"unknown review_status {status!r}")
    base_role = str(payload.get("base_role") or "")
    if base_role not in LABEL_BASE_ROLES:
        problems.append(f"unknown base_role {base_role!r}")
    if status == ReviewStatus.APPROVED.value and not str(payload.get("reviewed_by") or "").strip():
        problems.append("APPROVED without reviewed_by")
    mods = payload.get("mods") or ()
    if not mods:
        problems.append("no mod labels")
    for index, row in enumerate(mods):
        where = f"mods[{index}]"
        if str(row.get("role") or "") not in LABEL_ROLES:
            problems.append(f"{where}: unknown role {row.get('role')!r}")
        if str(row.get("direction") or "HIGHER_BETTER") not in LABEL_DIRECTIONS:
            problems.append(f"{where}: unknown direction {row.get('direction')!r}")
        if str(row.get("range_policy") or "DEGRADED_NO_TIER") not in LABEL_RANGE_POLICIES:
            problems.append(f"{where}: unknown range_policy {row.get('range_policy')!r}")
        if not str(row.get("text") or "").strip():
            problems.append(f"{where}: missing mod text")
    return problems


def load_labels(path: Path) -> tuple[ItemLabel, ...]:
    """Read one cohort file. Raises on any structural problem."""
    labels: list[ItemLabel] = []
    problems: list[str] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        payload = json.loads(line)
        found = validate_label(payload)
        if found:
            problems.extend(f"{path.name}:{number}: {issue}" for issue in found)
            continue
        labels.append(ItemLabel.from_dict(payload))
    if problems:
        raise CorpusValidationError("; ".join(problems))
    return tuple(labels)


def load_corpus(directory: Path | None = None) -> tuple[ItemLabel, ...]:
    """Every cohort file in the corpus directory, in cohort order."""
    root = directory or CORPUS_DIR
    if not root.exists():
        return ()
    labels: list[ItemLabel] = []
    for path in sorted(root.glob("cohort_*.jsonl")):
        labels.extend(load_labels(path))
    return tuple(sorted(labels, key=lambda row: (row.cohort, row.item_id)))


def approved(labels: Iterable[ItemLabel]) -> tuple[ItemLabel, ...]:
    return tuple(row for row in labels if row.review_status is ReviewStatus.APPROVED)


@dataclass(frozen=True)
class DesirabilityMetrics:
    """The brief's section 45 gate, plus the counts behind each number."""

    graded_items: int
    anchor_true_positives: int = 0
    anchor_predicted: int = 0
    anchor_labelled: int = 0
    material_labelled: int = 0
    material_recalled: int = 0
    dead_labelled: int = 0
    dead_selected: int = 0
    base_role_correct: int = 0
    base_role_graded: int = 0

    @property
    def anchor_precision(self) -> float | None:
        return None if not self.anchor_predicted else self.anchor_true_positives / self.anchor_predicted

    @property
    def anchor_recall(self) -> float | None:
        return None if not self.anchor_labelled else self.anchor_true_positives / self.anchor_labelled

    @property
    def material_mod_recall(self) -> float | None:
        return None if not self.material_labelled else self.material_recalled / self.material_labelled

    @property
    def dead_mod_selection_rate(self) -> float | None:
        return None if not self.dead_labelled else self.dead_selected / self.dead_labelled

    @property
    def base_role_accuracy(self) -> float | None:
        return None if not self.base_role_graded else self.base_role_correct / self.base_role_graded

    def gate_failures(self) -> tuple[str, ...]:
        """Brief section 45 thresholds. An ungradeable metric is a failure, not a pass."""
        if not self.graded_items:
            return ("no APPROVED labels to grade against",)
        failures: list[str] = []
        if self.material_mod_recall is None or self.material_mod_recall < 0.90:
            failures.append(f"material-mod recall {_pct(self.material_mod_recall)} < 90%")
        if self.anchor_precision is None or self.anchor_precision < 0.90:
            failures.append(f"anchor precision {_pct(self.anchor_precision)} < 90%")
        rate = self.dead_mod_selection_rate
        if rate is not None and rate > 0.05:
            failures.append(f"dead-mod selection {_pct(rate)} > 5%")
        return tuple(failures)

    @property
    def passes(self) -> bool:
        return not self.gate_failures()

    def to_dict(self) -> dict[str, Any]:
        return {
            "graded_items": self.graded_items,
            "anchor_precision": self.anchor_precision,
            "anchor_recall": self.anchor_recall,
            "material_mod_recall": self.material_mod_recall,
            "dead_mod_selection_rate": self.dead_mod_selection_rate,
            "base_role_accuracy": self.base_role_accuracy,
            "passes": self.passes,
            "gate_failures": list(self.gate_failures()),
        }


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


@dataclass(frozen=True)
class Prediction:
    """What the engine said about one item, reduced to families per role."""

    item_id: str
    base_role: str
    roles: Mapping[str, frozenset[str]]

    def families_with_role(self, *roles: str) -> frozenset[str]:
        out: set[str] = set()
        for role in roles:
            out |= set(self.roles.get(role, frozenset()))
        return frozenset(out)


def score(
    labels: Sequence[ItemLabel],
    predictions: Mapping[str, Prediction],
    *,
    require_approved: bool = True,
) -> DesirabilityMetrics:
    """Grade predictions against labels.

    ``require_approved`` defaults to True and must stay that way for the product gate;
    a dry run over PROPOSED labels is useful while preparing a cohort for review, and
    :func:`gate_metrics` is the entry point that refuses to relax it.
    """
    rows = approved(labels) if require_approved else tuple(labels)
    anchor_tp = anchor_pred = anchor_lab = 0
    material_lab = material_rec = 0
    dead_lab = dead_sel = 0
    base_ok = base_graded = 0
    graded = 0

    for label in rows:
        prediction = predictions.get(label.item_id)
        if prediction is None:
            continue
        graded += 1

        labelled_anchors = label.families_with_role("ANCHOR")
        predicted_anchors = prediction.families_with_role("ANCHOR")
        anchor_lab += len(labelled_anchors)
        anchor_pred += len(predicted_anchors)
        anchor_tp += len(labelled_anchors & predicted_anchors)

        labelled_material = label.families_with_role(*MATERIAL_ROLES)
        predicted_material = prediction.families_with_role(*MATERIAL_ROLES)
        material_lab += len(labelled_material)
        material_rec += len(labelled_material & predicted_material)

        labelled_dead = label.families_with_role("DEAD")
        dead_lab += len(labelled_dead)
        dead_sel += len(labelled_dead & predicted_material)

        if label.base_role:
            base_graded += 1
            base_ok += int(label.base_role == prediction.base_role)

    return DesirabilityMetrics(
        graded_items=graded,
        anchor_true_positives=anchor_tp,
        anchor_predicted=anchor_pred,
        anchor_labelled=anchor_lab,
        material_labelled=material_lab,
        material_recalled=material_rec,
        dead_labelled=dead_lab,
        dead_selected=dead_sel,
        base_role_correct=base_ok,
        base_role_graded=base_graded,
    )


def gate_metrics(
    labels: Sequence[ItemLabel], predictions: Mapping[str, Prediction]
) -> DesirabilityMetrics:
    """The product-gate entry point. APPROVED labels only, no override."""
    return score(labels, predictions, require_approved=True)


def review_summary(labels: Iterable[ItemLabel]) -> dict[str, Any]:
    """Cohort-by-cohort review progress, so it is obvious what still needs a human."""
    by_cohort: dict[int, dict[str, int]] = {}
    for label in labels:
        bucket = by_cohort.setdefault(label.cohort, {row.value: 0 for row in ReviewStatus})
        bucket[label.review_status.value] += 1
    total = {row.value: 0 for row in ReviewStatus}
    for bucket in by_cohort.values():
        for key, value in bucket.items():
            total[key] += value
    return {
        "cohorts": {str(key): by_cohort[key] for key in sorted(by_cohort)},
        "total": total,
        "gradeable": total[ReviewStatus.APPROVED.value],
    }
