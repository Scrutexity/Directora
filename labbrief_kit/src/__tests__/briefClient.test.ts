/**
 * briefClient.test.ts — integration test scaffolds for the LabBrief
 * adapter against a mocked fetch. Place under `src/api/__tests__/` (or
 * wherever your Vitest config picks up tests).
 */
import { describe, it, expect, vi } from "vitest";
import { BriefClient, BriefApiError } from "../api/briefClient";

function mockFetch(
  responses: Array<{ status: number; headers?: Record<string, string>; body: unknown }>,
): typeof fetch {
  let i = 0;
  return vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => {
    const r = responses[i++];
    return new Response(JSON.stringify(r.body), {
      status: r.status,
      headers: {
        "content-type": "application/json",
        ...(r.headers || {}),
      },
    });
  }) as unknown as typeof fetch;
}

function makeClient(fetchImpl: typeof fetch) {
  return new BriefClient({
    baseUrl: "http://localhost:8000",
    token: "stub",
    clinicId: "CLN_TEST",
    fetchImpl,
    newRequestId: () => "req_test_1",
  });
}

describe("BriefClient", () => {
  it("sign happy path returns parsed SignBriefResponse", async () => {
    const fetchImpl = mockFetch([
      {
        status: 200,
        headers: { "X-Request-ID": "req_test_1" },
        body: {
          status: "signed",
          ledger_event_id: "evt_abc",
          signed_at: "2026-05-16T17:01:33.000Z",
          brief_content_hash: "a".repeat(64),
          binding_hash: "b".repeat(64),
          next_actions: {
            export: "/api/brief/provider?brief_id=BRF",
            audit: "/api/labs/audit?brief_id=BRF",
          },
        },
      },
    ]);
    const client = makeClient(fetchImpl);
    const res = await client.signBrief({
      briefId: "BRF",
      providerId: "PRV",
      signature: { method: "typed", value: "Dr Jane Doe", signed_at: "x" },
      client: { app: "labbrief", version: "1.0.0", session_id: "s" },
      idempotencyKey: "sign-BRF-attempt-1",
    });
    expect(res.status).toBe("signed");
    expect(res.ledger_event_id).toBe("evt_abc");
  });

  it("error path raises BriefApiError with code + request_id", async () => {
    const fetchImpl = mockFetch([
      {
        status: 404,
        headers: { "X-Request-ID": "req_test_1" },
        body: { error: "brief_not_found", request_id: "req_test_1" },
      },
    ]);
    const client = makeClient(fetchImpl);
    await expect(
      client.signBrief({
        briefId: "MISSING",
        providerId: "PRV",
        signature: { method: "typed", value: "Dr Jane Doe", signed_at: "x" },
        client: { app: "labbrief", version: "1.0.0", session_id: "s" },
        idempotencyKey: "sign-MISSING-attempt-1",
      }),
    ).rejects.toMatchObject({
      code: "brief_not_found",
      requestId: "req_test_1",
      status: 404,
    });
  });

  it("getPendingBriefs returns parsed PendingBriefResponse", async () => {
    const fetchImpl = mockFetch([
      {
        status: 200,
        body: { items: [], next_cursor: null },
      },
    ]);
    const client = makeClient(fetchImpl);
    const res = await client.getPendingBriefs({ providerId: "PRV_TEST" });
    expect(res.items).toEqual([]);
    expect(res.next_cursor).toBeNull();
  });

  it("passes the caller's idempotencyKey through verbatim", async () => {
    // Capture the headers from each call.
    const calls: Array<Record<string, string>> = [];
    const fetchImpl = vi.fn(async (_input: any, init?: RequestInit) => {
      calls.push((init?.headers as Record<string, string>) || {});
      return new Response(
        JSON.stringify({
          status: "signed",
          ledger_event_id: "evt_a",
          signed_at: "2026-05-16T17:01:33.000Z",
          brief_content_hash: "a".repeat(64),
          binding_hash: "b".repeat(64),
          next_actions: { export: "/x", audit: "/y" },
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    }) as unknown as typeof fetch;
    const client = makeClient(fetchImpl);

    const idempotencyKey = "sign-BRF-attempt-1";
    await client.signBrief({
      briefId: "BRF",
      providerId: "PRV",
      idempotencyKey,
      signature: { method: "typed", value: "Dr Jane Doe", signed_at: "x" },
      client: { app: "labbrief", version: "1.0.0", session_id: "s" },
    });
    await client.signBrief({
      briefId: "BRF",
      providerId: "PRV",
      idempotencyKey,
      signature: { method: "typed", value: "Dr Jane Doe", signed_at: "x" },
      client: { app: "labbrief", version: "1.0.0", session_id: "s" },
    });
    expect(calls[0]["Idempotency-Key"]).toBe(idempotencyKey);
    expect(calls[1]["Idempotency-Key"]).toBe(idempotencyKey);
  });

  it("throws if signBrief is called without an idempotencyKey", async () => {
    const fetchImpl = vi.fn() as unknown as typeof fetch;
    const client = makeClient(fetchImpl);
    await expect(
      client.signBrief({
        briefId: "BRF",
        providerId: "PRV",
        signature: { method: "typed", value: "x", signed_at: "y" },
        client: { app: "labbrief", version: "1.0.0", session_id: "s" },
      } as any),
    ).rejects.toThrow(/idempotencyKey/);
  });
});
