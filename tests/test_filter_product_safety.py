"""Critical installation failures and production integration contracts."""
from pathlib import Path

import pytest

from exilelens.app.settings import AppSettings
from exilelens.filters.build_needs import BuildNeedsSnapshot
from exilelens.filters.intel_generate import generate
from exilelens.filters import install


@pytest.fixture(scope='module')
def content():
    return generate(BuildNeedsSnapshot.unavailable('General', 'no build')).text


def test_batch_filename_cannot_escape_filter_directory(tmp_path):
    with pytest.raises(ValueError):
        install.get_batch_filter_path(tmp_path, 'Recommended', '../../other')


@pytest.mark.parametrize('batch', [False, True])
def test_unrelated_same_named_file_is_never_overwritten(tmp_path, content, batch):
    destination = install.get_batch_filter_path(tmp_path, 'Recommended', 'Void Gold') if batch else tmp_path / install.TEST_FILTER_FILENAME
    destination.write_bytes(b'# My custom filter\nShow\n')
    call = install.install_batch_filter if batch else install.install_test_filter
    result = call(content, tmp_path, 'Recommended', 'Void Gold')
    assert not result.success
    assert destination.read_bytes() == b'# My custom filter\nShow\n'


def test_replace_failure_keeps_the_previous_working_bytes(tmp_path, content, monkeypatch):
    destination = tmp_path / install.TEST_FILTER_FILENAME
    assert install.install_test_filter(content, tmp_path, 'Recommended', 'Void Gold').success
    old = destination.read_bytes()
    monkeypatch.setattr(install.os, 'replace', lambda *args: (_ for _ in ()).throw(PermissionError('locked by game')))
    result = install.install_test_filter(content + '\n# next version\n', tmp_path, 'Recommended', 'Void Gold')
    assert not result.success and destination.read_bytes() == old
    assert not list(tmp_path.glob('.exilelens_*.tmp'))


@pytest.mark.parametrize('failure', ['read', 'mismatch'])
def test_post_replace_verification_failure_restores_the_previous_filter(tmp_path, content, monkeypatch, failure):
    destination = tmp_path / install.TEST_FILTER_FILENAME
    assert install.install_test_filter(content, tmp_path, 'Recommended', 'Void Gold').success
    old = destination.read_bytes()
    real_read = Path.read_bytes
    reads = 0

    def read(path):
        nonlocal reads
        if path == destination:
            reads += 1
            if reads == 3:
                if failure == 'read':
                    raise PermissionError('verification blocked')
                return b'corrupt'
        return real_read(path)

    monkeypatch.setattr(Path, 'read_bytes', read)
    result = install.install_test_filter(content + '\n# next version\n', tmp_path, 'Recommended', 'Void Gold')
    assert not result.success and 'restored' in result.error_message
    assert real_read(destination) == old
    assert not list(tmp_path.glob('.exilelens_*.tmp'))


def test_directory_detection_does_not_overwrite_a_user_probe_file(tmp_path):
    from exilelens.platform.windows.poe2_paths import verify_poe2_filter_directory
    sentinel = tmp_path / '.exilelens_write_test'
    sentinel.write_text('user data', encoding='utf-8')
    assert not verify_poe2_filter_directory(tmp_path)
    assert sentinel.read_text(encoding='utf-8') == 'user data'
    (tmp_path / 'poe2_production_Config.ini').write_text('[DISPLAY]', encoding='utf-8')
    assert verify_poe2_filter_directory(tmp_path)


def test_filter_settings_migrate_without_changing_privacy_or_market_consent():
    settings = AppSettings.from_dict({'filter_profile': 'Endgame', 'filter_theme': 'missing',
                                     'market_prices_enabled': False, 'usage_stats_enabled': False})
    assert settings.filter_profile == 'Very Strict' and settings.filter_profile_notice
    assert settings.filter_theme == 'Void Gold' and not settings.market_prices_enabled


def test_normal_analyze_build_still_defaults_to_the_standard_probe_catalog():
    from exilelens.app.controller import AnalysisRequest
    assert not AnalysisRequest(1).defence_probes


def test_package_includes_every_offline_filter_snapshot():
    spec = Path('packaging/exilelens-gui.spec').read_text(encoding='utf-8')
    assert 'filter_data' in spec and '+ filter_data' in spec
    assert '["data/*.json", "data/loot_ground.png"]' in Path('pyproject.toml').read_text(encoding='utf-8')


def test_rule_edits_cannot_leave_a_cached_preview_or_coverage_decision_stale():
    from exilelens.filters.preview import PreviewItem, preview_decision
    from exilelens.filters.rules import GeneratedRule
    from exilelens.filters.style_coverage import first_match
    item = PreviewItem('Chaos Orb', 'Currency', 'Stackable Currency')
    rule = GeneratedRule('TEST', 'mutable', ['Show', 'Class "Stackable Currency"'], 1)
    assert not preview_decision([rule], item).hidden
    rule.lines[0] = 'Hide'
    assert preview_decision([rule], item).hidden
    assert first_match([rule], item)[1] == 'Hide'
