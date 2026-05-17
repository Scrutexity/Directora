/**
 * DiagnosticsPanel — dev-only floating panel.
 *
 * Renders in the bottom-right corner when:
 *   * `import.meta.env.DEV === true` (Vite dev mode), AND
 *   * `import.meta.env.VITE_SHOW_DIAGNOSTICS` is truthy
 *
 * Surfaces the v3.6+ response headers and retry state so clinical /
 * QA folks can see what the engine actually told the client:
 *   * Contract Version (with mismatch warning)
 *   * Last Request ID  (the one to quote when reporting bugs)
 *   * Replay status    (X-Idempotency-Replayed)
 *   * Retry counter    (attempt N/M with last Retry-After)
 *   * Latency          (last measured round-trip)
 *
 * The panel is intentionally NOT exported from a production build. The
 * standard pattern is to gate the import with `if (import.meta.env.DEV)`
 * via dynamic import, or wrap the JSX in a `{import.meta.env.DEV && …}`
 * gate at the call site.
 */
import React from "react";

import type { BriefResponseHeaders } from "../api/headers";
import { contractVersionMismatch } from "../api/headers";

export interface DiagnosticsState {
  /** Most recent response headers seen. */
  lastHeaders: BriefResponseHeaders | null;
  /** Most recent observed round-trip latency (ms). */
  lastLatencyMs: number | null;
  /** 1-indexed current retry attempt, if any. */
  retryAttempt: number;
  /** Attempt budget (e.g. 4 means 1 initial + 3 retries). */
  retryBudget: number;
  /** Most recent Retry-After value used (ms). */
  lastRetryDelayMs: number | null;
  /** Most recent error code if the last call failed. */
  lastErrorCode: string | null;
}

export interface DiagnosticsPanelProps {
  state: DiagnosticsState;
  /** Snapshot version compiled into the bundle (from contract.ts). */
  expectedContractVersion: string;
}

const isDevEnv = (): boolean => {
  // Vite exposes import.meta.env.DEV. Non-Vite consumers can still
  // gate at the call site.
  try {
    return Boolean(
      (import.meta as unknown as { env?: { DEV?: boolean; VITE_SHOW_DIAGNOSTICS?: string } })
        .env?.DEV
      &&
      (import.meta as unknown as { env?: { VITE_SHOW_DIAGNOSTICS?: string } })
        .env?.VITE_SHOW_DIAGNOSTICS === "true",
    );
  } catch {
    return false;
  }
};

const labelStyle: React.CSSProperties = {
  fontSize: "10px",
  textTransform: "uppercase",
  color: "#7a7a7a",
  fontWeight: 600,
  letterSpacing: "0.5px",
};
const valueStyle: React.CSSProperties = {
  fontSize: "12px",
  fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
  color: "#111",
};
const rowStyle: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "auto 1fr",
  gap: "6px 12px",
  alignItems: "baseline",
};

export const DiagnosticsPanel: React.FC<DiagnosticsPanelProps> = ({
  state,
  expectedContractVersion,
}) => {
  if (!isDevEnv()) {
    return null;
  }

  const headers = state.lastHeaders;
  const mismatch = headers
    ? contractVersionMismatch(headers, expectedContractVersion)
    : false;

  return (
    <aside
      data-testid="diagnostics-panel"
      style={{
        position: "fixed",
        bottom: 12,
        right: 12,
        zIndex: 9999,
        padding: "10px 12px",
        background: "rgba(255, 255, 255, 0.96)",
        border: "1px solid #d0d7de",
        borderRadius: 8,
        boxShadow: "0 6px 24px rgba(0,0,0,0.12)",
        maxWidth: 320,
      }}
      aria-label="Diagnostics panel (dev only)"
    >
      <div
        style={{
          fontWeight: 700,
          marginBottom: 8,
          color: "#111",
        }}
      >
        Brief API — Diagnostics
      </div>

      <div style={rowStyle}>
        <span style={labelStyle}>Contract</span>
        <span style={valueStyle}>
          {headers?.contractVersion ?? "—"}{" "}
          {mismatch && (
            <span style={{ color: "#b34700" }}>
              ⚠ expected {expectedContractVersion}
            </span>
          )}
        </span>

        <span style={labelStyle}>Request ID</span>
        <span style={valueStyle}>{headers?.requestId ?? "—"}</span>

        <span style={labelStyle}>Replay</span>
        <span style={valueStyle}>
          {headers?.idempotencyReplayed ? "✓ replayed" : "—"}
        </span>

        <span style={labelStyle}>Latency</span>
        <span style={valueStyle}>
          {state.lastLatencyMs !== null
            ? `${state.lastLatencyMs} ms`
            : "—"}
        </span>

        {state.retryAttempt > 1 && (
          <>
            <span style={labelStyle}>Retry</span>
            <span style={valueStyle}>
              attempt {state.retryAttempt}/{state.retryBudget}
              {state.lastRetryDelayMs !== null && (
                <> · waited {state.lastRetryDelayMs} ms</>
              )}
            </span>
          </>
        )}

        {state.lastErrorCode && (
          <>
            <span style={labelStyle}>Error</span>
            <span style={{ ...valueStyle, color: "#a40000" }}>
              {state.lastErrorCode}
            </span>
          </>
        )}
      </div>
    </aside>
  );
};

DiagnosticsPanel.displayName = "DiagnosticsPanel";
