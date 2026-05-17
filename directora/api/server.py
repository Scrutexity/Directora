"""FastAPI app for the Scrutexity Authority Engine Brief API.

Routes:
    GET  /api/brief/pending
    POST /api/brief/sign
    GET  /api/brief/provider
    GET  /api/labs/audit

Middleware:
    ObservabilityMiddleware  X-Request-ID propagation + boundary logging
    CORSMiddleware           allow LabBrief dev origin via env CORS_ALLOW_ORIGINS

Run for development:
    uvicorn directora.api.server:app --reload
"""
from __future__ import annotations

import os
from typing import Iterable

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from directora.api.health import router as health_router, startup_probe
from directora.api.observability import ObservabilityMiddleware
from directora.api.routes.audit import router as audit_router
from directora.api.routes.brief import router as brief_router
from directora.api.routes.metrics import router as metrics_router


def _cors_origins() -> list[str]:
    raw = os.getenv("CORS_ALLOW_ORIGINS", "http://localhost:5173")
    return [o.strip() for o in raw.split(",") if o.strip()]


def create_app() -> FastAPI:
    app = FastAPI(
        title="Scrutexity Authority Engine — Brief API",
        version="3.5.0",
        description=(
            "Brief API for the Scrutexity Authority Engine. PHI-minimising "
            "endpoints for the LabBrief UI to drive provider sign-off "
            "against the governed workflow ledger."
        ),
    )
    # Order matters: observability wraps the app, CORS wraps observability.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "X-Clinic-ID",
            "X-Request-ID",
            "Idempotency-Key",
            "Content-Type",
        ],
        expose_headers=["X-Request-ID"],
    )
    app.add_middleware(ObservabilityMiddleware)
    app.include_router(health_router)
    app.include_router(metrics_router)
    app.include_router(brief_router)
    app.include_router(audit_router)

    @app.on_event("startup")
    def _on_startup() -> None:
        report = startup_probe()
        if (
            os.getenv("ENV", "").lower() == "production"
            and not report.get("ok", False)
        ):
            raise RuntimeError(
                "Refusing to serve traffic: production startup probe failed. "
                f"report={report}"
            )

    return app


app = create_app()


__all__ = ["app", "create_app"]
