"""Shared item evaluation presentation panel for passive and pinned overlays."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from exilelens.ui.overlay_detail_drawer import DetailAnalysisDrawer

from exilelens.branding import APP_NAME
from exilelens.items.presentation import SurfaceMode
from exilelens.ui.styles import (
    CAP_STATE_COLOR,
    EMPHASIS_DELTA_COLOR,
    RARITY_COLOR,
    VERDICT_CLASS,
    VERDICT_COLOR,
)


class ItemOverlayPanel(QWidget):
    """Presentation body shared by passive gameplay overlay and pinned compare windows."""

    detail_toggled = Signal(bool)
    pin_clicked = Signal()
    retry_clicked = Signal()
    hint_dismissed = Signal()
    close_clicked = Signal()
    ring_choice_changed = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rarity_accent = "#c9a227"
        self._detail_expanded = False
        self._drawer_mode = "right"
        self._pending_companion: dict[str, Any] = {}
        self._pending_more_info: dict[str, Any] = {}
        self._pending_model: dict[str, Any] = {}
        self._pinned = False
        self._build_ui()
        self._surface_mode = SurfaceMode.PASSIVE_COMPACT.value

    @property
    def rarity_accent(self) -> str:
        return self._rarity_accent

    def _build_ui(self) -> None:
        self._outer = QHBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._outer.setSpacing(0)
        self._compact_column = QWidget()
        root = QVBoxLayout(self._compact_column)
        self._compact_root = root
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(8)
        self._name = QLabel(APP_NAME)
        self._name.setObjectName("nameLabel")
        self._name.setWordWrap(True)
        self._rarity = QLabel("")
        self._rarity.setObjectName("rarityLabel")
        self._rarity.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        self._close = QPushButton("×")
        self._close.setObjectName("overlayCloseButton")
        self._close.setFlat(True)
        self._close.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._close.setToolTip("Close")
        self._close.clicked.connect(self.close_clicked.emit)
        self._stale_banner = QLabel("")
        self._stale_banner.setObjectName("flagChip")
        self._stale_banner.hide()
        header.addWidget(self._name, 1)
        header.addWidget(self._stale_banner, 0)
        header.addWidget(self._rarity, 0)
        header.addWidget(self._close, 0, Qt.AlignmentFlag.AlignTop)

        self._base = QLabel("")
        self._base.setObjectName("baseLabel")

        # ITEM-UX-COMPRESS: the conclusion is read before the statistics, so the score
        # sits directly under the item identity and is the loudest thing in the card.
        self._score_headline = QLabel("")
        self._score_headline.setObjectName("scoreHeadline")
        self._score_headline.setWordWrap(True)
        self._score_headline.hide()
        self._compared_with = QLabel("")
        self._compared_with.setObjectName("compactNote")
        self._compared_with.setWordWrap(True)
        self._compared_with.hide()
        self._profile_line = QLabel("")
        self._profile_line.setObjectName("compactNote")
        self._profile_line.hide()

        self._baseline_strip = QWidget()
        self._baseline_strip.setObjectName("baselineStrip")
        strip = QVBoxLayout(self._baseline_strip)
        strip.setContentsMargins(8, 4, 8, 4)
        strip.setSpacing(1)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)
        self._baseline = QLabel("")
        self._baseline.setObjectName("baselineLabel")
        self._profile = QLabel("")
        self._profile.setObjectName("profileChip")
        top.addWidget(self._baseline, 1)
        top.addWidget(self._profile, 0)
        self._best_slot = QLabel("")
        self._best_slot.setObjectName("bestSlotLabel")
        self._reasons_title = QLabel("")
        self._reasons_title.setObjectName("warningTitle")
        self._reasons_title.hide()
        self._why_host = QWidget()
        self._why_layout = QVBoxLayout(self._why_host)
        self._why_layout.setContentsMargins(0, 0, 0, 0)
        self._why_layout.setSpacing(2)
        self._why_widgets: list[QWidget] = []
        self._multi_profile = QLabel("")
        self._multi_profile.setObjectName("multiProfileRow")
        self._multi_profile.setWordWrap(True)
        self._baseline_meta = QLabel("")
        self._baseline_meta.setObjectName("baselineMeta")
        self._pob_hint = QLabel("")
        self._pob_hint.setObjectName("pobBaselineHint")
        strip.addLayout(top)
        strip.addWidget(self._baseline_meta)
        strip.addWidget(self._pob_hint)

        self._badge = QLabel("")
        self._badge.setObjectName("flagChip")
        self._badge.hide()

        self._impact_title = QLabel("BUILD IMPACT")
        self._impact_title.setObjectName("warningTitle")
        self._impact_title.hide()

        self._metrics_host = QWidget()
        self._metrics_layout = QVBoxLayout(self._metrics_host)
        self._metrics_layout.setContentsMargins(0, 2, 0, 2)
        self._metrics_layout.setSpacing(7)
        self._metric_widgets: list[QWidget] = []

        self._slot_lines_host = QWidget()
        self._slot_lines_layout = QVBoxLayout(self._slot_lines_host)
        self._slot_lines_layout.setContentsMargins(0, 0, 0, 0)
        self._slot_lines_layout.setSpacing(1)
        self._slot_line_widgets: list[QWidget] = []
        self._slot_lines_host.hide()

        self._compact = QLabel("")
        self._compact.setObjectName("compactNote")
        self._compact.hide()

        self._offense_host = QWidget()
        self._offense_layout = QVBoxLayout(self._offense_host)
        self._offense_layout.setContentsMargins(0, 0, 0, 0)
        self._offense_layout.setSpacing(1)
        self._offense_title = QLabel("OFFENSE")
        self._offense_title.setObjectName("warningTitle")
        self._offense_line = QLabel("")
        self._offense_line.setObjectName("compactNote")
        self._offense_layout.addWidget(self._offense_title)
        self._offense_layout.addWidget(self._offense_line)
        self._offense_host.hide()

        self._current_edge_host = QWidget()
        self._current_edge_layout = QVBoxLayout(self._current_edge_host)
        self._current_edge_layout.setContentsMargins(0, 0, 0, 0)
        self._current_edge_layout.setSpacing(2)
        self._current_edge_title = QLabel("WHY CURRENT WINS")
        self._current_edge_title.setObjectName("warningTitle")
        self._current_edge_widgets: list[QWidget] = []
        self._current_edge_layout.addWidget(self._current_edge_title)
        self._current_edge_host.hide()

        self._best_use = QLabel("")
        self._best_use.setObjectName("compactNote")
        self._best_use.hide()

        self._build_fix_host = QWidget()
        self._build_fix_layout = QVBoxLayout(self._build_fix_host)
        self._build_fix_layout.setContentsMargins(0, 0, 0, 0)
        self._build_fix_layout.setSpacing(2)
        self._build_fix_title = QLabel("BUILD FIX")
        self._build_fix_title.setObjectName("warningTitle")
        self._build_fix_widgets: list[QWidget] = []
        self._build_fix_layout.addWidget(self._build_fix_title)
        self._build_fix_host.hide()

        self._axis_host = QWidget()
        self._axis_layout = QVBoxLayout(self._axis_host)
        self._axis_layout.setContentsMargins(0, 0, 0, 0)
        self._axis_layout.setSpacing(1)
        self._axis_title = QLabel("AXES")
        self._axis_title.setObjectName("warningTitle")
        self._axis_line = QLabel("")
        self._axis_line.setObjectName("compactNote")
        self._axis_line.setWordWrap(True)
        self._axis_layout.addWidget(self._axis_title)
        self._axis_layout.addWidget(self._axis_line)
        self._axis_host.hide()

        self._tradeoff_host = QWidget()
        self._tradeoff_layout = QVBoxLayout(self._tradeoff_host)
        self._tradeoff_layout.setContentsMargins(0, 0, 0, 0)
        self._tradeoff_layout.setSpacing(2)
        self._tradeoff_title = QLabel("TRADE-OFF")
        self._tradeoff_title.setObjectName("warningTitle")
        self._tradeoff_widgets: list[QWidget] = []
        self._tradeoff_layout.addWidget(self._tradeoff_title)
        self._tradeoff_host.hide()

        self._mods_host = QWidget()
        self._mods_layout = QVBoxLayout(self._mods_host)
        self._mods_layout.setContentsMargins(0, 0, 0, 0)
        self._mods_layout.setSpacing(2)
        self._mods_title = QLabel("MOST IMPORTANT ON THIS ITEM")
        self._mods_title.setObjectName("warningTitle")
        self._mods_widgets: list[QWidget] = []
        self._mods_layout.addWidget(self._mods_title)
        self._mods_host.hide()

        self._notes_host = QWidget()
        self._notes_layout = QVBoxLayout(self._notes_host)
        self._notes_layout.setContentsMargins(0, 0, 0, 0)
        self._notes_layout.setSpacing(2)
        self._note_widgets: list[QWidget] = []
        self._notes_host.hide()

        self._risk = QLabel("")
        self._risk.setObjectName("compactNote")
        self._risk.hide()

        self._warnings_host = QWidget()
        self._warnings_layout = QVBoxLayout(self._warnings_host)
        self._warnings_layout.setContentsMargins(0, 0, 0, 0)
        self._warnings_layout.setSpacing(6)
        self._warning_widgets: list[QWidget] = []

        self._verdict_band = QWidget()
        self._verdict_band.setObjectName("verdictBand")
        verdict_layout = QVBoxLayout(self._verdict_band)
        verdict_layout.setContentsMargins(10, 8, 10, 8)
        verdict_layout.setSpacing(3)
        self._build_value = QLabel("")
        self._build_value.setObjectName("compactNote")
        self._build_value.hide()
        self._verdict = QLabel("")
        self._verdict.setObjectName("verdictLabel")
        self._explain = QLabel("")
        self._explain.setObjectName("explainLabel")
        self._explain.setWordWrap(True)
        verdict_layout.addWidget(self._build_value)
        verdict_layout.addWidget(self._verdict)
        verdict_layout.addWidget(self._explain)

        self._value_caption = QLabel("")
        self._value_caption.setObjectName("valueCaption")
        self._value = QLabel("")
        self._value.setObjectName("valueLabel")
        self._value_anchor = QLabel("")
        self._value_anchor.setObjectName("compactNote")
        value_layout = QVBoxLayout()
        value_layout.setContentsMargins(2, 0, 2, 0)
        value_layout.setSpacing(1)
        value_layout.addWidget(self._value_caption)
        value_layout.addWidget(self._value)
        value_layout.addWidget(self._value_anchor)
        self._value_host = QWidget()
        self._value_host.setLayout(value_layout)
        self._price = QLabel("")
        self._price.setObjectName("priceLabel")
        self._price_note = QLabel("")
        self._price_note.setObjectName("compactNote")
        self._price_note.hide()
        self._power = QLabel("")
        self._power.setObjectName("priceLabel")

        self._rule_upgrade = _rule()
        self._why_not_upgrade_host = QWidget()
        self._why_not_upgrade_layout = QVBoxLayout(self._why_not_upgrade_host)
        self._why_not_upgrade_layout.setContentsMargins(0, 0, 0, 0)
        self._why_not_upgrade_layout.setSpacing(2)
        self._why_not_upgrade_title = QLabel("WHY NOT UPGRADE?")
        self._why_not_upgrade_title.setObjectName("warningTitle")
        self._why_not_upgrade_widgets: list[QWidget] = []
        self._upgrade_path_host = QWidget()
        self._upgrade_path_layout = QVBoxLayout(self._upgrade_path_host)
        self._upgrade_path_layout.setContentsMargins(0, 0, 0, 0)
        self._upgrade_path_layout.setSpacing(2)
        self._upgrade_path_title = QLabel("UPGRADE PATH")
        self._upgrade_path_title.setObjectName("warningTitle")
        self._upgrade_path_summary = QLabel("")
        self._upgrade_path_summary.setWordWrap(True)
        self._upgrade_path_summary.setObjectName("whyLabel")
        self._upgrade_path_after_repair = QLabel("")
        self._upgrade_path_after_repair.setWordWrap(True)
        self._upgrade_path_after_repair.setObjectName("compactNote")
        self._upgrade_path_after_repair.hide()
        self._upgrade_path_note = QLabel("")
        self._upgrade_path_note.setObjectName("compactNote")
        self._why_not_upgrade_layout.addWidget(self._why_not_upgrade_title)
        self._upgrade_path_layout.addWidget(self._upgrade_path_title)
        self._upgrade_path_layout.addWidget(self._upgrade_path_summary)
        self._upgrade_path_layout.addWidget(self._upgrade_path_after_repair)
        self._upgrade_path_layout.addWidget(self._upgrade_path_note)
        self._why_not_upgrade_host.hide()
        self._upgrade_path_host.hide()
        self._rule_upgrade.hide()

        self._analyzing = QLabel("Analyzing…")
        self._analyzing.setObjectName("analyzingLabel")
        self._analyzing.hide()
        self._error = QLabel("")
        self._error.setObjectName("errorLabel")
        self._error.hide()

        self._rule_metrics = _rule()
        self._rule_warnings = _rule()
        self._rule_verdict = _rule()
        self._rule_value = _rule()

        root.addLayout(header)
        root.addWidget(self._base)
        root.addWidget(self._score_headline)
        root.addWidget(self._compared_with)
        root.addWidget(self._profile_line)
        root.addWidget(self._baseline_strip)
        root.addWidget(self._best_slot)
        root.addWidget(self._badge, 0, Qt.AlignmentFlag.AlignLeft)
        root.addWidget(self._rule_metrics)
        root.addWidget(self._impact_title)
        root.addWidget(self._metrics_host)
        root.addWidget(self._slot_lines_host)
        root.addWidget(self._compact)
        root.addWidget(self._offense_host)
        root.addWidget(self._current_edge_host)
        root.addWidget(self._best_use)
        root.addWidget(self._build_fix_host)
        root.addWidget(self._axis_host)
        root.addWidget(self._reasons_title)
        root.addWidget(self._why_host)
        root.addWidget(self._notes_host)
        root.addWidget(self._tradeoff_host)
        root.addWidget(self._mods_host)
        root.addWidget(self._multi_profile)
        root.addWidget(self._rule_warnings)
        root.addWidget(self._warnings_host)
        root.addWidget(self._rule_verdict)
        root.addWidget(self._verdict_band)
        root.addWidget(self._rule_value)
        root.addWidget(self._value_host)
        root.addWidget(self._price)
        root.addWidget(self._price_note)
        root.addWidget(self._power)
        root.addWidget(self._rule_upgrade)
        root.addWidget(self._why_not_upgrade_host)
        root.addWidget(self._upgrade_path_host)
        root.addWidget(self._risk)
        self._retry = QPushButton("Retry")
        self._retry.setObjectName("retryButton")
        self._retry.setCursor(Qt.CursorShape.PointingHandCursor)
        self._retry.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._retry.hide()
        self._retry.clicked.connect(self.retry_clicked.emit)

        self._hotkey_hint = QLabel("Shift+C to analyze")
        self._hotkey_hint.setObjectName("hotkeyHint")
        self._hotkey_hint.setWordWrap(True)
        self._hotkey_hint.hide()
        self._hint_dismiss = QPushButton("×")
        self._hint_dismiss.setObjectName("hintDismissButton")
        self._hint_dismiss.setFlat(True)
        self._hint_dismiss.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hint_dismiss.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._hint_dismiss.clicked.connect(self._on_hint_dismiss)
        self._hint_dismiss.hide()

        self._more_info = QPushButton("More info ›")
        self._more_info.setObjectName("moreInfoButton")
        self._more_info.setFlat(True)
        self._more_info.setCursor(Qt.CursorShape.PointingHandCursor)
        self._more_info.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._more_info.hide()
        self._more_info.clicked.connect(self._on_more_info_clicked)

        self._pin_button = QPushButton("Pin")
        self._pin_button.setObjectName("footerPinButton")
        self._pin_button.setFlat(True)
        self._pin_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pin_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._pin_button.hide()
        self._pin_button.clicked.connect(self.pin_clicked.emit)

        self._footer = QWidget()
        self._footer.setObjectName("overlayFooter")
        footer_layout = QHBoxLayout(self._footer)
        footer_layout.setContentsMargins(0, 4, 0, 0)
        footer_layout.setSpacing(8)
        footer_layout.addWidget(self._pin_button, 0, Qt.AlignmentFlag.AlignLeft)
        footer_layout.addStretch(1)
        footer_layout.addWidget(self._more_info, 0, Qt.AlignmentFlag.AlignRight)

        root.addWidget(self._analyzing)
        root.addWidget(self._error)
        root.addWidget(self._retry, 0, Qt.AlignmentFlag.AlignLeft)
        hint_row = QHBoxLayout()
        hint_row.setContentsMargins(0, 0, 0, 0)
        hint_row.setSpacing(4)
        hint_row.addWidget(self._hotkey_hint, 1)
        hint_row.addWidget(self._hint_dismiss, 0, Qt.AlignmentFlag.AlignTop)
        root.addLayout(hint_row)
        root.addWidget(self._footer)

        self._drawer_divider = QFrame()
        self._drawer_divider.setObjectName("detailDrawerDivider")
        self._drawer_divider.setFrameShape(QFrame.Shape.VLine)
        self._drawer_divider.setFrameShadow(QFrame.Shadow.Plain)
        self._drawer_divider.setFixedWidth(1)
        self._drawer_divider.hide()
        self._drawer = DetailAnalysisDrawer(self)
        self._drawer.ring_choice_changed.connect(self.ring_choice_changed.emit)
        self._outer.addWidget(self._compact_column, 0)

    @property
    def detail_expanded(self) -> bool:
        return self._detail_expanded

    @property
    def drawer_layout_mode(self) -> str:
        return self._drawer_mode

    @property
    def detail_section_ids(self) -> list[str]:
        return self._drawer.section_ids

    def reset_detail_drawer(self) -> None:
        self._detail_expanded = False
        self._pending_companion = {}
        self._pending_more_info = {}
        self._pending_model = {}
        self._drawer.clear()
        self._drawer.hide()
        self._more_info.hide()
        self._more_info.setText("More info ›")
        self._apply_drawer_attachment()

    def bind_detail_content(
        self,
        companion: dict[str, Any],
        *,
        compact_surface: bool,
        more_info: dict[str, Any] | None = None,
        model: dict[str, Any] | None = None,
    ) -> None:
        self._pending_companion = dict(companion or {})
        self._pending_more_info = dict(more_info or {})
        self._pending_model = dict(model or {})
        payload = self._pending_more_info or self._pending_companion
        has_sections = bool(payload.get("sections"))
        show_footer = compact_surface and self._surface_mode == SurfaceMode.PASSIVE_COMPACT.value
        self._more_info.setVisible(has_sections and show_footer)
        self._pin_button.setVisible(show_footer)
        self._footer.setVisible(show_footer)
        if not has_sections:
            self.set_detail_expanded(False, notify=False)
        elif self._detail_expanded:
            self._drawer.set_content(payload, model=self._pending_model)

    def set_detail_expanded(self, expanded: bool, *, notify: bool = True) -> None:
        payload = self._pending_more_info or self._pending_companion
        if expanded and not payload.get("sections"):
            expanded = False
        if expanded == self._detail_expanded:
            return
        self._detail_expanded = expanded
        self._more_info.setText("Less info ‹" if expanded else "More info ›")
        if expanded:
            self._drawer.set_content(payload, model=self._pending_model)
        else:
            self._drawer.clear()
        self._apply_drawer_attachment()
        if notify:
            self.detail_toggled.emit(self._detail_expanded)

    def apply_drawer_layout(self, mode: str) -> None:
        self._drawer_mode = "right" if mode != "below" else "below"
        if self._detail_expanded:
            self._apply_drawer_attachment()

    def more_info_hover_rect_global(self) -> QRect:
        """Global rect of the More info control (tests / screenshots)."""
        if not self._more_info.isVisible():
            return QRect()
        top_left = self._more_info.mapToGlobal(QPoint(0, 0))
        rect = QRect(top_left, self._more_info.size())
        return rect.adjusted(-16, -8, 16, 8)

    def footer_pin_rect_global(self) -> QRect:
        if not self._pin_button.isVisible():
            return QRect()
        top_left = self._pin_button.mapToGlobal(QPoint(0, 0))
        return QRect(top_left, self._pin_button.size())

    def _on_more_info_clicked(self) -> None:
        self.set_detail_expanded(not self._detail_expanded)

    def _on_hint_dismiss(self) -> None:
        self.set_hotkey_hint_visible(False)
        self.hint_dismissed.emit()

    def set_hotkey_hint_visible(self, visible: bool) -> None:
        self._hotkey_hint.setVisible(visible)
        self._hint_dismiss.setVisible(visible)

    def set_hotkey_hint_text(self, text: str) -> None:
        """Show the configured chord instead of a hardcoded default.

        The constructor default ("Shift+C to analyze") is kept as the
        fallback so existing callers that never set a chord render exactly
        as before.
        """
        self._hotkey_hint.setText(text or "Shift+C to analyze")

    def set_pinned_state(self, pinned: bool) -> None:
        self._pinned = bool(pinned)
        self._pin_button.setText("Pinned" if self._pinned else "Pin")
        self._pin_button.setEnabled(not self._pinned)

    def _apply_drawer_attachment(self) -> None:
        self._outer.removeWidget(self._compact_column)
        self._outer.removeWidget(self._drawer_divider)
        self._outer.removeWidget(self._drawer)
        self._compact_root.removeWidget(self._drawer)

        if not self._detail_expanded:
            self._outer.addWidget(self._compact_column, 0)
            self._drawer_divider.hide()
            self._drawer.hide()
            return

        if self._drawer_mode == "below":
            self._outer.addWidget(self._compact_column, 1)
            self._compact_root.addWidget(self._drawer)
            self._drawer_divider.hide()
        else:
            self._outer.addWidget(self._compact_column, 0)
            self._outer.addWidget(self._drawer_divider, 0)
            self._outer.addWidget(self._drawer, 0)
            self._drawer_divider.show()
        self._drawer.setMaximumHeight(16777215)
        self._drawer.show()

    def set_title_prefix(self, prefix: str) -> None:
        self._name_prefix = prefix

    def show_analyzing(self) -> None:
        self.reset_detail_drawer()
        self._clear_metrics()
        self._clear_warnings()
        self._set_result_chrome_visible(False)
        self._error.hide()
        self._retry.hide()
        self._stale_banner.hide()
        self._analyzing.setText("Analyzing…")
        self._analyzing.show()
        self._name.setText("Analyzing item…")
        self._footer.hide()

    def show_warming(self) -> None:
        self.reset_detail_drawer()
        self._clear_metrics()
        self._clear_warnings()
        self._set_result_chrome_visible(False)
        self._error.hide()
        self._retry.hide()
        self._stale_banner.hide()
        self._analyzing.setText("Warming PoB…")
        self._analyzing.show()
        self._name.setText("Warming Path of Building…")
        self._footer.hide()

    def show_error(self, message: str, *, retry: bool = False, title: str = "", structured_hint: str = "") -> None:
        self.reset_detail_drawer()
        self._analyzing.hide()
        self._set_result_chrome_visible(False)
        self._clear_metrics()
        self._clear_warnings()
        self._stale_banner.hide()
        self._name.setText(title or "Could not analyze")
        body = message
        if structured_hint:
            body = f"{message}\n\n{structured_hint}"
        self._error.setText(body)
        self._error.show()
        self._retry.setVisible(retry)
        self._footer.hide()

    def show_timeout(self) -> None:
        """Non-terminal slow feedback; a late worker result still replaces this.

        No new engine call backs this: the exact cause (e.g. a build with many
        Jewel sockets, each requiring its own Path of Building pass) is not known
        cheaply at this point, so the copy stays truthful and general rather than
        guessing a specific reason or a live count.
        """
        self.reset_detail_drawer()
        self._analyzing.hide()
        self._set_result_chrome_visible(False)
        self._clear_metrics()
        self._clear_warnings()
        self._stale_banner.hide()
        self._name.setText("STILL ANALYZING")
        self._error.setText(
            "Path of Building is taking longer than usual. Builds with many Jewel "
            "sockets can take longer to evaluate."
        )
        self._error.show()
        self._retry.hide()
        self._footer.hide()

    def render_presentation(
        self,
        model: dict[str, Any],
        *,
        stale_reason: str = "",
        pin_label: str = "",
        inline_current_edge: bool = True,
        surface_mode: str = SurfaceMode.PASSIVE_COMPACT.value,
    ) -> None:
        self._surface_mode = str(surface_mode or SurfaceMode.PASSIVE_COMPACT.value)
        pinned_extended = self._surface_mode == SurfaceMode.PINNED_EXTENDED.value
        self._analyzing.hide()
        self._error.hide()
        self._retry.hide()
        title = model.get("item_name") or "Unknown item"
        if pin_label:
            title = f"{pin_label}  {title}"
        self._name.setText(title)
        if stale_reason:
            self._stale_banner.setText(f"STALE — {stale_reason}")
            self._stale_banner.show()
        else:
            self._stale_banner.hide()
        rarity = model.get("rarity") or ""
        self._rarity.setText(rarity)
        accent = RARITY_COLOR.get(rarity, "#c9a227")
        self._rarity.setStyleSheet(f"color: {accent};")
        self._rarity.setVisible(bool(rarity))
        self._rarity_accent = accent
        base = model.get("base_type") or ""
        self._base.setText(base)
        self._base.setVisible(bool(base))
        compact_surface = bool(model.get("compact_surface"))
        self._render_score_header(model, compact_surface=compact_surface)
        baseline = model.get("baseline_line") or ""
        self._baseline.setText(baseline)
        meta_line = model.get("baseline_meta") or ""
        self._baseline_meta.setText(meta_line)
        self._baseline_meta.setVisible(bool(meta_line))
        hint = model.get("pob_baseline_label") or ""
        self._pob_hint.setText(hint)
        self._pob_hint.setVisible(bool(hint))
        compared = model.get("compared_against") or {}
        if compared:
            details = [
                str(compared.get("title") or "COMPARED AGAINST"),
                str(compared.get("name") or ""),
                str(compared.get("base_type") or ""),
                str(compared.get("slot") or ""),
                f"PoB Item Set: {compared.get('item_set')}" if compared.get("item_set") else "",
                str(compared.get("source") or "PoB baseline"),
            ]
            self._baseline_strip.setToolTip("\n".join(part for part in details if part))
        else:
            self._baseline_strip.setToolTip("")
        profile = model.get("profile_indicator") or ""
        self._profile.setText(profile)
        self._profile.setVisible(bool(profile))
        self._baseline_strip.setVisible(bool(baseline or profile) and not compact_surface)
        compact_density = str(model.get("popup_density") or "COMPACT").upper() == "COMPACT"
        best_slot = model.get("best_slot_headline") or ""
        slot_alt = str(model.get("slot_alternate_line") or "").strip()
        if slot_alt and compact_density:
            best_slot = f"{best_slot}\n{slot_alt}" if best_slot else slot_alt
        self._best_slot.setText(best_slot)
        self._best_slot.setVisible(bool(best_slot))

        if compact_surface:
            why = list(model.get("primary_reasons") or [])
            reasons_title = str(model.get("primary_reasons_title") or "")
        else:
            reasons_title = ""
            why = list(model.get("why_reasons") or [])
            if inline_current_edge:
                if pinned_extended:
                    why = why[:3]
            else:
                why = []
        self._populate_why(why)
        self._why_host.setVisible(bool(why))
        self._reasons_title.setText(reasons_title)
        self._reasons_title.setVisible(bool(reasons_title) and bool(why))
        self._populate_notes(model.get("critical_notes") or [])

        profile_row = model.get("multi_profile_row") or []
        if profile_row and (pinned_extended or not compact_density):
            parts = [f"{row.get('label')}: {row.get('rating_text')}" for row in profile_row]
            self._multi_profile.setText(" · ".join(parts))
            self._multi_profile.setVisible(True)
        else:
            self._multi_profile.hide()

        badges = list(model.get("badges") or [])
        if pinned_extended:
            badges = [
                item
                for item in badges
                if item.get("id") != "offense_coverage_limited"
                and str(item.get("label") or "") != "OFFENSE COVERAGE LIMITED"
            ]
        if badges:
            self._badge.setText(str(badges[0].get("label") or "Low confidence"))
            self._badge.show()
        else:
            self._badge.hide()

        rows = model.get("impact_rows") if compact_surface else model.get("rows")
        rows = rows or []
        compact = model.get("compact_notes") or []
        self._populate_metrics(rows, hide_ranges=compact_surface)
        self._metrics_host.setVisible(bool(rows))
        self._impact_title.setText(str(model.get("impact_title") or "BUILD IMPACT"))
        self._impact_title.setVisible(compact_surface and bool(rows))
        self._compact.setText(" · ".join(compact))
        self._compact.setVisible(bool(compact))
        self._rule_metrics.setVisible(bool(rows or compact))
        self._populate_slot_lines(model.get("slot_verdict_lines") or [] if compact_surface else [])

        offense_summary = str(model.get("offense_summary") or "").strip()
        if offense_summary:
            self._offense_line.setText(offense_summary)
            self._offense_host.show()
        else:
            self._offense_host.hide()

        if inline_current_edge:
            self._populate_current_edge(model.get("current_edge") or {})
        else:
            self._populate_current_edge({})
        self._populate_build_fixes([] if not inline_current_edge else model.get("build_fixes") or [])
        self._populate_axes(model.get("axis_rows") or [])
        self._populate_tradeoffs(model.get("tradeoff_lines") or [])
        self._populate_important_mods(model.get("important_mods") or [])
        if str(model.get("decomposition_status") or "") == "PENDING" and pinned_extended:
            self._compact.setText((self._compact.text() + " · details pending").strip(" ·"))
            self._compact.show()

        best_use = model.get("best_use") or {}
        slot_options = model.get("slot_options") or {}
        option_rows = list(slot_options.get("options") or [])
        if pinned_extended and option_rows:
            parts = [str(slot_options.get("title") or "SLOT OPTIONS")]
            for option in option_rows:
                marker = "→" if option.get("selected") else " "
                verdict_text = str(option.get("verdict") or "").replace("_", " ").title()
                line = f"{marker} {option.get('slot')}: {option.get('rating_text')} · {verdict_text}"
                if option.get("blocked"):
                    line += " · blocked"
                parts.append(line)
            self._best_use.setText("\n".join(parts))
            self._best_use.show()
        elif best_use.get("headline"):
            title = str(best_use.get("title") or "BEST PROFILE")
            headline = best_use.get("headline_detailed") if pinned_extended else best_use.get("headline")
            text = f"{title}\n{headline}"
            runner = best_use.get("runner_up") or {}
            if pinned_extended and runner.get("label"):
                rating = runner.get("rating")
                rating_text = f" {rating:.0f}" if rating is not None else ""
                text += f"\nRunner-up: {runner.get('label')}{rating_text}"
            self._best_use.setText(text)
            self._best_use.show()
        else:
            self._best_use.hide()

        risk = model.get("risk_summary") or {}
        if risk.get("label") or risk.get("detail"):
            if pinned_extended:
                parts = ["RISK"]
                if risk.get("level"):
                    parts.append(str(risk.get("level")))
                if risk.get("label"):
                    parts.append(str(risk.get("label")))
                if risk.get("detail"):
                    parts.append(str(risk.get("detail")))
                self._risk.setText("\n".join(parts))
            else:
                self._risk.setText(f"RISK\n{risk.get('label')}")
            self._risk.show()
        else:
            self._risk.hide()

        groups = model.get("warning_groups") or []
        self._populate_warnings(groups)
        self._warnings_host.setVisible(bool(groups))
        self._rule_warnings.setVisible(bool(groups))

        verdict = model.get("verdict") or "UNRESOLVED"
        css_class = VERDICT_CLASS.get(verdict, "neutral")
        color = VERDICT_COLOR.get(css_class, "#b0a890")
        headline = model.get("verdict_label") or verdict
        if compact_surface:
            self._verdict.setText(str(model.get("overall_line") or headline))
        else:
            self._verdict.setText(headline)
            tag = model.get("recommendation_tag") or ""
            if tag:
                self._verdict.setText(f"{headline} · {tag}")
        build_value_line = str(model.get("build_value_line") or "")
        self._build_value.setText(build_value_line)
        self._build_value.setVisible(compact_surface and bool(build_value_line))
        self._verdict.setStyleSheet(f"color: {color};")
        explanation = model.get("verdict_explanation") or ""
        self._explain.setText(explanation)
        self._explain.setVisible(bool(explanation) and not compact_surface)
        self._verdict_band.setVisible(not compact_surface)
        self._rule_verdict.setVisible(not compact_surface)

        value = model.get("value") or {}
        rating = value.get("rating")
        if rating is not None:
            if pinned_extended:
                caption = "Score"
            else:
                caption = value.get("caption") or f"{value.get('profile_label') or value.get('profile') or 'Balanced'} SWAP SCORE"
            self._value_caption.setText(caption)
            self._value.setText(value.get("rating_text") or f"{rating:.0f}")
            anchor = str(value.get("anchor_text") or "").strip()
            if anchor:
                self._value_anchor.setText(anchor)
                self._value_anchor.show()
            else:
                self._value_anchor.hide()
            self._value_caption.show()
            self._value.show()
            self._value_host.show()
        else:
            self._value_caption.hide()
            self._value.hide()
            self._value_anchor.hide()
            self._value_host.hide()

        price = model.get("price")
        if price:
            prefix = str(price.get("label_prefix") or "Price").strip()
            amount_label = str(price.get("label") or "").strip()
            self._price.setText(f"{prefix:<14}{amount_label}")
            note_lines: list[str] = []
            rank = price.get("session_rank")
            total = price.get("session_total")
            if rank and total:
                note_lines.append(f"#{rank} / {total}")
            if price.get("is_best_value"):
                note_lines.append("★ BEST VALUE SO FAR")
            if price.get("is_new_best"):
                note_lines.append("NEW PERSONAL BEST")
            self._price_note.setText("\n".join(note_lines))
            self._price_note.setVisible(bool(note_lines))
            classification = price.get("classification_label") or str(price.get("classification") or "").replace("_", " ")
            ppc = price.get("power_per_currency")
            if ppc is not None and classification:
                self._power.setText(
                    f"VALUE / COST    {ppc:+.1f} Build Value / {price.get('currency') or ''} · {classification}"
                )
            elif classification:
                self._power.setText(f"Power / Cost    {classification}")
            else:
                self._power.hide()
            self._price.show()
            if ppc is not None or classification:
                self._power.show()
        else:
            self._price.hide()
            self._price_note.hide()
            self._power.hide()
        self._rule_value.setVisible(rating is not None or bool(price))
        why_not = list(model.get("why_not_upgrade") or [])
        if inline_current_edge:
            why_not = why_not or list((model.get("upgrade_path") or {}).get("why_not_upgrade") or [])
        self._populate_why_not_upgrade(
            why_not,
            title=str(model.get("why_section_title") or ""),
        )
        self._populate_upgrade_path(model.get("upgrade_path") or {}, pinned_extended=pinned_extended)
        if compact_surface and self._surface_mode == SurfaceMode.PASSIVE_COMPACT.value:
            self.bind_detail_content(
                model.get("companion") or {},
                compact_surface=True,
                more_info=model.get("more_info") or {},
                model=model,
            )
        elif compact_surface and self._surface_mode == SurfaceMode.PINNED_EXTENDED.value:
            self._more_info.hide()
            self._pin_button.setVisible(True)
            self.set_pinned_state(True)
            self._footer.show()
        else:
            self._more_info.hide()
            if not compact_surface:
                self._footer.hide()

    def _render_score_header(self, model: dict[str, Any], *, compact_surface: bool) -> None:
        """Verdict immediately under the item identity. Compact never shows a score."""
        headline = str(model.get("verdict_headline") or model.get("overall_line") or "")
        show = compact_surface and bool(headline)
        self._score_headline.setText(headline)
        self._score_headline.setVisible(show)
        if show:
            color = VERDICT_COLOR.get(str(model.get("score_class") or model.get("verdict_class") or ""), "#e4d8c4")
            self._score_headline.setStyleSheet(f"color: {color};")
        compared = str(model.get("compared_with_line") or model.get("replacing_line") or "")
        self._compared_with.setText(compared)
        self._compared_with.setVisible(compact_surface and bool(compared))
        profile_line = str(model.get("profile_line") or "")
        self._profile_line.setText(profile_line)
        self._profile_line.setVisible(compact_surface and bool(profile_line))

    def _populate_slot_lines(self, lines: list[dict[str, Any]]) -> None:
        for widget in self._slot_line_widgets:
            self._slot_lines_layout.removeWidget(widget)
            widget.deleteLater()
        self._slot_line_widgets.clear()
        if not lines:
            self._slot_lines_host.hide()
            return
        for item in lines:
            text = str(item.get("text") if isinstance(item, dict) else item).strip()
            if not text:
                continue
            label = QLabel(text)
            label.setObjectName("slotVerdictLine")
            label.setWordWrap(True)
            self._slot_lines_layout.addWidget(label)
            self._slot_line_widgets.append(label)
        self._slot_lines_host.setVisible(bool(self._slot_line_widgets))

    def _populate_notes(self, notes: list[Any]) -> None:
        """Short semantic warnings — never a second reading of a delta already shown."""
        for widget in self._note_widgets:
            self._notes_layout.removeWidget(widget)
            widget.deleteLater()
        self._note_widgets.clear()
        lines = [str(note.get("text") if isinstance(note, dict) else note).strip() for note in notes or []]
        lines = [line for line in lines if line]
        if not lines:
            self._notes_host.hide()
            return
        for line in lines:
            label = QLabel(line)
            label.setObjectName("warningLabel")
            label.setWordWrap(True)
            label.setStyleSheet("color: #e58b8b;")
            self._notes_layout.addWidget(label)
            self._note_widgets.append(label)
        self._notes_host.show()

    def _set_result_chrome_visible(self, visible: bool) -> None:
        self._verdict_band.setVisible(visible)
        self._explain.setVisible(visible)
        self._value_caption.setVisible(visible)
        self._value.setVisible(visible)
        self._value_anchor.setVisible(visible and bool(self._value_anchor.text()))
        self._value_host.setVisible(visible)
        self._price.setVisible(visible)
        self._price_note.setVisible(visible and bool(self._price_note.text()))
        self._power.setVisible(visible)
        self._baseline_strip.setVisible(visible)
        self._build_fix_host.setVisible(visible)
        self._axis_host.setVisible(visible)
        self._tradeoff_host.setVisible(visible)
        self._mods_host.setVisible(visible)
        self._baseline_meta.setVisible(visible)
        self._pob_hint.setVisible(visible)
        self._base.setVisible(visible)
        self._rarity.setVisible(visible)
        self._badge.setVisible(visible)
        self._compact.setVisible(visible)
        self._metrics_host.setVisible(visible)
        self._warnings_host.setVisible(visible)
        self._rule_metrics.setVisible(visible)
        self._rule_warnings.setVisible(visible)
        self._rule_verdict.setVisible(visible)
        self._rule_value.setVisible(visible)
        self._score_headline.setVisible(visible and bool(self._score_headline.text()))
        self._compared_with.setVisible(visible and bool(self._compared_with.text()))
        self._profile_line.setVisible(visible and bool(self._profile_line.text()))
        self._impact_title.setVisible(visible and bool(self._impact_title.isVisible()))
        self._reasons_title.setVisible(visible and bool(self._reasons_title.text()))
        self._notes_host.setVisible(visible and bool(self._note_widgets))
        self._build_value.setVisible(visible and bool(self._build_value.text()))

    def _populate_current_edge(self, block: dict[str, Any]) -> None:
        for widget in self._current_edge_widgets:
            self._current_edge_layout.removeWidget(widget)
            widget.deleteLater()
        self._current_edge_widgets.clear()
        lines = list(block.get("lines") or [])
        if not lines:
            self._current_edge_host.hide()
            return
        title = str(block.get("title") or "WHY CURRENT WINS")
        self._current_edge_title.setText(title)
        for line in lines[:3]:
            text = str(line.get("text") if isinstance(line, dict) else line)
            lbl = QLabel(text)
            lbl.setObjectName("whyLabel")
            lbl.setWordWrap(True)
            self._current_edge_layout.addWidget(lbl)
            self._current_edge_widgets.append(lbl)
        self._current_edge_host.show()

    def _populate_build_fixes(self, fixes: list[str]) -> None:
        for widget in self._build_fix_widgets:
            self._build_fix_layout.removeWidget(widget)
            widget.deleteLater()
        self._build_fix_widgets.clear()
        if not fixes:
            self._build_fix_host.hide()
            return
        for line in fixes[:3]:
            lbl = QLabel(str(line))
            lbl.setObjectName("whyLabel")
            lbl.setWordWrap(True)
            lbl.setStyleSheet("color: #9fd6a8;")
            self._build_fix_layout.addWidget(lbl)
            self._build_fix_widgets.append(lbl)
        self._build_fix_host.show()

    def _populate_axes(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            self._axis_host.hide()
            return
        parts = []
        for row in rows:
            parts.append(str(row.get("text") or ""))
        self._axis_line.setText("\n".join(parts))
        self._axis_host.show()

    def _populate_tradeoffs(self, lines: list[dict[str, Any]]) -> None:
        for widget in self._tradeoff_widgets:
            self._tradeoff_layout.removeWidget(widget)
            widget.deleteLater()
        self._tradeoff_widgets.clear()
        if not lines:
            self._tradeoff_host.hide()
            return
        for item in lines[:3]:
            text = str(item.get("text") or item.get("detail") or item)
            lbl = QLabel(text)
            lbl.setObjectName("whyLabel")
            lbl.setWordWrap(True)
            lbl.setStyleSheet("color: #e8d7b0;")
            self._tradeoff_layout.addWidget(lbl)
            self._tradeoff_widgets.append(lbl)
        self._tradeoff_host.show()

    def _populate_important_mods(self, rows: list[dict[str, Any]]) -> None:
        for widget in self._mods_widgets:
            self._mods_layout.removeWidget(widget)
            widget.deleteLater()
        self._mods_widgets.clear()
        if not rows:
            self._mods_host.hide()
            return
        for item in rows[:4]:
            stars = str(item.get("stars") or "—")
            label = str(item.get("label") or item.get("text") or "")
            lbl = QLabel(f"{stars}  {label}")
            lbl.setObjectName("whyLabel")
            lbl.setWordWrap(True)
            self._mods_layout.addWidget(lbl)
            self._mods_widgets.append(lbl)
        self._mods_host.show()

    def _populate_why_not_upgrade(self, reasons: list[dict[str, Any]], *, title: str = "") -> None:
        for widget in self._why_not_upgrade_widgets:
            self._why_not_upgrade_layout.removeWidget(widget)
            widget.deleteLater()
        self._why_not_upgrade_widgets.clear()
        if not reasons:
            self._why_not_upgrade_host.hide()
            if not self._upgrade_path_host.isVisible():
                self._rule_upgrade.hide()
            return
        self._why_not_upgrade_title.setText(title or "WHY CURRENT WINS")
        for reason in reasons[:3]:
            lbl = QLabel(f"• {reason.get('explanation')}")
            lbl.setObjectName("whyLabel")
            lbl.setWordWrap(True)
            lbl.setStyleSheet("color: #e8d7b0;")
            self._why_not_upgrade_layout.addWidget(lbl)
            self._why_not_upgrade_widgets.append(lbl)
        self._why_not_upgrade_host.show()
        self._rule_upgrade.show()

    def _populate_upgrade_path(self, block: dict[str, Any], *, pinned_extended: bool = False) -> None:
        if not block:
            self._upgrade_path_host.hide()
            self._upgrade_path_after_repair.hide()
            if not self._why_not_upgrade_host.isVisible():
                self._rule_upgrade.hide()
            return
        self._upgrade_path_title.setText(str(block.get("title") or "UPGRADE PATH"))
        compact = str(block.get("summary_compact") or block.get("summary") or "")
        self._upgrade_path_summary.setText(compact)
        after_repair = block.get("after_repair") or {}
        after_line = str(after_repair.get("compact_line") or "").strip()
        if pinned_extended and after_line:
            self._upgrade_path_after_repair.setText(f"After repair: {after_line}")
            self._upgrade_path_after_repair.show()
        else:
            self._upgrade_path_after_repair.hide()
        note = str(block.get("hypothetical_note") or "")
        self._upgrade_path_note.setText(note)
        self._upgrade_path_note.setVisible(bool(note) and pinned_extended)
        self._upgrade_path_host.show()
        self._rule_upgrade.show()

    def _populate_why(self, reasons: list[dict[str, Any]]) -> None:
        self._clear_why()
        for reason in reasons:
            text = reason.get("explanation") or reason.get("text") or ""
            if not text:
                continue
            lbl = QLabel(f"• {text}")
            lbl.setObjectName("whyLabel")
            lbl.setWordWrap(True)
            severity = str(reason.get("severity") or "")
            if severity in {"critical", "high"}:
                lbl.setStyleSheet("color: #e8d7b0;")
            else:
                lbl.setStyleSheet("color: #c9bea8;")
            self._why_layout.addWidget(lbl)
            self._why_widgets.append(lbl)

    def _clear_why(self) -> None:
        for widget in self._why_widgets:
            self._why_layout.removeWidget(widget)
            widget.deleteLater()
        self._why_widgets.clear()

    def _populate_metrics(self, rows: list[dict[str, Any]], *, hide_ranges: bool = False) -> None:
        self._clear_metrics()
        for row in rows:
            block = QWidget()
            grid = QGridLayout(block)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setHorizontalSpacing(8)
            grid.setVerticalSpacing(1)
            label = QLabel(str(row.get("label") or "").upper())
            label.setObjectName("metricLabel")
            marker = str(row.get("marker") or "").strip()
            if marker:
                label.setText(f"{marker}  {label.text()}")
            delta = QLabel(str(row.get("delta_text") or ""))
            delta.setObjectName("metricDelta")
            emphasis = str(row.get("emphasis") or "medium")
            direction = str(row.get("direction") or "neutral")
            palette = EMPHASIS_DELTA_COLOR.get(emphasis, EMPHASIS_DELTA_COLOR["medium"])
            delta.setStyleSheet(f"color: {palette.get(direction, palette['neutral'])};")
            if emphasis == "critical":
                label.setStyleSheet("color: #e8d7b0; font-weight: 800;")
            delta.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            range_lbl = QLabel("" if hide_ranges else str(row.get("range_text") or ""))
            range_lbl.setObjectName("metricRange")
            range_lbl.setVisible(not hide_ranges)
            grid.addWidget(label, 0, 0)
            grid.addWidget(delta, 0, 1)
            grid.addWidget(range_lbl, 1, 0, 1, 2)
            cap_label = row.get("cap_label") or ""
            if cap_label:
                cap = QLabel(cap_label)
                cap.setObjectName("capLabel")
                cap_state = str(row.get("cap_state") or "")
                cap.setStyleSheet(f"color: {CAP_STATE_COLOR.get(cap_state, '#e0b35a')};")
                grid.addWidget(cap, 2, 0, 1, 2)
            self._metrics_layout.addWidget(block)
            self._metric_widgets.append(block)

    def _populate_warnings(self, groups: list[dict[str, Any]]) -> None:
        self._clear_warnings()
        for group in groups:
            panel = QWidget()
            panel.setObjectName("warningPanel")
            severity = str(group.get("severity") or "warning")
            if severity == "critical":
                panel.setStyleSheet(
                    "QWidget#warningPanel { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, "
                    "stop:0 rgba(211,122,122,46), stop:1 rgba(211,122,122,10)); "
                    "border-left: 3px solid #d37a7a; border-radius: 6px; }"
                )
            else:
                panel.setStyleSheet(
                    "QWidget#warningPanel { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, "
                    "stop:0 rgba(224,179,90,38), stop:1 rgba(224,179,90,8)); "
                    "border-left: 3px solid #e0b35a; border-radius: 6px; }"
                )
            layout = QVBoxLayout(panel)
            layout.setContentsMargins(10, 6, 10, 6)
            layout.setSpacing(2)
            title = QLabel(str(group.get("title") or "WARNING"))
            title.setObjectName("warningTitle")
            title.setStyleSheet("color: #e58b8b;" if severity == "critical" else "color: #e0b35a;")
            layout.addWidget(title)
            for warning in group.get("items") or []:
                lbl = QLabel(f"• {warning.get('text')}")
                lbl.setObjectName("warningLabel")
                lbl.setWordWrap(True)
                lbl.setStyleSheet("color: #f0c8c8;" if severity == "critical" else "color: #e8d3a4;")
                layout.addWidget(lbl)
            self._warnings_layout.addWidget(panel)
            self._warning_widgets.append(panel)

    def _clear_metrics(self) -> None:
        for widget in self._metric_widgets:
            self._metrics_layout.removeWidget(widget)
            widget.deleteLater()
        self._metric_widgets.clear()

    def _clear_warnings(self) -> None:
        for widget in self._warning_widgets:
            self._warnings_layout.removeWidget(widget)
            widget.deleteLater()
        self._warning_widgets.clear()


def _rule() -> QFrame:
    line = QFrame()
    line.setObjectName("sectionRule")
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFrameShadow(QFrame.Shadow.Plain)
    line.setFixedHeight(1)
    return line


class PriceCheckPanel(QWidget):
    """Distinct presentation shell for a Price Check request."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(8)
        self._headline = QLabel("PRICE CHECK")
        self._headline.setObjectName("sectionTitle")
        self._market_price = QLabel("")
        self._market_price.setObjectName("baselineLabel")
        self._market_price.setWordWrap(True)
        self._title = QLabel("")
        self._title.setObjectName("nameLabel")
        self._title.setWordWrap(True)
        self._subtitle = QLabel("")
        self._subtitle.setObjectName("baseLabel")
        self._subtitle.setWordWrap(True)
        self._confidence = QLabel("")
        self._confidence.setObjectName("profileChip")
        self._source = QLabel("")
        self._source.setObjectName("baselineLabel")
        self._comparable_count = QLabel("")
        self._comparable_count.setObjectName("metricLabel")
        self._search_basis = QLabel("")
        self._search_basis.setObjectName("baseLabel")
        self._search_basis.setWordWrap(True)
        self._drivers_host = QWidget()
        self._drivers_layout = QVBoxLayout(self._drivers_host)
        self._drivers_layout.setContentsMargins(0, 2, 0, 2)
        self._drivers_layout.setSpacing(1)
        self._match_mode = QLabel("")
        self._match_mode.setObjectName("baseLabel")
        self._refine_hint = QLabel("")
        self._refine_hint.setObjectName("compactNote")
        self._refine_hint.setWordWrap(True)
        self._comparables_host = QWidget()
        self._comparables_layout = QVBoxLayout(self._comparables_host)
        self._comparables_layout.setContentsMargins(0, 0, 0, 0)
        self._comparables_layout.setSpacing(2)
        self._disclaimer = QLabel("")
        self._disclaimer.setObjectName("warningLabel")
        self._disclaimer.setWordWrap(True)
        self._league_note = QLabel("")
        self._league_note.setObjectName("baselineLabel")
        self._league_note.setWordWrap(True)
        self._mods_host = QWidget()
        self._mods_layout = QVBoxLayout(self._mods_host)
        self._mods_layout.setContentsMargins(0, 0, 0, 0)
        self._mods_layout.setSpacing(2)
        self._currency_host = QWidget()
        self._currency_layout = QVBoxLayout(self._currency_host)
        self._currency_layout.setContentsMargins(0, 0, 0, 0)
        self._currency_layout.setSpacing(2)
        root.addWidget(self._headline)
        root.addWidget(self._market_price)
        root.addWidget(self._title)
        root.addWidget(self._subtitle)
        root.addWidget(self._currency_host)
        root.addWidget(self._comparable_count)
        root.addWidget(self._confidence)
        root.addWidget(self._source)
        root.addWidget(self._search_basis)
        root.addWidget(self._drivers_host)
        root.addWidget(self._match_mode)
        root.addWidget(self._refine_hint)
        root.addWidget(self._comparables_host)
        root.addWidget(self._disclaimer)
        root.addWidget(self._league_note)
        root.addWidget(self._mods_host)

    def render(self, model: dict[str, object]) -> None:
        self._headline.setText(str(model.get("headline") or "PRICE CHECK"))
        market_price = str(model.get("market_price") or "").strip()
        if market_price:
            self._market_price.setText(f"MARKET PRICE: {market_price}")
            self._market_price.setVisible(True)
        else:
            self._market_price.setText("")
            self._market_price.setVisible(False)
        self._title.setText(str(model.get("title") or ""))
        self._subtitle.setText(str(model.get("subtitle") or ""))
        comparable_count = int(model.get("comparable_count") or 0)
        if comparable_count > 0 and model.get("show_currency"):
            self._comparable_count.setText(f"Comparable items: {comparable_count}")
            self._comparable_count.setVisible(True)
        else:
            self._comparable_count.setText("")
            self._comparable_count.setVisible(False)
        confidence = str(model.get("price_confidence") or model.get("confidence") or "")
        reason = str(model.get("confidence_reason") or "").strip()
        if confidence and reason:
            self._confidence.setText(f"Confidence: {confidence} · {reason}")
        else:
            self._confidence.setText(f"Confidence: {confidence}" if confidence else "")
        self._confidence.setVisible(bool(confidence))
        source_label = str(model.get("source_label") or "")
        if source_label and model.get("show_currency"):
            self._source.setText(f"Source: {source_label}")
            self._source.setVisible(True)
        else:
            self._source.setText("")
            self._source.setVisible(False)
        # MARKET-01B12: show what the query actually matched on rather than the base
        # alone, which read as though only the base had been searched.
        matched = str(model.get("matched_features") or "").strip()
        search_basis = str(model.get("search_basis") or "")
        if model.get("base_only") and search_basis and model.get("show_currency"):
            # MARKET-01B13: `Jade Amulet · base only` — the query's own words.
            self._search_basis.setText(f"Search basis: {search_basis}")
            self._search_basis.setVisible(True)
        elif matched and model.get("show_currency"):
            self._search_basis.setText(f"Matched: {matched}")
            self._search_basis.setVisible(True)
        elif search_basis and model.get("show_currency"):
            self._search_basis.setText(f"Matched: {search_basis} (base only)")
            self._search_basis.setVisible(True)
        else:
            self._search_basis.setText("")
            self._search_basis.setVisible(False)
        while self._drivers_layout.count():
            item = self._drivers_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        driver_rows = list(model.get("drivers") or [])
        enabled_drivers = [row for row in driver_rows if row.get("enabled")]
        if enabled_drivers:
            title = QLabel("DRIVERS  (auto)")
            title.setObjectName("metricLabel")
            self._drivers_layout.addWidget(title)
            if model.get("learned_market_pattern"):
                learned = QLabel("Learned market pattern")
                learned.setObjectName("compactNote")
                learned.setWordWrap(True)
                self._drivers_layout.addWidget(learned)
            if model.get("refined_by_you"):
                refined = QLabel("Refined by you.")
                refined.setObjectName("compactNote")
                refined.setWordWrap(True)
                self._drivers_layout.addWidget(refined)
            if model.get("drivers_collapsed"):
                match = str(model.get("match_mode_label") or "").strip()
                summary = f"{len(enabled_drivers)} drivers"
                if match:
                    summary = f"{summary} · MATCH {match}"
                lbl = QLabel(summary)
                lbl.setObjectName("metricLabel")
                lbl.setWordWrap(True)
                self._drivers_layout.addWidget(lbl)
            else:
                for row in enabled_drivers:
                    text = str(row.get("overlay_row") or "").strip()
                    if not text:
                        text = f"[x] {row.get('label')}  min {row.get('search_min')}  ({row.get('actual_value')} on item)"
                    lbl = QLabel(text)
                    lbl.setObjectName("metricLabel")
                    lbl.setWordWrap(True)
                    self._drivers_layout.addWidget(lbl)
            original_auto = str(model.get("original_auto_summary") or "").strip()
            if original_auto and model.get("auto_adjusted"):
                hist = QLabel(f"Original AUTO: {original_auto}")
                hist.setObjectName("compactNote")
                hist.setWordWrap(True)
                self._drivers_layout.addWidget(hist)
        self._drivers_host.setVisible(bool(enabled_drivers))
        match_label = str(model.get("match_mode_label") or "").strip()
        if match_label and not model.get("drivers_collapsed"):
            self._match_mode.setText(f"MATCH  {match_label}")
        self._match_mode.setVisible(
            bool(match_label) and bool(enabled_drivers) and not bool(model.get("drivers_collapsed"))
        )
        refine_hint = str(model.get("refine_hint") or "").strip()
        self._refine_hint.setText(refine_hint)
        self._refine_hint.setVisible(bool(refine_hint))
        disclaimer = str(model.get("disclaimer") or model.get("message") or "")
        market_status = str(model.get("market_status") or "").strip()
        if market_status and not model.get("show_currency") and not disclaimer:
            disclaimer = market_status
        self._disclaimer.setText(disclaimer)
        self._disclaimer.setVisible(bool(disclaimer))
        league_note = str(model.get("league_note") or "")
        self._league_note.setText(league_note)
        self._league_note.setVisible(bool(league_note))
        while self._mods_layout.count():
            item = self._mods_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for mod in model.get("important_mods") or []:
            lbl = QLabel(f"+ {mod}")
            lbl.setObjectName("metricLabel")
            lbl.setWordWrap(True)
            self._mods_layout.addWidget(lbl)
        self._mods_host.setVisible(bool(model.get("important_mods")))
        while self._currency_layout.count():
            item = self._currency_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        show_currency = bool(model.get("show_currency"))
        if show_currency and model.get("bands_collapsed") and model.get("cluster_text"):
            # MARKET-01B12: three identical rows are not three concepts. When the bands
            # genuinely land on one number, say so once. MARKET-01B13: a base-only
            # estimate uses the same single-figure shape, under its own heading.
            lbl = QLabel("BASE MARKET ESTIMATE" if model.get("base_only") else "MARKET CLUSTER")
            lbl.setObjectName("metricLabel")
            self._currency_layout.addWidget(lbl)
            value = QLabel(str(model.get("cluster_text")))
            value.setObjectName("baselineLabel")
            self._currency_layout.addWidget(value)
        elif show_currency:
            for row in model.get("currency_bands") or []:
                display = str(row.get("display") or "").strip()
                if not display:
                    amount_high = row.get("amount_high")
                    amount = row.get("amount")
                    currency = row.get("currency")
                    if amount_high and float(amount_high) > float(amount or 0):
                        display = f"{amount}–{amount_high} {currency}"
                    else:
                        display = f"{amount} {currency}"
                lbl = QLabel(f"{row.get('label')}: {display}")
                lbl.setObjectName("metricLabel")
                self._currency_layout.addWidget(lbl)
        # MARKET-01B13: name the limitation directly under the figure it applies to.
        basis_note = str(model.get("basis_note") or "").strip()
        if show_currency and basis_note:
            lbl = QLabel(basis_note)
            lbl.setObjectName("baseLabel")
            lbl.setWordWrap(True)
            self._currency_layout.addWidget(lbl)
        basis = str(model.get("currency_basis") or "").strip()
        if show_currency and basis:
            lbl = QLabel(basis)
            lbl.setObjectName("baseLabel")
            lbl.setWordWrap(True)
            self._currency_layout.addWidget(lbl)
        self._currency_host.setVisible(show_currency and bool(model.get("currency_bands")))
        while self._comparables_layout.count():
            item = self._comparables_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for row in model.get("top_comparables") or []:
            # MARKET-01B12: the payload already carries "1 regal (~0.9 ex)"; the UI must
            # not do its own currency maths.
            text = str(row.get("display") or "").strip()
            if not text:
                amount = row.get("price_amount")
                currency = row.get("price_currency")
                text = f"{amount} {currency}"
            lbl = QLabel(f"• {text}")
            lbl.setObjectName("metricLabel")
            self._comparables_layout.addWidget(lbl)
        self._comparables_host.setVisible(bool(model.get("top_comparables")) and bool(model.get("show_currency")))

    def show_analyzing(self) -> None:
        self.render(
            {
                "headline": "PRICE CHECK",
                "market_price": "",
                "title": "Checking item...",
                "subtitle": "",
                "confidence": "",
                "disclaimer": "",
                "important_mods": [],
                "show_currency": False,
                "currency_bands": [],
                "top_comparables": [],
                "comparable_count": 0,
                "search_basis": "",
                "source_label": "",
                "league_note": "",
            }
        )
