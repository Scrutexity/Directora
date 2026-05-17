/**
 * Zod schemas mirroring `shared/brief-api-contract.json` (v3.5).
 *
 * Used by briefClient.ts to validate every API response before it
 * reaches the UI layer. If the Directora contract changes, the
 * snapshot regenerates and the parity test in
 * `contract.test.ts` fails — keep these schemas in lockstep with the
 * snapshot.
 */
import { z } from "zod";

export const RiskLevelSchema = z.enum(["low", "medium", "high"]);
export const SignatureMethodSchema = z.enum(["typed", "drawn", "biometric"]);
export const BriefStatusSchema = z.enum([
  "drafted",
  "reviewed",
  "pending_review",
  "signed",
]);

export const LabSummaryFlagsSchema = z.object({
  critical_count: z.number().int().nonnegative().default(0),
  abnormal_count: z.number().int().nonnegative().default(0),
  claim_risk_flagged: z.number().int().nonnegative().default(0),
});

export const ResultHighlightSchema = z.object({
  name: z.string(),
  value: z.string().nullable().optional(),
  flag: z.string().nullable().optional(),
  reference_range: z.string().nullable().optional(),
});

export const PendingBriefLinksSchema = z.object({
  audit: z.string(),
  detail: z.string(),
  provider: z.string(),
});

export const PendingBriefEngineOutputsSchema = z.object({
  provider_brief_preview: z.record(z.string(), z.unknown()),
  claim_risk: z.object({ items: z.array(z.unknown()) }),
});

export const PendingBriefEntrySchema = z.object({
  brief_id: z.string(),
  provider_id: z.string(),
  clinic_id: z.string(),
  status: BriefStatusSchema,
  created_at: z.number(),
  updated_at: z.number(),
  patient_ref: z.string().nullable().optional(),
  encounter_ref: z.string().nullable().optional(),
  treatment: z.string(),
  market: z.string(),
  lab_summary: LabSummaryFlagsSchema,
  results: z.array(ResultHighlightSchema),
  engine_outputs: PendingBriefEngineOutputsSchema,
  links: PendingBriefLinksSchema,
});

export const PendingBriefResponseSchema = z.object({
  items: z.array(PendingBriefEntrySchema),
  next_cursor: z.string().nullable().optional(),
});

export const SignatureBlockSchema = z.object({
  method: SignatureMethodSchema,
  value: z.string().min(1).max(512),
  signed_at: z.string(),
});

export const ClientBlockSchema = z.object({
  app: z.string(),
  version: z.string(),
  session_id: z.string().nullable().optional(),
});

export const SignBriefRequestSchema = z.object({
  brief_id: z.string(),
  provider_id: z.string(),
  signature: SignatureBlockSchema,
  client: ClientBlockSchema,
  engine_run_id: z.string().nullable().optional(),
  authority_brief_version: z.string().nullable().optional(),
  provider_brief_version: z.string().nullable().optional(),
});

export const SignBriefResponseSchema = z.object({
  status: z.literal("signed"),
  ledger_event_id: z.string(),
  signed_at: z.string(),
  brief_content_hash: z.string(),
  binding_hash: z.string(),
  next_actions: z.object({
    export: z.string(),
    audit: z.string(),
  }),
});

export const AuditEventSchema = z
  .object({
    event_id: z.string(),
    kind: z.string(),
    ts: z.number(),
    brief_id: z.string().nullable().optional(),
    clinic_id: z.string().nullable().optional(),
    provider_id: z.string().nullable().optional(),
    approval_status: z.string().nullable().optional(),
    risk_level: z.string().nullable().optional(),
  })
  .passthrough();

export const AuditResponseSchema = z.object({
  brief_id: z.string(),
  events: z.array(AuditEventSchema),
});

export const ProviderBriefResponseSchema = z.object({
  asset_type: z.literal("provider_brief_snippet"),
  brief_content_hash: z.string(),
  canonical_json: z.string(),
  snippet: z.record(z.string(), z.unknown()),
});

export const ErrorResponseSchema = z.object({
  error: z.string(),
  detail: z.string().nullable().optional(),
  ledger_event_id: z.string().nullable().optional(),
  request_id: z.string().nullable().optional(),
});

export type Contract = {
  PendingBriefResponse: z.infer<typeof PendingBriefResponseSchema>;
  SignBriefRequest: z.infer<typeof SignBriefRequestSchema>;
  SignBriefResponse: z.infer<typeof SignBriefResponseSchema>;
  AuditResponse: z.infer<typeof AuditResponseSchema>;
  ProviderBriefResponse: z.infer<typeof ProviderBriefResponseSchema>;
  ErrorResponse: z.infer<typeof ErrorResponseSchema>;
};
