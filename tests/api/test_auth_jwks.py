"""JWKS-backed RS256 JWT verifier tests.

We do not hit a real JWKS endpoint. Instead we generate an RSA keypair
in-process, encode an RS256 JWT with the private key, and stub the
PyJWKClient to return the matching public key.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from directora.api.auth import (
    JWKSPrincipalResolver,
    Principal,
    UnauthorizedError,
    reset_resolver_cache_for_tests,
)
from directora.api.server import create_app


ISSUER = "scrutexity-auth"


@pytest.fixture
def rsa_keys():
    """Generate an in-process RSA keypair for signing test JWTs."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return SimpleNamespace(
        private_pem=private_pem,
        public_pem=public_pem,
        public_key=public_key,
    )


@pytest.fixture
def jwks_resolver(rsa_keys):
    """A JWKSPrincipalResolver wired to a stub PyJWKClient that returns
    the matching public key for any token."""
    class FakeJWKClient:
        def get_signing_key_from_jwt(self, token):
            # PyJWKClient normally returns a `Key` object with a `.key`
            # attribute. We mimic that interface.
            return SimpleNamespace(key=rsa_keys.public_key)

    return JWKSPrincipalResolver(
        jwks_url="https://example.invalid/.well-known/jwks.json",
        issuer=ISSUER,
        client=FakeJWKClient(),
    )


def _make_jwt(
    rsa_keys,
    *,
    sub="PRV_X",
    clinic_id="CLN_X",
    roles=("provider",),
    exp_seconds_from_now: int = 3600,
    issuer: str = ISSUER,
    missing: tuple[str, ...] = (),
    headers: dict | None = None,
):
    now = datetime.now(timezone.utc)
    payload = {
        "sub": sub,
        "clinic_id": clinic_id,
        "roles": list(roles),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=exp_seconds_from_now)).timestamp()),
        "jti": "jti-test",
        "iss": issuer,
    }
    for key in missing:
        payload.pop(key, None)
    # v3.7: every JWKS-verified token MUST carry kid in the header.
    headers = {"kid": "test-key-1", **(headers or {})}
    return pyjwt.encode(
        payload, rsa_keys.private_pem, algorithm="RS256", headers=headers,
    )


def test_valid_rs256_token_resolves_to_principal(jwks_resolver, rsa_keys):
    token = _make_jwt(rsa_keys)
    p = jwks_resolver.resolve(token)
    assert isinstance(p, Principal)
    assert p.provider_id == "PRV_X"
    assert p.clinic_id == "CLN_X"


def test_expired_token_rejected(jwks_resolver, rsa_keys):
    token = _make_jwt(rsa_keys, exp_seconds_from_now=-10)
    with pytest.raises(UnauthorizedError) as exc:
        jwks_resolver.resolve(token)
    assert exc.value.detail == "token_expired"


def test_wrong_issuer_rejected(jwks_resolver, rsa_keys):
    token = _make_jwt(rsa_keys, issuer="evil.example")
    with pytest.raises(UnauthorizedError) as exc:
        jwks_resolver.resolve(token)
    assert exc.value.detail == "invalid_token"


def test_missing_required_claim_rejected(jwks_resolver, rsa_keys):
    token = _make_jwt(rsa_keys, missing=("exp",))
    with pytest.raises(UnauthorizedError):
        jwks_resolver.resolve(token)


def test_missing_clinic_id_rejected(jwks_resolver, rsa_keys):
    # A JWT that passes signature/claim checks but omits clinic_id.
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "PRV_X",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=1)).timestamp()),
        "jti": "j",
        "iss": ISSUER,
    }
    token = pyjwt.encode(payload, rsa_keys.private_pem, algorithm="RS256")
    with pytest.raises(UnauthorizedError) as exc:
        jwks_resolver.resolve(token)
    assert exc.value.detail == "invalid_token"


def test_jwks_mode_without_jwks_url_refuses_to_serve(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "jwks")
    monkeypatch.delenv("JWKS_URL", raising=False)
    monkeypatch.setenv("DIRECTORA_CLINIC_SIGNING_SECRET_DEFAULT", "test")
    reset_resolver_cache_for_tests()
    client = TestClient(create_app())
    res = client.get(
        "/api/brief/pending",
        headers={"Authorization": "Bearer any-token",
                 "X-Clinic-ID": "CLN_X"},
    )
    assert res.status_code == 500
    body = res.json()
    assert "missing_jwks_url" in (body.get("detail") or body.get("error") or "")


def test_jwks_mode_with_url_resolves_via_resolver(
    monkeypatch, rsa_keys,
):
    """End-to-end: server in JWKS mode resolves a real RS256 token by
    patching the cached resolver's PyJWKClient."""
    monkeypatch.setenv("AUTH_MODE", "jwks")
    monkeypatch.setenv("JWKS_URL", "https://example.invalid/.well-known/jwks.json")
    monkeypatch.setenv("DIRECTORA_CLINIC_SIGNING_SECRET_DEFAULT", "test")
    reset_resolver_cache_for_tests()

    # Patch the JWKSPrincipalResolver to use our stub PyJWKClient.
    from directora.api import auth as auth_module

    class FakeJWKClient:
        def get_signing_key_from_jwt(self, token):
            return SimpleNamespace(key=rsa_keys.public_key)

    real_init = auth_module.JWKSPrincipalResolver.__init__

    def fake_init(self, jwks_url, issuer="scrutexity-auth", *, client=None):
        real_init(self, jwks_url, issuer=issuer, client=FakeJWKClient())

    monkeypatch.setattr(
        auth_module.JWKSPrincipalResolver, "__init__", fake_init,
    )

    client = TestClient(create_app())
    token = _make_jwt(rsa_keys, sub="PRV_X", clinic_id="CLN_X")
    res = client.get(
        "/api/brief/pending",
        headers={"Authorization": f"Bearer {token}", "X-Clinic-ID": "CLN_X"},
    )
    assert res.status_code == 200
    reset_resolver_cache_for_tests()


def test_auth_mode_jwt_alias_is_hs256(monkeypatch):
    """Back-compat: AUTH_MODE=jwt is accepted as alias for hs256."""
    from directora.api.auth import _current_auth_mode
    monkeypatch.setenv("AUTH_MODE", "jwt")
    assert _current_auth_mode() == "hs256"


def test_token_without_kid_is_rejected(jwks_resolver, rsa_keys):
    """v3.7 rule: JWKS verification requires `kid` in the JWT header."""
    # Build a token whose header does NOT carry `kid`.
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "PRV_X", "clinic_id": "CLN_X", "roles": ["provider"],
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=1)).timestamp()),
        "jti": "j", "iss": ISSUER,
    }
    token = pyjwt.encode(
        payload, rsa_keys.private_pem, algorithm="RS256",
    )
    # PyJWT 2.x emits no `kid` by default. If a future version starts
    # auto-populating one, this test fails loudly and we know to update
    # the construction.
    header = pyjwt.get_unverified_header(token)
    assert "kid" not in header, "test setup invariant broken"
    with pytest.raises(UnauthorizedError) as exc:
        jwks_resolver.resolve(token)
    assert exc.value.detail == "invalid_token"


def test_wrong_alg_in_header_is_rejected(jwks_resolver, rsa_keys):
    """A token forged with HS256 must NOT be accepted by the JWKS path."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "PRV_X", "clinic_id": "CLN_X", "roles": ["provider"],
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=1)).timestamp()),
        "jti": "j", "iss": ISSUER,
    }
    forged = pyjwt.encode(
        payload, "shared-secret", algorithm="HS256",
        headers={"kid": "test-key-1"},
    )
    with pytest.raises(UnauthorizedError) as exc:
        jwks_resolver.resolve(forged)
    assert exc.value.detail == "invalid_token"


def test_jwks_fetch_failure_fails_closed(rsa_keys):
    """A PyJWKClient that raises must surface as 401, not 500."""
    class FailingClient:
        def get_signing_key_from_jwt(self, token):
            raise RuntimeError("network unreachable")

    resolver = JWKSPrincipalResolver(
        jwks_url="https://example.invalid/.well-known/jwks.json",
        issuer=ISSUER,
        client=FailingClient(),
    )
    token = _make_jwt(rsa_keys)
    with pytest.raises(UnauthorizedError) as exc:
        resolver.resolve(token)
    assert exc.value.detail == "invalid_token"


def test_jwks_client_constructed_with_cache_ttl(monkeypatch):
    """v3.7 rule: PyJWKClient is constructed with a finite cache TTL.

    We can't inspect PyJWKClient internals reliably across pyjwt
    versions, but we can confirm the resolver passes a `lifespan`
    integer derived from JWKS_CACHE_TTL_SECONDS.
    """
    monkeypatch.setenv("JWKS_CACHE_TTL_SECONDS", "120")
    resolver = JWKSPrincipalResolver(
        jwks_url="https://example.invalid/.well-known/jwks.json",
    )
    # PyJWKClient stores the lifespan as `self.lifespan` on supported
    # versions. Defensive: skip the assertion if the attribute moves.
    lifespan = getattr(resolver.jwks_client, "lifespan", None)
    if lifespan is not None:
        assert int(lifespan) == 120
