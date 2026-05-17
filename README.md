<!-- =======================
     DIRECTORA • README
     Production Governance Infrastructure
     ======================= -->

<div align="center">
  <img alt="Directora banner" src="assets/directora-banner.png" width="1000" />
</div>

<div align="center">

[![Governance Proof](https://github.com/Scrutexity/Directora/actions/workflows/governance-proof.yml/badge.svg)](https://github.com/Scrutexity/Directora/actions/workflows/governance-proof.yml)
[![GitHub stars](https://img.shields.io/github/stars/Scrutexity/Directora?style=for-the-badge&logo=github&color=0A2540&labelColor=080808)](https://github.com/Scrutexity/Directora/stargazers)
[![Latest release](https://img.shields.io/github/v/release/Scrutexity/Directora?style=for-the-badge&logo=github&color=00C853&labelColor=080808)](https://github.com/Scrutexity/Directora/releases)
[![License: MIT](https://img.shields.io/github/license/Scrutexity/Directora?style=for-the-badge&logo=opensourceinitiative&color=0A2540&labelColor=080808)](https://github.com/Scrutexity/Directora/blob/main/LICENSE)

![Status](https://img.shields.io/badge/status-governance%20proof-00C853?style=for-the-badge&labelColor=080808)
![Stack](https://img.shields.io/badge/stack-FastAPI%20%2F%20TypeScript-0A2540?style=for-the-badge&labelColor=080808)

# DIRECTORA

**Governance Infrastructure // Scrutexity**

*Immutable ledger. Atomic sign-off. Zero-drift contracts.*

[What this repo contains](#what-this-repo-contains) · [Verify in 60 seconds](#verify-in-60-seconds-the-gate) · [Quick start](#quick-start-local) · [Where to look](#where-to-look) · [Security](#security--scope)

</div>

<div align="center">
  <img alt="Directora governance flow demo" src="assets/directora-demo.gif" width="880" />
</div>

---

Directora is internal Scrutexity infrastructure — the machine behind our outcomes.

Engine published as proof of governance. `labbrief_kit/` is the integration surface. Full LabBrief UI remains private.

Not a clinical, legal, or regulatory assessment. PHI-minimizing IDs only (`patient_ref`, `encounter_ref`).

> Governed. Proof-verified. MIT-Licensed.  
> This repo ships a 60-second governance proof script + CI gate.

---

## What this repo contains

- **Directora (FastAPI · Python)** — governed server: append-only ledger, atomic sign-off, idempotency replay, contract snapshot drift guard.
- **LabBrief kit (TypeScript)** — integration kit: schemas + retry policy + idempotency lifecycle + drift detector (kit-only; not the full UI).
- **Shared wire contract** — `shared/brief-api-contract.json` is the single contract source of truth.

---

## Data Flow

```text
┌──────────────┐
│   LabBrief   │
│  (Client UI) │
└────────┬─────┘
         │
         │ POST /api/brief/sign
         │ (idempotency key + signature)
         │
         ▼
┌──────────────────────────┐
│  Directora (FastAPI)     │
│  ─────────────────────   │
│  • Validate signature    │
│  • Atomic ledger append  │
│  • X-Idempotency headers │
└────────┬────────────────┘
         │
         │ 200 OK (ledger_event_id, binding_hash)
         │ X-Contract-Version
         │ X-Idempotency-Replayed
         │ X-Request-ID
         │
         ▼
┌─────────────────────────────────────┐
│   LabBrief Kit (TypeScript)         │
│   ───────────────────────────────── │
│   • Retry on 503 / 429 / timeout    │
│   • Never retry on 409 / 422 / 4xx  │
│   • Contract drift detection        │
│   • Audit trail consumption         │
└─────────────────────────────────────┘
```

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

## Brief API

### Endpoints

```text
GET  /api/brief/pending
GET  /api/brief/provider
POST /api/brief/sign
GET  /api/labs/audit
```

### Signing guarantees

- **Atomicity** — ledger append is the commit point; no partial state on failure.
- **Idempotency** — byte-identical replay for the same `Idempotency-Key` (replay header surfaced).
- **Hash-binding** — signature binds to canonical Provider Brief JSON (stable artifact).

---

## Quick start (local)

### Install

```bash
python -m venv .venv
source .venv/bin/activate

# Install pinned deps (deployable/reproducible)
pip install -r requirements-lock.txt
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

## Dependency lock (required for deploys)

Directora deploys are pinned and reproducible. Install from `requirements-lock.txt` (generated from `requirements.txt`).

To regenerate the lock:

```bash
pip install pip-tools
pip-compile requirements.txt -o requirements-lock.txt
```

---

## Where to look

- Ship doc (repo-native): `RELEASE.md`
- Polished ship doc (HTML): `docs/release/release-page.html`
- Governance proof (the gate): `tests/governance/ultimate-governance-check.sh`
- Contract snapshot: `shared/brief-api-contract.json`
- Release history: `CHANGELOG.md`
- Ops handoff: `HANDOFF.md`
- Deployment runbook: `DEPLOYMENT.md`
- LabBrief integration kit: `labbrief_kit/`

---

## React Animation Component (optional)

This repo includes an optional animated governance-flow React component:

```text
components/ScrutexityFlow.tsx
```

Only needed if you import it into a React app (Next.js / Vite / CRA).  
If you are only running the Python API, ignore this section.

In your React project (the folder with `package.json`):

```bash
npm install framer-motion
```

---

## Security & scope

See `THREAT_MODEL.md` for attacker models, mitigations, and out-of-scope risks.

Directora does not claim HIPAA, SOC 2, FDA, legal, or regulatory certification. It provides governance mechanisms, auditability patterns, and safer workflow infrastructure.

---

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=Scrutexity/Directora&type=Date)](https://star-history.com/#Scrutexity/Directora&Date)

---

<div align="center">

**SCRUTEXITY // 2026**

*Built with precision. Governed by proof.*

</div>
