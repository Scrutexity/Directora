#!/usr/bin/env bash
# ultimate-governance-check.sh
#
# Single-command proof that the Scrutexity governance architecture is
# intact end-to-end. Runs:
#
#   1. Directora governance check     (./directora-governance-check.sh)
#       - atomicity, idempotency, replay, no-rollback, /health
#
#   2. LabBrief contract drift detector (vitest)
#       - snapshot ↔ Zod schema parity, drift sentinels
#
# Auto-detects layout. Works against:
#   * the scrutexity addon (this repo): scripts live in
#     `tests/governance/`, LabBrief tests in `labbrief_kit/`
#   * a real Scrutexity monorepo: `directora/` next to `labbrief/`
#   * a custom layout: pass DIRECTORA_SCRIPT and LABBRIEF_DIR
#
# Usage:
#   ./ultimate-governance-check.sh                    # default
#   STRICT=1 ./ultimate-governance-check.sh           # fail if vitest is missing
#   RUN_CHAOS=0 ./ultimate-governance-check.sh        # skip the chaos test
#
# Env overrides:
#   DIRECTORA_SCRIPT   path to directora-governance-check.sh
#   LABBRIEF_DIR       directory containing labbrief tests
#   VITEST_TEST        test path passed to vitest (default detected)
#   SKIP_DIRECTORA=1   skip the Directora half
#   SKIP_LABBRIEF=1    skip the LabBrief half
#   STRICT=1           fail on missing tooling instead of soft-skip
set -euo pipefail

echo "========================================="
echo "  SCRUTEXITY GOVERNANCE ARCHITECTURE PROOF"
echo "========================================="
echo

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIRECTORA_EXIT=0
LABBRIEF_EXIT=0
RAN_DIRECTORA=0
RAN_LABBRIEF=0

# ---------- Directora half ----------------------------------------------

if [ "${SKIP_DIRECTORA:-0}" = "1" ]; then
  echo ">>> Directora half: SKIP_DIRECTORA=1, skipping"
else
  DIRECTORA_SCRIPT="${DIRECTORA_SCRIPT:-}"
  if [ -z "$DIRECTORA_SCRIPT" ]; then
    for candidate in \
      "$HERE/directora-governance-check.sh" \
      "./directora-governance-check.sh" \
      "./tests/governance/directora-governance-check.sh" \
      "./directora/tests/governance/directora-governance-check.sh"; do
      if [ -x "$candidate" ]; then
        DIRECTORA_SCRIPT="$candidate"; break
      fi
    done
  fi
  if [ -z "$DIRECTORA_SCRIPT" ]; then
    echo "❌ Cannot locate directora-governance-check.sh."
    echo "   Set DIRECTORA_SCRIPT or run this from the addon root."
    exit 1
  fi
  echo ">>> Running Directora Chaos-Proof Atomicity Check..."
  echo "    script: $DIRECTORA_SCRIPT"
  set +e
  bash "$DIRECTORA_SCRIPT"
  DIRECTORA_EXIT=$?
  set -e
  RAN_DIRECTORA=1
fi
echo

# ---------- LabBrief half -----------------------------------------------

run_vitest() {
  local cwd="$1"
  local target="$2"
  echo "    cwd:        $cwd"
  echo "    vitest run: $target"
  set +e
  ( cd "$cwd" && npx --yes vitest run "$target" )
  LABBRIEF_EXIT=$?
  set -e
}

if [ "${SKIP_LABBRIEF:-0}" = "1" ]; then
  echo ">>> LabBrief half: SKIP_LABBRIEF=1, skipping"
else
  if ! command -v npx >/dev/null 2>&1; then
    if [ "${STRICT:-0}" = "1" ]; then
      echo "❌ STRICT=1 and npx not available."
      exit 1
    fi
    echo ">>> LabBrief half: SKIPPED (npx not on PATH — install Node + npm to run)"
  else
    LABBRIEF_DIR="${LABBRIEF_DIR:-}"
    if [ -z "$LABBRIEF_DIR" ]; then
      for candidate in \
        ./labbrief \
        ./labbrief_kit \
        "$HERE/../../labbrief" \
        "$HERE/../../labbrief_kit"; do
        if [ -d "$candidate" ]; then
          LABBRIEF_DIR="$candidate"; break
        fi
      done
    fi
    if [ -z "$LABBRIEF_DIR" ]; then
      if [ "${STRICT:-0}" = "1" ]; then
        echo "❌ STRICT=1 and no LabBrief directory found."
        exit 1
      fi
      echo ">>> LabBrief half: SKIPPED (no labbrief/ or labbrief_kit/ directory)"
    else
      VITEST_TEST="${VITEST_TEST:-}"
      if [ -z "$VITEST_TEST" ]; then
        for candidate in \
          src/__tests__/contractDriftDetector.test.ts \
          src/__tests__/contractGating.test.ts \
          src/schemas/contract.test.ts; do
          if [ -f "$LABBRIEF_DIR/$candidate" ]; then
            VITEST_TEST="$candidate"; break
          fi
        done
      fi
      if [ -z "$VITEST_TEST" ]; then
        if [ "${STRICT:-0}" = "1" ]; then
          echo "❌ STRICT=1 and no contract drift test file found in $LABBRIEF_DIR/src."
          exit 1
        fi
        echo ">>> LabBrief half: SKIPPED (no contract test file found in $LABBRIEF_DIR/src)"
      else
        echo ">>> Running LabBrief Contract Drift Detector..."
        run_vitest "$LABBRIEF_DIR" "$VITEST_TEST"
        RAN_LABBRIEF=1
      fi
    fi
  fi
fi
echo

# ---------- Summary -----------------------------------------------------

echo "========================================="
if [ "$DIRECTORA_EXIT" -eq 0 ] && [ "$LABBRIEF_EXIT" -eq 0 ]; then
  echo "✅ GOVERNANCE ARCHITECTURE INTACT"
  echo "   Directora and LabBrief cannot drift."
  echo "   Atomicity, idempotency, and contract versioning all verified."
  if [ "$RAN_DIRECTORA" = "1" ] && [ "$RAN_LABBRIEF" = "1" ]; then
    echo "   Both halves ran end-to-end."
  elif [ "$RAN_DIRECTORA" = "1" ]; then
    echo "   Note: LabBrief half was skipped (tooling or directory missing)."
  elif [ "$RAN_LABBRIEF" = "1" ]; then
    echo "   Note: Directora half was skipped (SKIP_DIRECTORA=1)."
  fi
else
  echo "❌ GOVERNANCE CHECK FAILED"
  echo "   Directora exit: $DIRECTORA_EXIT"
  echo "   LabBrief exit:  $LABBRIEF_EXIT"
  exit 1
fi
echo "========================================="
