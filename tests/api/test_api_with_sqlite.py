"""End-to-end API tests against the SQLite BriefStore backend.

Replaces the in-memory store with a real SQLite file under tmp_path,
runs the full pending → sign → audit flow, and verifies idempotency
and concurrent-sign behaviour through the HTTP layer.
"""
from __future__ import annotations

import threading

import pytest
from fastapi.testclient import TestClient

from directora.api.auth import encode_stub_token
from directora.api.server import create_app
from directora.api import idempotency as idem_module
from directora.scrutexity import brief_store as bs_module
from directora.scrutexity.brief_store_sqlite import SQLiteBriefStore
from directora.telemetry import outcome as ledger_module
from tests.api.conftest import _seeded_brief, CLINIC_ID, PROVIDER_ID


@pytest.fixture
def sqlite_app(tmp_path, monkeypatch):
    monkeypatch.setenv("DIRECTORA_CLINIC_SIGNING_SECRET_DEFAULT", "test-secret")
    # Reset stores: SQLite for briefs, in-memory for idempotency + ledger.
    store = SQLiteBriefStore(path=str(tmp_path / "briefs.db"))
    bs_module.reset_store_for_tests(store)
    idem_module.reset_store_for_tests(idem_module.InMemoryIdempotencyStore())
    ledger_module.reset_sink_for_tests(ledger_module.MemorySink())
    app = create_app()
    with TestClient(app) as c:
        yield c, store
    bs_module.reset_store_for_tests(None)
    idem_module.reset_store_for_tests(None)
    ledger_module.reset_sink_for_tests(None)


def _hdrs(token, idem=None):
    h = {"Authorization": f"Bearer {token}", "X-Clinic-ID": CLINIC_ID}
    if idem:
        h["Idempotency-Key"] = idem
        h["Content-Type"] = "application/json"
    return h


def _sign_body():
    return {
        "brief_id": "BRF_TEST_01",
        "provider_id": PROVIDER_ID,
        "signature": {
            "method": "typed", "value": "Dr Jane Doe",
            "signed_at": "2026-05-16T17:01:33Z",
        },
        "client": {"app": "labbrief", "version": "2.5.0", "session_id": "s"},
    }


def test_full_signoff_flow_against_sqlite(sqlite_app):
    client, store = sqlite_app
    store.put(_seeded_brief())
    token = encode_stub_token(PROVIDER_ID, CLINIC_ID)

    # 1. pending
    pending = client.get("/api/brief/pending", headers=_hdrs(token))
    assert pending.status_code == 200
    items = pending.json()["items"]
    assert any(it["brief_id"] == "BRF_TEST_01" for it in items)

    # 2. provider snippet
    prov = client.get(
        "/api/brief/provider",
        params={"brief_id": "BRF_TEST_01"},
        headers=_hdrs(token),
    )
    assert prov.status_code == 200
    assert prov.json()["snippet"]["treatment"] == "Morpheus8"

    # 3. sign
    sign = client.post(
        "/api/brief/sign",
        headers=_hdrs(token, idem="idem-sqlite"),
        json=_sign_body(),
    )
    assert sign.status_code == 200
    ledger_event_id = sign.json()["ledger_event_id"]

    # 4. audit
    audit = client.get(
        "/api/labs/audit",
        params={"brief_id": "BRF_TEST_01"},
        headers=_hdrs(token),
    )
    assert audit.status_code == 200
    kinds = [e["kind"] for e in audit.json()["events"]]
    assert "provider_brief_signed" in kinds

    # SQLite state reflects signed status.
    rec = store.get("BRF_TEST_01")
    assert rec.status == "signed"
    assert rec.ledger_event_id == ledger_event_id


def test_concurrent_sign_resolves_to_one_winner(sqlite_app, monkeypatch):
    client, store = sqlite_app
    store.put(_seeded_brief())
    token = encode_stub_token(PROVIDER_ID, CLINIC_ID)

    # Two concurrent sign attempts with different idempotency keys.
    # We expect: exactly one 200 and one 409.
    barrier = threading.Barrier(2)
    results: list[tuple[int, dict]] = [(0, {}), (0, {})]

    def attempt(idx: int, idem: str):
        barrier.wait(timeout=2)
        r = client.post(
            "/api/brief/sign",
            headers=_hdrs(token, idem=idem),
            json=_sign_body(),
        )
        results[idx] = (r.status_code, r.json())

    t1 = threading.Thread(target=attempt, args=(0, "idem-race-a"))
    t2 = threading.Thread(target=attempt, args=(1, "idem-race-b"))
    t1.start(); t2.start(); t1.join(timeout=5); t2.join(timeout=5)

    statuses = sorted(s for s, _ in results)
    assert statuses == [200, 409], f"got {results}"
    losing = [r for s, r in results if s == 409][0]
    assert losing["error"] == "already_signed"
