"""Settings persistence and cache-identity coverage for "Ignore socketed
modifiers in Item Check" (items/item_check_settings.py, items/evaluation_identity.py).
"""

from __future__ import annotations

import pytest

from poe2value.items.evaluation_identity import EvaluationContextIdentity, identity_from_state
from poe2value.items.item_check_settings import ItemCheckProSettings
from poe2value.items.result_cache import evaluation_cache_key

pytestmark = pytest.mark.itemcheck


def test_ignore_socketed_mods_defaults_off() -> None:
    settings = ItemCheckProSettings.from_dict(None)
    assert settings.ignore_socketed_mods is False


def test_ignore_socketed_mods_round_trips_through_to_dict_and_from_dict() -> None:
    settings = ItemCheckProSettings.from_dict({"ignore_socketed_mods": True})
    assert settings.ignore_socketed_mods is True

    persisted = settings.to_dict()
    assert persisted["ignore_socketed_mods"] is True

    reloaded = ItemCheckProSettings.from_dict(persisted)
    assert reloaded.ignore_socketed_mods is True

    # A settings dict that predates this field still loads with the documented
    # default OFF -- migration/back-compat for saved settings files.
    legacy = ItemCheckProSettings.from_dict({"decision_intelligence": True})
    assert legacy.ignore_socketed_mods is False


def _identity_kwargs(**overrides) -> dict:
    base = dict(
        source_identity="src",
        source_revision="rev",
        build_generation=1,
        baseline_fingerprint="bfp",
        equipment_fingerprint="efp",
        tree_fingerprint="tfp",
        fingerprint_components={},
        loadout="",
        item_set="",
        calculation_context="MAP",
        worker_generation=0,
    )
    base.update(overrides)
    return base


def test_context_identity_token_differs_by_ignore_socketed_mods() -> None:
    off = identity_from_state(**_identity_kwargs(ignore_socketed_mods=False))
    on = identity_from_state(**_identity_kwargs(ignore_socketed_mods=True))
    assert isinstance(off, EvaluationContextIdentity)
    assert off.ignore_socketed_mods is False
    assert on.ignore_socketed_mods is True
    assert off.token != on.token


def test_evaluation_cache_key_cannot_mix_on_and_off_results() -> None:
    """A cache entry built with the setting ON must never satisfy a lookup for OFF.

    ``evaluation_cache_key``'s v3 form is ``candidate_fingerprint | context_identity``;
    the identity token above already differs by the setting, so the composed cache
    key must differ too even when every other input (candidate text, build state) is
    identical.
    """
    off_identity = identity_from_state(**_identity_kwargs(ignore_socketed_mods=False))
    on_identity = identity_from_state(**_identity_kwargs(ignore_socketed_mods=True))

    common = dict(
        content_hash="same-candidate-hash",
        fingerprint="bfp",
        loadout="",
        item_set="",
        context="MAP",
        generation=1,
        candidate_fingerprint="same-candidate-hash",
    )
    key_off = evaluation_cache_key(context_identity=off_identity.token, **common)
    key_on = evaluation_cache_key(context_identity=on_identity.token, **common)
    assert key_off != key_on
