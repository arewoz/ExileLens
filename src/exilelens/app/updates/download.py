from __future__ import annotations

import hashlib
import os
import re
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from exilelens.app.updates.constants import DOWNLOAD_CHUNK_BYTES, DOWNLOAD_STALL_SECONDS, NETWORK_TIMEOUT_SECONDS

_CONTENT_RANGE_RE = re.compile(r"bytes\s+(\d+)-(\d+)/(\d+|\*)", re.IGNORECASE)


@dataclass(frozen=True)
class DownloadResult:
    path: Path
    sha256: str
    size: int


class DownloadError(RuntimeError):
    pass


class _RestartFromZero(Exception):
    """The server cannot continue the partial file; discard it and download from byte 0 once."""


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(DOWNLOAD_CHUNK_BYTES):
            hasher.update(chunk)
    return hasher.hexdigest().lower()


def _response_status(response) -> int:
    status = getattr(response, "status", None)
    if status is None and hasattr(response, "getcode"):
        status = response.getcode()
    return int(status) if status is not None else 200


def _response_header(response, name: str) -> str:
    headers = getattr(response, "headers", None)
    if headers is None:
        return ""
    try:
        return str(headers.get(name) or "")
    except Exception:  # noqa: BLE001 - foreign header containers
        return ""


class DownloadManager:
    """Single resumable downloader bound to the signed artifact size and SHA-256.

    Bytes beyond ``expected_size`` are never written. A ``.part`` file is only ever promoted to the final
    name after its full SHA-256 matches; partial or unverified data is never treated as a package.
    """

    def __init__(self, opener: Callable = urllib.request.urlopen, clock=time.time) -> None:
        self._opener = opener
        self._clock = clock
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None

    def cancel(self) -> None:
        self._cancel.set()

    def is_active(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def download(
        self,
        *,
        url: str,
        destination: Path,
        expected_size: int,
        expected_sha256: str,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> DownloadResult:
        self._cancel.clear()
        expected_sha256 = expected_sha256.lower()
        if expected_size <= 0:
            raise DownloadError("size_mismatch")
        destination.parent.mkdir(parents=True, exist_ok=True)
        part_path = destination.with_suffix(destination.suffix + ".part")
        resume_from = part_path.stat().st_size if part_path.is_file() else 0
        if resume_from > expected_size:
            part_path.unlink(missing_ok=True)
            resume_from = 0
        if resume_from == expected_size:
            # A complete .part from an interrupted finalization: verify locally, no request needed.
            if sha256_file(part_path) == expected_sha256:
                os.replace(part_path, destination)
                return DownloadResult(path=destination, sha256=expected_sha256, size=expected_size)
            part_path.unlink(missing_ok=True)
            resume_from = 0
        try:
            return self._fetch(url, destination, part_path, resume_from, expected_size, expected_sha256, on_progress)
        except _RestartFromZero:
            part_path.unlink(missing_ok=True)
            return self._fetch(url, destination, part_path, 0, expected_size, expected_sha256, on_progress)

    def _fetch(
        self,
        url: str,
        destination: Path,
        part_path: Path,
        resume_from: int,
        expected_size: int,
        expected_sha256: str,
        on_progress: Callable[[int, int], None] | None,
    ) -> DownloadResult:
        headers = {"User-Agent": "ExileLens-update-download"}
        if resume_from:
            headers["Range"] = f"bytes={resume_from}-"
        request = urllib.request.Request(url, headers=headers, method="GET")
        hasher = hashlib.sha256()
        downloaded = 0
        try:
            with self._opener(request, timeout=NETWORK_TIMEOUT_SECONDS) as response:
                mode = "wb"
                if resume_from:
                    status = _response_status(response)
                    if status == 206 and self._valid_content_range(response, resume_from, expected_size):
                        mode = "ab"
                        with part_path.open("rb") as existing:
                            while chunk := existing.read(DOWNLOAD_CHUNK_BYTES):
                                hasher.update(chunk)
                        downloaded = resume_from
                    elif status == 200:
                        # The server ignored the Range header and sent the whole file: start over from byte 0.
                        mode = "wb"
                    else:
                        raise _RestartFromZero()
                last_progress_at = float(self._clock())
                with part_path.open(mode) as handle:
                    while True:
                        if self._cancel.is_set():
                            raise DownloadError("cancelled")
                        chunk = response.read(DOWNLOAD_CHUNK_BYTES)
                        if not chunk:
                            break
                        now = float(self._clock())
                        if now - last_progress_at > DOWNLOAD_STALL_SECONDS:
                            # One chunk took longer than the stall budget (trickling connection).
                            raise DownloadError("stall_timeout")
                        last_progress_at = now
                        if downloaded + len(chunk) > expected_size:
                            handle.close()
                            part_path.unlink(missing_ok=True)
                            raise DownloadError("size_mismatch")
                        handle.write(chunk)
                        hasher.update(chunk)
                        downloaded += len(chunk)
                        if on_progress is not None:
                            on_progress(downloaded, expected_size)
        except urllib.error.HTTPError as exc:
            if resume_from and exc.code == 416:
                raise _RestartFromZero() from exc
            raise DownloadError("request_failed") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise DownloadError("request_failed") from exc
        if downloaded != expected_size:
            # Short read: keep the .part so the next attempt can resume it.
            raise DownloadError("size_mismatch")
        digest = hasher.hexdigest().lower()
        if digest != expected_sha256:
            part_path.unlink(missing_ok=True)
            raise DownloadError("hash_mismatch")
        os.replace(part_path, destination)
        return DownloadResult(path=destination, sha256=digest, size=downloaded)

    @staticmethod
    def _valid_content_range(response, resume_from: int, expected_size: int) -> bool:
        match = _CONTENT_RANGE_RE.fullmatch(_response_header(response, "Content-Range").strip())
        if match is None:
            return False
        start, _end, total = match.groups()
        if int(start) != resume_from:
            return False
        return total == "*" or int(total) == expected_size

    def start_background(
        self,
        *,
        url: str,
        destination: Path,
        expected_size: int,
        expected_sha256: str,
        on_progress: Callable[[int, int], None],
        on_finished: Callable[[DownloadResult | DownloadError], None],
    ) -> bool:
        if self.is_active():
            return False

        def run() -> None:
            try:
                result = self.download(
                    url=url,
                    destination=destination,
                    expected_size=expected_size,
                    expected_sha256=expected_sha256,
                    on_progress=on_progress,
                )
            except DownloadError as exc:
                on_finished(exc)
            except OSError:
                on_finished(DownloadError("disk_error"))
            else:
                on_finished(result)

        self._thread = threading.Thread(target=run, name="exilelens-update-download", daemon=True)
        self._thread.start()
        return True
