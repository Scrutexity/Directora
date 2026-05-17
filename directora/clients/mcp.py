"""Lightweight MCP client surface used by the Quality Render Step.

In production this module is expected to be the real MCP wrapper. Here
we ship a minimal stand-in so the v3.1 add-on imports cleanly even when
no MCP server is configured. The add-on always catches MCPError and
falls back to the legacy HappyHorse renderer, so the stub raising on
every call is a safe default.
"""
from __future__ import annotations

import os
from typing import Any


class MCPError(Exception):
    """Raised when an MCP call fails or no MCP server is configured."""


class MCPClient:
    """Stub client. Real implementations should override `call`."""

    def call(
        self,
        server: str,
        tool: str,
        params: dict,
        timeout_s: float | None = None,
    ) -> dict[str, Any]:
        if os.getenv("DIRECTORA_MCP_FAKE") == "1":
            return {
                "video_url": "https://example.invalid/fake.mp4",
                "frames": [],
                "duration_s": 0.0,
            }
        raise MCPError(
            f"No MCP server configured (asked for {server}.{tool}). "
            "Falling back to the Fallback Render Draft."
        )
