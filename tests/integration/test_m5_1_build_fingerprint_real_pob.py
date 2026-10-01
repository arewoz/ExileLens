"""M5.1: the base fingerprint truthfully reflects what real PoB reports, with no extra PoB work."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from exilelens.analysis.fingerprint import build_fingerprint
from exilelens.analysis.identity import AnalysisBaseline

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "fixtures" / "builds" / "public_corpus"
pytestmark = [pytest.mark.integration, pytest.mark.real_pob, pytest.mark.itemcheck]


def _fingerprint(engine, name: str):
    path = CORPUS / name
    engine.load_build(path)
    metrics = engine.get_metrics()
    raw = metrics["raw"]
    info = engine.get_build_info() or {}
    blob = info.get("build") if isinstance(info.get("build"), dict) else info
    baseline = AnalysisBaseline(str(path), str(blob.get("name") or ""), "", "", "MAP", "BALANCED", 1, str(metrics.get("fingerprint_hash") or ""))
    calls = {"n": 0}
    original = engine.evaluate_candidate
    engine.evaluate_candidate = lambda *a, **k: calls.__setitem__("n", calls["n"] + 1) or original(*a, **k)
    started = time.perf_counter()
    fp = build_fingerprint(raw=raw, baseline=baseline, build_info=blob).to_dict()
    elapsed_ms = (time.perf_counter() - started) * 1000
    engine.evaluate_candidate = original
    assert calls["n"] == 0  # zero hypothetical PoB recalculations
    assert elapsed_ms < 50
    json.dumps(fp)  # serialisable contract
    return fp, raw


def test_player_es_caster_fingerprint_matches_pob(real_pob_engine) -> None:
    fp, raw = _fingerprint(real_pob_engine, "corpus02g_dex_int_acolyte_hand_of_wisdom.xml")
    assert fp["offense"]["owner"] == "PLAYER"
    assert fp["offense"]["damage"]["value"] == raw[fp["offense"]["metric"]]
    assert fp["defense"]["energy_shield"]["value"]["value"] == raw["EnergyShield"]
    assert fp["defense"]["total_ehp"]["value"] == raw["TotalEHP"]
    assert fp["requirements"]["strength"]["highest_requirement"]["value"] == raw["ReqStr"]
    assert fp["requirements"]["intelligence"]["margin"]["value"] == raw["Int"] - raw["ReqInt"]
    assert fp["identity"]["baseline_fingerprint"]


def test_minion_build_fingerprint_names_the_minion_owner(real_pob_engine) -> None:
    fp, raw = _fingerprint(real_pob_engine, "core04_minion_actor.xml")
    assert fp["offense"]["owner"] == "MINION" and fp["offense"]["metric"].startswith("Minion.")
    assert fp["offense"]["damage"]["value"] == raw[fp["offense"]["metric"]]
    assert fp["offense"]["crit"]["present"]["evidence"] == "UNAVAILABLE"
    print(json.dumps({k: fp[k] for k in ("identity", "offense")}, indent=1)[:1500])
