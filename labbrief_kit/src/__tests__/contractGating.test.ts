/**
 * Contract-version gating tests for BriefClient.
 *
 * Verifies the three rules from Add-on A:
 *   1. No `expectedContractVersion` → no callback fires.
 *   2. Matching version → no callback.
 *   3. Mismatch / missing header → callback receives the event with
 *      `expected`, `actual`, `requestId`, `bodyRaw`, `headers`, `path`,
 *      AND `console.warn` was called.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  BriefApiError,
  BriefClient,
  type ContractMismatchEvent,
} from "../api/briefClient";

function mockOkPending(headers: Record<string, string>): typeof fetch {
  return vi.fn(async () =>
    new Response(
      JSON.stringify({ items: [], next_cursor: null }),
      { status: 200, headers: { "content-type": "application/json", ...headers } },
    ),
  ) as unknown as typeof fetch;
}

describe("contract version gating", () => {
  let warnSpy: ReturnType<typeof vi.spyOn>;
  let events: ContractMismatchEvent[];

  beforeEach(() => {
    events = [];
    warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
  });
  afterEach(() => {
    warnSpy.mockRestore();
  });

  it("fires no callback when expectedContractVersion is unset", async () => {
    const client = new BriefClient({
      token: "t",
      clinicId: "C",
      fetchImpl: mockOkPending({ "X-Contract-Version": "9.9.9" }),
      onContractMismatch: (e) => events.push(e),
    });
    await client.getPendingBriefs();
    expect(events).toEqual([]);
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("fires no callback when the header matches", async () => {
    const client = new BriefClient({
      token: "t",
      clinicId: "C",
      fetchImpl: mockOkPending({ "X-Contract-Version": "3.7.0" }),
      expectedContractVersion: "3.7.0",
      onContractMismatch: (e) => events.push(e),
    });
    await client.getPendingBriefs();
    expect(events).toEqual([]);
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("fires the callback when the header differs", async () => {
    const client = new BriefClient({
      token: "t",
      clinicId: "C",
      fetchImpl: mockOkPending({
        "X-Contract-Version": "9.9.9",
        "X-Request-ID": "req_abc",
      }),
      expectedContractVersion: "3.7.0",
      onContractMismatch: (e) => events.push(e),
    });
    await client.getPendingBriefs();
    expect(events).toHaveLength(1);
    expect(events[0]).toMatchObject({
      expected: "3.7.0",
      actual: "9.9.9",
      requestId: "req_abc",
      path: "/api/brief/pending",
    });
    // The raw body is preserved.
    expect(events[0].bodyRaw).toContain("items");
    expect(events[0].headers["x-contract-version"]).toBe("9.9.9");
    // console.warn was called once with the mismatch.
    expect(warnSpy).toHaveBeenCalled();
  });

  it("fires the callback when the header is missing", async () => {
    const client = new BriefClient({
      token: "t",
      clinicId: "C",
      fetchImpl: mockOkPending({ "X-Request-ID": "req_xyz" }),
      expectedContractVersion: "3.7.0",
      onContractMismatch: (e) => events.push(e),
    });
    await client.getPendingBriefs();
    expect(events).toHaveLength(1);
    expect(events[0].actual).toBeNull();
  });

  it("never throws or short-circuits the request on mismatch", async () => {
    const client = new BriefClient({
      token: "t",
      clinicId: "C",
      fetchImpl: mockOkPending({ "X-Contract-Version": "9.9.9" }),
      expectedContractVersion: "3.7.0",
    });
    // Even with no callback set, the request must succeed.
    const res = await client.getPendingBriefs();
    expect(res.items).toEqual([]);
  });

  it("does not crash the request when the callback throws", async () => {
    const client = new BriefClient({
      token: "t",
      clinicId: "C",
      fetchImpl: mockOkPending({ "X-Contract-Version": "9.9.9" }),
      expectedContractVersion: "3.7.0",
      onContractMismatch: () => {
        throw new Error("listener bug");
      },
    });
    const res = await client.getPendingBriefs();
    expect(res.items).toEqual([]);
  });
});
