"""BriefStore tests — in-memory and filesystem JSONL backends."""
from __future__ import annotations

import os
import time

import pytest

from directora.scrutexity.brief_store import (
    BriefRecord,
    BriefStatus,
    FilesystemBriefStore,
    InMemoryBriefStore,
)


def _make(brief_id="BRF_X"):
    return BriefRecord(
        brief_id=brief_id,
        clinic_id="CLN",
        provider_id="PRV",
        treatment="Morpheus8",
        market="Upper East Side, NYC",
        status=BriefStatus.PENDING_REVIEW,
        engine_run_id="run-test",
        provider_brief_canonical_json='{"asset_type":"provider_brief_snippet"}',
        brief_content_hash="abc",
    )


def test_inmemory_put_and_get_roundtrip():
    s = InMemoryBriefStore()
    rec = _make()
    s.put(rec)
    got = s.get("BRF_X")
    assert got is not None
    assert got.treatment == "Morpheus8"
    assert got.brief_content_hash == "abc"


def test_inmemory_list_pending_filters_by_clinic_and_status():
    s = InMemoryBriefStore()
    s.put(_make("A"))
    other = _make("B")
    other.clinic_id = "OTHER"
    s.put(other)
    signed = _make("C")
    signed.status = BriefStatus.SIGNED
    s.put(signed)
    items, _ = s.list_pending(clinic_id="CLN")
    ids = sorted(r.brief_id for r in items)
    assert ids == ["A"]


def test_inmemory_list_pending_pagination():
    s = InMemoryBriefStore()
    for i in range(5):
        s.put(_make(f"BRF_{i:02d}"))
    page1, cursor = s.list_pending(clinic_id="CLN", limit=2)
    assert len(page1) == 2 and cursor == "2"
    page2, cursor = s.list_pending(clinic_id="CLN", limit=2, cursor=cursor)
    assert len(page2) == 2 and cursor == "4"
    page3, cursor = s.list_pending(clinic_id="CLN", limit=2, cursor=cursor)
    assert len(page3) == 1 and cursor is None


def test_inmemory_mark_signed_changes_status_and_metadata():
    s = InMemoryBriefStore()
    s.put(_make())
    updated = s.mark_signed("BRF_X", signed_at=123.45, ledger_event_id="evt_abc")
    assert updated.status == BriefStatus.SIGNED
    assert updated.signed_at == 123.45
    assert updated.ledger_event_id == "evt_abc"


def test_filesystem_store_persists_across_instances(tmp_path):
    s1 = FilesystemBriefStore(root=tmp_path)
    s1.put(_make("BRF_PERSIST"))
    # New instance reads the same path — must replay state.
    s2 = FilesystemBriefStore(root=tmp_path)
    rec = s2.get("BRF_PERSIST")
    assert rec is not None
    assert rec.treatment == "Morpheus8"


def test_filesystem_store_replays_mark_signed(tmp_path):
    s1 = FilesystemBriefStore(root=tmp_path)
    s1.put(_make("BRF_REPLAY"))
    s1.mark_signed("BRF_REPLAY", signed_at=999.0, ledger_event_id="evt_xyz")
    s2 = FilesystemBriefStore(root=tmp_path)
    rec = s2.get("BRF_REPLAY")
    assert rec is not None
    assert rec.status == BriefStatus.SIGNED
    assert rec.ledger_event_id == "evt_xyz"
