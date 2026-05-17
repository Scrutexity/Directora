/**
 * Auth error → UI guidance.
 *
 * Single source of truth for what LabBrief shows users on 401 / 403.
 * The action verbs (re_authenticate / refresh / contact_support) let
 * the calling code decide whether to clear the session, prompt for
 * sign-in, or surface a static toast.
 */
import type { BriefApiError } from "./briefClient";

export type AuthRecoveryAction =
  | "re_authenticate"
  | "refresh"
  | "contact_support"
  | "none";

export interface AuthErrorGuidance {
  /** Plain-language message safe to render to a clinician. */
  message: string;
  /** What the client should prompt the user to do next. */
  action: AuthRecoveryAction;
  /** Should the existing session token be discarded? */
  clearSession: boolean;
  /** Severity for toast colour / banner level. */
  severity: "info" | "warning" | "error";
}

export const AUTH_ERROR_GUIDANCE: Record<string, AuthErrorGuidance> = {
  token_expired: {
    message: "Your session has expired. Please log in again.",
    action: "re_authenticate",
    clearSession: true,
    severity: "warning",
  },
  invalid_token: {
    message: "Authentication failed. Please log in again.",
    action: "re_authenticate",
    clearSession: true,
    severity: "error",
  },
  missing_bearer_token: {
    message: "You are not signed in. Please log in.",
    action: "re_authenticate",
    clearSession: true,
    severity: "warning",
  },
  permission_denied: {
    message:
      "You are not authorized to sign this brief. Ask the assigned " +
      "provider or a medical director to sign instead.",
    action: "none",
    clearSession: false,
    severity: "error",
  },
  clinic_mismatch: {
    message:
      "You are signed in to a different clinic than this brief. " +
      "Switch clinics and try again.",
    action: "re_authenticate",
    clearSession: false,
    severity: "error",
  },
};

export function authGuidanceForError(
  error: BriefApiError | { code?: string; status?: number },
): AuthErrorGuidance | null {
  const code =
    (error as BriefApiError).code !== undefined
      ? String((error as BriefApiError).code)
      : (error as { code?: string }).code;
  if (code && AUTH_ERROR_GUIDANCE[code]) {
    return AUTH_ERROR_GUIDANCE[code];
  }
  // Fallback: any 401 we don't recognise still gets a generic re-auth.
  if ((error as BriefApiError).status === 401) {
    return {
      message: "Authentication failed. Please log in again.",
      action: "re_authenticate",
      clearSession: true,
      severity: "error",
    };
  }
  return null;
}
