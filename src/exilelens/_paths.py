from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def bundle_root() -> Path:
    """Directory containing bundled data files (e.g. runtime/lua)."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parents[2]


def repo_root() -> Path:
    """Project root in dev; onedir exe folder when frozen."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def runtime_lua_dir() -> Path:
    return bundle_root() / "runtime" / "lua"


def bridge_lua_path() -> Path:
    return runtime_lua_dir() / "bridge.lua"


def worker_init_lua_path() -> Path:
    return runtime_lua_dir() / "worker_init.lua"


def pob_headless_wrapper_path() -> Path:
    return runtime_lua_dir() / "pob_headless_wrapper.lua"


def pob_simplegraphic_def_path() -> Path:
    return runtime_lua_dir() / "pob_simplegraphic.def.lua"
