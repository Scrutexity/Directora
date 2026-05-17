"""Generate the shared Brief API contract snapshot.

The snapshot is the SINGLE source of truth that:
    1. Directora's API responses validate against (contract tests).
    2. LabBrief's Zod schemas mirror.
    3. LabBrief's MSW handlers must satisfy.

Run from the repo root to regenerate:

    python -m directora.api.contract > shared/brief-api-contract.json

The snapshot is committed and reviewed like any other source file.
Changes require both sides to update in lockstep.
"""
from __future__ import annotations

import json
import sys
from typing import Any

from pydantic import BaseModel

from directora.api.schemas import (
    AuditResponse,
    ErrorResponse,
    PendingBriefResponse,
    ProviderBriefSnippetResponse,
    SignBriefRequest,
    SignBriefResponse,
)

# Map snapshot section name -> pydantic model.
_CONTRACT_MODELS: dict[str, type[BaseModel]] = {
    "PendingBriefResponse": PendingBriefResponse,
    "SignBriefRequest": SignBriefRequest,
    "SignResponse": SignBriefResponse,
    "ProviderBriefResponse": ProviderBriefSnippetResponse,
    "AuditResponse": AuditResponse,
    "ErrorResponse": ErrorResponse,
}

CONTRACT_VERSION = "3.7.0"
"""Bump on every API shape change.

The CI guard in tests/api/test_contract.py compares the version in
`shared/brief-api-contract.json` against this constant. If the snapshot
is regenerated without bumping CONTRACT_VERSION, the test fails with
`snapshot version mismatch`.

Patch releases that don't change response shapes (e.g. v3.7.1's
byte-identical-replay fix) do NOT bump CONTRACT_VERSION — LabBrief
consumers see a stable contract across the engine patch.
"""

ENGINE_RELEASE_VERSION = "3.7.1"
"""Engine release version (semver patch independent of CONTRACT_VERSION).

Bumped on every engine patch — incl. behaviour fixes that don't change
the wire contract. Surfaced on `/health.engine_release` for ops
dashboards; NOT served on the X-Contract-Version response header
(that header remains anchored to CONTRACT_VERSION so consumers don't
see noise during engine patches).

Note: `/health` exposes both `contract_version` (consumer-facing) and
`engine_release` (ops-facing) as DISTINCT fields. The legacy bare
`version` field was renamed in v3.7.1 because on-call was reading it
as "engine version".
"""


def _generated_at_iso() -> str:
    # Deterministic for repeatable diffs: rounded to the second, UTC.
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_contract_snapshot(*, generated_at: str | None = None) -> dict[str, Any]:
    """Return the contract snapshot as a plain dict, deterministic order.

    Each top-level model is self-contained: its nested types live in the
    model's own `$defs`, so a validator can be constructed from a single
    `models[name]` entry without resolving external references.

    Top-level shape:
        {
          "$schema": "https://json-schema.org/draft/2020-12/schema",
          "version": "3.6.0",
          "generated_at": "2026-05-16T19:00:00Z",
          "generated_by": "directora.api.contract.build_contract_snapshot",
          "models": {
            "PendingBriefResponse": { ...JSON Schema... },
            ...
          }
        }

    `generated_at` is parameterised so the contract generator can keep
    reproducible diffs when only the schema content changed.
    """
    models: dict[str, Any] = {}
    for name, model in _CONTRACT_MODELS.items():
        # Use pydantic's default ref_template so refs stay inside each
        # model's own $defs — keeps every model self-contained.
        models[name] = model.model_json_schema()
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Scrutexity Brief API contract",
        "version": CONTRACT_VERSION,
        "generated_at": generated_at or _generated_at_iso(),
        "generated_by": "directora.api.contract.build_contract_snapshot",
        "models": models,
    }


def write_contract_snapshot(path: str) -> None:
    snapshot = build_contract_snapshot()
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(snapshot, fh, indent=2, ensure_ascii=False, sort_keys=True)
        fh.write("\n")


def main() -> int:
    snapshot = build_contract_snapshot()
    json.dump(snapshot, sys.stdout, indent=2, ensure_ascii=False, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
