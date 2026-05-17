"""/health endpoint + startup probe.

The endpoint reports backend selection and contract version; the probe
verifies that the engine can read its critical resources at boot.

`/health` does not require authentication.
"""
from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from directora.api.contract import CONTRACT_VERSION, ENGINE_RELEASE_VERSION

log = logging.getLogger("directora.api.health")

router = APIRouter(tags=["health"])


def _resolve_brief_db_path() -> str:
    return os.getenv("DIRECTORA_BRIEF_DB_PATH", "./.directora/briefs.db")


def _resolve_idempotency_db_path() -> str:
    return os.getenv("IDEMPOTENCY_DB_PATH", "./.directora/idempotency.db")


def _resolve_contract_path() -> str:
    return os.getenv(
        "DIRECTORA_CONTRACT_SNAPSHOT_PATH",
        "shared/brief-api-contract.json",
    )


def _can_open_sqlite(path: str) -> bool:
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path)
        conn.execute("SELECT 1")
        conn.close()
        return True
    except Exception:
        return False


def _contract_loadable(path: str) -> bool:
    try:
        import json
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return bool(data.get("version") and data.get("generated_at"))
    except Exception:
        return False


def _signing_secret_configured() -> bool:
    if os.getenv("DIRECTORA_CLINIC_SIGNING_SECRET_DEFAULT"):
        return True
    return any(
        k.startswith("DIRECTORA_CLINIC_SIGNING_SECRET_") and v
        for k, v in os.environ.items()
    )


@router.get("/health")
def health_check() -> JSONResponse:
    backend = os.getenv("BRIEF_STORE_BACKEND", "sqlite")
    idempotency_backend = os.getenv("IDEMPOTENCY_STORE_BACKEND", "sqlite")
    auth_mode = os.getenv("AUTH_MODE", "stub")
    env = os.getenv("ENV", "development")

    brief_db_ok = (
        _can_open_sqlite(_resolve_brief_db_path()) if backend == "sqlite" else True
    )
    idem_db_ok = (
        _can_open_sqlite(_resolve_idempotency_db_path())
        if idempotency_backend == "sqlite" else True
    )
    contract_ok = _contract_loadable(_resolve_contract_path())
    secret_ok = _signing_secret_configured()

    status = "healthy" if all([brief_db_ok, idem_db_ok, contract_ok, secret_ok]) else "degraded"
    payload: dict[str, Any] = {
        "status": status,
        # Explicit field names — `version` alone was getting confused
        # for "engine version" by on-call. `contract_version` is the
        # consumer-facing shape, `engine_release` is the ops patch.
        "contract_version": CONTRACT_VERSION,
        "engine_release": ENGINE_RELEASE_VERSION,
        "env": env,
        "store_backend": backend,
        "idempotency_backend": idempotency_backend,
        "auth_mode": auth_mode,
        "checks": {
            "brief_db": brief_db_ok,
            "idempotency_db": idem_db_ok,
            "contract_snapshot": contract_ok,
            "signing_secret_configured": secret_ok,
        },
    }
    return JSONResponse(
        status_code=200 if status == "healthy" else 503,
        content=payload,
    )


def startup_probe() -> dict:
    """Run every check the health endpoint runs and log them at boot.

    Returns the same shape as `/health`. The caller can decide whether
    to refuse to start (recommended in production) or just log.
    """
    backend = os.getenv("BRIEF_STORE_BACKEND", "sqlite")
    idempotency_backend = os.getenv("IDEMPOTENCY_STORE_BACKEND", "sqlite")
    auth_mode = os.getenv("AUTH_MODE", "stub")
    env = os.getenv("ENV", "development")

    checks = {
        "brief_db": (
            _can_open_sqlite(_resolve_brief_db_path())
            if backend == "sqlite" else True
        ),
        "idempotency_db": (
            _can_open_sqlite(_resolve_idempotency_db_path())
            if idempotency_backend == "sqlite" else True
        ),
        "contract_snapshot": _contract_loadable(_resolve_contract_path()),
        "signing_secret_configured": _signing_secret_configured(),
    }
    report = {
        "env": env,
        "store_backend": backend,
        "idempotency_backend": idempotency_backend,
        "auth_mode": auth_mode,
        "checks": checks,
        "ok": all(checks.values()),
    }
    if env.lower() == "production" and auth_mode == "stub":
        log.error(
            "STARTUP PROBE FAILED: ENV=production with AUTH_MODE=stub is unsafe"
        )
        report["ok"] = False
    log.info("startup probe: %s", report)
    return report


__all__ = ["router", "health_check", "startup_probe"]
