"""P1.1c — More Info hierarchy: deterministic presentation-layer regression
coverage for the normal/Advanced split, the decision-relevant resist
summary, and the Advanced disclosure's collapse/expand behavior.

Presentation-only. Most tests are plain dict-fixture unit tests (no PoB
worker). A few need a real (offscreen) Qt widget to prove the disclosure
actually shows/hides and the ring selector still identifies the best socket
without leaking raw node ids -- these follow the same
`QT_QPA_PLATFORM=offscreen` pattern already used by
`public_tests/test_pob_path_state_consistency.py`.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from exilelens.items.more_info import (
    ADVANCED_SECTION_IDS,
    MORE_INFO_SECTION_ORDER,
    _resist_summary,
    _resists_section,
    build_more_info,
)

pytestmark = pytest.mark.itemcheck


# ----------------------------------------------------------------- resist summary


def _resist(element: str, state: str, severity: str, current: float | None, candidate: float | None) -> dict[str, object]:
    return {"element": element, "state": state, "severity": severity, "current": current, "candidate": candidate}


def test_capped_both_sides_collapses_to_capped_arrow_capped() -> None:
    summary, warning = _resist_summary(_resist("fire", "CAPPED_STAYS_CAPPED", "info", 75, 75))
    assert summary == "capped → capped"
    assert warning is False


def test_over_cap_reduced_still_capped_also_collapses() -> None:
    summary, warning = _resist_summary(_resist("cold", "OVER_CAP_REDUCED_BUT_STILL_CAPPED", "info", 90, 78))
    assert summary == "capped → capped"
    assert warning is False


def test_cap_reached_shows_the_improving_number_then_capped() -> None:
    summary, warning = _resist_summary(_resist("lightning", "CAP_REACHED", "critical_positive", 60, 75))
    assert summary == "60 → capped"
    assert warning is False


def test_cap_lost_shows_capped_then_the_real_number_and_warns() -> None:
    summary, warning = _resist_summary(_resist("fire", "CAP_LOST", "critical", 75, 62))
    assert summary == "capped → 62"
    assert warning is True


def test_below_cap_worsened_shows_real_numbers_and_warns() -> None:
    """The coordinator's exact reference case: Chaos 15 -> 0."""
    summary, warning = _resist_summary(_resist("chaos", "BELOW_CAP_WORSENED", "high", 15, 0))
    assert summary == "15 → 0"
    assert warning is True


def test_below_cap_improved_shows_real_numbers_no_warning() -> None:
    summary, warning = _resist_summary(_resist("chaos", "BELOW_CAP_IMPROVED", "positive", 15, 30))
    assert summary == "15 → 30"
    assert warning is False


def test_resists_section_matches_coordinators_worked_example() -> None:
    """Fire/Cold/Lightning capped -> capped, Chaos 15 -> 0 with a warning --
    derived from the real data model, not hard-coded in the section builder."""
    outcome = {
        "resistances": [
            _resist("fire", "CAPPED_STAYS_CAPPED", "info", 75, 75),
            _resist("cold", "CAPPED_STAYS_CAPPED", "info", 75, 75),
            _resist("lightning", "CAPPED_STAYS_CAPPED", "info", 75, 75),
            _resist("chaos", "BELOW_CAP_WORSENED", "high", 15, 0),
        ],
        "all_deltas": [],
    }
    section = _resists_section(outcome)
    assert section is not None
    rows = section["resist_rows"]
    assert [row["element"] for row in rows] == ["Fire", "Cold", "Lightning", "Chaos"]
    assert rows[0]["summary"] == "capped → capped" and rows[0]["warning"] is False
    assert rows[3]["summary"] == "15 → 0" and rows[3]["warning"] is True
    assert rows[3]["marker"] == "⚠"
    assert rows[0]["marker"] == ""
    # No raw engine state strings ("CAPPED_STAYS_CAPPED", "BELOW_CAP_WORSENED")
    # leak into the rendered text.
    joined = " ".join(section["lines"])
    assert "CAPPED" not in joined
    assert "BELOW_CAP" not in joined


def test_resist_with_no_data_produces_no_row() -> None:
    summary, _ = _resist_summary(_resist("chaos", "UNKNOWN", "unknown", None, None))
    assert summary == ""


# --------------------------------------------------------------- normal / advanced


def test_advanced_section_ids_are_the_technical_provenance_group() -> None:
    assert ADVANCED_SECTION_IDS == {"flexibility", "score_drivers", "damage_reference", "native_components"}


def test_normal_sections_not_marked_advanced() -> None:
    normal = {"verdict_header", "key_impact", "offense", "defense", "resists", "why_verdict", "unmodeled"}
    assert normal.isdisjoint(ADVANCED_SECTION_IDS)


def test_section_order_puts_key_impact_before_offense_and_defense() -> None:
    order = list(MORE_INFO_SECTION_ORDER)
    assert order.index("key_impact") < order.index("offense") < order.index("defense")


def test_section_order_puts_all_normal_sections_before_all_advanced_sections() -> None:
    order = list(MORE_INFO_SECTION_ORDER)
    normal_positions = [order.index(sid) for sid in order if sid not in ADVANCED_SECTION_IDS]
    advanced_positions = [order.index(sid) for sid in order if sid in ADVANCED_SECTION_IDS]
    assert max(normal_positions) < min(advanced_positions)


def test_build_more_info_splits_sections_consistently_with_advanced_ids() -> None:
    outcome = {
        "verdict": "SIDEGRADE",
        "verdict_label": "SIDEGRADE",
        "final_score": 50.0,
        "evaluation_quality": "FULL",
        "quality_label": "",
        "verdict_reason": "Net score +0.0 against the current item.",
        "guardrails_applied": [],
        "critical_tradeoffs": [],
        "resistances": [_resist("chaos", "BELOW_CAP_WORSENED", "high", 15, 0)],
        "all_deltas": [{"key": "primary_offense", "label": "Damage", "percent_delta": -4.9, "direction": "negative"}],
        "score_contributors": [{"key": "res_flex", "contribution": -0.4}],
        "unsupported_or_unmodeled": [],
        "evaluation_quality_reasons": [],
    }
    model = {"item_name": "Helmet", "impact_rows": [], "evaluation_outcome": outcome, "primary_metric": {}, "native_damage_discovery": {}}
    block = build_more_info(model, outcome=outcome)
    section_ids = block["section_ids"]
    assert "resists" in section_ids  # normal
    assert "flexibility" in section_ids  # advanced (res_flex contributor present)
    for section in block["sections"]:
        if section["id"] in ADVANCED_SECTION_IDS:
            assert section["id"] in {"flexibility", "score_drivers", "damage_reference", "native_components"}


# ------------------------------------------------------------- drawer behavior


def _make_app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _helmet_downgrade_block():
    outcome = {
        "verdict": "MEANINGFUL_DOWNGRADE",
        "verdict_label": "MEANINGFUL DOWNGRADE",
        "final_score": 22.0,
        "evaluation_quality": "FULL",
        "quality_label": "",
        "verdict_reason": "Net score -28.0 against the current item.",
        "guardrails_applied": [],
        "critical_tradeoffs": [],
        "resistances": [
            _resist("fire", "CAPPED_STAYS_CAPPED", "info", 75, 75),
            _resist("cold", "CAPPED_STAYS_CAPPED", "info", 75, 75),
            _resist("lightning", "CAPPED_STAYS_CAPPED", "info", 75, 75),
            _resist("chaos", "BELOW_CAP_WORSENED", "high", 15, 0),
        ],
        "all_deltas": [
            {"key": "primary_offense", "label": "Damage", "current": 1000, "candidate": 950.9, "percent_delta": -4.9, "direction": "negative"},
            {"key": "ehp", "label": "EHP", "current": 5000, "candidate": 4196, "percent_delta": -16.1, "direction": "negative"},
            {"key": "worst_max_hit", "label": "Max Hit", "current": 3000, "candidate": 2277, "percent_delta": -24.1, "direction": "negative"},
        ],
        "score_contributors": [{"key": "res_flex", "contribution": -0.5}],
        "unsupported_or_unmodeled": [],
        "evaluation_quality_reasons": [],
    }
    model = {
        "item_name": "Test Helmet",
        "impact_rows": [
            {"marker": "▼", "label": "Damage", "delta_text": "-4.9%", "direction": "negative", "emphasis": "medium"},
            {"marker": "▼", "label": "EHP", "delta_text": "-16.1%", "direction": "negative", "emphasis": "critical"},
            {"marker": "▼", "label": "Max Hit", "delta_text": "-24.1%", "direction": "negative", "emphasis": "critical"},
        ],
        "evaluation_outcome": outcome,
        "primary_metric": {},
        "native_damage_discovery": {},
    }
    return build_more_info(model, outcome=outcome), model


def test_advanced_disclosure_collapsed_by_default_and_toggles() -> None:
    _make_app()
    from exilelens.ui.overlay_detail_drawer import DetailAnalysisDrawer

    block, model = _helmet_downgrade_block()
    drawer = DetailAnalysisDrawer()
    drawer.set_content(block, model=model)
    drawer.show()
    assert drawer._advanced_toggle is not None, "this fixture has advanced content (flexibility)"
    assert drawer._advanced_expanded is False
    assert drawer._advanced_container.isVisible() is False

    drawer._advanced_toggle.click()
    assert drawer._advanced_expanded is True
    assert drawer._advanced_container.isVisible() is True

    drawer._advanced_toggle.click()
    assert drawer._advanced_expanded is False
    assert drawer._advanced_container.isVisible() is False


def test_advanced_disclosure_resets_collapsed_for_a_new_result() -> None:
    _make_app()
    from exilelens.ui.overlay_detail_drawer import DetailAnalysisDrawer

    block, model = _helmet_downgrade_block()
    drawer = DetailAnalysisDrawer()
    drawer.set_content(block, model=model)
    drawer._advanced_toggle.click()
    assert drawer._advanced_expanded is True

    # A brand new Item Check result calls set_content() again (via clear()).
    drawer.set_content(block, model=model)
    assert drawer._advanced_expanded is False


def test_normal_more_info_never_shows_raw_engine_state_names() -> None:
    _make_app()
    from exilelens.ui.overlay_detail_drawer import DetailAnalysisDrawer

    block, model = _helmet_downgrade_block()
    drawer = DetailAnalysisDrawer()
    drawer.set_content(block, model=model)
    all_text = " ".join(
        label.text()
        for label in drawer._section_widgets
        if hasattr(label, "text")
    )
    assert "CAPPED_STAYS_CAPPED" not in all_text
    assert "BELOW_CAP_WORSENED" not in all_text


def test_jewel_ring_selector_best_socket_identifiable_no_raw_ids_advanced_state_persists() -> None:
    _make_app()
    from exilelens.ui.overlay_detail_drawer import DetailAnalysisDrawer

    def outcome_for(node_id: int, score: float) -> dict[str, object]:
        return {
            "verdict": "SIDEGRADE",
            "verdict_label": "SIDEGRADE",
            "final_score": score,
            "evaluation_quality": "FULL",
            "quality_label": "",
            "verdict_reason": f"Net score test {node_id}.",
            "guardrails_applied": [],
            "critical_tradeoffs": [],
            "resistances": [],
            "all_deltas": [],
            "score_contributors": [{"key": "res_flex", "contribution": 0.2}],
            "unsupported_or_unmodeled": [],
            "evaluation_quality_reasons": [],
            "replacement_slot": f"Jewel {node_id}",
        }

    choices = [
        {
            "slot": "Jewel 7960",
            "selected": True,
            "best": True,
            "replacing_item": "Foe Joy, Sapphire",
            "verdict_label": "MEANINGFUL UPGRADE",
            "verdict": "MEANINGFUL_UPGRADE",
            "final_score": 71,
            "evaluation_outcome": outcome_for(7960, 71),
        },
        {
            "slot": "Jewel 21984",
            "replacing_item": "Apocalypse Stone, Sapphire",
            "verdict_label": "SIDEGRADE",
            "verdict": "SIDEGRADE",
            "final_score": 50,
            "evaluation_outcome": outcome_for(21984, 50),
        },
    ]
    model = {
        "item_name": "Test Jewel",
        "replacement_choices": choices,
        "evaluation_outcome": choices[0]["evaluation_outcome"],
        "primary_metric": {},
        "native_damage_discovery": {},
    }
    block = build_more_info(model, outcome=choices[0]["evaluation_outcome"])
    block["replacement_choices"] = choices

    drawer = DetailAnalysisDrawer()
    drawer.set_content(block, model=model)
    drawer.show()

    captions = [button.text() for button in drawer._ring_buttons]
    assert captions[0].startswith("Socket 1")
    assert "★" in captions[0]  # best socket clearly identifiable
    assert "★" not in captions[1]
    assert not any("7960" in caption or "21984" in caption for caption in captions)
    assert drawer._selected_index == 0

    if drawer._advanced_toggle is not None:
        drawer._advanced_toggle.click()
    expanded_before_switch = drawer._advanced_expanded

    events: list[int] = []
    drawer.ring_choice_changed.connect(events.append)
    drawer.select_choice(1)

    assert drawer._selected_index == 1
    assert events == [1]
    assert drawer._advanced_expanded == expanded_before_switch
