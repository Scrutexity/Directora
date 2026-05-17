"""Chaos switches — env-driven fault injection for production-safety tests.

NEVER enable any of these in production. They are wired so that the
test suite (and a developer running locally) can prove the engine's
atomicity, error mapping, and retry semantics under failures the real
production environment will eventually present.

Each switch reads its env var at call time, so tests can monkey-patch
via `monkeypatch.setenv(...)` without process restart.

Currently supported faults:

    FAULT_LEDGER_APPEND=1
        record_outcome will raise LedgerAppendFault on the next call.
        Tests assert: brief stays in pending_review, no ledger event is
        committed, API returns 500 engine_or_ledger_failure.

    FAULT_DB_LOCK=1
        SQLite operations raise OperationalError "database is locked".
        API translates to 503 with Retry-After: 1.

    FAULT_CONTRACT_MISMATCH=1
        The contract test response returns a deliberately wrong shape
        (missing required field) so contract tests prove they catch drift.
"""
from __future__ import annotations

import os
import sqlite3
from typing import Callable


def env_enabled(name: str) -> bool:
    """Return True if env var is set to a truthy value."""
    return os.getenv(name, "").lower() in ("1", "true", "yes", "on")


class LedgerAppendFault(RuntimeError):
    """Injected by FAULT_LEDGER_APPEND."""


def maybe_fault_ledger_append() -> None:
    """Raise if FAULT_LEDGER_APPEND is set. Call at the start of the
    ledger append site we want to test under failure."""
    if env_enabled("FAULT_LEDGER_APPEND"):
        raise LedgerAppendFault("FAULT_LEDGER_APPEND enabled")


def maybe_fault_db_lock() -> None:
    """Raise an OperationalError mimicking SQLite busy.

    The API translates this to 503 + Retry-After: 1.
    """
    if env_enabled("FAULT_DB_LOCK"):
        raise sqlite3.OperationalError("database is locked")


def fault_contract_mismatch_enabled() -> bool:
    """If True, response surfaces deliberately drop a required field so
    contract tests can prove they catch drift."""
    return env_enabled("FAULT_CONTRACT_MISMATCH")


__all__ = [
    "LedgerAppendFault",
    "env_enabled",
    "maybe_fault_ledger_append",
    "maybe_fault_db_lock",
    "fault_contract_mismatch_enabled",
]
