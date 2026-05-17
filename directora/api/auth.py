"""Authentication: stub bearer token + JWT verifier.

v3.6: introduces `JWTPrincipalResolver` alongside the bearer-token stub.
The `resolve_principal` FastAPI dependency interface is unchanged — call
sites do not need to know which resolver is active.

Env switch:
    AUTH_MODE       = "stub" (default in dev) | "jwt"
    ENV             = "production" | anything else
    JWT_SECRET_KEY  = symmetric secret (HS256)
    JWT_ISSUER      = expected issuer claim (defaults to "scrutexity-auth")

Production safety:
    If `ENV=production` and `AUTH_MODE=stub`, `resolve_principal` raises
    a 500 at request time. This is a deliberate fail-loud safety net.
    Same for missing JWT_SECRET_KEY when AUTH_MODE=jwt.
"""
from __future__ import annotations

import base64
import binascii
import json
import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt as pyjwt
from jwt import PyJWKClient
from fastapi import Header, HTTPException


# ---------- Principal ----------------------------------------------------


@dataclass(frozen=True)
class Principal:
    provider_id: str
    clinic_id: str
    roles: tuple[str, ...]

    def has_role(self, role: str) -> bool:
        return role in self.roles


# ---------- Stub bearer-token resolver (legacy, dev only) ---------------


def encode_stub_token(
    provider_id: str, clinic_id: str, roles: tuple[str, ...] = ("provider",)
) -> str:
    """Produce a base64-encoded JSON token the stub resolver decodes.

    Only valid when AUTH_MODE=stub. Never use in production.
    """
    payload = json.dumps(
        {"provider_id": provider_id, "clinic_id": clinic_id, "roles": list(roles)},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_stub(token: str) -> Principal:
    pad = "=" * (-len(token) % 4)
    try:
        raw = base64.urlsafe_b64decode(token + pad)
        data = json.loads(raw.decode("utf-8"))
    except (binascii.Error, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=401, detail="invalid_token") from exc
    try:
        return Principal(
            provider_id=str(data["provider_id"]),
            clinic_id=str(data["clinic_id"]),
            roles=tuple(data.get("roles", ()) or ()),
        )
    except KeyError as exc:
        raise HTTPException(status_code=401, detail="invalid_token") from exc


# ---------- JWT resolver -------------------------------------------------


class UnauthorizedError(HTTPException):
    """Convenience type for JWT failures. Always emitted as 401."""

    def __init__(self, code: str):
        super().__init__(status_code=401, detail=code)


class JWTPrincipalResolver:
    """HS256 JWT verifier.

    Expected payload:
        {
            "sub": "<provider_id>",
            "clinic_id": "<clinic_uuid>",
            "roles": ["provider", "medical_director"],
            "iat": <unix>,
            "exp": <unix>,
            "jti": "<unique token id>",
            "iss": "scrutexity-auth"
        }

    Production swap target: replace HS256 with RS256 and a JWKS lookup
    when the auth team is ready. The verify_jwt method is the single
    swap point.
    """

    def __init__(self, secret_key: str, issuer: str = "scrutexity-auth"):
        self.secret_key = secret_key
        self.issuer = issuer

    def verify_jwt(self, token: str) -> dict:
        try:
            payload = pyjwt.decode(
                token,
                self.secret_key,
                algorithms=["HS256"],
                issuer=self.issuer,
                options={"require": ["exp", "iat", "jti", "sub", "iss"]},
            )
        except pyjwt.ExpiredSignatureError as exc:
            raise UnauthorizedError("token_expired") from exc
        except pyjwt.InvalidIssuerError as exc:
            raise UnauthorizedError("invalid_token") from exc
        except pyjwt.MissingRequiredClaimError as exc:
            raise UnauthorizedError("invalid_token") from exc
        except pyjwt.InvalidTokenError as exc:
            raise UnauthorizedError("invalid_token") from exc
        if "clinic_id" not in payload:
            raise UnauthorizedError("invalid_token")
        return payload

    def resolve(self, token: str) -> Principal:
        payload = self.verify_jwt(token)
        return Principal(
            provider_id=str(payload["sub"]),
            clinic_id=str(payload["clinic_id"]),
            roles=tuple(payload.get("roles", ("provider",))),
        )


# ---------- JWKS resolver (production, no shared secret) ---------------


class JWKSPrincipalResolver:
    """RS256 JWT verifier using a JWKS endpoint.

    Production auth mode — no shared secret. Same `resolve` interface
    as the HS256 resolver. The PyJWKClient handles fetching, caching,
    and key rotation.

    Verification rules (v3.7):
        * Cache JWKS for `JWKS_CACHE_TTL_SECONDS` (default 600s = 10m).
        * Token header MUST carry `kid`; tokens without `kid` are rejected.
        * RS256 only — HS256 is reserved for the HS256 resolver / dev.
        * JWKS fetch failures fail closed: a JWKS lookup error in
          production yields `UnauthorizedError("invalid_token")` rather
          than masquerading as a 500. The middleware will translate it
          to a 401.

    Expected JWT payload identical to JWTPrincipalResolver:
        sub, clinic_id, roles[], iat, exp, jti, iss
    """

    def __init__(
        self,
        jwks_url: str,
        issuer: str = "scrutexity-auth",
        *,
        client: Optional[PyJWKClient] = None,
        cache_ttl_seconds: Optional[int] = None,
    ):
        self.jwks_url = jwks_url
        self.issuer = issuer
        ttl = int(
            cache_ttl_seconds
            if cache_ttl_seconds is not None
            else os.getenv("JWKS_CACHE_TTL_SECONDS", "600")
        )
        # PyJWKClient supports `lifespan` (seconds). Some older versions
        # accept `cache_keys`; we set both defensively.
        try:
            self.jwks_client = client or PyJWKClient(
                jwks_url, cache_keys=True, lifespan=ttl,
            )
        except TypeError:  # pragma: no cover - older pyjwt
            self.jwks_client = client or PyJWKClient(jwks_url)

    def verify_jwt(self, token: str) -> dict:
        # 1. Token header MUST carry `kid`. JWKS verification without
        #    a key id is unsafe.
        try:
            header = pyjwt.get_unverified_header(token)
        except pyjwt.InvalidTokenError as exc:
            raise UnauthorizedError("invalid_token") from exc
        if not header.get("kid"):
            raise UnauthorizedError("invalid_token")
        if header.get("alg") and header["alg"] != "RS256":
            raise UnauthorizedError("invalid_token")

        # 2. JWKS lookup — fail closed if it raises.
        try:
            signing_key = self.jwks_client.get_signing_key_from_jwt(token)
        except Exception as exc:
            # Includes PyJWKClientError, network errors, malformed jwks.
            raise UnauthorizedError("invalid_token") from exc

        # 3. Verify payload.
        try:
            payload = pyjwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                issuer=self.issuer,
                options={"require": ["exp", "iat", "jti", "sub", "iss"]},
            )
        except pyjwt.ExpiredSignatureError as exc:
            raise UnauthorizedError("token_expired") from exc
        except pyjwt.InvalidIssuerError as exc:
            raise UnauthorizedError("invalid_token") from exc
        except pyjwt.MissingRequiredClaimError as exc:
            raise UnauthorizedError("invalid_token") from exc
        except pyjwt.InvalidTokenError as exc:
            raise UnauthorizedError("invalid_token") from exc
        if "clinic_id" not in payload:
            raise UnauthorizedError("invalid_token")
        return payload

    def resolve(self, token: str) -> Principal:
        payload = self.verify_jwt(token)
        return Principal(
            provider_id=str(payload["sub"]),
            clinic_id=str(payload["clinic_id"]),
            roles=tuple(payload.get("roles", ("provider",))),
        )


# ---------- Resolver factory + production safety -----------------------


def _is_production() -> bool:
    return os.getenv("ENV", "").lower() == "production"


def _current_auth_mode() -> str:
    """Normalise AUTH_MODE. Accepted values: stub, hs256, jwks.

    Back-compat alias: `jwt` → `hs256` (legacy v3.6 value).
    """
    raw = os.getenv("AUTH_MODE", "stub").lower()
    if raw == "jwt":
        return "hs256"
    return raw


def _refuse_unsafe_production() -> None:
    """Production safety:
        * Forbid stub auth in production.
        * Forbid HS256 mode with no signing secret configured.
        * Forbid JWKS mode with no JWKS_URL configured.
    """
    mode = _current_auth_mode()
    if _is_production() and mode == "stub":
        raise HTTPException(
            status_code=500,
            detail=(
                "unsafe_auth_mode: AUTH_MODE=stub is forbidden when "
                "ENV=production. Set AUTH_MODE=jwks (preferred) or hs256."
            ),
        )
    if mode == "hs256" and not os.getenv("JWT_SECRET_KEY"):
        raise HTTPException(
            status_code=500,
            detail=(
                "missing_jwt_secret: AUTH_MODE=hs256 requires "
                "JWT_SECRET_KEY to be set."
            ),
        )
    if mode == "jwks" and not os.getenv("JWKS_URL"):
        raise HTTPException(
            status_code=500,
            detail=(
                "missing_jwks_url: AUTH_MODE=jwks requires "
                "JWKS_URL to be set."
            ),
        )


_jwks_resolver_cache: Optional["JWKSPrincipalResolver"] = None


def _build_resolver():
    mode = _current_auth_mode()
    if mode == "hs256":
        return JWTPrincipalResolver(
            secret_key=os.environ["JWT_SECRET_KEY"],
            issuer=os.getenv("JWT_ISSUER", "scrutexity-auth"),
        )
    if mode == "jwks":
        global _jwks_resolver_cache
        # Cache the resolver so the underlying PyJWKClient keeps its
        # signing-key cache between requests. Tests can clear via
        # reset_resolver_cache_for_tests().
        if _jwks_resolver_cache is None:
            _jwks_resolver_cache = JWKSPrincipalResolver(
                jwks_url=os.environ["JWKS_URL"],
                issuer=os.getenv("JWT_ISSUER", "scrutexity-auth"),
            )
        return _jwks_resolver_cache
    return None  # signals: use the bare stub path


def reset_resolver_cache_for_tests() -> None:
    global _jwks_resolver_cache
    _jwks_resolver_cache = None


def resolve_principal(
    authorization: Optional[str] = Header(default=None),
    x_clinic_id: Optional[str] = Header(default=None, alias="X-Clinic-ID"),
) -> Principal:
    _refuse_unsafe_production()
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing_bearer_token")
    token = authorization.split(" ", 1)[1].strip()

    resolver = _build_resolver()
    if resolver is None:
        principal = _decode_stub(token)
    else:
        principal = resolver.resolve(token)

    if x_clinic_id and x_clinic_id != principal.clinic_id:
        raise HTTPException(status_code=403, detail="clinic_mismatch")
    return principal


# ---------- Dev-only token generation -----------------------------------


def generate_dev_token(
    provider_id: str,
    clinic_id: str,
    roles: Optional[list[str]] = None,
    *,
    ttl_hours: int = 8,
) -> str:
    """Generate a JWT for development / smoke tests.

    Refuses to run when ENV=production. Requires JWT_SECRET_KEY.
    """
    if _is_production():
        raise RuntimeError("Token generation disabled in production")
    secret = os.environ.get("JWT_SECRET_KEY")
    if not secret:
        raise RuntimeError(
            "JWT_SECRET_KEY must be set to generate dev tokens"
        )
    now = datetime.now(timezone.utc)
    payload = {
        "sub": provider_id,
        "clinic_id": clinic_id,
        "roles": roles or ["provider"],
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=ttl_hours)).timestamp()),
        "jti": str(uuid.uuid4()),
        "iss": os.getenv("JWT_ISSUER", "scrutexity-auth"),
    }
    return pyjwt.encode(payload, secret, algorithm="HS256")


__all__ = [
    "Principal",
    "JWTPrincipalResolver",
    "JWKSPrincipalResolver",
    "UnauthorizedError",
    "resolve_principal",
    "reset_resolver_cache_for_tests",
    "encode_stub_token",
    "generate_dev_token",
]
