"""Static checks for startup-critical production modules."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from exilelens.ops.paths import repo_root

# Modules on the mandatory application startup path.
_STARTUP_PATHS = (
    "src/exilelens/app/main.py",
    "src/exilelens/ui/tray.py",
    "src/exilelens/ui/dashboard_window.py",
    "src/exilelens/ui/dashboard_pages.py",
    "src/exilelens/ui/update_actions.py",
    "src/exilelens/ui/ui_icons.py",
    "src/exilelens/app/updates/service.py",
)


def run_startup_static_check(*, root: Path | None = None) -> tuple[bool, str]:
    base = root or repo_root()
    targets = [str(base / rel) for rel in _STARTUP_PATHS]
    missing = [path for path in targets if not Path(path).is_file()]
    if missing:
        return False, f"missing startup modules: {', '.join(missing)}"

    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "ruff",
                "check",
                "--select",
                "F821",
                *targets,
            ],
            cwd=base,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return False, "ruff is not installed; pip install ruff to run startup static checks"
    if completed.returncode != 0:
        detail = (completed.stdout or "") + (completed.stderr or "")
        return False, detail.strip() or "ruff reported undefined-name violations"
    return True, "ok"


def main(argv: list[str] | None = None) -> int:
    ok, detail = run_startup_static_check()
    if not ok:
        print(detail, file=sys.stderr)
        return 1
    print(detail)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
