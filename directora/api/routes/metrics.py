"""/metrics endpoint.

Returns Prometheus text exposition. In production the endpoint is
guarded by `METRICS_TOKEN` (`Authorization: Bearer <token>`). In dev /
test it is open so scrapers and load-test dashboards can pull without
ceremony.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Header, HTTPException, Response
from typing import Optional

from directora.api.contract import CONTRACT_VERSION
from directora.api.metrics import (
    CONTENT_TYPE_LATEST,
    contract_version_info,
    render_metrics_text,
)

router = APIRouter(tags=["metrics"])

# Initialise the contract version gauge once. The metric carries the
# version string as a label; the value is always 1.
contract_version_info.labels(version=CONTRACT_VERSION).set(1)


def _is_production() -> bool:
    return os.getenv("ENV", "").lower() == "production"


@router.get("/metrics")
def metrics_endpoint(
    authorization: Optional[str] = Header(default=None),
) -> Response:
    if _is_production():
        expected = os.getenv("METRICS_TOKEN")
        if not expected:
            raise HTTPException(status_code=500, detail="metrics_token_unset")
        if (
            not authorization
            or not authorization.lower().startswith("bearer ")
            or authorization.split(" ", 1)[1].strip() != expected
        ):
            raise HTTPException(status_code=401, detail="metrics_unauthorized")
    return Response(
        content=render_metrics_text(),
        media_type=CONTENT_TYPE_LATEST,
    )


__all__ = ["router"]
