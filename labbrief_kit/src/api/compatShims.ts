/**
 * Compatibility shims for the original spec wording.
 *
 * Not required — these are thin wrappers around the canonical helpers
 * so existing docs / code samples using the original names continue
 * to compile.
 */
import type { BriefClient } from "./briefClient";
import type { BriefApiError } from "./briefClient";
import { authGuidanceForError } from "./authErrors";
import type { SignBriefResponse } from "../types/contract";
import { signBriefWithRetry, type SignWithRetryOptions } from "./retry";

/**
 * Alias for `signBriefWithRetry`. The retry semantics are identical;
 * the name matches the original integration-doc wording.
 */
export function signWithRetry(
  client: BriefClient,
  opts: SignWithRetryOptions,
): Promise<SignBriefResponse> {
  return signBriefWithRetry(client, opts);
}

/**
 * One-line wrapper returning the plain-language toast string for an
 * auth error. Useful when calling code wants the message alone and
 * doesn't need the structured `AuthErrorGuidance` (with `action`,
 * `clearSession`, `severity`).
 */
export function handleAuthError(error: BriefApiError | { code?: string; status?: number }): string {
  return (
    authGuidanceForError(error)?.message ??
    "An unexpected error occurred. Please try again."
  );
}
