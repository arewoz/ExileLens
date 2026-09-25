"""User-facing release notes from git history. Not a commit dump."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from exilelens.ops.paths import repo_root

_INTERNAL = re.compile(
    r"^(chore|test|tests|refactor|docs|ci|build|style)(\(.+\))?:",
    re.I,
)
_SECTION_PREFIX = {
    "feat": "Added",
    "add": "Added",
    "added": "Added",
    "improve": "Improved",
    "improved": "Improved",
    "perf": "Improved",
    "fix": "Fixed",
    "fixed": "Fixed",
}


@dataclass
class ReleaseNotes:
    since_ref: str
    added: list[str] = field(default_factory=list)
    improved: list[str] = field(default_factory=list)
    fixed: list[str] = field(default_factory=list)
    compatibility: list[str] = field(default_factory=list)
    known_issues: list[str] = field(default_factory=list)
    omitted: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "since_ref": self.since_ref,
            "Added": self.added,
            "Improved": self.improved,
            "Fixed": self.fixed,
            "Compatibility": self.compatibility,
            "Known Issues": self.known_issues,
            "omitted_internal": self.omitted,
        }

    def format_text(self) -> str:
        lines = [f"Since {self.since_ref}"]
        for title, items in (
            ("Added", self.added),
            ("Improved", self.improved),
            ("Fixed", self.fixed),
            ("Compatibility", self.compatibility),
            ("Known Issues", self.known_issues),
        ):
            lines.append("")
            lines.append(title)
            if items:
                lines.extend(f"- {item}" for item in items)
            else:
                lines.append("- None")
        return "\n".join(lines).strip() + "\n"


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False)
    return result.stdout.strip()


def detect_since_ref(root: Path | None = None) -> str:
    base = root or repo_root()
    describe = _git(base, "describe", "--tags", "--abbrev=0")
    if describe and "fatal" not in describe.lower():
        return describe.splitlines()[0].strip()
    changelog = (base / "packaging" / "CHANGELOG.txt").read_text(encoding="utf-8")
    versions = re.findall(r"^(\d+\.\d+\.\d+\S*)\s*$", changelog, re.M)
    if len(versions) >= 2:
        return versions[1]
    return "HEAD~20"


def classify_subject(subject: str) -> str | None:
    text = subject.strip()
    if not text or _INTERNAL.match(text):
        return None
    lowered = text.lower()
    if "compat" in lowered or "pob" in lowered or "path of exile" in lowered:
        section = "Compatibility"
    else:
        prefix = text.split(":", 1)[0].lower()
        prefix = re.sub(r"\(.+\)", "", prefix)
        section = _SECTION_PREFIX.get(prefix, None)
        if section is None:
            if lowered.startswith("fix"):
                section = "Fixed"
            elif lowered.startswith("add") or lowered.startswith("feat"):
                section = "Added"
            else:
                section = "Improved"
    body = text.split(":", 1)[-1].strip() if ":" in text else text
    body = body[0].upper() + body[1:] if body else text
    return f"{section}\t{body}"


def collect_release_notes(*, root: Path | None = None, since_ref: str | None = None) -> ReleaseNotes:
    base = root or repo_root()
    since = since_ref or detect_since_ref(base)
    log = _git(base, "log", f"{since}..HEAD", "--pretty=format:%s")
    notes = ReleaseNotes(since_ref=since)
    seen: set[str] = set()
    for line in log.splitlines():
        classified = classify_subject(line.strip())
        if classified is None:
            notes.omitted += 1
            continue
        section, body = classified.split("\t", 1)
        if body.lower() in seen:
            continue
        seen.add(body.lower())
        getattr(notes, section.lower().replace(" ", "_")).append(body)
    return notes
