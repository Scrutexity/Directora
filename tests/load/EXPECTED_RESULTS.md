# Load test pass/fail gates — sign-off path

These gates are the explicit success criteria for the sign-off load
test. **A run that violates any gate is a regression that blocks ship.**
The qualitative shape comes from the SQLite + idempotency design;
the numeric thresholds are the values we hold ourselves to.

## Pass/fail gates

| Gate | Threshold | Notes |
| --- | --- | --- |
| **G1. p95 sign latency under nominal load** | ≤ 250 ms | 50 vu / 60s / single uvicorn worker / local SQLite. Adjust the target downward when running on dedicated hardware. |
| **G2. p99 sign latency under nominal load** | ≤ 750 ms | Same setup as G1. |
| **G3. Zero 500s** | 0 | Under nominal load (no fault injection). Any 500 is a regression. |
| **G4. 503s only when DB is locked** | 503s carry `Retry-After: 1` and only appear when the FAULT_DB_LOCK switch is on, OR when sustained contention triggers real SQLite busy events. Missing `Retry-After` is a fail. |
| **G5. Idempotency replay byte-identical** | 100% | Every `X-Idempotency-Replayed: true` response body equals the original 200 byte-for-byte. The load script's `replayed` counter increases monotonically; `replay_mismatch` (not yet defined) is zero. |
| **G6. At most one signed event per brief** | ≤ 1 | For any seeded brief id, the audit ledger has exactly one `provider_brief_signed` event. The load script's `unexpected` counter remains zero. |
| **G7. `unexpected` counter zero** | 0 | Anything outside the canonical outcomes (200, 409 already_signed, 409 idempotency_conflict, 503 with Retry-After) is a failure. |

## Setup

1. Run Directora locally:
   ```bash
   export AUTH_MODE=stub
   export DIRECTORA_CLINIC_SIGNING_SECRET_DEFAULT=load-secret
   export ENV=development
   uvicorn directora.api.server:app --host 0.0.0.0 --port 8000
   ```
2. Seed 50 briefs (`BRF_LOAD_000` … `BRF_LOAD_049`) into the SQLite
   store via your fixture helper. The load script does not seed.
3. Generate a stub auth token and export it:
   ```bash
   export LOAD_STUB_TOKEN=$(python -c "from directora.api.auth import encode_stub_token; print(encode_stub_token('PRV_LOAD','CLN_LOAD'))")
   ```
4. Run:
   ```bash
   locust --config tests/load/locust.conf
   ```

## Counters surfaced by the test script

```
=== sign-off load test summary ===
  ok:                       <N>     # 200 OK signs
  already_signed:           <N>     # 409 — brief was already signed
  idempotency_conflict:     <N>     # 409 — same key, different body
  db_busy_503:              <N>     # 503 with Retry-After (G4)
  missing_retry_after:      0       # ← G4: must remain 0
  replayed:                 <N>     # 200 + X-Idempotency-Replayed: true (G5)
  unexpected:               0       # ← G7: must remain 0
```

If you also want to assert G1/G2 latency gates programmatically, parse
the `tests/load/results_stats.csv` artifact locust writes when
`--csv tests/load/results` is set, and read the p95/p99 columns for the
`POST /api/brief/sign (unique)` row.

## What this load test does NOT validate

- **PHI guard** — covered by unit tests; not exercisable via HTTP.
- **JWT auth** — load test uses stub mode by design. Production-mode
  auth is covered by `tests/api/test_auth_jwks.py`.
- **Cross-clinic isolation** — single clinic id per run.

## Production safety

Never run this load test against a production engine. The script
deliberately drives 503 backpressure and is designed to stress SQLite
contention. The local Directora dev process is the only valid target.
