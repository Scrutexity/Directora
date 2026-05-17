/**
 * signBriefWithRetry tests — verifies the v3.6+ retry policy.
 */
import { describe, it, expect, vi } from "vitest";

import { BriefApiError, BriefClient } from "../api/briefClient";
import {
  BACKOFF_SCHEDULE_MS,
  BACKOFF_JITTER_PCT,
  MaxRetriesExceededError,
  NEVER_RETRY_STATUSES,
  RETRYABLE_STATUSES,
  applyJitter,
  scheduledBackoffMs,
  signBriefWithRetry,
} from "../api/retry";

function mockFetch(
  responses: Array<{
    status: number;
    headers?: Record<string, string>;
    body: unknown;
  }>,
): typeof fetch {
  let i = 0;
  return vi.fn(async () => {
    const r = responses[i++];
    return new Response(JSON.stringify(r.body), {
      status: r.status,
      headers: { "content-type": "application/json", ...(r.headers || {}) },
    });
  }) as unknown as typeof fetch;
}

function makeClient(fetchImpl: typeof fetch) {
  return new BriefClient({
    baseUrl: "http://localhost:8000",
    token: "stub",
    clinicId: "CLN_TEST",
    fetchImpl,
    newRequestId: () => "req_test",
  });
}

const signOptsBase = {
  briefId: "BRF_TEST",
  providerId: "PRV",
  signature: {
    method: "typed" as const,
    value: "Dr Jane Doe",
    signed_at: "2026-05-16T17:01:33Z",
  },
  client: { app: "labbrief", version: "1.0.0", session_id: "s" },
  // The store layer owns key generation. The retry layer just
  // passes the value through — same key across every retry of the
  // same attempt.
  idempotencyKey: "sign-BRF_TEST-attempt-fixed",
};

const okBody = {
  status: "signed" as const,
  ledger_event_id: "evt_a",
  signed_at: "2026-05-16T17:01:33Z",
  brief_content_hash: "a".repeat(64),
  binding_hash: "b".repeat(64),
  next_actions: { export: "/x", audit: "/y" },
};

describe("signBriefWithRetry — never retries", () => {
  it.each([400, 401, 403, 404, 409, 422])(
    "throws BriefApiError without retry on status %s",
    async (status) => {
      const fetchImpl = mockFetch([
        { status, body: { error: "x", request_id: "req_test" } },
      ]);
      const client = makeClient(fetchImpl);
      await expect(
        signBriefWithRetry(client, { ...signOptsBase, maxRetries: 3 }),
      ).rejects.toBeInstanceOf(BriefApiError);
      // Exactly one call — no retries.
      expect((fetchImpl as unknown as { mock: { calls: unknown[] } }).mock.calls).toHaveLength(1);
    },
  );
});

describe("signBriefWithRetry — 503 with Retry-After", () => {
  it("retries with the same idempotency key and respects Retry-After", async () => {
    const headerLog: string[] = [];
    const fetchImpl = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      headerLog.push(
        ((init?.headers as Record<string, string>) || {})["Idempotency-Key"] ?? "",
      );
      if (headerLog.length === 1) {
        return new Response(
          JSON.stringify({
            error: "idempotency_store_busy",
            request_id: "req_test",
          }),
          {
            status: 503,
            headers: { "content-type": "application/json", "Retry-After": "1" },
          },
        );
      }
      return new Response(JSON.stringify(okBody), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }) as unknown as typeof fetch;

    const client = makeClient(fetchImpl);
    const res = await signBriefWithRetry(client, {
      ...signOptsBase,
      maxRetries: 3,
      backoffScheduleMs: [1, 1, 1], // keep tests fast
      jitterPct: 0,
    });
    expect(res.status).toBe("signed");
    // Both attempts used the SAME Idempotency-Key.
    expect(headerLog).toEqual([
      "sign-BRF_TEST-attempt-fixed",
      "sign-BRF_TEST-attempt-fixed",
    ]);
  });

  it("gives up after maxRetries on persistent 503 and surfaces request_id", async () => {
    const fetchImpl = mockFetch(
      Array.from({ length: 5 }).map(() => ({
        status: 503,
        headers: { "Retry-After": "1" },
        body: { error: "idempotency_store_busy", request_id: "req_terminal" },
      })),
    );
    const client = makeClient(fetchImpl);
    try {
      await signBriefWithRetry(client, {
        ...signOptsBase,
        maxRetries: 2, // 1 initial + 2 retries = 3 calls
        backoffScheduleMs: [1, 1, 1],
        jitterPct: 0,
      });
      throw new Error("should have thrown");
    } catch (err) {
      // Persistent 503 surfaces the final BriefApiError to the caller.
      expect(err).toBeInstanceOf(BriefApiError);
      expect((err as BriefApiError).requestId).toBe("req_terminal");
      expect((err as BriefApiError).status).toBe(503);
    }
    expect(
      (fetchImpl as unknown as { mock: { calls: unknown[] } }).mock.calls,
    ).toHaveLength(3);
  });
});

describe("signBriefWithRetry — soft 5xx retry", () => {
  it("retries engine_or_ledger_failure up to maxRetries", async () => {
    const fetchImpl = mockFetch([
      { status: 500, body: { error: "engine_or_ledger_failure", request_id: "r" } },
      { status: 200, body: okBody },
    ]);
    const client = makeClient(fetchImpl);
    const res = await signBriefWithRetry(client, {
      ...signOptsBase,
      maxRetries: 3,
      backoffScheduleMs: [1],
      jitterPct: 0,
    });
    expect(res.status).toBe("signed");
  });

  it("does not retry soft 5xx when disabled", async () => {
    const fetchImpl = mockFetch([
      { status: 500, body: { error: "engine_or_ledger_failure", request_id: "r" } },
      { status: 200, body: okBody },
    ]);
    const client = makeClient(fetchImpl);
    await expect(
      signBriefWithRetry(client, {
        ...signOptsBase,
        maxRetries: 3,
        backoffScheduleMs: [1],
        jitterPct: 0,
        retryOnSoftErrors: false,
      }),
    ).rejects.toBeInstanceOf(BriefApiError);
    expect(
      (fetchImpl as unknown as { mock: { calls: unknown[] } }).mock.calls,
    ).toHaveLength(1);
  });
});

describe("signBriefWithRetry — network failure", () => {
  it("retries when fetch itself throws", async () => {
    let calls = 0;
    const fetchImpl = vi.fn(async () => {
      calls += 1;
      if (calls === 1) throw new TypeError("Failed to fetch");
      return new Response(JSON.stringify(okBody), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }) as unknown as typeof fetch;
    const client = makeClient(fetchImpl);
    const res = await signBriefWithRetry(client, {
      ...signOptsBase,
      maxRetries: 2,
      backoffScheduleMs: [1],
      jitterPct: 0,
    });
    expect(res.status).toBe("signed");
  });

  it("wraps repeated network failure as MaxRetriesExceededError", async () => {
    const fetchImpl = vi.fn(async () => {
      throw new TypeError("Failed to fetch");
    }) as unknown as typeof fetch;
    const client = makeClient(fetchImpl);
    await expect(
      signBriefWithRetry(client, {
        ...signOptsBase,
        maxRetries: 1,
        backoffScheduleMs: [1],
        jitterPct: 0,
      }),
    ).rejects.toBeInstanceOf(MaxRetriesExceededError);
  });
});

describe("signBriefWithRetry — onAttempt hook", () => {
  it("emits attempt info for success, retry, and give_up", async () => {
    const fetchImpl = mockFetch([
      {
        status: 503,
        headers: { "Retry-After": "1" },
        body: { error: "idempotency_store_busy", request_id: "r" },
      },
      { status: 200, body: okBody },
    ]);
    const events: string[] = [];
    const client = makeClient(fetchImpl);
    await signBriefWithRetry(client, {
      ...signOptsBase,
      maxRetries: 2,
      backoffScheduleMs: [1],
      jitterPct: 0,
      onAttempt: (info) => events.push(`${info.outcome}:${info.attempt}`),
    });
    expect(events).toEqual(["retry:1", "success:2"]);
  });
});

describe("constants", () => {
  it("never retries 409", () => {
    expect(NEVER_RETRY_STATUSES.has(409)).toBe(true);
    expect(RETRYABLE_STATUSES.has(409)).toBe(false);
  });
  it("retries 503", () => {
    expect(RETRYABLE_STATUSES.has(503)).toBe(true);
    expect(NEVER_RETRY_STATUSES.has(503)).toBe(false);
  });
  it("default schedule is 250 / 500 / 1000 ms", () => {
    expect([...BACKOFF_SCHEDULE_MS]).toEqual([250, 500, 1000]);
  });
  it("default jitter is ±15 %", () => {
    expect(BACKOFF_JITTER_PCT).toBeCloseTo(0.15);
  });
});

describe("jitter and schedule helpers", () => {
  it("applyJitter stays within ±jitterPct of the base", () => {
    const samples = Array.from({ length: 50 }, () => applyJitter(1000, 0.15));
    for (const s of samples) {
      expect(s).toBeGreaterThanOrEqual(850);
      expect(s).toBeLessThanOrEqual(1150);
    }
  });

  it("applyJitter with 0 pct returns the floored base", () => {
    expect(applyJitter(123.7, 0)).toBe(123);
  });

  it("scheduledBackoffMs walks the schedule and clamps past the tail", () => {
    expect(scheduledBackoffMs(1, [100, 200, 300], 0)).toBe(100);
    expect(scheduledBackoffMs(2, [100, 200, 300], 0)).toBe(200);
    expect(scheduledBackoffMs(3, [100, 200, 300], 0)).toBe(300);
    // beyond the schedule the last entry is reused
    expect(scheduledBackoffMs(99, [100, 200, 300], 0)).toBe(300);
  });
});

describe("auditor-grade — key reuse across multiple retries", () => {
  it("uses the SAME Idempotency-Key on attempt 1, 2, and 3 (two 503s, then 200)", async () => {
    // Capture every Idempotency-Key the client actually sent.
    const idempotencyHeaderLog: string[] = [];
    let callIndex = 0;
    const fetchImpl = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      callIndex += 1;
      idempotencyHeaderLog.push(
        ((init?.headers as Record<string, string>) || {})["Idempotency-Key"]
          ?? "",
      );
      if (callIndex <= 2) {
        // Two 503s before success.
        return new Response(
          JSON.stringify({
            error: "idempotency_store_busy",
            request_id: `req-busy-${callIndex}`,
          }),
          {
            status: 503,
            headers: {
              "content-type": "application/json",
              "Retry-After": "1",
            },
          },
        );
      }
      return new Response(JSON.stringify(okBody), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }) as unknown as typeof fetch;

    const client = makeClient(fetchImpl);
    const fixedKey = "sign-BRF_TEST-attempt-fixed";  // store-owned
    const res = await signBriefWithRetry(client, {
      ...signOptsBase,
      idempotencyKey: fixedKey,
      maxRetries: 3,
      backoffScheduleMs: [1, 1, 1],
      jitterPct: 0,
    });
    expect(res.status).toBe("signed");
    expect(idempotencyHeaderLog).toHaveLength(3);
    // Every attempt used the same key — never regenerated.
    expect(new Set(idempotencyHeaderLog).size).toBe(1);
    expect(idempotencyHeaderLog[0]).toBe(fixedKey);
    expect(idempotencyHeaderLog[1]).toBe(fixedKey);
    expect(idempotencyHeaderLog[2]).toBe(fixedKey);
  });
});

describe("MaxRetriesExceededError carries requestId", () => {
  it("surfaces the request_id of the final attempt", async () => {
    const fetchImpl = vi.fn(async () => {
      throw new TypeError("Failed to fetch");
    }) as unknown as typeof fetch;
    const client = makeClient(fetchImpl);
    try {
      await signBriefWithRetry(client, {
        ...signOptsBase,
        maxRetries: 0,
        backoffScheduleMs: [1],
        jitterPct: 0,
      });
      throw new Error("should have thrown");
    } catch (err) {
      expect(err).toBeInstanceOf(MaxRetriesExceededError);
      // Network failure: no requestId from the server.
      expect((err as MaxRetriesExceededError).requestId).toBeNull();
    }
  });
});
