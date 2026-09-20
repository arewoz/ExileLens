"""Public deterministic Build Corpus regression gate."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from xml.etree import ElementTree

import pytest


ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "fixtures" / "builds" / "public_corpus"
MANIFEST = json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))
CASES = MANIFEST["fixtures"]
PUBLIC_FIXTURES = (
    ROOT / "fixtures" / "builds" / "core04_player_ring.xml",
    *(ROOT / case["file"] for case in CASES),
    *(ROOT / "fixtures" / "items" / name for name in (
        "core04_baseline_ring.txt",
        "core04_offense_ring.txt",
        "core04_defense_ring.txt",
        "core04_tradeoff_ring.txt",
    )),
)
pytestmark = pytest.mark.build_corpus


def _path(case: dict) -> Path:
    return ROOT / case["file"]


def test_manifest_is_small_complete_and_repository_relative() -> None:
    assert [case["id"] for case in CASES] == [
        "CORE04-BOW-QUIVER",
        "CORE04-MINION-ACTOR",
        "CORE04-STAGE-CONTEXT",
        "CORE04-MELEE-WEAPON",
        "CORE04-ONEHAND-WEAPON",
        "CORE04-POISON-AILMENT",
        "CORE04-MIXED-HIT-AILMENT",
    ]
    assert len(CASES) == 7
    for case in CASES:
        assert set(case) == {"id", "file", "class", "ascendancy", "primary_skill", "actor", "purpose"}
        assert not Path(case["file"]).is_absolute()
        assert _path(case).is_file()


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_fixture_is_well_formed_and_matches_declared_semantics(case: dict) -> None:
    path = _path(case)
    root = ElementTree.fromstring(path.read_text(encoding="utf-8"))
    build = root.find("Build")
    assert build is not None
    assert build.get("className") == case["class"]
    assert build.get("ascendClassName") == case["ascendancy"]
    assert case["primary_skill"] in {gem.get("nameSpec") for gem in root.iter("Gem")}
    assert hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("fixture", PUBLIC_FIXTURES, ids=lambda fixture: fixture.name)
def test_selected_fixture_contains_no_private_path_or_identity_markers(fixture: Path) -> None:
    text = fixture.read_text(encoding="utf-8")
    forbidden = (
        r"(?i)[a-z]:\\",
        r"(?i)/(?:users|home)/",
        r"(?i)accountname|charactername|lastcharacterhash",
        r"(?i)(?:authorization|bearer|oauth|session(?:id)?|cookie|api[_-]?key|secret|token)",
        r"(?i)[\w.+-]+@[\w.-]+\.[a-z]{2,}",
    )
    assert all(re.search(pattern, text) is None for pattern in forbidden)


@pytest.mark.integration
@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_public_corpus_loads_with_expected_primary_actor(real_pob_engine, case: dict) -> None:
    loaded = real_pob_engine.load_build(_path(case))
    identity = loaded["build"]["main_skill_identity"]
    assert loaded["build"]["class"] == case["class"]
    assert loaded["build"]["ascendancy"] == case["ascendancy"]
    assert identity["skill_name"] == case["primary_skill"]
    assert identity["damage_owner"] == case["actor"]
    assert loaded["fingerprint_hash"]
