"""Overview -- the natural home of the desktop companion.

Flat page, no hero container. For a healthy build it starts directly with the build name
(the Status Rail already says Ready); when something needs the player's attention the page
repeats the state, because there is something to do. Order, top to bottom:

    title, [one-time consent card], [status word], build name or headline, meta,
    primary action, hairline, "press Shift + C", evaluation profile, Fix first.

Everything shown is derived from data the product already has: ``derive_status`` (which
wraps ``derive_health``), the controller's build accessors and the cached Analyze Build
result. Nothing is invented.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from exilelens.app.build_state import BuildState
from exilelens.app.controller import EvaluationController
from exilelens.app.settings import AppSettings, save_settings
from exilelens.ui import status_model, theme
from exilelens.ui.components import SegmentedControl, StatusValue, make_button, make_link_button
from exilelens.ui.dashboard_widgets import ColumnPage, Hairline, keycaps, make_label
from exilelens.ui.health import hotkey_display
from exilelens.ui.profile_catalog import PROFILE_CARDS
from exilelens.ui.setup_dialog import pick_build_file
from exilelens.ui.ui_icons import outline_icon

_PROFILE_BY_VALUE = {card.profile.value: card for card in PROFILE_CARDS}
_LABEL_COLUMN = 132  # "Evaluate items for" and "Fix first" share one value axis
_MAX_ATTENTION_ROWS = 3


class OverviewPage(ColumnPage):
    def __init__(
        self,
        controller: EvaluationController,
        settings: AppSettings,
        *,
        navigate=None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(sticky_header=False, object_name="overviewPage", parent=parent)
        self.controller = controller
        self.settings = settings
        self._navigate = navigate
        self._consent_card = None
        self._status: status_model.AppStatus | None = None

        title = QLabel("Overview")
        title.setObjectName("pageTitle")
        self.column.setSpacing(0)
        self.column.addWidget(title)
        self._consent_slot = QVBoxLayout()
        self._consent_slot.setContentsMargins(0, 16, 0, 0)
        self.column.addLayout(self._consent_slot)

        # --- primary area -------------------------------------------------------------
        primary = QVBoxLayout()
        primary.setContentsMargins(0, 22, 0, 0)
        primary.setSpacing(0)
        self._status_line = StatusValue("", "neutral")
        self._status_line.set_word_wrap(False)
        self._status_host = QWidget()
        status_layout = QVBoxLayout(self._status_host)
        status_layout.setContentsMargins(0, 0, 0, 8)
        status_layout.addWidget(self._status_line)
        primary.addWidget(self._status_host)
        self._build_name = QLabel("")
        self._build_name.setObjectName("buildName")
        self._build_name.setWordWrap(True)
        self._headline = QLabel("")
        self._headline.setObjectName("headline")
        self._headline.setWordWrap(True)
        self._lead = make_label("", "leadText")
        self._lead.setMaximumWidth(560)
        primary.addWidget(self._build_name)
        primary.addWidget(self._headline)
        primary.addSpacing(6)
        primary.addWidget(self._lead)

        self._meta_row = QWidget()
        meta = QHBoxLayout(self._meta_row)
        meta.setContentsMargins(0, 4, 0, 0)
        meta.setSpacing(6)
        self._meta = QLabel("")
        self._meta.setObjectName("bodyText")
        self._refresh_btn = make_button("Refresh", "tertiary", compact=True)
        self._refresh_btn.clicked.connect(self.controller.reload_evaluation_build)
        meta.addWidget(self._meta, 0)
        meta.addWidget(self._refresh_btn, 0)
        meta.addStretch(1)
        primary.addWidget(self._meta_row)

        # Build-freshness notice (shipped behaviour; StatusValue keeps dot + text).
        self._notice = StatusValue("", "neutral")
        self._notice.setVisible(False)
        primary.addSpacing(6)
        primary.addWidget(self._notice)

        self._attention_host = QWidget()
        self._attention_layout = QVBoxLayout(self._attention_host)
        self._attention_layout.setContentsMargins(0, 0, 0, 0)
        self._attention_layout.setSpacing(0)
        primary.addSpacing(14)
        self._attention_rule = Hairline()
        primary.addWidget(self._attention_rule)
        primary.addWidget(self._attention_host)

        self._actions = QHBoxLayout()
        self._actions.setContentsMargins(0, 18, 0, 0)
        self._actions.setSpacing(10)
        self._primary_btn = make_button("Analyze Build", "primary")
        self._secondary_btn = make_button("Change build", "secondary")
        self._primary_btn.clicked.connect(self._on_primary_clicked)
        self._secondary_btn.clicked.connect(self._on_secondary_clicked)
        self._actions.addWidget(self._primary_btn)
        self._actions.addWidget(self._secondary_btn)
        self._actions.addStretch(1)
        primary.addLayout(self._actions)
        self.column.addLayout(primary)
        self._primary_kind = ""
        self._secondary_kind = ""

        # --- how to check an item -----------------------------------------------------------
        self._key_block = QWidget()
        key_layout = QVBoxLayout(self._key_block)
        key_layout.setContentsMargins(0, 24, 0, 0)
        key_layout.setSpacing(18)
        key_layout.addWidget(Hairline())
        self._key_row = QHBoxLayout()
        self._key_row.setContentsMargins(0, 0, 0, 0)
        self._key_row.setSpacing(8)
        self._key_text = QLabel("Hover an item in Path of Exile 2 and press")
        self._key_text.setObjectName("bodyText")
        self._key_caps_host = QWidget()
        self._key_caps_layout = QHBoxLayout(self._key_caps_host)
        self._key_caps_layout.setContentsMargins(0, 0, 0, 0)
        self._key_row.addWidget(self._key_text)
        self._key_row.addWidget(self._key_caps_host)
        self._key_row.addStretch(1)
        key_layout.addLayout(self._key_row)
        self.column.addWidget(self._key_block)

        # --- evaluation profile ----------------------------------------------------------------
        self._profile_block = QWidget()
        profile_layout = QHBoxLayout(self._profile_block)
        profile_layout.setContentsMargins(0, 20, 0, 0)
        profile_layout.setSpacing(16)
        label = QLabel("Evaluate items for")
        label.setObjectName("fieldLabel")
        label.setFixedWidth(_LABEL_COLUMN)
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._segments = SegmentedControl([(card.profile.value, card.title) for card in PROFILE_CARDS])
        self._segments.changed.connect(self._set_profile)
        self._profile_description = QLabel("")
        self._profile_description.setObjectName("helperText")
        self._profile_description.setWordWrap(True)
        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(6)
        right.addWidget(self._segments, 0, Qt.AlignmentFlag.AlignLeft)
        right.addWidget(self._profile_description)
        profile_layout.addWidget(label, 0, Qt.AlignmentFlag.AlignTop)
        profile_layout.addLayout(right, 1)
        self._profile_label = label
        self.column.addWidget(self._profile_block)

        # --- fix first ------------------------------------------------------------------------------
        self._fix_block = QWidget()
        fix_layout = QHBoxLayout(self._fix_block)
        fix_layout.setContentsMargins(0, 20, 0, 0)
        fix_layout.setSpacing(16)
        fix_label = QLabel("Fix first")
        fix_label.setObjectName("fieldLabel")
        fix_label.setFixedWidth(_LABEL_COLUMN)
        fix_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        fix_text = QVBoxLayout()
        fix_text.setContentsMargins(0, 0, 0, 0)
        fix_text.setSpacing(1)
        self._fix_headline = QLabel("")
        self._fix_headline.setObjectName("fieldLabel")
        self._fix_headline.setWordWrap(True)
        self._fix_caption = QLabel("From your last analysis")
        self._fix_caption.setObjectName("helperText")
        fix_text.addWidget(self._fix_headline)
        fix_text.addWidget(self._fix_caption)
        self._fix_link = make_link_button("Open analysis")
        self._fix_link.clicked.connect(lambda: self._go("build_analysis"))
        fix_layout.addWidget(fix_label, 0, Qt.AlignmentFlag.AlignTop)
        fix_layout.addLayout(fix_text, 1)
        fix_layout.addWidget(self._fix_link, 0, Qt.AlignmentFlag.AlignTop)
        self.column.addWidget(self._fix_block)
        self.column.addStretch(1)

        controller.active_build_status_changed.connect(lambda _s: self.refresh())
        controller.build_changed.connect(lambda _info: self.refresh())
        controller.baseline_state_changed.connect(lambda _state: self.refresh())
        controller.engine_ready.connect(self.refresh)
        controller.engine_failed.connect(lambda _msg: self.refresh())
        controller.value_profile_changed.connect(self._on_profile_changed)
        for name in ("analysis_finished", "analysis_stale"):
            signal = getattr(controller, name, None)
            if signal is not None:
                signal.connect(lambda *_a: self._refresh_fix_first())
        hotkey = getattr(controller, "price_check_hotkey", None)
        if hotkey is not None and hasattr(hotkey, "diagnostics_changed"):
            hotkey.diagnostics_changed.connect(self.refresh)
        self.refresh()

    # --- interactions --------------------------------------------------------------------------

    def _go(self, page_id: str) -> None:
        if self._navigate is not None:
            self._navigate(page_id)

    def _choose_build(self) -> None:
        path = pick_build_file(self.settings.build_path)
        if path:
            self.controller.change_build(path)

    def _sync_consent_card(self) -> None:
        """Show the one-time, non-modal privacy card after onboarding (both switches start OFF)."""
        if self._consent_card is not None:  # shown once per session; Save / Not now resolve it for good
            return
        try:
            from exilelens.app.settings import onboarding_required
            from exilelens.cloud import consent, hooks
            from exilelens.ui.privacy_panel import ConsentCard

            cloud = hooks.get()
            if not consent.should_show_card(self.settings, cloud, onboarding_pending=onboarding_required(self.settings)):
                return
            self._consent_card = ConsentCard(self.settings, cloud)
            self._consent_slot.addWidget(self._consent_card)
        except Exception:  # noqa: BLE001 - an optional card must never break the dashboard
            self._consent_card = None

    def _set_profile(self, profile: str) -> None:
        self.controller.select_value_profile(profile)
        self._show_profile_description(profile)

    def _on_profile_changed(self, profile: str) -> None:
        self._segments.set_current_value(profile)
        self._show_profile_description(profile)

    def _show_profile_description(self, profile: str) -> None:
        card = _PROFILE_BY_VALUE.get(profile)
        self._profile_description.setText(card.description if card else "")

    def _run(self, kind: str) -> None:
        if kind == "analyze":
            self._go("build_analysis")
        elif kind == "change_build" or kind == "choose_build":
            self._choose_build()
        elif kind == "detect_pob":
            from exilelens.ui.pob_detect import detect_pob_path

            path = detect_pob_path(self)
            if path:
                self.settings.pob_path = path
                save_settings(self.settings)
                self.controller.restart_engine()
                self.refresh()
            else:
                self._go("settings")  # nothing detected: fall back to choosing the folder manually
        elif kind == "settings":
            self._go("settings")
        elif kind == "reconnect":
            self.controller.restart_engine()
        elif kind == "refresh":
            self.controller.reload_evaluation_build()
        elif kind == "diagnostics":
            self._go("diagnostics")

    def _on_primary_clicked(self) -> None:
        self._run(self._primary_kind)

    def _on_secondary_clicked(self) -> None:
        self._run(self._secondary_kind)

    # --- state ------------------------------------------------------------------------------------

    def hotkey_instruction(self) -> str:
        """Always renders the configured chord -- never a hardcoded Shift+C."""
        return f"Hover an item in Path of Exile 2 and press {hotkey_display(self.settings)}."

    def status(self) -> status_model.AppStatus | None:
        return self._status

    def refresh(self) -> None:
        self._sync_consent_card()
        status = status_model.derive_status(self.controller, self.settings)
        self._status = status
        self._on_profile_changed(self.settings.value_profile)
        self._render(status)
        self._refresh_fix_first()

    def _set_buttons(self, primary: tuple[str, str] | None, secondary: tuple[str, str] | None = None) -> None:
        for button, spec, attr in (
            (self._primary_btn, primary, "_primary_kind"),
            (self._secondary_btn, secondary, "_secondary_kind"),
        ):
            button.setVisible(spec is not None)
            if spec is not None:
                setattr(self, attr, spec[0])
                button.setText(spec[1])
        self._primary_btn.setAccessibleName(self._primary_btn.text())

    def _clear_attention(self) -> None:
        while self._attention_layout.count():
            item = self._attention_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()  # deleteLater() alone leaves the old row painted until the event loop runs
                widget.setParent(None)
                widget.deleteLater()

    def _attention_row(self, title: str, detail: str, action: tuple[str, str] | None) -> QWidget:
        row = QWidget()
        row.setObjectName("settingsRow")
        row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 12, 0, 12)
        layout.setSpacing(12)
        icon = QLabel()
        icon.setFixedSize(16, 20)
        icon.setPixmap(outline_icon("warn", theme.WARN, 16).pixmap(16, 16))
        icon.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(0)
        head = QLabel(title)
        head.setObjectName("fieldLabel")
        head.setWordWrap(True)
        text.addWidget(head)
        if detail:
            sub = QLabel(detail)
            sub.setObjectName("helperText")
            sub.setWordWrap(True)
            text.addWidget(sub)
        layout.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(text, 1)
        if action is not None:
            kind, label = action
            button = make_button(label, "secondary", compact=True)
            button.clicked.connect(lambda _c=False, k=kind: self._run(k))
            layout.addWidget(button, 0, Qt.AlignmentFlag.AlignVCenter)
        return row

    def _attention_items(self, status: status_model.AppStatus) -> list[tuple[str, str, tuple[str, str] | None]]:
        build, hotkey = status.health.build, status.health.hotkey
        items: list[tuple[str, str, tuple[str, str] | None]] = []
        if build.status == "warn":
            detail = (build.detail or "").strip()
            if "changed on disk" in detail.lower():
                items.append(("The build file changed on disk", "Refresh so item checks use the version you just saved.", ("refresh", "Refresh")))
            elif detail:
                items.append((detail.rstrip("."), "", ("refresh", "Refresh")))
            else:
                items.append(("The build is not loaded", "", ("refresh", "Refresh")))
        if hotkey.status in ("warn", "error"):
            items.append(("Item check is not active", hotkey.detail or "", ("diagnostics", "Open Diagnostics")))
        return items

    def _render(self, status: status_model.AppStatus) -> None:
        key = status.key
        health = status.health
        has_build = status.build_selected
        # Defaults: hide everything, then reveal what this state needs.
        self._clear_attention()
        self._attention_host.setVisible(False)
        self._attention_rule.setVisible(False)
        self._status_host.setVisible(False)
        self._build_name.setVisible(False)
        self._headline.setVisible(False)
        self._lead.setVisible(False)
        self._meta_row.setVisible(False)
        self._key_block.setVisible(False)
        self._profile_block.setVisible(False)
        self._set_buttons(None)
        self._refresh_meta(status)

        if status.needs_action or key in (status_model.CONNECTING, status_model.LOADING):
            self._status_line.set_value(status.label, status.tone)
            self._status_host.setVisible(True)

        if key == status_model.READY:
            self._show_build(status, with_meta=True)
            self._set_buttons(("analyze", "Analyze Build"), ("change_build", "Change build"))
            self._key_text.setText("Hover an item in Path of Exile 2 and press")
            self._set_keycaps()
            self._key_block.setVisible(True)
            self._profile_block.setVisible(True)
        elif key == status_model.LOADING:
            self._show_build(status, with_meta=False)
        elif key == status_model.CONNECTING:
            self._headline.setText("Connecting to Path of Building…")
            self._headline.setVisible(True)
        elif key == status_model.SETUP and health.pob.value == "Not found":
            self._headline.setText("Path of Building could not be detected")
            self._lead.setText(health.pob.detail or "Detect it automatically, or choose its installation folder in Settings.")
            self._headline.setVisible(True)
            self._lead.setVisible(True)
            self._set_buttons(("detect_pob", "Detect automatically"), ("settings", "Open Settings"))
        elif key == status_model.SETUP:
            self._headline.setText("Choose your build")
            self._lead.setText("Pick the Path of Building .xml you play so ExileLens can evaluate items against it.")
            self._headline.setVisible(True)
            self._lead.setVisible(True)
            self._set_buttons(("choose_build", "Choose build"))
        elif key == status_model.DISCONNECTED:
            if has_build:
                self._show_build(status, with_meta=False)
            else:
                self._headline.setText("ExileLens is not connected to Path of Building")
                self._headline.setVisible(True)
            detail = (health.pob.detail or "").strip()
            lead = "ExileLens is not connected to Path of Building."
            if detail:
                lead = f"{lead} {detail}"
            self._lead.setText(f"{lead} Item checks are paused until it reconnects.")
            self._lead.setVisible(True)
            self._set_buttons(("reconnect", "Reconnect"), ("diagnostics", "Open Diagnostics"))
        elif key == status_model.ATTENTION and health.build.status == "error":
            self._headline.setText("That build could not be loaded")
            self._headline.setVisible(True)
            if health.build.detail:
                self._lead.setText(health.build.detail)
                self._lead.setVisible(True)
            self._set_buttons(("choose_build", "Choose another build"), ("refresh", "Refresh"))
        elif key == status_model.ATTENTION:
            self._show_build(status, with_meta=True)
            items = self._attention_items(status)
            for title, detail, action in items[:_MAX_ATTENTION_ROWS]:
                self._attention_layout.addWidget(self._attention_row(title, detail, action))
            if any(action and action[0] == "refresh" for _t, _d, action in items[:_MAX_ATTENTION_ROWS]):
                self._refresh_btn.setVisible(False)  # the row below already offers Refresh
            extra = max(0, status.attention_count - len(items[:_MAX_ATTENTION_ROWS]))
            if extra:
                more = make_link_button(f"+{extra} more in Diagnostics")
                more.clicked.connect(lambda: self._go("diagnostics"))
                self._attention_layout.addWidget(more)
            self._attention_host.setVisible(bool(items))
            self._attention_rule.setVisible(bool(items))
            self._profile_block.setVisible(True)
        # The spacing above the primary actions only exists when there are actions.
        self._actions.setContentsMargins(0, 18 if (self._primary_btn.isVisibleTo(self) or self._secondary_btn.isVisibleTo(self)) else 0, 0, 0)

    def _show_build(self, status: status_model.AppStatus, *, with_meta: bool) -> None:
        self._build_name.setText(status.build_name if status.build_selected else "")
        self._build_name.setVisible(status.build_selected)
        self._meta_row.setVisible(with_meta and status.build_selected)

    def _set_keycaps(self) -> None:
        while self._key_caps_layout.count():
            item = self._key_caps_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self._key_caps_layout.addWidget(keycaps(hotkey_display(self.settings)))

    def _refresh_meta(self, status: status_model.AppStatus) -> None:
        info = self.controller.build_info
        build_status = self.controller.active_build_status()
        path = build_status.build_path or info.path or ""
        self._notice.setVisible(False)
        if not path:
            self._meta.setText("")
            self._refresh_btn.setEnabled(False)
            return
        from exilelens.ui.health import loaded_text

        loaded = loaded_text(self.controller, build_status)
        self._meta.setText(f"Path of Building · loaded {loaded}" if loaded else "Path of Building")
        self._meta.setToolTip(path)
        self._refresh_btn.setEnabled(True)
        build = status.health.build
        if build.status in ("warn", "error") and build.detail and status.key not in (status_model.ATTENTION,):
            self._notice.set_value(build.detail, build.status)
            self._notice.setVisible(True)
        self._apply_freshness_notice(build)

    def _apply_freshness_notice(self, build) -> None:
        """Persistent home of build freshness. Quiet when CURRENT; never claims the character is stale."""
        try:
            freshness = self.controller.build_freshness()
        except Exception:  # noqa: BLE001 - never break Overview
            return
        state = freshness.get("state")
        if state == "USING_LAST_GOOD":
            severity = "error"
        elif state in {"OLD_FILE", "DISK_CHANGED", "RELOADING"}:
            severity = "warn"
        else:
            return
        if state == "OLD_FILE" and self._notice.isVisible():
            return  # a more specific problem is already shown
        text = " ".join(part for part in (freshness.get("title"), freshness.get("detail")) if part)
        self._notice.set_value(text, severity)
        self._notice.setVisible(True)

    def _refresh_fix_first(self) -> None:
        """The Current focus headline from the cached Analyze Build result, or nothing."""
        headline = ""
        try:
            result = self.controller.last_analysis()
            if result and result.get("build_priorities"):
                from exilelens.analysis.view import build_analysis_view

                view = build_analysis_view(result)
                if view.get("has_actionable"):
                    headline = str((view.get("focus") or {}).get("headline") or "")
        except Exception:  # noqa: BLE001 - an optional teaser must never break Overview
            headline = ""
        self._fix_headline.setText(headline)
        ready = bool(self._status and self._status.key in (status_model.READY, status_model.ATTENTION))
        self._fix_block.setVisible(bool(headline) and ready)
