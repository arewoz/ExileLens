"""Regression coverage for Unicode-safe PoB worker stdio on Windows."""

from __future__ import annotations

import io
import sys
from pathlib import Path

from exilelens.config import PobConfig
from exilelens.engine import SubprocessWorkerClient
from exilelens import worker


def test_worker_command_forces_utf8_mode(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("exilelens.engine.is_frozen", lambda: False)
    monkeypatch.setattr("exilelens.engine.repo_root", lambda: tmp_path)

    command, env = SubprocessWorkerClient(PobConfig(pob_path=tmp_path))._command()

    assert command == [sys.executable, "-X", "utf8", "-m", "exilelens.worker"]
    assert env["PYTHONUTF8"] == "1"
    assert env["PYTHONPATH"] == str(tmp_path / "src")


def test_worker_reconfigures_non_utf8_streams_before_protocol_output(monkeypatch) -> None:
    stdout_bytes = io.BytesIO()
    stderr_bytes = io.BytesIO()
    stdout = io.TextIOWrapper(stdout_bytes, encoding="cp1252")
    stderr = io.TextIOWrapper(stderr_bytes, encoding="cp1252")
    monkeypatch.setattr(worker.sys, "stdout", stdout)
    monkeypatch.setattr(worker.sys, "stderr", stderr)

    worker._configure_std_streams_utf8()
    worker.sys.stdout.write("Łódź 龍 🎮")
    worker.sys.stdout.flush()

    assert worker.sys.stdout.encoding.lower().replace("-", "") == "utf8"
    assert stdout_bytes.getvalue().decode("utf-8") == "Łódź 龍 🎮"
