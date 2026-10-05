"""Spec-aware audit of the two PyInstaller specs (pre-build: "the configuration is what we claim").

The specs are parsed with ``ast`` and never executed, so the audit compares structure (call keywords, list members), not
whole-file text. A passing audit says the CONFIGURATION is right; only a built artifact (``release_gate --require-artifact``)
proves what actually shipped.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

#: Qt modules that must be excluded from the GUI build (heavy stacks, and every module with no LGPL option in Qt 6.11.2).
GUI_REQUIRED_EXCLUDES = (
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtMultimedia",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtGraphs", "PySide6.QtHttpServer", "PySide6.QtNetworkAuth",
    "pytest", "unittest", "pip", "setuptools",
)
#: Nothing outside the standard library and exilelens may enter the updater.
UPDATER_REQUIRED_EXCLUDES = ("PySide6", "shiboken6", "cryptography", "cffi", "pycparser", "pytest")


class _Spec:
    def __init__(self, text: str) -> None:
        self.tree = ast.parse(text)
        self.assigns: dict[str, ast.expr] = {}
        for node in self.tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                self.assigns[node.targets[0].id] = node.value
        self.calls: dict[str, ast.Call] = {}
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id not in self.calls:
                self.calls[node.func.id] = node

    def kw(self, call: str, key: str) -> ast.expr | None:
        node = self.calls.get(call)
        if node is None:
            return None
        for keyword in node.keywords:
            if keyword.arg == key:
                return keyword.value
        return None

    def literal(self, node: ast.expr | None) -> Any:
        if node is None:
            return _MISSING
        if isinstance(node, ast.Name) and node.id in self.assigns:
            node = self.assigns[node.id]
        try:
            return ast.literal_eval(node)
        except (ValueError, SyntaxError):
            return _MISSING

    def source(self, node: ast.expr | None) -> str:
        """The expression with simple module-level names expanded one level (``icon=str(app_icon)`` -> its path expression)."""
        if node is None:
            return ""
        text = ast.unparse(node)
        for name, value in self.assigns.items():
            if name in text:
                text += " " + ast.unparse(value)
        return text


_MISSING = object()


def _list_of_str(spec: _Spec, node: ast.expr | None) -> list[str] | None:
    value = spec.literal(node)
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return value
    return None


def audit_gui_spec(text: str) -> list[str]:
    spec = _Spec(text)
    problems: list[str] = []
    analysis = spec.calls.get("Analysis")
    if analysis is None or not analysis.args:
        return ["GUI spec has no Analysis(...) entry list"]
    entry = spec.source(analysis.args[0])
    if '"app" / "main.py"' not in entry.replace("'", '"'):
        problems.append("GUI entry point is not src/exilelens/app/main.py")
    if spec.literal(spec.kw("Analysis", "hookspath")) != []:
        problems.append("GUI Analysis hookspath must be [] (no extra PyInstaller hook directories)")
    hooks = spec.source(spec.kw("Analysis", "runtime_hooks"))
    if "pyi_runtime_qt_dll.py" not in hooks:
        problems.append("GUI runtime hook pyi_runtime_qt_dll.py is not configured")
    excludes = _list_of_str(spec, spec.kw("Analysis", "excludes")) or []
    missing = [name for name in GUI_REQUIRED_EXCLUDES if name not in excludes]
    if missing:
        problems.append("GUI excludes lack " + ", ".join(missing))
    hidden = _list_of_str(spec, spec.kw("Analysis", "hiddenimports")) or []
    gpl = {name for name in GUI_REQUIRED_EXCLUDES if name.startswith("PySide6.Qt") and name.split(".")[-1] in (
        "QtCharts", "QtDataVisualization", "QtGraphs", "QtHttpServer", "QtNetworkAuth")}
    if gpl & set(hidden):
        problems.append("GUI hiddenimports pull a GPL-only Qt module")
    if "exilelens.ico" not in spec.source(spec.kw("EXE", "icon")):
        problems.append("GUI EXE icon is not assets/app/exilelens.ico")
    if "version_info.txt" not in spec.source(spec.kw("EXE", "version")):
        problems.append("GUI EXE version resource is not packaging/version_info.txt")
    if spec.literal(spec.kw("EXE", "upx")) is not False or spec.literal(spec.kw("COLLECT", "upx")) is not False:
        problems.append("GUI EXE and COLLECT must set upx=False")
    if spec.literal(spec.kw("EXE", "console")) is not False:
        problems.append("GUI EXE must be windowed (console=False)")
    if spec.literal(spec.kw("EXE", "exclude_binaries")) is not True or "COLLECT" not in spec.calls:
        problems.append("GUI build must be onedir (EXE exclude_binaries=True plus COLLECT)")
    if spec.literal(spec.kw("COLLECT", "name")) != "ExileLens" or spec.literal(spec.kw("EXE", "name")) != "ExileLens":
        problems.append("GUI EXE/COLLECT name must be ExileLens")
    for key in ("codesign_identity", "entitlements_file"):
        if spec.literal(spec.kw("EXE", key)) not in (None, _MISSING):
            problems.append(f"GUI EXE sets {key}: no code-signing configuration is expected")
    return problems


def audit_updater_spec(text: str) -> list[str]:
    spec = _Spec(text)
    problems: list[str] = []
    analysis = spec.calls.get("Analysis")
    if analysis is None or not analysis.args:
        return ["updater spec has no Analysis(...) entry list"]
    entry = spec.source(analysis.args[0]).replace("'", '"')
    if '"updater" / "__main__.py"' not in entry:
        problems.append("updater entry point is not src/exilelens/updater/__main__.py")
    hidden = _list_of_str(spec, spec.kw("Analysis", "hiddenimports"))
    if hidden is None or any(not name.startswith("exilelens.") for name in hidden):
        problems.append("updater hiddenimports must all be exilelens.* modules")
    excludes = _list_of_str(spec, spec.kw("Analysis", "excludes")) or []
    missing = [name for name in UPDATER_REQUIRED_EXCLUDES if name not in excludes]
    if missing:
        problems.append("updater excludes lack " + ", ".join(missing))
    for key in ("binaries", "datas", "runtime_hooks", "hookspath"):
        if spec.literal(spec.kw("Analysis", key)) not in ([], _MISSING):
            problems.append(f"updater Analysis {key} must be empty (nothing outside the stdlib and exilelens)")
    if "COLLECT" in spec.calls or spec.literal(spec.kw("EXE", "exclude_binaries")) is True:
        problems.append("updater must stay a single onefile executable (no COLLECT / exclude_binaries)")
    if spec.literal(spec.kw("EXE", "name")) != "ExileLensUpdater":
        problems.append("updater EXE name must be ExileLensUpdater")
    if "exilelens.ico" not in spec.source(spec.kw("EXE", "icon")):
        problems.append("updater EXE icon is not assets/app/exilelens.ico")
    if "version_info_updater.txt" not in spec.source(spec.kw("EXE", "version")):
        problems.append("updater EXE version resource is not packaging/version_info_updater.txt")
    if spec.literal(spec.kw("EXE", "upx")) is not False:
        problems.append("updater EXE must set upx=False")
    if spec.literal(spec.kw("EXE", "console")) is not True:
        problems.append("updater keeps its console behaviour (console=True)")
    for key in ("codesign_identity", "entitlements_file"):
        if spec.literal(spec.kw("EXE", key)) not in (None, _MISSING):
            problems.append(f"updater EXE sets {key}: no code-signing configuration is expected")
    return problems


def audit_specs(root: Path) -> list[str]:
    problems: list[str] = []
    for name, audit in (("exilelens-gui.spec", audit_gui_spec), ("exilelens-updater.spec", audit_updater_spec)):
        path = root / "packaging" / name
        if not path.is_file():
            problems.append(f"packaging/{name} missing")
            continue
        try:
            found = audit(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            found = [f"cannot parse: {exc.msg}"]
        problems.extend(f"packaging/{name}: {item}" for item in found)
    return problems
