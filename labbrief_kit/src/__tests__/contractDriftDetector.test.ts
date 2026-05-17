/**
 * Contract drift detector — the canonical end-to-end check that proves
 * LabBrief sees the same response shapes Directora produces.
 *
 * Three layers, all driven from the single snapshot at
 * `shared/brief-api-contract.json`:
 *
 *   1. Every snapshot model is parsable by ajv. (Catches malformed
 *      snapshot files committed by mistake.)
 *   2. Every snapshot model accepts a representative-but-valid payload.
 *      (Catches the snapshot drifting to a strictly-narrower shape than
 *      the Zod schema currently accepts.)
 *   3. Every snapshot model rejects a malformed payload. (Catches the
 *      snapshot drifting to a strictly-wider shape than the Zod schema
 *      enforces.)
 *   4. Every snapshot model agrees with its Zod counterpart on both
 *      payloads. (Catches one side silently widening or narrowing.)
 *
 * The pytest-side `tests/api/test_contract.py` covers the
 * Directora→snapshot direction. This file covers the snapshot↔Zod
 * direction. Together they form the closed loop:
 *
 *     Pydantic model → snapshot → Zod schema
 *           ▲                          │
 *           └──── drift fails here ────┘
 */
import { describe, expect, it } from "vitest";
import Ajv from "ajv";
import addFormats from "ajv-formats";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import {
  AuditResponseSchema,
  ErrorResponseSchema,
  PendingBriefResponseSchema,
  ProviderBriefResponseSchema,
  SignBriefResponseSchema,
} from "../schemas/contract";
import { EXPECTED_CONTRACT_VERSION } from "../v3_6_compatibility";

const SNAPSHOT_PATH = resolve(
  __dirname,
  "../../../shared/brief-api-contract.json",
);

interface Snapshot {
  version: string;
  generated_at: string;
  models: Record<string, object>;
}

const snapshot: Snapshot = JSON.parse(
  readFileSync(SNAPSHOT_PATH, "utf-8"),
);
const ajv = new Ajv({ strict: false, allErrors: true });
addFormats(ajv);

const fixtures: Record<
  string,
  { zod: { safeParse(input: unknown): { success: boolean } }; good: object }
> = {
  PendingBriefResponse: {
    zod: PendingBriefResponseSchema,
    good: {
      items: [
        {
          brief_id: "BRF_DRIFT_01",
          provider_id: "PRV_DRIFT",
          clinic_id: "CLN_DRIFT",
          status: "pending_review",
          created_at: 1747432893.0,
          updated_at: 1747432893.0,
          patient_ref: "P_REF",
          encounter_ref: "E_REF",
          treatment: "Example Treatment",
          market: "Example Market",
          lab_summary: {
            critical_count: 0,
            abnormal_count: 1,
            claim_risk_flagged: 1,
          },
          results: [{ name: "vitamin_D", value: "low", flag: "abnormal" }],
          engine_outputs: {
            provider_brief_preview: { headline: "Provider Brief: …" },
            claim_risk: { items: [] },
          },
          links: {
            audit: "/api/labs/audit?brief_id=BRF_DRIFT_01",
            detail: "/api/brief/provider?brief_id=BRF_DRIFT_01",
            provider: "/api/brief/provider?brief_id=BRF_DRIFT_01",
          },
        },
      ],
      next_cursor: null,
    },
  },
  SignResponse: {
    zod: SignBriefResponseSchema,
    good: {
      status: "signed",
      ledger_event_id: "evt_drift",
      signed_at: "2026-05-16T17:01:33.000Z",
      brief_content_hash: "a".repeat(64),
      binding_hash: "b".repeat(64),
      next_actions: {
        export: "/api/brief/provider?brief_id=BRF_DRIFT_01",
        audit: "/api/labs/audit?brief_id=BRF_DRIFT_01",
      },
    },
  },
  ProviderBriefResponse: {
    zod: ProviderBriefResponseSchema,
    good: {
      asset_type: "provider_brief_snippet",
      brief_content_hash: "a".repeat(64),
      canonical_json: "{\"asset_type\":\"provider_brief_snippet\"}",
      snippet: { treatment: "Example Treatment" },
    },
  },
  AuditResponse: {
    zod: AuditResponseSchema,
    good: {
      brief_id: "BRF_DRIFT_01",
      events: [
        {
          event_id: "evt_drift_1",
          kind: "provider_brief_signed",
          ts: 1747432900,
          brief_id: "BRF_DRIFT_01",
        },
      ],
    },
  },
  ErrorResponse: {
    zod: ErrorResponseSchema,
    good: {
      error: "already_signed",
      ledger_event_id: "evt_drift",
      request_id: "req_drift",
    },
  },
};

describe("Layer 0: snapshot integrity", () => {
  it("loads with version + generated_at + at least 5 models", () => {
    expect(snapshot.version).toBeTruthy();
    expect(snapshot.generated_at).toBeTruthy();
    expect(Object.keys(snapshot.models).length).toBeGreaterThanOrEqual(5);
  });

  it("kit's EXPECTED_CONTRACT_VERSION matches the snapshot version", () => {
    expect(EXPECTED_CONTRACT_VERSION).toBe(snapshot.version);
  });
});

describe("Layer 1: ajv can compile every snapshot model", () => {
  for (const name of Object.keys(fixtures)) {
    it(`compiles snapshot.models.${name}`, () => {
      const schema = snapshot.models[name];
      expect(schema).toBeTruthy();
      const validate = ajv.compile(schema as never);
      expect(validate).toBeTypeOf("function");
    });
  }
});

describe("Layer 2 & 3: snapshot + Zod agree on good and bad payloads", () => {
  for (const [name, { zod, good }] of Object.entries(fixtures)) {
    it(`${name}: ajv-snapshot AND Zod both accept a representative payload`, () => {
      const validate = ajv.compile(snapshot.models[name] as never);
      const ajvOk = validate(good);
      const zodOk = zod.safeParse(good).success;
      expect(ajvOk, `ajv rejected: ${JSON.stringify(validate.errors)}`).toBe(true);
      expect(zodOk).toBe(true);
    });

    it(`${name}: ajv-snapshot AND Zod both reject a malformed payload`, () => {
      const validate = ajv.compile(snapshot.models[name] as never);
      // Status: 12345 is type-wrong for every "status" field we use,
      // and the rest is filler so structurally something is off.
      const bad: Record<string, unknown> = {
        ...(good as Record<string, unknown>),
        status: 12345,
        brief_id: 12345,
      };
      const ajvBad = !validate(bad);
      const zodBad = !zod.safeParse(bad).success;
      // If only one side rejects, the contract has drifted. Both must reject.
      expect(ajvBad && zodBad).toBe(true);
    });
  }
});

describe("drift sentinel — direct field-level checks", () => {
  it("SignResponse.required includes binding_hash + brief_content_hash", () => {
    const schema = snapshot.models.SignResponse as {
      required?: string[];
    };
    expect(schema.required).toContain("binding_hash");
    expect(schema.required).toContain("brief_content_hash");
  });

  it("ErrorResponse declares request_id (v3.6 addition)", () => {
    const schema = snapshot.models.ErrorResponse as {
      properties?: Record<string, unknown>;
    };
    expect(schema.properties).toHaveProperty("request_id");
  });

  it("PendingBriefEntry status is the four-value enum", () => {
    // PendingBriefResponse → items → PendingBriefEntry → status
    const pending = snapshot.models.PendingBriefResponse as Record<
      string,
      unknown
    >;
    const defs = (pending as { $defs?: Record<string, unknown> }).$defs;
    expect(defs).toBeTruthy();
    // Pydantic embeds the BriefStatus enum somewhere under $defs. We
    // search the JSON for the four values rather than over-coupling
    // to pydantic's exact nesting.
    const text = JSON.stringify(pending);
    for (const value of ["drafted", "reviewed", "pending_review", "signed"]) {
      expect(text).toContain(`"${value}"`);
    }
  });
});
