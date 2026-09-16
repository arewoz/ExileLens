from __future__ import annotations

import ctypes
import os
import sys
from contextlib import contextmanager
from ctypes import c_size_t, c_void_p
from pathlib import Path

from poe2value._paths import worker_init_lua_path
from poe2value.config import PobConfig, validate_pob_path
from poe2value.errors import PobBootFailed, raise_from_payload


@contextmanager
def _use_pob_src_cwd(src_path: Path):
    previous = os.getcwd()
    try:
        os.chdir(src_path)
        yield
    finally:
        os.chdir(previous)


class LuaHost:
    LUA_MULTRET = -1
    LUA_GLOBALSINDEX = -10002

    def __init__(self, config: PobConfig):
        validate_pob_path(config)
        self.config = config
        self._cwd_anchor = os.getcwd()
        self.lua = self._load_lua()
        self.state = self.lua.luaL_newstate()
        if not self.state:
            raise PobBootFailed("failed to create Lua state")
        self._booted = False

    def _load_lua(self):
        os.add_dll_directory(str(self.config.runtime_path))
        # Preload curl so PoB's lcurl.safe can LoadLibrary from headless LuaJIT.
        # Without this, package.loadlib fails with "the specified module could
        # not be found" because lua51.dll's loader does not see Python's
        # add_dll_directory for lcurl's dependents (libcurl, zlib).
        for name in ("zlib1.dll", "libcurl.dll", "lcurl.dll"):
            path = self.config.runtime_path / name
            if path.exists():
                try:
                    ctypes.CDLL(str(path))
                except OSError:
                    pass
        lua = ctypes.CDLL(str(self.config.lua_dll))
        lua.luaL_newstate.restype = c_void_p
        lua.luaL_openlibs.argtypes = [c_void_p]
        lua.luaL_loadfile.argtypes = [c_void_p, ctypes.c_char_p]
        lua.luaL_loadfile.restype = ctypes.c_int
        lua.luaL_loadstring.argtypes = [c_void_p, ctypes.c_char_p]
        lua.luaL_loadstring.restype = ctypes.c_int
        lua.lua_pcall.argtypes = [c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int]
        lua.lua_pcall.restype = ctypes.c_int
        lua.lua_tolstring.argtypes = [c_void_p, ctypes.c_int, ctypes.POINTER(c_size_t)]
        lua.lua_tolstring.restype = ctypes.c_char_p
        lua.lua_settop.argtypes = [c_void_p, ctypes.c_int]
        lua.lua_getfield.argtypes = [c_void_p, ctypes.c_int, ctypes.c_char_p]
        lua.lua_pushstring.argtypes = [c_void_p, ctypes.c_char_p]
        lua.lua_close.argtypes = [c_void_p]
        return lua

    def _restore_cwd(self) -> None:
        os.chdir(self._cwd_anchor)

    def _check(self, status: int, what: str) -> None:
        if status != 0:
            msg = self.lua.lua_tolstring(self.state, -1, None)
            text = msg.decode("utf-8", "replace") if msg else "?"
            self.close()
            raise PobBootFailed(f"Lua error during {what}: {text}")

    def _dostring(self, code: str, what: str) -> None:
        self._check(self.lua.luaL_loadstring(self.state, code.encode("utf-8")), what)
        self._check(self.lua.lua_pcall(self.state, 0, self.LUA_MULTRET, 0), what)

    def boot(self) -> None:
        if self._booted:
            return
        self.lua.luaL_openlibs(self.state)
        src = self.config.program_path.as_posix()
        runtime = self.config.runtime_path.as_posix()
        lua_modules = self.config.lua_modules_path.as_posix()
        bridge = self.config.bridge_lua.as_posix()
        headless_wrapper = self.config.headless_wrapper.as_posix()
        simplegraphic_def = self.config.simplegraphic_def.as_posix()
        worker_init = worker_init_lua_path().as_posix()
        prelude = f"""
            POE2VALUE_BRIDGE = "{bridge}"
            POE2VALUE_HEADLESS_WRAPPER = "{headless_wrapper}"
            POE2VALUE_SIMPLEGRAPHIC_DEF = "{simplegraphic_def}"
            POE2VALUE_POB_PROGRAM = "{src}"
            package.path = table.concat({{
                "{src}/?.lua", "{src}/?/init.lua",
                "{lua_modules}/?.lua", "{lua_modules}/?/init.lua",
                package.path }}, ";")
            package.cpath = table.concat({{ "{runtime}/?.dll", package.cpath }}, ";")
            arg = {{ [0] = "{worker_init}" }}
            io.stdout:setvbuf("no")
            io.stdout = io.stderr
        """
        self._dostring(prelude, "prelude")
        with _use_pob_src_cwd(self.config.program_path):
            self._check(
                self.lua.luaL_loadfile(self.state, worker_init.encode("utf-8")),
                "load worker_init",
            )
            self._check(self.lua.lua_pcall(self.state, 0, self.LUA_MULTRET, 0), "run worker_init")
        self._restore_cwd()
        self._booted = True

    def dispatch_json(self, payload: str) -> str:
        if not self._booted:
            self.boot()
        with _use_pob_src_cwd(self.config.program_path):
            self.lua.lua_getfield(self.state, self.LUA_GLOBALSINDEX, b"poe2value_dispatch")
            self.lua.lua_pushstring(self.state, payload.encode("utf-8"))
            self._check(self.lua.lua_pcall(self.state, 1, 1, 0), "dispatch")
            msg = self.lua.lua_tolstring(self.state, -1, None)
            self.lua.lua_settop(self.state, 0)
        self._restore_cwd()
        if not msg:
            raise PobBootFailed("dispatch returned empty response")
        return msg.decode("utf-8", "replace")

    def close(self) -> None:
        if getattr(self, "state", None):
            self.lua.lua_close(self.state)
            self.state = None
            self._booted = False
        self._restore_cwd()

    def __enter__(self):
        self.boot()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False
