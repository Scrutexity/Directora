"""Brief store — persistence for Authority + Provider briefs and their
canonical JSON form.

The signing path retrieves the exact canonical JSON that triggered
`provider_brief_ready` and hashes it. Re-rendering would risk drift, so
the store is the single source of truth between generation and signing.

v3.4 ships two backends behind a single interface:
    InMemoryBriefStore         dict-based, default for tests
    FilesystemBriefStore       JSONL append-log under .directora/briefs/

Production swap to SQLite / object storage requires only implementing
the `BriefStore` protocol — no other module changes.
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Iterable, Optional, Protocol

from directora.scrutexity.canonical_json import canonical_bytes, canonical_dumps


class BriefStatus:
    DRAFTED = "drafted"
    REVIEWED = "reviewed"
    PENDING_REVIEW = "pending_review"
    SIGNED = "signed"


@dataclass
class BriefRecord:
    """Everything the API needs about a brief in one place.

    `provider_brief_canonical_json` is the canonical JSON for the
    Provider Brief snippet — the exact string that backs
    `brief_content_hash`. Keep it as a string (already canonical) so
    re-serialisation can never drift.
    """
    brief_id: str
    clinic_id: str
    provider_id: str
    treatment: str
    market: str
    status: str = BriefStatus.PENDING_REVIEW
    patient_ref: Optional[str] = None
    encounter_ref: Optional[str] = None
    engine_run_id: str = ""
    authority_brief_version: str = "1"
    provider_brief_version: str = "1"
    provider_brief_canonical_json: Optional[str] = None
    brief_content_hash: Optional[str] = None
    lab_summary_flags: dict = field(default_factory=dict)
    results: list = field(default_factory=list)
    claim_risk_items: list = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    signed_at: Optional[float] = None
    ledger_event_id: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


class BriefStore(Protocol):
    def put(self, record: BriefRecord) -> None: ...
    def get(self, brief_id: str) -> Optional[BriefRecord]: ...
    def list_pending(
        self, clinic_id: str, provider_id: Optional[str] = None,
        limit: int = 50, cursor: Optional[str] = None,
    ) -> tuple[list[BriefRecord], Optional[str]]: ...
    def mark_signed(
        self, brief_id: str, *, signed_at: float, ledger_event_id: str,
    ) -> BriefRecord: ...


class InMemoryBriefStore:
    def __init__(self) -> None:
        self._records: dict[str, BriefRecord] = {}
        self._lock = threading.Lock()

    def put(self, record: BriefRecord) -> None:
        with self._lock:
            record.updated_at = time.time()
            self._records[record.brief_id] = record

    def get(self, brief_id: str) -> Optional[BriefRecord]:
        with self._lock:
            return self._records.get(brief_id)

    def list_pending(
        self, clinic_id: str, provider_id: Optional[str] = None,
        limit: int = 50, cursor: Optional[str] = None,
    ) -> tuple[list[BriefRecord], Optional[str]]:
        with self._lock:
            items = [
                r for r in self._records.values()
                if r.clinic_id == clinic_id
                and r.status == BriefStatus.PENDING_REVIEW
                and (provider_id is None or r.provider_id == provider_id)
            ]
        items.sort(key=lambda r: r.created_at)
        start = 0
        if cursor:
            try:
                start = int(cursor)
            except ValueError:
                start = 0
        page = items[start:start + limit]
        next_cursor = (
            str(start + limit) if start + limit < len(items) else None
        )
        return page, next_cursor

    def mark_signed(
        self, brief_id: str, *, signed_at: float, ledger_event_id: str,
    ) -> BriefRecord:
        with self._lock:
            record = self._records.get(brief_id)
            if record is None:
                raise KeyError(brief_id)
            updated = replace(
                record,
                status=BriefStatus.SIGNED,
                signed_at=signed_at,
                ledger_event_id=ledger_event_id,
                updated_at=time.time(),
            )
            self._records[brief_id] = updated
            return updated


class FilesystemBriefStore(InMemoryBriefStore):
    """In-memory cache + append-only JSONL on disk.

    Each `put` and `mark_signed` appends a line to `.directora/briefs/store.jsonl`.
    On construction the file is replayed to rebuild memory state. Crash-safe
    enough for the v3.4 contract; SQLite swap can land later behind the
    same interface without API changes.
    """

    def __init__(self, root: Path | str | None = None) -> None:
        super().__init__()
        self.root = Path(root or os.getenv(
            "DIRECTORA_BRIEF_STORE_PATH", "./.directora/briefs"
        ))
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "store.jsonl"
        self._replay()

    def _append(self, kind: str, payload: dict) -> None:
        line = canonical_dumps({"kind": kind, "payload": payload})
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    def _replay(self) -> None:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                kind = entry.get("kind")
                payload = entry.get("payload", {})
                if kind == "put":
                    rec = BriefRecord(**payload)
                    super().put(rec)
                elif kind == "mark_signed":
                    try:
                        super().mark_signed(
                            payload["brief_id"],
                            signed_at=payload["signed_at"],
                            ledger_event_id=payload["ledger_event_id"],
                        )
                    except KeyError:
                        pass

    def put(self, record: BriefRecord) -> None:
        super().put(record)
        self._append("put", record.to_dict())

    def mark_signed(
        self, brief_id: str, *, signed_at: float, ledger_event_id: str,
    ) -> BriefRecord:
        updated = super().mark_signed(
            brief_id, signed_at=signed_at, ledger_event_id=ledger_event_id
        )
        self._append(
            "mark_signed",
            {
                "brief_id": brief_id,
                "signed_at": signed_at,
                "ledger_event_id": ledger_event_id,
            },
        )
        return updated


# Module-level default store. Tests override via reset_store_for_tests().
_default_store: BriefStore | None = None
_default_store_lock = threading.Lock()


def _build_default_store() -> BriefStore:
    # BRIEF_STORE_BACKEND is the v3.5 environment variable name; the
    # legacy DIRECTORA_BRIEF_STORE_BACKEND name is also honoured for
    # backwards compatibility with v3.4 deployments.
    backend = (
        os.getenv("BRIEF_STORE_BACKEND")
        or os.getenv("DIRECTORA_BRIEF_STORE_BACKEND")
        or "sqlite"
    ).lower()
    if backend == "memory":
        return InMemoryBriefStore()
    if backend in ("jsonl", "filesystem"):
        return FilesystemBriefStore()
    if backend == "sqlite":
        # Imported lazily so the sqlite backend is optional at import time.
        from directora.scrutexity.brief_store_sqlite import SQLiteBriefStore
        return SQLiteBriefStore()
    raise ValueError(
        f"Unknown BRIEF_STORE_BACKEND={backend!r}; "
        "expected one of: sqlite, jsonl, memory"
    )


def get_brief_store() -> BriefStore:
    global _default_store
    if _default_store is None:
        with _default_store_lock:
            if _default_store is None:
                _default_store = _build_default_store()
    return _default_store


def reset_store_for_tests(store: BriefStore | None = None) -> None:
    """Test hook only — never call from production code."""
    global _default_store
    with _default_store_lock:
        _default_store = store


__all__ = [
    "BriefRecord",
    "BriefStatus",
    "BriefStore",
    "InMemoryBriefStore",
    "FilesystemBriefStore",
    "get_brief_store",
    "reset_store_for_tests",
]
