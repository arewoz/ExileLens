"""R2 structural security review: guarantees that must hold in the source tree itself."""

from __future__ import annotations

import ast
import re
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.smoke

ROOT = Path(__file__).resolve().parents[1]
CLOUD_PY = ROOT / "src" / "exilelens" / "cloud"
# The only committed private key material is the two TEST-ONLY signing fixtures.
ALLOWED_TEST_KEYS = {
    "fixtures/update_signing/test_signing_key.pem",
    "cloud/test/keys/entitlement-test-1.pkcs8.b64",
}
ED25519_PKCS8_B64_PREFIX = "MC4CAQAwBQYDK2VwBCIEI"


def _tracked_files() -> list[str]:
    if shutil.which("git") is None or not (ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    out = subprocess.run(["git", "-C", str(ROOT), "ls-files"], capture_output=True, text=True, check=True).stdout
    return [line for line in out.splitlines() if line]


def test_no_private_key_material_is_committed_besides_the_two_test_fixtures() -> None:
    offenders = []
    for name in _tracked_files():
        path = ROOT / name
        if not path.is_file() or path.stat().st_size > 2_000_000:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "-----BEGIN" in text and "PRIVATE KEY" in text or ED25519_PKCS8_B64_PREFIX in text:
            if name not in ALLOWED_TEST_KEYS:
                offenders.append(name)
    assert offenders == []


def test_production_signing_secrets_are_never_referenced_with_values() -> None:
    for name in _tracked_files():
        if not name.startswith((".github/", "cloud/", "scripts/", "src/")) or not (ROOT / name).is_file():
            continue
        if name.startswith("cloud/test/") or name in ("cloud/vitest.config.ts", "cloud/.dev.vars.example"):  # clearly fake test values
            continue
        text = (ROOT / name).read_text(encoding="utf-8", errors="ignore")
        # Secret *names* appear in workflows/docs; assigned literal values must not.
        assert not re.search(r"(PATREON_CLIENT_SECRET|ENTITLEMENT_SIGNING_KEY|TOKEN_ENC_KEY|ANALYTICS_PEPPER|DIAGNOSTIC_PEPPER|PATREON_ID_PEPPER)\s*[=:]\s*['\"](?!test|example|fake|dev-)[A-Za-z0-9+/=_-]{24,}['\"]", text), name


def test_telemetry_and_error_modules_know_nothing_about_patreon_or_entitlement() -> None:
    for name in ("contract", "sink", "telemetry", "errors", "store", "consent", "transparency", "wiring"):
        text = (CLOUD_PY / f"{name}.py").read_text(encoding="utf-8").lower()
        assert "patreon" not in text and "entitlement" not in text and "device_token" not in text, name


def test_patreon_modules_know_nothing_about_telemetry_ids_or_queues() -> None:
    for name in ("patreon", "entitlement"):
        text = (CLOUD_PY / f"{name}.py").read_text(encoding="utf-8")
        assert "analytics_id" not in text and "diagnostic_id" not in text and "exilelens.cloud.sink" not in text, name


def test_cloud_package_uses_only_the_standard_library_for_http() -> None:
    banned = {"requests", "httpx", "aiohttp", "urllib3", "sentry_sdk", "keyring"}
    for path in CLOUD_PY.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = [a.name.split(".")[0] for a in node.names] if isinstance(node, ast.Import) else [node.module.split(".")[0]] if isinstance(node, ast.ImportFrom) and node.module else []
            assert not (set(names) & banned), (path.name, names)


def test_item_check_hot_path_has_no_cloud_dependency() -> None:
    """The evaluation pipeline and hotkey code never import the cloud package."""
    offenders = []
    for rel in ("app/controller.py", "app/price_check_hotkey.py", "app/price_check_capture.py", "items", "analysis", "pob"):
        target = ROOT / "src" / "exilelens" / rel
        files = [target] if target.is_file() else list(target.rglob("*.py"))
        for path in files:
            if "exilelens.cloud" in path.read_text(encoding="utf-8", errors="ignore"):
                offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_update_and_entitlement_trust_material_is_disjoint() -> None:
    from exilelens.cloud import entitlement

    assert entitlement.key_sets_are_disjoint()
    assert entitlement.PRODUCTION_ENTITLEMENT_KEYS == {} or all(k.startswith("exilelens-entitlement-") for k in entitlement.PRODUCTION_ENTITLEMENT_KEYS)


def test_cloud_features_default_off_in_a_fresh_install() -> None:
    from exilelens.app.settings import AppSettings
    from exilelens.cloud.endpoint import release_config_url

    settings = AppSettings()
    assert settings.send_usage_stats is False and settings.send_error_reports is False
    assert release_config_url() is None  # the committed tree ships no cloud endpoint
