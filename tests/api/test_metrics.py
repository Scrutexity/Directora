"""Prometheus metrics tests for the v3.7 canonical metric names."""
from __future__ import annotations

import pytest

from directora.api.metrics import (
    METRICS_REGISTRY,
    brief_sign_total,
    idempotency_replay_total,
    ledger_append_fail_total,
    sqlite_busy_total,
)
from tests.api.conftest import CLINIC_ID, PROVIDER_ID


def _hdrs(token, *, idem=None):
    h = {"Authorization": f"Bearer {token}", "X-Clinic-ID": CLINIC_ID}
    if idem:
        h["Idempotency-Key"] = idem
        h["Content-Type"] = "application/json"
    return h


def _sign_body():
    return {
        "brief_id": "BRF_TEST_01",
        "provider_id": PROVIDER_ID,
        "signature": {"method": "typed", "value": "Dr Jane Doe",
                      "signed_at": "2026-05-16T17:01:33Z"},
        "client": {"app": "labbrief", "version": "2.5.0", "session_id": "s"},
    }


def _counter(c, *labels) -> float:
    if labels:
        return c.labels(*labels)._value.get()
    return c._value.get()


# ---- /metrics endpoint -------------------------------------------------


def test_metrics_endpoint_returns_prometheus_format(client):
    res = client.get("/metrics")
    assert res.status_code == 200
    text = res.text
    # All canonical metric names appear in the output.
    for name in (
        "http_requests_total",
        "http_request_duration_seconds",
        "brief_sign_total",
        "idempotency_replay_total",
        "sqlite_busy_total",
        "ledger_append_fail_total",
        "briefs_pending",
        "briefs_signed",
        "contract_version_info",
    ):
        assert name in text, f"/metrics missing {name}"


def test_metrics_endpoint_open_in_dev(client, monkeypatch):
    monkeypatch.delenv("ENV", raising=False)
    res = client.get("/metrics")
    assert res.status_code == 200


def test_metrics_endpoint_protected_in_production(client, monkeypatch):
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("METRICS_TOKEN", "expected-token")
    # No token → 401.
    assert client.get("/metrics").status_code == 401
    # Wrong token → 401.
    assert client.get(
        "/metrics", headers={"Authorization": "Bearer nope"},
    ).status_code == 401
    # Valid token → 200.
    assert client.get(
        "/metrics", headers={"Authorization": "Bearer expected-token"},
    ).status_code == 200


def test_metrics_production_without_token_fails(client, monkeypatch):
    monkeypatch.setenv("ENV", "production")
    monkeypatch.delenv("METRICS_TOKEN", raising=False)
    assert client.get(
        "/metrics", headers={"Authorization": "Bearer x"},
    ).status_code == 500


# ---- brief_sign_total{result} ----------------------------------------


def test_brief_sign_total_increments_signed_label(
    client, provider_token, stored_brief,
):
    before = _counter(brief_sign_total, "signed")
    res = client.post(
        "/api/brief/sign",
        headers=_hdrs(provider_token, idem="idem-m1"),
        json=_sign_body(),
    )
    assert res.status_code == 200
    after = _counter(brief_sign_total, "signed")
    assert after == before + 1


def test_brief_sign_total_increments_already_signed(
    client, provider_token, stored_brief,
):
    client.post(
        "/api/brief/sign",
        headers=_hdrs(provider_token, idem="idem-m-first"),
        json=_sign_body(),
    )
    before = _counter(brief_sign_total, "already_signed")
    res = client.post(
        "/api/brief/sign",
        headers=_hdrs(provider_token, idem="idem-m-second"),
        json=_sign_body(),
    )
    assert res.status_code == 409
    after = _counter(brief_sign_total, "already_signed")
    assert after == before + 1


def test_brief_sign_total_increments_idempotency_conflict(
    client, provider_token, stored_brief,
):
    client.post(
        "/api/brief/sign",
        headers=_hdrs(provider_token, idem="idem-m-conflict"),
        json=_sign_body(),
    )
    before = _counter(brief_sign_total, "idempotency_conflict")
    # Same idempotency key, different body → conflict.
    res = client.post(
        "/api/brief/sign",
        headers=_hdrs(provider_token, idem="idem-m-conflict"),
        json={**_sign_body(),
              "signature": {"method": "typed", "value": "different",
                            "signed_at": "2026-05-16T17:01:33Z"}},
    )
    assert res.status_code == 409
    after = _counter(brief_sign_total, "idempotency_conflict")
    assert after == before + 1


# ---- replay + busy + ledger fail -------------------------------------


def test_idempotency_replay_total_increments_on_replay(
    client, provider_token, stored_brief,
):
    client.post(
        "/api/brief/sign",
        headers=_hdrs(provider_token, idem="idem-m-replay"),
        json=_sign_body(),
    )
    before = _counter(idempotency_replay_total)
    res = client.post(
        "/api/brief/sign",
        headers=_hdrs(provider_token, idem="idem-m-replay"),
        json=_sign_body(),
    )
    assert res.status_code == 200
    assert res.headers.get("X-Idempotency-Replayed") == "true"
    after = _counter(idempotency_replay_total)
    assert after == before + 1


def test_ledger_append_fail_total_under_chaos(
    monkeypatch, client, provider_token, stored_brief,
):
    monkeypatch.setenv("FAULT_LEDGER_APPEND", "1")
    before = _counter(ledger_append_fail_total)
    res = client.post(
        "/api/brief/sign",
        headers=_hdrs(provider_token, idem="idem-m-fault"),
        json=_sign_body(),
    )
    assert res.status_code == 500
    after = _counter(ledger_append_fail_total)
    assert after == before + 1


def test_sqlite_busy_total_under_chaos(
    monkeypatch, client, provider_token, stored_brief,
):
    import tempfile
    from directora.api import idempotency as idem_module
    from directora.api.idempotency_store import SQLiteIdempotencyStore

    with tempfile.TemporaryDirectory() as tmp:
        sql = SQLiteIdempotencyStore(db_path=f"{tmp}/idem.db")
        idem_module.reset_store_for_tests(sql)
        try:
            monkeypatch.setenv("FAULT_DB_LOCK", "1")
            before = _counter(sqlite_busy_total)
            res = client.post(
                "/api/brief/sign",
                headers=_hdrs(provider_token, idem="idem-m-busy"),
                json=_sign_body(),
            )
            assert res.status_code == 503
            after = _counter(sqlite_busy_total)
            assert after == before + 1
        finally:
            idem_module.reset_store_for_tests(None)


# ---- http_requests_total ---------------------------------------------


def test_http_requests_total_increments_per_route_method_status(
    client, provider_token, stored_brief,
):
    from directora.api.metrics import http_requests_total
    before = _counter(
        http_requests_total, "/api/brief/sign", "POST", "200",
    )
    client.post(
        "/api/brief/sign",
        headers=_hdrs(provider_token, idem="idem-http-1"),
        json=_sign_body(),
    )
    after = _counter(
        http_requests_total, "/api/brief/sign", "POST", "200",
    )
    assert after == before + 1
