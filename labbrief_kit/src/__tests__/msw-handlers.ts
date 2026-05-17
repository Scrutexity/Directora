/**
 * MSW handler stubs that satisfy the v3.5 contract snapshot.
 *
 * Drop into your LabBrief test setup. The shapes here mirror the
 * Directora API responses; the parity test in `schemas/contract.test.ts`
 * ensures Zod accepts the same payloads.
 */
import { http, HttpResponse } from "msw";

const BASE = "http://localhost:8000";

export const briefApiHandlers = [
  http.get(`${BASE}/api/brief/pending`, ({ request }) => {
    const rid = request.headers.get("X-Request-ID") || "req_msw";
    return HttpResponse.json(
      {
        items: [
          {
            brief_id: "BRF_MSW_01",
            provider_id: "PRV_TEST",
            clinic_id: "CLN_TEST",
            status: "pending_review",
            created_at: 1747432893,
            updated_at: 1747432893,
            patient_ref: "P_REF_001",
            encounter_ref: "E_REF_001",
            treatment: "Example Treatment",
            market: "Example Market",
            lab_summary: {
              critical_count: 0,
              abnormal_count: 1,
              claim_risk_flagged: 1,
            },
            results: [{ name: "vitamin_D", value: "low", flag: "abnormal" }],
            engine_outputs: {
              provider_brief_preview: {
                headline:
                  "Provider Brief: claim-risk review for Example Treatment at Example Clinic",
                human_approval_status: "human approval required",
                approval_required: true,
                claim_risk_review_checklist_count: 9,
              },
              claim_risk: { items: ["Avoid guaranteed results"] },
            },
            links: {
              audit: "/api/labs/audit?brief_id=BRF_MSW_01",
              detail: "/api/brief/provider?brief_id=BRF_MSW_01",
              provider: "/api/brief/provider?brief_id=BRF_MSW_01",
            },
          },
        ],
        next_cursor: null,
      },
      { headers: { "X-Request-ID": rid } },
    );
  }),

  http.post(`${BASE}/api/brief/sign`, async ({ request }) => {
    const rid = request.headers.get("X-Request-ID") || "req_msw";
    const idem = request.headers.get("Idempotency-Key");
    if (!idem) {
      return HttpResponse.json(
        { error: "missing_idempotency_key", request_id: rid },
        { status: 400, headers: { "X-Request-ID": rid } },
      );
    }
    const body = (await request.json()) as { brief_id: string };
    if (body.brief_id === "BRF_NOT_FOUND") {
      return HttpResponse.json(
        { error: "brief_not_found", request_id: rid },
        { status: 404, headers: { "X-Request-ID": rid } },
      );
    }
    return HttpResponse.json(
      {
        status: "signed",
        ledger_event_id: `evt_${idem.replace(/[^a-z0-9]/gi, "").slice(0, 16)}`,
        signed_at: "2026-05-16T17:01:33.000Z",
        brief_content_hash: "a".repeat(64),
        binding_hash: "b".repeat(64),
        next_actions: {
          export: `/api/brief/provider?brief_id=${body.brief_id}`,
          audit: `/api/labs/audit?brief_id=${body.brief_id}`,
        },
      },
      { headers: { "X-Request-ID": rid } },
    );
  }),

  http.get(`${BASE}/api/brief/provider`, ({ request }) => {
    const rid = request.headers.get("X-Request-ID") || "req_msw";
    const url = new URL(request.url);
    const briefId = url.searchParams.get("brief_id");
    if (briefId === "BRF_NOT_FOUND") {
      return HttpResponse.json(
        { error: "brief_not_found", request_id: rid },
        { status: 404, headers: { "X-Request-ID": rid } },
      );
    }
    return HttpResponse.json(
      {
        asset_type: "provider_brief_snippet",
        brief_content_hash: "a".repeat(64),
        canonical_json: '{"asset_type":"provider_brief_snippet"}',
        snippet: {
          headline:
            "Provider Brief: claim-risk review for Example Treatment at Example Clinic",
          treatment: "Example Treatment",
          market: "Example Market",
          approval_required: true,
        },
      },
      { headers: { "X-Request-ID": rid } },
    );
  }),

  http.get(`${BASE}/api/labs/audit`, ({ request }) => {
    const rid = request.headers.get("X-Request-ID") || "req_msw";
    const url = new URL(request.url);
    const briefId = url.searchParams.get("brief_id") || "";
    return HttpResponse.json(
      {
        brief_id: briefId,
        events: [
          {
            event_id: "evt_msw_1",
            kind: "provider_brief_signed",
            ts: 1747432900,
            brief_id: briefId,
            clinic_id: "CLN_TEST",
            provider_id: "PRV_TEST",
            approval_status: "signed",
          },
        ],
      },
      { headers: { "X-Request-ID": rid } },
    );
  }),
];
