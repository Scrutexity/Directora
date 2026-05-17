"""SQLite BriefStore tests — interface parity, migration, concurrency."""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

import pytest

from directora.scrutexity.brief_store import (
    BriefRecord,
    BriefStatus,
    FilesystemBriefStore,
)
from directora.scrutexity.brief_store_sqlite import (
    ConcurrentSignError,
    SQLiteBriefStore,
)
from directora.scrutexity.brief_store_migrate import migrate_jsonl_to_sqlite


def _make(brief_id="BRF_X", clinic_id="CLN", provider_id="PRV"):
    return BriefRecord(
        brief_id=brief_id,
        clinic_id=clinic_id,
        provider_id=provider_id,
        treatment="Morpheus8",
        market="Upper East Side, NYC",
        status=BriefStatus.PENDING_REVIEW,
        engine_run_id="run-test",
        authority_brief_version="1",
        provider_brief_version="1",
        provider_brief_canonical_json='{"asset_type":"provider_brief_snippet"}',
        brief_content_hash="abc",
        lab_summary_flags={"critical_count": 0},
        results=[{"name": "vitamin_D", "value": "low"}],
        claim_risk_items=["Avoid guaranteed results"],
    )


def test_put_and_get_roundtrip(tmp_path):
    s = SQLiteBriefStore(path=str(tmp_path / "store.db"))
    s.put(_make())
    got = s.get("BRF_X")
    assert got is not None
    assert got.treatment == "Morpheus8"
    assert got.brief_content_hash == "abc"
    assert got.lab_summary_flags == {"critical_count": 0}


def test_get_missing_returns_none(tmp_path):
    s = SQLiteBriefStore(path=str(tmp_path / "store.db"))
    assert s.get("NOPE") is None


def test_list_pending_filters_by_clinic(tmp_path):
    s = SQLiteBriefStore(path=str(tmp_path / "store.db"))
    s.put(_make("A", clinic_id="CLN_A"))
    s.put(_make("B", clinic_id="CLN_B"))
    items_a, _ = s.list_pending(clinic_id="CLN_A")
    items_b, _ = s.list_pending(clinic_id="CLN_B")
    assert [r.brief_id for r in items_a] == ["A"]
    assert [r.brief_id for r in items_b] == ["B"]


def test_list_pending_pagination(tmp_path):
    s = SQLiteBriefStore(path=str(tmp_path / "store.db"))
    for i in range(5):
        rec = _make(f"BRF_{i:02d}")
        rec.created_at = float(i)  # deterministic order
        s.put(rec)
    page1, cursor = s.list_pending(clinic_id="CLN", limit=2)
    assert [r.brief_id for r in page1] == ["BRF_00", "BRF_01"]
    assert cursor == "2"
    page2, cursor = s.list_pending(clinic_id="CLN", limit=2, cursor=cursor)
    assert [r.brief_id for r in page2] == ["BRF_02", "BRF_03"]
    assert cursor == "4"
    page3, cursor = s.list_pending(clinic_id="CLN", limit=2, cursor=cursor)
    assert [r.brief_id for r in page3] == ["BRF_04"]
    assert cursor is None


def test_mark_signed_changes_status(tmp_path):
    s = SQLiteBriefStore(path=str(tmp_path / "store.db"))
    s.put(_make())
    rec = s.mark_signed("BRF_X", signed_at=123.0, ledger_event_id="evt_a")
    assert rec.status == BriefStatus.SIGNED
    assert rec.signed_at == 123.0
    assert rec.ledger_event_id == "evt_a"


def test_mark_signed_missing_raises_keyerror(tmp_path):
    s = SQLiteBriefStore(path=str(tmp_path / "store.db"))
    with pytest.raises(KeyError):
        s.mark_signed("MISSING", signed_at=0.0, ledger_event_id="x")


def test_mark_signed_twice_raises_concurrent_sign_error(tmp_path):
    s = SQLiteBriefStore(path=str(tmp_path / "store.db"))
    s.put(_make())
    s.mark_signed("BRF_X", signed_at=1.0, ledger_event_id="evt_first")
    with pytest.raises(ConcurrentSignError):
        s.mark_signed("BRF_X", signed_at=2.0, ledger_event_id="evt_second")


def test_persists_across_instances(tmp_path):
    p = str(tmp_path / "store.db")
    s1 = SQLiteBriefStore(path=p)
    s1.put(_make("BRF_PERSIST"))
    s1.close()
    s2 = SQLiteBriefStore(path=p)
    rec = s2.get("BRF_PERSIST")
    assert rec is not None
    assert rec.treatment == "Morpheus8"


def test_migration_from_jsonl_to_sqlite_preserves_records(tmp_path):
    src = tmp_path / "jsonl"
    src.mkdir()
    js = FilesystemBriefStore(root=src)
    js.put(_make("BRF_M1"))
    js.put(_make("BRF_M2"))
    js.mark_signed("BRF_M2", signed_at=time.time(), ledger_event_id="evt_pre")

    dst = tmp_path / "briefs.db"
    legacy = tmp_path / "briefs_migrated"
    report = migrate_jsonl_to_sqlite(
        src, dst,
        rename_legacy_to=legacy,
        log_path=tmp_path / "migration.log",
    )
    assert report["ok"] is True
    assert report["jsonl_records_seen"] == 2
    assert report["sqlite_records_after"] == 2

    s = SQLiteBriefStore(path=str(dst))
    assert s.get("BRF_M1") is not None
    signed = s.get("BRF_M2")
    assert signed is not None
    assert signed.status == BriefStatus.SIGNED
    assert signed.ledger_event_id == "evt_pre"

    # Legacy directory renamed.
    assert not src.exists()
    assert legacy.exists()


def test_concurrent_mark_signed_one_wins_one_loses(tmp_path):
    """The whole point of WAL + IMMEDIATE: one writer wins, one raises."""
    s = SQLiteBriefStore(path=str(tmp_path / "store.db"))
    s.put(_make())
    results: list[Exception | None] = [None, None]
    barrier = threading.Barrier(2)

    def attempt(idx: int, event_id: str):
        try:
            barrier.wait(timeout=2)
            s.mark_signed("BRF_X", signed_at=1.0 + idx, ledger_event_id=event_id)
            results[idx] = None
        except Exception as exc:
            results[idx] = exc

    t1 = threading.Thread(target=attempt, args=(0, "evt_a"))
    t2 = threading.Thread(target=attempt, args=(1, "evt_b"))
    t1.start(); t2.start()
    t1.join(timeout=5); t2.join(timeout=5)

    losers = [r for r in results if r is not None]
    winners = [r for r in results if r is None]
    assert len(winners) == 1
    assert len(losers) == 1
    assert isinstance(losers[0], ConcurrentSignError)
