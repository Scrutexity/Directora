"""Storage facade for the API layer.

Re-exports the brief store and a small mapper so route handlers do not
import deeply into the scrutexity package. Production swap points
(persistent backends, KMS-bound secrets) plug in here.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from directora.scrutexity.brief_store import (
    BriefRecord,
    BriefStatus,
    BriefStore,
    InMemoryBriefStore,
    FilesystemBriefStore,
    get_brief_store,
    reset_store_for_tests,
)

__all__ = [
    "BriefRecord",
    "BriefStatus",
    "BriefStore",
    "InMemoryBriefStore",
    "FilesystemBriefStore",
    "get_brief_store",
    "reset_store_for_tests",
]
