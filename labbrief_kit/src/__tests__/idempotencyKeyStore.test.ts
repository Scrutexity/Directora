/**
 * Idempotency key store tests.
 *
 * Verifies:
 *   * get-or-create returns the SAME key for the same (provider, brief)
 *     until cleared
 *   * different (provider, brief) pairs get distinct keys
 *   * key format is `sign-{briefId}-{uuid}`
 *   * shouldClearKeyForOutcome enforces the spec lifecycle
 *   * pluggable backend works (e.g. sessionStorage simulation)
 */
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  clearIdempotencyKey,
  getOrCreateIdempotencyKey,
  resetIdempotencyStore,
  setIdempotencyKeyBackend,
  shouldClearKeyForOutcome,
  withIdempotencyKey,
  type IdempotencyKeyBackend,
} from "../api/idempotencyStore";

beforeEach(() => {
  resetIdempotencyStore();
});
afterEach(() => {
  resetIdempotencyStore();
});

describe("getOrCreateIdempotencyKey", () => {
  it("returns the same key on repeated calls for the same (provider, brief)", () => {
    const a = getOrCreateIdempotencyKey("PRV", "BRF");
    const b = getOrCreateIdempotencyKey("PRV", "BRF");
    expect(a).toBe(b);
  });

  it("returns different keys for different (provider, brief) pairs", () => {
    const a = getOrCreateIdempotencyKey("PRV", "BRF_1");
    const b = getOrCreateIdempotencyKey("PRV", "BRF_2");
    const c = getOrCreateIdempotencyKey("OTHER", "BRF_1");
    expect(a).not.toBe(b);
    expect(a).not.toBe(c);
  });

  it("uses the conventional sign-{briefId}-{uuid} format", () => {
    const key = getOrCreateIdempotencyKey("PRV", "BRF_X");
    expect(key.startsWith("sign-BRF_X-")).toBe(true);
    // UUIDv4 has 4 dashes; total of 5 dashes after the prefix.
    expect(key.split("-").length).toBeGreaterThanOrEqual(6);
  });
});

describe("clearIdempotencyKey", () => {
  it("removes the key so the next get-or-create produces a fresh one", () => {
    const first = getOrCreateIdempotencyKey("PRV", "BRF");
    clearIdempotencyKey("PRV", "BRF");
    const second = getOrCreateIdempotencyKey("PRV", "BRF");
    expect(second).not.toBe(first);
  });

  it("is a no-op for unknown keys", () => {
    // Should not throw.
    clearIdempotencyKey("UNKNOWN", "UNKNOWN");
  });
});

describe("shouldClearKeyForOutcome", () => {
  it("clears on success", () => {
    expect(shouldClearKeyForOutcome({ success: true })).toBe(true);
  });

  it("clears on terminal 409 codes per spec", () => {
    for (const code of ["already_signed", "invalid_status", "idempotency_conflict"]) {
      expect(
        shouldClearKeyForOutcome({ status: 409, code }),
      ).toBe(true);
    }
  });

  it("keeps the key on 503 idempotency_store_busy", () => {
    expect(
      shouldClearKeyForOutcome({
        status: 503, code: "idempotency_store_busy",
      }),
    ).toBe(false);
  });

  it("keeps the key on 429", () => {
    expect(shouldClearKeyForOutcome({ status: 429 })).toBe(false);
  });

  it("keeps the key on network timeout (no status)", () => {
    expect(shouldClearKeyForOutcome({ status: null, code: "network_error" })).toBe(false);
    expect(shouldClearKeyForOutcome({})).toBe(false);
  });

  it("clears when MaxRetriesExceededError is signalled", () => {
    expect(shouldClearKeyForOutcome({ maxRetriesExceeded: true })).toBe(true);
  });

  it("clears on terminal 4xx / 5xx errors that aren't transient", () => {
    expect(shouldClearKeyForOutcome({ status: 401, code: "token_expired" })).toBe(true);
    expect(shouldClearKeyForOutcome({ status: 403, code: "permission_denied" })).toBe(true);
    expect(shouldClearKeyForOutcome({ status: 404, code: "brief_not_found" })).toBe(true);
    expect(shouldClearKeyForOutcome({ status: 422, code: "invalid_signature" })).toBe(true);
    expect(
      shouldClearKeyForOutcome({ status: 500, code: "engine_or_ledger_failure" }),
    ).toBe(true);
  });
});

describe("withIdempotencyKey convenience wrapper", () => {
  it("provides the key, awaits the body, then clears on success", async () => {
    let observed = "";
    const result = await withIdempotencyKey("PRV", "BRF", async (key) => {
      observed = key;
      return 42;
    });
    expect(observed).toMatch(/^sign-BRF-/);
    expect(result).toBe(42);
    // After success the key is cleared; next call generates a new one.
    const next = getOrCreateIdempotencyKey("PRV", "BRF");
    expect(next).not.toBe(observed);
  });
});

describe("auditor-grade — store does not clear on retryable outcomes", () => {
  it("503 idempotency_store_busy keeps the key (next get returns same value)", () => {
    const first = getOrCreateIdempotencyKey("PRV", "BRF");

    // Policy: must NOT clear on 503.
    const decision = shouldClearKeyForOutcome({
      status: 503, code: "idempotency_store_busy",
    });
    expect(decision).toBe(false);

    // The store still has the same key. A second get-or-create on the
    // same (provider, brief) MUST return the same value — proves the
    // retry layer can reuse it on the next attempt.
    const second = getOrCreateIdempotencyKey("PRV", "BRF");
    expect(second).toBe(first);
  });

  it("429 rate limit keeps the key", () => {
    const first = getOrCreateIdempotencyKey("PRV", "BRF_429");
    expect(shouldClearKeyForOutcome({ status: 429 })).toBe(false);
    expect(getOrCreateIdempotencyKey("PRV", "BRF_429")).toBe(first);
  });

  it("network timeout (no status) keeps the key", () => {
    const first = getOrCreateIdempotencyKey("PRV", "BRF_TIMEOUT");
    expect(shouldClearKeyForOutcome({ status: null })).toBe(false);
    expect(shouldClearKeyForOutcome({})).toBe(false);
    expect(getOrCreateIdempotencyKey("PRV", "BRF_TIMEOUT")).toBe(first);
  });

  it("simulates a real retry flow: 503 → keep → retry uses same key → 200 → clear", () => {
    // Setup: caller starts a sign attempt.
    const initial = getOrCreateIdempotencyKey("PRV", "BRF_FLOW");

    // First HTTP attempt returns 503 (transient SQLite busy).
    if (
      shouldClearKeyForOutcome({
        status: 503, code: "idempotency_store_busy",
      })
    ) {
      clearIdempotencyKey("PRV", "BRF_FLOW");
    }
    // Retry layer fires the next attempt — pulls the SAME key.
    const onRetry = getOrCreateIdempotencyKey("PRV", "BRF_FLOW");
    expect(onRetry).toBe(initial);

    // Second HTTP attempt returns 200 (success).
    if (shouldClearKeyForOutcome({ success: true })) {
      clearIdempotencyKey("PRV", "BRF_FLOW");
    }

    // A FRESH user click after success generates a NEW key.
    const next = getOrCreateIdempotencyKey("PRV", "BRF_FLOW");
    expect(next).not.toBe(initial);
  });
});

describe("pluggable backend", () => {
  it("delegates to the injected backend", () => {
    const log: string[] = [];
    const fake: IdempotencyKeyBackend = {
      get: (k) => (log.push(`get ${k}`), undefined),
      set: (k, v) => log.push(`set ${k}=${v}`),
      delete: (k) => log.push(`delete ${k}`),
    };
    setIdempotencyKeyBackend(fake);
    const key = getOrCreateIdempotencyKey("PRV", "BRF");
    clearIdempotencyKey("PRV", "BRF");
    expect(log[0]).toBe("get PRV:BRF");
    expect(log[1]).toMatch(/^set PRV:BRF=sign-BRF-/);
    expect(log[2]).toBe("delete PRV:BRF");
    expect(key).toMatch(/^sign-BRF-/);
  });
});
