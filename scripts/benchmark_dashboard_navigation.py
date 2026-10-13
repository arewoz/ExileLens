"""Offline Qt navigation timings on an isolated profile; no PoB or network.

Run in a fresh process: python scripts/benchmark_dashboard_navigation.py
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts"), str(ROOT)]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer, Qt
from ui_visual_qa import Harness


def wait(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    results = []
    with tempfile.TemporaryDirectory(prefix="exilelens-navigation-") as profile:
        h = Harness(Path(profile))
        h.window.resize(1280, 860)
        gaps = []
        last = [time.perf_counter()]

        def heartbeat():
            now = time.perf_counter()
            gaps.append((now - last[0]) * 1000)
            last[0] = now

        timer = QTimer()
        timer.setTimerType(Qt.TimerType.PreciseTimer)
        timer.setInterval(4)
        timer.timeout.connect(heartbeat)
        timer.start()
        wait(100)
        try:
            for target in ("filters", "diagnostics", "filters", "diagnostics", "filters", "diagnostics",
                           "filter-profile-change", "filter-theme-change"):
                h.window.navigate("filters" if "-change" in target else "overview")
                wait(60)
                gaps.clear()
                last[0] = start = time.perf_counter()
                if "-change" in target:
                    combo = h.window._filters_page._profile if "profile" in target else h.window._filters_page._theme
                    combo.setCurrentIndex((combo.currentIndex() + 1) % combo.count())
                else:
                    h.window.navigate(target)
                navigation_ms = (time.perf_counter() - start) * 1000
                h.app.processEvents()
                deadline = start + 5
                page = h.window._filters_page
                while getattr(page, "_generation_task", None) is not None and time.perf_counter() < deadline:
                    wait(10)
                if getattr(page, "_generation_task", None) is not None:
                    raise RuntimeError("filter generation did not settle")
                ready_ms = (time.perf_counter() - start) * 1000
                wait(80)
                results.append({"target": target, "navigation_ms": round(navigation_ms, 2),
                                "ready_ms": round(ready_ms, 2), "max_ui_gap_ms": round(max(gaps, default=0), 2)})
        finally:
            timer.stop()
            h.window.close()
            h.controller.shutdown()
    payload = {"python": sys.version.split()[0], "viewport": [1280, 860], "results": results}
    text = json.dumps(payload, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
