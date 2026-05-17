/**
 * Error-code → UI copy map.
 *
 * One source of truth so the sign-off flow and any retry flow share
 * the same strings. Update here if marketing/clinical needs revise the
 * UI copy — never embed strings inline.
 */
import type { BriefApiErrorCode } from "../types/contract";

export interface BriefErrorCopy {
  /** Headline shown in the toast / banner. */
  title: string;
  /** Supporting paragraph. */
  body: string;
  /** What the UI should suggest the user do next. */
  action: string;
}

export const ERROR_MESSAGES: Record<
  BriefApiErrorCode | "default",
  BriefErrorCopy
> = {
  already_signed: {
    title: "Already signed",
    body: "This brief has already been signed by a provider.",
    action: "View audit trail.",
  },
  idempotency_conflict: {
    title: "Request collision",
    body: "Two different sign requests arrived under the same key.",
    action: "Refresh the page and try again.",
  },
  invalid_status: {
    title: "Brief is not pending review",
    body: "Sign-off requires the brief to be in pending_review status.",
    action: "Refresh the list to see the current state.",
  },
  permission_denied: {
    title: "Not authorized to sign this brief",
    body: "Only the assigned provider or a medical director can sign.",
    action: "Ask the medical director to sign, or check assignment.",
  },
  engine_or_ledger_failure: {
    title: "Signing failed",
    body: "The engine or ledger could not complete the sign-off.",
    action: "Please try again. If the problem persists, contact support.",
  },
  brief_not_found: {
    title: "Brief not found",
    body: "We could not find this brief.",
    action: "Refresh the list to see the current state.",
  },
  missing_idempotency_key: {
    title: "Missing idempotency key",
    body: "The signing request did not include an Idempotency-Key header.",
    action: "This is a client bug — please contact support.",
  },
  invalid_signature: {
    title: "Signature is invalid",
    body: "The signature value did not meet validation requirements.",
    action: "Re-enter the signature.",
  },
  clinic_mismatch: {
    title: "Clinic mismatch",
    body: "You are not authorized to access this brief.",
    action: "Check that you are signed in to the correct clinic.",
  },
  missing_bearer_token: {
    title: "Not signed in",
    body: "Your session is missing or expired.",
    action: "Sign in again.",
  },
  invalid_token: {
    title: "Session token invalid",
    body: "Your session token could not be verified.",
    action: "Sign in again.",
  },
  default: {
    title: "Something went wrong",
    body: "An unexpected error prevented this action.",
    action: "Please try again. Include the request ID below if reporting.",
  },
};

export function copyForError(
  code: BriefApiErrorCode | string | null | undefined,
): BriefErrorCopy {
  if (!code) return ERROR_MESSAGES.default;
  return (
    (ERROR_MESSAGES as Record<string, BriefErrorCopy>)[code] ||
    ERROR_MESSAGES.default
  );
}
