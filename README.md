# Birkin

**My personal iPhone controller for Hermes Agents — open-source alternative to Claude Dispatch.**

Control my Hermes agents from my iPhone with voice input, get Telegram alerts when governance fails, and cryptographically verify agent integrity with hash-chained audit logs. **Self-hosted, free, my data stays local.**

PRIORITY FEATURES (for personal use, not public):

1. (30min) Siri Shortcuts integration — POST /api/skills/{name}/trigger endpoint so "Hey Siri, run sourcing-intel" triggers agents without unlocking phone

2. (3hr) iOS Widget showing real-time agent status (health, uptime, last action, pending alerts)

3. (1hr) Shortcuts automation — scheduled triggers (daily-brief at 7 AM, competitor-monitor on geofence, etc.)

4. (3hr) Cost tracker per skill — track spending per agent/skill, monthly budget alerts

5. (3hr) Native push notifications (via Pusher or OneSignal) instead of Telegram — better iOS UX

6. (2hr) Apple Watch complication showing agent status

7. (2hr) Focus mode integration — agents behave differently based on Work/Personal/Sleep/Driving

8. (4hr) Offline mode — queue agent actions when offline, auto-sync when online

9. (2hr) 3D Touch quick actions — long-press app icon to run skills directly

10. (2hr) Handoff to Mac — seamless handoff from iPhone to Mac for audit logs

---

## Architecture

Birkin is a FastAPI server that runs locally (or on a personal VPS) and exposes endpoints consumed by Siri Shortcuts, iOS Widgets, and a companion SwiftUI app. The underlying Directora governance layer provides immutable, hash-chained audit logs for every agent action.

```
iPhone (Siri / Widgets / SwiftUI) → Birkin FastAPI → Hermes Agents → Directora Ledger
```

### Core Guarantees

| Guarantee | Enforcement |
|---|---|
| **Auditability** | Hash-chained ledger — every agent action is verifiable |
| **Atomicity** | Ledger append is the single commit point |
| **Idempotency** | Safe retries without duplicate agent runs |
| **Governed failure** | Fails closed on integrity violations — Telegram alert fires |

---

## Repository Layout

| Path | Stack | Function |
|---|---|---|
| `directora/api/routes/skills.py` | FastAPI | Siri Shortcuts trigger endpoint |
| `directora/api/routes/widget.py` | FastAPI | iOS Widget status feed |
| `directora/api/routes/schedules.py` | FastAPI | Shortcuts automation / cron triggers |
| `directora/api/routes/costs.py` | FastAPI | Per-skill cost tracking |
| `directora/api/routes/notifications.py` | FastAPI | Push notification dispatch |
| `directora/` | FastAPI / Python | Governed server, ledger, idempotency |
| `shared/` | JSON Schema | Contract source |
| `tests/` | Python | Governance gates |

---

## Quickstart

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-lock.txt

# copy and fill in your keys
cp .env.example .env

uvicorn directora.api.server:app --host 0.0.0.0 --port 8000 --reload
```

### Health check

```bash
curl http://localhost:8000/health
```

### Trigger a skill (Siri Shortcuts compatible)

```bash
curl -X POST http://localhost:8000/api/skills/sourcing-intel/trigger \
  -H "Authorization: Bearer $BIRKIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"source": "siri", "params": {}}'
```

---

## Feature 1 — Siri Shortcuts Integration

`POST /api/skills/{name}/trigger` accepts a bearer token and optional params. Configure a Shortcut that POSTs to this endpoint — "Hey Siri, run sourcing-intel" triggers the agent without unlocking the phone.

```
POST /api/skills/{name}/trigger
Authorization: Bearer <BIRKIN_TOKEN>
→ { "run_id": "...", "status": "queued", "skill": "sourcing-intel" }
```

## Feature 2 — iOS Widget

`GET /api/widget/status` returns agent health, uptime, last action, and pending alert count — everything the iOS widget needs in a single call.

```
GET /api/widget/status
→ { "agents": [...], "pending_alerts": 2, "updated_at": "..." }
```

## Feature 3 — Shortcuts Automation

`POST /api/schedules` creates a named trigger (cron or geofence label). The server fires the linked skill at the scheduled time.

```
POST /api/schedules
→ { "id": "daily-brief-0700", "skill": "daily-brief", "cron": "0 7 * * *" }
```

## Feature 4 — Cost Tracker

`GET /api/costs` returns per-skill spend for the current month, total, and alerts when budget thresholds are hit.

```
GET /api/costs?period=month
→ { "skills": { "sourcing-intel": { "usd": 1.42, "runs": 18 } }, "total_usd": 4.87 }
```

## Feature 5 — Push Notifications

`POST /api/notifications/register` registers a device token. The server sends native push via Pusher Beams or OneSignal when governance fails or a budget alert fires.

```
POST /api/notifications/register
→ { "device_id": "...", "registered": true }
```

---

## Governance & Audit

Every agent trigger writes a hash-chained ledger event. Verify the audit trail:

```bash
./tests/governance/ultimate-governance-check.sh
```

---

## Security

| Control | How |
|---|---|
| **Auth** | Bearer token (`BIRKIN_TOKEN` env var) on all skill/schedule endpoints |
| **Local data** | Ledger is SQLite on local disk — nothing leaves your machine |
| **Fail-closed** | Governance violations block the operation and fire a Telegram alert |

See [`SECURITY.md`](SECURITY.md) for disclosure protocols.

---

*Self-hosted. Personal use. My data stays local.*
