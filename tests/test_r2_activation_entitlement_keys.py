"""Production activation: the provisioned entitlement public key is separate from every other key."""

from __future__ import annotations

from exilelens.app.updates import trust
from exilelens.cloud import entitlement


def test_production_entitlement_key_is_provisioned_and_frozen_builds_trust_only_it() -> None:
    assert set(entitlement.PRODUCTION_ENTITLEMENT_KEYS) == {entitlement.ENTITLEMENT_PROD_KEY_ID}
    assert dict(entitlement.entitlement_verify_keys(frozen=True)) == dict(entitlement.PRODUCTION_ENTITLEMENT_KEYS)
    assert len(entitlement.PRODUCTION_ENTITLEMENT_KEYS[entitlement.ENTITLEMENT_PROD_KEY_ID]) == 32


def test_entitlement_and_update_key_sets_never_overlap_by_id_or_bytes() -> None:
    assert entitlement.key_sets_are_disjoint()
    update_bytes = set(trust.PRODUCTION_VERIFY_KEYS.values()) | set(trust.TEST_VERIFY_KEYS.values())
    assert not (set(entitlement.PRODUCTION_ENTITLEMENT_KEYS.values()) & update_bytes)
    assert not (set(entitlement.PRODUCTION_ENTITLEMENT_KEYS.values()) & set(entitlement.TEST_ENTITLEMENT_KEYS.values()))


def test_update_manifest_trust_does_not_include_entitlement_key() -> None:
    assert entitlement.ENTITLEMENT_PROD_KEY_ID not in trust.trusted_update_keys(frozen=True)
