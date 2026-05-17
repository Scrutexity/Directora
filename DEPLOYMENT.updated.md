# Scrutexity Authority Engine — Deployment Runbook (v3.6)

Production deployment of the Directora Brief API.

The engine ships as a stateless FastAPI app backed by two SQLite databases and a versioned contract snapshot. Multi-worker safe with WAL + IMMEDIATE transactions and a SQLite-backed idempotency store.

JWT auth is mandatory in production — the engine refuses to serve traffic with the stub auth when `ENV=production`.

---

## 0. Install (pinned)

Always install from the lockfile:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-lock.txt
```

(Developers may keep `requirements.txt` as the editable surface. Regenerate `requirements-lock.txt` via `pip-compile`.)

---

## 1. Environment variables

### Always required

| Var | Default | Required where? | Notes |
| --- | --- | --- | --- |
| `ENV` | `development` | prod | Set to `production`. Triggers strict auth checks. |
| `BRIEF_STORE_BACKEND` | `sqlite` | all | `sqlite` (prod) / `jsonl` / `memory` |
| `DIRECTORA_BRIEF_DB_PATH` | `./.directora/briefs.db` | sqlite backend | Writable file path |
| `IDEMPOTENCY_STORE_BACKEND` | `sqlite` | all | `sqlite` (prod) / `memory` (single-worker dev only) |
| `IDEMPOTENCY_DB_PATH` | `./.directora/idempotency.db` | sqlite backend | Writable file path |
| `CORS_ALLOW_ORIGINS` | `http://localhost:5173` | all | Comma-separated. |
| `AUTH_MODE` | `stub` | all | `jwt` is **required** in production. |
| `DIRECTORA_CLINIC_SIGNING_SECRET_DEFAULT` | unset | dev | Fallback HMAC secret. Forbidden in prod. |
| `DIRECTORA_CLINIC_SIGNING_SECRET_{ID}` | unset | prod | Per-clinic HMAC secrets. Rotate regularly. |

### JWT-mode required

| Var | Default | Notes |
| --- | --- | --- |
| `JWT_SECRET_KEY` | unset | HS256 symmetric secret. **Required** when `AUTH_MODE=jwt`. |
| `JWT_ISSUER` | `scrutexity-auth` | Must match the issuer claim on signed JWTs. |

### Optional / observability

| Var | Default | Notes |
| --- | --- | --- |
| `DIRECTORA_TELEMETRY_SINK` | `jsonl` | `jsonl` / `memory` / `noop` |
| `DIRECTORA_TELEMETRY_PATH` | `./.directora/ledger.jsonl` | JSONL ledger output path |
| `DIRECTORA_CONTRACT_SNAPSHOT_PATH` | `shared/brief-api-contract.json` | Read at startup probe |

### Chaos switches (NEVER set in production)

| Var | Effect |
| --- | --- |
| `FAULT_LEDGER_APPEND=1` | `record_outcome` raises before writing — atomicity test. |
| `FAULT_DB_LOCK=1` | Idempotency store raises busy — proves 503 + Retry-After contract. |
| `FAULT_CONTRACT_MISMATCH=1` | Used only in chaos tests; never wire to production response surfaces. |

---

## 2. Database setup

The engine creates the SQLite files lazily on first request.

For production, pre-create the parent directory with appropriate permissions:

```bash
sudo mkdir -p /var/lib/directora
sudo chown directora:directora /var/lib/directora
sudo chmod 700 /var/lib/directora

export DIRECTORA_BRIEF_DB_PATH=/var/lib/directora/briefs.db
export IDEMPOTENCY_DB_PATH=/var/lib/directora/idempotency.db
```

**Permissions:** the engine process must own (or have RWX on) the directory containing the SQLite files. Other users should NOT have read access — the ledger contains audit metadata and the idempotency store contains stored response bodies.

**WAL files:** SQLite WAL mode produces `*.db-wal` and `*.db-shm` sidecar files. Back them up alongside the main DB. Do not delete WAL files while the engine is running.

**Backups:** use the SQLite `.backup` command or `sqlite3_db_dump`. Filesystem snapshots are acceptable as long as the WAL has been checkpointed:

```bash
sqlite3 /var/lib/directora/briefs.db "PRAGMA wal_checkpoint(TRUNCATE);"
cp -a /var/lib/directora /backup/directora-$(date +%F)
```

**Migrating from v3.4 (JSONL → SQLite):**

```bash
python -m directora.scrutexity.brief_store_migrate   --src ./.directora/briefs   --dst ./.directora/briefs.db   --rename-legacy-to ./.directora/briefs_migrated   --log-path ./.directora/migration.log
```

Migration is idempotent: the engine writes a JSONL log entry per run and renames the legacy directory only on success.

---

## 3. CORS configuration

```bash
export CORS_ALLOW_ORIGINS="https://labbrief.example.com,https://staff.example.com"
```

Multiple origins comma-separated. The engine rejects bare wildcards in production — the allow-list must be explicit.

---

## 4. Auth mode selection

### Dev (stub)

```bash
export AUTH_MODE=stub
```

Tests and local development use a base64-encoded JSON token. The stub is disabled in production by a runtime safety check (`unsafe_auth_mode`).

### Production (JWT)

```bash
export ENV=production
export AUTH_MODE=jwt
export JWT_SECRET_KEY="$(openssl rand -hex 64)"
export JWT_ISSUER="scrutexity-auth"
```

Verify by issuing a token:

```bash
python -c "from directora.api.auth import generate_dev_token; print(generate_dev_token('PRV_123', 'CLN_456'))"
```

(Set `ENV=development` before running this — `generate_dev_token` refuses in production.)

---

## 5. Multi-worker deployment

The engine is stateless. Run N workers behind a load balancer (Nginx, HAProxy, or a managed service). The SQLite stores are shared via the filesystem; concurrent safety comes from WAL + `BEGIN IMMEDIATE` transactions.

Recommended:

```bash
gunicorn directora.api.server:app   -k uvicorn.workers.UvicornWorker   -w 4   --bind 0.0.0.0:8000   --timeout 30
```

**Idempotency:** the SQLite-backed idempotency store is the only multi-worker-safe option. `IDEMPOTENCY_STORE_BACKEND=memory` is **dev only** — multiple workers will not see each other's idempotency records under the memory backend.

**Backpressure:** workers under SQLite contention return 503 with `Retry-After: 1`. Configure the load balancer to honour `Retry-After` or to apply its own retry policy on 503.

---

## 6. Health check endpoint

```bash
curl -s http://127.0.0.1:8000/health | jq .
```

Returns 200 when healthy, 503 when degraded.

---

## 7. Smoke test verification after deploy

Once the engine is live, run an end-to-end probe with a freshly issued token:

```bash
export BASE=https://api.scrutexity.example.com
export TOKEN=$(python -c "from directora.api.auth import generate_dev_token; print(generate_dev_token('PRV_smoke','CLN_smoke'))")
export RID=$(uuidgen)

# Health
curl -fsS "$BASE/health" | jq .

# List pending (expect 0 entries on a fresh deploy)
curl -fsS "$BASE/api/brief/pending"   -H "Authorization: Bearer $TOKEN"   -H "X-Clinic-ID: CLN_smoke"   -H "X-Request-ID: $RID" | jq .

# Sign a known fixture brief
curl -fsS -X POST "$BASE/api/brief/sign"   -H "Authorization: Bearer $TOKEN"   -H "X-Clinic-ID: CLN_smoke"   -H "X-Request-ID: $RID"   -H "Idempotency-Key: sign-BRF_smoke-$(uuidgen)"   -H "Content-Type: application/json"   -d '{ "brief_id": "BRF_smoke", "provider_id": "PRV_smoke", "signature": {"method":"typed","value":"Smoke","signed_at":"2026-05-16T17:01:33Z"}, "client": {"app":"smoke","version":"1.0.0","session_id":"s"} }'
```

---

## 8. Rollback procedure

If a deploy is bad, roll back in this order:

1. **Drain traffic.** Take the load balancer to the previous version.
2. **Stop new workers.** `systemctl stop directora-api` (or k8s `kubectl rollout undo`).
3. **Restore SQLite if needed.** Copy the most recent backup over the live files only if the new version corrupted the DB (rare — schema changes are backward-compatible by design).
4. **Re-run startup probe** against the rolled-back version to verify.
5. **Smoke test** as in §7.
6. **Post-mortem:** capture the `X-Request-ID` of any failing sign-off from the audit ledger.

Hard rule: the Governed Workflow Ledger is **append-only**. Never delete events. If a rollback invalidates a signing event, append a compensation event rather than removing the original.
