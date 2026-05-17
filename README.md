<!-- =======================
     DIRECTORA • README
     Production Governance Infrastructure
     ======================= -->

<div align="center">

[![Governance Proof](https://github.com/Scrutexity/Directora/actions/workflows/governance-proof.yml/badge.svg)](https://github.com/Scrutexity/Directora/actions/workflows/governance-proof.yml)
[![GitHub stars](https://img.shields.io/github/stars/Scrutexity/Directora?style=for-the-badge&logo=github&color=0A2540&labelColor=080808)](https://github.com/Scrutexity/Directora/stargazers)
[![Latest release](https://img.shields.io/github/v/release/Scrutexity/Directora?style=for-the-badge&logo=github&color=00C853&labelColor=080808)](https://github.com/Scrutexity/Directora/releases)
[![License: MIT](https://img.shields.io/github/license/Scrutexity/Directora?style=for-the-badge&logo=opensourceinitiative&color=0A2540&labelColor=080808)](https://github.com/Scrutexity/Directora/blob/main/LICENSE)

![Version](https://img.shields.io/badge/version-1.0.0-00C853?style=for-the-badge&labelColor=080808)
![Governance Gates](https://img.shields.io/badge/governance-9%2F9%20gates-green?style=for-the-badge&labelColor=080808)
![Stack: FastAPI / Python](https://img.shields.io/badge/stack-FastAPI%20%2F%20Python-0A2540?style=for-the-badge&labelColor=080808)

# DIRECTORA

**Governance Infrastructure // Scrutexity**

*Immutable ledger. Atomic sign-off. Zero-drift contracts.*

[Architecture](#01--architecture) · [Repository Matrix](#02--repository-matrix) · [Deployment](#03--deployment--protocol) · [Contract](#04--contract-specification) · [Governance Proof](#05--governance-proof) · [Security](#06--compliance--security) · [Threat Model](THREAT_MODEL.md)

</div>

---

## 01 // Architecture

Modern clinical operations fail from **system drift**.

Directora eliminates that failure mode by enforcing a provably correct, immutable, and retry-safe event ledger. If a transaction passes Directora governance, the client and server remain synchronized by contract.

> **Directora is an immutable governed commit system.**  
> The ledger append is the commit point. The contract is the boundary. Drift fails closed.

### Core Guarantees

| Guarantee | Enforcement | Outcome |
|---|---|---|
| **Atomicity** | Ledger append is the single isolated commit point | No partial states |
| **Idempotency** | Byte-identical replay detection | Safe retries without duplication |
| **Contract Integrity** | Golden contract alignment + CI drift gates | Zero silent drift |
| **Auditability** | Immutable hash-chained event history | Provable operational trail |
| **Governed Failure** | Fail-closed on signature, drift, or tampering anomalies | Defense-in-depth |
| **Tamper Evidence** | Cryptographic hash chaining across all ledger events | Broken chain detected on verification |

> **Note:** Directora uses PHI-minimizing references such as `patient_ref` and `encounter_ref`. Raw clinical payloads are prohibited from the ledger.

---

## 02 // Repository Matrix

| Path | Stack | Function |
|---|---|---|
| `directora/` | FastAPI / Python | Governed server for append-only events, signing, and idempotency |
| `labbrief_kit/` | TypeScript | Private integration surface and retry-safe client logic (access-controlled) |
| `shared/` | JSON Schema | Canonical contract source for client/server alignment |
| `tests/governance/` | Shell / Python CI gates | Automated drift gates and ledger discipline proofs |
| `tests/adversarial/` | Python | Adversarial tests breaking replay, drift, signatures, backpressure |
| `scripts/` | Shell | `demo_trust.sh` — 5 guarantees in under 5 minutes |
| `docs/` | Markdown / HTML | Architecture notes, release page, ship document |

---

## 03 // Deployment & Protocol

### Quick Start (dev)

```bash
python -m venv .venv
source .venv/bin/activate

# Install pinned deps (deployable/reproducible)
pip install -r requirements-lock.txt

export DIRECTORA_CLINIC_SIGNING_SECRET_DEFAULT="dev-secret-do-not-use-in-production"
uvicorn directora.api.server:app --host 0.0.0.0 --port 8000 --reload
```

### Production (multi-worker)

```bash
gunicorn directora.api.server:app   -k uvicorn.workers.UvicornWorker   -w 4   --bind 0.0.0.0:8000
```

### Environment variables (minimum set)

| Variable | Purpose | Required |
|---|---|---|
| `DIRECTORA_CLINIC_SIGNING_SECRET_DEFAULT` | Dev fallback signing key | Dev only |
| `DIRECTORA_CLINIC_SIGNING_SECRET_{CLINIC_ID}` | Per-clinic signing key | Production |
| `DIRECTORA_ADMIN_API_KEY` | Admin endpoint auth | Production |
| `BRIEF_STORE_BACKEND` | `sqlite` or `postgres` | Yes (default: `sqlite`) |
| `IDEMPOTENCY_STORE_BACKEND` | `sqlite` or `memory` | Yes (default: `sqlite`) |
| `AUTH_MODE` | `stub`, `hs256`, or `jwks` | Yes |
| `JWT_SECRET_KEY` | HS256 signing key | If `AUTH_MODE=hs256` |
| `JWKS_URL` | JWKS endpoint URL | If `AUTH_MODE=jwks` |
| `CORS_ALLOW_ORIGINS` | Allowed origins | Production |

See `DEPLOYMENT.md` for the full runbook.

### Dependency lock (required for deploys)

Directora deploys are pinned and reproducible. Install from `requirements-lock.txt` (generated from `requirements.txt`).

To regenerate the lock:

```bash
pip install pip-tools
pip-compile requirements.txt -o requirements-lock.txt
```

---

## Health Check

```bash
curl http://localhost:8000/health
```

Returns `contract_version`, `engine_release`, backend status, and auth mode.

---

## 04 // Contract Specification

### Signing protocol

```http
POST /api/brief/sign
```

| Header / Field | Requirement | Purpose |
|---|---:|---|
| `Idempotency-Key` | Required | Safe identical replays without double-commits |
| `Authorization` | Required | Bearer token (stub, HS256, or RS256/JWKS) |
| `X-Clinic-ID` | Required | Clinic tenant routing |
| `X-Contract-Version` | Required | Drift detection against golden JSON schema |
| `X-Idempotency-Replayed` | Server return | `true` when replay served byte-identical response |
| `X-Request-ID` | Server return | Audit correlation across requests |
| `ledger_event_id` | Server return | Immutable event reference after commit |
| `binding_hash` | Server return | HMAC-SHA256 binding of provider identity to brief content |

### Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/brief/pending` | List briefs awaiting provider sign-off |
| `POST` | `/api/brief/sign` | Sign a brief (idempotent, atomic, ledger-backed) |
| `GET` | `/api/brief/provider` | Get canonical provider brief JSON (hash source) |
| `GET` | `/api/labs/audit` | Get audit trail for a brief |
| `GET` | `/api/labs/audit/verify` | Verify full ledger hash-chain integrity |
| `POST` | `/admin/jwt/revoke` | Revoke a JWT by `jti` (requires admin key) |
| `POST` | `/admin/secrets/rotate` | Rotate clinic signing secret |
| `GET` | `/health` | Health check |
| `GET` | `/metrics` | Prometheus metrics (auth-gated in production) |

---

## 05 // Governance Proof

Directora's governance model is not decorative. It is enforced.

### Trust in 3 Minutes

```bash
./scripts/demo_trust.sh
```

### Full governance check

```bash
./tests/governance/directora-governance-check.sh
```

The 9-gate proof verifies:

| Gate | What it proves |
|---:|---|
| 1 | Successful sign-off with binding hash |
| 2 | Contract version header on GET paths |
| 3 | Byte-identical replay with `X-Idempotency-Replayed: true` |
| 4 | Hash binding — sign and provider endpoints agree |
| 5 | Idempotency conflict (same key, different body) |
| 6 | Already-signed gating (new key on signed brief) |
| 7 | Backpressure — `503` + `Retry-After` under `FAULT_DB_LOCK` |
| 8 | Chaos — ledger failure atomicity under `FAULT_LEDGER_APPEND` |
| 9 | Health check includes `contract_version` + `engine_release` |

Expected output:

```text
✅ GOVERNANCE ARCHITECTURE INTACT
   Directora and LabBrief cannot drift.
```

### Adversarial tests

```bash
pytest tests/adversarial/ -v
```

---

## 06 // Compliance & Security

### Threat model

See `THREAT_MODEL.md` for attacker models, mitigations, and out-of-scope risks.

### Security controls

| Control | Implementation |
|---|---|
| Zero PHI | Response-surface controls; only minimized references (`patient_ref`, `encounter_ref`) |
| Zero secret logging | Tokens/signatures/sensitive payloads stripped from logs |
| Least privilege | Tenant isolation (backend-dependent); admin endpoints gated via `DIRECTORA_ADMIN_API_KEY` |
| Fail-closed | Signature/contract/tampering deviations block the operation |
| Tamper evidence | Hash-chained ledger; `/api/labs/audit/verify` detects modification |
| JWT revocation | `jti` blacklist; `POST /admin/jwt/revoke` for incident response |

> Directora does not claim HIPAA, SOC 2, FDA, legal, or regulatory certification. It provides governance mechanisms, auditability patterns, and safer workflow infrastructure.

---

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=Scrutexity/Directora&type=Date)](https://star-history.com/#Scrutexity/Directora&Date)

---

<div align="center">

**SCRUTEXITY // 2026**

*Built with precision. Governed by proof.*

</div>
