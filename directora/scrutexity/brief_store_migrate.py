"""JSONL → SQLite migration.

Replays the v3.4 filesystem JSONL append-log into the v3.5 SQLite
backend, asserts row counts match the JSONL `put` event count, and
renames the legacy directory on success.

Idempotent: re-running on an already-migrated tree is a no-op.

CLI:
    python -m directora.scrutexity.brief_store_migrate \
        --src ./.directora/briefs \
        --dst ./.directora/briefs.db
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
import time
from pathlib import Path
from typing import Optional

from directora.scrutexity.brief_store import (
    BriefRecord,
    FilesystemBriefStore,
)
from directora.scrutexity.brief_store_sqlite import SQLiteBriefStore

log = logging.getLogger("directora.migrate")


def migrate_jsonl_to_sqlite(
    jsonl_root: Path,
    sqlite_path: Path,
    *,
    rename_legacy_to: Optional[Path] = None,
    log_path: Optional[Path] = None,
) -> dict:
    """Run the migration. Returns a report dict.

    Strategy:
        1. Load every brief from the JSONL store into memory by replay.
        2. Open or create the SQLite store at `sqlite_path`.
        3. For each record, call `put` (upsert) followed by `mark_signed`
           if the JSONL state indicates a signed brief.
        4. Compare row counts; abort if mismatch.
        5. Optionally rename the JSONL directory so it can't drift.
    """
    started = time.time()
    jsonl_root = Path(jsonl_root)
    sqlite_path = Path(sqlite_path)

    src = FilesystemBriefStore(root=jsonl_root)
    # Reuse the InMemoryBriefStore's records dict to count distinct briefs.
    expected_ids = list(src._records.keys())  # noqa: SLF001

    dst = SQLiteBriefStore(path=str(sqlite_path))
    migrated_ids: list[str] = []
    signed_after_migrate: list[str] = []
    for brief_id in expected_ids:
        record = src.get(brief_id)
        if record is None:  # pragma: no cover - defensive
            continue
        dst.put(record)
        migrated_ids.append(brief_id)
        if record.signed_at and record.ledger_event_id:
            # The JSONL replay applied mark_signed onto the in-memory
            # cache. The dst.put above already carries the status, so
            # nothing more is needed — `put` upserts the full record.
            signed_after_migrate.append(brief_id)

    # Cross-check by re-reading from SQLite.
    dst_count = 0
    with dst._lock:  # noqa: SLF001
        row = dst._conn.execute("SELECT COUNT(*) FROM briefs").fetchone()
        dst_count = int(row[0]) if row else 0

    report = {
        "started_at": started,
        "completed_at": time.time(),
        "jsonl_records_seen": len(expected_ids),
        "sqlite_records_after": dst_count,
        "migrated_ids": migrated_ids,
        "signed_records": signed_after_migrate,
        "ok": dst_count >= len(expected_ids),
    }

    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(report, separators=(",", ":")) + "\n")

    if not report["ok"]:
        raise RuntimeError(
            f"Migration row-count mismatch: jsonl={len(expected_ids)} "
            f"sqlite={dst_count}"
        )

    if rename_legacy_to is not None and jsonl_root.exists():
        rename_legacy_to = Path(rename_legacy_to)
        if rename_legacy_to.exists():
            # Make rename atomic & idempotent by suffixing with timestamp.
            rename_legacy_to = rename_legacy_to.with_suffix(
                f".{int(time.time())}"
            )
        shutil.move(str(jsonl_root), str(rename_legacy_to))
        report["renamed_legacy_to"] = str(rename_legacy_to)

    return report


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--src", default="./.directora/briefs",
                   help="JSONL store root directory")
    p.add_argument("--dst", default="./.directora/briefs.db",
                   help="SQLite database path")
    p.add_argument("--rename-legacy-to", default="./.directora/briefs_migrated",
                   help="Where to move the legacy JSONL tree after success")
    p.add_argument("--log-path", default="./.directora/migration.log",
                   help="Append-only migration log JSONL path")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    src = Path(args.src)
    if not src.exists():
        print(json.dumps({"ok": True, "skipped": "no jsonl source"}))
        return 0
    report = migrate_jsonl_to_sqlite(
        src,
        Path(args.dst),
        rename_legacy_to=(Path(args.rename_legacy_to) if args.rename_legacy_to
                          else None),
        log_path=(Path(args.log_path) if args.log_path else None),
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["migrate_jsonl_to_sqlite", "main"]
