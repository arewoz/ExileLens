"""R2 Package B: Patreon device credential, entitlement lease and the link/refresh/unlink state machine.

No real network, no real Patreon: the service is a scripted fake. DPAPI is exercised for real on Windows.
Everything lives in tmp_path.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import uuid
from pathlib import Path

if sys.platform != "win32":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from exilelens.app.settings import AppSettings
from exilelens.app.updates import trust
from exilelens.cloud import entitlement
from exilelens.cloud.entitlement import CAP_SEAMLESS_UPDATES, LeaseStatus, canonical_lease_bytes, signing_message, verify_lease
from exilelens.cloud.patreon import Credential, PatreonLink, PatreonState, PatreonStore, valid_authorize_url
from exilelens.cloud.transport import PostResult
from exilelens.platform.windows import dpapi

pytestmark = pytest.mark.smoke

ROOT = Path(__file__).resolve().parents[1]
TEST_PRIVATE = ROOT / "cloud" / "test" / "keys" / "entitlement-test-1.pkcs8.b64"
DEVICE_ID = "0123456789abcdef0123456789abcdef"
DEVICE_TOKEN = "dtok_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4"
NOW = 1_790_000_000
windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows DPAPI")


@pytest.fixture(autouse=True)
def _test_profile():
    with trust.use_test_trust_profile():
        yield


def _private_key():
    from cryptography.hazmat.primitives import serialization

    der = base64.b64decode(TEST_PRIVATE.read_text(encoding="ascii").strip())
    return serialization.load_der_private_key(der, password=None)


def make_lease(*, sub: str = DEVICE_ID, caps=(CAP_SEAMLESS_UPDATES,), now: int = NOW, kid: str = entitlement.ENTITLEMENT_TEST_KEY_ID, **overrides) -> dict:
    lease = {
        "schema": 1,
        "kid": kid,
        "lease_id": uuid.uuid4().hex,
        "sub": sub,
        "capabilities": sorted(caps),
        "issued_at": now,
        "refresh_after": now + 86400,
        "expires_at": now + 7 * 86400,
        "policy_version": 1,
    }
    lease.update(overrides)
    return lease


def sign(lease: dict, *, key=None, message=None) -> dict:
    key = key or _private_key()
    data = message if message is not None else signing_message(lease)
    return {"lease": lease, "signature": base64.b64encode(key.sign(data)).decode("ascii")}


# ----------------------------------------------------------------------------- lease verification


def test_valid_lease_yields_only_known_capabilities() -> None:
    result = verify_lease(sign(make_lease()), device_id=DEVICE_ID, now=NOW + 60)
    assert result.valid and result.capabilities == frozenset({CAP_SEAMLESS_UPDATES})


def test_unknown_capabilities_are_ignored() -> None:
    result = verify_lease(sign(make_lease(caps=("seamless_updates", "teleport", "install_anything"))), device_id=DEVICE_ID, now=NOW)
    assert result.valid and result.capabilities == frozenset({CAP_SEAMLESS_UPDATES})
    only_unknown = verify_lease(sign(make_lease(caps=("teleport",))), device_id=DEVICE_ID, now=NOW)
    assert only_unknown.valid and only_unknown.capabilities == frozenset()


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda e: e["lease"].__setitem__("capabilities", ["seamless_updates", "x_extra"]), LeaseStatus.BAD_SIGNATURE),
        (lambda e: e["lease"].__setitem__("expires_at", e["lease"]["expires_at"] + 86400), LeaseStatus.BAD_SIGNATURE),
        (lambda e: e["lease"].__setitem__("sub", "f" * 32), LeaseStatus.BAD_SIGNATURE),
        (lambda e: e.__setitem__("signature", base64.b64encode(b"\x00" * 64).decode()), LeaseStatus.BAD_SIGNATURE),
        (lambda e: e.__setitem__("signature", "not base64!"), LeaseStatus.BAD_SIGNATURE),
        (lambda e: e["lease"].__setitem__("kid", "exilelens-entitlement-evil"), LeaseStatus.UNKNOWN_KEY),
        (lambda e: e["lease"].__setitem__("url", "https://evil.example/update.zip"), LeaseStatus.MALFORMED),
        (lambda e: e["lease"].__setitem__("version", "9.9.9"), LeaseStatus.MALFORMED),
        (lambda e: e["lease"].pop("policy_version"), LeaseStatus.MALFORMED),
        (lambda e: e.__setitem__("manifest", {}), LeaseStatus.MALFORMED),
    ],
)
def test_tampered_leases_fail_closed(mutate, expected) -> None:
    envelope = sign(make_lease())
    mutate(envelope)
    result = verify_lease(envelope, device_id=DEVICE_ID, now=NOW + 60)
    assert result.status is expected and result.capabilities == frozenset()


def test_wrong_device_expired_and_not_yet_valid() -> None:
    envelope = sign(make_lease())
    assert verify_lease(envelope, device_id="f" * 32, now=NOW).status is LeaseStatus.WRONG_DEVICE
    expired = verify_lease(envelope, device_id=DEVICE_ID, now=NOW + 7 * 86400)
    assert expired.status is LeaseStatus.EXPIRED and expired.capabilities == frozenset()
    assert verify_lease(envelope, device_id=DEVICE_ID, now=NOW - 3600).status is LeaseStatus.NOT_YET_VALID
    assert verify_lease(envelope, device_id=DEVICE_ID, now=NOW - 60).valid  # within clock-skew tolerance


def test_signature_by_another_key_including_the_update_test_key_is_rejected() -> None:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    update_key = serialization.load_pem_private_key((ROOT / "fixtures" / "update_signing" / "test_signing_key.pem").read_bytes(), password=None)
    assert verify_lease(sign(make_lease(), key=update_key), device_id=DEVICE_ID, now=NOW).status is LeaseStatus.BAD_SIGNATURE
    assert verify_lease(sign(make_lease(), key=Ed25519PrivateKey.generate()), device_id=DEVICE_ID, now=NOW).status is LeaseStatus.BAD_SIGNATURE


def test_domain_separation_between_leases_and_update_manifests() -> None:
    lease = make_lease()
    # A signature over the bare JSON (what an update manifest signature looks like) is not a lease signature.
    assert verify_lease(sign(lease, message=canonical_lease_bytes(lease)), device_id=DEVICE_ID, now=NOW).status is LeaseStatus.BAD_SIGNATURE
    assert signing_message(lease).startswith(b"exilelens/entitlement-lease/v1\n")
    assert not signing_message(lease).startswith(b"{")  # can never be valid manifest JSON


def test_key_sets_are_disjoint_and_production_has_no_test_key() -> None:
    assert entitlement.key_sets_are_disjoint()
    assert entitlement.ENTITLEMENT_TEST_KEY_ID not in entitlement.entitlement_verify_keys(frozen=True)
    assert dict(entitlement.entitlement_verify_keys(frozen=True)) == dict(entitlement.PRODUCTION_ENTITLEMENT_KEYS)
    with trust.use_test_trust_profile(False):
        assert verify_lease(sign(make_lease()), device_id=DEVICE_ID, now=NOW).status is LeaseStatus.UNKNOWN_KEY


def test_committed_worker_vector_verifies_in_python() -> None:
    vector = json.loads((ROOT / "cloud" / "contract" / "lease_vector.json").read_text(encoding="utf-8"))
    keys = {vector["kid"]: base64.b64decode(vector["public_key_b64"])}
    assert keys[vector["kid"]] == entitlement.TEST_ENTITLEMENT_KEYS[vector["kid"]]
    envelope = {"lease": vector["lease"], "signature": vector["signature"]}
    result = verify_lease(envelope, device_id=vector["device_id"], now=vector["lease"]["issued_at"] + 60, keys=keys)
    assert result.valid and result.capabilities == frozenset({CAP_SEAMLESS_UPDATES})
    envelope["lease"]["capabilities"] = []
    assert verify_lease(envelope, device_id=vector["device_id"], now=vector["lease"]["issued_at"] + 60, keys=keys).status is LeaseStatus.BAD_SIGNATURE


def test_canonical_json_matches_the_documented_form() -> None:
    assert canonical_lease_bytes({"b": [2, 1], "a": "é"}) == '{"a":"é","b":[2,1]}'.encode("utf-8")


# ----------------------------------------------------------------------------- credential storage


@windows_only
def test_dpapi_roundtrip_and_protected_file_does_not_contain_the_token(tmp_path: Path) -> None:
    store = PatreonStore(tmp_path / "patreon")
    store.save_credential(Credential(DEVICE_ID, DEVICE_TOKEN))
    raw = store.credential_path.read_bytes()
    assert DEVICE_TOKEN.encode() not in raw and DEVICE_ID.encode() not in raw
    assert store.load_credential() == Credential(DEVICE_ID, DEVICE_TOKEN)
    assert dpapi.unprotect(dpapi.protect(b"x" * 100_000)) == b"x" * 100_000  # no 2.5 KB credential-manager limit
    with pytest.raises(dpapi.DpapiUnavailable):
        dpapi.unprotect(dpapi.protect(b"secret"), entropy=b"different entropy")


@windows_only
def test_corrupt_or_foreign_credential_means_safe_reconnect_not_a_crash(tmp_path: Path) -> None:
    store = PatreonStore(tmp_path / "patreon")
    store.save_credential(Credential(DEVICE_ID, DEVICE_TOKEN))
    store.credential_path.write_bytes(b"\x00garbage\x01" * 10)
    assert store.load_credential() is None
    link = PatreonLink(store, base_url=lambda: "https://api.example.test", http_factory=lambda _u: ScriptedHttp(), clock=lambda: NOW)
    view = link.view()
    assert view.state is PatreonState.RECONNECT_REQUIRED and not view.capabilities
    assert link.seamless_updates_allowed() is False


def fake_store(root: Path) -> PatreonStore:
    """Reversible stand-in for DPAPI (so state-machine tests also run off Windows)."""
    return PatreonStore(root, protect=lambda b: b"FAKE" + base64.b64encode(b), unprotect=lambda b: base64.b64decode(b[4:]))


# ----------------------------------------------------------------------------- scripted service


class ScriptedHttp:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict | None, dict | None]] = []
        self.responses: dict[tuple[str, str], list[PostResult]] = {}

    def script(self, method: str, path_prefix: str, *results: PostResult) -> None:
        self.responses.setdefault((method, path_prefix), []).extend(results)

    def _answer(self, method: str, path: str, body, headers) -> PostResult:
        self.calls.append((method, path, body, headers))
        for (m, prefix), queue in self.responses.items():
            if m == method and path.startswith(prefix) and queue:
                return queue.pop(0) if len(queue) > 1 else queue[0]
        return PostResult(status=0, code="network")

    def post_json(self, path, body, headers=None):
        return self._answer("POST", path, body, headers)

    def get_json(self, path, headers=None):
        return self._answer("GET", path, None, headers)

    def delete_json(self, path, headers=None):
        return self._answer("DELETE", path, None, headers)


AUTHORIZE = "https://www.patreon.com/oauth2/authorize?response_type=code&client_id=cid&scope=identity&state=s"
START_OK = PostResult(status=201, body={"ok": True, "session_id": "ab" * 16, "poll_token": "P" * 43, "authorize_url": AUTHORIZE, "expires_at": NOW + 600, "poll_interval_s": 2})


def linked_result(*, caps=(CAP_SEAMLESS_UPDATES,), status="linked", token=DEVICE_TOKEN, device=DEVICE_ID, lease=None) -> PostResult:
    return PostResult(
        status=200,
        body={"ok": True, "status": status, "device_token": token, "device_id": device, "lease": lease or sign(make_lease(caps=caps, sub=device))},
    )


class Clock:
    def __init__(self, now: float = NOW) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def make_link(tmp_path: Path, http: ScriptedHttp, *, clock=None, opened=None, url="https://api.example.test") -> PatreonLink:
    clock = clock or Clock()
    opened = opened if opened is not None else []
    return PatreonLink(
        fake_store(tmp_path / "patreon"),
        base_url=lambda: url,
        http_factory=lambda _u: http,
        clock=clock,
        sleep=lambda s: setattr(clock, "now", clock.now + s),
        open_url=lambda u: opened.append(u) or True,
    )


def run_link(link: PatreonLink) -> None:
    assert link.start_link()
    link._link_thread.join(10)
    assert not link._linking


# ----------------------------------------------------------------------------- linking


def test_link_flow_stores_credential_and_lease_and_never_exposes_provider_data(tmp_path: Path) -> None:
    http = ScriptedHttp()
    http.script("POST", "/v1/patreon/link/start", START_OK)
    http.script("GET", "/v1/patreon/link/status", PostResult(200, body={"ok": True, "status": "pending"}), linked_result())
    opened: list[str] = []
    link = make_link(tmp_path, http, opened=opened)
    run_link(link)
    assert opened == [AUTHORIZE]
    view = link.view()
    assert view.state is PatreonState.ACTIVE and view.seamless_updates and link.seamless_updates_allowed()
    status_call = next(c for c in http.calls if c[0] == "GET")
    assert status_call[3] == {"Authorization": "Bearer " + "P" * 43}
    stored = " ".join(p.read_text(encoding="utf-8", errors="ignore") for p in (tmp_path / "patreon").glob("*") if p.name != "device.bin")
    assert DEVICE_TOKEN not in stored and "P" * 43 not in stored
    assert DEVICE_TOKEN.encode() not in (tmp_path / "patreon" / "device.bin").read_bytes()


def test_not_entitled_link_is_connected_but_not_eligible(tmp_path: Path) -> None:
    http = ScriptedHttp()
    http.script("POST", "/v1/patreon/link/start", START_OK)
    http.script("GET", "/v1/patreon/link/status", linked_result(caps=(), status="not_entitled"))
    link = make_link(tmp_path, http)
    run_link(link)
    view = link.view()
    assert view.state is PatreonState.NOT_ELIGIBLE and not link.seamless_updates_allowed()


@pytest.mark.parametrize("terminal", ["denied", "expired", "failed", "cancelled"])
def test_failed_link_attempts_leave_nothing_behind(tmp_path: Path, terminal: str) -> None:
    http = ScriptedHttp()
    http.script("POST", "/v1/patreon/link/start", START_OK)
    http.script("GET", "/v1/patreon/link/status", PostResult(200, body={"ok": True, "status": terminal}))
    link = make_link(tmp_path, http)
    run_link(link)
    view = link.view()
    assert view.state is PatreonState.NOT_CONNECTED and view.detail == terminal
    assert not (tmp_path / "patreon").exists()


def test_unknown_session_or_wrong_token_404_ends_linking(tmp_path: Path) -> None:
    http = ScriptedHttp()
    http.script("POST", "/v1/patreon/link/start", START_OK)
    http.script("GET", "/v1/patreon/link/status", PostResult(404, code="not_found", body={"ok": False, "code": "not_found"}))
    link = make_link(tmp_path, http)
    run_link(link)
    assert link.view().state is PatreonState.NOT_CONNECTED and not (tmp_path / "patreon").exists()


def test_link_times_out_and_can_be_cancelled(tmp_path: Path) -> None:
    http = ScriptedHttp()
    http.script("POST", "/v1/patreon/link/start", START_OK)
    http.script("GET", "/v1/patreon/link/status", PostResult(200, body={"ok": True, "status": "pending"}))
    link = make_link(tmp_path, http)
    run_link(link)
    assert link.view().detail == "timeout"
    http.script("POST", "/v1/patreon/link/start", START_OK)
    cancelled = make_link(tmp_path, http)
    cancelled._open_url = lambda u: cancelled.cancel_link() or True  # the user cancels right after the browser opens
    run_link(cancelled)
    assert cancelled.view().detail == "cancelled"


def test_service_unavailable_at_start_shows_service_unavailable(tmp_path: Path) -> None:
    http = ScriptedHttp()
    http.script("POST", "/v1/patreon/link/start", PostResult(status=503, code="link_disabled", retry_after=3600))
    link = make_link(tmp_path, http)
    run_link(link)
    assert link.view().state is PatreonState.SERVICE_UNAVAILABLE


@pytest.mark.parametrize(
    "url",
    [
        "http://www.patreon.com/oauth2/authorize?x=1",
        "https://evil.example/oauth2/authorize?x=1",
        "https://www.patreon.com.evil.example/oauth2/authorize?x=1",
        "https://user:pw@www.patreon.com/oauth2/authorize?x=1",
        "https://www.patreon.com/other?x=1",
        "javascript:alert(1)",
        "file:///C:/Windows/System32/calc.exe",
        "",
    ],
)
def test_only_the_patreon_authorize_url_is_ever_opened(tmp_path: Path, url: str) -> None:
    assert not valid_authorize_url(url)
    http = ScriptedHttp()
    http.script("POST", "/v1/patreon/link/start", PostResult(201, body={**START_OK.body, "authorize_url": url}))
    opened: list[str] = []
    link = make_link(tmp_path, http, opened=opened)
    run_link(link)
    assert opened == [] and link.view().state is PatreonState.SERVICE_UNAVAILABLE
    assert valid_authorize_url(AUTHORIZE)


def test_credential_with_invalid_lease_is_rejected_not_stored(tmp_path: Path) -> None:
    http = ScriptedHttp()
    http.script("POST", "/v1/patreon/link/start", START_OK)
    forged = sign(make_lease(caps=(CAP_SEAMLESS_UPDATES,)))
    forged["signature"] = base64.b64encode(b"\x01" * 64).decode()
    http.script("GET", "/v1/patreon/link/status", linked_result(lease=forged))
    link = make_link(tmp_path, http)
    run_link(link)
    assert link.view().detail == "invalid_lease" and not (tmp_path / "patreon").exists()
    wrong_device = sign(make_lease(sub="e" * 32))
    http2 = ScriptedHttp()
    http2.script("POST", "/v1/patreon/link/start", START_OK)
    http2.script("GET", "/v1/patreon/link/status", linked_result(lease=wrong_device))
    link2 = make_link(tmp_path, http2)
    run_link(link2)
    assert not link2.seamless_updates_allowed()


def test_link_is_unavailable_without_a_configured_endpoint(tmp_path: Path) -> None:
    link = make_link(tmp_path, ScriptedHttp(), url=None)
    assert not link.available() and not link.start_link()
    assert link.view().state is PatreonState.NOT_CONNECTED


# ----------------------------------------------------------------------------- refresh / grace / expiry


def linked(tmp_path: Path, http: ScriptedHttp | None = None, clock=None) -> tuple[PatreonLink, ScriptedHttp, Clock]:
    http = http or ScriptedHttp()
    clock = clock or Clock()
    http.script("POST", "/v1/patreon/link/start", START_OK)
    http.script("GET", "/v1/patreon/link/status", linked_result())
    link = make_link(tmp_path, http, clock=clock)
    run_link(link)
    assert link.view().state is PatreonState.ACTIVE
    return link, http, clock


def refresh_ok(clock: Clock, caps=(CAP_SEAMLESS_UPDATES,)) -> PostResult:
    return PostResult(200, body={"ok": True, "lease": sign(make_lease(caps=caps, now=int(clock.now))), "next_refresh_after_s": 86400, "server_time": int(clock.now)})


def test_refresh_happens_only_when_due_and_updates_the_lease(tmp_path: Path) -> None:
    link, http, clock = linked(tmp_path)
    before = len(http.calls)
    link.tick(clock.now + 3600)
    assert len(http.calls) == before  # not due yet
    clock.now += 86400 + 60
    http.script("POST", "/v1/patreon/entitlement/refresh", refresh_ok(clock))
    link.tick(clock.now)
    refresh_call = http.calls[-1]
    assert refresh_call[1] == "/v1/patreon/entitlement/refresh" and refresh_call[3] == {"Authorization": f"Bearer {DEVICE_TOKEN}"}
    assert refresh_call[2]["schema"] == 1 and set(refresh_call[2]) <= {"schema", "client_version"}
    assert link.view().state is PatreonState.ACTIVE and link.capabilities()


@pytest.mark.parametrize("outage", [PostResult(0, code="network"), PostResult(503, code="patreon_unavailable", retry_after=600), PostResult(429, code="rate_limited", retry_after=60), PostResult(500)])
def test_outage_during_a_valid_lease_is_offline_grace_not_loss_of_benefit(tmp_path: Path, outage: PostResult) -> None:
    link, http, clock = linked(tmp_path)
    clock.now += 86400 + 60
    http.script("POST", "/v1/patreon/entitlement/refresh", outage)
    link.tick(clock.now)
    view = link.view()
    assert view.state is PatreonState.OFFLINE_GRACE and view.seamless_updates and link.seamless_updates_allowed()
    clock.now += 3 * 86400
    assert link.view().state is PatreonState.OFFLINE_GRACE and link.seamless_updates_allowed()


def test_backend_outage_does_not_hammer_the_service(tmp_path: Path) -> None:
    link, http, clock = linked(tmp_path)
    clock.now += 86400 + 60
    http.script("POST", "/v1/patreon/entitlement/refresh", PostResult(503, code="patreon_unavailable", retry_after=3600))
    link.tick(clock.now)
    calls = len([c for c in http.calls if c[1].endswith("/refresh")])
    for step in range(1, 100):
        link.tick(clock.now + step * 30)
    assert len([c for c in http.calls if c[1].endswith("/refresh")]) == calls == 1


def test_expired_lease_falls_back_to_free_behaviour_and_manual_updates_stay_possible(tmp_path: Path) -> None:
    link, http, clock = linked(tmp_path)
    clock.now += 8 * 86400
    http.script("POST", "/v1/patreon/entitlement/refresh", PostResult(503, code="patreon_unavailable"))
    view = link.view()
    assert view.state is PatreonState.EXPIRED and not view.capabilities
    assert link.seamless_updates_allowed() is False


def test_revoked_membership_arrives_as_a_lease_without_capabilities(tmp_path: Path) -> None:
    link, http, clock = linked(tmp_path)
    clock.now += 86400 + 60
    http.script("POST", "/v1/patreon/entitlement/refresh", refresh_ok(clock, caps=()))
    link.tick(clock.now)
    assert link.view().state is PatreonState.NOT_ELIGIBLE and not link.seamless_updates_allowed()


@pytest.mark.parametrize("code", ["device_unknown", "reauthorize_required"])
def test_unknown_device_or_reauthorisation_requires_reconnect_and_drops_the_lease(tmp_path: Path, code: str) -> None:
    link, http, clock = linked(tmp_path)
    clock.now += 86400 + 60
    http.script("POST", "/v1/patreon/entitlement/refresh", PostResult(401, code=code, body={"ok": False, "code": code}))
    link.tick(clock.now)
    assert link.view().state is PatreonState.RECONNECT_REQUIRED and not link.seamless_updates_allowed()
    assert not (tmp_path / "patreon" / "lease.json").exists()
    before = len(http.calls)
    link.tick(clock.now + 100000)
    assert len(http.calls) == before  # no retry loop against a device the service rejected


def test_tampered_lease_file_on_disk_means_free_behaviour(tmp_path: Path) -> None:
    link, http, clock = linked(tmp_path)
    path = tmp_path / "patreon" / "lease.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["lease"]["capabilities"] = ["seamless_updates", "more"]
    path.write_text(json.dumps(data), encoding="utf-8")
    assert not link.seamless_updates_allowed()
    assert link.view().state is PatreonState.EXPIRED
    path.write_text("{ not json", encoding="utf-8")
    assert not link.seamless_updates_allowed()


def test_a_refreshed_but_forged_lease_is_not_accepted(tmp_path: Path) -> None:
    link, http, clock = linked(tmp_path)
    clock.now += 86400 + 60
    forged = refresh_ok(clock)
    forged.body["lease"]["signature"] = base64.b64encode(b"\x07" * 64).decode()
    http.script("POST", "/v1/patreon/entitlement/refresh", forged)
    link.tick(clock.now)
    assert link.view().state is PatreonState.OFFLINE_GRACE  # old lease still valid; the forgery changed nothing
    stored = json.loads((tmp_path / "patreon" / "lease.json").read_text(encoding="utf-8"))
    assert stored["lease"]["issued_at"] == NOW


# ----------------------------------------------------------------------------- unlink / reconnect


def test_unlink_removes_local_state_immediately_even_if_the_service_is_down(tmp_path: Path) -> None:
    link, http, clock = linked(tmp_path)
    http.script("POST", "/v1/patreon/unlink", PostResult(0, code="network"))
    link.unlink()
    assert not (tmp_path / "patreon").exists()
    assert link.view().state is PatreonState.NOT_CONNECTED and not link.seamless_updates_allowed()
    import time

    deadline = time.time() + 3
    while time.time() < deadline and not any(c[1] == "/v1/patreon/unlink" for c in http.calls):
        time.sleep(0.02)
    unlink_call = next(c for c in http.calls if c[1] == "/v1/patreon/unlink")
    assert unlink_call[3] == {"Authorization": f"Bearer {DEVICE_TOKEN}"}


def test_reconnect_after_unlink_creates_a_fresh_state(tmp_path: Path) -> None:
    link, http, clock = linked(tmp_path)
    link.unlink()
    http.responses.clear()
    http.script("POST", "/v1/patreon/link/start", START_OK)
    http.script("GET", "/v1/patreon/link/status", linked_result(token="N" * 40, device="9" * 32, lease=sign(make_lease(sub="9" * 32))))
    run_link(link)
    assert link.view().state is PatreonState.ACTIVE
    assert link.store.load_credential() == Credential("9" * 32, "N" * 40)


# ----------------------------------------------------------------------------- settings / UI copy


def test_supporter_update_toggles_default_on_and_parse_strictly() -> None:
    settings = AppSettings()
    assert settings.updates_auto_download is True and settings.updates_install_on_exit is True
    off = AppSettings.from_dict({"updates_auto_download": False, "updates_install_on_exit": False})
    assert off.updates_auto_download is False and off.updates_install_on_exit is False
    assert AppSettings.from_dict({"updates_auto_download": "no"}).updates_auto_download is True


def test_status_copy_for_every_state_says_manual_updates_work_and_shows_no_profile_data() -> None:
    from exilelens.cloud.patreon import PatreonView
    from exilelens.ui.patreon_panel import describe_view

    for state in PatreonState:
        text = describe_view(PatreonView(state, expires_at=NOW + 86400), available=True)
        assert text
        if state not in (PatreonState.ACTIVE, PatreonState.NOT_CONNECTED, PatreonState.LINKING):
            assert "Manual updates still work" in text
        assert "@" not in text and "email" not in text.lower()
    assert "available in this build" in describe_view(PatreonView(PatreonState.NOT_CONNECTED), available=False)


def test_patreon_panel_states_and_actions(tmp_path: Path) -> None:
    from PySide6.QtWidgets import QApplication

    from exilelens.cloud.service import CloudServices
    from exilelens.ui.patreon_panel import PatreonPanel

    app = QApplication.instance() or QApplication([])
    http = ScriptedHttp()
    cloud = CloudServices(AppSettings(), base_url=lambda: "https://api.example.test", http_factory=lambda _u: http, root=tmp_path / "cloud")
    cloud.patreon = make_link(tmp_path / "x", http)  # fake DPAPI, scripted service
    settings = AppSettings()
    panel = PatreonPanel(settings, cloud)
    # Not linked: the entry state offers Support on Patreon and Link Patreon as distinct actions. The two
    # supporter switches stay visible (Settings shows them under Updates) but are disabled and Off.
    assert panel.link_button.isEnabled() and panel.support_button.isVisibleTo(panel) and not panel.disconnect_button.isVisibleTo(panel)
    assert not panel.auto_download.isEnabled() and not panel.install_on_exit.isEnabled()
    assert not panel.auto_download.isChecked() and not panel.install_on_exit.isChecked()
    http.script("POST", "/v1/patreon/link/start", START_OK)
    http.script("GET", "/v1/patreon/link/status", linked_result())
    cloud.patreon._open_url = lambda u: True
    cloud.patreon.start_link()
    cloud.patreon._link_thread.join(10)
    panel.render()
    assert panel.disconnect_button.isVisibleTo(panel) and not panel.support_button.isVisibleTo(panel)
    assert panel.auto_download.isEnabled() and panel.install_on_exit.isEnabled()
    assert panel.auto_download.isChecked() and panel.install_on_exit.isChecked()
    panel.install_on_exit.setChecked(False)
    assert settings.updates_install_on_exit is False
    panel.disconnect_button.click()
    assert not panel.disconnect_button.isVisibleTo(panel) and not panel.auto_download.isEnabled()
    assert app is not None


def test_cloud_services_tick_drives_refresh_and_does_not_need_consent(tmp_path: Path) -> None:
    from exilelens.cloud.service import CloudServices

    http = ScriptedHttp()
    clock = Clock()
    cloud = CloudServices(AppSettings(), clock=clock, base_url=lambda: "https://api.example.test", http_factory=lambda _u: http, root=tmp_path / "cloud")
    cloud.patreon = make_link(tmp_path / "y", http, clock=clock)
    http.script("POST", "/v1/patreon/link/start", START_OK)
    http.script("GET", "/v1/patreon/link/status", linked_result())
    run_link(cloud.patreon)
    clock.now += 86400 + 60
    http.script("POST", "/v1/patreon/entitlement/refresh", refresh_ok(clock))
    cloud.tick(clock.now)
    assert any(c[1].endswith("/refresh") for c in http.calls)
    assert not cloud.usage.active and not cloud.errors.active  # telemetry stays off
