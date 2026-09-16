"""Precise, user-facing status of each piece of ExileLens setup.

A tester with a wrong path used to see only that nothing worked. These checks name the
broken part (PoB folder, build file, engine, loaded build) and say what to do about it.
They only read the filesystem; nothing here loads PoB.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from poe2value.app.build_state import BuildInfo, BuildState
from poe2value.config import PobConfig, required_pob_files


@dataclass(frozen=True)
class SetupCheck:
    ok: bool
    label: str
    detail: str = ""

    def text(self) -> str:
        return f"{self.label} — {self.detail}" if self.detail else self.label


def check_pob_folder(path: str) -> SetupCheck:
    raw = str(path or "").strip()
    if not raw:
        return SetupCheck(False, "NOT SET", "Choose your Path of Building Community (PoE2) installation.")
    root = Path(raw)
    if not root.is_dir():
        return SetupCheck(False, "NOT FOUND", f"This folder does not exist: {raw}")
    config = PobConfig(pob_path=root)
    required = required_pob_files(config)
    missing = [
        label
        for label, candidate in required.items()
        if not label.startswith("ExileLens") and not Path(candidate).exists()
    ]
    if missing:
        looks_like_pob = any((root / name).exists() for name in ("Data", "Modules", "Assets", "Launch.lua"))
        return SetupCheck(
            False,
            "INCOMPATIBLE POB INSTALLATION" if looks_like_pob else "NOT A POB INSTALLATION",
            f"Missing {', '.join(missing)}. Choose the installation folder containing Launch.lua and lua51.dll.",
        )
    layout = "installed application" if config.layout == "installed" else "developer checkout"
    return SetupCheck(True, "FOUND", f"Detected {layout}; Apply will start an engine probe.")


def check_build_file(path: str) -> SetupCheck:
    raw = str(path or "").strip()
    if not raw:
        return SetupCheck(False, "NOT SET", "Choose the PoB build (.xml) you play.")
    candidate = Path(raw)
    if candidate.is_dir():
        return SetupCheck(False, "FOLDER SELECTED", "That is a folder. Choose the build's .xml file inside it.")
    if not candidate.exists():
        return SetupCheck(False, "NOT FOUND", f"The configured file no longer exists: {raw}")
    if candidate.suffix.lower() != ".xml":
        return SetupCheck(False, "WRONG FILE TYPE", "Choose a Path of Building build saved as .xml.")
    try:
        root = ET.parse(candidate).getroot()
    except (ET.ParseError, OSError) as exc:
        return SetupCheck(False, "PARSE FAILED", f"The file could not be read as a PoB build ({exc}).")
    if not root.tag.startswith("PathOfBuilding"):
        return SetupCheck(False, "NOT A POB BUILD", f"The file is XML but not a Path of Building build (<{root.tag}>).")
    return SetupCheck(True, "FOUND")


def describe_build_state(info: BuildInfo) -> SetupCheck:
    state = info.state
    name = info.name or (Path(info.path).stem if info.path else "")
    if state == BuildState.READY:
        return SetupCheck(True, "LOADED", name)
    if state in (BuildState.LOADING, BuildState.RELOADING):
        return SetupCheck(False, "LOADING", name)
    if state in (BuildState.FAILED, BuildState.ERROR):
        return SetupCheck(False, "LOAD FAILED", info.error_message or "unknown error")
    return SetupCheck(False, "NOT LOADED", "No build is loaded yet.")


def describe_engine(status: str) -> SetupCheck:
    if status == "ready":
        return SetupCheck(True, "RUNNING")
    if status == "starting":
        return SetupCheck(False, "STARTING", "Path of Building is starting…")
    if status.startswith("failed:"):
        return SetupCheck(False, "FAILED", status.split(":", 1)[1].strip())
    return SetupCheck(False, "STOPPED")
