<p align="center">
  <img alt="Directora banner" src="assets/directora-banner.png" width="980" />
</p>

<p align="center">
  <a href="https://github.com/Scrutexity/Directora/actions/workflows/governance-proof.yml">
    <img alt="Governance Proof" src="https://github.com/Scrutexity/Directora/actions/workflows/governance-proof.yml/badge.svg"/>
  </a>
  <img alt="Status" src="https://img.shields.io/badge/status-governance%20proof-green?style=flat-square"/>
  <img alt="License" src="https://img.shields.io/badge/license-MIT-green?style=flat-square"/>
</p>

# Directora

Directora is internal Scrutexity infrastructure — the machine behind our outcomes.

Engine published as **proof of governance**. `labbrief_kit/` is the integration surface. The full LabBrief UI remains private.

**Not a clinical, legal, or regulatory assessment.** PHI-minimizing IDs only (`patient_ref`, `encounter_ref`).

---

## Verify in 60 seconds (the gate)

Run from repo root:

```bash
./tests/governance/ultimate-governance-check.sh
```

Expected output:

```text
✅ GOVERNANCE ARCHITECTURE INTACT
   Directora and LabBrief cannot drift.
   Atomicity, idempotency, and contract versioning all verified.
```

CI runs the same proof on every PR via `.github/workflows/governance-proof.yml`.

---

## What this repo contains

- **Directora (FastAPI · Python)** — governed server: append-only ledger, atomic sign-off, idempotency replay, contract snapshot drift guard.
- **LabBrief kit (TypeScript)** — integration kit: schemas + retry policy + idempotency lifecycle + drift detector (kit-only; not the full UI).
- **Shared wire contract** — `shared/brief-api-contract.json` is the single contract source of truth.

---

## Data flow (high level)

```text
LabBrief (Client UI)
    |
    |  POST /api/brief/sign   (Idempotency-Key + signature)
    v
Directora (FastAPI)
  - validate signature
  - atomic ledger append (commit point)
  - byte-identical replay for retries
    |
    |  200 OK (ledger_event_id, binding_hash)
    |  X-Contract-Version, X-Idempotency-Replayed, X-Request-ID
    v
LabBrief kit (TypeScript)
  - retries (503/429/timeouts)
  - never retries on 409/422/other 4xx
  - contract drift detection
  - audit trail consumption
```

---

## Brief API

### Endpoints

- `GET  /api/brief/pending`
- `GET  /api/brief/provider`
- `POST /api/brief/sign`
- `GET  /api/labs/audit`

### Signing guarantees

- **Atomicity** — ledger append is the commit point; no partial state on failure.
- **Idempotency** — byte-identical replay for the same `Idempotency-Key` (replay header surfaced).
- **Hash-binding** — signature binds to canonical Provider Brief JSON (stable artifact).
- **Contract versioning** — `X-Contract-Version` matches `shared/brief-api-contract.json::version`.

---

## Quick start (local)

### Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Run

```bash
uvicorn directora.api.server:app --host 0.0.0.0 --port 8000
```

### Health

```bash
curl http://localhost:8000/health
```

---

## Advanced: Idempotency lifecycle

Every sign request carries an `Idempotency-Key` header. The server stores the request + response for 24 hours:

- First attempt → computes signature, appends ledger entry, returns `200` + `ledger_event_id`.
- Retry with same key → returns the original response byte-identical + `X-Idempotency-Replayed: true`.
- Retry with same key, different body → mismatch detected → `409 idempotency_conflict`.

## Advanced: Atomicity guarantee

The ledger append is the commit point. If post-append finalization fails:

- Brief stays in `pending_review`.
- Zero rollback events are written.
- Client retries with the same key and receives the original `ledger_event_id`.

---

## Where to look

- Governance proof (the gate): `tests/governance/ultimate-governance-check.sh`
- Contract snapshot: `shared/brief-api-contract.json`
- Ops handoff: `HANDOFF.md`
- Deployment runbook: `DEPLOYMENT.md`
- LabBrief integration kit: `labbrief_kit/`
