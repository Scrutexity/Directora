"""Clinic signing secret resolution.

Production swap point: replace `get_clinic_signing_secret` with a KMS or
Vault client. Call sites do not need to change. The function MUST be the
single read path for any clinic signing material so production rotation
and access control land in one place.

Resolution order:
    1. DIRECTORA_CLINIC_SIGNING_SECRET_{CLINIC_ID_SLUG} env var
    2. DIRECTORA_CLINIC_SIGNING_SECRET_DEFAULT env var (dev fallback)
    3. raises MissingClinicSigningSecret
"""
from __future__ import annotations

import os
import re


class MissingClinicSigningSecret(RuntimeError):
    """Raised when no signing secret can be resolved for a clinic."""


_SLUG_RE = re.compile(r"[^A-Z0-9]+")


def _slug(clinic_id: str) -> str:
    """Normalise a clinic_id into an env-var-safe upper-snake slug."""
    return _SLUG_RE.sub("_", str(clinic_id).upper()).strip("_")


def get_clinic_signing_secret(clinic_id: str) -> str:
    """Return the HMAC signing secret for `clinic_id`.

    Look up the per-clinic secret first; fall back to the default for
    development. Raises if neither is configured — production must
    never silently sign with a default.
    """
    slug = _slug(clinic_id)
    per_clinic_var = f"DIRECTORA_CLINIC_SIGNING_SECRET_{slug}"
    secret = os.getenv(per_clinic_var)
    if secret:
        return secret
    fallback = os.getenv("DIRECTORA_CLINIC_SIGNING_SECRET_DEFAULT")
    if fallback:
        return fallback
    raise MissingClinicSigningSecret(
        f"No signing secret configured: set {per_clinic_var} or "
        f"DIRECTORA_CLINIC_SIGNING_SECRET_DEFAULT"
    )


def get_secret(name: str) -> str | None:
    """Return the value of an env var secret, or None if unset."""
    return os.getenv(name)


__all__ = ["get_clinic_signing_secret", "get_secret", "MissingClinicSigningSecret"]
