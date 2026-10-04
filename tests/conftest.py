"""Public test support with no developer-machine PoB path assumptions."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture(scope="session")
def pob_config():
    """Return a validated public PoB runtime, or explicitly skip if none exists.

    `POB2_PATH` is intentionally the only non-standard lookup. It is never written
    by tests, and a configured path is validated rather than silently skipped.
    """

    from exilelens.config import PobConfig, detect_common_pob_installation, validate_pob_path

    explicit = os.environ.get("POB2_PATH", "").strip()
    if explicit:
        config = PobConfig(Path(explicit).expanduser().resolve())
        validate_pob_path(config)
        return config

    discovered = detect_common_pob_installation()
    if discovered is None:
        pytest.skip("real PoB runtime unavailable: set POB2_PATH to a supported PoB2 installation")
    config = PobConfig(discovered)
    validate_pob_path(config)
    return config


@pytest.fixture(scope="module")
def real_pob_engine(pob_config):
    from exilelens.engine import Engine

    with Engine(pob_config, use_subprocess=True) as engine:
        yield engine


@pytest.fixture(autouse=True)
def _r5a_market_tests_never_touch_the_network(request, monkeypatch):
    """R5-A: the market foundation is tested entirely against injected fake transports. Any attempt to open a real connection from
    a `test_r5a_*` module fails the test loudly, so a regression in the transport seam cannot silently reach pathofexile.com."""
    name = Path(str(request.node.fspath)).name
    if not name.startswith("test_r5a_"):
        return

    def _refuse(*args, **kwargs):
        raise AssertionError("a real network connection was attempted from an R5-A market test")

    import socket
    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", _refuse)
    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)
