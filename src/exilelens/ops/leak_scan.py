"""Focused leak scanner for the release package and for the committed source tree. Not a general DLP engine.

NEVER prints or returns a matched value: a finding is only ``(category, relative path, count)``.

* ``scan_package`` inspects ``dist/ExileLens`` (and the final ZIP, including nested ``.zip`` members) for developer paths, key
  material, token-like strings, named secrets with real values, ``.dev.vars`` and development hosts.
* ``scan_source`` inspects tracked files for obviously committed credentials. Git history is out of scope.

A small explicit allowlist covers known-safe public test material (``ALLOWLIST``); anything else must be fixed at its source.
"""

from __future__ import annotations

import fnmatch
import io
import json
import re
import subprocess
import sys
import zipfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

#: (category, path glob) pairs that are known safe. Keep this tiny and documented.
ALLOWLIST: tuple[tuple[str, str], ...] = (
    # The PUBLIC test signing key: its private half is published on purpose so tests can sign fixtures; shipping builds never trust it.
    ("private-key-block", "fixtures/update_signing/test_signing_key.pem"),
    ("key-file", "fixtures/update_signing/test_signing_key.pem"),
    # A test that generates a throwaway key at run time and wraps it in PEM armour (no key material is committed).
    ("private-key-block", "cloud/test/patreon-lease.test.ts"),
    # An obviously fake token used to prove that diagnostics redact token-shaped strings.
    ("github-token", "public_tests/test_m4_4_diagnostics.py"),
)

_PLACEHOLDER = re.compile(
    rb"^(?:<[^>]*>|\$\{?[A-Za-z_][A-Za-z0-9_]*\}?|x{3,}|\*{3,}|\.{3,}|changeme|change-me|replace[-_ ]?me|your[-_ ].*|example.*|placeholder.*|dummy.*|fake.*|test.*|none|null|undefined|true|false|todo|redacted.*)$",
    re.IGNORECASE,
)

_NAMED_SECRETS = (
    "PATREON_ID_PEPPER", "PATREON_CLIENT_SECRET", "PATREON_WEBHOOK_SECRET", "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID",
    "EXILELENS_UPDATE_SIGNING_KEY_B64", "ENTITLEMENT_PRIVATE_KEY", "ENTITLEMENT_SIGNING_KEY", "TOKEN_ENCRYPTION_KEY",
    "DISCORD_RELEASE_WEBHOOK", "OAUTH_CLIENT_SECRET", "CLIENT_SECRET", "INSTALL_ID_PEPPER", "ERROR_ID_PEPPER",
)
_NAMED = re.compile(
    rb"(?P<name>" + b"|".join(n.encode() for n in _NAMED_SECRETS) + rb")[\"']?\s*[:=]\s*[\"']?(?P<value>[A-Za-z0-9+/=_\-]{8,})(?![A-Za-z0-9+/=_\-.(])"
)

# category -> compiled bytes regex (matched values are counted, never reported)
_PATTERNS: tuple[tuple[str, re.Pattern[bytes]], ...] = (
    # A PEM private-key BLOCK: the header followed by its base64 body (or RFC 1421 headers). The bare header string alone is not key
    # material: parsers such as Qt Network's QSslKey carry the delimiters as constants (NUL-separated), so those must not block a release.
    (
        "private-key-block",
        re.compile(rb"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----[ \t]*(?:\r?\n|\\n)(?:(?:Proc-Type|DEK-Info)[^\n]*\r?\n)*[A-Za-z0-9+/=]{40,}"),
    ),
    ("github-token", re.compile(rb"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{22,})")),
    ("discord-webhook-url", re.compile(rb"https://(?:discord|discordapp)\.com/api/webhooks/\d+/[A-Za-z0-9_\-]{20,}")),
    ("cloudflare-token-like", re.compile(rb"\b(?:cf|cloudflare)[_-]?(?:api[_-]?)?token[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9_\-]{36,}", re.IGNORECASE)),
    ("workers-dev-host", re.compile(rb"\b[A-Za-z0-9][A-Za-z0-9\-]{1,62}\.[A-Za-z0-9\-]{1,62}\.workers\.dev\b", re.IGNORECASE)),
)
_USER_PATH = re.compile(rb"(?<![A-Za-z0-9])[A-Za-z]:[\\/]+Users[\\/]+(?P<user>[^\\/\s\"'<>|*?:\x00]{1,64})[\\/]", re.IGNORECASE)
#: Windows profile folders that are not a person (no identity in them).
_GENERIC_USERS = {b"public", b"default", b"all users", b"default user", b"user", b"<user>", b"%username%", b"username", b"you", b"yourname", b"example"}

#: Third-party native libraries (.dll/.pyd, never ExileLens's own executables) carry the build-machine paths of THEIR upstream CI inside
#: panic/diagnostic strings: Qt's CI account ("qt") in every Qt binary and the GitHub-hosted runner account ("runneradmin") in the
#: cryptography wheel's Rust module. They are not ours, expose no one, and cannot be removed without rebuilding upstream binaries.
#: Only these two account names, only in third-party native files; any other user name, and every path in an ExileLens-built file,
#: still blocks the release.
UPSTREAM_CI_ACCOUNTS = frozenset({b"qt", b"runneradmin"})
_THIRD_PARTY_NATIVE_SUFFIXES = (".dll", ".pyd")

_FILENAME_RULES: tuple[tuple[str, str], ...] = (
    ("key-file", "*.pem"),
    ("key-file", "*.key"),
    ("dev-vars-file", ".dev.vars"),
    ("env-file", ".env"),
)

_SOURCE_SKIP_SUFFIXES = {".png", ".ico", ".webp", ".jpg", ".jpeg", ".gif", ".ttf", ".otf", ".woff", ".woff2", ".zip", ".pdf", ".exe", ".dll", ".pyd", ".pyc", ".svg"}
_MAX_FILE_BYTES = 64 * 1024 * 1024
_MAX_SOURCE_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class Finding:
    category: str
    path: str
    count: int

    def line(self) -> str:
        return f"{self.category}: {self.path} (x{self.count})"


def _allowed(category: str, rel: str) -> bool:
    return any(category == cat and fnmatch.fnmatch(rel.replace("\\", "/"), glob) for cat, glob in ALLOWLIST)


def _named_secret_count(data: bytes) -> int:
    count = 0
    for match in _NAMED.finditer(data):
        value = match.group("value")
        if _PLACEHOLDER.match(value) or len(set(value)) <= 2:
            continue
        # A name followed by another identifier-like token (for example an env var NAME on the right) is not a value.
        if value.isupper() and b"_" in value:
            continue
        count += 1
    return count


def scan_bytes(
    data: bytes, *, literals: tuple[bytes, ...] = (), paths: bool = True, ignore_users: frozenset[bytes] = frozenset()
) -> Counter[str]:
    """Counts of finding categories in ``data`` (values are never kept). ``paths`` is True for a built package: it also looks for
    developer paths and development hosts, which are legitimate in a source tree (docs, dev config)."""
    found: Counter[str] = Counter()
    for category, pattern in _PATTERNS:
        if category == "workers-dev-host" and not paths:
            continue
        hits = len(pattern.findall(data))
        if hits:
            found[category] += hits
    named = _named_secret_count(data)
    if named:
        found["named-secret-value"] += named
    if paths:
        user_hits = sum(
            1 for m in _USER_PATH.finditer(data) if m.group("user").lower() not in _GENERIC_USERS and m.group("user").lower() not in ignore_users
        )
        if user_hits:
            found["developer-user-path"] += user_hits
        for literal in literals:
            if literal and literal in data:
                found["build-machine-path"] += data.count(literal)
    return found


def _scan_named(rel: str, data: bytes, literals: tuple[bytes, ...], paths: bool, findings: list[Finding]) -> None:
    name = rel.replace("\\", "/").rsplit("/", 1)[-1]
    for category, glob in _FILENAME_RULES:
        if fnmatch.fnmatch(name.lower(), glob) and not _allowed(category, rel):
            findings.append(Finding(category, rel, 1))
    third_party_native = name.lower().endswith(_THIRD_PARTY_NATIVE_SUFFIXES) and not name.lower().startswith("exilelens")
    ignore = UPSTREAM_CI_ACCOUNTS if third_party_native else frozenset()
    for category, count in sorted(scan_bytes(data, literals=literals, paths=paths, ignore_users=ignore).items()):
        if not _allowed(category, rel):
            findings.append(Finding(category, rel, count))
    if name.lower() == "release_config.json":
        findings.extend(_release_config(rel, data))
    if name.lower().endswith(".zip") and len(data) <= _MAX_FILE_BYTES:
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as nested:
                for info in nested.infolist():
                    if info.is_dir() or info.file_size > _MAX_FILE_BYTES:
                        continue
                    _scan_named(f"{rel}!{info.filename}", nested.read(info), literals, paths, findings)
        except (zipfile.BadZipFile, OSError):
            pass


def _release_config(rel: str, data: bytes) -> list[Finding]:
    """The packaged cloud config may be empty or one https origin that is not a *.workers.dev development host."""
    try:
        config = json.loads(data.decode("utf-8-sig"))
        url = config.get("api_base_url", "")
        keys = set(config)
    except (ValueError, AttributeError, UnicodeError):
        return [Finding("release-config-invalid", rel, 1)]
    problems = []
    if keys - {"schema", "api_base_url"}:
        problems.append(Finding("release-config-unexpected-keys", rel, len(keys - {"schema", "api_base_url"})))
    if isinstance(url, str) and url.strip() and (not url.startswith("https://") or "workers.dev" in url.lower()):
        problems.append(Finding("release-config-host", rel, 1))
    return problems


def scan_package(root: Path, *, zip_path: Path | None = None, literals: tuple[str, ...] = ()) -> list[Finding]:
    """Scan every file under ``root`` (the packaged distribution) and, when given, the final ZIP."""
    # Each build-machine path in the three spellings a file can hold it: as is, forward slashes, and JSON-escaped backslashes.
    needles = tuple(
        {variant.encode("utf-8") for item in literals if item for variant in (item, item.replace("\\", "/"), item.replace("\\", "\\\\"))}
    )
    findings: list[Finding] = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        if path.stat().st_size > _MAX_FILE_BYTES:
            findings.append(Finding("file-too-large-to-scan", path.relative_to(root).as_posix(), 1))
            continue
        _scan_named(path.relative_to(root).as_posix(), path.read_bytes(), needles, True, findings)
    if zip_path is not None:
        try:
            with zipfile.ZipFile(zip_path) as archive:
                for info in archive.infolist():
                    if info.is_dir():
                        continue
                    if info.file_size > _MAX_FILE_BYTES:
                        findings.append(Finding("file-too-large-to-scan", f"{zip_path.name}!{info.filename}", 1))
                        continue
                    _scan_named(f"{zip_path.name}!{info.filename}", archive.read(info), needles, True, findings)
        except (zipfile.BadZipFile, OSError):
            findings.append(Finding("zip-unreadable", zip_path.name, 1))
    return findings


def _tracked_files(root: Path) -> list[Path]:
    try:
        out = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True, check=True).stdout
        return [root / item.decode("utf-8") for item in out.split(b"\x00") if item]
    except (OSError, subprocess.CalledProcessError):
        return [p for p in root.rglob("*") if p.is_file() and ".git" not in p.parts]


def scan_source(root: Path) -> list[Finding]:
    """Obvious committed credentials in tracked files (current tree only)."""
    findings: list[Finding] = []
    for path in _tracked_files(root):
        if not path.is_file() or path.suffix.lower() in _SOURCE_SKIP_SUFFIXES or path.stat().st_size > _MAX_SOURCE_BYTES:
            continue
        rel = path.relative_to(root).as_posix()
        _scan_named(rel, path.read_bytes(), (), False, findings)
    return findings


def format_findings(findings: list[Finding]) -> str:
    return "\n".join(f.line() for f in findings)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    pkg = sub.add_parser("package", help="scan dist/ExileLens (and the final ZIP)")
    pkg.add_argument("root", type=Path)
    pkg.add_argument("--zip", type=Path, default=None)
    pkg.add_argument("--literal", action="append", default=[], help="a build-machine path that must not appear (never printed)")
    src = sub.add_parser("source", help="scan tracked source files for committed credentials")
    src.add_argument("root", type=Path, nargs="?", default=Path("."))
    args = parser.parse_args(argv)
    if args.mode == "package":
        findings = scan_package(args.root.resolve(), zip_path=args.zip, literals=tuple(args.literal))
    else:
        findings = scan_source(args.root.resolve())
    if findings:
        print("LEAK SCAN: BLOCKED")
        print(format_findings(findings))
        return 1
    print("LEAK SCAN: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
