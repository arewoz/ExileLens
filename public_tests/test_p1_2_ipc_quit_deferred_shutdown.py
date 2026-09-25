"""Regression coverage for the IPC-quit native abort fixed in P1.2.

``ExileLensApp._on_quit_requested`` runs nested inside QLocalSocket's own
readyRead delivery (InstanceServer -> quit_requested). Tearing the instance
server down synchronously from inside that call stack crashed with a native
"Fatal Python error: Aborted" on every ``--quit`` IPC shutdown, reproduced
from source. The fix defers teardown by a short real delay so the socket's
in-flight (overlapped, on Windows) I/O settles first. This test guards the
one property that matters: shutdown must not run synchronously inside
``_on_quit_requested`` itself.
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from exilelens.app.main import ExileLensApp


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_on_quit_requested_does_not_shut_down_synchronously() -> None:
    app = _app()
    fake_self = SimpleNamespace(_setup_dialog=None, shutdown=Mock())
    fake_self._finish_ipc_quit = lambda: ExileLensApp._finish_ipc_quit(fake_self)

    ExileLensApp._on_quit_requested(fake_self)

    # The whole point of the deferral: shutdown() (which destroys the very
    # InstanceServer/socket whose signal we are still nested inside) must not
    # have run yet when _on_quit_requested returns.
    fake_self.shutdown.assert_not_called()

    loop = QEventLoop()
    QTimer.singleShot(400, loop.quit)
    loop.exec()

    fake_self.shutdown.assert_called_once()


def test_finish_ipc_quit_shuts_down_and_exits_the_app() -> None:
    app = _app()
    fake_self = SimpleNamespace(shutdown=Mock())

    exit_mock = Mock()
    app.exit = exit_mock  # type: ignore[method-assign]
    try:
        ExileLensApp._finish_ipc_quit(fake_self)
    finally:
        del app.exit

    fake_self.shutdown.assert_called_once()
    exit_mock.assert_called_once_with(0)
