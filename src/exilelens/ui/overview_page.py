"""Overview -- the default user-facing dashboard.

Replaces ``BuildPage``, which rendered the build identity inside a bordered card
(already shown in the header and the footer), printed the full XML path on its own
wrapped line, and stacked four full-width radio rows each carrying a long profile
description.

The information architecture here is: which build is active, how it is evaluated,
and what to do next. Nothing else.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from exilelens.app.build_state import BuildState
from exilelens.app.controller import EvaluationController
from exilelens.app.settings import AppSettings
from exilelens.ui import theme
from exilelens.ui.components import (
    ElidedLabel,
    Section,
    StatusValue,
    button_row,
    make_button,
)
from exilelens.ui.health import hotkey_display
from exilelens.ui.profile_catalog import PROFILE_CARDS
from exilelens.ui.setup_dialog import pick_build_file
from exilelens.ui.ui_icons import apply_button_icon

_PROFILE_BY_VALUE = {card.profile.value: card for card in PROFILE_CARDS}


class OverviewPage(QWidget):
    def __init__(
        self,
        controller: EvaluationController,
        settings: AppSettings,
        *,
        navigate=None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("overviewPage")
        self.controller = controller
        self.settings = settings
        self._navigate = navigate

        title = QLabel("Overview")
        title.setObjectName("pageTitle")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SECTION_GAP)
        layout.addWidget(title)
        layout.addWidget(self._build_section())
        layout.addWidget(self._profile_section())
        layout.addWidget(self._action_section())
        layout.addWidget(self._support_section())
        layout.addStretch(1)

        controller.active_build_status_changed.connect(lambda _s: self.refresh())
        controller.build_changed.connect(lambda _info: self.refresh())
        controller.baseline_state_changed.connect(lambda _state: self.refresh())
        controller.engine_ready.connect(self.refresh)
        controller.engine_failed.connect(lambda _msg: self.refresh())
        controller.value_profile_changed.connect(self._on_profile_changed)
        hotkey = getattr(controller, "price_check_hotkey", None)
        if hotkey is not None and hasattr(hotkey, "diagnostics_changed"):
            hotkey.diagnostics_changed.connect(self.refresh)
        self.refresh()

    # --- construction -----------------------------------------------------------

    def _build_section(self) -> QWidget:
        section = Section("Your build")

        self._name = QLabel("—")
        self._name.setObjectName("primaryValue")

        # The path is metadata, not headline content: one elided line with the full
        # value in the tooltip, instead of a wrapped two-line filesystem path.
        self._meta = ElidedLabel("")
        self._meta.setObjectName("secondaryText")

        self._notice = StatusValue("", "neutral")
        self._notice.setVisible(False)

        self._choose_btn = make_button("Change build", "secondary")
        self._choose_btn.clicked.connect(self._choose_build)
        self._refresh_btn = make_button("Refresh", "tertiary")
        self._refresh_btn.clicked.connect(self.controller.reload_evaluation_build)

        section.add_widget(self._name)
        section.add_widget(self._meta)
        section.add_widget(self._notice)
        section.add_layout(button_row([self._choose_btn, self._refresh_btn]))
        return section

    def _profile_section(self) -> QWidget:
        from exilelens.ui.components import SegmentedControl

        section = Section("Profile")
        self._segments = SegmentedControl(
            [(card.profile.value, card.title) for card in PROFILE_CARDS]
        )
        self._segments.changed.connect(self._set_profile)

        # Only the selected profile's description is shown; four at once was noise.
        self._profile_description = QLabel("")
        self._profile_description.setObjectName("helperText")
        self._profile_description.setWordWrap(True)

        section.add_widget(self._segments)
        section.add_widget(self._profile_description)
        return section

    def _action_section(self) -> QWidget:
        section = Section()
        self._action_title = QLabel("")
        self._action_title.setObjectName("cardTitle")
        self._action_body = QLabel("")
        self._action_body.setObjectName("helperText")
        self._action_body.setWordWrap(True)
        self._action_btn = make_button("", "primary")
        self._action_btn.setVisible(False)
        self._action_btn.clicked.connect(self._on_action_clicked)

        section.add_widget(self._action_title)
        section.add_widget(self._action_body)
        section.add_layout(button_row([self._action_btn]))
        self._action_kind = ""
        return section

    def _support_section(self) -> QWidget:
        card = QFrame()
        card.setObjectName("patreonSupportCard")
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(theme.SPACE_SM)

        heading = QLabel("Enjoying ExileLens?")
        heading.setObjectName("cardTitle")
        layout.addWidget(heading)

        body = QLabel("Support its continued development and help keep it free and open source.")
        body.setObjectName("helperText")
        body.setWordWrap(True)
        layout.addWidget(body)

        button = make_button("Support on Patreon", "secondary")
        apply_button_icon(button, "patreon", ui_scale=float(getattr(self.settings, "ui_scale", 1.0) or 1.0))
        button.setToolTip("Open ExileLens on Patreon")
        button.clicked.connect(self._open_patreon)
        layout.addLayout(button_row([button]))
        return card

    # --- interactions -----------------------------------------------------------

    def _choose_build(self) -> None:
        path = pick_build_file(self.settings.build_path)
        if path:
            self.controller.change_build(path)

    def _open_patreon(self) -> None:
        from exilelens.ui.recovery_actions import open_patreon

        open_patreon()

    def _set_profile(self, profile: str) -> None:
        self.controller.select_value_profile(profile)
        self._show_profile_description(profile)

    def _on_profile_changed(self, profile: str) -> None:
        self._segments.set_current_value(profile)
        self._show_profile_description(profile)

    def _show_profile_description(self, profile: str) -> None:
        card = _PROFILE_BY_VALUE.get(profile)
        self._profile_description.setText(card.description if card else "")

    def _on_action_clicked(self) -> None:
        kind = self._action_kind
        if kind == "choose_build":
            self._choose_build()
        elif kind == "locate_pob":
            if self._navigate is not None:
                self._navigate("settings")
        elif kind == "reconnect":
            self.controller.restart_engine()
        elif kind == "refresh":
            self.controller.reload_evaluation_build()
        elif kind == "diagnostics":
            if self._navigate is not None:
                self._navigate("diagnostics")

    def _set_action(self, kind: str, title: str, body: str, button: str = "") -> None:
        self._action_kind = kind
        self._action_title.setText(title)
        self._action_body.setText(body)
        self._action_btn.setText(button)
        self._action_btn.setVisible(bool(button))

    # --- state ------------------------------------------------------------------

    def hotkey_instruction(self) -> str:
        """Always renders the configured chord -- never a hardcoded Shift+C."""
        return f"Hover an item in Path of Exile 2 and press {hotkey_display(self.settings)}."

    def refresh(self) -> None:
        from exilelens.ui.health import derive_health

        health = derive_health(self.controller, self.settings)
        self._refresh_build(health)
        self._on_profile_changed(self.settings.value_profile)
        self._refresh_action(health)

    def _refresh_build(self, health) -> None:
        status = self.controller.active_build_status()
        info = self.controller.build_info
        path = status.build_path or info.path or ""

        if not path:
            self._name.setText("No build selected")
            self._meta.set_full_text("")
            self._meta.setVisible(False)
            self._notice.setVisible(False)
            self._refresh_btn.setEnabled(False)
            return

        from exilelens.ui.health import loaded_text

        name = status.display_name or info.name or Path(path).stem
        self._name.setText(name)
        # Shared with the Settings build row so the two cannot drift apart; returns
        # "" when there is genuinely no timestamp, rather than "loaded never".
        loaded = loaded_text(self.controller, status)
        self._meta.set_full_text(
            f"Path of Building · loaded {loaded}" if loaded else "Path of Building"
        )
        self._meta.setToolTip(path)
        self._meta.setVisible(True)
        self._refresh_btn.setEnabled(True)

        build = health.build
        if build.status in ("warn", "error") and build.detail:
            self._notice.set_value(build.detail, build.status)
            self._notice.setVisible(True)
        else:
            self._notice.setVisible(False)

    def _refresh_action(self, health) -> None:
        """Tell the player what to do next, in priority order of what is broken."""
        pob, build, hotkey = health.pob, health.build, health.hotkey

        if pob.value == "Not found":
            self._set_action(
                "locate_pob",
                "Path of Building could not be detected",
                pob.detail or "Choose your Path of Building installation folder.",
                "Locate Path of Building",
            )
            return
        if pob.status == "error":
            self._set_action(
                "reconnect",
                "ExileLens is not connected to Path of Building",
                pob.detail or "",
                "Reconnect",
            )
            return
        if pob.status == "warn":
            if pob.value.startswith("Connecting"):
                self._set_action("", "Connecting to Path of Building…", "")
                return
            self._set_action(
                "reconnect",
                "ExileLens is not connected to Path of Building",
                pob.detail or "",
                "Reconnect",
            )
            return

        if build.value == "Not selected":
            self._set_action(
                "choose_build",
                "Choose your build",
                "Pick the Path of Building .xml you play so ExileLens can evaluate items against it.",
                "Choose build",
            )
            return
        if build.status == "error":
            self._set_action(
                "choose_build",
                "That build could not be loaded",
                build.detail or "",
                "Choose another build",
            )
            return
        if build.detail and "changed on disk" in build.detail.lower():
            self._set_action(
                "refresh",
                "The build file changed on disk",
                "Refresh so item checks use the version you just saved.",
                "Refresh",
            )
            return

        if hotkey.status in ("warn", "error"):
            self._set_action(
                "diagnostics",
                "Item check is not active",
                hotkey.detail or "",
                "Open Diagnostics",
            )
            return

        if self.controller.build_info.state != BuildState.READY:
            self._set_action("", "Loading your build…", "")
            return

        self._set_action("", "Ready to evaluate items", self.hotkey_instruction())
