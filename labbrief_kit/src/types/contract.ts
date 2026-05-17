/**
 * TypeScript types mirroring `shared/brief-api-contract.json` (v3.5).
 *
 * Keep this file in lockstep with the snapshot. Regenerate by hand when
 * Directora changes the contract; the parity test in
 * `schemas/contract.test.ts` will fail otherwise.
 */

export type RiskLevel = "low" | "medium" | "high";
export type SignatureMethod = "typed" | "drawn" | "biometric";
export type BriefStatus = "drafted" | "reviewed" | "pending_review" | "signed";

export interface LabSummaryFlags {
  critical_count: number;
  abnormal_count: number;
  claim_risk_flagged: number;
}

export interface ResultHighlight {
  name: string;
  value: string | null;
  flag: string | null;
  reference_range: string | null;
}

export interface PendingBriefLinks {
  audit: string;
  detail: string;
  provider: string;
}

export interface PendingBriefEngineOutputs {
  provider_brief_preview: Record<string, unknown>;
  claim_risk: { items: string[] };
}

export interface PendingBriefEntry {
  brief_id: string;
  provider_id: string;
  clinic_id: string;
  status: BriefStatus;
  created_at: number;
  updated_at: number;
  patient_ref: string | null;
  encounter_ref: string | null;
  treatment: string;
  market: string;
  lab_summary: LabSummaryFlags;
  results: ResultHighlight[];
  engine_outputs: PendingBriefEngineOutputs;
  links: PendingBriefLinks;
}

export interface PendingBriefResponse {
  items: PendingBriefEntry[];
  next_cursor: string | null;
}

export interface SignatureBlock {
  method: SignatureMethod;
  value: string;
  signed_at: string; // ISO 8601 UTC
}

export interface ClientBlock {
  app: string;
  version: string;
  session_id?: string | null;
}

export interface SignBriefRequest {
  brief_id: string;
  provider_id: string;
  signature: SignatureBlock;
  client: ClientBlock;
  // Optional engine-context echo so the API can detect stale signings.
  engine_run_id?: string | null;
  authority_brief_version?: string | null;
  provider_brief_version?: string | null;
}

export interface SignBriefResponse {
  status: "signed";
  ledger_event_id: string;
  signed_at: string;
  brief_content_hash: string;
  binding_hash: string;
  next_actions: { export: string; audit: string };
}

export interface AuditEvent {
  event_id: string;
  kind: string;
  ts: number;
  brief_id?: string | null;
  clinic_id?: string | null;
  provider_id?: string | null;
  approval_status?: string | null;
  risk_level?: string | null;
  [extra: string]: unknown;
}

export interface AuditResponse {
  brief_id: string;
  events: AuditEvent[];
}

export interface ProviderBriefResponse {
  asset_type: "provider_brief_snippet";
  brief_content_hash: string;
  canonical_json: string;
  snippet: Record<string, unknown>;
}

export type BriefApiErrorCode =
  | "brief_not_found"
  | "invalid_status"
  | "already_signed"
  | "permission_denied"
  | "idempotency_conflict"
  | "missing_idempotency_key"
  | "invalid_signature"
  | "engine_or_ledger_failure"
  | "clinic_mismatch"
  | "missing_bearer_token"
  | "invalid_token";

export interface ErrorResponse {
  error: BriefApiErrorCode | string;
  detail?: string | null;
  ledger_event_id?: string | null;
  request_id?: string | null;
}
