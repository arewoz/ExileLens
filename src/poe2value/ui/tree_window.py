from __future__ import annotations

from typing import Any

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QRadioButton,
    QSlider,
    QSplitter,
    QTextEdit,
    QToolButton,
    QToolTip,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from poe2value.app.controller import EvaluationController
from poe2value.app.settings import save_settings
from poe2value.tree.models import HeatmapMetric, RankingMode
from poe2value.tree.overlay_mode import OverlayMode
from poe2value.tree.view_model import TreeCoachFilters
from poe2value.ui.styles import TREE_COACH_STYLESHEET
from poe2value.ui.tree_graphics import TreeCoachView
from poe2value.ui.tree_legend import TreeLegendWidget
from poe2value.ui.window_policy import WindowInteractionPolicy, apply_native_extended_style, apply_window_interaction_policy


def _fmt_delta(value: float | None) -> str:
    if value is None:
        return "—"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.1f}"


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "—"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.1f}%"


class TreeWorkspace(QWidget):
    """Tree Coach workspace — embeddable in Dashboard or standalone window."""

    def __init__(
        self,
        controller: EvaluationController,
        parent: QWidget | None = None,
        *,
        embed_mode: bool = False,
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self._embed_mode = embed_mode
        settings = controller.settings
        self.model = controller.tree_view_model
        self.model.profile = settings.value_profile
        try:
            self.model.heatmap_metric = HeatmapMetric(settings.tree_heatmap_metric)
        except ValueError:
            pass
        try:
            self.model.ranking_mode = RankingMode(settings.tree_ranking_mode)
        except ValueError:
            pass
        self.model.filters = TreeCoachFilters(
            show_allocated=settings.tree_show_allocated,
            show_frontier=settings.tree_show_frontier,
            show_evaluated=settings.tree_show_evaluated,
            show_unevaluated=settings.tree_show_unevaluated,
            show_notables=settings.tree_show_notables,
            show_keystones=settings.tree_show_keystones,
            show_small=settings.tree_show_small,
        )
        self.setObjectName("treeWorkspaceRoot")
        if not embed_mode:
            self.setWindowTitle("Tree Coach")
            apply_window_interaction_policy(self, WindowInteractionPolicy.INTERACTIVE_TOOL)
        self.setStyleSheet(TREE_COACH_STYLESHEET)
        if not embed_mode:
            self.resize(1320, 900)
        self._debug = bool(settings.debug)
        self._input_receipt: list[str] = []
        self._opened = False

        self.view = TreeCoachView()
        self.view.setMinimumHeight(280)
        self.view.set_model(self.model)
        self.view.nodeHovered.connect(self._on_hover)
        self.view.nodeSelected.connect(self._on_select)
        self._legend = TreeLegendWidget()

        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("Profile"))
        self._profile = QComboBox()
        for name in ("BALANCED", "MAPPING", "BOSSING", "DEFENSIVE"):
            self._profile.addItem(name.title(), name)
        idx = self._profile.findData(settings.value_profile)
        if idx >= 0:
            self._profile.setCurrentIndex(idx)
        self._profile.currentIndexChanged.connect(self._on_profile)
        toolbar.addWidget(self._profile)
        self._btn_next = QPushButton("Analyze Next Points")
        self._btn_next.clicked.connect(lambda: self._note_input("button.clicked") or self._analyze("frontier"))
        toolbar.addWidget(self._btn_next)
        self._metric_vpp = QRadioButton("Value / Point")
        self._metric_total = QRadioButton("Total Value")
        if settings.tree_heatmap_metric == HeatmapMetric.TOTAL_VALUE.value:
            self._metric_total.setChecked(True)
        else:
            self._metric_vpp.setChecked(True)
        self._metric_vpp.toggled.connect(self._on_metric)
        metric_group = QButtonGroup(self)
        metric_group.addButton(self._metric_vpp)
        metric_group.addButton(self._metric_total)
        toolbar.addWidget(QLabel("Heatmap"))
        toolbar.addWidget(self._metric_vpp)
        toolbar.addWidget(self._metric_total)
        fit_alloc = QPushButton("Fit Allocated")
        fit_alloc.clicked.connect(self._fit)
        fit_rel = QPushButton("Fit Relevant")
        fit_rel.clicked.connect(lambda: self.view.fit_relevant())
        fit_all = QPushButton("Fit Entire Tree")
        fit_all.clicked.connect(lambda: self.view.fit_entire_tree())
        self._btn_center = QPushButton("Center Selected")
        self._btn_center.clicked.connect(self._center_selected)
        toolbar.addWidget(fit_alloc)
        toolbar.addWidget(fit_rel)
        toolbar.addWidget(fit_all)
        toolbar.addWidget(self._btn_center)
        self._more = QToolButton()
        self._more.setText("More ▾")
        self._more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        more_menu = QMenu(self)
        vis_action = more_menu.addAction("Analyze Visible")
        vis_action.triggered.connect(lambda: self._note_input("button.clicked") or self._analyze_visible())
        r3_action = more_menu.addAction("Nearby ≤3")
        r3_action.triggered.connect(lambda: self._note_input("button.clicked") or self._analyze("radius3"))
        r5_action = more_menu.addAction("Nearby ≤5")
        r5_action.triggered.connect(lambda: self._note_input("button.clicked") or self._analyze("radius5"))
        re_action = more_menu.addAction("Re-analyze")
        re_action.triggered.connect(lambda: self._note_input("button.clicked") or self._analyze("frontier"))
        more_menu.addSeparator()
        self._rank_vpp = QRadioButton("Rank by Value / Point")
        self._rank_total = QRadioButton("Rank by Total Value")
        if settings.tree_ranking_mode == RankingMode.TOTAL.value:
            self._rank_total.setChecked(True)
        else:
            self._rank_vpp.setChecked(True)
        self._rank_vpp.toggled.connect(self._on_rank)
        rank_group = QButtonGroup(self)
        rank_group.addButton(self._rank_vpp)
        rank_group.addButton(self._rank_total)
        rank_widget = QWidget()
        rank_layout = QVBoxLayout(rank_widget)
        rank_layout.setContentsMargins(8, 4, 8, 4)
        rank_layout.addWidget(self._rank_vpp)
        rank_layout.addWidget(self._rank_total)
        rank_action = QWidgetAction(self)
        rank_action.setDefaultWidget(rank_widget)
        more_menu.addAction(rank_action)
        self._more.setMenu(more_menu)
        toolbar.addWidget(self._more)
        toolbar.addStretch(1)
        self._btn_r3 = QPushButton()
        self._btn_r3.hide()
        self._btn_r3.clicked.connect(lambda: self._note_input("button.clicked") or self._analyze("radius3"))
        self._btn_r5 = QPushButton()
        self._btn_r5.hide()
        self._btn_r5.clicked.connect(lambda: self._note_input("button.clicked") or self._analyze("radius5"))
        self._btn_re = QPushButton()
        self._btn_re.hide()
        self._btn_re.clicked.connect(lambda: self._note_input("button.clicked") or self._analyze("frontier"))
        self._btn_vis = QPushButton()
        self._btn_vis.hide()
        self._btn_vis.clicked.connect(lambda: self._note_input("button.clicked") or self._analyze_visible())
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search node name")
        self._search.returnPressed.connect(self._run_search)
        self._search.installEventFilter(self)
        search_btn = QPushButton("Find")
        search_btn.clicked.connect(self._run_search)
        toolbar.addWidget(self._search, 1)
        toolbar.addWidget(search_btn)

        status_row = QHBoxLayout()
        self._stale = QLabel("")
        self._stale.setObjectName("staleBanner")
        self._coverage = QLabel("Next points 0 / 0")
        self._coverage.setObjectName("baselineLabel")
        self._progress = QLabel("")
        self._progress.setObjectName("analyzingLabel")
        self._btn_cancel = QPushButton("Cancel")
        self._btn_cancel.clicked.connect(lambda: self._note_input("button.clicked") or self.controller.cancel_tree_analysis())
        status_row.addWidget(self._coverage)
        status_row.addWidget(self._progress, 1)
        status_row.addWidget(self._stale)
        status_row.addWidget(self._btn_cancel)

        self._eval_label = QLabel("EVALUATION BUILD: —")
        self._eval_label.setObjectName("compactNote")
        self._track_label = QLabel("TRACKING GUIDE TREE: —")
        self._track_label.setObjectName("compactNote")
        self._engine_status = QLabel("ENGINE\nNO BUILD")
        self._engine_status.setObjectName("baselineLabel")

        self._list = QListWidget()
        self._list.itemClicked.connect(self._on_list)
        self._detail = QTextEdit()
        self._detail.setReadOnly(True)
        self._detail.setMinimumHeight(120)

        rec_panel = QWidget()
        rec_l = QVBoxLayout(rec_panel)
        rec_l.setContentsMargins(0, 0, 0, 0)
        rec_l.addWidget(QLabel("Recommendations"))
        rec_l.addWidget(self._list)
        detail_panel = QWidget()
        detail_l = QVBoxLayout(detail_panel)
        detail_l.setContentsMargins(0, 0, 0, 0)
        detail_l.addWidget(QLabel("Selected Node"))
        detail_l.addWidget(self._detail)
        bottom_split = QSplitter(Qt.Orientation.Horizontal)
        bottom_split.addWidget(rec_panel)
        bottom_split.addWidget(detail_panel)
        bottom_split.setStretchFactor(0, 1)
        bottom_split.setStretchFactor(1, 1)

        main_split = QSplitter(Qt.Orientation.Vertical)
        main_split.addWidget(self.view)
        main_split.addWidget(bottom_split)
        main_split.setStretchFactor(0, 7)
        main_split.setStretchFactor(1, 3)
        self._main_split = main_split
        self._bottom_split = bottom_split

        self._filter_boxes: dict[str, QCheckBox] = {}
        filters = QHBoxLayout()
        for key, label, attr in (
            ("allocated", "Allocated", "show_allocated"),
            ("frontier", "Frontier", "show_frontier"),
            ("evaluated", "Evaluated", "show_evaluated"),
            ("unevaluated", "Unevaluated", "show_unevaluated"),
            ("notables", "Notables", "show_notables"),
            ("keystones", "Keystones", "show_keystones"),
            ("small", "Small", "show_small"),
        ):
            box = QCheckBox(label)
            box.setChecked(getattr(self.model.filters, attr))
            box.toggled.connect(self._on_filters)
            box.toggled.connect(lambda _checked=False: self._note_input("checkbox"))
            self._filter_boxes[key] = box
            filters.addWidget(box)
        filters.addStretch(1)

        self._btn_overlay = QPushButton("Show Tree Overlay")
        self._btn_calibrate = QPushButton("Calibrate Tree Overlay…")
        self._btn_overlay.clicked.connect(self._toggle_overlay)
        self._btn_calibrate.clicked.connect(self._calibrate_overlay)
        self._btn_anchor_a = QPushButton("Use as Anchor A")
        self._btn_anchor_b = QPushButton("Use as Anchor B")
        self._btn_anchor_a.clicked.connect(lambda: self._assign_anchor("A"))
        self._btn_anchor_b.clicked.connect(lambda: self._assign_anchor("B"))

        self._advanced = QGroupBox("Advanced / Experimental")
        self._advanced.setCheckable(True)
        self._advanced.setChecked(False)
        adv_layout = QVBoxLayout(self._advanced)
        adv_layout.addWidget(self._eval_label)
        adv_layout.addWidget(self._track_label)
        adv_layout.addWidget(self._build_live_path_panel())
        overlay_note = QLabel("Live Tree Overlay — EXPERIMENTAL · Human validation incomplete")
        overlay_note.setObjectName("staleBanner")
        overlay_note.setWordWrap(True)
        adv_layout.addWidget(overlay_note)
        adv_layout.addWidget(self._build_calibration_panel())
        adv_layout.addLayout(filters)
        adv_layout.addWidget(self._engine_status)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        layout.addLayout(toolbar)
        layout.addLayout(status_row)
        layout.addWidget(self._legend)
        layout.addWidget(main_split, 1)
        layout.addWidget(self._advanced)

        controller.analysis_finished.connect(self._on_analysis)
        controller.analysis_stale.connect(self._on_stale)
        controller.analysis_progress.connect(self._on_progress)
        controller.analysis_started.connect(lambda _rid: self._progress.setText("Analyzing…"))
        controller.analysis_error.connect(lambda msg: self._progress.setText(str(msg)))
        controller.build_changed.connect(lambda _info: self._refresh_header())
        controller.baseline_state_changed.connect(lambda _state: self._refresh_header())
        controller.tracked_tree_changed.connect(lambda _payload: self._refresh_tracked_labels())
        controller.tracked_tree_sets_changed.connect(self._on_tracked_sets)
        controller.tracked_tree_error.connect(lambda msg: self._track_label.setText(f"TRACKING GUIDE TREE: {msg}"))
        self.view.installEventFilter(self)
        self.view.viewport().installEventFilter(self)
        self.installEventFilter(self)

    def _note_input(self, kind: str) -> None:
        self._input_receipt.append(kind)

    def eventFilter(self, watched, event):  # noqa: N802
        etype = event.type()
        if etype == QEvent.Type.MouseButtonPress:
            self._note_input("mousePress")
            if watched in {self.view, self.view.viewport()}:
                self._note_input("graphics-scene")
        elif etype == QEvent.Type.MouseMove:
            if "mouseMove" not in self._input_receipt:
                self._note_input("mouseMove")
        elif etype == QEvent.Type.Wheel:
            self._note_input("wheel")
        elif etype == QEvent.Type.FocusIn and watched is self._search:
            self._note_input("search-focus")
        return super().eventFilter(watched, event)

    def _persist(self) -> None:
        s = self.controller.settings
        s.tree_heatmap_metric = self.model.heatmap_metric.value
        s.tree_ranking_mode = self.model.ranking_mode.value
        s.tree_show_allocated = self.model.filters.show_allocated
        s.tree_show_frontier = self.model.filters.show_frontier
        s.tree_show_evaluated = self.model.filters.show_evaluated
        s.tree_show_unevaluated = self.model.filters.show_unevaluated
        s.tree_show_notables = self.model.filters.show_notables
        s.tree_show_keystones = self.model.filters.show_keystones
        s.tree_show_small = self.model.filters.show_small
        save_settings(s)

    def _refresh_header(self) -> None:
        if not self._embed_mode:
            baseline = self.controller.resolved_baseline()
            name = baseline.build_name or self.controller.build_info.name or "Build"
            ctx = baseline.context or getattr(self.controller.build_info, "context", self.controller.settings.context)
            profile = self.controller.settings.value_profile.title()
            item_label = baseline.item_set_name or (f"Item Set {baseline.item_set_id}" if baseline.item_set_id else "")
            if baseline.item_set_id and not baseline.item_set_valid:
                item_label = f"{item_label} (unresolved)"
            tree_label = baseline.tree_set_name
            bits = [name, ctx, profile]
            if tree_label:
                bits.append(tree_label)
            if item_label:
                bits.append(item_label)
        lines = self.controller.baseline_state.status_lines()
        self._engine_status.setText("ENGINE\n" + "\n".join(lines))
        cov = self.model.coverage()
        if cov.frontier_total or self.model.snapshot is not None:
            self._coverage.setText(f"Next points {cov.frontier_done} / {cov.frontier_total}")
        self._refresh_tracked_labels()

    def _refresh_tracked_labels(self) -> None:
        baseline = self.controller.resolved_baseline()
        eval_bits = [baseline.build_name or "—", baseline.context or "MAP"]
        if baseline.tree_set_name:
            eval_bits.append(baseline.tree_set_name)
        self._eval_label.setText("EVALUATION BUILD: " + " · ".join(eval_bits))
        source = self.controller.tracked_tree_source
        if source is not None:
            alloc = len(source.passive_tree_snapshot.allocated_ids())
            self._track_label.setText(
                f"TRACKING GUIDE TREE: {source.display_label} · {alloc} allocated nodes"
            )
        elif self.controller._tracked_tree_loading:
            self._track_label.setText("TRACKING GUIDE TREE: Loading…")
        else:
            self._track_label.setText("TRACKING GUIDE TREE: Not loaded — pick a tracked build below")

    def _build_live_path_panel(self) -> QWidget:
        box = QGroupBox("LIVE BUILD PATH")
        layout = QVBoxLayout(box)
        row = QHBoxLayout()
        pick_build = QPushButton("Tracked Build…")
        pick_build.clicked.connect(self._pick_tracked_build)
        self._tracked_build = QLabel(self.controller.settings.tracked_build_path or "(same as evaluation)")
        self._tracked_build.setObjectName("compactNote")
        self._tracked_tree = QComboBox()
        self._tracked_tree.currentIndexChanged.connect(self._on_tracked_tree_changed)
        prev_tree = QPushButton("<")
        prev_tree.setFixedWidth(28)
        prev_tree.clicked.connect(lambda: self.controller.step_tracked_tree_set(-1))
        next_tree = QPushButton(">")
        next_tree.setFixedWidth(28)
        next_tree.clicked.connect(lambda: self.controller.step_tracked_tree_set(1))
        reload_btn = QPushButton("Reload Tracked Tree")
        reload_btn.clicked.connect(lambda: self.controller.reload_tracked_tree())
        show_path = QPushButton("Show Build Path")
        show_path.clicked.connect(self._show_build_path)
        row.addWidget(pick_build)
        row.addWidget(self._tracked_build, 1)
        layout.addLayout(row)
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Tracked Tree Set"))
        row2.addWidget(prev_tree)
        row2.addWidget(self._tracked_tree, 1)
        row2.addWidget(next_tree)
        row2.addWidget(reload_btn)
        row2.addWidget(show_path)
        layout.addLayout(row2)
        note = QLabel("BUILD PATH overlay uses the tracked tree only. Next Points / Heatmap use the evaluation build.")
        note.setObjectName("compactNote")
        note.setWordWrap(True)
        layout.addWidget(note)
        return box

    def _pick_tracked_build(self) -> None:
        self._note_input("button.clicked")
        start = self.controller.settings.tracked_build_path or self.controller.build_info.path
        path, _ = QFileDialog.getOpenFileName(self, "Select Tracked PoB Build", start, "PoB Builds (*.xml)")
        if path:
            self.controller.reload_tracked_tree(build_path=path)

    def _on_tracked_sets(self, payload: object) -> None:
        if not isinstance(payload, dict):
            return
        sets = list(payload.get("tree_sets") or [])
        path = str(payload.get("build_path") or "")
        if path:
            self._tracked_build.setText(path)
        self._tracked_tree.blockSignals(True)
        self._tracked_tree.clear()
        current = str(self.controller.settings.tracked_tree_set_id or "")
        pick = 0
        for idx, entry in enumerate(sets):
            sid = str(entry.get("id") or entry.get("index") or "")
            title = str(entry.get("title") or f"Tree {sid}")
            self._tracked_tree.addItem(title, sid)
            if sid == current or (not current and entry.get("active")):
                pick = idx
        if sets:
            self._tracked_tree.setCurrentIndex(pick)
        self._tracked_tree.blockSignals(False)
        self._refresh_tracked_labels()

    def _on_tracked_tree_changed(self) -> None:
        sid = str(self._tracked_tree.currentData() or "")
        if sid and sid != str(self.controller.settings.tracked_tree_set_id or ""):
            self.controller.set_tracked_tree_set(sid)

    def _show_build_path(self) -> None:
        self._note_input("button.clicked")
        self.controller.set_tree_overlay_mode(OverlayMode.BUILD_PATH.value)
        self.controller.settings.tree_overlay_enabled = True
        save_settings(self.controller.settings)
        self.controller.tree_overlay_show_requested.emit(True)

    def _fit(self) -> None:
        self.view.fit_allocated()

    def _center_selected(self) -> None:
        if self.view.selected_id is not None:
            self._focus_node(int(self.view.selected_id))

    def viewport_sizes(self) -> dict[str, int]:
        tree = self.view.viewport().size()
        bottom = self._bottom_split.size()
        return {
            "tree_width": tree.width(),
            "tree_height": tree.height(),
            "bottom_width": bottom.width(),
            "bottom_height": bottom.height(),
            "workspace_width": self.width(),
            "workspace_height": self.height(),
        }

    def _on_stale(self) -> None:
        self.model.mark_stale()
        self._stale.setText("STALE — Re-analyze")
        self.view.rebuild()
        self._refresh_panels()

    def _analyze(self, scope: str) -> None:
        self.controller.settings.tree_analysis_radius = {"frontier": 1, "radius3": 3, "radius5": 5}.get(scope, 1)
        save_settings(self.controller.settings)
        self.controller.submit_tree_analysis(scope=scope)

    def _analyze_visible(self) -> None:
        ids = self.view.visible_node_ids()
        self.controller.submit_tree_analysis(scope="visible", node_ids=ids)

    def _on_progress(self, payload: object) -> None:
        if not isinstance(payload, dict):
            return
        stage = str(payload.get("stage") or "")
        done = payload.get("done")
        total = payload.get("total")
        if stage == "frontier":
            label = "Analyzing next passive points..."
        elif str(payload.get("scope")) == "radius5" or payload.get("max_points") == 5:
            label = "Nearby ≤5"
        elif str(payload.get("scope")) == "visible":
            label = "Visible area targets"
        else:
            label = "Nearby ≤3"
        if done is not None and total is not None:
            self._progress.setText(f"{label}\n{done} / {total}")
        else:
            self._progress.setText(label)

    def _on_analysis(self, result: dict[str, Any]) -> None:
        if result.get("kind") not in {"tree", "tree_snapshot"} and not result.get("nodes"):
            return
        if result.get("nodes") or result.get("graph") or result.get("kind") == "tree_snapshot":
            payload = dict(result.get("graph") or result)
            if result.get("baseline") and not payload.get("baseline"):
                payload["baseline"] = result["baseline"]
            had_snapshot = self.model.snapshot is not None
            self.model.ingest_graph_payload(payload)
            self.view.set_model(self.model)
            if not had_snapshot:
                self.view.fit_allocated()
        if result.get("kind") == "tree":
            self.model.ingest_analysis(result, scope=result.get("scope"))
            self.view.rebuild()
        self._refresh_header()
        self._stale.setText("")
        self._progress.setText("")
        self._refresh_panels()
        self.refresh_calibration_panel()
        if result.get("kind") == "tree_snapshot" and not self.model.frontier_cached():
            self.controller.submit_tree_analysis(scope="frontier")

    def _on_profile(self) -> None:
        profile = str(self._profile.currentData() or "BALANCED")
        self.controller.set_value_profile(profile)
        self.model.rescore_profile(profile)
        self.view.rebuild()
        self._refresh_header()
        self._refresh_panels()

    def _on_metric(self) -> None:
        metric = HeatmapMetric.VALUE_PER_POINT if self._metric_vpp.isChecked() else HeatmapMetric.TOTAL_VALUE
        self.model.set_heatmap_metric(metric)
        self.view.rebuild()
        self._persist()
        self._refresh_panels()

    def _on_rank(self) -> None:
        mode = RankingMode.EFFICIENCY if self._rank_vpp.isChecked() else RankingMode.TOTAL
        self.model.set_ranking_mode(mode)
        self.view.rebuild()
        self._persist()
        self._refresh_panels()

    def _on_filters(self) -> None:
        f = self.model.filters
        f.show_allocated = self._filter_boxes["allocated"].isChecked()
        f.show_frontier = self._filter_boxes["frontier"].isChecked()
        f.show_evaluated = self._filter_boxes["evaluated"].isChecked()
        f.show_unevaluated = self._filter_boxes["unevaluated"].isChecked()
        f.show_notables = self._filter_boxes["notables"].isChecked()
        f.show_keystones = self._filter_boxes["keystones"].isChecked()
        f.show_small = self._filter_boxes["small"].isChecked()
        self.view.rebuild()
        self._persist()

    def _run_search(self) -> None:
        hits = self.model.search(self._search.text())
        if not hits:
            return
        self._focus_node(int(hits[0]["node_id"]))

    def _on_list(self, item: QListWidgetItem) -> None:
        nid = item.data(Qt.ItemDataRole.UserRole)
        if nid is not None:
            self._focus_node(int(nid))

    def _focus_node(self, node_id: int) -> None:
        self.view.select_node(node_id)
        self.view.center_on_node(node_id)

    def _on_hover(self, node_id: object) -> None:
        if node_id is None or self.model.snapshot is None:
            QToolTip.hideText()
            return
        pres = self.model.presentation(int(node_id))
        if pres is None:
            return
        if pres.unsupported:
            QToolTip.showText(
                self.view.mapToGlobal(self.view.cursor().pos()),
                f"{pres.name}\nAnalysis not supported for this node type yet.",
            )
            return
        ev = self.model.evaluations.get(int(node_id)) or {}
        lines = [pres.name.upper(), f"Cost                  {pres.cost if pres.cost is not None else '—'}", f"Value               {_fmt_delta(pres.heat_value)}"]
        if ev.get("value_per_point") is not None:
            lines.append(f"Value / point       {_fmt_delta(float(ev['value_per_point']))}")
        metrics = ev.get("metrics") or {}
        dmg = (metrics.get("primary_offense") or {}).get("percent_delta")
        ehp = (metrics.get("ehp") or {}).get("percent_delta")
        if dmg is not None:
            lines.append(f"Damage              {_fmt_pct(float(dmg))}")
        if ehp is not None:
            lines.append(f"EHP                 {_fmt_pct(float(ehp))}")
        lines.append(pres.band.value.replace("UNKNOWN", "UNEVALUATED"))
        scores = ev.get("profile_scores") or {}
        if scores:
            lines.append("")
            for key in ("BALANCED", "MAPPING", "BOSSING", "DEFENSIVE"):
                if key in scores:
                    lines.append(f"{key.title():<12} {_fmt_delta(float(scores[key]))}")
        QToolTip.showText(self.cursor().pos(), "\n".join(lines))

    def _on_select(self, node_id: object) -> None:
        self._render_detail(None if node_id is None else int(node_id))

    def _render_detail(self, node_id: int | None) -> None:
        if node_id is None:
            self._detail.setPlainText("Select a node")
            return
        detail = self.model.selected_detail(node_id)
        if not detail:
            return
        if detail.get("unsupported"):
            self._detail.setPlainText(f"{detail['name']}\n\nAnalysis not supported for this node type yet.")
            return
        lines = [
            str(detail["name"]).upper(),
            f"Type: {detail['type']}",
            f"Role: {detail['role']}",
            f"Status: {detail['status']}",
        ]
        if self._debug:
            lines.append(f"Node ID: {detail['node_id']}")
        cost = detail.get("cost")
        lines.append(f"Cost to reach: {cost if cost is not None else '—'} points")
        if detail.get("path_includes_travel"):
            lines.append("Path Value includes the full missing path, not the notable alone.")
        lines.append(f"Path Value: {_fmt_delta(detail.get('path_value'))}")
        lines.append(f"Value / Point: {_fmt_delta(detail.get('value_per_point'))}")
        lines.append(f"Damage: {_fmt_pct(detail.get('primary_offense_pct'))}")
        lines.append(f"EHP: {_fmt_pct(detail.get('ehp_pct'))}")
        lines.append(f"Max Hit: {_fmt_pct(detail.get('max_hit_pct'))}")
        if detail.get("breakpoints"):
            lines.append("")
            for bp in detail["breakpoints"]:
                lines.append(f"★ {bp.get('label') or bp.get('code')}")
        if detail.get("warnings"):
            lines.append("")
            for warn in detail["warnings"]:
                lines.append(str(warn.get("message") or warn.get("code") or warn))
        if detail.get("profile_scores"):
            lines.append("")
            lines.append("Cached profile scores (no extra PoB):")
            for key, val in detail["profile_scores"].items():
                lines.append(f"  {key.title()}: {_fmt_delta(float(val))}")
        if detail.get("confidence"):
            lines.append(f"Confidence: {detail['confidence']}")
        if detail.get("path"):
            lines.append(f"Path: {detail['path']}")
        session = self.controller.calibration_session
        if session.anchor_a and session.anchor_a.node_id == node_id:
            lines.append("Calibration Anchor A")
        if session.anchor_b and session.anchor_b.node_id == node_id:
            lines.append("Calibration Anchor B")
        self._detail.setPlainText("\n".join(lines))
        if detail.get("path"):
            self.view.set_highlighted_path(detail["path"])

    def _refresh_panels(self) -> None:
        cov = self.model.coverage()
        self._coverage.setText(
            f"Next points {cov.frontier_done} / {cov.frontier_total}   "
            f"≤3 pts {cov.radius3_done}/{cov.radius3_total}   "
            f"≤5 pts {cov.radius5_done}/{cov.radius5_total}"
        )
        self._list.clear()
        for row in self.model.ranked_rows()[:12]:
            label = (
                f"{row['rank']}. {row['name']}   {_fmt_delta(row.get('build_value_delta'))}   "
                f"{_fmt_delta(row.get('value_per_point'))}/pt  cost {row.get('cost')}"
            )
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, row["node_id"])
            self._list.addItem(item)
        if self.view.selected_id is not None:
            self._render_detail(self.view.selected_id)

    def _build_calibration_panel(self) -> QWidget:
        box = QGroupBox("LIVE OVERLAY CALIBRATION (anchors from tracking guide tree)")
        layout = QVBoxLayout(box)
        self._cal_status = QLabel("Status: NOT CALIBRATED")
        self._cal_anchor_a = QLabel("Anchor A: —")
        self._cal_anchor_b = QLabel("Anchor B: —")
        self._cal_warn = QLabel("")
        self._cal_warn.setObjectName("staleBanner")
        self._cal_diag = QLabel("")
        self._cal_diag.setObjectName("compactNote")
        row_assign = QHBoxLayout()
        row_assign.addWidget(self._btn_anchor_a)
        row_assign.addWidget(self._btn_anchor_b)
        suggest = QPushButton("Suggest Anchors")
        suggest.clicked.connect(self._suggest_anchors)
        row_assign.addWidget(suggest)
        cap = QHBoxLayout()
        cap_a = QPushButton("Capture A")
        cap_b = QPushButton("Capture B")
        cap_a.clicked.connect(lambda: self.controller.tree_overlay_capture_requested.emit("A"))
        cap_b.clicked.connect(lambda: self.controller.tree_overlay_capture_requested.emit("B"))
        cap.addWidget(cap_a)
        cap.addWidget(cap_b)
        actions = QHBoxLayout()
        preview = QPushButton("Show Preview")
        preview.clicked.connect(lambda: self.controller.tree_overlay_show_requested.emit(True))
        looks = QPushButton("Looks Good")
        looks.clicked.connect(lambda: self.controller.tree_overlay_looks_good_requested.emit())
        fine = QPushButton("Fine Tune")
        fine.clicked.connect(lambda: self.controller.tree_overlay_fine_tune_requested.emit())
        reset = QPushButton("Reset")
        reset.clicked.connect(self._reset_calibration)
        actions.addWidget(preview)
        actions.addWidget(looks)
        actions.addWidget(fine)
        actions.addWidget(reset)
        extra = QHBoxLayout()
        realign = QPushButton("Quick Re-align")
        realign.clicked.connect(lambda: self.controller.tree_overlay_realign_requested.emit())
        scale = QPushButton("Recalibrate Scale")
        scale.clicked.connect(lambda: self.controller.tree_overlay_scale_requested.emit())
        anchors_only = QPushButton("Show Only Calibration Anchors")
        anchors_only.setCheckable(True)
        anchors_only.toggled.connect(lambda on: self.controller.tree_overlay_anchors_only_requested.emit(bool(on)))
        test_pat = QPushButton("Show Overlay Test Pattern")
        test_pat.clicked.connect(lambda: self.controller.tree_overlay_test_pattern_requested.emit())
        extra.addWidget(realign)
        extra.addWidget(scale)
        extra.addWidget(anchors_only)
        extra.addWidget(test_pat)
        modes = QHBoxLayout()
        for key, title in (
            (OverlayMode.BUILD_PATH.value, "BUILD PATH"),
            (OverlayMode.NEXT_POINTS.value, "NEXT POINTS"),
            (OverlayMode.VALUE_HEATMAP.value, "VALUE HEATMAP"),
        ):
            btn = QPushButton(title)
            btn.clicked.connect(lambda _=False, mode=key: self.controller.set_tree_overlay_mode(mode))
            modes.addWidget(btn)
        appear = QHBoxLayout()
        self._opacity = QSlider(Qt.Orientation.Horizontal)
        self._opacity.setRange(40, 100)
        self._opacity.setValue(int(self.controller.settings.tree_overlay_opacity * 100))
        self._opacity.valueChanged.connect(self._on_appearance)
        self._marker = QSlider(Qt.Orientation.Horizontal)
        self._marker.setRange(6, 20)
        self._marker.setValue(int(self.controller.settings.tree_overlay_marker_size * 10))
        self._marker.valueChanged.connect(self._on_appearance)
        self._line = QSlider(Qt.Orientation.Horizontal)
        self._line.setRange(10, 80)
        self._line.setValue(int(self.controller.settings.tree_overlay_line_width * 10))
        self._line.valueChanged.connect(self._on_appearance)
        appear.addWidget(QLabel("Opacity"))
        appear.addWidget(self._opacity)
        appear.addWidget(QLabel("Marker size"))
        appear.addWidget(self._marker)
        appear.addWidget(QLabel("Line width"))
        appear.addWidget(self._line)
        layout.addWidget(self._cal_status)
        layout.addWidget(self._cal_anchor_a)
        layout.addWidget(self._cal_anchor_b)
        layout.addLayout(row_assign)
        layout.addLayout(cap)
        layout.addLayout(actions)
        layout.addLayout(extra)
        layout.addLayout(modes)
        layout.addLayout(appear)
        layout.addWidget(self._cal_warn)
        layout.addWidget(self._cal_diag)
        self.refresh_calibration_panel()
        return box

    def refresh_calibration_panel(self) -> None:
        session = self.controller.calibration_session
        status = session.ui_status().value
        self._cal_status.setText(f"Status: {status}")
        a = session.anchor_a
        b = session.anchor_b
        a_mark = " ✓" if a and a.captured else ""
        b_mark = " ✓" if b and b.captured else ""
        self._cal_anchor_a.setText(f"Anchor A: {a.name if a else '—'}{a_mark}")
        self._cal_anchor_b.setText(f"Anchor B: {b.name if b else '—'}{b_mark}")
        self._cal_warn.setText(session.warning or session.verify_label())
        diag = self.controller.tree_overlay_diagnostics or {}
        cov = diag.get("coverage") or {}
        bits = []
        if cov:
            bits.append(
                f"PoB Build Path: {cov.get('allocated_target', 0)} nodes  Mapped: {cov.get('mapped', 0)}  "
                f"Visible in PoE client: {cov.get('inside_client', 0)}  Outside: {cov.get('outside_client', 0)}"
            )
        if diag.get("misalignment"):
            bits.append(str(diag["misalignment"]))
        hwnd = diag.get("hwnd") or {}
        if hwnd:
            bits.append(f"HWND {hwnd.get('hwnd')} topmost={hwnd.get('topmost')} click-through={hwnd.get('click_through')}")
        self._cal_diag.setText("\n".join(bits))
        self.view.set_calibration_anchors(
            a.node_id if a else None,
            b.node_id if b else None,
        )

    def _selected_tree_node(self):
        nid = self.view.selected_id
        snap = self.controller.tracked_snapshot()
        if nid is None or snap is None:
            return None
        return snap.node(int(nid))

    def _assign_anchor(self, slot: str) -> None:
        self._note_input("button.clicked")
        node = self._selected_tree_node()
        warn = self.controller.calibration_session.assign_from_node(node, slot=slot)
        if warn:
            self._cal_warn.setText(warn)
        self.refresh_calibration_panel()
        self.controller.tree_overlay_invalidated.emit()
        if self.view.selected_id is not None:
            self._render_detail(self.view.selected_id)

    def _suggest_anchors(self) -> None:
        self._note_input("button.clicked")
        msg = self.controller.calibration_session.apply_suggestions(self.controller.tracked_snapshot())
        if msg:
            self._cal_warn.setText(msg)
        self.refresh_calibration_panel()
        self.controller.tree_overlay_invalidated.emit()

    def _reset_calibration(self) -> None:
        self._note_input("button.clicked")
        self.controller.tree_overlay_reset_calibration_requested.emit()
        self.refresh_calibration_panel()

    def _on_appearance(self) -> None:
        s = self.controller.settings
        s.tree_overlay_opacity = self._opacity.value() / 100.0
        s.tree_overlay_marker_size = self._marker.value() / 10.0
        s.tree_overlay_line_width = self._line.value() / 10.0
        save_settings(s)
        self.controller.tree_overlay_invalidated.emit()

    def _toggle_overlay(self) -> None:
        self._note_input("button.clicked")
        enabled = not bool(self.controller.settings.tree_overlay_enabled)
        self.controller.settings.tree_overlay_enabled = enabled
        save_settings(self.controller.settings)
        self.controller.tree_overlay_show_requested.emit(enabled)

    def _calibrate_overlay(self) -> None:
        self._note_input("button.clicked")
        self.controller.tree_overlay_calibrate_requested.emit()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._embed_mode:
            apply_native_extended_style(self, WindowInteractionPolicy.INTERACTIVE_TOOL)
        self._refresh_header()
        self.refresh_calibration_panel()
        if not self._opened:
            self._opened = True
            if self.model.snapshot is None:
                self.controller.submit_tree_snapshot()
            else:
                self.view.fit_allocated()
                self._refresh_panels()
            if self.controller.tracked_tree_source is None and (
                self.controller.settings.tracked_build_path or self.controller.build_info.path
            ):
                self.controller.reload_tracked_tree()

    def on_page_shown(self) -> None:
        """Called when embedded in Dashboard TREE page."""
        self._refresh_header()
        self.refresh_calibration_panel()
        if not self._opened:
            self._opened = True
            if self.model.snapshot is None:
                self.controller.submit_tree_snapshot()
            else:
                self.view.fit_allocated()
                self._refresh_panels()
            if self.controller.tracked_tree_source is None and (
                self.controller.settings.tracked_build_path or self.controller.build_info.path
            ):
                self.controller.reload_tracked_tree()


class TreeCoachWindow(TreeWorkspace):
    """Standalone Tree Coach window (legacy entry; prefer Dashboard TREE page)."""

    def __init__(self, controller: EvaluationController, parent: QWidget | None = None) -> None:
        super().__init__(controller, parent, embed_mode=False)
        self.setObjectName("treeCoachRoot")
        flags = self.windowFlags()
        flags |= Qt.WindowType.WindowCloseButtonHint | Qt.WindowType.WindowMinimizeButtonHint
        self.setWindowFlags(flags)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        event.ignore()
        self.hide()


TreeAnalysisWindow = TreeCoachWindow
