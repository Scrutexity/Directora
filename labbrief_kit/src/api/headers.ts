/**
 * Header capture for the v3.6+ Directora Brief API.
 *
 * Three response headers Directora ALWAYS sets (200 or error):
 *   X-Contract-Version       — snapshot version this engine produced from.
 *   X-Request-ID             — opaque correlation id (echo or generated).
 *
 * One header Directora sets only on idempotent replay:
 *   X-Idempotency-Replayed: true
 *
 * One header Directora sets only on 503 idempotency-store-busy:
 *   Retry-After: <seconds>
 *
 * Capture every one of these via `extractHeaders(response)` and surface
 * them in the diagnostics panel.
 */

export interface BriefResponseHeaders {
  contractVersion: string | null;
  idempotencyReplayed: boolean;
  requestId: string | null;
  retryAfterSeconds: number | null;
}

export function extractHeaders(response: Response): BriefResponseHeaders {
  const raw = response.headers.get("Retry-After");
  const retryAfterSeconds = raw ? parseRetryAfter(raw) : null;
  return {
    contractVersion: response.headers.get("X-Contract-Version"),
    idempotencyReplayed:
      response.headers.get("X-Idempotency-Replayed") === "true",
    requestId: response.headers.get("X-Request-ID"),
    retryAfterSeconds,
  };
}

/**
 * Retry-After can be either a number of seconds (RFC 7231 section 7.1.3)
 * or an HTTP-date. Directora always uses seconds; we still parse defensively.
 */
export function parseRetryAfter(raw: string): number | null {
  const trimmed = raw.trim();
  if (/^\d+$/.test(trimmed)) {
    return Number(trimmed);
  }
  const ts = Date.parse(trimmed);
  if (!Number.isNaN(ts)) {
    const delta = Math.ceil((ts - Date.now()) / 1000);
    return delta > 0 ? delta : 0;
  }
  return null;
}

/**
 * Hash equality test for the contract-version mismatch banner.
 *
 * Use `null` for `expected` only during initial bootstrap; once the
 * LabBrief client has loaded the snapshot, it should pass the snapshot
 * version it compiled against.
 */
export function contractVersionMismatch(
  headers: BriefResponseHeaders,
  expected: string | null,
): boolean {
  if (!expected || !headers.contractVersion) return false;
  return headers.contractVersion !== expected;
}
