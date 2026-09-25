"""P1.1b — visual language / hierarchy polish: deterministic presentation-layer
regression coverage for the two behavior changes in this pass (jewel socket
copy, primary-offense visibility in the compact impact selector).

Presentation-only unit tests: no PoB worker, no real evaluation, deterministic
dict fixtures only. `test_p1_1_tooltip_presentation.py` already covers (and,
re-run here, still passes unchanged) the BV/score wording, UNCERTAIN quality
note, and row/reason/note bound regressions this pass did not touch.
"""

from __future__ import annotations

import pytest

from exilelens.items.compact_tooltip import replacing_line, select_impact_rows, slot_verdict_lines
from exilelens.items.slots import is_jewel_socket_pob_slot, jewel_socket_display_label

pytestmark = pytest.mark.itemcheck


# --------------------------------------------------------------------------- helpers


def _impact_row(key: str, *, pct: float, emphasis: str = "medium", delta_kind: str = "MEASURED") -> dict[str, object]:
    return {
        "key": key,
        "label": key.replace("_", " ").title(),
        "percent_delta": pct,
        "absolute_delta": None,
        "delta_text": f"{pct:+.1f}%",
        "direction": "positive" if pct > 0 else "negative",
        "emphasis": emphasis,
        "cap_state": "",
        "delta_kind": delta_kind,
    }


def _jewel_choice(node_id: int, **overrides: object) -> dict[str, object]:
    base = {"slot": f"Jewel {node_id}"}
    base.update(overrides)
    return base


# ------------------------------------------------------------------ jewel copy


def test_is_jewel_socket_pob_slot_matches_only_the_dynamic_pattern() -> None:
    assert is_jewel_socket_pob_slot("Jewel 11184")
    assert is_jewel_socket_pob_slot("Jewel 7960")
    assert not is_jewel_socket_pob_slot("Ring 1")
    assert not is_jewel_socket_pob_slot("Weapon 2")
    assert not is_jewel_socket_pob_slot("")


def test_jewel_socket_display_label_is_an_ordinal_never_a_node_id() -> None:
    assert jewel_socket_display_label(0) == "Socket 1"
    assert jewel_socket_display_label(3) == "Socket 4"
    for index in range(5):
        assert "Jewel" not in jewel_socket_display_label(index)


def test_replacing_line_never_leaks_raw_jewel_node_id_occupied_best() -> None:
    model = {
        "evaluation_outcome": {"replacement_slot": "Jewel 7960"},
        "replacement_choices": [
            _jewel_choice(7960, selected=True, best=True, replacing_item="Foe Joy, Sapphire"),
            _jewel_choice(21984, replacing_item="Apocalypse Stone, Sapphire"),
            _jewel_choice(26196, replacing_item="From Nothing, Diamond"),
            _jewel_choice(61419, replacing_item="Spirit Glisten, Sapphire"),
        ],
    }
    line = replacing_line(model)
    assert "Jewel 7960" not in line
    assert "7960" not in line
    assert "Foe Joy, Sapphire" in line
    assert "Checked 4 jewel sockets" in line


def test_replacing_line_never_leaks_raw_jewel_node_id_empty_best() -> None:
    model = {
        "evaluation_outcome": {"replacement_slot": "Jewel 100"},
        "replacement_choices": [
            _jewel_choice(100, selected=True, best=True, empty=True),
            _jewel_choice(200, replacing_item="Some Jewel"),
        ],
    }
    line = replacing_line(model)
    assert "Jewel 100" not in line
    assert "Empty jewel socket" in line
    assert "Checked 2 jewel sockets" in line


def test_replacing_line_single_jewel_choice_no_count_suffix() -> None:
    model = {
        "evaluation_outcome": {"replacement_slot": "Jewel 42", "replacing_item": "Some Jewel"},
        "replacement_choices": [],
    }
    line = replacing_line(model)
    assert "Jewel 42" not in line
    assert line == "Replacing: Some Jewel"


def test_replacing_line_equipment_slots_unaffected() -> None:
    """Regression guard: the jewel-specific branches must not change ordinary
    equipment (Ring/Weapon/etc.) copy at all."""
    model = {
        "evaluation_outcome": {"replacement_slot": "Ring 1"},
        "replacement_choices": [
            {"slot": "Ring 1", "selected": True, "best": True, "replacing_item": "Old Ring"},
            {"slot": "Ring 2", "replacing_item": "Other Ring"},
        ],
    }
    assert replacing_line(model) == "Best: Ring 1 — Old Ring"


def test_slot_verdict_lines_suppressed_entirely_for_jewel_sockets() -> None:
    """Never dump the evaluated socket list -- replacing_line()'s single
    best-fit + count summary is the only jewel-socket copy in the compact
    surface."""
    model = {
        "replacement_choices": [
            _jewel_choice(7960, selected=True, verdict_label="MEANINGFUL UPGRADE"),
            _jewel_choice(21984, verdict_label="SIDEGRADE"),
            _jewel_choice(26196, verdict_label="MINOR DOWNGRADE"),
        ],
    }
    assert slot_verdict_lines(model) == []


def test_slot_verdict_lines_equipment_slots_unaffected() -> None:
    model = {
        "replacement_choices": [
            {"slot": "Ring 1", "selected": True, "verdict_label": "CLEAR UPGRADE", "verdict": "MEANINGFUL_UPGRADE"},
            {"slot": "Ring 2", "verdict_label": "SIDEGRADE", "verdict": "SIDEGRADE"},
        ],
    }
    lines = slot_verdict_lines(model)
    assert len(lines) == 2
    assert lines[0]["text"] == "Ring 1: CLEAR UPGRADE"


# --------------------------------------------------------- primary offense visibility


def test_material_primary_offense_survives_multiple_large_defensive_losses() -> None:
    """The coordinator's exact scenario: a real, measured primary-offense loss
    (Spark DPS -4.9%) must not be silently dropped from the compact impact
    rows just because several defensive metrics separately cross the
    LARGE_DAMAGE_LOSS_PCT-equivalent threshold and outrank it in the
    higher-priority 'large loss' bucket."""
    rows = [
        _impact_row("primary_offense", pct=-4.9),
        _impact_row("ehp", pct=-16.1, emphasis="critical"),
        _impact_row("worst_max_hit", pct=-24.1, emphasis="critical"),
        _impact_row("chaos_res", pct=-15.0, emphasis="high"),
        _impact_row("lightning_res", pct=-12.0, emphasis="high"),
        _impact_row("fire_res", pct=-11.0, emphasis="high"),
    ]
    selected = select_impact_rows(rows, limit=5)
    keys = [row["key"] for row in selected]
    assert "primary_offense" in keys
    assert len(selected) <= 5


def test_unmeasured_primary_offense_never_forced_into_view() -> None:
    """The visibility guarantee is presentation-ranking only -- it must never
    promote an UNMEASURED/ESTIMATED/UNSUPPORTED damage number just to fill the
    primary-offense slot (that stays a truthfulness gate elsewhere)."""
    rows = [
        {**_impact_row("primary_offense", pct=-4.9), "delta_kind": "ESTIMATED"},
        _impact_row("ehp", pct=-16.1, emphasis="critical"),
        _impact_row("worst_max_hit", pct=-24.1, emphasis="critical"),
        _impact_row("chaos_res", pct=-15.0, emphasis="high"),
        _impact_row("lightning_res", pct=-12.0, emphasis="high"),
        _impact_row("fire_res", pct=-11.0, emphasis="high"),
    ]
    selected = select_impact_rows(rows, limit=5)
    keys = [row["key"] for row in selected]
    # Not force-included via the new rule -- may still appear on its own
    # ranking merits, but the test fixture's magnitude/bucket puts a real
    # ESTIMATED row below the cut same as before this change.
    assert "primary_offense" not in keys


def test_small_primary_offense_change_not_forced_into_view() -> None:
    """Below the materiality threshold, no visibility guarantee applies --
    this is not a blanket 'always show primary_offense' rule."""
    rows = [
        _impact_row("primary_offense", pct=-0.4),
        _impact_row("ehp", pct=-16.1, emphasis="critical"),
        _impact_row("worst_max_hit", pct=-24.1, emphasis="critical"),
        _impact_row("chaos_res", pct=-15.0, emphasis="high"),
        _impact_row("lightning_res", pct=-12.0, emphasis="high"),
        _impact_row("fire_res", pct=-11.0, emphasis="high"),
    ]
    selected = select_impact_rows(rows, limit=5)
    keys = [row["key"] for row in selected]
    assert "primary_offense" not in keys


def test_material_loss_guarantee_and_offense_guarantee_coexist() -> None:
    """When both safety nets are needed at once (a material loss AND a
    material offense change would otherwise be squeezed out together), both
    must survive, not just whichever ran last."""
    rows = [
        _impact_row("primary_offense", pct=-3.5),
        _impact_row("ehp", pct=-16.1, emphasis="critical"),
        _impact_row("worst_max_hit", pct=-24.1, emphasis="critical"),
        _impact_row("chaos_res", pct=-15.0, emphasis="high"),
        _impact_row("lightning_res", pct=-12.0, emphasis="high"),
        _impact_row("fire_res", pct=-11.0, emphasis="high"),
        _impact_row("cold_res", pct=-10.5, emphasis="high"),
    ]
    selected = select_impact_rows(rows, limit=5)
    keys = [row["key"] for row in selected]
    assert "primary_offense" in keys
    assert any(row.get("emphasis") in {"critical", "high"} for row in selected if row["key"] != "primary_offense")
    assert len(selected) <= 5
