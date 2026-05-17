"""Deterministic JSON serialisation helper.

Every hash computation in the Brief API uses this single helper. No
inline json.dumps anywhere in the API or signing path. Tests assert
byte-identical output across re-serialisation.

Public API:
    canonical_dumps(obj) -> str       deterministic JSON string
    canonical_bytes(obj) -> bytes     UTF-8 encoded canonical bytes
"""
from __future__ import annotations

import json
from typing import Any


def canonical_dumps(obj: Any) -> str:
    """Return a deterministic JSON string for `obj`.

    Rules:
      sort_keys=True          stable ordering across dict insertion order
      separators=(",", ":")   no whitespace drift between environments
      ensure_ascii=False      preserve UTF-8 directly (no \\uXXXX escapes)
      allow_nan=False         no NaN / Infinity drift; raises ValueError
    """
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def canonical_bytes(obj: Any) -> bytes:
    """Return UTF-8 encoded canonical JSON bytes — what hash functions consume."""
    return canonical_dumps(obj).encode("utf-8")


__all__ = ["canonical_dumps", "canonical_bytes"]
