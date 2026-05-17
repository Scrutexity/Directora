/**
 * briefClient.ts — fetch-based adapter for the Directora Brief API (v3.5).
 *
 * Drop into LabBrief at `src/api/briefClient.ts`. The four functions
 * exposed here mirror the four endpoints. Every function:
 *   1. Sends the required headers (Authorization, X-Clinic-ID, X-Request-ID)
 *   2. Generates a per-attempt UUIDv4 Idempotency-Key on POST /sign
 *   3. Validates the response with Zod (single source of truth)
 *   4. Surfaces typed errors via the `BriefApiError` class with request_id
 *
 * No state mutations happen client-side until the server returns 200.
 * The Zustand store should update only from the parsed response object.
 */

import {
  PendingBriefResponseSchema,
  SignBriefResponseSchema,
  AuditResponseSchema,
  ProviderBriefResponseSchema,
  ErrorResponseSchema,
} from "../schemas/contract";

import type {
  PendingBriefResponse,
  SignBriefResponse,
  AuditResponse,
  ProviderBriefResponse,
  SignatureBlock,
  ClientBlock,
  BriefApiErrorCode,
  ErrorResponse,
} from "../types/contract";

const DEFAULT_BASE =
  (typeof import.meta !== "undefined" &&
    (import.meta as any).env?.VITE_BRIEF_API_BASE) ||
  "http://localhost:8000";

/**
 * Contract-version mismatch report passed to `onContractMismatch`.
 *
 * Fired whenever a response's `X-Contract-Version` is either missing
 * or differs from `expectedContractVersion`. The client still parses
 * the body so the in-flight request can complete; the callback is
 * for surfacing the drift loudly.
 */
export interface ContractMismatchEvent {
  expected: string;
  actual: string | null;
  requestId: string | null;
  /** Stringified response body for the offending response. */
  bodyRaw: string;
  /** Snapshot of every response header (lower-cased keys). */
  headers: Record<string, string>;
  /** URL path that returned the mismatched response. */
  path: string;
}

export interface BriefClientOptions {
  baseUrl?: string;
  token: string;             // Bearer token (stub-encoded in dev)
  clinicId: string;          // X-Clinic-ID
  newRequestId?: () => string;
  fetchImpl?: typeof fetch;  // injectable for tests
  /**
   * Snapshot version the Zod schemas in this kit were compiled
   * against. When set, every response's `X-Contract-Version` header
   * is compared. Mismatches fire `onContractMismatch` AND
   * `console.warn` the full body + headers (dev visibility).
   *
   * Leave undefined to disable the check (production might do this
   * if it does its own header validation upstream).
   */
  expectedContractVersion?: string;
  /**
   * Callback invoked when a response's contract version differs from
   * `expectedContractVersion` (or is absent). Useful for surfacing a
   * top-level banner in dev.
   */
  onContractMismatch?: (event: ContractMismatchEvent) => void;
}

export class BriefApiError extends Error {
  status: number;
  code: BriefApiErrorCode | string;
  requestId: string | null;
  ledgerEventId: string | null;
  detail: string | null;
  retryAfterSeconds: number | null;

  constructor(opts: {
    status: number;
    code: BriefApiErrorCode | string;
    requestId: string | null;
    ledgerEventId?: string | null;
    detail?: string | null;
    retryAfterSeconds?: number | null;
  }) {
    super(`BriefApiError(${opts.code})`);
    this.status = opts.status;
    this.code = opts.code;
    this.requestId = opts.requestId;
    this.ledgerEventId = opts.ledgerEventId ?? null;
    this.detail = opts.detail ?? null;
    this.retryAfterSeconds = opts.retryAfterSeconds ?? null;
  }
}

function tryParseJson(text: string): unknown {
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

function uuidv4(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  // Fallback for environments without crypto.randomUUID
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

export class BriefClient {
  private baseUrl: string;
  private token: string;
  private clinicId: string;
  private newRequestId: () => string;
  private fetchImpl: typeof fetch;
  private expectedContractVersion: string | undefined;
  private onContractMismatch: ((event: ContractMismatchEvent) => void) | undefined;

  constructor(opts: BriefClientOptions) {
    this.baseUrl = (opts.baseUrl || DEFAULT_BASE).replace(/\/+$/, "");
    this.token = opts.token;
    this.clinicId = opts.clinicId;
    this.newRequestId = opts.newRequestId || (() => `req_${uuidv4()}`);
    this.fetchImpl = opts.fetchImpl || fetch;
    this.expectedContractVersion = opts.expectedContractVersion;
    this.onContractMismatch = opts.onContractMismatch;
  }

  private async readBodyWithContractCheck<T>(
    res: Response,
    schema: { parse(input: unknown): T },
    path: string,
  ): Promise<T> {
    const text = await res.text();
    this.inspectContractVersion(res, text, path);
    const parsedBody = text ? JSON.parse(text) : {};
    return schema.parse(parsedBody);
  }

  private inspectContractVersion(
    res: Response,
    bodyRaw: string,
    path: string,
  ): void {
    const expected = this.expectedContractVersion;
    if (!expected) return;
    const actual = res.headers.get("X-Contract-Version");
    if (actual === expected) return;
    // Drift detected. Build the event and fire the callback. We also
    // log loudly so engineers see the mismatch even without wiring a
    // handler (`onContractMismatch` is optional).
    const headers: Record<string, string> = {};
    res.headers.forEach((value, key) => {
      headers[key.toLowerCase()] = value;
    });
    const event: ContractMismatchEvent = {
      expected,
      actual,
      requestId: res.headers.get("X-Request-ID"),
      bodyRaw,
      headers,
      path,
    };
    try {
      if (typeof console !== "undefined" && console.warn) {
        console.warn(
          "[BriefClient] X-Contract-Version mismatch",
          {
            path,
            expected,
            actual,
            requestId: event.requestId,
            headers,
            body: tryParseJson(bodyRaw),
          },
        );
      }
    } catch {
      // never crash the request on logging failure
    }
    try {
      this.onContractMismatch?.(event);
    } catch {
      // never crash the request on callback failure
    }
  }

  private baseHeaders(): Record<string, string> {
    return {
      Authorization: `Bearer ${this.token}`,
      "X-Clinic-ID": this.clinicId,
      "X-Request-ID": this.newRequestId(),
    };
  }

  private async parseErrorResponse(
    res: Response,
  ): Promise<BriefApiError> {
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      body = {};
    }
    const parsed = ErrorResponseSchema.safeParse(body);
    const errObj: ErrorResponse = parsed.success
      ? parsed.data
      : { error: `http_${res.status}`, request_id: res.headers.get("X-Request-ID") };
    // Capture Retry-After so the retry layer doesn't have to re-read the
    // raw response. Directora emits this header on 503; LabBrief may also
    // see it from a future 429 once we wire rate limiting.
    const retryAfterRaw = res.headers.get("Retry-After");
    let retryAfterSeconds: number | null = null;
    if (retryAfterRaw) {
      if (/^\d+$/.test(retryAfterRaw.trim())) {
        retryAfterSeconds = Number(retryAfterRaw.trim());
      } else {
        const ts = Date.parse(retryAfterRaw);
        if (!Number.isNaN(ts)) {
          retryAfterSeconds = Math.max(0, Math.ceil((ts - Date.now()) / 1000));
        }
      }
    }
    return new BriefApiError({
      status: res.status,
      code: errObj.error,
      requestId: errObj.request_id ?? res.headers.get("X-Request-ID"),
      ledgerEventId: errObj.ledger_event_id ?? null,
      detail: errObj.detail ?? null,
      retryAfterSeconds,
    });
  }

  // ------------- GET /api/brief/pending --------------------------

  async getPendingBriefs(params?: {
    providerId?: string;
    status?: "pending";
    limit?: number;
    cursor?: string;
  }): Promise<PendingBriefResponse> {
    const url = new URL(`${this.baseUrl}/api/brief/pending`);
    if (params?.providerId) url.searchParams.set("provider_id", params.providerId);
    url.searchParams.set("status", params?.status || "pending");
    if (params?.limit) url.searchParams.set("limit", String(params.limit));
    if (params?.cursor) url.searchParams.set("cursor", params.cursor);

    const res = await this.fetchImpl(url.toString(), {
      method: "GET",
      headers: this.baseHeaders(),
    });
    if (!res.ok) throw await this.parseErrorResponse(res);
    return this.readBodyWithContractCheck(
      res, PendingBriefResponseSchema, "/api/brief/pending",
    );
  }

  // ------------- POST /api/brief/sign ----------------------------

  /**
   * Sign a brief.
   *
   * The caller MUST pass an `idempotencyKey`. The Brief API will use
   * this exact value as the `Idempotency-Key` request header. The
   * store layer owns key generation and lifecycle — see
   * `src/api/idempotencyStore.ts`.
   *
   * briefClient deliberately does NOT generate keys internally.
   * Generating here would scatter ownership across the codebase and
   * make it impossible to persist a key across the retry → success
   * boundary safely.
   */
  async signBrief(args: {
    briefId: string;
    providerId: string;
    signature: SignatureBlock;
    client: ClientBlock;
    /**
     * Full Idempotency-Key value, generated by the store layer for the
     * current intent-to-sign. Reuse the SAME value across retries of
     * the same attempt. The convention is `sign-{briefId}-{uuidv4}`.
     */
    idempotencyKey: string;
    engineRunId?: string;
    authorityBriefVersion?: string;
    providerBriefVersion?: string;
  }): Promise<SignBriefResponse> {
    if (!args.idempotencyKey) {
      throw new Error(
        "BriefClient.signBrief requires an idempotencyKey. " +
          "Generate one per intent-to-sign in your store layer " +
          "(see src/api/idempotencyStore.ts) and pass it in.",
      );
    }
    const idempotencyKey = args.idempotencyKey;

    const res = await this.fetchImpl(`${this.baseUrl}/api/brief/sign`, {
      method: "POST",
      headers: {
        ...this.baseHeaders(),
        "Idempotency-Key": idempotencyKey,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        brief_id: args.briefId,
        provider_id: args.providerId,
        signature: args.signature,
        client: args.client,
        engine_run_id: args.engineRunId,
        authority_brief_version: args.authorityBriefVersion,
        provider_brief_version: args.providerBriefVersion,
      }),
    });
    if (!res.ok) throw await this.parseErrorResponse(res);
    return this.readBodyWithContractCheck(
      res, SignBriefResponseSchema, "/api/brief/sign",
    );
  }

  // ------------- GET /api/labs/audit -----------------------------

  async getAuditTrail(briefId: string): Promise<AuditResponse> {
    const url = new URL(`${this.baseUrl}/api/labs/audit`);
    url.searchParams.set("brief_id", briefId);
    const res = await this.fetchImpl(url.toString(), {
      method: "GET",
      headers: this.baseHeaders(),
    });
    if (!res.ok) throw await this.parseErrorResponse(res);
    return this.readBodyWithContractCheck(
      res, AuditResponseSchema, "/api/labs/audit",
    );
  }

  // ------------- GET /api/brief/provider -------------------------

  async getProviderBrief(briefId: string): Promise<ProviderBriefResponse> {
    const url = new URL(`${this.baseUrl}/api/brief/provider`);
    url.searchParams.set("brief_id", briefId);
    const res = await this.fetchImpl(url.toString(), {
      method: "GET",
      headers: this.baseHeaders(),
    });
    if (!res.ok) throw await this.parseErrorResponse(res);
    return this.readBodyWithContractCheck(
      res, ProviderBriefResponseSchema, "/api/brief/provider",
    );
  }
}

/**
 * Convenience factory mirroring most call-site usage.
 *
 * Example:
 *   const client = makeBriefClient({ token, clinicId: "CLN_456" });
 *   const pending = await client.getPendingBriefs({ providerId: "PRV_123" });
 */
export function makeBriefClient(opts: BriefClientOptions): BriefClient {
  return new BriefClient(opts);
}
