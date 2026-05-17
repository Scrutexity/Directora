"""Hash chain primitives for the Brief API sign-off path.

All hashing routes through `canonical_json.canonical_bytes` — no inline
serialisation anywhere else. The HMAC binding payload is versioned so we
can rotate the construction without ambiguity.

Binding payload (v1):
    v1:{brief_content_hash}
      :{signature_value_hash}
      :{engine_run_id}
      :{authority_brief_version}
      :{provider_brief_version}
      :{clinic_id}
      :{provider_id}
      :{signed_at}

The engine_run_id + version fields prevent a brief regenerated under a
different run from being signed against a stale context.
"""
from __future__ import annotations

import hashlib
import hmac
import unicodedata
from typing import Any

from directora.scrutexity.canonical_json import canonical_bytes
from directora.api.secrets import get_clinic_signing_secret


BINDING_VERSION = "v1"


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def compute_brief_content_hash(canonical_brief_json: str | bytes) -> str:
    """Hash the canonical Provider Brief JSON.

    Accepts either a canonical JSON string (UTF-8 encodable) or raw bytes
    that the caller has already produced via `canonical_bytes`. Use this
    only with the JSON that triggered `provider_brief_ready`.
    """
    if isinstance(canonical_brief_json, str):
        data = canonical_brief_json.encode("utf-8")
    else:
        data = canonical_brief_json
    return sha256_hex(data)


def hash_brief_dict(brief_dict: dict) -> str:
    """Helper: canonicalise + hash a brief dict in one step."""
    return compute_brief_content_hash(canonical_bytes(brief_dict))


def normalise_signature_value(value: str) -> str:
    """Trim, NFKC-normalise, and collapse internal whitespace runs.

    The same physical signature retyped with stray spaces or different
    Unicode normal forms must hash to the same bytes.
    """
    if value is None:
        return ""
    nfkc = unicodedata.normalize("NFKC", str(value))
    stripped = nfkc.strip()
    # Collapse any whitespace run (spaces, tabs, NBSP, etc.) to a single space.
    return " ".join(stripped.split())


def compute_signature_value_hash(value: str) -> str:
    return sha256_hex(normalise_signature_value(value).encode("utf-8"))


def build_binding_payload(
    *,
    brief_content_hash: str,
    signature_value_hash: str,
    engine_run_id: str,
    authority_brief_version: str,
    provider_brief_version: str,
    clinic_id: str,
    provider_id: str,
    signed_at: str,
) -> str:
    return (
        f"{BINDING_VERSION}:{brief_content_hash}:{signature_value_hash}"
        f":{engine_run_id}:{authority_brief_version}:{provider_brief_version}"
        f":{clinic_id}:{provider_id}:{signed_at}"
    )


def compute_binding_hash(
    *,
    brief_content_hash: str,
    signature_value_hash: str,
    engine_run_id: str,
    authority_brief_version: str,
    provider_brief_version: str,
    clinic_id: str,
    provider_id: str,
    signed_at: str,
) -> str:
    """HMAC-SHA256 over the canonical binding payload, keyed by the
    clinic's signing secret. Raises MissingClinicSigningSecret if no
    secret is configured for the clinic."""
    payload = build_binding_payload(
        brief_content_hash=brief_content_hash,
        signature_value_hash=signature_value_hash,
        engine_run_id=engine_run_id,
        authority_brief_version=authority_brief_version,
        provider_brief_version=provider_brief_version,
        clinic_id=clinic_id,
        provider_id=provider_id,
        signed_at=signed_at,
    )
    secret = get_clinic_signing_secret(clinic_id).encode("utf-8")
    return hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()


def request_hash(payload: dict | bytes) -> str:
    """Hash a request body for idempotency comparison.

    Accepts a dict (canonicalised first) or pre-encoded bytes.
    """
    if isinstance(payload, dict):
        return sha256_hex(canonical_bytes(payload))
    return sha256_hex(payload)


__all__ = [
    "BINDING_VERSION",
    "sha256_hex",
    "compute_brief_content_hash",
    "hash_brief_dict",
    "normalise_signature_value",
    "compute_signature_value_hash",
    "build_binding_payload",
    "compute_binding_hash",
    "request_hash",
]
