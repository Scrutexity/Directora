"""Feature 5 — Native push notifications (Pusher Beams / OneSignal).

POST /api/notifications/register   register device token
DELETE /api/notifications/register  unregister device
POST /api/notifications/send        send push to all registered devices (internal)
GET  /api/notifications/devices     list registered devices

Set ONE of these env vars to activate a provider:
  PUSHER_INSTANCE_ID + PUSHER_SECRET_KEY   → Pusher Beams
  ONESIGNAL_APP_ID + ONESIGNAL_API_KEY     → OneSignal

Without a provider configured, notifications are logged but not sent
(useful for local dev — check server logs for the payload).
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Literal, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
import secrets

from directora.api.secrets import get_secret

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/notifications", tags=["notifications"])

_bearer = HTTPBearer(auto_error=True)

_devices: dict[str, dict[str, Any]] = {}


def _verify_token(creds: HTTPAuthorizationCredentials = Depends(_bearer)) -> str:
    expected = get_secret("BIRKIN_TOKEN")
    if not expected or not secrets.compare_digest(creds.credentials, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return creds.credentials


class DeviceRegisterRequest(BaseModel):
    device_token: str
    platform: Literal["ios", "macos", "watchos"] = "ios"
    device_name: Optional[str] = None


class DeviceRegisterResponse(BaseModel):
    device_id: str
    platform: str
    registered: bool
    registered_at: str


class NotificationPayload(BaseModel):
    title: str
    body: str
    category: Literal["governance_fail", "budget_alert", "skill_complete", "agent_alert"] = "agent_alert"
    data: Optional[dict[str, Any]] = None


class NotificationSendResponse(BaseModel):
    sent: bool
    provider: Optional[str]
    devices: int
    notification_id: Optional[str] = None


@router.post("/register", response_model=DeviceRegisterResponse)
async def register_device(
    body: DeviceRegisterRequest,
    _token: str = Depends(_verify_token),
) -> DeviceRegisterResponse:
    """Register an iOS/watchOS device token for push notifications."""
    device_id = f"dev_{body.platform}_{secrets.token_hex(6)}"
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _devices[device_id] = {
        "device_id": device_id,
        "device_token": body.device_token,
        "platform": body.platform,
        "device_name": body.device_name,
        "registered_at": now,
    }
    return DeviceRegisterResponse(
        device_id=device_id,
        platform=body.platform,
        registered=True,
        registered_at=now,
    )


@router.delete("/register/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unregister_device(
    device_id: str,
    _token: str = Depends(_verify_token),
) -> None:
    if device_id not in _devices:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    del _devices[device_id]


@router.get("/devices")
async def list_devices(_token: str = Depends(_verify_token)) -> dict[str, Any]:
    return {"devices": list(_devices.values()), "total": len(_devices)}


@router.post("/send", response_model=NotificationSendResponse)
async def send_notification(
    payload: NotificationPayload,
    _token: str = Depends(_verify_token),
) -> NotificationSendResponse:
    """Send a push notification to all registered devices."""
    if not _devices:
        return NotificationSendResponse(sent=False, provider=None, devices=0)

    provider = _detect_provider()
    if provider == "pusher":
        return await _send_pusher(payload)
    if provider == "onesignal":
        return await _send_onesignal(payload)

    log.info("[notifications] No provider configured — payload: title=%r body=%r", payload.title, payload.body)
    return NotificationSendResponse(sent=False, provider=None, devices=len(_devices))


def _detect_provider() -> Optional[str]:
    if os.getenv("PUSHER_INSTANCE_ID") and os.getenv("PUSHER_SECRET_KEY"):
        return "pusher"
    if os.getenv("ONESIGNAL_APP_ID") and os.getenv("ONESIGNAL_API_KEY"):
        return "onesignal"
    return None


async def _send_pusher(payload: NotificationPayload) -> NotificationSendResponse:
    instance_id = os.environ["PUSHER_INSTANCE_ID"]
    secret_key = os.environ["PUSHER_SECRET_KEY"]
    url = f"https://{instance_id}.pushnotifications.pusher.com/publish_api/v1/instances/{instance_id}/publishes/interests"
    body = {
        "interests": ["birkin-alerts"],
        "apns": {
            "aps": {
                "alert": {"title": payload.title, "body": payload.body},
                "category": payload.category,
            },
            "data": payload.data or {},
        },
    }
    async with httpx.AsyncClient() as client:
        r = await client.post(url, json=body, auth=(instance_id, secret_key), timeout=5)
        r.raise_for_status()
        resp = r.json()
    return NotificationSendResponse(
        sent=True,
        provider="pusher",
        devices=len(_devices),
        notification_id=resp.get("publishId"),
    )


async def _send_onesignal(payload: NotificationPayload) -> NotificationSendResponse:
    app_id = os.environ["ONESIGNAL_APP_ID"]
    api_key = os.environ["ONESIGNAL_API_KEY"]
    body = {
        "app_id": app_id,
        "included_segments": ["All"],
        "headings": {"en": payload.title},
        "contents": {"en": payload.body},
        "data": payload.data or {},
    }
    async with httpx.AsyncClient() as client:
        r = await client.post(
            "https://onesignal.com/api/v1/notifications",
            json=body,
            headers={"Authorization": f"Basic {api_key}"},
            timeout=5,
        )
        r.raise_for_status()
        resp = r.json()
    return NotificationSendResponse(
        sent=True,
        provider="onesignal",
        devices=len(_devices),
        notification_id=resp.get("id"),
    )


__all__ = ["router"]
