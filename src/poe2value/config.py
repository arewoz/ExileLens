from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from poe2value import SUPPORTED_POB_HEAD
from poe2value._paths import bridge_lua_path, pob_headless_wrapper_path, pob_simplegraphic_def_path
from poe2value.errors import PobPathInvalid, UnsupportedPobRevision


@dataclass(frozen=True)
class PobConfig:
    pob_path: Path
    supported_head: str = SUPPORTED_POB_HEAD

    @property
    def layout(self) -> str:
        if (self.pob_path / "src" / "Launch.lua").is_file():
            return "source"
        if (self.pob_path / "Launch.lua").is_file():
            return "installed"
        return "unknown"

    @property
    def program_path(self) -> Path:
        return self.pob_path / "src" if self.layout == "source" else self.pob_path

    @property
    def src_path(self) -> Path:
        """Compatibility alias for the directory containing PoB's Lua program."""
        return self.program_path

    @property
    def runtime_path(self) -> Path:
        return self.pob_path / "runtime" if self.layout == "source" else self.pob_path

    @property
    def lua_modules_path(self) -> Path:
        return self.runtime_path / "lua"

    @property
    def lua_dll(self) -> Path:
        return self.runtime_path / "lua51.dll"

    @property
    def headless_wrapper(self) -> Path:
        return pob_headless_wrapper_path()

    @property
    def simplegraphic_def(self) -> Path:
        return pob_simplegraphic_def_path()

    @property
    def bridge_lua(self) -> Path:
        return bridge_lua_path()


def load_config() -> PobConfig:
    raw = (os.environ.get("POB2_PATH") or "").strip()
    return PobConfig(pob_path=Path(raw).resolve() if raw else Path())


def required_pob_files(config: PobConfig) -> dict[str, Path]:
    """Files supplied by PoB and ExileLens that the headless worker needs."""
    return {
        "pob_root": config.pob_path,
        "Launch.lua": config.program_path / "Launch.lua",
        "Modules/Main.lua": config.program_path / "Modules" / "Main.lua",
        "Modules/Build.lua": config.program_path / "Modules" / "Build.lua",
        "Data/ModItem.lua": config.program_path / "Data" / "ModItem.lua",
        "lua51.dll": config.lua_dll,
        "lua/xml.lua": config.lua_modules_path / "xml.lua",
        "ExileLens bridge.lua": config.bridge_lua,
        "ExileLens headless wrapper": config.headless_wrapper,
        "ExileLens SimpleGraphic definitions": config.simplegraphic_def,
    }


def detect_common_pob_installation() -> Path | None:
    """Return a structurally plausible normal Windows PoB2 installation."""
    candidates: list[Path] = []
    for variable, suffix in (
        ("APPDATA", "Path of Building Community (PoE2)"),
        ("LOCALAPPDATA", "Path of Building Community (PoE2)"),
        ("LOCALAPPDATA", "Programs/Path of Building Community (PoE2)"),
        ("ProgramFiles", "Path of Building Community (PoE2)"),
        ("ProgramFiles(x86)", "Path of Building Community (PoE2)"),
    ):
        base = str(os.environ.get(variable) or "").strip()
        if base:
            candidates.append(Path(base) / suffix)
    for candidate in candidates:
        config = PobConfig(candidate)
        if config.layout == "installed" and not any(
            not path.exists() for label, path in required_pob_files(config).items() if not label.startswith("ExileLens")
        ):
            return candidate
    return None


def validate_pob_path(config: PobConfig) -> dict:
    missing = []
    for label, path in required_pob_files(config).items():
        if not path.exists():
            missing.append(label)
    if missing:
        looks_like_pob = any((config.pob_path / name).exists() for name in ("Data", "Modules", "Assets", "Launch.lua"))
        if looks_like_pob:
            message = (
                "This folder looks like a Path of Building installation, but required runtime files "
                f"could not be found: {', '.join(missing)}"
            )
        else:
            message = (
                "Path of Building files could not be found. Choose the installation folder "
                f"that contains Launch.lua and lua51.dll (missing: {', '.join(missing)})."
            )
        raise PobPathInvalid(message, {"missing": missing, "pob_path": str(config.pob_path), "layout": config.layout})

    head = None
    try:
        result = subprocess.run(
            ["git", "-C", str(config.pob_path), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
            # The frozen app is windowed; without this every probe flashes a console.
            creationflags=0x08000000 if sys.platform == "win32" else 0,
        )
        head = result.stdout.strip()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        head = None

    if head and head != config.supported_head:
        raise UnsupportedPobRevision(
            f"PoB HEAD {head} is not the tested revision {config.supported_head}",
            {"actual_head": head, "supported_head": config.supported_head},
        )

    return {
        "pob_path": str(config.pob_path),
        "layout": config.layout,
        "program_path": str(config.program_path),
        "runtime_path": str(config.runtime_path),
        "head": head,
        "supported_head": config.supported_head,
        "bridge_lua": str(config.bridge_lua),
    }


def fingerprint_hash(components: dict) -> str:
    payload = json.dumps(components, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
