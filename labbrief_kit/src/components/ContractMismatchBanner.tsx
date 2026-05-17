/**
 * ContractMismatchBanner — dev-only fixed banner.
 *
 * Renders along the top of the viewport when the most recent API
 * response carried an `X-Contract-Version` that disagrees with the
 * value the kit was compiled against. Mounting is gated by
 * `import.meta.env.DEV && VITE_SHOW_DIAGNOSTICS === "true"` — the
 * banner never reaches production users.
 *
 * Wire with `useContractMismatchState()`:
 *
 *     const banner = useContractMismatchState();
 *     const client = new BriefClient({
 *       …,
 *       expectedContractVersion: EXPECTED_CONTRACT_VERSION,
 *       onContractMismatch: banner.onMismatch,
 *     });
 *     <ContractMismatchBanner state={banner.state} />
 */
import React from "react";

import type { ContractMismatchEvent } from "../api/briefClient";

export interface ContractMismatchBannerState {
  /** The most recent mismatch event, if any. */
  last: ContractMismatchEvent | null;
  /** Number of mismatched responses observed in this session. */
  count: number;
}

export interface ContractMismatchBannerProps {
  state: ContractMismatchBannerState;
  /** Optional: render only when this returns true. Defaults to dev+VITE_SHOW_DIAGNOSTICS. */
  isVisible?: () => boolean;
}

const defaultIsVisible = (): boolean => {
  try {
    const env = (
      import.meta as unknown as { env?: { DEV?: boolean; VITE_SHOW_DIAGNOSTICS?: string } }
    ).env;
    return Boolean(env?.DEV) && env?.VITE_SHOW_DIAGNOSTICS === "true";
  } catch {
    return false;
  }
};

export const ContractMismatchBanner: React.FC<ContractMismatchBannerProps> = ({
  state,
  isVisible,
}) => {
  const visible = (isVisible ?? defaultIsVisible)();
  if (!visible || !state.last) return null;

  const e = state.last;
  return (
    <div
      role="alert"
      data-testid="contract-mismatch-banner"
      style={{
        position: "fixed",
        top: 0,
        left: 0,
        right: 0,
        zIndex: 9998,
        background: "#b34700",
        color: "#fff",
        padding: "8px 12px",
        fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
        fontSize: 12,
        boxShadow: "0 1px 4px rgba(0,0,0,0.25)",
      }}
    >
      <strong>Contract mismatch · </strong>
      expected <code style={{ background: "rgba(255,255,255,0.15)", padding: "0 4px" }}>
        {e.expected}
      </code>
      , got <code style={{ background: "rgba(255,255,255,0.15)", padding: "0 4px" }}>
        {e.actual ?? "<missing>"}
      </code>
      {" · "}
      <span style={{ opacity: 0.85 }}>path {e.path}</span>
      {" · "}
      <span style={{ opacity: 0.85 }}>request_id {e.requestId ?? "—"}</span>
      {" · "}
      <span style={{ opacity: 0.85 }}>events: {state.count}</span>
      <details style={{ marginTop: 6 }}>
        <summary style={{ cursor: "pointer" }}>headers + body (dev only)</summary>
        <pre
          style={{
            margin: "6px 0 0 0",
            background: "rgba(0,0,0,0.25)",
            padding: 8,
            borderRadius: 4,
            maxHeight: 240,
            overflow: "auto",
          }}
        >
{`headers: ${JSON.stringify(e.headers, null, 2)}

body: ${e.bodyRaw.length > 4000 ? e.bodyRaw.slice(0, 4000) + "\n…truncated…" : e.bodyRaw}`}
        </pre>
      </details>
    </div>
  );
};

ContractMismatchBanner.displayName = "ContractMismatchBanner";
