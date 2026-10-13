"""Generation stays off the dashboard thread and never installs stale output."""
from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")


@pytest.fixture
def page_factory(monkeypatch):
    from PySide6.QtCore import QObject, Signal
    from PySide6.QtWidgets import QApplication
    from exilelens.ui.filters_page import FiltersPage

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])

    class Controller(QObject):
        build_changed = Signal()
        engine_ready = Signal()
        engine_failed = Signal(str)

        def __init__(self):
            super().__init__()
            self.engine = None
            self.baseline_generation = 1
            self.build_info = SimpleNamespace(is_ready=False, name="", path="")

    pages = []

    def create(*, background=True):
        controller = Controller()
        page = FiltersPage(controller, SimpleNamespace(), background_generation=background)
        pages.append(page)
        return app, page, controller

    yield create
    for page in pages:
        task = page._generation_task
        if task is not None and task.thread is not None:
            task.thread.join(5)
    app.processEvents()
    for page in pages:
        page.close()
        page.deleteLater()
    app.processEvents()


def settle(app, predicate):
    from PySide6.QtTest import QTest

    deadline = time.monotonic() + 5
    while not predicate() and time.monotonic() < deadline:
        QTest.qWait(10)
        app.processEvents()
    assert predicate(), "background generation did not settle"


def test_navigation_reuses_output_and_regenerates_when_baseline_changes(page_factory, monkeypatch):
    import exilelens.ui.filters_page as module

    original = module.generate_filter
    calls = []

    def generate(*args, **kwargs):
        calls.append(args)
        return original(*args, **kwargs)

    monkeypatch.setattr(module, "generate_filter", generate)
    _app, page, controller = page_factory(background=False)
    assert len(calls) == 1
    labels = tuple(page._preview_labels)
    text = page._filter_text
    for _ in range(3):
        page.on_page_shown()
    assert len(calls) == 1
    assert page._filter_text == text and tuple(page._preview_labels) == labels
    controller.baseline_generation += 1
    controller.build_changed.emit()
    assert len(calls) == 2
    page._theme.setCurrentIndex((page._theme.currentIndex() + 1) % page._theme.count())
    assert len(calls) == 3


def test_busy_generation_keeps_ui_alive_coalesces_changes_and_blocks_install(page_factory, monkeypatch, tmp_path):
    from PySide6.QtCore import QTimer
    from PySide6.QtTest import QTest
    import exilelens.ui.filters_page as module

    original = module.generate_filter
    release = threading.Event()
    calls, threads, installed = [], [], []

    def generate(*args, **kwargs):
        calls.append(args)
        threads.append(threading.get_ident())
        assert release.wait(3)
        return original(*args, **kwargs)

    monkeypatch.setattr(module, "generate_filter", generate)
    monkeypatch.setattr(module, "verify_poe2_filter_directory", lambda _path: True)

    def install(text, *_args):
        installed.append(text)
        return SimpleNamespace(success=True, verified=True, filter_name="test.filter")

    monkeypatch.setattr(module, "install_test_filter", install)
    app, page, controller = page_factory()
    beats = []
    timer = QTimer()
    timer.setInterval(5)
    timer.timeout.connect(lambda: beats.append(1))
    timer.start()
    try:
        settle(app, lambda: len(calls) == 1)
        QTest.qWait(40)
        assert len(beats) >= 3
        assert not page._filter_text and not page._install.isEnabled()
        page._profile.setCurrentIndex((page._profile.currentIndex() + 1) % page._profile.count())
        page._theme.setCurrentIndex((page._theme.currentIndex() + 2) % page._theme.count())
        controller.baseline_generation += 1
        controller.build_changed.emit()
        page._filter_dir = tmp_path
        page._generate_install()
        assert not installed and len(calls) == 1
        release.set()
        settle(app, lambda: page._generation_task is None and bool(page._filter_text))
        assert len(calls) == 2  # superseded intermediate selections were coalesced
        assert all(thread != threading.get_ident() for thread in threads)
        assert page._generated_inputs[-1] == controller.baseline_generation
        assert page._last_generated[:2] == (page._profile.currentData(), page._theme.currentData())
        page._generate_install()
        assert installed == [page._filter_text] and len(calls) == 2
    finally:
        release.set()
        timer.stop()


def test_generation_failure_is_fail_closed_and_can_retry(page_factory, monkeypatch):
    import exilelens.ui.filters_page as module

    original = module.generate_filter

    def fail(*_args, **_kwargs):
        raise ValueError("test generation failure")

    monkeypatch.setattr(module, "generate_filter", fail)
    app, page, _controller = page_factory()
    settle(app, lambda: page._generation_task is None)
    assert "test generation failure" in page._preview_status.text()
    assert not page._filter_text and not page._rules and not page._install.isEnabled()
    monkeypatch.setattr(module, "generate_filter", original)
    page.on_page_shown()
    settle(app, lambda: page._generation_task is None and bool(page._filter_text))
    assert page._validation.valid


def test_breakpoint_search_matches_original_thresholds_for_every_verified_base():
    from exilelens.filters import affix_pools, crafting_intel
    from exilelens.filters.verified_bases import load_base_properties

    # Group equivalent level sets so this reference scan remains a quick test.
    reference = {}
    for base in load_base_properties():
        ps = affix_pools.pools_for(base)
        levels = tuple(p.levels for p in ps.values())
        assert all(tuple(sorted(tiers)) == tiers for tiers in levels)
        if levels not in reference:
            expected = {}
            for name, target in (("meaningful", .60), ("high", .85), ("premium", .95)):
                for level in range(1, 101):
                    if levels and sum(sum(t <= level for t in tiers) / len(tiers)
                                      for tiers in levels) / len(levels) >= target:
                        expected[name] = level
                        break
            reference[levels] = expected
        assert crafting_intel.breakpoints(base) == reference[levels]


def test_source_identity_resolves_git_once_and_keeps_explicit_override(monkeypatch):
    from exilelens import _version

    calls = []
    _version._git_rev_parse.cache_clear()
    monkeypatch.delenv("EXILELENS_GIT_COMMIT", raising=False)
    monkeypatch.setattr(_version, "is_packaged", lambda: False)

    def run(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(stdout="a" * 40)

    monkeypatch.setattr(_version.subprocess, "run", run)
    try:
        assert _version.build_identity().git_commit == "a" * 40
        assert _version.build_identity().git_commit == "a" * 40
        assert len(calls) == 1
        monkeypatch.setenv("EXILELENS_GIT_COMMIT", "b" * 40)
        assert _version.build_identity().git_commit == "b" * 40
    finally:
        _version._git_rev_parse.cache_clear()


@pytest.mark.parametrize("measured", [False, True])
def test_cooperative_generation_preserves_the_filter_rules(measured):
    from exilelens.filters.build_needs import BuildNeedsSnapshot
    from exilelens.filters.intel_fixtures import synthetic_analysis
    from exilelens.filters.intel_generate import filter_body_sha256, generate

    needs = (BuildNeedsSnapshot.from_analysis(synthetic_analysis()) if measured
             else BuildNeedsSnapshot.unavailable("General filter", "no build connected"))
    for profile, theme in (("Recommended", "Void Gold"), ("Uber Strict", "Emberforge")):
        yields = []
        immediate = generate(needs, profile, theme)
        cooperative = generate(needs, profile, theme, cooperate=lambda: yields.append(1))
        assert yields and immediate.valid and cooperative.valid
        assert immediate.rules == cooperative.rules
        assert filter_body_sha256(immediate.text) == filter_body_sha256(cooperative.text)
