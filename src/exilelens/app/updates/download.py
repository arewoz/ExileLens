from __future__ import annotations

import hashlib
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from exilelens.app.updates.constants import DOWNLOAD_CHUNK_BYTES, DOWNLOAD_STALL_SECONDS, NETWORK_TIMEOUT_SECONDS


@dataclass(frozen=True)
class DownloadResult:
    path: Path
    sha256: str
    size: int


class DownloadError(RuntimeError):
    pass


class DownloadManager:
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
        destination.parent.mkdir(parents=True, exist_ok=True)
        part_path = destination.with_suffix(destination.suffix + ".part")
        resume_from = part_path.stat().st_size if part_path.is_file() else 0
        if resume_from > expected_size:
            part_path.unlink(missing_ok=True)
            resume_from = 0
        headers = {"User-Agent": "ExileLens-update-download"}
        if resume_from:
            headers["Range"] = f"bytes={resume_from}-"
        request = urllib.request.Request(url, headers=headers, method="GET")
        hasher = hashlib.sha256()
        if resume_from:
            with part_path.open("rb") as existing:
                while chunk := existing.read(DOWNLOAD_CHUNK_BYTES):
                    hasher.update(chunk)
        downloaded = resume_from
        last_byte_at = float(self._clock())
        try:
            with self._opener(request, timeout=NETWORK_TIMEOUT_SECONDS) as response:
                mode = "ab" if resume_from else "wb"
                with part_path.open(mode) as handle:
                    while True:
                        if self._cancel.is_set():
                            raise DownloadError("cancelled")
                        chunk = response.read(DOWNLOAD_CHUNK_BYTES)
                        if not chunk:
                            break
                        handle.write(chunk)
                        hasher.update(chunk)
                        downloaded += len(chunk)
                        last_byte_at = float(self._clock())
                        if on_progress is not None:
                            on_progress(downloaded, expected_size)
                        if float(self._clock()) - last_byte_at > DOWNLOAD_STALL_SECONDS:
                            raise DownloadError("stall_timeout")
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
            raise DownloadError("request_failed") from exc
        if downloaded != expected_size:
            raise DownloadError("size_mismatch")
        digest = hasher.hexdigest().lower()
        if digest != expected_sha256.lower():
            part_path.unlink(missing_ok=True)
            raise DownloadError("hash_mismatch")
        os.replace(part_path, destination)
        return DownloadResult(path=destination, sha256=digest, size=downloaded)

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
            else:
                on_finished(result)

        self._thread = threading.Thread(target=run, name="exilelens-update-download", daemon=True)
        self._thread.start()
        return True
