"""OLD vs NEW replay flip report.

``recorded`` in each fixture is what the pipeline produced at the commit the fixture was captured from
(before the policy change); the replay is what the current tree produces from the same measured inputs.

    python -m tests.policy_replay.flip_report
"""

from __future__ import annotations

from typing import Any

from tests.policy_replay.replay import fixture_ids, load_fixture, replay, summarize


def flip_rows() -> list[dict[str, Any]]:
    rows = []
    for fixture_id in fixture_ids():
        fixture = load_fixture(fixture_id)
        old = fixture["recorded"]
        new = summarize(replay(fixture))
        opposition = [
            f"{name}{'+' if axis.get('material_positive') else ''}{'-' if axis.get('material_negative') else ''}"
            for name, axis in new["axes"].items()
            if axis.get("material_positive") or axis.get("material_negative")
        ]
        rows.append({
            "fixture": fixture_id,
            "old_verdict": old["verdict"], "new_verdict": new["verdict"],
            "old_final": old["final_score"], "new_final": new["final_score"],
            "raw_score": new["raw_score"],
            "conflict_kind": new["conflict_kind"],
            "material_axes": opposition,
            "negligible_opposition": new["negligible_opposition"],
            "changed": old["verdict"] != new["verdict"] or old["final_score"] != new["final_score"],
        })
    return rows


def format_report(rows: list[dict[str, Any]] | None = None) -> str:
    rows = rows if rows is not None else flip_rows()
    lines = ["| fixture | old verdict | new verdict | old final | new final | raw | conflict | material axes | negligible opposition |",
             "|---|---|---|---|---|---|---|---|---|"]
    for row in rows:
        mark = " **(flip)**" if row["changed"] else ""
        lines.append(
            f"| {row['fixture']} | {row['old_verdict']} | {row['new_verdict']}{mark} | {row['old_final']} | {row['new_final']} | "
            f"{row['raw_score']} | {row['conflict_kind']} | {', '.join(row['material_axes']) or '-'} | "
            f"{', '.join(row['negligible_opposition']) or '-'} |"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    print(format_report())
