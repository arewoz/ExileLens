"""Minimal JUnit XML reader for pytest's built-in `--junitxml` output.

No third-party dependency: pytest's own JUnit writer is stdlib-parseable. We only
need pass/fail/error/skipped per test `name`, nothing else (no durations/timestamps,
so downstream reports stay deterministic).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree


@dataclass(frozen=True)
class JUnitOutcome:
    name: str
    classname: str
    status: str  # "passed" | "failed" | "error" | "skipped"
    message: str = ""


def read_junit_outcomes(path: Path) -> list[JUnitOutcome]:
    root = ElementTree.parse(path).getroot()
    outcomes: list[JUnitOutcome] = []
    for testcase in root.iter("testcase"):
        name = testcase.get("name", "")
        classname = testcase.get("classname", "")
        failure = testcase.find("failure")
        error = testcase.find("error")
        skipped = testcase.find("skipped")
        if failure is not None:
            status, message = "failed", failure.get("message", "") or (failure.text or "")
        elif error is not None:
            status, message = "error", error.get("message", "") or (error.text or "")
        elif skipped is not None:
            status, message = "skipped", skipped.get("message", "") or (skipped.text or "")
        else:
            status, message = "passed", ""
        outcomes.append(JUnitOutcome(name=name, classname=classname, status=status, message=message))
    return outcomes
