"""Prometheus metrics — canonical names exposed at /metrics.

Public surface (this is the contract):

    # Generic HTTP metrics, emitted by the observability middleware.
    http_requests_total{route,method,status}        Counter
    http_request_duration_seconds{route,method}     Histogram (exposes _bucket / _sum / _count)

    # Sign-off specific.
    brief_sign_total{result}                        Counter
        result ∈ {signed, already_signed, idempotency_conflict,
                  invalid_status, engine_or_ledger_failure}

    idempotency_replay_total                        Counter
    sqlite_busy_total                               Counter (503s due to SQLite busy)
    ledger_append_fail_total                        Counter

    # Gauges.
    briefs_pending                                  Gauge (sampled on /pending)
    briefs_signed                                   Gauge (incremented on success)
    contract_version_info{version}                  Gauge (always 1; label carries the version)

All metrics are registered against a private `CollectorRegistry` so the
test suite and any concurrently-imported prometheus_client client code
remain isolated.
"""
from __future__ import annotations

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

METRICS_REGISTRY = CollectorRegistry(auto_describe=False)


# ---- HTTP-level metrics (emitted by ObservabilityMiddleware) -----------

http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests grouped by route, method and status",
    labelnames=["route", "method", "status"],
    registry=METRICS_REGISTRY,
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds grouped by route and method",
    labelnames=["route", "method"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    registry=METRICS_REGISTRY,
)


# ---- Sign-off + idempotency + storage + ledger ------------------------

# Possible result labels for brief_sign_total. The whitelist enforced
# here is also the contract LabBrief relies on for dashboards.
BRIEF_SIGN_RESULTS = (
    "signed",
    "already_signed",
    "idempotency_conflict",
    "invalid_status",
    "engine_or_ledger_failure",
)

brief_sign_total = Counter(
    "brief_sign_total",
    "Total sign-off requests grouped by terminal result",
    labelnames=["result"],
    registry=METRICS_REGISTRY,
)
# Pre-initialise label combinations so they appear in /metrics even
# before the first request. Counters expose `0` until incremented; this
# avoids gaps in Grafana panels at engine boot.
for _label in BRIEF_SIGN_RESULTS:
    brief_sign_total.labels(result=_label)

idempotency_replay_total = Counter(
    "idempotency_replay_total",
    "Total idempotent replays returned",
    registry=METRICS_REGISTRY,
)

sqlite_busy_total = Counter(
    "sqlite_busy_total",
    "Total SQLite busy events translated to 503 + Retry-After",
    registry=METRICS_REGISTRY,
)

ledger_append_fail_total = Counter(
    "ledger_append_fail_total",
    "Total ledger append failures observed by the API",
    registry=METRICS_REGISTRY,
)


# ---- Gauges -----------------------------------------------------------

briefs_pending = Gauge(
    "briefs_pending",
    "Number of briefs awaiting provider review (sampled on /pending)",
    registry=METRICS_REGISTRY,
)

briefs_signed = Gauge(
    "briefs_signed",
    "Number of briefs that have been signed in this process lifetime",
    registry=METRICS_REGISTRY,
)

contract_version_info = Gauge(
    "contract_version_info",
    "Contract version reported as a label; value is always 1",
    labelnames=["version"],
    registry=METRICS_REGISTRY,
)


def render_metrics_text() -> bytes:
    return generate_latest(METRICS_REGISTRY)


__all__ = [
    "METRICS_REGISTRY",
    "CONTENT_TYPE_LATEST",
    "render_metrics_text",
    "BRIEF_SIGN_RESULTS",
    # HTTP-level
    "http_requests_total",
    "http_request_duration_seconds",
    # Sign-off + storage
    "brief_sign_total",
    "idempotency_replay_total",
    "sqlite_busy_total",
    "ledger_append_fail_total",
    "briefs_pending",
    "briefs_signed",
    "contract_version_info",
]
