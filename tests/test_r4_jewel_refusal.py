"""R4: the three reasons a jewel candidate can have no socket must not read alike."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from exilelens.items.evaluation import no_compatible_jewel_slot_error


pytestmark = pytest.mark.itemcheck


def _parse(allocated, excluded):
    return SimpleNamespace(allocated_jewel_socket_count=allocated, excluded_connectivity_risky_socket_count=excluded)


def test_no_allocated_sockets() -> None:
    error = no_compatible_jewel_slot_error(_parse(0, 0))
    assert "no allocated jewel sockets" in str(error)
    assert error.details == {"allocated_jewel_socket_count": 0}


def test_all_sockets_withheld_is_not_reported_as_incompatible() -> None:
    error = no_compatible_jewel_slot_error(_parse(3, 3))
    assert "not compatible" not in str(error)
    assert "could not be compared safely" in str(error)
    assert error.details["excluded_connectivity_risky_socket_count"] == 3


def test_sockets_exist_but_none_accepts_the_jewel() -> None:
    for excluded in (0, 1):
        error = no_compatible_jewel_slot_error(_parse(4, excluded))
        assert "not compatible with any allocated jewel socket" in str(error)


def test_missing_counts_degrade_to_no_sockets() -> None:
    assert "no allocated jewel sockets" in str(no_compatible_jewel_slot_error(_parse(None, None)))
