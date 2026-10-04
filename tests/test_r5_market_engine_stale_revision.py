"""R5: the stale-build-revision early return of `run_market_search` builds its result (it raised NameError: MarketQueryPlan was never imported)."""

from __future__ import annotations

import pytest

from exilelens.app.build_revision import read_build_revision
from exilelens.market.engine import run_market_search
from exilelens.market.models import MarketQueryPlan, MarketSearchRequest

pytestmark = pytest.mark.itemcheck


def test_a_build_changed_since_the_request_returns_a_stale_result_not_an_exception(tmp_path) -> None:
    build = tmp_path / "build.xml"
    build.write_text("<PathOfBuilding2/>", encoding="utf-8")
    revision = read_build_revision(build)
    assert revision is not None
    request = MarketSearchRequest(
        slot="RING_1",
        build_revision={"path": revision.path, "mtime_ns": revision.mtime_ns - 1, "size": revision.size},
    )

    result = run_market_search(object(), request, build_path=str(build))

    assert result.stale is True
    assert result.provider_status == "STALE_BUILD_REVISION"
    assert isinstance(result.query_plan, MarketQueryPlan) and result.query_plan.slot == "RING_1"
    assert result.progress.phase == "stale"
