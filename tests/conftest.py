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

    from poe2value.config import PobConfig, detect_common_pob_installation, validate_pob_path

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
    from poe2value.engine import Engine

    with Engine(pob_config, use_subprocess=True) as engine:
        yield engine
