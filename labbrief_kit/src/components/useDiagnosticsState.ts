/**
 * React hook wiring the diagnostics state for `DiagnosticsPanel`.
 *
 * Returned `actions` are deliberately small — call them from the
 * briefClient adapter you wrap into your store. They are stable
 * across renders so you can drop them into deps.
 */
import { useCallback, useState } from "react";

import type { BriefResponseHeaders } from "../api/headers";
import type { DiagnosticsState } from "./DiagnosticsPanel";
import type { RetryAttemptInfo } from "../api/retry";

const INITIAL: DiagnosticsState = {
  lastHeaders: null,
  lastLatencyMs: null,
  retryAttempt: 0,
  retryBudget: 0,
  lastRetryDelayMs: null,
  lastErrorCode: null,
};

export function useDiagnosticsState() {
  const [state, setState] = useState<DiagnosticsState>(INITIAL);

  const recordResponse = useCallback(
    (headers: BriefResponseHeaders, latencyMs: number) => {
      setState((prev) => ({
        ...prev,
        lastHeaders: headers,
        lastLatencyMs: latencyMs,
        lastErrorCode: null,
      }));
    },
    [],
  );

  const recordError = useCallback(
    (errorCode: string, headers?: BriefResponseHeaders | null) => {
      setState((prev) => ({
        ...prev,
        lastHeaders: headers ?? prev.lastHeaders,
        lastErrorCode: errorCode,
      }));
    },
    [],
  );

  const recordRetry = useCallback((info: RetryAttemptInfo) => {
    setState((prev) => ({
      ...prev,
      retryAttempt: info.attempt,
      retryBudget: info.totalAttempts,
      lastRetryDelayMs:
        info.retryAfterMs !== undefined ? info.retryAfterMs : prev.lastRetryDelayMs,
      lastErrorCode: info.errorCode ?? prev.lastErrorCode,
    }));
  }, []);

  const reset = useCallback(() => setState(INITIAL), []);

  return { state, actions: { recordResponse, recordError, recordRetry, reset } };
}
