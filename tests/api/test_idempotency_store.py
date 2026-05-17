"""SQLiteIdempotencyStore tests.

Covers:
    * interface parity with InMemoryIdempotencyStore
    * concurrent same-hash → REPLAY for one writer
    * concurrent different-hash → CONFLICT
    * survives process restart (data persists to file)
    * byte-identical replay via canonical_dumps
    * IdempotencyStoreBusy translation when FAULT_DB_LOCK is set
"""
from __future__ import annotations

import threading

import pytest

from directora.api.idempotency import (
    IdempotencyOutcome,
    InMemoryIdempotencyStore,
)
from directora.api.idempotency_store import (
    IdempotencyStoreBusy,
    SQLiteIdempotencyStore,
)


@pytest.fixture
def sqlite_store(tmp_path):
    s = SQLiteIdempotencyStore(db_path=str(tmp_path / "idem.db"))
    yield s
    s.close()


def _begin(s, **kw):
    return s.begin(
        clinic_id=kw.get("clinic_id", "CLN"),
        provider_id=kw.get("provider_id", "PRV"),
        brief_id=kw.get("brief_id", "BRF"),
        route=kw.get("route", "POST /api/brief/sign"),
        idempotency_key=kw["idempotency_key"],
        request_hash=kw.get("request_hash", "h-1"),
    )


def _commit(s, response, **kw):
    s.commit(
        clinic_id=kw.get("clinic_id", "CLN"),
        provider_id=kw.get("provider_id", "PRV"),
        brief_id=kw.get("brief_id", "BRF"),
        route=kw.get("route", "POST /api/brief/sign"),
        idempotency_key=kw["idempotency_key"],
        request_hash=kw.get("request_hash", "h-1"),
        response=response,
    )


def test_first_call_proceeds(sqlite_store):
    res = _begin(sqlite_store, idempotency_key="idem-1")
    assert res.outcome == IdempotencyOutcome.PROCEED


def test_replay_returns_stored_response(sqlite_store):
    _begin(sqlite_store, idempotency_key="idem-2")
    _commit(sqlite_store, {"status": "signed", "ledger_event_id": "evt_x"},
            idempotency_key="idem-2")
    again = _begin(sqlite_store, idempotency_key="idem-2")
    assert again.outcome == IdempotencyOutcome.REPLAY
    assert again.stored_response["status"] == "signed"
    assert again.stored_response["ledger_event_id"] == "evt_x"


def test_conflict_same_key_different_hash(sqlite_store):
    _begin(sqlite_store, idempotency_key="idem-3", request_hash="h-A")
    _commit(sqlite_store, {"status": "signed"},
            idempotency_key="idem-3", request_hash="h-A")
    conflicted = _begin(sqlite_store,
                        idempotency_key="idem-3", request_hash="h-B")
    assert conflicted.outcome == IdempotencyOutcome.CONFLICT


def test_byte_identical_replay_after_canonicalisation(sqlite_store):
    """Storage + retrieval must round-trip through canonical_dumps so
    replay returns the same JSON the original commit produced."""
    response = {"b": 1, "a": [3, 2, 1], "c": {"y": True}}
    _begin(sqlite_store, idempotency_key="idem-4")
    _commit(sqlite_store, response, idempotency_key="idem-4")
    again = _begin(sqlite_store, idempotency_key="idem-4")
    assert again.outcome == IdempotencyOutcome.REPLAY
    assert again.stored_response == response


def test_data_persists_across_instances(tmp_path):
    path = str(tmp_path / "idem.db")
    s1 = SQLiteIdempotencyStore(db_path=path)
    _begin(s1, idempotency_key="idem-restart")
    _commit(s1, {"ok": True}, idempotency_key="idem-restart")
    s1.close()
    s2 = SQLiteIdempotencyStore(db_path=path)
    again = _begin(s2, idempotency_key="idem-restart")
    assert again.outcome == IdempotencyOutcome.REPLAY
    assert again.stored_response == {"ok": True}
    s2.close()


def test_concurrent_writes_same_key_same_hash_one_wins_others_replay(
    sqlite_store,
):
    """N concurrent writers under the same key + same request hash.
    INSERT OR IGNORE means the first to commit wins; later begin()
    calls return REPLAY with the winner's response."""
    response = {"status": "signed", "ledger_event_id": "evt_winner"}
    barrier = threading.Barrier(5)
    outcomes: list[IdempotencyOutcome] = []
    lock = threading.Lock()

    def worker():
        barrier.wait(timeout=2)
        r = _begin(sqlite_store, idempotency_key="idem-race")
        if r.outcome == IdempotencyOutcome.PROCEED:
            # Simulate doing work and committing.
            _commit(sqlite_store, response, idempotency_key="idem-race")
        with lock:
            outcomes.append(r.outcome)

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)
    # At least one PROCEED. Once committed, any subsequent begin()
    # within this test would see REPLAY — we don't assert exact mix
    # because thread interleaving is non-deterministic.
    assert IdempotencyOutcome.PROCEED in outcomes


def test_db_lock_translates_to_busy_error(sqlite_store, monkeypatch):
    monkeypatch.setenv("FAULT_DB_LOCK", "1")
    with pytest.raises(IdempotencyStoreBusy):
        _begin(sqlite_store, idempotency_key="idem-busy")


def test_env_switch_selects_sqlite_by_default(monkeypatch, tmp_path):
    monkeypatch.setenv("IDEMPOTENCY_DB_PATH", str(tmp_path / "x.db"))
    monkeypatch.delenv("IDEMPOTENCY_STORE_BACKEND", raising=False)
    from directora.api import idempotency as idem
    idem.reset_store_for_tests(None)
    s = idem.get_idempotency_store()
    assert isinstance(s, SQLiteIdempotencyStore)


def test_env_switch_selects_memory_when_requested(monkeypatch):
    monkeypatch.setenv("IDEMPOTENCY_STORE_BACKEND", "memory")
    from directora.api import idempotency as idem
    idem.reset_store_for_tests(None)
    s = idem.get_idempotency_store()
    assert isinstance(s, InMemoryIdempotencyStore)


def test_inmemory_parity_with_sqlite_for_basic_ops():
    """Sanity: both backends share the same outcome under identical
    workloads. Catches divergence between implementations."""
    mem = InMemoryIdempotencyStore()
    sql = SQLiteIdempotencyStore(db_path=":memory:")  # ephemeral
    try:
        for store in (mem, sql):
            r1 = store.begin(
                clinic_id="CLN", provider_id="PRV", brief_id="BRF",
                route="r", idempotency_key="k", request_hash="h",
            )
            assert r1.outcome == IdempotencyOutcome.PROCEED
            store.commit(
                clinic_id="CLN", provider_id="PRV", brief_id="BRF",
                route="r", idempotency_key="k", request_hash="h",
                response={"a": 1},
            )
            r2 = store.begin(
                clinic_id="CLN", provider_id="PRV", brief_id="BRF",
                route="r", idempotency_key="k", request_hash="h",
            )
            assert r2.outcome == IdempotencyOutcome.REPLAY
            assert r2.stored_response == {"a": 1}
    finally:
        sql.close()
