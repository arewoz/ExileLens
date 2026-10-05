"""1.0-C: the release-package leak scanner and the committed-source secret guard. Seeded values are built at run time so this file
itself stays clean under the source scan; no scan output may ever contain a matched value."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from exilelens.ops import leak_scan
from exilelens.ops.leak_scan import Finding, format_findings, scan_package, scan_source

pytestmark = pytest.mark.itemcheck

ROOT = Path(__file__).resolve().parents[1]

GH_TOKEN = "gh" + "p_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
PEM_HEADER = "-----BEGIN " + "PRIVATE KEY-----"
USER_PATH = "C:" + "\\Users\\" + "alice" + "\\AppData\\Local\\build\\x.py"
WEBHOOK = "https://discord" + ".com/api/webhooks/" + "123456789012345678/" + "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"
PEPPER_VALUE = "k9Zx" + "Q2mV7pLr4TyB"
WORKERS_HOST = "exilelens-dev" + ".acct" + ".workers" + ".dev"


def _write(root: Path, rel: str, data: bytes | str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
    return path


def _categories(findings: list[Finding]) -> set[str]:
    return {item.category for item in findings}


def test_a_clean_package_passes(tmp_path):
    _write(tmp_path, "ExileLens.exe", b"MZ" + b"\x00" * 64)
    _write(tmp_path, "README.txt", "Settings live in %LOCALAPPDATA%\\ExileLens. Example: C:\\Users\\You\\Builds\\a.xml")
    _write(tmp_path, "_internal/exilelens/cloud/release_config.json", json.dumps({"schema": 1, "api_base_url": ""}))
    assert scan_package(tmp_path) == []


@pytest.mark.parametrize(
    "rel,content,category",
    [
        ("a.txt", GH_TOKEN, "github-token"),
        ("a.txt", "x " + PEM_HEADER + "\nAAAA", "private-key-header"),
        ("a.bin", b"\x00\x01" + USER_PATH.encode() + b"\x00", "developer-user-path"),
        ("a.txt", WEBHOOK, "discord-webhook-url"),
        ("a.txt", "PATREON_ID_PEPPER=" + PEPPER_VALUE, "named-secret-value"),
        ("a.txt", 'CLOUDFLARE_API_TOKEN: "' + PEPPER_VALUE + 'abcdefghijklmnopqrstuvwxyz"', "named-secret-value"),
        ("a.txt", "endpoint " + WORKERS_HOST, "workers-dev-host"),
        ("cacert.pem", "public certificates", "key-file"),
        ("x/.dev.vars", "ANYTHING=1", "dev-vars-file"),
        ("x/id.key", "k", "key-file"),
    ],
)
def test_each_category_is_detected_and_no_value_is_ever_printed(tmp_path, rel, content, category):
    _write(tmp_path, rel, content)
    findings = scan_package(tmp_path)
    assert category in _categories(findings)
    report = format_findings(findings)
    for secret in (GH_TOKEN, PEPPER_VALUE, WEBHOOK, "alice", WORKERS_HOST):
        assert secret not in report
    assert report and all(len(item.line().split()) >= 3 for item in findings)  # category, path, count only


def test_placeholders_and_generic_profile_names_are_not_findings(tmp_path):
    _write(tmp_path, "a.txt", "PATREON_ID_PEPPER=<set with wrangler secret put>\nCLIENT_SECRET=changeme\nTOKEN_ENCRYPTION_KEY=${KEY}\n")
    _write(tmp_path, "b.txt", "C:\\Users\\Public\\Desktop and C:\\Users\\Default\\NTUSER and D:/Users/<user>/x")
    assert scan_package(tmp_path) == []


def test_the_build_machine_path_literal_is_a_finding_without_being_printed(tmp_path):
    root = "Q:\\ci-" + "workspace-7f3a"
    _write(tmp_path, "m.json", json.dumps({"p": root + "\\src"}))
    findings = scan_package(tmp_path, literals=(root,))
    assert "build-machine-path" in _categories(findings)
    assert "workspace-7f3a" not in format_findings(findings)


def test_release_config_rules(tmp_path):
    for body, bad in (
        ({"schema": 1, "api_base_url": "https://api.example.com"}, False),
        ({"schema": 1, "api_base_url": ""}, False),
        ({"schema": 1, "api_base_url": "http://api.example.com"}, True),
        ({"schema": 1, "api_base_url": "https://x" + ".workers" + ".dev"}, True),
        ({"schema": 1, "api_base_url": "https://api.example.com", "api_key": "x"}, True),
    ):
        folder = tmp_path / str(abs(hash(json.dumps(body))))
        _write(folder, "release_config.json", json.dumps(body))
        assert bool(scan_package(folder)) is bad, body
    _write(tmp_path / "broken", "release_config.json", "{")
    assert "release-config-invalid" in _categories(scan_package(tmp_path / "broken"))


def test_zip_members_and_nested_zips_are_scanned(tmp_path):
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w") as z:
        z.writestr("deep/leak.txt", USER_PATH)
    package = tmp_path / "dist"
    _write(package, "ok.txt", "fine")
    _write(package, "base_library.zip", inner.getvalue())
    archive = tmp_path / "release.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("ExileLens/ok.txt", "fine")
        z.writestr("ExileLens/secret.txt", GH_TOKEN)
    findings = scan_package(package, zip_path=archive)
    paths = {item.path for item in findings}
    assert any(p.startswith("base_library.zip!deep/") for p in paths)
    assert "release.zip!ExileLens/secret.txt" in paths
    assert "github-token" in _categories(findings)


def test_allowlist_is_small_explicit_and_path_specific():
    assert len(leak_scan.ALLOWLIST) <= 8
    assert all(path and "*" not in path.split("/")[0] for _, path in leak_scan.ALLOWLIST)
    assert ("private-key-header", "fixtures/update_signing/test_signing_key.pem") in leak_scan.ALLOWLIST


def test_source_scan_allows_the_public_test_key_and_nothing_else(tmp_path):
    key = _write(tmp_path, "fixtures/update_signing/test_signing_key.pem", PEM_HEADER + "\nAAAA\n-----END PRIVATE KEY-----")
    assert key.is_file()
    assert scan_source(tmp_path) == []
    _write(tmp_path, "other/real.pem", PEM_HEADER + "\nAAAA")
    _write(tmp_path, "notes.md", "token " + GH_TOKEN)
    found = {(f.category, f.path) for f in scan_source(tmp_path)}
    assert ("private-key-header", "other/real.pem") in found and ("key-file", "other/real.pem") in found
    assert ("github-token", "notes.md") in found


def test_source_scan_does_not_flag_development_hosts_or_example_files(tmp_path):
    _write(tmp_path, "docs/dev.md", "use " + WORKERS_HOST + " while developing")
    _write(tmp_path, "cloud/.dev.vars.example", "PATREON_ID_PEPPER=")
    assert scan_source(tmp_path) == []


def test_the_committed_tree_is_clean():
    """The same guard CI runs on every pull request (`python -m exilelens.ops.leak_scan source .`)."""
    findings = scan_source(ROOT)
    assert findings == [], format_findings(findings)


def test_cli_exit_codes_and_output_never_contain_values(tmp_path, capsys):
    _write(tmp_path, "leak.txt", GH_TOKEN)
    assert leak_scan.main(["package", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "LEAK SCAN: BLOCKED" in out and "github-token: leak.txt (x1)" in out and GH_TOKEN not in out
    clean = tmp_path / "clean"
    _write(clean, "ok.txt", "ok")
    assert leak_scan.main(["package", str(clean)]) == 0
