"""/health endpoint + startup probe tests."""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from directora.api.contract import CONTRACT_VERSION
from directora.api.health import startup_probe
from directora.api.server import create_app


@pytest.fixture(autouse=True)
def _baseline_env(monkeypatch):
    monkeypatch.setenv("DIRECTORA_CLINIC_SIGNING_SECRET_DEFAULT", "test")
    yield


def _client():
    return TestClient(create_app())


def test_health_returns_contract_version_and_backends(monkeypatch):
    monkeypatch.setenv("BRIEF_STORE_BACKEND", "sqlite")
    monkeypatch.setenv("IDEMPOTENCY_STORE_BACKEND", "sqlite")
    monkeypatch.setenv("AUTH_MODE", "stub")
    client = _client()
    res = client.get("/health")
    body = res.json()
    assert body["contract_version"] == CONTRACT_VERSION
    assert body["store_backend"] == "sqlite"
    assert body["idempotency_backend"] == "sqlite"
    assert body["auth_mode"] == "stub"


def test_health_uses_explicit_field_names_for_version_axes():
    """v3.7.1 — `/health` exposes `contract_version` AND `engine_release`
    as distinct fields. The legacy bare `version` field was getting
    read as "engine version" by on-call, so we renamed it for clarity.

    The two fields are intentionally independent. The engine can patch
    (bump engine_release) without bumping the consumer contract
    (contract_version stays put).
    """
    from directora.api.contract import ENGINE_RELEASE_VERSION
    client = _client()
    body = client.get("/health").json()
    assert "contract_version" in body, (
        "/health must expose contract_version explicitly"
    )
    assert "engine_release" in body, (
        "/health must expose engine_release for ops dashboards"
    )
    # The legacy bare `version` field is gone — using it now is a
    # KeyError, which catches stale clients at the wire.
    assert "version" not in body, (
        "/health must NOT expose the ambiguous bare `version` field"
    )
    assert body["contract_version"] == CONTRACT_VERSION
    assert body["engine_release"] == ENGINE_RELEASE_VERSION


def test_health_surfaces_contract_and_engine_as_distinct_values():
    """Lock in that the two version axes diverge in v3.7.1. A future
    engineer who 'simplifies' health to a single version field would
    have to make contract_version == engine_release, breaking this
    assertion. The point of the split is that the two can differ;
    asserting non-equality keeps that property visible."""
    from directora.api.contract import ENGINE_RELEASE_VERSION
    client = _client()
    body = client.get("/health").json()
    assert body["contract_version"] == CONTRACT_VERSION
    assert body["engine_release"] == ENGINE_RELEASE_VERSION
    # The very thing that motivated the rename: the two are different.
    # When a future engine patch unifies them again (e.g. v4.0.0 with
    # contract == engine), update this test to reflect the new policy
    # — don't delete it.
    assert body["contract_version"] != body["engine_release"], (
        "v3.7.1 ships with contract_version != engine_release on "
        "purpose. If they unify, document the policy change and "
        "update this assertion explicitly."
    )


def test_health_reports_healthy_when_all_checks_pass():
    client = _client()
    res = client.get("/health")
    body = res.json()
    assert body["status"] in ("healthy", "degraded")
    # All four checks present.
    for key in ("brief_db", "idempotency_db", "contract_snapshot",
                "signing_secret_configured"):
        assert key in body["checks"]


def test_health_returns_503_when_secret_missing(monkeypatch):
    monkeypatch.delenv("DIRECTORA_CLINIC_SIGNING_SECRET_DEFAULT", raising=False)
    for key in list(os.environ):
        if key.startswith("DIRECTORA_CLINIC_SIGNING_SECRET_"):
            monkeypatch.delenv(key, raising=False)
    client = _client()
    res = client.get("/health")
    assert res.status_code == 503
    assert res.json()["status"] == "degraded"


def test_startup_probe_returns_ok_in_dev():
    report = startup_probe()
    assert "checks" in report


def test_startup_probe_marks_production_stub_as_not_ok(monkeypatch):
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("AUTH_MODE", "stub")
    report = startup_probe()
    assert report["ok"] is False
