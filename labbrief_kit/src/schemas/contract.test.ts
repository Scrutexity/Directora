/**
 * contract.test.ts — parity test between Zod schemas and the
 * shared JSON Schema snapshot.
 *
 * Runs in Vitest. Loads the snapshot, compiles each named JSON Schema
 * with ajv, then verifies that representative valid + invalid payloads
 * agree between Zod and ajv. This is a coarse drift detector — when
 * the Directora contract changes, both Zod and the snapshot must
 * update or this test fails.
 *
 * Place at `src/schemas/contract.test.ts` (or wherever your Vitest
 * config picks up tests). Make sure the snapshot path matches your
 * repo layout.
 */
import { describe, it, expect } from "vitest";
import Ajv from "ajv";
import addFormats from "ajv-formats";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import {
  PendingBriefResponseSchema,
  SignBriefResponseSchema,
  AuditResponseSchema,
  ProviderBriefResponseSchema,
  ErrorResponseSchema,
} from "./contract";

const SNAPSHOT_PATH = resolve(__dirname, "../../../shared/brief-api-contract.json");

interface Snapshot {
  version: string;
  models: Record<string, object>;
}

const snapshot: Snapshot = JSON.parse(readFileSync(SNAPSHOT_PATH, "utf-8"));
const ajv = new Ajv({ strict: false, allErrors: true });
addFormats(ajv);

const sampleResponses: Record<string, { good: object; zod: any }> = {
  PendingBriefResponse: {
    zod: PendingBriefResponseSchema,
    good: {
      items: [
        {
          brief_id: "BRF_TEST_01",
          provider_id: "PRV_TEST",
          clinic_id: "CLN_TEST",
          status: "pending_review",
          created_at: 1747432893.0,
          updated_at: 1747432893.0,
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
            provider_brief_preview: { headline: "Provider Brief: ..." },
            claim_risk: { items: ["Avoid guaranteed results"] },
          },
          links: {
            audit: "/api/labs/audit?brief_id=BRF_TEST_01",
            detail: "/api/brief/provider?brief_id=BRF_TEST_01",
            provider: "/api/brief/provider?brief_id=BRF_TEST_01",
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
      ledger_event_id: "evt_abc",
      signed_at: "2026-05-16T17:01:33.000Z",
      brief_content_hash: "a".repeat(64),
      binding_hash: "b".repeat(64),
      next_actions: {
        export: "/api/brief/provider?brief_id=BRF_TEST_01",
        audit: "/api/labs/audit?brief_id=BRF_TEST_01",
      },
    },
  },
  AuditResponse: {
    zod: AuditResponseSchema,
    good: {
      brief_id: "BRF_TEST_01",
      events: [
        {
          event_id: "evt_abc",
          kind: "provider_brief_signed",
          ts: 1747432893.0,
          brief_id: "BRF_TEST_01",
        },
      ],
    },
  },
  ProviderBriefResponse: {
    zod: ProviderBriefResponseSchema,
    good: {
      asset_type: "provider_brief_snippet",
      brief_content_hash: "a".repeat(64),
      canonical_json: "{\"asset_type\":\"provider_brief_snippet\"}",
      snippet: { headline: "Provider Brief: ..." },
    },
  },
  ErrorResponse: {
    zod: ErrorResponseSchema,
    good: {
      error: "already_signed",
      ledger_event_id: "evt_abc",
      request_id: "req_xyz",
    },
  },
};

describe("brief-api-contract.json ↔ Zod schema parity", () => {
  it("snapshot is loadable and versioned", () => {
    expect(snapshot.version).toBeTruthy();
    expect(snapshot.models).toBeTruthy();
  });

  for (const [name, { good, zod }] of Object.entries(sampleResponses)) {
    it(`${name}: ajv-snapshot AND Zod both accept a representative payload`, () => {
      const schema = snapshot.models[name];
      expect(schema, `snapshot missing ${name}`).toBeTruthy();
      const validateAjv = ajv.compile(schema as any);

      const ajvOk = validateAjv(good);
      if (!ajvOk) {
        throw new Error(
          `ajv rejected snapshot-conformant payload for ${name}: ` +
            JSON.stringify(validateAjv.errors),
        );
      }
      const zodOk = zod.safeParse(good);
      if (!zodOk.success) {
        throw new Error(
          `Zod rejected snapshot-conformant payload for ${name}: ` +
            JSON.stringify(zodOk.error.issues),
        );
      }
    });

    it(`${name}: ajv-snapshot AND Zod both reject a malformed payload`, () => {
      const schema = snapshot.models[name];
      const validateAjv = ajv.compile(schema as any);
      const bad: any = { ...good, status: 12345 }; // mostly nonsense
      const ajvBad = !validateAjv(bad);
      const zodBad = !zod.safeParse(bad).success;
      // Both sides should reject; if only one does, the contract has drifted.
      expect(ajvBad && zodBad).toBe(true);
    });
  }
});
