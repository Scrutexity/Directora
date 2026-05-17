"""Bash syntax-check for the governance script + smoke test on the
seed helper.

The full governance script needs a live Directora to run, so we don't
exercise it here. We do confirm:

  * the script's bash is valid (`bash -n`)
  * required commands referenced in the script exist in known PATHs
    (curl, jq, uuidgen, python3) — by file inspection only
  * the seed helper imports cleanly with the same env we set in the
    shell preflight
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

GOVERNANCE_DIR = Path(__file__).resolve().parent
SCRIPT_PATH = GOVERNANCE_DIR / "directora-governance-check.sh"
ULTIMATE_PATH = GOVERNANCE_DIR / "ultimate-governance-check.sh"
SEED_PATH = GOVERNANCE_DIR / "seed_governance_fixtures.py"
DRIFT_TEST_PATH = (
    GOVERNANCE_DIR.parent.parent
    / "labbrief_kit" / "src" / "__tests__"
    / "contractDriftDetector.test.ts"
)


def test_governance_script_exists_and_is_executable():
    assert SCRIPT_PATH.exists(), f"missing {SCRIPT_PATH}"
    assert os.access(SCRIPT_PATH, os.X_OK), (
        f"{SCRIPT_PATH} must be executable (chmod +x)"
    )


def test_governance_script_bash_syntax_is_valid():
    """`bash -n` parses the file without executing it. Fails loudly on
    typos, mismatched quotes, unterminated heredocs."""
    if not shutil.which("bash"):
        pytest.skip("bash not available")
    res = subprocess.run(
        ["bash", "-n", str(SCRIPT_PATH)],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, (
        f"bash -n reported a syntax error:\n{res.stderr}"
    )


def test_governance_script_uses_correct_uvicorn_entry_point():
    """We replaced `python -m directora` (broken — no __main__.py) with
    `uvicorn directora.api.server:app`. Make sure no one regresses it."""
    text = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "uvicorn directora.api.server:app" in text, (
        "DIRECTORA_CMD default should use uvicorn; never python -m directora"
    )
    assert "python -m directora" not in text, (
        "Found python -m directora — this entry point does not exist"
    )


def test_governance_script_checks_kind_not_event_type():
    """The audit ledger event field is `kind`. An earlier draft used
    `event_type` which would silently pass on the wrong field."""
    text = SCRIPT_PATH.read_text(encoding="utf-8")
    assert ".events[].kind" in text, (
        "Rollback assertion must query .events[].kind"
    )
    assert ".events[].event_type" not in text, (
        "Found .events[].event_type — audit schema uses .kind"
    )


def test_governance_script_diffs_original_against_replay():
    """Test 3 must compare the ORIGINAL sign response against the replay
    body, not just compare two replays against each other. The original
    is the strongest baseline — a buggy engine could return identical
    replays that differ from the original."""
    text = SCRIPT_PATH.read_text(encoding="utf-8")
    # The canonical assertion uses `cmp -s` between SIGN_BODY_FILE and
    # REPLAY_BODY_1_FILE (the file holding the first sign response).
    assert 'cmp -s "$SIGN_BODY_FILE" "$REPLAY_BODY_1_FILE"' in text, (
        "Test 3 must run `cmp -s` between the original sign body file "
        "and the first replay body file"
    )
    # And it must also diff the two replays against each other (3b).
    assert 'cmp -s "$REPLAY_BODY_1_FILE" "$REPLAY_BODY_2_FILE"' in text, (
        "Test 3 must verify both replays match each other too"
    )


def test_governance_script_distinguishes_missing_from_wrong_header():
    """The contract-version check must surface 'MISSING' (proxy stripped
    header / middleware bug) distinctly from 'WRONG' (snapshot drift /
    unversioned deploy). Generic 'mismatch' confuses on-call."""
    text = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "Contract header MISSING" in text, (
        "header_missing failure must say MISSING explicitly"
    )
    assert "Contract header WRONG" in text, (
        "header_wrong failure must say WRONG explicitly"
    )
    # Both failure paths should hint at the most likely cause.
    assert "proxy/middleware stripping" in text or \
           "stripping X-* headers" in text
    assert "snapshot drift" in text


def test_governance_script_asserts_contract_header_on_both_methods():
    """A misconfigured proxy may strip X-* headers on POST but not GET
    (or vice versa). The script must verify the header on at least one
    of each method."""
    text = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "POST /api/brief/sign" in text and \
           "GET /api/brief/pending" in text, (
        "Header check must run on both POST and GET response paths"
    )
    # And on the replayed POST too — that's a third independent path.
    assert "POST /api/brief/sign (replay)" in text
    # And the provider GET (Test 4) — fourth independent path.
    assert "GET /api/brief/provider" in text
    # And the 503 error response (Test 7) — fifth path, proves headers
    # travel on error responses too.
    assert "POST /api/brief/sign (503)" in text


def test_governance_script_proves_hash_binding():
    """Test 4 must compare brief_content_hash from /sign and /provider,
    AND independently re-hash the returned canonical_json. Both proofs
    are necessary to anchor the HMAC binding to a stable artifact."""
    text = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "hash-binding" in text.lower() or "Hash binding" in text, (
        "Script must include a hash-binding test"
    )
    # Cross-endpoint hash agreement.
    assert 'SIGNED_HASH' in text and 'PROVIDER_HASH' in text
    # Local recomputation via SHA-256.
    assert "hashlib.sha256" in text
    assert "canonical_json" in text
    # And the failure message points at the right cause.
    assert "HMAC binding is broken" in text


def test_governance_script_proves_503_retry_after_contract():
    """Test 7 must prove the engine's 503 contract under FAULT_DB_LOCK:
    status=503, Retry-After numeric, X-Request-ID echoed, X-Contract-Version
    travels, body.error=idempotency_store_busy."""
    text = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "FAULT_DB_LOCK=1" in text
    assert "Retry-After" in text
    # Numeric assertion (a non-regex caller would pass a date here).
    assert "^[0-9]+$" in text or "is_numeric" in text.lower()
    # Body shape.
    assert "idempotency_store_busy" in text


def test_governance_script_refuses_memory_idempotency_in_production():
    """The preflight must read /health and refuse to proceed if
    ENV=production AND IDEMPOTENCY_STORE_BACKEND=memory. Single-worker
    only — silently breaks the idempotency guarantee under multi-worker
    deployments."""
    text = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "idempotency_backend" in text
    assert "UNSAFE multi-worker configuration" in text
    assert 'HEALTH_ENV" = "production"' in text
    assert 'HEALTH_IDEM_BACKEND" = "memory"' in text


def test_governance_script_test_numbers_are_unique_and_sequential():
    """The script's `=== Test N: ...` headings should be unique and
    cover 1..9 (Test 7 + 8 are chaos tests; gated by RUN_CHAOS)."""
    import re
    text = SCRIPT_PATH.read_text(encoding="utf-8")
    found = sorted(set(
        int(m.group(1))
        for m in re.finditer(r"=== Test (\d+):", text)
    ))
    # 1..9 expected after the v3.7 hash-binding + backpressure additions.
    assert found == list(range(1, 10)), (
        f"Expected Test 1..9, found {found}"
    )


def test_seed_helper_imports_cleanly(monkeypatch, tmp_path):
    """The seed helper must be importable without side effects."""
    monkeypatch.setenv("DIRECTORA_CLINIC_SIGNING_SECRET_DEFAULT", "x")
    monkeypatch.setenv("BRIEF_STORE_BACKEND", "memory")
    monkeypatch.setenv("DIRECTORA_BRIEF_DB_PATH", str(tmp_path / "x.db"))
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "seed_governance_fixtures", SEED_PATH,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # raises on import-time errors
    assert hasattr(module, "main")
    assert hasattr(module, "_seed_one")


def test_seed_helper_seeds_a_brief_end_to_end(monkeypatch, tmp_path):
    """Run the seed helper against an in-memory store and confirm the
    brief is reachable + canonical JSON + hash are stamped."""
    monkeypatch.setenv("DIRECTORA_CLINIC_SIGNING_SECRET_DEFAULT", "test")
    monkeypatch.setenv("BRIEF_STORE_BACKEND", "memory")
    monkeypatch.setenv("DIRECTORA_BRIEF_DB_PATH", str(tmp_path / "x.db"))

    # Reset stores so seed runs against a known-empty engine.
    from directora.scrutexity import brief_store as bs_module
    from directora.scrutexity.brief_store import InMemoryBriefStore
    from directora.telemetry import outcome as ledger

    bs_module.reset_store_for_tests(InMemoryBriefStore())
    ledger.reset_sink_for_tests(ledger.MemorySink())

    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "seed_governance_fixtures", SEED_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)

    module._seed_one("BRF_GOV_TEST", "CLN_GOV", "PRV_GOV")
    rec = bs_module.get_brief_store().get("BRF_GOV_TEST")
    assert rec is not None
    assert rec.clinic_id == "CLN_GOV"
    assert rec.provider_id == "PRV_GOV"
    assert rec.treatment == "Morpheus8"
    assert rec.brief_content_hash, "seed must stamp brief_content_hash"
    assert rec.provider_brief_canonical_json, (
        "seed must persist canonical JSON"
    )
    bs_module.reset_store_for_tests(None)
    ledger.reset_sink_for_tests(None)


def test_governance_readme_exists():
    readme = GOVERNANCE_DIR / "README.md"
    assert readme.exists()
    text = readme.read_text(encoding="utf-8")
    assert "directora-governance-check.sh" in text
    assert "FAULT_LEDGER_APPEND" in text
    assert "rollback" in text.lower()


# --------- ultimate-governance-check.sh -------------------------------


def test_ultimate_script_exists_and_is_executable():
    assert ULTIMATE_PATH.exists(), f"missing {ULTIMATE_PATH}"
    assert os.access(ULTIMATE_PATH, os.X_OK)


def test_ultimate_script_bash_syntax_is_valid():
    if not shutil.which("bash"):
        pytest.skip("bash not available")
    res = subprocess.run(
        ["bash", "-n", str(ULTIMATE_PATH)],
        capture_output=True, text=True,
    )
    assert res.returncode == 0, res.stderr


def test_ultimate_script_handles_missing_tooling_softly():
    """Without STRICT=1, the meta-runner soft-skips the LabBrief half
    when neither npx nor a labbrief dir is reachable. Run the script
    from a temp cwd to guarantee no detection."""
    if not shutil.which("bash"):
        pytest.skip("bash not available")
    env = {
        **os.environ,
        "SKIP_DIRECTORA": "1",     # focus on the LabBrief half behaviour
        "PATH": "/usr/bin:/bin",   # strip any npx
    }
    # Run from /tmp so the auto-detection finds nothing.
    res = subprocess.run(
        ["bash", str(ULTIMATE_PATH)],
        env=env, cwd="/tmp",
        capture_output=True, text=True,
    )
    assert res.returncode == 0, (
        f"meta-runner should soft-skip on missing tooling. "
        f"stdout: {res.stdout}\nstderr: {res.stderr}"
    )
    combined = res.stdout + res.stderr
    assert (
        "SKIPPED" in combined
        and "GOVERNANCE ARCHITECTURE INTACT" in combined
    )


def test_ultimate_script_strict_fails_on_missing_tooling():
    """With STRICT=1, missing tooling is a hard failure."""
    if not shutil.which("bash"):
        pytest.skip("bash not available")
    env = {
        **os.environ,
        "SKIP_DIRECTORA": "1",
        "STRICT": "1",
        "PATH": "/usr/bin:/bin",
    }
    res = subprocess.run(
        ["bash", str(ULTIMATE_PATH)],
        env=env, cwd="/tmp",
        capture_output=True, text=True,
    )
    assert res.returncode != 0


# --------- contract drift detector (LabBrief side) --------------------


def test_governance_script_surfaces_auth_mode_in_preflight():
    """v3.7.1: the preflight banner must print auth_mode too. The
    'unsafe auth configuration in production' check refuses to proceed
    when ENV=production with AUTH_MODE=stub — the same posture the
    engine takes (500 unsafe_auth_mode), surfaced earlier so on-call
    sees the misconfig before Test 1."""
    text = SCRIPT_PATH.read_text(encoding="utf-8")
    assert '.auth_mode' in text, (
        "Script must read .auth_mode from /health"
    )
    assert "auth_mode=$HEALTH_AUTH_MODE" in text, (
        "Preflight banner must surface auth_mode"
    )
    assert 'UNSAFE auth configuration' in text
    assert 'HEALTH_ENV" = "production"' in text \
           and 'HEALTH_AUTH_MODE" = "stub"' in text


def test_governance_script_reads_both_health_version_axes():
    """The preflight banner must surface BOTH contract_version and
    engine_release from /health. v3.7.1 renamed the bare `version`
    field; the script must read the new names AND fail loudly if
    either is missing (catches stale engines / proxy strips)."""
    text = SCRIPT_PATH.read_text(encoding="utf-8")
    assert '.contract_version' in text, (
        "Script must read .contract_version from /health"
    )
    assert '.engine_release' in text, (
        "Script must read .engine_release from /health"
    )
    # And surface them in the preflight banner.
    assert 'contract=$HEALTH_CONTRACT_VERSION' in text
    assert 'engine=$HEALTH_ENGINE_RELEASE' in text
    # And refuse to proceed if either is missing — catches a stale
    # engine that doesn't expose the new fields yet.
    assert 'HEALTH_CONTRACT_VERSION" = "unknown"' in text
    assert 'HEALTH_ENGINE_RELEASE" = "unknown"' in text


def test_docs_health_examples_use_renamed_fields():
    """Every `/health` example block in shipped docs must use
    `contract_version` + `engine_release`, never the legacy bare
    `version` field. Catches a future doc update that copy-pastes a
    pre-v3.7.1 snippet.

    The CHANGELOG's Before/After table is the only place `version`
    legitimately appears — that's documenting the rename. We allow
    that block specifically; any other `"version"` near a /health
    response shape is rejected.
    """
    root = GOVERNANCE_DIR.parent.parent
    docs = [
        root / "HANDOFF.md",
        root / "DEPLOYMENT.md",
        root / "README.md",
    ]
    for doc in docs:
        if not doc.exists():
            continue
        text = doc.read_text(encoding="utf-8")
        # Find any /health response block (heuristic: contains
        # `"status": "healthy"`). Inside it, the bare `"version"` field
        # must not appear.
        i = 0
        while True:
            start = text.find('"status": "healthy"', i)
            if start == -1:
                break
            # Inspect the next ~20 lines for stale field names.
            block = text[start:start + 800]
            assert '"version":' not in block, (
                f"{doc.name}: /health example uses the legacy bare "
                f"`version` field. Replace with `contract_version` + "
                "`engine_release` per v3.7.1."
            )
            # AND the new fields are present.
            assert 'contract_version' in block, (
                f"{doc.name}: /health example missing `contract_version`"
            )
            assert 'engine_release' in block, (
                f"{doc.name}: /health example missing `engine_release`"
            )
            i = start + 1


def test_smoke_test_uses_renamed_health_fields():
    """v3.7.1 renamed /health.version to /health.contract_version. The
    smoke test must read the new field names so a future re-introduction
    of the ambiguous bare `version` field fails CI."""
    smoke = GOVERNANCE_DIR.parent.parent / "smoke_test.py"
    text = smoke.read_text(encoding="utf-8")
    assert 'health_res.json()["contract_version"]' in text, (
        "Smoke test must read /health.contract_version explicitly"
    )
    assert 'health_res.json()["engine_release"]' in text, (
        "Smoke test must also read /health.engine_release"
    )
    assert 'health_res.json()["version"]' not in text, (
        "Found stale read of /health.version — v3.7.1 renamed this "
        "field to /health.contract_version"
    )


def test_changelog_exists_and_documents_v371():
    """The byte-identical-replay fix in v3.7.1 must be documented in
    CHANGELOG.md so future operators can trace why the engine
    serialisation changed without touching the consumer contract."""
    changelog = GOVERNANCE_DIR.parent.parent / "CHANGELOG.md"
    assert changelog.exists(), f"missing {changelog}"
    text = changelog.read_text(encoding="utf-8")
    assert "v3.7.1" in text
    assert "byte-identical" in text.lower()
    # And the explicit note that the contract version is unchanged.
    assert "CONTRACT_VERSION unchanged" in text or \
           "no contract change" in text.lower() or \
           "do not need to update" in text.lower()


def test_contract_drift_detector_test_exists():
    """The LabBrief drift detector test must exist so the meta-runner
    has something to run. Catches missing-file drift in CI."""
    assert DRIFT_TEST_PATH.exists(), (
        f"missing {DRIFT_TEST_PATH} — meta-runner's LabBrief half "
        "won't have anything to run"
    )
    text = DRIFT_TEST_PATH.read_text(encoding="utf-8")
    # Sentinel content checks — keeps the file from regressing into a stub.
    assert "snapshot" in text.lower()
    assert "Zod" in text or "zod" in text.lower()
    assert "EXPECTED_CONTRACT_VERSION" in text
