/**
 * v3.6+ Compatibility add-on — single import surface for LabBrief.
 *
 * Pulls together the pieces LabBrief needs to consume Directora v3.6
 * (headers + 503 + replay) and v3.7 (`X-Contract-Version`,
 * canonical metric names). Nothing in here changes the existing
 * briefClient API; the additions are layered on top.
 *
 * Import from a single path:
 *
 *     import {
 *       signBriefWithRetry,
 *       extractHeaders,
 *       DiagnosticsPanel,
 *       useDiagnosticsState,
 *       authGuidanceForError,
 *       EXPECTED_CONTRACT_VERSION,
 *     } from "labbrief/v3_6_compatibility";
 *
 * The constant `EXPECTED_CONTRACT_VERSION` is the snapshot version
 * the Zod schemas in this kit were compiled against. Bump it whenever
 * you re-copy `shared/brief-api-contract.json` from Directora.
 */

export {
  BriefApiError,
  BriefClient,
  makeBriefClient,
  type ContractMismatchEvent,
} from "./api/briefClient";

export {
  extractHeaders,
  parseRetryAfter,
  contractVersionMismatch,
  type BriefResponseHeaders,
} from "./api/headers";

export {
  signBriefWithRetry,
  applyJitter,
  scheduledBackoffMs,
  BACKOFF_SCHEDULE_MS,
  BACKOFF_JITTER_PCT,
  RETRYABLE_STATUSES,
  RETRYABLE_ERROR_CODES,
  NEVER_RETRY_STATUSES,
  MaxRetriesExceededError,
  type SignWithRetryOptions,
  type RetryAttemptInfo,
} from "./api/retry";

export {
  AUTH_ERROR_GUIDANCE,
  authGuidanceForError,
  type AuthRecoveryAction,
  type AuthErrorGuidance,
} from "./api/authErrors";

export {
  DiagnosticsPanel,
  type DiagnosticsPanelProps,
  type DiagnosticsState,
} from "./components/DiagnosticsPanel";

export { useDiagnosticsState } from "./components/useDiagnosticsState";

export {
  ContractMismatchBanner,
  type ContractMismatchBannerProps,
  type ContractMismatchBannerState,
} from "./components/ContractMismatchBanner";

export { useContractMismatchState } from "./components/useContractMismatchState";

export {
  getOrCreateIdempotencyKey,
  clearIdempotencyKey,
  shouldClearKeyForOutcome,
  withIdempotencyKey,
  setIdempotencyKeyBackend,
  resetIdempotencyStore,
  resetIdempotencyKeyBackend,    // deprecated alias; same behaviour as resetIdempotencyStore
  type IdempotencyKeyBackend,
  type SignOutcome,
} from "./api/idempotencyStore";

export {
  signWithRetry,                  // alias for signBriefWithRetry
  handleAuthError,                // string-returning wrapper around authGuidanceForError
} from "./api/compatShims";

/**
 * The contract version this kit's Zod schemas were compiled against.
 *
 * Update this on every Directora deploy that bumps `CONTRACT_VERSION`,
 * along with `shared/brief-api-contract.json`. The diagnostics panel
 * shows a yellow ⚠ banner when a response's `X-Contract-Version`
 * differs from this value — that's the early warning that the kit
 * needs to be regenerated.
 */
export const EXPECTED_CONTRACT_VERSION = "3.7.0";
