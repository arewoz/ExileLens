"""Experimental build-aware loot filter dashboard."""
from __future__ import annotations

import random
import hashlib
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel,
                               QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

from exilelens.app.controller import EvaluationController
from exilelens.app.settings import AppSettings
from exilelens.filters.build_needs import BuildNeedsSnapshot, Coverage
from exilelens.filters.fingerprint import BuildFingerprintExtractor
from exilelens.filters.install import get_installed_filter_info, install_test_filter, open_filter_folder
from exilelens.filters.intel_generate import filter_body_sha256, generate as generate_filter
from exilelens.filters.intel_status import IntelState, describe, is_build_analysis, is_current
from exilelens.filters.preview import preview_decision, preview_scene_items, visible_preview_entries
from exilelens.filters.scene_pool import RANDOM_SCENE, pool_size, random_scene_items
from exilelens.filters.profiles import PROFILE_INTENT as PROFILE_INTENT_TEXT
from exilelens.filters.profiles import FilterProfileName, FilterThemeName, get_profile_with_theme
from exilelens.filters.style_system import native_style
from exilelens.platform.windows.poe2_paths import find_poe2_filter_directory, verify_poe2_filter_directory
from exilelens.ui import theme
from exilelens.ui.components import Disclosure, Section, make_button
from exilelens.ui.styles import apply_scroll_area_theme


PROFILE_INTENT = PROFILE_INTENT_TEXT   # one-line description per strictness level (filters.profiles)
THEME_INTENT = {
    FilterThemeName.VOID_GOLD: ("Obsidian · antique gold · diamond marks", "#ddbd65"),
    FilterThemeName.BLOOD_SIGIL: ("Crimson ritual · dark enamel · sigil marks", "#d85269"),
    FilterThemeName.ARCANE_PRISM: ("Cobalt · violet · cyan prismatic cues", "#77cfff"),
    FilterThemeName.VERDANT_RELIC: ("Jade stone · relic brass · pentagon marks", "#8be1a3"),
    FilterThemeName.EMBERFORGE: ("Iron · furnace orange · hexagon marks", "#ff9c62"),
    FilterThemeName.ABYSSAL_COVENANT: ("Abyssal violet · muted ritual pink · moon marks", "#d5a5ea"),
    FilterThemeName.ETERNAL_EMPIRE: ("Ivory · aged bronze · ceremonial pentagon marks", "#ecd8aa"),
    FilterThemeName.WRAECLAST_ASHES: ("Ash · cold iron · pale spectral diamond marks", "#d0e0df"),
}
class LootGroundScene(QWidget):
    """Original scenery behind native-action label approximations."""

    width_changed = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self.beams: list[tuple[int, int, str]] = []
        self.bright_environment = False
        ground_path = Path(__file__).resolve().parents[1] / "filters" / "data" / "loot_ground.png"
        self._ground = QPixmap(str(ground_path))
        self._reported_width = -1
        self.setMinimumHeight(420)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        width = event.size().width()
        if abs(width - self._reported_width) >= 12:
            self._reported_width = width
            self.width_changed.emit(width)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        rect = self.rect()
        if self.bright_environment:
            painter.fillRect(rect, QColor("#b5aa93"))
        elif not self._ground.isNull():
            painter.drawPixmap(rect, self._ground, self._ground.rect())
        else:
            painter.fillRect(rect, QColor("#202526"))
        for beam in self.beams:
            x, y, color = beam[:3]
            persistent = len(beam) > 3 and beam[3]
            marker = QColor(color if color.lower() != "white" else "#ffffff")
            if persistent:                       # PlayEffect without Temp: the beam stays for as long as the item lies there
                halo = QColor(marker)
                halo.setAlpha(70)
                painter.setPen(QPen(halo, 9))
                painter.drawLine(x, 0, x, y + 3)
                marker.setAlpha(235)
                painter.setPen(QPen(marker, 3))
                painter.drawLine(x, 0, x, y + 3)
            else:                                # Temp: a short beam while the item drops
                marker.setAlpha(170)
                painter.setPen(QPen(marker, 2))
                painter.drawLine(x, max(0, y - 84), x, y + 3)


def _ground_layout(seed: int, sizes: list[tuple[int, int]], width: int,
                   levels: list[str] | None = None) -> tuple[list[tuple[int, int]], int]:
    """Place important labels near the cluster centre with collision-safe spacing."""
    rng = random.Random(seed)
    levels = levels or ["MEDIUM"] * len(sizes)
    positions = [(0, 0)] * len(sizes)
    priority = {"HERO": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    occupied: list[tuple[int, int, int, int]] = []
    # A bounded grid makes the layout deterministic, keeps labels fully visible,
    # and avoids artificial shared baselines. Narrow scenes may grow vertically.
    canvas_height = 420
    for rank, index in enumerate(sorted(range(len(sizes)),
                                        key=lambda i: priority.get(levels[i], 3))):
        w, h = sizes[index]
        if w + 24 > width:
            raise ValueError("scene width must accommodate the complete item name")
        anchor_x = width / 2 + rng.uniform(-width * .16, width * .16)
        anchor_y = 180 + rng.uniform(-65, 65)
        x_phase = rng.randrange(16)
        y_phase = rng.randrange(12)
        while True:
            max_x = width - w - 12
            max_y = canvas_height - h - 18
            xs = list(range(12 + x_phase, max_x + 1, 16))
            ys = list(range(58 + y_phase, max_y + 1, 12))
            if not xs or xs[-1] != max_x:
                xs.append(max_x)
            if not ys or ys[-1] != max_y:
                ys.append(max_y)
            candidates = sorted(
                ((x, y) for y in ys for x in xs),
                key=lambda point: (
                    ((point[0] + w / 2 - anchor_x) / max(1, width * .48)) ** 2
                    + ((point[1] + h / 2 - anchor_y) / 245) ** 2,
                    (point[0] + seed * 7 + rank * 19) % 17,
                    point[1],
                ),
            )
            spot = next(((x, y) for x, y in candidates
                         if all(x + w + 8 <= ox or ox + ow + 8 <= x or
                                y + h + 8 <= oy or oy + oh + 8 <= y
                                for ox, oy, ow, oh in occupied)), None)
            if spot is not None:
                positions[index] = spot
                occupied.append((*spot, w, h))
                break
            canvas_height += 120
    return positions, max((y + h for _, y, _, h in occupied), default=0) + 30


def _ground_positions(seed: int, sizes: list[tuple[int, int]], width: int, height: int,
                      levels: list[str] | None = None) -> list[tuple[int, int]]:
    """Compatibility entry point for deterministic nonoverlapping positions."""
    return _ground_layout(seed, sizes, width, levels)[0]


def _ground_label(scene: LootGroundScene, item, decision) -> QLabel:
    text = item.label                   # stacks print as "20x Chaos Orb"; the count never selects a style
    label = QLabel(text, scene)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    provenance = "".join(f"{name:<12} {text}\n" for name, text in decision.sections)
    if provenance and decision.detail_lines:
        provenance += "Why:\n" + "".join(f"  · {line}\n" for line in decision.detail_lines[:4])
    label.setToolTip(
        f"{decision.importance} · {'HIDDEN' if decision.hidden else 'SHOWN'} · {decision.source}\n"
        + (provenance + "\n" if provenance else "") +
        f"{decision.reason}\nRule: {decision.rule_name}\n"
        f"Matched item: {item.item_class} / {item.base_type or item.name} · {item.rarity} · item level {item.item_level}\n"
        f"Style family: {decision.style_role.replace('_', ' ')}\nNative style: {decision.native_details}\n"
        f"Evidence: {decision.provenance}")
    label.setStyleSheet(decision.stylesheet + " padding: 6px 10px;")
    font = QFont("Georgia")
    # PoE2's supplied capture uses tracked small caps. Georgia is the closest
    # installed serif fallback; the exact game font and UI scale remain unknown.
    font.setPixelSize(round(decision.font_size * .66))
    font.setWeight(QFont.Weight.Medium)
    font.setCapitalization(QFont.Capitalization.SmallCaps)
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing,
                          max(1.0, font.pixelSize() * .085))
    label.setFont(font)
    metrics = QFontMetrics(font)
    bounds = metrics.boundingRect(text)
    width = max(42, max(bounds.width(), metrics.horizontalAdvance(text)) + 22)
    height = max(28, metrics.height() + 18)
    label.setFixedSize(width, height)
    return label


class FiltersPage(QWidget):
    def __init__(self, controller: EvaluationController, settings: AppSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.settings = settings
        self._filter_dir: Path | None = None
        self._fingerprint = None
        self._needs: BuildNeedsSnapshot | None = None        # production Build Intelligence for the CURRENT build
        self._intel_state = IntelState.NOT_ANALYZED
        self._intel_error = ""
        self._analysis_request = None
        self._generated_with = "fallback"                    # which measurement the current filter text was built from
        self._rules = []
        self._filter_text = ""
        self._validation = None
        self._last_generated: tuple[str, str, str] | None = None
        self._seed = random.randrange(1_000_000)

        def section(title):
            host = Section(title)
            host._title.setText(title)
            return host

        config = section("Choose your filter")
        self._personalization = QLabel("General")
        self._personalization.setObjectName("fieldLabel")
        self._personalization.setWordWrap(True)
        self._analyze = make_button("Analyze Build", "secondary", compact=True)
        self._analyze.setToolTip("Optional: measure build responses in PoB for personalized opportunities.")
        self._analyze.clicked.connect(self._analyze_clicked)
        state_row = QHBoxLayout()
        state_row.addWidget(self._personalization, 1)
        state_row.addWidget(self._analyze)
        config.add_layout(state_row)
        row = QHBoxLayout()
        self._profile = QComboBox()
        self._profile.setAccessibleName("Loot filter profile")
        for name in FilterProfileName:
            self._profile.addItem(name.value, name)
        from exilelens.filters.profile_policy import normalize_level
        saved_level, _ = normalize_level(getattr(settings, "filter_profile", ""))
        self._profile.setCurrentIndex(self._profile.findData(FilterProfileName(saved_level)))
        self._theme = QComboBox()
        self._theme.setAccessibleName("Loot filter theme")
        for name in FilterThemeName:
            self._theme.addItem(name.value, name)
        saved_theme = self._theme.findText(getattr(settings, "filter_theme", "Void Gold"))
        self._theme.setCurrentIndex(max(0, saved_theme))
        for title, control in (("Profile", self._profile), ("Theme", self._theme)):
            field = QVBoxLayout()
            label = QLabel(title)
            label.setBuddy(control)
            field.addWidget(label)
            field.addWidget(control)
            row.addLayout(field, 1)
        config.add_layout(row)
        self._profile_intent = QLabel()
        self._profile_intent.setWordWrap(True)
        self._profile_intent.setObjectName("helperText")
        config.add_widget(self._profile_intent)
        self._theme_intent = QLabel()
        self._theme_intent.setWordWrap(True)
        config.add_widget(self._theme_intent)
        self._profile_notice = QLabel(getattr(settings, "filter_profile_notice", ""))
        self._profile_notice.setWordWrap(True)
        self._profile_notice.setVisible(bool(self._profile_notice.text()))
        config.add_widget(self._profile_notice)
        self._install = make_button("Generate && Install", "primary")
        self._install.setAccessibleName("Generate & Install")
        self._install.clicked.connect(self._generate_install)
        self._check_install = make_button("Check installation", "secondary")
        self._check_install.clicked.connect(self._check_or_choose_directory)
        install_actions = QHBoxLayout()
        install_actions.addWidget(self._install)
        install_actions.addWidget(self._check_install)
        install_actions.addStretch(1)
        config.add_layout(install_actions)
        self._status = QLabel()
        self._status.setWordWrap(True)
        config.add_widget(self._status)
        self._configuration_state = QLabel()
        self._configuration_state.setWordWrap(True)
        self._configuration_state.setObjectName("helperText")
        config.add_widget(self._configuration_state)
        self._sync_notice = QLabel()
        self._sync_notice.setWordWrap(True)
        self._sync_notice.setObjectName("helperText")
        config.add_widget(self._sync_notice)

        preview = section("Preview")
        preview_controls = QHBoxLayout()
        self._scene_preset = QComboBox()
        self._scene_preset.setAccessibleName("Preview sample")
        for name in ("Mixed Loot", "Showcase", RANDOM_SCENE, "Real Game Cluster", "Hero Cluster", "Value Dense",
                     "Hero Drop", "Clutter Stress Test", "Observed Currency"):
            self._scene_preset.addItem(name)
        self._environment = QComboBox()
        self._environment.setAccessibleName("Preview lighting")
        self._environment.addItems(("Dark ruins", "Sunlit stone"))
        reroll = make_button("Reroll", "secondary", compact=True)
        reroll.setAccessibleName("Reroll preview sample")
        reroll.clicked.connect(self._reroll)
        preview_controls.addWidget(self._scene_preset, 1)
        preview_controls.addWidget(self._environment, 1)
        preview_controls.addWidget(reroll)
        preview.add_layout(preview_controls)
        self._preview_status = QLabel()
        self._preview_status.setWordWrap(True)
        self._preview_status.setObjectName("helperText")
        preview.add_widget(self._preview_status)
        self._family_badges = []
        self._scene = LootGroundScene()
        self._scene.width_changed.connect(self._reflow_preview)
        self._preview_labels = []
        self._preview_decisions = []
        self._preview_levels = []
        preview.add_widget(self._scene)
        sample_note = QLabel("Same sample across profiles. Hover a label for its decision; reroll to change the sample.")
        sample_note.setWordWrap(True)
        sample_note.setObjectName("helperText")
        preview.add_widget(sample_note)

        details = Disclosure("Details & diagnostics")
        self._build_label = QLabel()
        self._build_label.setWordWrap(True)
        details.add_widget(self._build_label)
        refresh = make_button("Refresh build", "secondary", compact=True)
        refresh.clicked.connect(self._refresh_build)
        details.add_widget(refresh)
        self._intel_label = QLabel()
        self._intel_label.setWordWrap(True)
        self._intel_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        details.add_widget(self._intel_label)
        self._intelligence_note = QLabel()
        self._intelligence_note.setWordWrap(True)
        details.add_widget(self._intelligence_note)
        self._preview_mode_note = QLabel("Preview labels resolve the generated native actions. Font, sound and beam rendering require comparison in PoE2. Build and crafting candidates are opportunities, not confirmed upgrades. Trade relevance uses offline heuristics, without live prices.")
        self._preview_mode_note.setWordWrap(True)
        details.add_widget(self._preview_mode_note)
        self._effect_status = QLabel()
        self._effect_status.setWordWrap(True)
        details.add_widget(self._effect_status)
        self._directory = QLabel()
        self._directory.setWordWrap(True)
        self._directory.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        details.add_widget(self._directory)
        tools = QHBoxLayout()
        detect = make_button("Detect folder", "secondary", compact=True)
        detect.clicked.connect(self._detect_directory)
        override = make_button("Choose folder…", "secondary", compact=True)
        override.clicked.connect(self._override_directory)
        self._open = make_button("Open folder", "secondary", compact=True)
        self._open.clicked.connect(self._open_directory)
        for button in (detect, override, self._open):
            tools.addWidget(button)
        details.add_layout(tools)
        self._installed = QLabel()
        self._installed.setWordWrap(True)
        details.add_widget(self._installed)
        self._hashes = QLabel()
        self._hashes.setWordWrap(True)
        self._hashes.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        details.add_widget(self._hashes)

        content = QWidget()
        column = QVBoxLayout(content)
        column.setContentsMargins(theme.PAGE_GUTTER, 12, theme.PAGE_GUTTER, 20)
        column.setSpacing(14)
        for host in (config, preview, details):
            column.addWidget(host)
        column.addStretch(1)
        scroll = QScrollArea()
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        apply_scroll_area_theme(scroll, viewport_object_name="filtersScrollViewport")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        title = QLabel("Loot Filters")
        title.setObjectName("pageTitle")
        title.setContentsMargins(theme.PAGE_GUTTER, 20, theme.PAGE_GUTTER, 0)
        layout.addWidget(title)
        layout.addWidget(scroll, 1)
        self._profile.currentIndexChanged.connect(self._remember_profile)
        self._profile.currentIndexChanged.connect(self._config_changed)
        self._theme.currentIndexChanged.connect(self._remember_theme)
        self._theme.currentIndexChanged.connect(self._config_changed)
        self._scene_preset.currentIndexChanged.connect(self._render_preview)
        self._environment.currentIndexChanged.connect(self._render_preview)

        controller.build_changed.connect(self._build_changed)
        controller.engine_ready.connect(self._build_changed)
        controller.engine_failed.connect(self._engine_failed)
        for name, slot in (("analysis_started", self._on_analysis_started), ("analysis_finished", self._on_analysis_finished),
                           ("analysis_error", self._on_analysis_error), ("analysis_stale", self._on_analysis_stale)):
            signal = getattr(controller, name, None)
            if signal is not None:
                signal.connect(slot)
        self._age_timer = QTimer(self)
        self._age_timer.setInterval(30_000)
        self._age_timer.timeout.connect(self._update_intel_label)
        self._age_timer.start()
        self._adopt_cached_analysis()
        self._refresh_build_info()
        self._detect_directory()
        self._config_changed()

    def _refresh_build(self) -> None:
        self._build_label.setText("Refreshing connected build...")
        self.controller.reload_build()
        self._refresh_build_info()

    def _build_changed(self, *_args) -> None:
        self._fingerprint = None
        had_measurement = self._needs is not None
        self._needs = None
        self._intel_error = ""
        self._intel_state = IntelState.STALE if had_measurement else IntelState.NOT_ANALYZED
        self._adopt_cached_analysis()          # a still-current production analysis (e.g. from the Analysis page) is reused
        self._refresh_build_info()
        self._config_changed()

    # ---- Build Intelligence (production analysis -> needs snapshot) ---------------------------------------------------
    def _build_label_name(self) -> str:
        info = self.controller.build_info
        return str(getattr(info, "name", "") or Path(str(getattr(info, "path", "") or "build")).stem)

    def _adopt_cached_analysis(self) -> None:
        """Reuse the controller's last analysis when production says it still describes the loaded build."""
        getter = getattr(self.controller, "last_analysis", None)
        payload = getter() if callable(getter) else None
        if payload and self._is_current_analysis(payload):
            self._ingest_analysis(payload)

    def _is_current_analysis(self, payload) -> bool:
        info = self.controller.build_info
        generation = getattr(self.controller, "baseline_generation", None)
        if not is_build_analysis(payload) or generation is None or not getattr(info, "is_ready", False):
            return False
        return is_current(payload, generation=generation, build_path=str(info.path))

    def _ingest_analysis(self, payload) -> None:
        needs = BuildNeedsSnapshot.from_analysis(payload, label=self._build_label_name())
        previous = self._needs
        same_measurement = (previous is not None and previous.measured_at and previous.identity.get("generation") == needs.identity.get("generation")
                            and previous.identity.get("baseline_fingerprint") == needs.identity.get("baseline_fingerprint")
                            and len(previous.signals) == len(needs.signals))
        # A value-profile rescore re-emits the same analysis: it is not a fresh measurement.
        stamp = previous.measured_at if same_measurement else datetime.now(timezone.utc).isoformat(timespec="seconds")
        self._needs = replace(needs, measured_at=stamp)
        self._intel_state = IntelState.CURRENT
        self._intel_error = ""

    def _analyze_clicked(self) -> None:
        submit = getattr(self.controller, "submit_analyze_build", None)
        if not callable(submit) or not self.controller.build_info.is_ready:
            self._intel_state = IntelState.FAILED
            self._intel_error = "no loaded build"
            self._update_intel_label()
            return
        self._analysis_request = submit(defence_probes=True)
        if self._analysis_request is None:
            self._intel_state = IntelState.FAILED
            self._intel_error = "analysis could not be started (module disabled or no build)"
        else:
            self._intel_state = IntelState.ANALYZING
        self._update_intel_label()

    def _on_analysis_started(self, request_id: int) -> None:
        if self._analysis_request is not None and request_id == self._analysis_request:
            self._intel_state = IntelState.ANALYZING
            self._update_intel_label()

    def _on_analysis_finished(self, payload) -> None:
        if not is_build_analysis(payload):
            return
        if not self._is_current_analysis(payload):
            self._intel_state = IntelState.STALE
            self._update_intel_label()
            return
        self._ingest_analysis(payload)
        self._config_changed()                 # regenerate: the filter now follows the measurement

    def _on_analysis_error(self, message: str) -> None:
        if self._intel_state == IntelState.ANALYZING:
            self._intel_state = IntelState.FAILED
            self._intel_error = str(message)
            self._update_intel_label()

    def _on_analysis_stale(self) -> None:
        self._intel_state = IntelState.STALE if self._needs is not None else IntelState.NOT_ANALYZED
        self._needs = None
        self._config_changed()

    def _update_intel_label(self) -> None:
        status = describe(self._needs, state=self._intel_state, error=self._intel_error,
                          data_status=getattr(getattr(self, "_validation", None), "data_status", None),
                          degradations=getattr(getattr(self, "_validation", None), "degradations", ()),
                          build_connected=bool(getattr(self.controller.build_info, "is_ready", False)))
        built_from = "this analysis" if self._needs is not None and self._generated_with == "measured" else "the general filter"
        suffix = f"\nFilter below is built from {built_from}." if self._filter_text else ""
        self._intel_label.setText(status.text + suffix)
        connected = bool(getattr(self.controller.build_info, "is_ready", False))
        if self._intel_state == IntelState.STALE and connected:
            summary = "Analysis outdated"
        elif self._needs is not None and self._needs.has_measurement:
            summary = "Personalized" if self._needs.coverage == Coverage.MEASURED else "Partial personalization"
        else:
            summary = "General"
        if connected:
            summary += " · " + self._build_label_name()
        if self._intel_state == IntelState.ANALYZING:
            summary += " · analyzing…"
        self._personalization.setText(summary)
        if hasattr(self, "_analyze"):
            busy = self._intel_state == IntelState.ANALYZING
            self._analyze.setEnabled(not busy and bool(getattr(self.controller.build_info, "is_ready", False)))
            self._analyze.setText("Analyzing…" if busy else ("Re-analyze Build" if self._needs is not None else "Analyze Build"))

    def _engine_failed(self, message: str) -> None:
        self._build_label.setText(f"Build error: {message}")
        self._preview_status.setText("General filter preview (the build could not be loaded).")

    def _refresh_build_info(self) -> None:
        info = self.controller.build_info
        if not info.is_ready:
            # No build is a product mode, not an error: the general filter is complete without one.
            self._build_label.setText("General filter · no PoB build connected." + chr(10) +
                                      "Connect a PoB build in Overview or Settings for personalized item opportunities.")
            return
        self._build_label.setText(f"{info.name or Path(info.path).stem}\n{info.path}")

    def _ensure_build_model(self) -> None:
        # Generation reconstructs identity from the cached measurement. No synchronous engine calls.
        return

    def on_page_shown(self) -> None:
        self._adopt_cached_analysis()
        self._refresh_build_info()
        self._config_changed()

    def _remember_theme(self) -> None:
        self.settings.filter_theme = self._theme.currentText()
        from exilelens.app.settings import save_settings
        if isinstance(self.settings, AppSettings):
            save_settings(self.settings)

    def _current_needs(self) -> BuildNeedsSnapshot:
        """Measured needs when a current analysis exists; otherwise an explicit conservative fallback (never silent)."""
        if self._needs is not None:
            return self._needs
        if self._fingerprint is None:
            return BuildNeedsSnapshot.unavailable("General filter", "no build connected")
        reason = {IntelState.STALE: "build changed since the last analysis", IntelState.FAILED: f"analysis failed: {self._intel_error}",
                  IntelState.ANALYZING: "analysis in progress"}.get(self._intel_state, "build not analyzed")
        equipped = {slot.value: item.base_type for slot, item in (self._fingerprint.equipped or {}).items() if item.base_type}
        return BuildNeedsSnapshot.unavailable(self._build_label_name(), reason, skill_name=self._fingerprint.main_skill,
                                              equipped=equipped)

    def _generate(self) -> None:
        self._ensure_build_model()
        needs = self._current_needs()
        profile_value = self._profile.currentData()
        theme_value = self._theme.currentData()
        result = generate_filter(needs, profile_value, theme_value, intel=True, fingerprint=self._fingerprint)
        if not result.valid:
            raise ValueError("Generated filter failed validation: " + "; ".join(result.errors[:5]))
        self._rules = result.rules
        self._filter_text = result.text
        self._validation = result
        self._generated_with = "measured" if self._needs is not None else "fallback"
        self._last_generated = (
            getattr(profile_value, "value", profile_value),
            getattr(theme_value, "value", theme_value),
            hashlib.sha256(self._filter_text.encode("utf-8")).hexdigest(),
        )
        self._intelligence_note.setText(
            "Market: HEURISTIC · no live price used for filter generation. Build relevance: candidate bases, not confirmed upgrades. "
            f"Personalization: {needs.coverage.value}"
            + (f" ({'; '.join(needs.coverage_reasons)})" if needs.coverage != Coverage.MEASURED else "") + ".")
        self._update_intel_label()

    def _remember_profile(self) -> None:
        """Persist the chosen strictness; the one-time migration notice goes away after the first deliberate choice."""
        data = self._profile.currentData()                                  # Qt hands a str-enum back as a plain str
        value = str(getattr(data, "value", data) or "")
        if not value or value == getattr(self.settings, "filter_profile", None) and not getattr(self.settings, "filter_profile_notice", ""):
            return
        self.settings.filter_profile = value
        self.settings.filter_profile_notice = ""
        self._profile_notice.setVisible(False)
        try:
            from exilelens.app.settings import save_settings
            save_settings(self.settings)
        except Exception:                      # a read-only settings file must never break the filter page
            pass

    def _config_changed(self, *_args) -> None:
        profile = self._profile.currentData()
        theme_name = self._theme.currentData()
        if profile in PROFILE_INTENT:
            self._profile_intent.setText(PROFILE_INTENT[profile])
        if theme_name in THEME_INTENT:
            description, accent = THEME_INTENT[theme_name]
            self._theme_intent.setText(f"◆  {self._theme.currentText()}  ·  {description}")
            self._theme_intent.setStyleSheet(f"color: {accent}; font-weight: 600;")
            self._scene.update()
            for role, badge in self._family_badges:
                style = native_style(theme_name, role)
                def rgb(value: str) -> str:
                    red, green, blue, *_ = map(int, value.split())
                    return f"rgb({red},{green},{blue})"
                badge.setStyleSheet(
                    f"color: {rgb(style['text_color'])}; "
                    f"background: {rgb(style['bg_color'])}; "
                    f"border: 1px solid {rgb(style['border_color'])}; "
                    "padding: 2px 7px; font-weight: 600;")
        try:
            self._generate()
            self._render_preview()
        except Exception as exc:
            self._filter_text = ""
            self._rules = []
            self._clear_scene()
            self._preview_status.setText(f"Validation blocked preview/install: {exc}")
        self._update_intel_label()
        self._update_installed()
        self._update_actions()

    def _clear_scene(self) -> None:
        self._preview_labels = []
        self._preview_decisions = []
        self._preview_levels = []
        for child in self._scene.findChildren(QLabel):
            child.hide()
            child.setParent(None)
            child.deleteLater()

    def _reroll(self) -> None:
        self._seed = random.randrange(1_000_000)
        self._scene.update()
        self._render_preview()

    def _render_preview(self) -> None:
        self._clear_scene()
        self._scene.beams = []
        self._scene.bright_environment = self._environment.currentIndex() == 1
        if not self._rules:
            self._scene.update()
            return
        rng = random.Random(self._seed)
        preset = self._scene_preset.currentText()
        # curated scenes are fixed references (Reroll moves them); the random scene draws a new floor from the whole pool per Reroll
        items = random_scene_items(self._seed) if preset == RANDOM_SCENE else preview_scene_items(preset)
        rng.shuffle(items)
        entries = [(item, preview_decision(self._rules, item)) for item in items]
        labels = []
        decisions = []
        sizes = []
        levels = []
        counts = {"Build": 0, "Fallback": 0, "Crafting": 0, "Trade": 0,
                  "Protected": 0, "Hidden": 0, "Other": 0, "Default": 0}
        for _, decision in entries:
            counts[decision.source] = counts.get(decision.source, 0) + 1
        for item, decision in visible_preview_entries(entries):
            label = _ground_label(self._scene, item, decision)
            labels.append(label)
            decisions.append(decision)
            sizes.append((label.width(), label.height()))
            levels.append(decision.importance)
        self._preview_labels = labels
        self._preview_decisions = decisions
        self._preview_levels = levels
        self._scene.setMinimumWidth(max((w for w, _ in sizes), default=0) + 24)
        self._reflow_preview()
        effect_rows = [f"{item.name}: beam {decision.effect or 'none'}; minimap {decision.minimap_icon or 'none'}"
                       for item, decision in visible_preview_entries(entries)
                       if decision.effect or decision.minimap_icon]
        self._effect_status.setText("Native effects (separate from labels): " + (" · ".join(effect_rows[:9]) or "none in this scene"))
        quiet = sum(1 for _, d in entries if not d.hidden and d.state == "QUIET")
        self._preview_status.setText(f"{len(labels)} visible · {quiet} quiet · {counts['Hidden']} hidden")

    def _reflow_preview(self, *_args) -> None:
        """Repack existing labels when the available preview width changes."""
        if not self._preview_labels:
            return
        sizes = [(label.width(), label.height()) for label in self._preview_labels]
        scene_width = max(self._scene.width(), max(w for w, _ in sizes) + 24)
        positions, packed_height = _ground_layout(
            self._seed, sizes, scene_width, self._preview_levels)
        self._scene.setMinimumHeight(max(420, packed_height))
        self._scene.beams = []
        for label, decision, (x, y) in zip(
                self._preview_labels, self._preview_decisions, positions):
            label.move(x, y)
            label.show()
            if decision.effect and not decision.hidden:
                self._scene.beams.append(
                    (x + label.width() // 2, y, decision.effect.split()[0], "Temp" not in decision.effect.split()))
        self._scene.update()

    def _detect_directory(self) -> None:
        saved = getattr(self.settings, "filter_directory", "")
        self._filter_dir = Path(saved) if saved and verify_poe2_filter_directory(Path(saved)) else find_poe2_filter_directory()
        self._update_directory()

    def _override_directory(self) -> None:
        picked = QFileDialog.getExistingDirectory(self, "Choose PoE2 filter folder", str(self._filter_dir or Path.home()))
        if picked:
            path = Path(picked)
            if verify_poe2_filter_directory(path):
                self._filter_dir = path
                if isinstance(self.settings, AppSettings):
                    self.settings.filter_directory = str(path)
                    from exilelens.app.settings import save_settings
                    save_settings(self.settings)
                self._update_directory()
            else:
                self._status.setText("Selected folder is unavailable or not writable.")

    def _update_directory(self) -> None:
        valid = bool(self._filter_dir and verify_poe2_filter_directory(self._filter_dir))
        self._directory.setText(f"Detected PoE2 filter folder: {self._filter_dir}" if valid else "PoE2 filter folder was not detected. Choose it manually.")
        self._open.setEnabled(valid)
        self._check_install.setText("Check installation" if valid else "Choose folder…")
        self._update_actions()
        self._update_installed()

    def _check_or_choose_directory(self) -> None:
        if self._filter_dir:
            self._update_installed()
        else:
            self._override_directory()

    def _update_actions(self) -> None:
        self._install.setEnabled(bool(self._filter_text and self._filter_dir and verify_poe2_filter_directory(self._filter_dir)))

    def _open_directory(self) -> None:
        if self._filter_dir and not open_filter_folder(self._filter_dir):
            self._status.setText("Could not open the filter folder.")

    def _update_installed(self) -> None:
        profile = self._profile.currentData()
        profile = getattr(profile, "value", profile)
        info = get_installed_filter_info(self._filter_dir, profile) if self._filter_dir else None
        if info:
            installed_path = self._filter_dir / info['path']
            installed_at = datetime.fromtimestamp(installed_path.stat().st_mtime).astimezone().strftime("%Y-%m-%d %H:%M")
            self._installed.setText(f"Installed file {installed_at} · {info.get('profile', 'Unknown')} / {info.get('theme', 'Unknown')}\n"
                                    f"Build Intelligence: {info.get('intelligence', 'none (legacy file)')}\n{installed_path}")
        else:
            self._installed.setText("No ExileLens filter installed for this profile.")
        selected = (getattr(self._profile.currentData(), "value", self._profile.currentData()),
                    getattr(self._theme.currentData(), "value", self._theme.currentData()))
        generated = self._last_generated
        def hash_lines(value: str) -> str:
            return f"{value[:32]}\n{value[32:]}"
        generated_line = (f"{generated[0]} / {generated[1]}\n"
                          f"Generated SHA-256: {hash_lines(generated[2])}\n"
                          f"Rules SHA-256 (header-independent): {filter_body_sha256(self._filter_text)[:32]}…"
                          if generated else "none")
        installed_line = (f"{info.get('profile', 'Unknown')} / {info.get('theme', 'Unknown')}\n"
                          f"Installed SHA-256: {hash_lines(info['sha256'])}"
                          if info else "none")
        if not self._filter_text or not generated or selected != generated[:2]:
            pending = "Selected configuration has not been generated."
        elif not info or generated[2] != info["sha256"]:
            pending = "Selected generated configuration awaits installation."
        else:
            pending = "Generated file matches the installed file."
        self._hashes.setText(
            f"Selected in dashboard: {selected[0]} / {selected[1]}\n"
            f"Last generated: {generated_line}\n"
            f"Installed file: {installed_line}\n"
            f"{pending}\n"
            "In-game refresh: unconfirmed. The dashboard cannot read which file bytes PoE2 has loaded; "
            "select/refresh the filter in game after installing.")
        self._configuration_state.setText(
            f"Selected: {selected[0]} / {selected[1]}\n"
            f"Generated: {generated[0] + ' / ' + generated[1] if generated and self._filter_text else 'unavailable'}\n"
            f"Installed: {info.get('profile', 'Unknown') + ' / ' + info.get('theme', 'Unknown') if info else 'none'}")
        if (self._filter_text and info and generated and
                info.get("sha256") == generated[2]):
            short_state = "Installed file matches this preview. Confirm refresh in PoE2."
        elif info:
            short_state = (f"Installed file is {info.get('profile', 'Unknown')} / "
                           f"{info.get('theme', 'Unknown')}; this preview is {selected[0]} / {selected[1]}. "
                           "Install this selection before comparing in game.")
        else:
            short_state = "Choose a PoE2 filter folder to install." if not self._filter_dir else "Ready to install."
        self._sync_notice.setText(short_state)

    def _generate_install(self) -> None:
        if not self._filter_dir:
            self._status.setText("Choose a PoE2 filter folder first.")
            return
        self._install.setEnabled(False)
        self._status.setText("Generating and installing...")
        try:
            self._generate()
            profile_data = self._profile.currentData()
            theme_data = self._theme.currentData()
            profile_value = profile_data.value if hasattr(profile_data, "value") else profile_data
            theme_value = theme_data.value if hasattr(theme_data, "value") else theme_data
            result = install_test_filter(self._filter_text, self._filter_dir, profile_value, theme_value)
            if not result.success or not result.verified:
                raise RuntimeError(result.error_message or "Installed file could not be verified")
            coverage = self._current_needs().coverage.value
            self._status.setText(f"Installed and verified {result.filter_name} · {profile_value} / {theme_value} · {coverage} · "
                                 f"{datetime.now().astimezone():%Y-%m-%d %H:%M}. Refresh the item filter in game.")
            self._update_installed()
        except Exception as exc:
            self._status.setText(f"Installation failed: {exc}")
        finally:
            self._update_actions()
