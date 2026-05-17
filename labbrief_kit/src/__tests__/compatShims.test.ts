/**
 * Tests for the optional compat shims.
 *
 * `signWithRetry` and `handleAuthError` exist so docs using the
 * original spec wording continue to compile. The aliases delegate
 * to the canonical helpers verbatim.
 */
import { describe, expect, it, vi } from "vitest";

import { BriefClient, BriefApiError } from "../api/briefClient";
import { signWithRetry, handleAuthError } from "../api/compatShims";

function mockFetch(body: unknown, status = 200): typeof fetch {
  return vi.fn(async () =>
    new Response(JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    }),
  ) as unknown as typeof fetch;
}

const okBody = {
  status: "signed",
  ledger_event_id: "evt_a",
  signed_at: "2026-05-16T17:01:33Z",
  brief_content_hash: "a".repeat(64),
  binding_hash: "b".repeat(64),
  next_actions: { export: "/x", audit: "/y" },
};

describe("signWithRetry alias", () => {
  it("delegates to signBriefWithRetry", async () => {
    const fetchImpl = mockFetch(okBody);
    const client = new BriefClient({
      token: "stub", clinicId: "CLN_TEST", fetchImpl,
    });
    const res = await signWithRetry(client, {
      briefId: "BRF",
      providerId: "PRV",
      idempotencyKey: "sign-BRF-shim-1",
      signature: { method: "typed", value: "x", signed_at: "y" },
      client: { app: "labbrief", version: "1.0.0", session_id: "s" },
      backoffScheduleMs: [1],
      jitterPct: 0,
    });
    expect(res.status).toBe("signed");
  });
});

describe("handleAuthError shim", () => {
  it("returns the plain-language message for a known code", () => {
    const err = new BriefApiError({
      status: 401, code: "token_expired", requestId: null,
    });
    expect(handleAuthError(err)).toBe(
      "Your session has expired. Please log in again.",
    );
  });

  it("falls back to a generic message for an unknown code", () => {
    expect(handleAuthError({ status: 999, code: "weird" })).toMatch(
      /unexpected error/i,
    );
  });

  it("falls back to a 401 generic message when code is missing", () => {
    expect(handleAuthError({ status: 401 })).toBe(
      "Authentication failed. Please log in again.",
    );
  });
});
