"""R5-A: the REAL startup construction path (EvaluationController) with market prices off must not load the live trade stack, and the
legacy market-only service is created lazily and still obeys central market access. Runs in a fresh interpreter so module state is
honest; no real network (the subprocess refuses any connection)."""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from tests.market_support import RING_ITEM, ROOT

pytestmark = pytest.mark.itemcheck

HEAVY = (
    "exilelens.price_check.trade2_client",
    "exilelens.price_check.transport",
    "exilelens.price_check.providers.live_trade2",
    "exilelens.price_check.providers.cached_live_trade2",
    "exilelens.price_check.providers.market_session_provider",
)

SCRIPT = f"""
import json, os, socket, sys, urllib.request
def refuse(*a, **k):
    raise AssertionError("real network attempted")
urllib.request.urlopen = refuse
socket.socket.connect = refuse
socket.create_connection = refuse
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])
from exilelens.app.controller import EvaluationController
from exilelens.app.settings import AppSettings
heavy = {HEAVY!r}
controller = EvaluationController(AppSettings())
out = {{"loaded_after_construction": [m for m in heavy if m in sys.modules],
        "lazy_attr": controller._market_only_service is None}}
from exilelens.items.raw_input import RawItemInput
from exilelens.price_check.models import PriceCheckRequest, LeagueContext
text = open({str(RING_ITEM)!r}, encoding="utf-8").read()
request = PriceCheckRequest(item_raw=text, content_hash=RawItemInput.from_text(text).content_hash,
                            league=LeagueContext.from_settings("Synthetic League"), request_id=1)
service = controller._get_market_only_service()
out["created_on_demand"] = controller._market_only_service is service and controller._get_market_only_service() is service
result = service.check(request)
out["has_estimate"] = bool(result.estimate.has_currency_estimate)
out["state"] = result.live_search_state.value if result.live_search_state else None
controller.shutdown()
print("RESULT" + json.dumps(out))
"""


def test_controller_construction_is_lazy_and_market_only_obeys_central_policy(tmp_path):
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "LOCALAPPDATA": str(tmp_path), "QT_QPA_PLATFORM": "offscreen"}
    env.pop("EXILELENS_AUDIT_VARIANT", None)
    done = subprocess.run([sys.executable, "-c", SCRIPT], cwd=ROOT, env=env, capture_output=True, text=True, timeout=180)
    assert done.returncode == 0, done.stderr[-2000:]
    out = json.loads(next(line for line in done.stdout.splitlines() if line.startswith("RESULT"))[len("RESULT"):])
    assert out["loaded_after_construction"] == [], "constructing the controller with market off loaded the live trade stack"
    assert out["lazy_attr"] is True
    assert out["created_on_demand"] is True
    # Central policy still wins once the service exists: no estimate, typed failure, and the refusing network was never touched.
    assert out["has_estimate"] is False
    assert out["state"] is not None and out["state"] != "LIVE_SEARCH_OK_RESULTS"
