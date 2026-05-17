# Directora handoff (v3.7)

This is the final Directora-side document. After v3.7 ships, all future
work moves to LabBrief integration. This handoff captures everything
LabBrief needs to wire up the engine: contract, headers, retry policy,
hash verification, auth modes, observability, and a step-by-step
checklist.

---

## 1. Architecture overview

**What Directora does**

- Translates an AI Visibility Receipt into a Scrutexity Authority Brief.
- Runs the Authority Review (multi-persona) layer and produces a
  clinic-facing Authority Review Summary.
- Drafts five Authority Asset types plus an Owner Brief snippet and a
  Provider Brief snippet.
- Persists the Provider Brief canonical JSON + content hash at
  generation time.
- Exposes a small HTTP API that lets LabBrief list pending briefs,
  fetch the canonical Provider Brief, and sign briefs against the
  Governed Workflow Ledger.

**What Directora does NOT do**

- It does not store PHI. Patient identifiers are reduced to
  `patient_ref` / `encounter_ref` upstream.
- It does not render video. The Quality Render Step is optional and
  non-blocking.
- It does not host LabBrief assets, run authentication issuance, or
  host the JWKS endpoint.
- It does not ship Treatment Plan signing — namespace reserved.

**System boundary**

```
AI Visibility Receipt  →  Authority Engine  →  Brief Store + Ledger  →  Brief API
                                                                          │
                                                                          ▼
                                                                    LabBrief UI
```

LabBrief never writes to the brief store, the ledger, or the
idempotency store directly. All writes go through the API.

---

## 2. API contract (what LabBrief calls)

The single source of truth is `shared/brief-api-contract.json`
(versioned, includes `version` + `generated_at`). Pydantic v2 generates
it from the same models the FastAPI app uses; the contract test
fails on any drift.

### Endpoints

```
GET  /health                                  health + version + backends
GET  /metrics                                 Prometheus exposition (prod auth)
GET  /api/brief/pending                        list pending briefs
GET  /api/brief/provider?brief_id=…            canonical Provider Brief snippet
POST /api/brief/sign                           sign a brief (idempotent, hash-bound)
GET  /api/labs/audit?brief_id=…                append-only ledger view
```

### Required request headers

| Header              | Used on             | Meaning                                                                 |
| ------------------- | ------------------- | ----------------------------------------------------------------------- |
| `Authorization`     | every request       | `Bearer <token>` — stub-encoded JSON or JWT depending on `AUTH_MODE`.   |
| `X-Clinic-ID`       | every request       | Caller's clinic id. Must match the principal's clinic.                  |
| `X-Request-ID`      | optional            | Opaque correlation id. Echoed on every response. Generated if absent.   |
| `Idempotency-Key`   | `POST /api/brief/sign` only | Per-attempt UUIDv4 — `sign-{briefId}-{crypto.randomUUID()}`.       |

### Response headers (always present)

| Header                      | Meaning                                                                        |
| --------------------------- | ------------------------------------------------------------------------------ |
| `X-Request-ID`              | Echo of the request id, generated if the client didn't send one.               |
| `X-Contract-Version`        | The contract snapshot version this engine instance produced the response from. |

### Response headers (situational)

| Header                      | When                                                       |
| --------------------------- | ---------------------------------------------------------- |
| `X-Idempotency-Replayed: true` | `POST /api/brief/sign` returned a replay of an earlier 200. |
| `Retry-After: 1`            | `POST /api/brief/sign` returned `503 idempotency_store_busy`. |

### Error response shape

```json
{
  "error": "<error_code>",
  "detail": "<optional human-readable detail>",
  "ledger_event_id": "<optional ledger event id (already_signed)>",
  "request_id": "<X-Request-ID>"
}
```

### Error codes

| HTTP | `error`                       | Meaning                                                                 | Retry? |
| ---- | ----------------------------- | ----------------------------------------------------------------------- | ------ |
| 401  | `missing_bearer_token`        | No `Authorization` header.                                              | no     |
| 401  | `invalid_token`               | Token failed verification (HS256 / JWKS).                               | no     |
| 401  | `token_expired`               | JWT past `exp`.                                                         | no     |
| 401  | `metrics_unauthorized`        | Production `/metrics` without `METRICS_TOKEN`.                          | no     |
| 403  | `clinic_mismatch`             | Principal's clinic doesn't match `X-Clinic-ID` or the brief's clinic.   | no     |
| 403  | `permission_denied`           | Provider isn't assigned to brief and isn't a medical director.          | no     |
| 404  | `brief_not_found`             | Brief id doesn't exist.                                                 | no     |
| 409  | `already_signed`              | Brief already signed (response includes `ledger_event_id`).              | no     |
| 409  | `invalid_status`              | Brief isn't in `pending_review` (e.g. `stale_engine_context` detail).    | no     |
| 409  | `idempotency_conflict`        | Same `Idempotency-Key`, different body.                                  | no     |
| 422  | `invalid_signature`           | Pydantic / signature bounds rejected the request.                       | no     |
| 503  | `idempotency_store_busy`      | SQLite contention; response carries `Retry-After: 1`.                    | **YES** |
| 500  | `engine_or_ledger_failure`    | Server failure not covered above.                                       | conservative retry OK |

### Contract snapshot

- Location: `shared/brief-api-contract.json` (relative to the repo
  root). Symlink it into LabBrief or copy it on every release.
- Includes top-level `version` (must equal `CONTRACT_VERSION` in
  `directora/api/contract.py`) and `generated_at`.
- LabBrief's `src/schemas/contract.ts` mirrors the snapshot via Zod.
- LabBrief's parity test (`src/schemas/contract.test.ts`) compiles the
  snapshot with ajv and confirms both sides agree on representative
  payloads.

---

## 3. Auth modes

Selected by the `AUTH_MODE` env var. The `resolve_principal` interface
is identical across modes — only the resolver implementation changes.

### `stub` (dev / local tests)

A base64-encoded JSON blob `{provider_id, clinic_id, roles}`. No
cryptographic verification. Production refuses to serve traffic with
`AUTH_MODE=stub`.

Generate:
```python
from directora.api.auth import encode_stub_token
encode_stub_token("PRV_123", "CLN_456")
```

### `hs256` (staging / single-tenant prod)

Symmetric HS256 JWT. Requires `JWT_SECRET_KEY` and (optionally)
`JWT_ISSUER`. Expected claims: `sub`, `clinic_id`, `roles`, `iat`,
`exp`, `jti`, `iss`. The legacy value `AUTH_MODE=jwt` is accepted as
an alias for `hs256`.

Generate dev tokens:
```python
from directora.api.auth import generate_dev_token
generate_dev_token("PRV_123", "CLN_456")
```

### `jwks` (production — recommended)

RS256 JWT verified against a JWKS endpoint. Required env: `JWKS_URL`.
The resolver:

- Caches keys for `JWKS_CACHE_TTL_SECONDS` (default `600`, configurable).
- Enforces `kid` in the JWT header — tokens without `kid` are rejected.
- Accepts only `alg: RS256`. Forged HS256 tokens are rejected.
- Fails closed: JWKS fetch failures yield `401 invalid_token` rather
  than 500. Production never masquerades a verification failure as a
  server error.

---

## 4. Database architecture

### Brief store

- SQLite at `DIRECTORA_BRIEF_DB_PATH` (default `./.directora/briefs.db`).
- Schema: one `briefs` table keyed by `brief_id`; canonical Provider
  Brief JSON + `brief_content_hash` stored at generation time.
- WAL journaling, `BEGIN IMMEDIATE` transactions; concurrent-sign
  test asserts one 200 + one 409.
- `BRIEF_STORE_BACKEND` env switch: `sqlite` (default) / `jsonl` /
  `memory`.
- One-shot JSONL → SQLite migration via
  `python -m directora.scrutexity.brief_store_migrate`.

### Idempotency store

- SQLite at `IDEMPOTENCY_DB_PATH` (default
  `./.directora/idempotency.db`). Multi-worker safe.
- Stores the full response body as canonical JSON so replay is
  byte-identical.
- WAL journaling + 100 ms busy timeout. On busy, the API translates
  to `503 + Retry-After: 1` instead of 500.
- `IDEMPOTENCY_STORE_BACKEND` env switch: `sqlite` (default) /
  `memory` (single-worker dev only).

### Governed Workflow Ledger

- Append-only JSONL by default. Configurable via
  `DIRECTORA_TELEMETRY_SINK` (`jsonl` / `memory` / `noop`).
- Event kinds include `provider_brief_signed` and the neutral
  `provider_brief_finalize_failed`.
- **There is NO `provider_brief_signed_rollback` kind.** Finalize
  failures use a neutral note. The ledger does not frame anything as
  compensation.

---

## 5. Observability

### `/health`

Returns 200 healthy / 503 degraded. Body includes:

```json
{
  "status": "healthy",
  "contract_version": "3.7.0",
  "engine_release": "3.7.1",
  "env": "production",
  "store_backend": "sqlite",
  "idempotency_backend": "sqlite",
  "auth_mode": "jwks",
  "checks": {
    "brief_db": true,
    "idempotency_db": true,
    "contract_snapshot": true,
    "signing_secret_configured": true
  }
}
```

`contract_version` is the consumer-facing API contract version (bumps
on response shape change). `engine_release` is the ops patch level
(bumps on every engine release). v3.7.1 renamed the legacy bare
`version` field for clarity — see `CHANGELOG.md`.

Wire k8s / load-balancer readiness + liveness probes against this
endpoint.

### `/metrics` (Prometheus)

Canonical metric names exposed:

```
http_requests_total{route,method,status}
http_request_duration_seconds_bucket{route,method,le}    # via histogram
http_request_duration_seconds_count{route,method}
http_request_duration_seconds_sum{route,method}

brief_sign_total{result="signed|already_signed|idempotency_conflict|invalid_status|engine_or_ledger_failure"}

idempotency_replay_total
sqlite_busy_total
ledger_append_fail_total

briefs_pending
briefs_signed
contract_version_info{version}
```

Production auth: bearer `METRICS_TOKEN` env. Without the env, prod
`/metrics` returns 500 by design (fail closed).

### `X-Request-ID` propagation

Every request gets a `X-Request-ID` (generated if absent). Every
response — including errors — echoes it on the header AND injects it
into the JSON error body. LabBrief should surface this in a dev-only
"Error Details" panel.

### Chaos switches (dev/test only)

| Env var                        | Effect                                                  |
| ------------------------------ | ------------------------------------------------------- |
| `FAULT_LEDGER_APPEND=1`        | Ledger appends fail. Tests assert no signed state.      |
| `FAULT_DB_LOCK=1`              | Idempotency store raises busy → 503 + Retry-After.      |
| `FAULT_CONTRACT_MISMATCH=1`    | Reserved for drift drills.                              |

Never set in production.

---

## 6. Deployment

Read `DEPLOYMENT.md` for the production runbook (env vars, DB setup,
CORS, multi-worker, smoke verification, rollback procedure).

### Quick environment cheat sheet

```bash
ENV=production
AUTH_MODE=jwks
JWKS_URL=https://auth.scrutexity.com/.well-known/jwks.json
JWT_ISSUER=scrutexity-auth

BRIEF_STORE_BACKEND=sqlite
DIRECTORA_BRIEF_DB_PATH=/var/lib/directora/briefs.db
IDEMPOTENCY_STORE_BACKEND=sqlite
IDEMPOTENCY_DB_PATH=/var/lib/directora/idempotency.db

DIRECTORA_CLINIC_SIGNING_SECRET_CLN_456=…

CORS_ALLOW_ORIGINS=https://labbrief.example.com
METRICS_TOKEN=…
```

---

## 7. LabBrief wiring checklist

This is the exact sequence LabBrief follows to wire onto a fresh
Directora v3.7 deployment.

### 7a. Environment

```dotenv
# labbrief/.env.local
VITE_BRIEF_API_BASE=https://api.scrutexity.example.com
```

### 7b. Required headers on every request

| Header              | Required? | Value                                                                     |
| ------------------- | --------- | ------------------------------------------------------------------------- |
| `Authorization`     | yes       | `Bearer <token>` (JWT in prod).                                            |
| `X-Clinic-ID`       | yes       | Caller's clinic id.                                                        |
| `X-Request-ID`      | recommended | UUIDv4 per HTTP request; echoed back so LabBrief can log it.             |
| `Idempotency-Key`   | `POST /api/brief/sign` only | `sign-{briefId}-{crypto.randomUUID()}` per attempt.       |

`Idempotency-Key` MUST be generated **once per attempt** and reused
across retries of the same attempt. Do NOT derive from `session_id`
or any volatile value.

### 7c. Retry policy

LabBrief retries ONLY when the response is `503`, `429`, or a network
timeout. **Reuse the same `Idempotency-Key`** across retries of the
same attempt; the engine returns a byte-identical replay with
`X-Idempotency-Replayed: true`.

| Status | Retry? | Notes |
| ------ | ------ | ----- |
| 503 (`idempotency_store_busy`) | **YES** | Honour the `Retry-After: 1` header. Up to 3 attempts. Same `Idempotency-Key`. |
| 429 (any) | **YES** | Same key. Honour `Retry-After` if present. |
| network timeout | **YES** | Same key. Backoff: 250 ms, 1 s, 4 s. |
| 409 (`already_signed`) | NO | Authoritative; show the audit trail. |
| 409 (`idempotency_conflict`) | NO | Client bug — generated the same key with different bodies. Refresh + retry. |
| 422 (`invalid_signature`) | NO | Validation. Reopen the signing UI. |
| 401 (`token_expired`) | NO | Re-auth flow. |
| 401 (`invalid_token`) | NO | Sign out + re-auth flow. |
| 4xx other | NO | Surface the error code + `request_id`. |
| 5xx other | NO | Surface the error code + `request_id`. |

### 7d. Client-side hash verification

The engine sets `brief_content_hash` on every `POST /api/brief/sign`
response. LabBrief can independently verify it before trusting the
sign-off:

1. `GET /api/brief/provider?brief_id={id}` returns `{ canonical_json, brief_content_hash }`.
2. Compute `sha256(utf8(canonical_json))` client-side.
3. Compare to `brief_content_hash`.
4. If they match, the sign-off bound to that hash genuinely signed the
   canonical artifact.

```ts
async function verifyBriefHash(briefId: string): Promise<boolean> {
  const res = await briefClient.getProviderBrief(briefId);
  const expected = res.brief_content_hash;
  const buf = new TextEncoder().encode(res.canonical_json);
  const digest = await crypto.subtle.digest("SHA-256", buf);
  const hex = Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
  return hex === expected;
}
```

The canonical JSON is generated by `canonical_dumps`: sort_keys=True,
separators=(",", ":"), ensure_ascii=False, allow_nan=False. Any
JSON.stringify on the client must NOT be used to re-encode — round-trip
the `canonical_json` string from the API directly.

### 7e. Using observability headers

| Header                     | LabBrief use                                                         |
| -------------------------- | -------------------------------------------------------------------- |
| `X-Request-ID`             | Log it on every API call. Surface in dev-only Error Details panel.   |
| `X-Contract-Version`       | Log on first response of session. Warn if it differs from the snapshot version Zod compiled against. |
| `X-Idempotency-Replayed`   | Render a small "Replayed" indicator on the sign-off success toast.   |
| `Retry-After`              | Schedule the next retry timer with this value as the floor.          |

### 7f. UI copy table for error codes

See `labbrief_kit/src/api/errorMessages.ts` — covers every code listed
in §2. Update there if marketing/clinical revises the copy.

### 7g. Verification after wiring

Run the smoke test from a LabBrief dev machine:

```bash
curl -s http://localhost:8000/health | jq .
curl -s http://localhost:8000/api/brief/pending \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Clinic-ID: CLN_456" -i | grep -E "X-Contract-Version|X-Request-ID"
```

Both headers must appear. Then drive the full sign flow from the
LabBrief UI and confirm:

- 200 on first sign with `X-Contract-Version`.
- 200 on replay with `X-Idempotency-Replayed: true`.
- 409 `already_signed` on a second attempt with a different key.

### 7h. Common failure modes

| Symptom | Likely cause |
| --- | --- |
| `401 invalid_token` on every request | Wrong issuer, missing `kid` (JWKS), or `AUTH_MODE` mismatch. |
| `401 missing_bearer_token` | Header not attached or wrong scheme. |
| `403 clinic_mismatch` | `X-Clinic-ID` doesn't match the principal's clinic. |
| `400 missing_idempotency_key` | LabBrief forgot to attach `Idempotency-Key` to `POST /sign`. |
| `409 idempotency_conflict` | Same key sent with different bodies — client bug. |
| `503 idempotency_store_busy` (no Retry-After) | Reverse proxy stripped the header. Configure it to preserve `Retry-After`. |
| Contract version mismatch warning | Snapshot wasn't re-copied after a Directora deploy. Pull the new snapshot. |

---

## 8. What's reserved (not yet shipped)

- **Treatment Plan signing.** Event-kind namespace reserved
  (`treatment_plan_*`); schema stubs in `directora/api/schemas.py`;
  `/api/treatment-plan/*` routes return 404.
- **PDF export of Provider Brief.** Canonical JSON is what the hash
  binds. PDF rendering would be a future engine node, not API work.
- **Full multi-tenant isolation.** Per-clinic SQLite shards / row-level
  isolation. Today every clinic shares one SQLite file; the PHI guard
  + `clinic_id` enforcement prevents cross-clinic data leakage at the
  API layer.

---

## 9. Contact / escalation

- **Source code** lives in the scrutexity_addon repo. The Directora
  side is under `directora/`; the LabBrief integration kit is under
  `labbrief_kit/`; the shared contract snapshot is at
  `shared/brief-api-contract.json`.
- **Tests**: `python -m pytest` from the addon root. Smoke test:
  `python smoke_test.py`. Load test: `locust --config tests/load/locust.conf`.
- **Runbook**: `DEPLOYMENT.md`.
- **Drift**: any contract change MUST bump `CONTRACT_VERSION` in
  `directora/api/contract.py` AND regenerate `shared/brief-api-contract.json`.
  The contract test (`tests/api/test_contract.py`) fails loudly if
  these get out of sync.
- **Auditability**: the Governed Workflow Ledger is append-only.
  Nothing is ever deleted; finalize failures are recorded as a
  neutral note (`provider_brief_finalize_failed`), never as a
  compensation event.

After v3.7, all Directora work freezes. Open issues go to LabBrief.
