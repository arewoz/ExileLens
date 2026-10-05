"""1.0-A: licensing documentation consistency, the Qt LGPL route, GPL-only Qt exclusion, and the stable-by-default update channel."""

from __future__ import annotations

import ast
import json
import re
import shutil
from pathlib import Path

import pytest

from exilelens.ops.models import GateVerdict
from exilelens.ops.release_gate import (
    GPL_ONLY_QT_BINARY_TOKENS,
    _distribution_files,
    _gpl_only_qt,
    _license_documentation_problems,
    _locked_version,
)
from tests.test_release_1_0a_distribution import _fake_dist
from tests.test_release_gate import ROOT, _valid_root

pytestmark = pytest.mark.itemcheck


# ----------------------------------------------------------------------------------------- documents match the lock


def test_licensing_documents_agree_with_the_release_lock():
    assert _license_documentation_problems(ROOT) == []
    for package in ("PySide6", "shiboken6", "cryptography", "cffi", "pycparser", "pyinstaller"):
        assert _locked_version(ROOT, package), package


def test_the_notices_state_the_exact_versions_and_the_openssl_version_from_the_wheel_sbom():
    notices = (ROOT / "packaging" / "THIRD_PARTY_NOTICES.txt").read_text(encoding="utf-8")
    assert "Python runtime 3.12.10" in notices and (ROOT / ".python-version").read_text(encoding="utf-8").strip() == "3.12.10"
    assert "cryptography 50.0.0" in notices and "OpenSSL 4.0.1" in notices
    sbom = json.loads((ROOT / "packaging" / "third_party_licenses" / "cryptography" / "SBOM-openssl.json").read_text(encoding="utf-8"))
    assert {c["version"] for c in sbom["components"] if c["name"] == "openssl"} == {"4.0.1"}


@pytest.mark.parametrize(
    ("document", "needle", "replacement"),
    [
        ("THIRD_PARTY_NOTICES.txt", "cryptography 50.0.0", "cryptography 50.0.1"),
        ("THIRD_PARTY_NOTICES.txt", "OpenSSL 4.0.1", "OpenSSL 3.0.0"),
        ("THIRD_PARTY_NOTICES.txt", "Python runtime 3.12.10", "Python runtime 3.14.3"),
        ("QT_LGPL_COMPLIANCE.txt", "Qt                 6.11.2", "Qt                 6.9.0"),
        ("QT_LGPL_COMPLIANCE.txt", "Source code offer", "Source code details"),
    ],
)
def test_documentation_drift_is_blocked(tmp_path: Path, document: str, needle: str, replacement: str):
    root = _valid_root(tmp_path)
    path = root / "packaging" / document
    text = path.read_text(encoding="utf-8")
    assert needle in text
    path.write_text(text.replace(needle, replacement), encoding="utf-8")
    result = _distribution_files(root)
    assert result.status is GateVerdict.BLOCKED


def test_the_dependency_pin_in_the_lock_drives_the_check(tmp_path: Path):
    root = _valid_root(tmp_path)
    shutil.copyfile(ROOT / "packaging" / "requirements-release.lock", root / "packaging" / "requirements-release.lock")
    shutil.copyfile(ROOT / ".python-version", root / ".python-version")
    assert _license_documentation_problems(root) == []
    lock = root / "packaging" / "requirements-release.lock"
    lock.write_text(lock.read_text(encoding="utf-8").replace("cffi==2.1.1", "cffi==2.2.0"), encoding="utf-8")
    assert any("cffi" in problem for problem in _license_documentation_problems(root))


# ------------------------------------------------------------------------------------------------------- Qt LGPL route


def test_the_qt_compliance_notice_has_the_real_route_not_a_link():
    text = (ROOT / "packaging" / "QT_LGPL_COMPLIANCE.txt").read_text(encoding="utf-8")
    flat = " ".join(text.split())
    for required in (
        "LGPL-3.0",
        "6.11.2",
        "separate files",
        "interface-compatible",
        "py -3.12 -m pip install -e .",
        "scripts\\build_exe.ps1",
        "will provide, on request, the complete corresponding source code",
        "at least three years",
        "github.com/arewoz/ExileLens/issues",
        "reverse engineer",
    ):
        assert required in flat, required
    assert "qt-everywhere-src-6.11.2.tar.xz" in text and "pyside-setup-everywhere-src-6.11.2.tar.xz" in text


def test_the_notices_state_the_lgpl_route_precisely():
    flat = " ".join((ROOT / "packaging" / "THIRD_PARTY_NOTICES.txt").read_text(encoding="utf-8").split())
    for required in (
        "ExileLens uses these libraries under the GNU Lesser General Public License version 3",
        "dynamically loaded",
        "separate DLL files",
        "replace them with a modified, interface-compatible version",
        "free and open source under the MIT license",
        "QT_LGPL_COMPLIANCE.txt",
    ):
        assert required in flat, required


def test_the_lgpl_texts_are_the_qt_6_11_2_files_and_the_license_set_is_complete():
    lgpl = (ROOT / "packaging" / "third_party_licenses" / "qt" / "LGPL-3.0.txt").read_text(encoding="utf-8")
    assert "GNU LESSER GENERAL PUBLIC LICENSE" in lgpl and "Version 3, 29 June 2007" in lgpl
    gpl = (ROOT / "packaging" / "third_party_licenses" / "qt" / "GPL-3.0.txt").read_text(encoding="utf-8")
    assert "GNU GENERAL PUBLIC LICENSE" in gpl and "Version 3, 29 June 2007" in gpl
    python_license = (ROOT / "packaging" / "third_party_licenses" / "python" / "LICENSE.txt").read_text(encoding="utf-8")
    assert "PYTHON SOFTWARE FOUNDATION LICENSE VERSION 2" in python_license
    incorporated = (ROOT / "packaging" / "third_party_licenses" / "python" / "LICENSES-incorporated-software.rst").read_text(encoding="utf-8")
    assert "Licenses and Acknowledgements for Incorporated Software" in incorporated and "OpenSSL" in incorporated
    assert "Apache License" in (ROOT / "packaging" / "third_party_licenses" / "openssl" / "LICENSE.txt").read_text(encoding="utf-8")


def test_the_modules_exilelens_imports_are_all_lgpl_modules():
    """Qt modules in `src/` imports: Core, Gui, Widgets, Svg, Network. None of them is in the GPL-only list."""
    modules = set()
    for path in (ROOT / "src").rglob("*.py"):
        modules.update(re.findall(r"(?m)^\s*(?:from|import)\s+PySide6\.(Qt[A-Za-z0-9]+)", path.read_text(encoding="utf-8")))
    assert modules == {"QtCore", "QtGui", "QtWidgets", "QtSvg", "QtNetwork"}, modules
    for module in modules:
        assert not any(token.replace("qt6", "qt") in module.lower() for token in GPL_ONLY_QT_BINARY_TOKENS if "plugin" not in token)


# --------------------------------------------------------------------------------------------- GPL-only Qt exclusion


def test_the_spec_is_valid_python_and_filters_gpl_only_qt_binaries():
    spec = (ROOT / "packaging" / "exilelens-gui.spec").read_text(encoding="utf-8")
    ast.parse(spec)  # a syntax error here would only surface during a release build
    assert _gpl_only_qt(ROOT).status is GateVerdict.PASS
    match = re.search(r"_GPL_ONLY_QT_BINARY_TOKENS\s*=\s*\(([^)]*)\)", spec)
    assert tuple(re.findall(r'"([^"]+)"', match.group(1))) == GPL_ONLY_QT_BINARY_TOKENS
    assert "Qt Virtual Keyboard" in spec and "qtvirtualkeyboardplugin" in GPL_ONLY_QT_BINARY_TOKENS


def test_the_spec_never_imports_or_collects_a_gpl_only_pyside_module():
    spec = (ROOT / "packaging" / "exilelens-gui.spec").read_text(encoding="utf-8")
    hidden = spec[spec.index("hiddenimports = ["): spec.index("excludes = [")]
    for module in ("QtCharts", "QtDataVisualization", "QtGraphs", "QtHttpServer", "QtNetworkAuth", "QtVirtualKeyboard"):
        assert module not in hidden
    assert "collect_all" not in spec.replace("Do not use collect_all", "")


@pytest.mark.parametrize("token", GPL_ONLY_QT_BINARY_TOKENS)
def test_a_built_package_carrying_a_gpl_only_qt_binary_is_blocked(tmp_path: Path, token: str):
    root = _valid_root(tmp_path)
    shutil.copyfile(ROOT / "packaging" / "exilelens-gui.spec", root / "packaging" / "exilelens-gui.spec")
    dist = _fake_dist(root)
    assert _gpl_only_qt(root, required=True).status is GateVerdict.PASS
    plugin = dist / "_internal" / "PySide6" / "plugins" / "platforminputcontexts"
    plugin.mkdir(parents=True)
    (plugin / f"{token}.dll").write_bytes(b"MZ")
    result = _gpl_only_qt(root, required=True)
    assert result.status is GateVerdict.BLOCKED and token in result.detail


def test_a_spec_that_lost_the_filter_is_blocked(tmp_path: Path):
    root = _valid_root(tmp_path)
    spec = (ROOT / "packaging" / "exilelens-gui.spec").read_text(encoding="utf-8")
    (root / "packaging" / "exilelens-gui.spec").write_text(spec.replace("a.binaries = [", "a.binaries_unused = ["), encoding="utf-8")
    assert _gpl_only_qt(root).status is GateVerdict.BLOCKED


def test_the_gate_does_not_claim_the_built_inventory_before_a_package_exists():
    """Source-level pass says only that the spec filters; the artifact-level text appears only with --require-artifact."""
    assert "none in the built package" not in _gpl_only_qt(ROOT).detail
    assert "separate, still-open" in (ROOT / "src" / "exilelens" / "ops" / "release_gate.py").read_text(encoding="utf-8")


# --------------------------------------------------------------------------------------------------- update channel


def _release(version: str):
    from exilelens.app.updates.constants import GITHUB_RELEASES_URL
    from exilelens.app.updates.version import ExileLensVersion, Release

    parsed = ExileLensVersion.parse(version)
    return Release(parsed, GITHUB_RELEASES_URL, f"v{version}", not parsed.final)


class _Listed:
    def __init__(self, releases):
        from exilelens.app.updates.github import GitHubReleaseClient

        client = GitHubReleaseClient()
        client.list_releases = lambda per_page=30: list(releases)  # type: ignore[method-assign]
        self.client = client


def test_fresh_settings_default_to_the_stable_channel():
    from exilelens.app.settings import AppSettings
    from exilelens.app.updates.channels import UpdateChannel
    from exilelens.app.updates.service import UpdateService

    assert AppSettings().update_channel == "stable"
    assert AppSettings.from_dict({}).update_channel == "stable"
    assert UpdateService(AppSettings()).channel() is UpdateChannel.STABLE


@pytest.mark.parametrize("stored", ["beta", "BETA", "", None, "nightly", "stable"])
def test_a_legacy_profile_with_any_stored_channel_loads_as_stable(stored):
    from exilelens.app.settings import AppSettings

    assert AppSettings.from_dict({"schema_version": 22, "update_channel": stored}).update_channel == "stable"


def test_loading_a_beta_profile_from_disk_is_stable_in_memory_and_does_not_rewrite_the_file(tmp_path, monkeypatch):
    from exilelens.app import settings as settings_module

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    path = settings_module.settings_path()
    original = '{"schema_version": 22, "update_channel": "beta"}'
    path.write_text(original, encoding="utf-8")
    loaded = settings_module.load_settings()
    assert loaded.update_channel == "stable"
    assert path.read_text(encoding="utf-8") == original, "migration is in memory; loading never writes"


def test_migration_enables_nothing_and_touches_no_network(monkeypatch):
    import socket
    import urllib.request

    from exilelens.app.settings import AppSettings

    def refuse(*args, **kwargs):
        raise AssertionError("loading settings must not touch the network")

    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    loaded = AppSettings.from_dict({"schema_version": 22, "update_channel": "beta"})
    defaults = AppSettings()
    for field in ("send_usage_stats", "send_error_reports", "market_prices_enabled", "market_consent_version", "updates_auto_download",
                  "updates_install_on_exit", "last_seen_release_notes_version", "update_last_check_at", "update_last_error"):
        assert getattr(loaded, field) == getattr(defaults, field), field
    assert loaded.send_usage_stats is False and loaded.send_error_reports is False and loaded.market_prices_enabled is False


def test_stable_excludes_github_prereleases_and_accepts_a_newer_final_release():
    from exilelens.app.updates.channels import UpdateChannel

    client = _Listed([_release("0.7.0b1"), _release("1.0.0b1"), _release("1.0.0"), _release("1.1.0b1")]).client
    newest = client.best_newest_release_for_channel(UpdateChannel.STABLE)
    assert str(newest.version) == "1.0.0"
    assert _Listed([_release("1.1.0b1")]).client.best_newest_release_for_channel(UpdateChannel.STABLE) is None


def test_an_installed_prerelease_build_discovers_the_stable_1_0_0_through_the_service(monkeypatch):
    from exilelens.app.settings import AppSettings
    from exilelens.app.updates import service as service_module
    from exilelens.app.updates.version import ExileLensVersion

    assert ExileLensVersion.parse("1.0.0") > ExileLensVersion.parse("0.7.0b1")
    settings = AppSettings.from_dict({"update_channel": "beta"})  # the old implicit default
    service = service_module.UpdateService(settings, client=_Listed([_release("0.7.0b1"), _release("1.0.0"), _release("1.1.0b1")]).client)
    offered = service._newest_release_for_channel()
    assert str(offered.version) == "1.0.0"
    assert ExileLensVersion.parse("0.7.0b1") < offered.version


def test_the_default_channel_never_changes_a_stable_install_into_a_beta_follower():
    from exilelens.app.updates.channels import UpdateChannel

    assert UpdateChannel.parse(None) is UpdateChannel.STABLE
    assert UpdateChannel.parse("garbage") is UpdateChannel.STABLE
    assert UpdateChannel.parse("beta") is UpdateChannel.BETA  # reachable only by explicit code, never by default or by a stored profile
