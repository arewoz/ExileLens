"""The Status Rail: global status, navigation, community links and version.

Replaces the header bar, the left sidebar and the version footer with one fixed rail.
Full width is 208px; below :data:`theme.COMPACT_BREAKPOINT` it collapses to a 64px icon
rail. The text/icon axis is x = 24 for the status block, navigation, community links and
version (rail padding 12 + item border/padding 12), and is checked by the QA harness.
"""

from __future__ import annotations

from typing import Callable, Sequence

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from exilelens.ui import theme
from exilelens.ui.components import ElidedLabel, StatusDot
from exilelens.ui.dashboard_widgets import set_property
from exilelens.ui.status_model import AppStatus, derive_status
from exilelens.ui.ui_icons import apply_button_icon, outline_icon

#: (page id, visible label, outline icon for the compact rail)
NavItem = tuple[str, str, str]

_LINK_SPECS = (
    ("support", "Support ExileLens", "patreon",
     "Support the continued development of free, open-source ExileLens on Patreon."),
    ("discord", "Discord", "discord",
     "Join the ExileLens Discord for questions, feedback and community help."),
    ("issues", "Report an Issue", "github",
     "Open the ExileLens issue tracker on GitHub to report a bug."),
)


class _NavButton(QPushButton):
    """Navigation entry. Text in the wide rail, icon in the compact rail, optional count."""

    def __init__(self, page_id: str, label: str, icon_name: str, parent: QWidget | None = None) -> None:
        super().__init__(label, parent)
        self.page_id = page_id
        self._label = label
        self._icon_name = icon_name
        self.setObjectName("railNav")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setAccessibleName(label)
        self.setFixedHeight(theme.NAV_ITEM_HEIGHT + 4)
        self._count_label = QLabel("", self)
        self._count_label.setObjectName("railNavCount")
        self._count_label.hide()
        self._compact = False
        self._count = 0

    def label(self) -> str:
        return self._label

    def set_count(self, count: int) -> None:
        self._count = max(0, int(count))
        self.setAccessibleDescription(f"{self._count} items need attention" if self._count else "")
        self._sync_count()

    def set_compact(self, compact: bool) -> None:
        self._compact = compact
        if compact:
            icon = QIcon()
            idle = outline_icon(self._icon_name, theme.TEXT_BODY, 20).pixmap(20, 20)
            on = outline_icon(self._icon_name, theme.TEXT, 20).pixmap(20, 20)
            icon.addPixmap(idle, QIcon.Mode.Normal, QIcon.State.Off)
            icon.addPixmap(on, QIcon.Mode.Normal, QIcon.State.On)
            self.setIcon(icon)
            self.setIconSize(QSize(20, 20))
            self.setText("")
            self.setToolTip(self._label)
            self.setFixedSize(44, theme.NAV_ITEM_HEIGHT + 4)
        else:
            self.setIcon(QIcon())
            self.setText(self._label)
            self.setToolTip("")
            self.setMinimumWidth(0)
            self.setMaximumWidth(16777215)
            self.setFixedHeight(theme.NAV_ITEM_HEIGHT + 4)
        self._sync_count()
        self._place_count()

    def _sync_count(self) -> None:
        if self._count <= 0:
            self._count_label.hide()
            return
        if self._compact:
            self._count_label.setText("")
            self._count_label.setFixedSize(12, 12)
            self._count_label.setStyleSheet(
                f"background:{theme.WARN}; border-radius:6px; border:2px solid {theme.RAIL_BG};"
            )
        else:
            self._count_label.setStyleSheet("")
            self._count_label.setText(str(self._count))
            self._count_label.adjustSize()
        self._count_label.show()
        self._place_count()

    def _place_count(self) -> None:
        if self._count <= 0:
            return
        if self._compact:
            self._count_label.move(self.width() - 16, 2)
        else:
            self._count_label.adjustSize()
            self._count_label.move(self.width() - self._count_label.width() - 12, (self.height() - self._count_label.height()) // 2)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._place_count()


class _StatusBlock(QPushButton):
    """Three lines: dot + status word, build name, PoB connection. Click goes to Overview."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("railStatus")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self._dot = StatusDot("neutral")
        self._word = QLabel("")
        self._word.setObjectName("railStatusWord")
        self._build = ElidedLabel("")
        self._build.setObjectName("railBuildName")
        self._pob = ElidedLabel("")
        self._pob.setObjectName("railPobLine")
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(4)
        top.addWidget(self._dot, 0, Qt.AlignmentFlag.AlignVCenter)
        top.addWidget(self._word, 1, Qt.AlignmentFlag.AlignVCenter)
        self._top_row = top
        self._column = QVBoxLayout(self)
        self._column.setContentsMargins(10, 8, 10, 10)
        self._column.setSpacing(5)
        self._column.addLayout(top)
        self._column.addWidget(self._build)
        self._column.addWidget(self._pob)
        for child in (self._dot, self._word, self._build, self._pob):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._compact = False
        self._tone = "neutral"

    def sizeHint(self) -> QSize:  # noqa: N802 - a QPushButton ignores its child layout's size
        hint = self.layout().sizeHint()
        return QSize(max(hint.width(), 0), hint.height() + 4)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        hint = self.layout().minimumSize()
        return QSize(hint.width(), hint.height() + 4)

    def apply(self, status: AppStatus) -> None:
        self._tone = status.tone
        self._dot.set_status(status.tone)
        self._word.setText(status.label)
        color = theme.STATUS_COLORS.get(status.tone, theme.NEUTRAL)
        if status.tone == "neutral":
            color = theme.TEXT_BODY
        self._word.setStyleSheet(f"color:{color};")
        self._build.set_full_text(status.build_name)
        self._pob.set_full_text(status.pob_line)
        description = f"{status.label}. {status.build_name}. {status.pob_line}"
        self.setAccessibleName(description)
        self.setToolTip(description if self._compact else "")

    def set_compact(self, compact: bool) -> None:
        self._compact = compact
        for widget in (self._word, self._build, self._pob):
            widget.setVisible(not compact)
        if compact:
            self._column.setContentsMargins(0, 0, 0, 0)
            self._top_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.setFixedSize(44, 40)
            self._dot.set_dot_size(12)
        else:
            self._column.setContentsMargins(10, 8, 10, 10)
            self.setMinimumSize(0, 0)
            self.setMaximumSize(16777215, 16777215)
            self._dot.set_dot_size(theme.STATUS_DOT_SIZE)
        self.setToolTip(self.accessibleName() if compact else "")


class StatusRail(QWidget):
    navigate_requested = Signal(str)
    update_action_requested = Signal()

    def __init__(
        self,
        controller,
        settings,
        nav_groups: Sequence[Sequence[NavItem]],
        *,
        open_patreon: Callable[[], None],
        open_discord: Callable[[], None],
        open_issues: Callable[[], None],
        version_text: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self.settings = settings
        self.setObjectName("statusRail")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(theme.RAIL_WIDTH)
        self._compact = False
        self._status: AppStatus | None = None

        column = QVBoxLayout(self)
        column.setContentsMargins(12, 12, 12, 14)
        column.setSpacing(0)

        self._status_block = _StatusBlock()
        self._status_block.clicked.connect(lambda: self.navigate_requested.emit("overview"))
        column.addWidget(self._status_block, 0, Qt.AlignmentFlag.AlignTop)
        column.addSpacing(8)
        self._top_divider = self._divider()
        column.addWidget(self._top_divider)
        column.addSpacing(8)

        # No QButtonGroup: Qt treats a group of checkable buttons as one tab stop, so keyboard users could not
        # Tab to each destination. set_current() keeps exactly one button checked instead.
        self._nav_buttons: dict[str, _NavButton] = {}
        nav = QVBoxLayout()
        nav.setContentsMargins(0, 0, 0, 0)
        nav.setSpacing(2)
        self._nav_layout = nav
        for index, items in enumerate(nav_groups):
            if index:
                nav.addSpacing(10)
            for page_id, label, icon_name in items:
                button = _NavButton(page_id, label, icon_name)
                button.clicked.connect(lambda _checked=False, pid=page_id: self.navigate_requested.emit(pid))
                self._nav_buttons[page_id] = button
                nav.addWidget(button)
        column.addLayout(nav)
        column.addStretch(1)

        column.addWidget(self._divider())
        column.addSpacing(8)
        self._links: dict[str, QPushButton] = {}
        handlers = {"support": open_patreon, "discord": open_discord, "issues": open_issues}
        links = QVBoxLayout()
        links.setContentsMargins(0, 0, 0, 0)
        links.setSpacing(1)
        ui_scale = float(getattr(settings, "ui_scale", 1.0) or 1.0)
        self._link_separator = QFrame()
        self._link_separator.setObjectName("railDivider")
        self._link_separator.setFixedHeight(1)
        for key, label, icon_name, tooltip in _LINK_SPECS:
            button = QPushButton(label)
            button.setObjectName("railSupport" if key == "support" else "railLink")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            button.setFixedHeight(40 if key == "support" else 36)
            button.setToolTip(tooltip)
            button.setAccessibleName(label)
            apply_button_icon(button, icon_name, ui_scale=1.0)
            button.setIconSize(QSize(16, 16))
            button.clicked.connect(lambda _checked=False, fn=handlers[key]: fn())
            self._links[key] = button
            links.addWidget(button)
            if key == "support":
                links.addSpacing(5)
                links.addWidget(self._link_separator)
                links.addSpacing(5)
        column.addLayout(links)

        version_row = QVBoxLayout()  # the update action sits under the version so neither ever clips
        version_row.setContentsMargins(12, 10, 0, 0)
        version_row.setSpacing(2)
        self._version = QLabel(version_text)
        self._version.setObjectName("railVersion")
        self._update_button = QPushButton("")
        self._update_button.setObjectName("railUpdate")
        self._update_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self._update_button.clicked.connect(self.update_action_requested.emit)
        self._update_button.hide()
        version_row.addWidget(self._version, 0, Qt.AlignmentFlag.AlignLeft)
        version_row.addWidget(self._update_button, 0, Qt.AlignmentFlag.AlignLeft)
        self._version_row_widget = QWidget()
        self._version_row_widget.setLayout(version_row)
        column.addWidget(self._version_row_widget)

        for name in ("engine_ready", "build_changed", "baseline_state_changed", "value_profile_changed"):
            signal = getattr(controller, name, None)
            if signal is not None:
                signal.connect(lambda *_args: self.refresh())
        failed = getattr(controller, "engine_failed", None)
        if failed is not None:
            failed.connect(lambda *_args: self.refresh())
        status_changed = getattr(controller, "active_build_status_changed", None)
        if status_changed is not None:
            status_changed.connect(lambda *_args: self.refresh())
        hotkey = getattr(controller, "price_check_hotkey", None)
        if hotkey is not None and hasattr(hotkey, "diagnostics_changed"):
            hotkey.diagnostics_changed.connect(self.refresh)
        self.set_compact(False)
        self.refresh()

    # --- structure --------------------------------------------------------------

    @staticmethod
    def _divider() -> QFrame:
        line = QFrame()
        line.setObjectName("railDivider")
        line.setFixedHeight(1)
        return line

    def nav_buttons(self) -> dict[str, QPushButton]:
        return dict(self._nav_buttons)

    def link_buttons(self) -> dict[str, QPushButton]:
        return dict(self._links)

    def status_button(self) -> QPushButton:
        return self._status_block

    def status(self) -> AppStatus | None:
        return self._status

    def is_compact(self) -> bool:
        return self._compact

    def set_current(self, page_id: str) -> None:
        for key, button in self._nav_buttons.items():
            button.setChecked(key == page_id)

    def set_page_visible(self, page_id: str, visible: bool) -> None:
        button = self._nav_buttons.get(page_id)
        if button is not None:
            button.setVisible(visible)

    # --- state ------------------------------------------------------------------

    def refresh(self) -> None:
        status = derive_status(self.controller, self.settings)
        self._status = status
        self._status_block.apply(status)
        diag = self._nav_buttons.get("diagnostics")
        if diag is not None:
            diag.set_count(status.attention_count)

    def version_text(self) -> str:
        return self._version.text()

    def update_text(self) -> str:
        """The actionable update link label shown beside the version, or ''."""
        return self._update_button.text() if not self._update_button.isHidden() else ""

    def set_update_state(self, text: str) -> None:
        """``text`` is the actionable link label ("Update available", "Restart to update") or empty."""
        self._update_button.setText(text)
        self._update_button.setVisible(bool(text) and not self._compact)
        self._pending_update_text = text

    # --- responsive -------------------------------------------------------------

    def set_compact(self, compact: bool) -> None:
        self._compact = compact
        self.setFixedWidth(theme.COMPACT_RAIL_WIDTH if compact else theme.RAIL_WIDTH)
        layout = self.layout()
        if compact:
            layout.setContentsMargins(10, 10, 10, 12)
        else:
            layout.setContentsMargins(12, 12, 12, 14)
        self._status_block.set_compact(compact)
        for button in self._nav_buttons.values():
            button.set_compact(compact)
        for key, button in self._links.items():
            label = next(spec[1] for spec in _LINK_SPECS if spec[0] == key)
            # Re-resolve the stylesheet first: QStyleSheetStyle rewrites min/max sizes on repolish, which would
            # otherwise undo the fixed sizes set below.
            set_property(button, "compact", compact)
            if compact:
                button.setText("")
                button.setFixedSize(44, 40 if key == "support" else 36)
                button.setToolTip(label)
            else:
                button.setText(label)
                button.setMinimumWidth(0)
                button.setMaximumWidth(16777215)
                button.setFixedHeight(40 if key == "support" else 36)
                button.setToolTip(next(spec[3] for spec in _LINK_SPECS if spec[0] == key))
        self._version_row_widget.setVisible(not compact)
        self._update_button.setVisible(bool(self._update_button.text()) and not compact)
        if self._status is not None:
            self.refresh()
