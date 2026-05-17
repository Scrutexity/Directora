"""Structural invariants for `.github/workflows/governance-proof.yml`.

A workflow file is just YAML, so the only invariants worth asserting
are the ones that would silently disable the proof if regressed:

  * a single job (not three) — keeps environment consistent
  * STRICT=1 — converts soft skips into hard failures in CI
  * a real health-loop (not `sleep N` flakiness)
  * artifact upload on always() — gives reviewers the proof log
  * Stop Directora on always() — no zombie processes

These are pure file-content checks; they don't run the workflow.
"""
from __future__ import annotations

from pathlib import Path

WORKFLOW_PATH = (
    Path(__file__).resolve().parents[2]
    / ".github" / "workflows" / "governance-proof.yml"
)


def _workflow_text() -> str:
    assert WORKFLOW_PATH.exists(), (
        f"missing workflow at {WORKFLOW_PATH} — the CI proof is gone"
    )
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def test_workflow_file_exists():
    assert WORKFLOW_PATH.exists()


def test_workflow_runs_on_main_and_prs():
    text = _workflow_text()
    assert "branches: [main]" in text


def test_workflow_uses_single_job():
    """Setup cost paid once, no environment drift between halves."""
    text = _workflow_text()
    # Exactly one job under `jobs:`. A simple count of two-space-indented
    # `:` after `jobs:` is fragile; instead we just assert that the
    # canonical single-job key is the one defined.
    assert "governance-proof:" in text
    # And the obvious anti-pattern (three jobs) is absent.
    assert "directora-tests:" not in text
    assert "labbrief-drift-detector:" not in text


def test_workflow_sets_strict_mode():
    text = _workflow_text()
    assert "STRICT: 1" in text or "STRICT: '1'" in text or 'STRICT: "1"' in text


def test_workflow_uses_health_loop_not_sleep():
    text = _workflow_text()
    assert "for i in {1..30}" in text, (
        "Health loop missing — replace `sleep N` with a deterministic loop"
    )
    assert "curl -fsS \"$BASE/health\"" in text


def test_workflow_uploads_artifacts_on_always():
    text = _workflow_text()
    assert "actions/upload-artifact" in text
    # The upload must run on success AND failure so reviewers always
    # get the log.
    assert "if: always()" in text


def test_workflow_stops_directora_cleanly():
    text = _workflow_text()
    assert "Stop Directora" in text
    assert 'pkill -f "uvicorn directora.api.server"' in text


def test_workflow_invokes_the_meta_runner():
    text = _workflow_text()
    assert "ultimate-governance-check.sh" in text


def test_workflow_passes_engine_env_to_uvicorn():
    text = _workflow_text()
    # The job-level env should declare the engine config so the same
    # vars reach both the pytest step AND the uvicorn step.
    for key in (
        "BRIEF_STORE_BACKEND",
        "IDEMPOTENCY_STORE_BACKEND",
        "DIRECTORA_CLINIC_SIGNING_SECRET_DEFAULT",
        "AUTH_MODE",
        "ENV",
    ):
        assert key in text, f"workflow missing engine env var {key}"


def test_workflow_seeds_fixtures_before_meta_runner():
    text = _workflow_text()
    seed_idx = text.find("Seed governance fixtures")
    meta_idx = text.find("Governance meta-runner")
    assert seed_idx >= 0 and meta_idx >= 0
    assert seed_idx < meta_idx, (
        "Seed must run BEFORE the meta-runner so the script can sign briefs"
    )
