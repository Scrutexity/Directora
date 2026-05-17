"""Observability middleware for the Brief API.

Responsibilities:
    1. Generate or propagate `X-Request-ID` on every request.
    2. Echo it on every response header.
    3. Inject it into error response bodies so the LabBrief UI can
       surface it in its "Error Details" panel (dev-only).
    4. Log `[request_id] METHOD path -> status latency_ms` at the
       boundary (start + end).

The middleware never adds PHI to logs — only request_id, method, path,
status code, and latency.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

log = logging.getLogger("directora.api.observability")

REQUEST_ID_HEADER = "X-Request-ID"
CONTRACT_VERSION_HEADER = "X-Contract-Version"


def _route_label(request: Request) -> str:
    """Return a low-cardinality route label.

    FastAPI sets `request.scope["route"]` for matched routes; we read
    `route.path` to get the pattern (e.g. `/api/brief/sign`) rather
    than the concrete request path. Falls back to the raw path for
    unknown routes.
    """
    route = request.scope.get("route")
    return getattr(route, "path", request.url.path) if route else request.url.path


def _new_request_id() -> str:
    return f"req_{uuid.uuid4().hex}"


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """Attach X-Request-ID to every request/response and log boundary events."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or _new_request_id()
        request.state.request_id = request_id

        start = time.time()
        log.info("[%s] %s %s start", request_id, request.method, request.url.path)
        try:
            response = await call_next(request)
        except Exception:
            log.exception("[%s] %s %s 500", request_id, request.method, request.url.path)
            raise
        latency_s = time.time() - start
        latency_ms = int(latency_s * 1000)

        # Echo the request id and contract version on the response.
        response.headers[REQUEST_ID_HEADER] = request_id
        # Lazy import to avoid a circular at module import time.
        try:
            from directora.api.contract import CONTRACT_VERSION
            response.headers[CONTRACT_VERSION_HEADER] = CONTRACT_VERSION
        except Exception:  # pragma: no cover - defensive
            pass

        # Emit generic HTTP-level metrics. Route label uses the matched
        # pattern (low cardinality) so concrete IDs don't blow up the
        # cardinality of {route} in Prometheus.
        try:
            from directora.api.metrics import (
                http_request_duration_seconds,
                http_requests_total,
            )
            route_label = _route_label(request)
            method_label = request.method.upper()
            http_requests_total.labels(
                route=route_label,
                method=method_label,
                status=str(response.status_code),
            ).inc()
            http_request_duration_seconds.labels(
                route=route_label, method=method_label,
            ).observe(latency_s)
        except Exception:  # pragma: no cover - never block on metrics
            pass

        # For error responses, inject the request_id into the JSON body
        # so the client UI can surface it. We only do this for JSON
        # responses to avoid corrupting binary or non-JSON payloads.
        if response.status_code >= 400 and _is_json_response(response):
            response = await _inject_request_id_into_body(response, request_id)

        log.info(
            "[%s] %s %s %s %dms",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            latency_ms,
        )
        return response


def _is_json_response(response: Response) -> bool:
    ctype = response.headers.get("content-type", "")
    return "application/json" in ctype.lower()


async def _inject_request_id_into_body(
    response: Response, request_id: str
) -> Response:
    """Read the body, parse JSON, add request_id, re-emit. Safe for our
    own ErrorResponse shape; falls back to passthrough on parse failure."""
    body_chunks = []
    async for chunk in response.body_iterator:
        body_chunks.append(chunk)
    body = b"".join(body_chunks)
    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        # Not a JSON body we can safely modify — return as-is.
        return Response(
            content=body,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type,
        )

    if isinstance(payload, dict) and "request_id" not in payload:
        payload["request_id"] = request_id

    new_body = json.dumps(
        payload, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    headers = dict(response.headers)
    # content-length must be recomputed since we may have grown the body.
    headers["content-length"] = str(len(new_body))
    return Response(
        content=new_body,
        status_code=response.status_code,
        headers=headers,
        media_type=response.media_type or "application/json",
    )


__all__ = ["ObservabilityMiddleware", "REQUEST_ID_HEADER"]
