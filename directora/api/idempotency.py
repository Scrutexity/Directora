"""Idempotency record store + replay/conflict semantics.

In-memory dict for v3.4. Production swap (Redis, Postgres) implements
the `IdempotencyStore` protocol. Replay returns the stored response
verbatim; same key with a different request_hash yields a 409 conflict.

Composite key: (clinic_id, provider_id, brief_id, route, idempotency_key).
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, Protocol


class IdempotencyOutcome(str, Enum):
    PROCEED = "proceed"
    REPLAY = "replay"
    CONFLICT = "conflict"


@dataclass
class IdempotencyRecord:
    request_hash: str
    response: dict
    ts: float = field(default_factory=time.time)


@dataclass
class IdempotencyResult:
    outcome: IdempotencyOutcome
    stored_response: Optional[dict] = None


class IdempotencyStore(Protocol):
    def begin(
        self,
        *,
        clinic_id: str,
        provider_id: str,
        brief_id: str,
        route: str,
        idempotency_key: str,
        request_hash: str,
    ) -> IdempotencyResult: ...

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
    ) -> None: ...


class InMemoryIdempotencyStore:
    def __init__(self) -> None:
        self._records: dict[tuple, IdempotencyRecord] = {}
        self._lock = threading.Lock()

    def _key(self, **kw: Any) -> tuple:
        return (
            kw["clinic_id"],
            kw["provider_id"],
            kw["brief_id"],
            kw["route"],
            kw["idempotency_key"],
        )

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
        key = self._key(
            clinic_id=clinic_id,
            provider_id=provider_id,
            brief_id=brief_id,
            route=route,
            idempotency_key=idempotency_key,
        )
        with self._lock:
            existing = self._records.get(key)
            if existing is None:
                # First attempt — caller proceeds; commit later.
                return IdempotencyResult(outcome=IdempotencyOutcome.PROCEED)
            if existing.request_hash == request_hash:
                return IdempotencyResult(
                    outcome=IdempotencyOutcome.REPLAY,
                    stored_response=existing.response,
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
        key = self._key(
            clinic_id=clinic_id,
            provider_id=provider_id,
            brief_id=brief_id,
            route=route,
            idempotency_key=idempotency_key,
        )
        with self._lock:
            self._records[key] = IdempotencyRecord(
                request_hash=request_hash,
                response=response,
            )


_default_store: IdempotencyStore | None = None
_default_store_lock = threading.Lock()


def _build_default_store() -> "IdempotencyStore":
    """v3.6: production default is SQLite. memory remains for dev /
    single-worker setups where the env var is set explicitly."""
    import os
    backend = os.getenv("IDEMPOTENCY_STORE_BACKEND", "sqlite").lower()
    if backend == "memory":
        return InMemoryIdempotencyStore()
    if backend == "sqlite":
        # Lazy import so the SQLite backend is optional at import time.
        from directora.api.idempotency_store import SQLiteIdempotencyStore
        return SQLiteIdempotencyStore()
    raise ValueError(
        f"Unknown IDEMPOTENCY_STORE_BACKEND={backend!r}; "
        "expected one of: sqlite, memory"
    )


def get_idempotency_store() -> IdempotencyStore:
    global _default_store
    if _default_store is None:
        with _default_store_lock:
            if _default_store is None:
                _default_store = _build_default_store()
    return _default_store


def reset_store_for_tests(store: IdempotencyStore | None = None) -> None:
    global _default_store
    with _default_store_lock:
        _default_store = store


__all__ = [
    "IdempotencyOutcome",
    "IdempotencyRecord",
    "IdempotencyResult",
    "IdempotencyStore",
    "InMemoryIdempotencyStore",
    "get_idempotency_store",
    "reset_store_for_tests",
]
