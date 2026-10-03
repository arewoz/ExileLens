from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from exilelens.app.logging_setup import configure_logging
from exilelens.updater.install import run_recovery, run_update_job


def _default_updates_dir() -> Path:
    from exilelens.app.settings import app_data_dir
    from exilelens.updater.layout import UPDATES_DIR_NAME

    return app_data_dir() / UPDATES_DIR_NAME


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="exilelens-updater")
    parser.add_argument("job", type=Path, nargs="?", help="Path to the pending update job JSON")
    parser.add_argument("--recover", action="store_true", help="Roll back an interrupted install, then exit")
    parser.add_argument("--restart", action="store_true", help="With --recover: relaunch ExileLens afterwards")
    parser.add_argument("--updates-dir", type=Path, default=None, help="With --recover: ExileLens updates directory")
    args = parser.parse_args(argv)
    if not args.recover and args.job is None:
        parser.error("a job path is required unless --recover is given")
    configure_logging()
    log = logging.getLogger(__name__)
    if args.recover:
        updates_dir = args.updates_dir or _default_updates_dir()
        log.info("updater_recover_start")
        return run_recovery(updates_dir, restart=args.restart)
    log.info("updater_start job=%s", args.job)
    return run_update_job(args.job)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
