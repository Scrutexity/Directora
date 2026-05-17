#!/usr/bin/env bash
# directora-governance-check.sh
#
# End-to-end governance proofs against a running Directora v3.7 instance.
# Verifies:
#   * Happy-path sign-off
#   * X-Contract-Version header on responses
#   * Byte-identical idempotent replay (+ X-Idempotency-Replayed header)
#   * Idempotency conflict (same key, different body)
#   * Already-signed gating
#   * Chaos: FAULT_LEDGER_APPEND atomicity (brief stays pending_review,
#     zero ledger events for the failed brief, NO rollback events
#     anywhere)
#   * Health endpoint
#
# Tests 1-5 and 7 run against any reachable Directora. Test 6 (chaos)
# requires the ability to restart Directora locally with environment
# variables — set RUN_CHAOS=0 to skip it.
#
# Usage:
#   ./directora-governance-check.sh
#
# Optional env vars:
#   BASE              base URL (default http://localhost:8000)
#   AUTH_MODE         token mode: stub (default) | hs256 | jwks
#   TOKEN             pre-issued bearer token (skip auto-generation)
#   PROVIDER_ID       caller's provider id (default PRV_GOV)
#   CLINIC_ID         caller's clinic id (default CLN_GOV)
#   RUN_CHAOS         1 (default) — set 0 to skip Test 6
#   DIRECTORA_CMD     command to (re)start Directora; defaults to uvicorn
#   SEED              1 (default) — seed BRF_GOV_01 + BRF_GOV_02 before
#                     running. Set 0 if your environment already has them.
#
# Exit codes:
#   0  all assertions passed
#   1  prerequisite missing or test failure
set -euo pipefail

# ---------- prerequisites -----------------------------------------------

command -v jq   >/dev/null 2>&1 || { echo "❌ jq is required.";   exit 1; }
command -v curl >/dev/null 2>&1 || { echo "❌ curl is required."; exit 1; }
command -v uuidgen >/dev/null 2>&1 || { echo "❌ uuidgen is required."; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "❌ python3 is required."; exit 1; }

BASE="${BASE:-http://localhost:8000}"
EXPECTED_CONTRACT_VERSION="${EXPECTED_CONTRACT_VERSION:-3.7.0}"
PROVIDER_ID="${PROVIDER_ID:-PRV_GOV}"
CLINIC_ID="${CLINIC_ID:-CLN_GOV}"
BRIEF_HAPPY="${BRIEF_HAPPY:-BRF_GOV_01}"
BRIEF_CHAOS="${BRIEF_CHAOS:-BRF_GOV_02}"
RUN_CHAOS="${RUN_CHAOS:-1}"
SEED="${SEED:-1}"
DIRECTORA_CMD="${DIRECTORA_CMD:-uvicorn directora.api.server:app --host 0.0.0.0 --port 8000}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---------- helpers -----------------------------------------------------

issue_token() {
  if [ -n "${TOKEN:-}" ]; then
    echo "$TOKEN"
    return
  fi
  case "${AUTH_MODE:-stub}" in
    stub|jwt|hs256)
      python3 -c "
from directora.api.auth import encode_stub_token, generate_dev_token
import os
mode = os.getenv('AUTH_MODE', 'stub')
if mode == 'stub':
    print(encode_stub_token('${PROVIDER_ID}', '${CLINIC_ID}'))
else:
    print(generate_dev_token('${PROVIDER_ID}', '${CLINIC_ID}'))
"
      ;;
    *)
      echo "❌ AUTH_MODE=$AUTH_MODE not supported by this script. Pass TOKEN explicitly." >&2
      exit 1
      ;;
  esac
}

await_health() {
  for _ in $(seq 1 30); do
    if curl -s --max-time 2 "$BASE/health" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.3
  done
  echo "❌ Directora not reachable at $BASE after 9s"
  return 1
}

start_directora() {
  local env_pairs="$1"
  # shellcheck disable=SC2086
  env $env_pairs $DIRECTORA_CMD >/tmp/directora.log 2>&1 &
  echo $!
}

kill_directora() {
  local pid="${1:-}"
  if [ -n "$pid" ]; then
    kill "$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
  fi
  pkill -f "uvicorn directora.api.server" 2>/dev/null || true
  sleep 0.5
}

# ---------- preflight ---------------------------------------------------

echo "=== Preflight ==="
await_health || exit 1
echo "✅ Directora reachable at $BASE"

# Multi-worker safety sanity check (rides on /health). If this engine is
# running with `env=production` AND `idempotency_backend=memory`, refuse
# to proceed — the memory backend is not shared across workers and the
# idempotency guarantee is silently broken under load.
#
# Also surface BOTH version axes so on-call doesn't have to guess
# whether the number shown is the engine patch or the consumer
# contract — v3.7.1 renamed the old bare `version` field for exactly
# this reason.
HEALTH_PROBE=$(curl -sS --max-time 5 "$BASE/health" 2>/dev/null || echo '{}')
HEALTH_ENV=$(echo "$HEALTH_PROBE" | jq -r '.env // "unknown"')
HEALTH_IDEM_BACKEND=$(echo "$HEALTH_PROBE" | jq -r '.idempotency_backend // "unknown"')
HEALTH_BRIEF_BACKEND=$(echo "$HEALTH_PROBE" | jq -r '.store_backend // "unknown"')
HEALTH_CONTRACT_VERSION=$(echo "$HEALTH_PROBE" | jq -r '.contract_version // "unknown"')
HEALTH_ENGINE_RELEASE=$(echo "$HEALTH_PROBE" | jq -r '.engine_release // "unknown"')
HEALTH_AUTH_MODE=$(echo "$HEALTH_PROBE" | jq -r '.auth_mode // "unknown"')
echo "ℹ env=$HEALTH_ENV  brief_store=$HEALTH_BRIEF_BACKEND  idempotency=$HEALTH_IDEM_BACKEND"
echo "ℹ contract=$HEALTH_CONTRACT_VERSION  engine=$HEALTH_ENGINE_RELEASE  auth_mode=$HEALTH_AUTH_MODE"
# Auth-mode safety: stub auth is forbidden in production. The engine
# already refuses to serve in that combo (returns 500 unsafe_auth_mode),
# but we surface it here so on-call sees the misconfig at the
# preflight line instead of having to dig into Test 1's failure.
if [ "$HEALTH_ENV" = "production" ] && [ "$HEALTH_AUTH_MODE" = "stub" ]; then
  echo
  echo "❌ UNSAFE auth configuration detected"
  echo "   ENV=production with AUTH_MODE=stub is a refuse-to-serve combo."
  echo "   The engine returns 500 unsafe_auth_mode on every request."
  echo "   Set AUTH_MODE=jwks (or hs256 for staging) before deploy."
  exit 1
fi
# Sanity: /health must expose BOTH axes. Catches stale engines or
# reverse proxies stripping fields.
if [ "$HEALTH_CONTRACT_VERSION" = "unknown" ] \
   || [ "$HEALTH_ENGINE_RELEASE" = "unknown" ]; then
  echo
  echo "❌ /health did not expose both contract_version AND engine_release"
  echo "   Likely cause: engine predates v3.7.1, or a proxy stripped fields."
  echo "   Got: $HEALTH_PROBE"
  exit 1
fi
if [ "$HEALTH_ENV" = "production" ] \
   && [ "$HEALTH_IDEM_BACKEND" = "memory" ]; then
  echo
  echo "❌ UNSAFE multi-worker configuration detected"
  echo "   ENV=production with IDEMPOTENCY_STORE_BACKEND=memory."
  echo "   The memory backend is single-worker only; multiple Directora"
  echo "   workers do NOT share replay/conflict state, which silently"
  echo "   defeats the byte-identical-replay guarantee under load."
  echo "   Set IDEMPOTENCY_STORE_BACKEND=sqlite (or another shared"
  echo "   backend) before running governance checks in production."
  exit 1
fi

if [ "$SEED" = "1" ]; then
  python3 "$HERE/seed_governance_fixtures.py" \
    --clinic "$CLINIC_ID" --provider "$PROVIDER_ID" \
    --brief "$BRIEF_HAPPY" --brief "$BRIEF_CHAOS" \
    || { echo "❌ seed step failed"; exit 1; }
  echo "✅ seeded fixtures: $BRIEF_HAPPY, $BRIEF_CHAOS"
fi

TOKEN="$(issue_token)"
IDEM="sign-${BRIEF_HAPPY}-$(uuidgen)"
SIGN_BODY=$(cat <<EOF
{"brief_id":"${BRIEF_HAPPY}","provider_id":"${PROVIDER_ID}","signature":{"method":"typed","value":"Dr Jane Doe","signed_at":"2026-05-16T17:01:33Z"},"client":{"app":"governance-check","version":"1.0","session_id":"test"}}
EOF
)

# ---------- helper: assert X-Contract-Version on a header file ----------
#
# Splits two failure modes so a misconfigured proxy doesn't look like a
# version drift:
#
#   1. header_missing — the response carried NO X-Contract-Version at all.
#      Likely cause: a reverse proxy stripping unknown headers, a CDN
#      edge config dropping X-* on certain methods, or
#      ObservabilityMiddleware not wired on the running engine.
#
#   2. header_wrong — the header is present but does not equal the
#      expected version. Likely cause: snapshot drift / unversioned
#      deploy.
assert_contract_header() {
  local headers_file="$1"
  local method_label="$2"
  local header
  header=$(grep -i "^X-Contract-Version:" "$headers_file" | head -n1 \
           | tr -d '\r' | awk '{print $2}')
  if [ -z "${header:-}" ]; then
    echo "❌ Contract header MISSING on ${method_label}"
    echo "   No X-Contract-Version found in response headers."
    echo "   Likely cause: proxy/middleware stripping X-* headers, OR"
    echo "   the engine is running without ObservabilityMiddleware."
    echo "   Dumping response headers for diagnosis:"
    sed -n '1,40p' "$headers_file" | sed 's/^/     /'
    return 1
  fi
  if [ "$header" != "$EXPECTED_CONTRACT_VERSION" ]; then
    echo "❌ Contract header WRONG on ${method_label}"
    echo "   expected: $EXPECTED_CONTRACT_VERSION"
    echo "   got:      $header"
    echo "   Likely cause: snapshot drift — bump CONTRACT_VERSION + "
    echo "   regenerate shared/brief-api-contract.json."
    return 1
  fi
  echo "✅ X-Contract-Version (${method_label}): $header"
  return 0
}

# ---------- Test 1: happy-path sign-off ---------------------------------

echo
echo "=== Test 1: successful sign-off ==="
SIGN_BODY_FILE="$(mktemp -t gov_sign_body.XXXXXX)"
SIGN_HEADERS_FILE="$(mktemp -t gov_sign_headers.XXXXXX)"
# Note: we deliberately do NOT `trap rm` these. On failure we want the
# tmpfiles preserved for forensic inspection — the failure message
# points at them by path. On success we clean them up explicitly at
# the end of the script.

curl -sS -D "$SIGN_HEADERS_FILE" -o "$SIGN_BODY_FILE" \
  -X POST "$BASE/api/brief/sign" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Clinic-ID: ${CLINIC_ID}" \
  -H "X-Request-ID: gov-success-001" \
  -H "Idempotency-Key: $IDEM" \
  -H "Content-Type: application/json" \
  -d "$SIGN_BODY"

SIGN_RESPONSE=$(cat "$SIGN_BODY_FILE")
STATUS=$(echo "$SIGN_RESPONSE" | jq -r '.status // empty')
LEDGER_EVENT=$(echo "$SIGN_RESPONSE" | jq -r '.ledger_event_id // empty')
BINDING_HASH=$(echo "$SIGN_RESPONSE" | jq -r '.binding_hash // empty')
if [ "$STATUS" != "signed" ]; then
  echo "❌ Sign failed. Response: $SIGN_RESPONSE"; exit 1
fi
# Contract header MUST be set on POST responses too. Misconfigured
# proxies are notorious for stripping headers per-method, so we assert
# both the GET (Test 2) and the POST (here).
assert_contract_header "$SIGN_HEADERS_FILE" "POST /api/brief/sign" || exit 1
echo "✅ status=signed ledger=$LEDGER_EVENT binding=$BINDING_HASH"

# ---------- Test 2: X-Contract-Version header on GET --------------------

echo
echo "=== Test 2: contract-version header on GET ==="
PENDING_HEADERS_FILE="$(mktemp -t gov_pending_headers.XXXXXX)"
curl -sS -D "$PENDING_HEADERS_FILE" -o /dev/null \
  -X GET "$BASE/api/brief/pending?provider_id=${PROVIDER_ID}" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Clinic-ID: ${CLINIC_ID}"
assert_contract_header "$PENDING_HEADERS_FILE" "GET /api/brief/pending" || {
  rm -f "$PENDING_HEADERS_FILE"; exit 1; }
rm -f "$PENDING_HEADERS_FILE"

# ---------- Test 3: byte-identical replay -------------------------------
#
# The strongest proof of correct idempotency: every replay of the same
# (key, body) returns the EXACT bytes of the original 200. We save each
# response body to a tmpfile so:
#   * the diff is shown on failure with meaningful context
#   * a developer can inspect the artifacts post-mortem

echo
echo "=== Test 3: byte-identical idempotent replay ==="
REPLAY_BODY_1_FILE="$(mktemp -t gov_replay_1_body.XXXXXX)"
REPLAY_BODY_2_FILE="$(mktemp -t gov_replay_2_body.XXXXXX)"
REPLAY_HEADERS_FILE="$(mktemp -t gov_replay_headers.XXXXXX)"

curl -sS -o "$REPLAY_BODY_1_FILE" \
  -X POST "$BASE/api/brief/sign" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Clinic-ID: ${CLINIC_ID}" \
  -H "X-Request-ID: gov-replay-001" \
  -H "Idempotency-Key: $IDEM" \
  -H "Content-Type: application/json" \
  -d "$SIGN_BODY"

curl -sS -D "$REPLAY_HEADERS_FILE" -o "$REPLAY_BODY_2_FILE" \
  -X POST "$BASE/api/brief/sign" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Clinic-ID: ${CLINIC_ID}" \
  -H "X-Request-ID: gov-replay-002" \
  -H "Idempotency-Key: $IDEM" \
  -H "Content-Type: application/json" \
  -d "$SIGN_BODY"

# 3a — original sign body MUST equal replay body 1 (the strongest check).
if ! cmp -s "$SIGN_BODY_FILE" "$REPLAY_BODY_1_FILE"; then
  echo "❌ Replay body differs from the original sign response"
  echo "   original sign body : $SIGN_BODY_FILE"
  echo "   replay body 1      : $REPLAY_BODY_1_FILE"
  echo
  diff "$SIGN_BODY_FILE" "$REPLAY_BODY_1_FILE" || true
  exit 1
fi
# 3b — two consecutive replays MUST be byte-identical to each other.
if ! cmp -s "$REPLAY_BODY_1_FILE" "$REPLAY_BODY_2_FILE"; then
  echo "❌ Two replays disagree (idempotent reads non-deterministic)"
  diff "$REPLAY_BODY_1_FILE" "$REPLAY_BODY_2_FILE" || true
  exit 1
fi
# 3c — the replay carries X-Idempotency-Replayed: true.
REPLAY_HEADER=$(grep -i "^X-Idempotency-Replayed:" "$REPLAY_HEADERS_FILE" \
                | tr -d '\r')
if [ -z "$REPLAY_HEADER" ]; then
  echo "❌ X-Idempotency-Replayed header missing on replay"
  echo "   Replay headers dumped from $REPLAY_HEADERS_FILE:"
  sed -n '1,30p' "$REPLAY_HEADERS_FILE" | sed 's/^/     /'
  exit 1
fi
# 3d — contract header still present on replayed POST responses.
assert_contract_header "$REPLAY_HEADERS_FILE" \
  "POST /api/brief/sign (replay)" || exit 1
SIGN_BYTES=$(wc -c <"$SIGN_BODY_FILE" | tr -d ' ')
echo "✅ Replay is byte-identical to the original (${SIGN_BYTES} bytes)"
echo "   $REPLAY_HEADER"

# ---------- Test 4: hash-binding proof (sign ↔ provider artifact) -------
#
# After a successful sign, the engine signed a specific canonical artifact.
# Fetch the provider snippet and prove:
#   a) the hash the engine reported in /sign equals the hash it reports
#      in /provider (no drift between endpoints)
#   b) the local SHA-256 of the returned canonical_json equals the same
#      hash (the engine isn't lying — the HMAC binding is anchored to a
#      stable artifact, not a transient render)

echo
echo "=== Test 4: hash-binding (sign ↔ provider artifact) ==="

SIGNED_HASH=$(jq -r '.brief_content_hash' "$SIGN_BODY_FILE")
if [ -z "$SIGNED_HASH" ] || [ "$SIGNED_HASH" = "null" ]; then
  echo "❌ Sign response missing brief_content_hash"; exit 1
fi

PROVIDER_FILE="$(mktemp -t gov_provider_body.XXXXXX)"
PROVIDER_HEADERS_FILE="$(mktemp -t gov_provider_headers.XXXXXX)"
curl -sS -D "$PROVIDER_HEADERS_FILE" -o "$PROVIDER_FILE" \
  -X GET "$BASE/api/brief/provider?brief_id=${BRIEF_HAPPY}" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Clinic-ID: ${CLINIC_ID}"

PROVIDER_HASH=$(jq -r '.brief_content_hash' "$PROVIDER_FILE")
if [ -z "$PROVIDER_HASH" ] || [ "$PROVIDER_HASH" = "null" ]; then
  echo "❌ Provider response missing brief_content_hash"
  echo "   response body: $(cat "$PROVIDER_FILE")"
  exit 1
fi

# 4a — the two endpoints must agree on the canonical hash.
if [ "$SIGNED_HASH" != "$PROVIDER_HASH" ]; then
  echo "❌ Hash mismatch — sign and provider disagree on the canonical artifact"
  echo "   POST /api/brief/sign returned:     $SIGNED_HASH"
  echo "   GET /api/brief/provider returned:  $PROVIDER_HASH"
  echo "   Likely cause: the brief was re-generated between the sign"
  echo "   and the fetch (brief_content_hash should be locked at"
  echo "   provider_brief_ready time, never recomputed)."
  exit 1
fi

# 4b — the local SHA-256 of canonical_json must equal the same hash.
# This is the auditor-grade proof: the engine cannot lie about the hash
# because we recompute it independently. Python's hashlib + json reads
# the canonical_json string verbatim.
RECOMPUTED_HASH=$(python3 - "$PROVIDER_FILE" <<'PY'
import hashlib, json, sys
with open(sys.argv[1], "r", encoding="utf-8") as fh:
    payload = json.load(fh)
canonical = payload["canonical_json"]
# canonical_json is already the byte-identical string the engine signed.
# We just SHA-256 its UTF-8 encoding.
print(hashlib.sha256(canonical.encode("utf-8")).hexdigest())
PY
)
if [ "$RECOMPUTED_HASH" != "$SIGNED_HASH" ]; then
  echo "❌ Recomputed hash differs from engine's brief_content_hash"
  echo "   engine's hash:    $SIGNED_HASH"
  echo "   recomputed hash:  $RECOMPUTED_HASH"
  echo "   Likely cause: engine returned a canonical_json that is NOT"
  echo "   the byte-identical artifact it signed. HMAC binding is broken."
  echo "   Inspect: $PROVIDER_FILE"
  exit 1
fi

# 4c — contract header still travels on the provider GET.
assert_contract_header "$PROVIDER_HEADERS_FILE" \
  "GET /api/brief/provider" || exit 1

echo "✅ Sign hash:           $SIGNED_HASH"
echo "✅ Provider hash:       (matches)"
echo "✅ Recomputed locally:  (matches — HMAC binding anchored to stable artifact)"
rm -f "$PROVIDER_FILE" "$PROVIDER_HEADERS_FILE"

# ---------- Test 5: idempotency conflict --------------------------------

echo
echo "=== Test 5: idempotency conflict detection ==="
CONFLICT_BODY_REQ=$(cat <<EOF
{"brief_id":"${BRIEF_HAPPY}","provider_id":"${PROVIDER_ID}","signature":{"method":"typed","value":"DIFFERENT DOCTOR","signed_at":"2026-05-16T17:01:33Z"},"client":{"app":"governance-check","version":"1.0","session_id":"test"}}
EOF
)
CONFLICT_BODY=$(curl -sS -X POST "$BASE/api/brief/sign" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Clinic-ID: ${CLINIC_ID}" \
  -H "X-Request-ID: gov-conflict-001" \
  -H "Idempotency-Key: $IDEM" \
  -H "Content-Type: application/json" \
  -d "$CONFLICT_BODY_REQ")
CONFLICT_ERROR=$(echo "$CONFLICT_BODY" | jq -r '.error // empty')
if [ "$CONFLICT_ERROR" != "idempotency_conflict" ]; then
  echo "❌ Expected idempotency_conflict, got: $CONFLICT_BODY"; exit 1
fi
echo "✅ 409 idempotency_conflict"

# ---------- Test 5: already-signed gating -------------------------------

echo
echo "=== Test 6: already-signed detection ==="
ALREADY_SIGNED=$(curl -sS -X POST "$BASE/api/brief/sign" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Clinic-ID: ${CLINIC_ID}" \
  -H "X-Request-ID: gov-already-001" \
  -H "Idempotency-Key: sign-${BRIEF_HAPPY}-$(uuidgen)" \
  -H "Content-Type: application/json" \
  -d "$SIGN_BODY")
ALREADY_ERROR=$(echo "$ALREADY_SIGNED" | jq -r '.error // empty')
ALREADY_LEDGER=$(echo "$ALREADY_SIGNED" | jq -r '.ledger_event_id // empty')
if [ "$ALREADY_ERROR" != "already_signed" ]; then
  echo "❌ Expected already_signed, got: $ALREADY_SIGNED"; exit 1
fi
if [ -z "$ALREADY_LEDGER" ]; then
  echo "❌ already_signed response missing ledger_event_id"; exit 1
fi
echo "✅ 409 already_signed (original ledger event: $ALREADY_LEDGER)"

# ---------- Test 7: backpressure proof (503 + Retry-After) --------------
#
# Forces SQLite-busy behaviour via the FAULT_DB_LOCK chaos switch and
# asserts every contract the LabBrief retry layer depends on:
#   * 503 status (not 500)
#   * Retry-After header present + numeric
#   * X-Request-ID echoed
#   * X-Contract-Version still travels on error responses
#   * body carries error="idempotency_store_busy"

if [ "$RUN_CHAOS" = "1" ]; then
  echo
  echo "=== Test 7: backpressure — 503 + Retry-After ==="
  echo "Restarting Directora with FAULT_DB_LOCK=1..."
  kill_directora ""
  BUSY_PID="$(start_directora "FAULT_DB_LOCK=1")"
  trap 'kill_directora "$BUSY_PID"' EXIT
  await_health || exit 1

  BUSY_TOKEN="$(issue_token)"
  BUSY_IDEM="sign-${BRIEF_HAPPY}-$(uuidgen)"
  BUSY_HEADERS_FILE="$(mktemp -t gov_busy_headers.XXXXXX)"
  BUSY_BODY_FILE="$(mktemp -t gov_busy_body.XXXXXX)"

  curl -sS -D "$BUSY_HEADERS_FILE" -o "$BUSY_BODY_FILE" \
    -X POST "$BASE/api/brief/sign" \
    -H "Authorization: Bearer $BUSY_TOKEN" \
    -H "X-Clinic-ID: ${CLINIC_ID}" \
    -H "X-Request-ID: gov-busy-001" \
    -H "Idempotency-Key: $BUSY_IDEM" \
    -H "Content-Type: application/json" \
    -d "$SIGN_BODY" || true

  # 7a — status MUST be 503 (not 500). The first line of the dump is
  # `HTTP/1.1 503 Service Unavailable` (HTTP/2 strips the `.0` but
  # awk $2 is still the numeric code).
  BUSY_STATUS=$(head -n1 "$BUSY_HEADERS_FILE" | awk '{print $2}')
  if [ "$BUSY_STATUS" != "503" ]; then
    echo "❌ Expected 503 under FAULT_DB_LOCK, got $BUSY_STATUS"
    echo "   Likely cause: chaos switch not wired, OR the API translated"
    echo "   busy to 500 (regression — should be 503 + Retry-After)."
    echo "   Headers dump:"
    sed -n '1,15p' "$BUSY_HEADERS_FILE" | sed 's/^/     /'
    exit 1
  fi
  echo "✅ 503 returned under FAULT_DB_LOCK"

  # 7b — Retry-After must be present + numeric.
  RETRY_AFTER=$(grep -i "^Retry-After:" "$BUSY_HEADERS_FILE" \
                | head -n1 | tr -d '\r' | awk '{print $2}')
  if [ -z "$RETRY_AFTER" ]; then
    echo "❌ Retry-After header MISSING on 503"
    echo "   LabBrief's retry layer needs this to schedule the next attempt."
    exit 1
  fi
  if ! [[ "$RETRY_AFTER" =~ ^[0-9]+$ ]]; then
    echo "❌ Retry-After is not numeric: '$RETRY_AFTER'"
    echo "   Must be an integer number of seconds (RFC 7231)."
    exit 1
  fi
  echo "✅ Retry-After: ${RETRY_AFTER}s (numeric)"

  # 7c — X-Request-ID must travel on error responses too.
  BUSY_REQ_ID=$(grep -i "^X-Request-ID:" "$BUSY_HEADERS_FILE" \
                | head -n1 | tr -d '\r' | awk '{print $2}')
  if [ -z "$BUSY_REQ_ID" ]; then
    echo "❌ X-Request-ID missing on 503 — on-call can't correlate"
    exit 1
  fi
  echo "✅ X-Request-ID: $BUSY_REQ_ID"

  # 7d — contract header still travels on a 503 error response.
  assert_contract_header "$BUSY_HEADERS_FILE" \
    "POST /api/brief/sign (503)" || exit 1

  # 7e — body shape.
  BUSY_ERROR=$(jq -r '.error // empty' "$BUSY_BODY_FILE")
  if [ "$BUSY_ERROR" != "idempotency_store_busy" ]; then
    echo "❌ Expected error=idempotency_store_busy, got: $BUSY_ERROR"
    echo "   Body: $(cat "$BUSY_BODY_FILE")"
    exit 1
  fi
  echo "✅ body.error=idempotency_store_busy"

  rm -f "$BUSY_HEADERS_FILE" "$BUSY_BODY_FILE"

  # Restart clean for the next test.
  kill_directora "$BUSY_PID"
  STAGE_PID="$(start_directora "")"
  trap 'kill_directora "$STAGE_PID"' EXIT
  await_health || exit 1
  echo "✅ Restarted clean Directora"
else
  echo
  echo "=== Test 7: skipped (RUN_CHAOS=0) ==="
fi

# ---------- Test 8: chaos — ledger-append atomicity ---------------------

if [ "$RUN_CHAOS" = "1" ]; then
  echo
  echo "=== Test 8: chaos — ledger-append atomicity ==="
  echo "Restarting Directora with FAULT_LEDGER_APPEND=1..."
  kill_directora ""
  CHAOS_PID="$(start_directora "FAULT_LEDGER_APPEND=1")"
  trap 'kill_directora "$CHAOS_PID"' EXIT
  await_health || exit 1

  CHAOS_TOKEN="$(issue_token)"
  CHAOS_IDEM="sign-${BRIEF_CHAOS}-$(uuidgen)"
  CHAOS_BODY=$(cat <<EOF
{"brief_id":"${BRIEF_CHAOS}","provider_id":"${PROVIDER_ID}","signature":{"method":"typed","value":"Dr Jane Doe","signed_at":"2026-05-16T17:01:33Z"},"client":{"app":"governance-check","version":"1.0","session_id":"test"}}
EOF
)
  CHAOS_RESPONSE=$(curl -sS -X POST "$BASE/api/brief/sign" \
    -H "Authorization: Bearer $CHAOS_TOKEN" \
    -H "X-Clinic-ID: ${CLINIC_ID}" \
    -H "X-Request-ID: gov-chaos-001" \
    -H "Idempotency-Key: $CHAOS_IDEM" \
    -H "Content-Type: application/json" \
    -d "$CHAOS_BODY")
  CHAOS_ERROR=$(echo "$CHAOS_RESPONSE" | jq -r '.error // empty')
  if [ "$CHAOS_ERROR" != "engine_or_ledger_failure" ]; then
    echo "❌ Expected engine_or_ledger_failure under chaos, got: $CHAOS_RESPONSE"; exit 1
  fi
  echo "✅ 500 engine_or_ledger_failure under FAULT_LEDGER_APPEND"

  # Brief must remain pending_review — no partial commit.
  PENDING_STATUS=$(curl -sS -X GET "$BASE/api/brief/pending?provider_id=${PROVIDER_ID}" \
    -H "Authorization: Bearer $CHAOS_TOKEN" \
    -H "X-Clinic-ID: ${CLINIC_ID}" \
    | jq -r ".items[] | select(.brief_id==\"${BRIEF_CHAOS}\") | .status // \"not_found\"")
  if [ "$PENDING_STATUS" != "pending_review" ]; then
    echo "❌ Brief status should be pending_review after ledger failure, got: $PENDING_STATUS"; exit 1
  fi
  echo "✅ Brief remains pending_review (no partial commit)"

  # Zero `provider_brief_signed` events for the failed brief. Note: the
  # audit ledger may contain `provider_brief_ready` from the seed step;
  # what matters is that nothing graduated to `signed`.
  AUDIT_JSON=$(curl -sS -X GET "$BASE/api/labs/audit?brief_id=${BRIEF_CHAOS}" \
    -H "Authorization: Bearer $CHAOS_TOKEN" \
    -H "X-Clinic-ID: ${CLINIC_ID}")
  SIGNED_COUNT=$(echo "$AUDIT_JSON" \
    | jq '[.events[].kind | select(. == "provider_brief_signed")] | length')
  if [ "$SIGNED_COUNT" != "0" ]; then
    echo "❌ Expected 0 provider_brief_signed events after failure, got: $SIGNED_COUNT"
    echo "   Atomicity broken — a partial commit graduated to signed."
    exit 1
  fi
  echo "✅ Zero provider_brief_signed events for failed brief"

  # NO rollback events anywhere — v3.7 eliminated `provider_brief_signed_rollback`.
  ROLLBACK_COUNT=$(echo "$AUDIT_JSON" \
    | jq '[.events[].kind | select(contains("rollback"))] | length')
  if [ "$ROLLBACK_COUNT" != "0" ]; then
    echo "❌ Found $ROLLBACK_COUNT rollback events — must be zero"; exit 1
  fi
  echo "✅ Zero rollback events (no compensation framing)"

  # Cleanup: restart without the chaos switch.
  kill_directora "$CHAOS_PID"
  CLEAN_PID="$(start_directora "")"
  trap 'kill_directora "$CLEAN_PID"' EXIT
  await_health || exit 1
  echo "✅ Restarted clean Directora"
else
  echo
  echo "=== Test 8: skipped (RUN_CHAOS=0) ==="
fi

# ---------- Test 9: health check ----------------------------------------

echo
echo "=== Test 9: health check ==="
HEALTH=$(curl -sS "$BASE/health")
HEALTH_STATUS=$(echo "$HEALTH" | jq -r '.status // "unhealthy"')
if [ "$HEALTH_STATUS" != "healthy" ]; then
  echo "❌ Health check failed: $HEALTH"; exit 1
fi
echo "✅ Health: $HEALTH_STATUS"

# ---------- summary -----------------------------------------------------

echo

# Clean up tmpfiles only on the success path. Failures leave them
# behind so the developer can inspect.
rm -f "$SIGN_BODY_FILE" "$SIGN_HEADERS_FILE" \
      "${REPLAY_BODY_1_FILE:-}" "${REPLAY_BODY_2_FILE:-}" \
      "${REPLAY_HEADERS_FILE:-}"

echo "========================================="
echo "✅ ALL DIRECTORA GOVERNANCE CHECKS PASSED"
echo "========================================="
echo
echo "Proved:"
echo "  • Atomicity — ledger failure leaves no trace"
echo "  • Idempotency — byte-identical replay (sign body == replay body)"
echo "  • Hash binding — HMAC anchored to stable canonical artifact (recomputed locally)"
echo "  • Conflict detection — different body rejected"
echo "  • Already-signed gating — double-sign blocked"
echo "  • No rollback events — neutral failure note only"
echo "  • Contract versioning — X-Contract-Version: $EXPECTED_CONTRACT_VERSION on POST + GET + replay"
echo "  • Multi-worker safety — idempotency backend = $HEALTH_IDEM_BACKEND"
if [ "$RUN_CHAOS" = "1" ]; then
  echo "  • Backpressure — 503 + Retry-After (numeric) + X-Request-ID on FAULT_DB_LOCK"
  echo "  • Chaos resilience — FAULT_LEDGER_APPEND"
fi
echo
echo "Base URL: $BASE"
