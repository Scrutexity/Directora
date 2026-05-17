"""JWT auth tests + production safety net.

Covers:
    valid JWT → correct Principal
    expired JWT → 401 token_expired
    invalid signature → 401 invalid_token
    missing required claims → 401 invalid_token
    wrong issuer → 401 invalid_token
    stub mode still works when AUTH_MODE=stub
    JWT mode is selected when AUTH_MODE=jwt
    Production safety: ENV=production + AUTH_MODE=stub → refuse
    Production safety: AUTH_MODE=jwt without JWT_SECRET_KEY → refuse
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient

from directora.api.auth import (
    JWTPrincipalResolver,
    Principal,
    UnauthorizedError,
    encode_stub_token,
    generate_dev_token,
)
from directora.api.server import create_app


SECRET = "test-jwt-secret"
ISSUER = "scrutexity-auth"


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch):
    """Ensure each test starts from a clean auth env."""
    for var in ("AUTH_MODE", "JWT_SECRET_KEY", "JWT_ISSUER", "ENV"):
        monkeypatch.delenv(var, raising=False)
    yield


def _make_jwt(sub="PRV_X", clinic_id="CLN_X",
              roles=("provider",), *,
              exp_seconds_from_now: int = 3600,
              issuer: str = ISSUER,
              missing: tuple[str, ...] = ()) -> str:
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
    return pyjwt.encode(payload, SECRET, algorithm="HS256")


# ---------- Resolver-level tests ---------------------------------------


def test_valid_jwt_resolves_to_principal():
    r = JWTPrincipalResolver(SECRET, ISSUER)
    p = r.resolve(_make_jwt())
    assert isinstance(p, Principal)
    assert p.provider_id == "PRV_X"
    assert p.clinic_id == "CLN_X"
    assert "provider" in p.roles


def test_expired_jwt_returns_token_expired():
    r = JWTPrincipalResolver(SECRET, ISSUER)
    expired = _make_jwt(exp_seconds_from_now=-10)
    with pytest.raises(UnauthorizedError) as exc:
        r.resolve(expired)
    assert exc.value.detail == "token_expired"


def test_invalid_signature_returns_invalid_token():
    r = JWTPrincipalResolver(SECRET, ISSUER)
    other = pyjwt.encode(
        {
            "sub": "x", "clinic_id": "y", "roles": [], "iat": int(time.time()),
            "exp": int(time.time()) + 60, "jti": "j", "iss": ISSUER,
        },
        "DIFFERENT-SECRET", algorithm="HS256",
    )
    with pytest.raises(UnauthorizedError) as exc:
        r.resolve(other)
    assert exc.value.detail == "invalid_token"


def test_missing_required_claims_rejected():
    r = JWTPrincipalResolver(SECRET, ISSUER)
    with pytest.raises(UnauthorizedError):
        r.resolve(_make_jwt(missing=("exp",)))


def test_wrong_issuer_rejected():
    r = JWTPrincipalResolver(SECRET, ISSUER)
    with pytest.raises(UnauthorizedError):
        r.resolve(_make_jwt(issuer="evil.example"))


def test_missing_clinic_id_rejected(monkeypatch):
    """Even if the JWT verifies, an absent clinic_id is invalid."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "PRV", "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=1)).timestamp()),
        "jti": "j", "iss": ISSUER,
    }
    bad = pyjwt.encode(payload, SECRET, algorithm="HS256")
    r = JWTPrincipalResolver(SECRET, ISSUER)
    with pytest.raises(UnauthorizedError):
        r.resolve(bad)


# ---------- Mode switching + HTTP integration --------------------------


def _hdrs(token):
    return {"Authorization": f"Bearer {token}", "X-Clinic-ID": "CLN_X"}


def test_stub_mode_default(monkeypatch):
    """AUTH_MODE unset → stub path."""
    monkeypatch.setenv("DIRECTORA_CLINIC_SIGNING_SECRET_DEFAULT", "s")
    client = TestClient(create_app())
    token = encode_stub_token("PRV_X", "CLN_X")
    res = client.get("/api/brief/pending", headers=_hdrs(token))
    assert res.status_code == 200


def test_jwt_mode_swaps_resolver(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "jwt")
    monkeypatch.setenv("JWT_SECRET_KEY", SECRET)
    monkeypatch.setenv("DIRECTORA_CLINIC_SIGNING_SECRET_DEFAULT", "s")
    client = TestClient(create_app())
    token = _make_jwt(sub="PRV_X", clinic_id="CLN_X")
    res = client.get("/api/brief/pending", headers=_hdrs(token))
    assert res.status_code == 200


def test_jwt_mode_rejects_stub_token(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "jwt")
    monkeypatch.setenv("JWT_SECRET_KEY", SECRET)
    monkeypatch.setenv("DIRECTORA_CLINIC_SIGNING_SECRET_DEFAULT", "s")
    client = TestClient(create_app())
    stub_token = encode_stub_token("PRV_X", "CLN_X")
    res = client.get("/api/brief/pending", headers=_hdrs(stub_token))
    assert res.status_code == 401


# ---------- Production safety -----------------------------------------


def test_production_with_stub_auth_refuses_to_serve(monkeypatch):
    """Spec: if ENV=production and AUTH_MODE=stub, the engine must
    refuse to serve. We surface this as a 500 at request time."""
    monkeypatch.setenv("ENV", "production")
    # leave AUTH_MODE unset (default stub)
    client = TestClient(create_app())
    res = client.get(
        "/api/brief/pending",
        headers=_hdrs(encode_stub_token("PRV_X", "CLN_X")),
    )
    assert res.status_code == 500
    assert "unsafe_auth_mode" in (
        res.json().get("detail") or res.json().get("error") or ""
    )


def test_jwt_mode_without_secret_refuses_to_serve(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "jwt")
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    client = TestClient(create_app())
    res = client.get(
        "/api/brief/pending",
        headers=_hdrs("any-token"),
    )
    assert res.status_code == 500
    assert "missing_jwt_secret" in (
        res.json().get("detail") or res.json().get("error") or ""
    )


# ---------- generate_dev_token ----------------------------------------


def test_generate_dev_token_succeeds_without_production(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", SECRET)
    monkeypatch.setenv("JWT_ISSUER", ISSUER)
    token = generate_dev_token("PRV_X", "CLN_X")
    r = JWTPrincipalResolver(SECRET, ISSUER)
    p = r.resolve(token)
    assert p.provider_id == "PRV_X"
    assert p.clinic_id == "CLN_X"


def test_generate_dev_token_refuses_in_production(monkeypatch):
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("JWT_SECRET_KEY", SECRET)
    with pytest.raises(RuntimeError, match="production"):
        generate_dev_token("PRV", "CLN")
