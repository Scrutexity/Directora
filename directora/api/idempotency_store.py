"""SQLite-backed IdempotencyStore for multi-worker deployments.

Implements the `IdempotencyStore` protocol from `directora.api.idempotency`.

Concurrency model:
    * WAL journaling so readers never block writers.
    * INSERT OR IGNORE for the put step — first writer wins atomically.
    * IMMEDIATE transactions on the begin step so concurrent attempts
      with the SAME key see consistent state.
    * The store records the FULL response body. Replay returns the
      stored response byte-identically (via `canonical_dumps`).

Backpressure:
    * If SQLite raises OperationalError ("database is locked"), the
      store re-raises a typed `IdempotencyStoreBusy` so the API layer
      can translate to 503 + Retry-After: 1 instead of 500.

Public class:
    SQLiteIdempotencyStore
        same begin/commit interface as InMemoryIdempotencyStore
        stores response JSON bytes alongside the request hash
        survives process restart
"""
from __future__ import annotations

import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Optional

from directora.api.idempotency import (
    IdempotencyOutcome,
    IdempotencyRecord,
    IdempotencyResult,
)
from directora.scrutexity.canonical_json import canonical_dumps


CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS idempotency_records (
    clinic_id TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    brief_id TEXT NOT NULL,
    route TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    response_json TEXT,
    created_at REAL NOT NULL,
    PRIMARY KEY (clinic_id, provider_id, brief_id, route, idempotency_key)
)
"""


class IdempotencyStoreBusy(RuntimeError):
    """Translated by the API layer into 503 + Retry-After."""


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    # Short busy timeout so concurrent writers detect contention quickly
    # and the API can return 503 with Retry-After rather than blocking.
    conn.execute("PRAGMA busy_timeout=100")
    return conn


class SQLiteIdempotencyStore:
    """SQLite-backed idempotency store safe for multi-worker setups."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = str(db_path or os.getenv(
            "IDEMPOTENCY_DB_PATH", "./.directora/idempotency.db"
        ))
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = _connect(self.db_path)
        with self._lock:
            self._conn.execute(CREATE_TABLE)

    # ----- helpers ---------------------------------------------------

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    def clear(self) -> None:
        """Test hook."""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                self._conn.execute("DELETE FROM idempotency_records")
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    # ----- IdempotencyStore protocol --------------------------------

    def begin(
        self,
        *,
        clinic_id: str,
        provider_id: str,
        brief_id: str,
        route: str,
        idempotency_key: str,
        request_hash: str,
    ) -> IdempotencyResult:
        # Chaos switch — translate to 503 in the caller.
        from directora.api.chaos import maybe_fault_db_lock
        try:
            maybe_fault_db_lock()
        except sqlite3.OperationalError as exc:
            raise IdempotencyStoreBusy(str(exc)) from exc

        try:
            with self._lock:
                cur = self._conn.execute(
                    """
                    SELECT request_hash, response_json
                    FROM idempotency_records
                    WHERE clinic_id = ? AND provider_id = ? AND brief_id = ?
                      AND route = ? AND idempotency_key = ?
                    """,
                    (clinic_id, provider_id, brief_id, route, idempotency_key),
                )
                row = cur.fetchone()
        except sqlite3.OperationalError as exc:
            raise IdempotencyStoreBusy(str(exc)) from exc

        if row is None:
            return IdempotencyResult(outcome=IdempotencyOutcome.PROCEED)
        if row["request_hash"] == request_hash:
            try:
                stored = (
                    sqlite3_json_loads(row["response_json"])
                    if row["response_json"] else {}
                )
            except Exception:
                stored = {}
            return IdempotencyResult(
                outcome=IdempotencyOutcome.REPLAY, stored_response=stored,
            )
        return IdempotencyResult(outcome=IdempotencyOutcome.CONFLICT)

    def commit(
        self,
        *,
        clinic_id: str,
        provider_id: str,
        brief_id: str,
        route: str,
        idempotency_key: str,
        request_hash: str,
        response: dict,
    ) -> None:
        # Store the canonical JSON form of the response so replay
        # returns byte-identical bytes (stable key order).
        response_json = canonical_dumps(response or {})
        try:
            with self._lock:
                # INSERT OR IGNORE: if a concurrent worker beat us to it,
                # the existing row stays. The API layer's begin() call on
                # the loser's next attempt will detect REPLAY or CONFLICT.
                self._conn.execute(
                    """
                    INSERT OR IGNORE INTO idempotency_records (
                        clinic_id, provider_id, brief_id, route, idempotency_key,
                        request_hash, response_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        clinic_id, provider_id, brief_id, route, idempotency_key,
                        request_hash, response_json, time.time(),
                    ),
                )
        except sqlite3.OperationalError as exc:
            raise IdempotencyStoreBusy(str(exc)) from exc


def sqlite3_json_loads(raw: Any) -> Any:
    """JSON loader that tolerates non-string sentinels in stored rows."""
    if raw is None:
        return None
    if isinstance(raw, (dict, list)):
        return raw
    import json
    return json.loads(raw)


__all__ = ["SQLiteIdempotencyStore", "IdempotencyStoreBusy"]
