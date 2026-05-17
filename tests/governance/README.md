# Governance checks — single-command proof of the Scrutexity architecture

[Verify Locally](#verify-locally) · [Wire Contract](#wire-contract) · [Test Counts](#test-counts) · [File Tree](#file-tree) · [Invariants](#invariants) · [Threat Model](#threat-model) · [Follow-ups](#follow-ups) · [Extension Recipe](#extension-recipe)

---


Two scripts in this directory:

| Script | Scope |
|---|---|
| `directora-governance-check.sh` | Engine-side proofs (7 assertions against a running Directora). |
| `ultimate-governance-check.sh` | Meta-runner. Runs both halves: Directora script + LabBrief contract drift detector. Auto-detects layout, soft-skips on missing tooling unless `STRICT=1`. |

The two auditor-grade tests for the v3.7 patch live in
`labbrief_kit/src/__tests__/`:

| Test | Proves |
|---|---|
| `retry.test.ts::"uses the SAME Idempotency-Key on attempt 1, 2, and 3"` | Two 503s before success → the captured `Idempotency-Key` header is byte-identical across all three attempts. |
| `idempotencyKeyStore.test.ts::"simulates a real retry flow"` | After a 503, the store still holds the same key. After a 200, a subsequent `getOrCreateIdempotencyKey` returns a fresh value. |
| `contractDriftDetector.test.ts` | snapshot ↔ Zod parity, version match against `EXPECTED_CONTRACT_VERSION`, drift sentinels for `SignResponse.required`, `ErrorResponse.request_id`, and `BriefStatus` enum. |

## What it proves

| # | Assertion | Method |
|---|---|---|
| 1 | Happy-path sign-off returns 200 with `ledger_event_id` + `binding_hash` | POST `/api/brief/sign` |
| 2 | Every response carries `X-Contract-Version` matching the expected version | GET `/api/brief/pending` |
| 3 | Replay with the same `Idempotency-Key` returns a byte-identical body + `X-Idempotency-Replayed: true` | Two replay POSTs + a third for the header |
| 4 | Same key + different body returns `409 idempotency_conflict` | POST with altered signature |
| 5 | Different key on a signed brief returns `409 already_signed` with the original `ledger_event_id` | POST with fresh key |
| 6 | **Chaos** — `FAULT_LEDGER_APPEND=1` causes `500 engine_or_ledger_failure`, the brief stays in `pending_review`, **zero ledger events** for the failed brief, **zero rollback events** anywhere | Restart Directora with the env var; assert via `/api/labs/audit` |
| 7 | `/health` returns `healthy` | GET `/health` |

## Prerequisites

Hosts:

- `curl`, `jq`, `uuidgen`, `python3`
- A running Directora at `http://localhost:8000` (override with `BASE`)
- For test 6 (chaos): permission to kill and restart the Directora
  process locally. Set `RUN_CHAOS=0` to skip it.

Directora-side environment expected by default:

```bash
ENV=development
AUTH_MODE=stub
DIRECTORA_CLINIC_SIGNING_SECRET_DEFAULT=governance-seed-secret
BRIEF_STORE_BACKEND=sqlite
DIRECTORA_BRIEF_DB_PATH=./.directora/briefs.db
```

## Running

```bash
# 1. Start Directora locally:
uvicorn directora.api.server:app --host 0.0.0.0 --port 8000

# 2. From a second shell, run the governance check:
./tests/governance/directora-governance-check.sh
```

### Or run both halves at once

```bash
./tests/governance/ultimate-governance-check.sh
```

The meta-runner auto-detects:

- the Directora script under `tests/governance/`, `./directora/`, or the cwd
- a LabBrief tree at `./labbrief/` or `./labbrief_kit/`
- the drift-detector test file (`contractDriftDetector.test.ts` →
  `contractGating.test.ts` → `schemas/contract.test.ts`, first match wins)

It exits non-zero on real failure and soft-skips when tooling is
missing. Use `STRICT=1` to convert skips into failures.

Override paths if your layout is different:

```bash
DIRECTORA_SCRIPT=/path/to/directora-governance-check.sh \
  LABBRIEF_DIR=/path/to/labbrief \
  VITEST_TEST=src/__tests__/contractDriftDetector.test.ts \
  ./tests/governance/ultimate-governance-check.sh
```

To skip the chaos test (e.g. when running against a remote engine you
don't control):

```bash
RUN_CHAOS=0 ./tests/governance/directora-governance-check.sh
```

To run against a different deployment:

```bash
BASE=https://api.scrutexity.example.com \
  EXPECTED_CONTRACT_VERSION=3.7.0 \
  TOKEN=<your-jwt> \
  PROVIDER_ID=PRV_REAL \
  CLINIC_ID=CLN_REAL \
  RUN_CHAOS=0 \
  ./tests/governance/directora-governance-check.sh
```

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `BASE` | `http://localhost:8000` | Directora base URL |
| `EXPECTED_CONTRACT_VERSION` | `3.7.0` | Asserted against `X-Contract-Version` |
| `AUTH_MODE` | `stub` | One of `stub` / `hs256` / `jwks`. If `TOKEN` is set, this is ignored. |
| `TOKEN` | (auto-generated) | Pre-issued bearer token. Useful for JWKS deployments. |
| `PROVIDER_ID` | `PRV_GOV` | Caller's provider id |
| `CLINIC_ID` | `CLN_GOV` | Caller's clinic id |
| `BRIEF_HAPPY` | `BRF_GOV_01` | Brief id used by tests 1–5 |
| `BRIEF_CHAOS` | `BRF_GOV_02` | Brief id used by test 6 (chaos) |
| `RUN_CHAOS` | `1` | Set `0` to skip test 6 |
| `SEED` | `1` | Set `0` to skip the seed step if your environment already has the briefs |
| `DIRECTORA_CMD` | `uvicorn directora.api.server:app --host 0.0.0.0 --port 8000` | Command the chaos test uses to restart Directora |

## What the script changed vs the original spec

Two corrections were needed against our v3.7 build:

1. **Entry point**: our app starts via `uvicorn directora.api.server:app`,
   not `python -m directora` (we don't ship a `__main__.py`). The
   `DIRECTORA_CMD` env var makes this overridable.
2. **Audit field name**: the audit ledger event field is `kind`, not
   `event_type`. The rollback check now uses `.events[].kind` so it
   genuinely catches a stray `*_rollback` kind if one ever returns.

We also seed `BRF_GOV_01` + `BRF_GOV_02` via `seed_governance_fixtures.py`
because the engine doesn't have BRF_GOV_* by default — the helper
drives the real `provider_brief_node` so the persisted canonical JSON
matches what the running engine produces.

## CI integration

The script is bash-syntax-checked via
`tests/governance/test_governance_script_syntax.py` so the regular
pytest suite catches breakage at commit time without requiring a live
engine. The full E2E run remains a post-deploy step.

```bash
# CI-friendly bash-syntax check (no live engine needed):
python -m pytest tests/governance/test_governance_script_syntax.py
```

---

## Verify Locally

The fastest path from a clean checkout to a green proof:

```bash
# 1. Start the engine in one terminal.
export DIRECTORA_CLINIC_SIGNING_SECRET_DEFAULT=governance-seed-secret
uvicorn directora.api.server:app --host 0.0.0.0 --port 8000

# 2. In a second terminal, run the meta-runner.
./tests/governance/ultimate-governance-check.sh
```

The Directora half (9 tests) runs first; if `npx` + a LabBrief tree
are detected, the contract drift detector runs next. `STRICT=1`
converts soft skips into hard failures.

## Wire Contract

`shared/brief-api-contract.json` is the single source of truth for the
shapes both sides exchange. The bash script asserts every response
header still carries `X-Contract-Version` equal to the snapshot's
`version` field; the vitest drift detector verifies the Zod schemas
parse the same shapes the snapshot defines. Bump
`CONTRACT_VERSION` in `directora/api/contract.py` AND regenerate the
snapshot in lockstep with every API shape change.

## Test Counts

| Layer | Count | Source |
|---|---|---|
| Directora pytest | 252 | `python -m pytest` from the addon root |
| Smoke E2E (in-process) | 25 / 25 checks | `python smoke_test.py` |
| Governance bash | 9 (or 7 with `RUN_CHAOS=0`) | `directora-governance-check.sh` |
| LabBrief vitest | 17 in `contractDriftDetector.test.ts` + ~30 across the kit | `npx vitest run` in `labbrief_kit/` |
| Governance pytest gates | 15 | `tests/governance/test_governance_script_syntax.py` |

## File Tree

```
tests/governance/
├── README.md                         this file
├── directora-governance-check.sh     9-test E2E proof against a running engine
├── ultimate-governance-check.sh      meta-runner — bash + vitest in one command
├── seed_governance_fixtures.py       seeds BRF_GOV_01 + BRF_GOV_02
└── test_governance_script_syntax.py  pytest gates for the bash scripts
labbrief_kit/src/__tests__/
└── contractDriftDetector.test.ts     snapshot ↔ Zod drift detector
```

## Invariants

The script proves these never break:

- **Atomicity** — `record_outcome` failure leaves the brief in
  `pending_review`, with zero ledger events for the failed sign.
- **Idempotency** — every replay of `(Idempotency-Key, body)` returns
  the byte-identical 200 body the original call produced. Verified by
  3-way `cmp -s` against the original sign body.
- **Hash binding** — `brief_content_hash` is locked at
  `provider_brief_ready` time. The local SHA-256 of the
  `canonical_json` returned from `/api/brief/provider` equals the
  hash reported by `/api/brief/sign`. The HMAC binding is anchored
  to a stable artifact, not a transient render.
- **Contract versioning** — every response (GET, POST, replay, 503)
  carries `X-Contract-Version` matching the snapshot.
- **Backpressure** — SQLite-busy translates to 503 with a numeric
  `Retry-After` and `X-Request-ID`, never to 500.
- **No rollback events** — finalize failures use a neutral note
  (`provider_brief_finalize_failed`), not a compensation kind.
- **Multi-worker safety** — `idempotency_backend=memory` is forbidden
  when `ENV=production` (single-worker only).

## Threat Model

The governance check is a *proof of compliance*, not a security
scanner. It explicitly does NOT cover:

- TLS configuration / cert validity
- Auth bypass (the stub mode is dev-only by design; production refuses
  to serve under stub)
- PHI in logs (covered by the response-shape PHI guard inside the
  engine; this script does not inspect log files)
- DoS resilience beyond a single FAULT_DB_LOCK probe

The check assumes the operator has chosen the right deploy posture
(JWKS auth, SQLite backends, CORS allow-list, signing-secret rotation
via env var or KMS). It catches operator regressions in those areas,
it does not configure them.

## Follow-ups

- 503 storm test (concurrent sign against the same brief) — currently
  covered in `tests/test_brief_store_sqlite.py` at the store layer; an
  HTTP-level storm sub-test in this script would be additive but
  expensive.
- Health-endpoint probe ergonomics (k8s readiness/liveness) — covered
  by `/health` in `DEPLOYMENT.md`; no separate governance test
  scheduled.
- Prometheus scrape sanity (`/metrics` reachable + canonical names) —
  covered by `tests/api/test_metrics.py`; an end-to-end metric-value
  assertion would be expensive and is left to staging-time scrape
  verification.

## Extension Recipe

To add a new governance assertion:

1. Open `directora-governance-check.sh` and add a numbered test block
   between the existing tests (or at the end before the success
   summary). Use `assert_contract_header` for any new response-header
   check.
2. Update the success-summary `Proved:` list.
3. Add a pytest gate in `test_governance_script_syntax.py` that
   asserts the new test's distinctive string is present. The gate
   prevents accidental removal.
4. Document the assertion in this README's "Invariants" section.
5. Run `python -m pytest tests/governance/` from the addon root to
   confirm the gate passes.
