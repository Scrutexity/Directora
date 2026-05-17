"""SQLite-backed BriefStore (v3.5).

Uses stdlib `sqlite3` (sync) so the existing sync BriefStore protocol and
FastAPI sync handlers run unchanged. Concurrency is handled with WAL
journaling + `BEGIN IMMEDIATE` per write — readers don't block writers,
and one writer succeeds while a contending writer gets a clear failure
the caller can translate to a 409.

Schema (single file, no migrations needed for v3.5):

    briefs(brief_id PK, ...)
    idempotency_records((clinic_id, provider_id, brief_id, route, idempotency_key) PK)
    ledger_events(event_id PK, brief_id, ...)

The brief store interface in `brief_store.py` is unchanged. This backend
plugs in behind `BriefStore` protocol. Migration from JSONL is in
`brief_store_migrate.py`.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from dataclasses import asdict, fields, replace
from pathlib import Path
from typing import Optional

from directora.scrutexity.brief_store import BriefRecord, BriefStatus


CREATE_BRIEFS = """
CREATE TABLE IF NOT EXISTS briefs (
    brief_id TEXT PRIMARY KEY,
    clinic_id TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    treatment TEXT NOT NULL,
    market TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending_review',
    patient_ref TEXT,
    encounter_ref TEXT,
    engine_run_id TEXT NOT NULL DEFAULT '',
    authority_brief_version TEXT NOT NULL DEFAULT '1',
    provider_brief_version TEXT NOT NULL DEFAULT '1',
    provider_brief_canonical_json TEXT,
    brief_content_hash TEXT,
    lab_summary_flags_json TEXT NOT NULL DEFAULT '{}',
    results_json TEXT NOT NULL DEFAULT '[]',
    claim_risk_items_json TEXT NOT NULL DEFAULT '[]',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    signed_at REAL,
    ledger_event_id TEXT
)
"""

CREATE_BRIEFS_INDEX = """
CREATE INDEX IF NOT EXISTS idx_briefs_clinic_status_created
ON briefs (clinic_id, status, created_at)
"""


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _row_to_record(row: sqlite3.Row) -> BriefRecord:
    return BriefRecord(
        brief_id=row["brief_id"],
        clinic_id=row["clinic_id"],
        provider_id=row["provider_id"],
        treatment=row["treatment"],
        market=row["market"],
        status=row["status"],
        patient_ref=row["patient_ref"],
        encounter_ref=row["encounter_ref"],
        engine_run_id=row["engine_run_id"] or "",
        authority_brief_version=row["authority_brief_version"] or "1",
        provider_brief_version=row["provider_brief_version"] or "1",
        provider_brief_canonical_json=row["provider_brief_canonical_json"],
        brief_content_hash=row["brief_content_hash"],
        lab_summary_flags=json.loads(row["lab_summary_flags_json"] or "{}"),
        results=json.loads(row["results_json"] or "[]"),
        claim_risk_items=json.loads(row["claim_risk_items_json"] or "[]"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        signed_at=row["signed_at"],
        ledger_event_id=row["ledger_event_id"],
    )


class SQLiteBriefStore:
    """SQLite BriefStore. Sync; safe across threads via WAL + a per-write
    BEGIN IMMEDIATE transaction. Implements the BriefStore protocol."""

    def __init__(self, path: Optional[str] = None):
        self.path = str(path or os.getenv(
            "DIRECTORA_BRIEF_DB_PATH", "./.directora/briefs.db"
        ))
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = _connect(self.path)
        self._init_schema()

    # ----- internals -------------------------------------------------

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.execute(CREATE_BRIEFS)
            self._conn.execute(CREATE_BRIEFS_INDEX)

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    # ----- BriefStore protocol --------------------------------------

    def put(self, record: BriefRecord) -> None:
        now = time.time()
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                self._conn.execute(
                    """
                    INSERT INTO briefs (
                        brief_id, clinic_id, provider_id, treatment, market,
                        status, patient_ref, encounter_ref,
                        engine_run_id, authority_brief_version, provider_brief_version,
                        provider_brief_canonical_json, brief_content_hash,
                        lab_summary_flags_json, results_json, claim_risk_items_json,
                        created_at, updated_at, signed_at, ledger_event_id
                    ) VALUES (
                        ?, ?, ?, ?, ?,
                        ?, ?, ?,
                        ?, ?, ?,
                        ?, ?,
                        ?, ?, ?,
                        ?, ?, ?, ?
                    )
                    ON CONFLICT(brief_id) DO UPDATE SET
                        clinic_id=excluded.clinic_id,
                        provider_id=excluded.provider_id,
                        treatment=excluded.treatment,
                        market=excluded.market,
                        status=excluded.status,
                        patient_ref=excluded.patient_ref,
                        encounter_ref=excluded.encounter_ref,
                        engine_run_id=excluded.engine_run_id,
                        authority_brief_version=excluded.authority_brief_version,
                        provider_brief_version=excluded.provider_brief_version,
                        provider_brief_canonical_json=excluded.provider_brief_canonical_json,
                        brief_content_hash=excluded.brief_content_hash,
                        lab_summary_flags_json=excluded.lab_summary_flags_json,
                        results_json=excluded.results_json,
                        claim_risk_items_json=excluded.claim_risk_items_json,
                        updated_at=excluded.updated_at,
                        signed_at=excluded.signed_at,
                        ledger_event_id=excluded.ledger_event_id
                    """,
                    (
                        record.brief_id,
                        record.clinic_id,
                        record.provider_id,
                        record.treatment,
                        record.market,
                        record.status,
                        record.patient_ref,
                        record.encounter_ref,
                        record.engine_run_id or "",
                        record.authority_brief_version or "1",
                        record.provider_brief_version or "1",
                        record.provider_brief_canonical_json,
                        record.brief_content_hash,
                        json.dumps(record.lab_summary_flags or {},
                                   separators=(",", ":")),
                        json.dumps(record.results or [],
                                   separators=(",", ":")),
                        json.dumps(record.claim_risk_items or [],
                                   separators=(",", ":")),
                        record.created_at,
                        now,
                        record.signed_at,
                        record.ledger_event_id,
                    ),
                )
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def get(self, brief_id: str) -> Optional[BriefRecord]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM briefs WHERE brief_id = ?", (brief_id,),
            )
            row = cur.fetchone()
            return _row_to_record(row) if row else None

    def list_pending(
        self,
        clinic_id: str,
        provider_id: Optional[str] = None,
        limit: int = 50,
        cursor: Optional[str] = None,
    ) -> tuple[list[BriefRecord], Optional[str]]:
        try:
            offset = int(cursor) if cursor else 0
        except ValueError:
            offset = 0
        with self._lock:
            if provider_id:
                cur = self._conn.execute(
                    """
                    SELECT * FROM briefs
                    WHERE clinic_id = ? AND status = ? AND provider_id = ?
                    ORDER BY created_at ASC
                    LIMIT ? OFFSET ?
                    """,
                    (clinic_id, BriefStatus.PENDING_REVIEW,
                     provider_id, limit + 1, offset),
                )
            else:
                cur = self._conn.execute(
                    """
                    SELECT * FROM briefs
                    WHERE clinic_id = ? AND status = ?
                    ORDER BY created_at ASC
                    LIMIT ? OFFSET ?
                    """,
                    (clinic_id, BriefStatus.PENDING_REVIEW,
                     limit + 1, offset),
                )
            rows = cur.fetchall()
        has_more = len(rows) > limit
        rows = rows[:limit]
        items = [_row_to_record(r) for r in rows]
        next_cursor = str(offset + limit) if has_more else None
        return items, next_cursor

    def mark_signed(
        self, brief_id: str, *, signed_at: float, ledger_event_id: str,
    ) -> BriefRecord:
        """Atomic status flip from pending_review -> signed.

        Returns the updated record. Raises KeyError if missing.
        Raises ConcurrentSignError if another transaction already
        flipped the status to signed before this one — translate to a
        409 in the API layer.
        """
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                cur = self._conn.execute(
                    "SELECT * FROM briefs WHERE brief_id = ?", (brief_id,),
                )
                row = cur.fetchone()
                if row is None:
                    self._conn.execute("ROLLBACK")
                    raise KeyError(brief_id)
                if row["status"] != BriefStatus.PENDING_REVIEW:
                    self._conn.execute("ROLLBACK")
                    raise ConcurrentSignError(
                        f"brief {brief_id!r} is already in status "
                        f"{row['status']!r}"
                    )
                self._conn.execute(
                    """
                    UPDATE briefs
                    SET status = ?, signed_at = ?, ledger_event_id = ?, updated_at = ?
                    WHERE brief_id = ?
                    """,
                    (BriefStatus.SIGNED, signed_at, ledger_event_id,
                     time.time(), brief_id),
                )
                self._conn.execute("COMMIT")
                cur = self._conn.execute(
                    "SELECT * FROM briefs WHERE brief_id = ?", (brief_id,),
                )
                return _row_to_record(cur.fetchone())
            except (KeyError, ConcurrentSignError):
                raise
            except Exception:
                self._conn.execute("ROLLBACK")
                raise


class ConcurrentSignError(RuntimeError):
    """Raised when two writers race to sign the same brief.

    The API translates this to a 409 already_signed response without
    appending a ledger event for the loser.
    """


__all__ = ["SQLiteBriefStore", "ConcurrentSignError"]
