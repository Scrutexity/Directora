# Directora

[![License: MIT](https://img.shields.io/badge/license-MIT-green?style=flat-square)](./LICENSE)
[![Status](https://img.shields.io/badge/status-governance%20proof-green?style=flat-square)](https://github.com/Scrutexity/Directora/actions/workflows/governance-proof.yml)

Directora is Scrutexity's governed signing engine and append-only audit ledger. It provides atomic sign-off, idempotent replay, and contract-versioned signatures for client apps.

> Not a clinical, legal, or regulatory assessment. PHI-minimizing IDs only (e.g. `patient_ref`, `encounter_ref`).

## Quick verify
Run the governance proof locally from the repository root:

```bash
./tests/governance/directora-governance-check.sh
```

Expected summary output:

```
✅ GOVERNANCE ARCHITECTURE INTACT
```

## Quick start (local)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn directora.api.server:app --host 0.0.0.0 --port 8000
```

Health check:

```bash
curl http://localhost:8000/health
```

## Ignore sensitive data
This repository includes a .gitignore configured to avoid committing exports and environment files. If you accidentally committed sensitive files, remove them from the index before pushing:

```bash
git rm -r --cached data/ exports/ receipts/ diagnostics/ screenshots/
git rm --cached *.csv *.xlsx *.log .env .env.*
git commit -m "chore: remove sensitive files from index"
```

If you need to purge sensitive files from history, I can provide BFG or git-filter-repo commands — ask and I will draft the exact steps.

## Where to look
- Governance proof: `tests/governance/ultimate-governance-check.sh` and `tests/governance/directora-governance-check.sh`
- Contract snapshot: `shared/brief-api-contract.json`
- LabBrief integration kit: `labbrief_kit/`

## License
This project is MIT licensed. See [LICENSE](./LICENSE).
