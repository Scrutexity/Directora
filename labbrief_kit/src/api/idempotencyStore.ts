/**
 * Idempotency key store — store-owned, not client-owned.
 *
 * Rule: `BriefClient.signBrief` requires the caller to pass
 * `idempotencyKey`. It never generates a key internally. The store
 * layer owns:
 *
 *   * generation       (once per intent-to-sign)
 *   * persistence      (keyed by (providerId, briefId) so retries
 *                       across the network layer reuse the same key)
 *   * lifecycle        (clear on terminal outcomes; keep on transient)
 *
 * Default backend is an in-memory `Map`. The interface is intentionally
 * small so you can swap a backend that persists across page reloads
 * (e.g. `sessionStorage` keyed by `signin-attempt-{providerId}-{briefId}`)
 * without touching the rest of the kit.
 *
 * Clear conditions (per spec):
 *   * 200 signed                       → clear
 *   * 409 already_signed               → clear
 *   * 409 invalid_status               → clear
 *   * 409 idempotency_conflict         → clear (client bug; force a fresh key)
 *   * 4xx auth/validation (401/403/404/422) → clear (attempt is dead)
 *   * 5xx engine_or_ledger_failure     → clear (non-retryable in our taxonomy)
 *   * 503 idempotency_store_busy / 429 → keep (retry layer reuses)
 *   * network timeout                  → keep
 */

const DEFAULT_STORE = new Map<string, string>();

export interface IdempotencyKeyBackend {
  get(key: string): string | undefined;
  set(key: string, value: string): void;
  delete(key: string): void;
}

class MapBackend implements IdempotencyKeyBackend {
  private map: Map<string, string>;
  constructor(map: Map<string, string>) {
    this.map = map;
  }
  get(key: string): string | undefined {
    return this.map.get(key);
  }
  set(key: string, value: string): void {
    this.map.set(key, value);
  }
  delete(key: string): void {
    this.map.delete(key);
  }
}

let backend: IdempotencyKeyBackend = new MapBackend(DEFAULT_STORE);

/** Swap the backend. Useful for sessionStorage-backed persistence or tests. */
export function setIdempotencyKeyBackend(b: IdempotencyKeyBackend): void {
  backend = b;
}

/** Clear the in-memory store. Test seam — the canonical reset hook. */
export function resetIdempotencyStore(): void {
  DEFAULT_STORE.clear();
  backend = new MapBackend(DEFAULT_STORE);
}

/** @deprecated Use `resetIdempotencyStore` (renamed in v3.7 patch). */
export const resetIdempotencyKeyBackend = resetIdempotencyStore;

function compositeKey(providerId: string, briefId: string): string {
  return `${providerId}:${briefId}`;
}

function newKey(briefId: string): string {
  // Convention: `sign-{briefId}-{uuidv4}`. Directora doesn't parse the
  // key; we use a recognisable prefix so logs and ledger entries are
  // human-scannable.
  return `sign-${briefId}-${uuidv4()}`;
}

function uuidv4(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

/**
 * Return the persisted idempotency key for this (providerId, briefId),
 * creating it if missing. Multiple calls for the same pair return the
 * SAME key until you explicitly clear it.
 */
export function getOrCreateIdempotencyKey(
  providerId: string,
  briefId: string,
): string {
  const k = compositeKey(providerId, briefId);
  const existing = backend.get(k);
  if (existing) return existing;
  const created = newKey(briefId);
  backend.set(k, created);
  return created;
}

/** Drop the persisted key — call after a terminal outcome. */
export function clearIdempotencyKey(
  providerId: string,
  briefId: string,
): void {
  backend.delete(compositeKey(providerId, briefId));
}

/**
 * Outcome shape for `shouldClearKeyForOutcome`. Either pass a clean
 * success flag, or the BriefApiError fields (`status`, `code`), or a
 * `MaxRetriesExceededError`-like wrapper.
 */
export interface SignOutcome {
  success?: boolean;
  status?: number | null;
  code?: string | null;
  /**
   * Pass `true` when the caller has caught a `MaxRetriesExceededError`.
   * Forces clear regardless of the per-attempt status/code because no
   * more attempts are coming.
   */
  maxRetriesExceeded?: boolean;
}

/**
 * Decide whether to drop the stored key for this outcome. The retry
 * layer never clears keys (that would force a NEW header on the next
 * attempt and lose idempotent replay) — only the terminal outcome
 * triggers the clear.
 *
 * Locked table:
 *
 *   | outcome                              | clear? |
 *   | ------------------------------------ | ------ |
 *   | 200 signed                           | YES    |
 *   | 409 already_signed                   | YES    |
 *   | 409 invalid_status                   | YES    |
 *   | 409 idempotency_conflict             | YES    |
 *   | 401 / 403 / 404 / 422 / 500          | YES    |
 *   | MaxRetriesExceededError              | YES    |
 *   | 503 idempotency_store_busy           | NO     |
 *   | 429                                  | NO     |
 *   | network timeout (no HTTP status)     | NO     |
 */
export function shouldClearKeyForOutcome(outcome: SignOutcome): boolean {
  if (outcome.success) return true;
  if (outcome.maxRetriesExceeded) return true;
  const status = outcome.status ?? null;
  const code = outcome.code ?? null;
  if (status === 503 || status === 429) return false;
  // Network timeout — no HTTP status surfaced. Retry layer keeps key.
  if (status === null || status === undefined) return false;
  if (status === 409) {
    return (
      code === "already_signed" ||
      code === "invalid_status" ||
      code === "idempotency_conflict"
    );
  }
  // Any other terminal HTTP status (400/401/403/404/422/500…): clear.
  return true;
}

/**
 * Convenience wrapper for the success path: run a function with the
 * persisted key and clear on success. Use only when the only terminal
 * outcome you care about is success — for error-aware lifecycle,
 * inspect the error yourself and call `clearIdempotencyKey` via
 * `shouldClearKeyForOutcome`.
 */
export async function withIdempotencyKey<T>(
  providerId: string,
  briefId: string,
  fn: (key: string) => Promise<T>,
): Promise<T> {
  const key = getOrCreateIdempotencyKey(providerId, briefId);
  const out = await fn(key);
  clearIdempotencyKey(providerId, briefId);
  return out;
}
