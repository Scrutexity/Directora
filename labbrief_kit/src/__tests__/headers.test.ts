import { describe, it, expect } from "vitest";

import {
  contractVersionMismatch,
  extractHeaders,
  parseRetryAfter,
} from "../api/headers";

function resWith(headers: Record<string, string>): Response {
  return new Response("{}", { status: 200, headers });
}

describe("extractHeaders", () => {
  it("captures all four v3.6+ headers", () => {
    const res = resWith({
      "X-Contract-Version": "3.7.0",
      "X-Idempotency-Replayed": "true",
      "X-Request-ID": "req_abc",
      "Retry-After": "5",
    });
    expect(extractHeaders(res)).toEqual({
      contractVersion: "3.7.0",
      idempotencyReplayed: true,
      requestId: "req_abc",
      retryAfterSeconds: 5,
    });
  });

  it("returns null fields when headers are absent", () => {
    const res = resWith({});
    const h = extractHeaders(res);
    expect(h.contractVersion).toBeNull();
    expect(h.idempotencyReplayed).toBe(false);
    expect(h.requestId).toBeNull();
    expect(h.retryAfterSeconds).toBeNull();
  });

  it("treats X-Idempotency-Replayed values other than 'true' as false", () => {
    expect(
      extractHeaders(resWith({ "X-Idempotency-Replayed": "1" })).idempotencyReplayed,
    ).toBe(false);
    expect(
      extractHeaders(resWith({ "X-Idempotency-Replayed": "" })).idempotencyReplayed,
    ).toBe(false);
  });
});

describe("parseRetryAfter", () => {
  it("parses seconds as integer", () => {
    expect(parseRetryAfter("1")).toBe(1);
    expect(parseRetryAfter("  30 ")).toBe(30);
  });

  it("parses HTTP-date defensively", () => {
    const future = new Date(Date.now() + 5000).toUTCString();
    const seconds = parseRetryAfter(future);
    // Allow a 1s slack for timer drift inside the test runner.
    expect(seconds).toBeGreaterThan(2);
    expect(seconds).toBeLessThan(10);
  });

  it("returns null for invalid input", () => {
    expect(parseRetryAfter("nonsense")).toBeNull();
  });
});

describe("contractVersionMismatch", () => {
  it("flags drift", () => {
    expect(
      contractVersionMismatch(
        {
          contractVersion: "3.7.1",
          idempotencyReplayed: false,
          requestId: null,
          retryAfterSeconds: null,
        },
        "3.7.0",
      ),
    ).toBe(true);
  });

  it("does not flag when versions match", () => {
    expect(
      contractVersionMismatch(
        {
          contractVersion: "3.7.0",
          idempotencyReplayed: false,
          requestId: null,
          retryAfterSeconds: null,
        },
        "3.7.0",
      ),
    ).toBe(false);
  });

  it("does not flag when either side is null", () => {
    expect(
      contractVersionMismatch(
        {
          contractVersion: null,
          idempotencyReplayed: false,
          requestId: null,
          retryAfterSeconds: null,
        },
        "3.7.0",
      ),
    ).toBe(false);
    expect(
      contractVersionMismatch(
        {
          contractVersion: "3.7.0",
          idempotencyReplayed: false,
          requestId: null,
          retryAfterSeconds: null,
        },
        null,
      ),
    ).toBe(false);
  });
});
