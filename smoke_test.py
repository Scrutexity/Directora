"""End-to-end smoke test using the provided Elite Aesthetics NYC receipt.

Runs the full Scrutexity flow (no real MCP, no real LLM) and prints a
checklist of every expected outcome. This is the merge-readiness probe.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

import os
import uuid

os.environ.setdefault("DIRECTORA_CLINIC_SIGNING_SECRET_DEFAULT", "smoke-secret")
# v3.5: SQLite brief store. v3.6: SQLite idempotency store + JWT auth.
os.environ.setdefault("BRIEF_STORE_BACKEND", "sqlite")
os.environ.setdefault(
    "DIRECTORA_BRIEF_DB_PATH",
    "./.smoke_directora_briefs.db",
)
os.environ.setdefault("IDEMPOTENCY_STORE_BACKEND", "memory")  # hermetic for smoke
os.environ.setdefault(
    "CORS_ALLOW_ORIGINS", "http://localhost:5173,http://localhost:3000"
)
os.environ.setdefault("AUTH_MODE", "stub")
os.environ.setdefault("ENV", "development")

from directora.api import idempotency as idem_module
from directora.api.auth import encode_stub_token
from directora.api.server import create_app
from directora.mirror import transcript as authority_review_summary
from directora.nodes import (
    authority_brief_node,
    owner_brief_node,
    provider_brief_node,
    render_seedance,
)
from directora.scrutexity import authority_brief as ab
from directora.scrutexity import brief_store as bs_module
from directora.scrutexity import export, language
from directora.scrutexity.brief_store import InMemoryBriefStore
from directora.scrutexity.schema import ReceiptValidationError
from directora.telemetry import outcome as ledger

from fastapi.testclient import TestClient


# Original ambiguous receipt — exactly as supplied. treatments_tested has
# three entries with no explicit `treatment`. Strict mode must reject it.
AMBIGUOUS_RECEIPT = {
    "clinic_name": "Elite Aesthetics NYC",
    "market": "Upper East Side, NYC",
    "treatments_tested": ["Morpheus8", "lip filler", "Botox"],
    "primary_visibility_gap": (
        "Did not surface in this prompt set for Morpheus8 acne scars Upper East Side"
    ),
    "competitors_surfacing_more_often": ["Competitor A", "Competitor B"],
    "booking_friction": "Treatment CTA is not visible above the fold",
    "claim_risk_notes": [
        "Avoid guaranteed skin tightening claims",
        "Avoid unqualified before/after promises",
    ],
    "first_fix_id_prioritize": (
        "Create provider-led Morpheus8 acne scar content with safe expectations "
        "and a consult CTA"
    ),
}

# Same receipt but with the focus treatment named explicitly. This is the
# shape the Authority Engine expects after the upstream Scrutexity surface
# picks which treatment this brief covers.
RECEIPT = {**AMBIGUOUS_RECEIPT, "treatment": "Morpheus8"}


@dataclass
class State:
    run_id: str = "smoke-001"
    tier: str = "quality"          # exercise the Quality Render Step path
    clinic_name: str | None = None
    treatment: str | None = None
    market: str | None = None
    primary_visibility_gap: str | None = None
    competitors_surfacing_more_often: list = field(default_factory=list)
    first_fix_id_prioritize: str | None = None
    claim_risk_notes: list = field(default_factory=list)
    approval_status: str | None = None
    receipt_input: dict | None = None
    clinic_context: dict | None = None
    authority_brief: dict | None = None
    authority_brief_validation: dict | None = None
    directora_input: dict | None = None
    authority_review: list = field(default_factory=list)
    selected_recommendation: object | None = None
    prompt: str = "Morpheus8 acne scars, Upper East Side"
    shot_plan: list = field(default_factory=list)
    use_seedance: bool = True
    provider_brief: dict | None = None
    owner_brief: dict | None = None
    telemetry: dict = field(default_factory=lambda: {"events": []})


def main() -> int:
    # Hermetic SQLite + in-memory ledger / idempotency.
    import pathlib
    db_path = pathlib.Path(os.environ["DIRECTORA_BRIEF_DB_PATH"])
    if db_path.exists():
        db_path.unlink()
    from directora.scrutexity.brief_store_sqlite import SQLiteBriefStore
    ledger.reset_sink_for_tests(ledger.MemorySink())
    bs_module.reset_store_for_tests(SQLiteBriefStore(path=str(db_path)))
    idem_module.reset_store_for_tests(idem_module.InMemoryIdempotencyStore())

    # 0) Strict-validation probe — the user's original receipt has
    # treatments_tested=[3 items] with no `treatment`. Must reject.
    strict_caught = False
    try:
        ab.build_authority_brief(AMBIGUOUS_RECEIPT, None)
    except ReceiptValidationError as exc:
        strict_caught = True
        strict_error_summary = str(exc)
    else:
        strict_error_summary = "unexpectedly accepted ambiguous receipt"

    state = State(receipt_input=RECEIPT, clinic_context=None)
    # Identifiers the brief store / API need.
    state.brief_id = "BRF_SMOKE_01"  # type: ignore[attr-defined]
    state.clinic_id = "CLN_ELITE_NYC"  # type: ignore[attr-defined]
    state.provider_id = "PRV_SMOKE"  # type: ignore[attr-defined]

    # 1) Authority Brief
    brief_delta = authority_brief_node.run(state)
    for k, v in brief_delta.items():
        setattr(state, k, v)
    brief = state.authority_brief

    # 2) Authority Review (simulated multi-persona findings)
    state.authority_review = _fake_findings()
    state.selected_recommendation = "Compliance Reviewer"
    review_delta = authority_review_summary.attach_to_state(state)
    for k, v in review_delta.items():
        setattr(state, k, v)
    ledger.record_outcome(state, kind="authority_review_completed")
    for finding in state.authority_review_summary or []:
        if finding["risk_level"] in ("medium", "high"):
            ledger.record_outcome(
                state,
                kind="claim_risk_flagged",
                risk_level=finding["risk_level"],
                reason=finding["concern_type"],
            )
    if brief.get("approval_required"):
        ledger.record_outcome(state, kind="human_approval_required")

    # 3) Asset export (3-5 claim-safe assets)
    drafted = {
        "short_form_script": (
            "Provider voiceover: Morpheus8 supports treatment of acne scars "
            "with provider-reviewed planning. Book a consult."
        ),
        "faq_block": (
            "Q: What is Morpheus8 for acne scars? "
            "A: A microneedling+RF treatment evaluated by a provider during consult."
        ),
        "gbp_post": (
            "We guarantee dramatic results — invisible to AI search."  # forbidden language test
        ),
        "landing_page_section": (
            "Morpheus8 in Upper East Side. Provider-led, treatment-specific consult above the fold."
        ),
        "provider_quote": (
            "Dr. K: We tailor Morpheus8 to each patient after assessment."
        ),
    }
    bundle = export.render_bundle(brief, drafted)
    for asset in bundle:
        ledger.record_outcome(
            state,
            kind="asset_drafted",
            engine="scrutexity",
            extra_asset_type=asset["asset_type"],
        )
    ledger.record_outcome(state, kind="export_completed")

    # 4) Quality Render Step (no real MCP -> safe fallback, must NOT block)
    render_delta = render_seedance.render(state)
    for k, v in render_delta.items():
        setattr(state, k, v)

    # 5a) Provider Brief snippet (Brief Path, provider-facing)
    provider_delta = provider_brief_node.run(state)
    for k, v in provider_delta.items():
        setattr(state, k, v)
    provider_brief = state.provider_brief
    brief_content_hash_at_generation = state.brief_content_hash  # type: ignore[attr-defined]

    # 5b) Owner Brief snippet (uses the ledger summary)
    owner_delta = owner_brief_node.run(state)
    for k, v in owner_delta.items():
        setattr(state, k, v)
    owner_brief = state.owner_brief

    # 6) Final ledger roll-up
    final = ledger.finalize_node(state)
    state.telemetry["summary"] = final["telemetry"]["summary"]

    # 7) Brief API sign-off probe — drive the FastAPI app via TestClient.
    api = TestClient(create_app())
    # v3.5: observability + CORS probe. We send a request_id header and
    # verify the response echoes it.
    obs_res = api.get(
        "/api/brief/pending",
        headers={
            "Authorization": f"Bearer {encode_stub_token(state.provider_id, state.clinic_id)}",  # noqa: E501
            "X-Clinic-ID": state.clinic_id,
            "X-Request-ID": "req_smoke_obs_001",
        },
    )
    obs_ok = (
        obs_res.status_code == 200
        and obs_res.headers.get("X-Request-ID") == "req_smoke_obs_001"
    )
    token = encode_stub_token(
        provider_id=state.provider_id,
        clinic_id=state.clinic_id,
        roles=("provider",),
    )
    hdrs_base = {"Authorization": f"Bearer {token}", "X-Clinic-ID": state.clinic_id}

    # 7a) GET /api/brief/pending — should list the smoke brief.
    pending_res = api.get(
        "/api/brief/pending",
        headers={**hdrs_base, "X-Request-ID": "smoke-pending"},
    )
    pending_ok = pending_res.status_code == 200 and any(
        item["brief_id"] == state.brief_id for item in pending_res.json()["items"]
    )

    # 7b) GET /api/brief/provider — canonical snippet + hash.
    prov_res = api.get(
        "/api/brief/provider",
        params={"brief_id": state.brief_id},
        headers=hdrs_base,
    )
    prov_ok = (
        prov_res.status_code == 200
        and prov_res.json()["brief_content_hash"] == brief_content_hash_at_generation
    )

    # 7c) POST /api/brief/sign — happy path.
    sign_body = {
        "brief_id": state.brief_id,
        "provider_id": state.provider_id,
        "signature": {
            "method": "typed",
            "value": "Dr Jane Doe",
            "signed_at": "2026-05-16T17:01:33Z",
        },
        "client": {
            "app": "labbrief",
            "version": "2.5.0",
            "session_id": "sess_smoke",
        },
    }
    sign_res = api.post(
        "/api/brief/sign",
        headers={
            **hdrs_base,
            "Idempotency-Key": f"sign-{state.brief_id}-{uuid.uuid4()}",
            "X-Request-ID": "smoke-sign",
            "Content-Type": "application/json",
        },
        json=sign_body,
    )
    sign_ok = (
        sign_res.status_code == 200
        and sign_res.json()["status"] == "signed"
        and sign_res.json()["brief_content_hash"] == brief_content_hash_at_generation
    )
    signed_event_id = sign_res.json().get("ledger_event_id") if sign_ok else None

    # 7d) GET /api/labs/audit — must show provider_brief_signed.
    audit_res = api.get(
        "/api/labs/audit",
        params={"brief_id": state.brief_id},
        headers=hdrs_base,
    )
    audit_ok = audit_res.status_code == 200 and any(
        e["kind"] == "provider_brief_signed"
        for e in audit_res.json()["events"]
    )

    # 7e) Idempotency replay — same Idempotency-Key, same body → byte-identical
    # 200 with X-Idempotency-Replayed: true (v3.6).
    initial_sign_idem = sign_res.request.headers.get("Idempotency-Key")
    replay_res = api.post(
        "/api/brief/sign",
        headers={
            **hdrs_base,
            "Idempotency-Key": initial_sign_idem,
            "Content-Type": "application/json",
        },
        json=sign_body,
    )
    replay_ok = (
        replay_res.status_code == 200
        and replay_res.headers.get("X-Idempotency-Replayed") == "true"
        and replay_res.json() == sign_res.json()
    )

    # 7f) Different idempotency key on already-signed brief → already_signed
    # with the stored ledger_event_id.
    sign_attempt = api.post(
        "/api/brief/sign",
        headers={
            **hdrs_base,
            "Idempotency-Key": f"sign-{state.brief_id}-{uuid.uuid4()}",
            "Content-Type": "application/json",
        },
        json=sign_body,
    )
    already_ok = (
        sign_attempt.status_code == 409
        and sign_attempt.json().get("error") == "already_signed"
        and sign_attempt.json().get("ledger_event_id") == signed_event_id
    )

    # 7g) /health endpoint returns 200 healthy + contract_version + backends.
    # `contract_version` is the v3.7.1 explicit field name (the legacy
    # bare `version` was renamed to avoid being read as "engine version").
    health_res = api.get("/health")
    health_ok = (
        health_res.status_code == 200
        and health_res.json()["contract_version"]
        and health_res.json()["engine_release"]
        and health_res.json()["store_backend"] == "sqlite"
    )
    contract_version_header_ok = (
        sign_res.headers.get("X-Contract-Version") is not None
    )

    # ---------- assertions / checklist ----------
    checks: list[tuple[str, bool, str]] = []

    checks.append(("Schema rejects ambiguous receipt", strict_caught, strict_error_summary))
    checks.append(("Authority Brief created", brief is not None and brief["treatment"] == "Morpheus8", f"treatment={brief and brief['treatment']}"))
    checks.append(("Validation OK", state.authority_brief_validation["ok"] is True, str(state.authority_brief_validation)))
    checks.append(("Authority Review Summary generated", len(state.authority_review_summary or []) >= 3, f"turns={len(state.authority_review_summary or [])}"))
    checks.append(("Owner Brief snippet created", owner_brief is not None and owner_brief["asset_type"] == "owner_brief_snippet", "ok"))
    checks.append(("Provider Brief snippet created", provider_brief is not None and provider_brief["asset_type"] == "provider_brief_snippet", "ok"))
    checks.append(("Provider Brief headline names treatment + clinic", provider_brief is not None and "Morpheus8" in provider_brief["headline"] and "Elite Aesthetics NYC" in provider_brief["headline"], provider_brief and provider_brief["headline"]))
    checks.append(("Provider Brief checklist non-empty", provider_brief is not None and len(provider_brief["claim_risk_review_checklist"]) >= 7, f"checklist_len={provider_brief and len(provider_brief['claim_risk_review_checklist'])}"))
    checks.append(("Provider Brief selected recommendation surfaces", provider_brief is not None and provider_brief["selected_recommendation"] is not None and provider_brief["selected_recommendation"]["reviewer_role"] == "Compliance Reviewer", "ok"))
    checks.append(("3-5 claim-safe assets exported", 3 <= len(bundle) <= 5, f"asset_count={len(bundle)}"))

    # All clinic-facing surfaces include the canonical disclaimer.
    md = state.authority_review_summary_markdown or ""
    owner_summary = owner_brief["summary"] if owner_brief else ""
    disclaimers_ok = (
        language.DISCLAIMER in md
        and owner_brief["disclaimer"] == language.DISCLAIMER
        and provider_brief["disclaimer"] == language.DISCLAIMER
        and all(asset["disclaimer"] == language.DISCLAIMER for asset in bundle)
    )
    checks.append(("Disclaimer present everywhere clinic-facing", disclaimers_ok, "yes"))

    # No forbidden language in any clinic-facing surface.
    clinic_surfaces: dict[str, str] = {
        "authority_review_summary_markdown": md,
        "owner_brief_summary": owner_summary,
        "provider_brief_summary": provider_brief["provider_facing_summary"],
    }
    for asset in bundle:
        body = asset["body"]
        clinic_surfaces[f"asset:{asset['asset_type']}"] = body if isinstance(body, str) else json.dumps(body)
    leaks: dict[str, list[str]] = {}
    for name, text in clinic_surfaces.items():
        hits = language.contains_forbidden(text)
        if hits:
            leaks[name] = hits
    checks.append(("No forbidden language in clinic-facing output", not leaks, f"leaks={leaks}" if leaks else "clean"))

    # Render fallback did not block — render result still present and not skipped-with-error-flag.
    render = state.render
    checks.append(
        (
            "Render failure does not block final output",
            render is not None and (owner_brief is not None and bundle and state.authority_review_summary is not None),
            f"render_label={render['label']}, engine={render['engine']}",
        )
    )

    # Re-compute the ledger summary after sign-off so we see the new event kinds.
    final_after_sign = ledger.finalize_node(state)
    state.telemetry["summary"] = final_after_sign["telemetry"]["summary"]

    # Brief API checks
    checks.append(("Brief API pending lists smoke brief", pending_ok, f"status={pending_res.status_code}"))
    checks.append(("Brief API provider returns canonical hash", prov_ok, f"status={prov_res.status_code}"))
    checks.append(("Brief API sign happy path", sign_ok, f"status={sign_res.status_code}, ledger_event_id={signed_event_id}"))
    checks.append(("Brief API audit shows provider_brief_signed", audit_ok, f"status={audit_res.status_code}"))
    checks.append(("Brief API rejects re-sign with already_signed", already_ok, f"status={sign_attempt.status_code}"))
    checks.append(("Idempotent replay returns same body + X-Idempotency-Replayed", replay_ok, f"status={replay_res.status_code}"))
    checks.append(("Health endpoint reports healthy + version", health_ok, f"status={health_res.status_code}"))
    checks.append(("Responses carry X-Contract-Version header", contract_version_header_ok, f"version={sign_res.headers.get('X-Contract-Version')}"))
    checks.append(("Observability echoes X-Request-ID", obs_ok, f"echoed={obs_res.headers.get('X-Request-ID')}"))
    checks.append(("Smoke ran against SQLite backend", db_path.exists(), f"db={db_path}"))
    checks.append(("Contract snapshot present + versioned", pathlib.Path("shared/brief-api-contract.json").exists(), "shared/brief-api-contract.json"))

    # Governed Workflow Ledger captured the expected event kinds.
    summary = state.telemetry["summary"]
    required_kinds = {
        "authority_brief_created",
        "authority_review_completed",
        "asset_drafted",
        "claim_risk_flagged",
        "human_approval_required",
        "render_fallback",   # we are in fast/no-MCP, should record fallback
        "provider_brief_ready",
        "owner_brief_ready",
        "export_completed",
        "provider_brief_signed",
    }
    seen_kinds = set(summary["by_kind"].keys())
    missing_kinds = required_kinds - seen_kinds
    checks.append(
        (
            "Governed Workflow Ledger recorded all required event kinds",
            not missing_kinds,
            f"missing={sorted(missing_kinds)}" if missing_kinds else "all kinds present",
        )
    )

    # ----- Pretty print -----
    print("=" * 78)
    print("Scrutexity Authority Engine — Smoke Test: Elite Aesthetics NYC")
    print("=" * 78)
    for label, ok, detail in checks:
        mark = "PASS" if ok else "FAIL"
        print(f"[{mark}] {label}: {detail}")
    print("=" * 78)
    print(f"clinic       : {brief['clinic_name']}")
    print(f"treatment    : {brief['treatment']}")
    print(f"market       : {brief['market']}")
    print(f"primary gap  : {brief['primary_visibility_gap']}")
    print(f"first fix    : {brief['first_fix_id_prioritize']}")
    print(f"approval     : {state.approval_status}")
    print(f"render label : {state.render['label']}")
    print(f"ledger kinds : {dict(summary['by_kind'])}")
    print(f"risk count   : {summary['claim_risk_count']}")
    print(f"approvals req: {summary['human_approval_required_count']}")
    print(f"render falls : {summary['render_fallback_count']}")
    print(f"treatments   : {summary['treatments_processed']}")
    print("=" * 78)
    print("\nProvider Brief snippet:\n")
    print(f"  Headline: {provider_brief['headline']}")
    print(f"  Approval status: {provider_brief['human_approval_status']}")
    print(f"  Selected recommendation: {provider_brief['selected_recommendation']['reviewer_role']} ({provider_brief['selected_recommendation']['risk_level']} risk)")
    print(f"  Checklist items ({len(provider_brief['claim_risk_review_checklist'])}):")
    for item in provider_brief["claim_risk_review_checklist"][:5]:
        print(f"    - {item}")
    if len(provider_brief["claim_risk_review_checklist"]) > 5:
        print(f"    ... and {len(provider_brief['claim_risk_review_checklist']) - 5} more")
    print(f"  Suggested safe language ({len(provider_brief['suggested_safe_language'])}):")
    for line in provider_brief["suggested_safe_language"][:3]:
        print(f"    - {line}")
    if len(provider_brief["suggested_safe_language"]) > 3:
        print(f"    ... and {len(provider_brief['suggested_safe_language']) - 3} more")
    print("=" * 78)
    print("\nOwner Brief snippet summary:\n")
    print(owner_brief["summary"])
    print("\n--- disclaimer ---")
    print(owner_brief["disclaimer"])
    print("=" * 78)
    print("\nAuthority Review Summary (first 600 chars of markdown):\n")
    print((state.authority_review_summary_markdown or "")[:600])
    print("=" * 78)
    print("\nAsset bundle (clinic-facing bodies, post-scrub):\n")
    for asset in bundle:
        body = asset["body"] if isinstance(asset["body"], str) else json.dumps(asset["body"])
        print(f"  - {asset['label']}: {body[:140]}")
    print("=" * 78)

    return 0 if all(ok for _, ok, _ in checks) else 1


def _fake_findings() -> list[dict]:
    """Stand in for the existing v3.0 Authority Review output."""
    @dataclass
    class P:
        name: str
        ecosystem: str = "deepseek"

    @dataclass
    class T:
        persona: P
        content: str
        recommended_fix: str
        risk_level: str
        score: float
        reviewer_role: str
        concern_type: str

    raw = [
        T(P("Reviewer-1", "deepseek"),
          "Body asserts a guaranteed outcome.",
          "Replace with provider-reviewed phrasing.",
          "high", 0.92, "Compliance Reviewer", "claim-risk review"),
        T(P("Reviewer-2", "qwen"),
          "Tone reads marketing-first.",
          "Re-anchor on provider voice and consult invitation.",
          "medium", 0.78, "Patient Trust Reviewer", "patient-experience trust"),
        T(P("Reviewer-3", "kimi"),
          "CTA not treatment-specific.",
          "Use 'Book a Morpheus8 consult' above the fold.",
          "low", 0.71, "Conversion Strategist", "booking-friction reduction"),
        T(P("Reviewer-4", "grok"),
          "Treatment + market not in first sentence.",
          "Open with treatment + neighborhood reference.",
          "medium", 0.69, "AI Visibility Reviewer", "treatment-level visibility"),
    ]
    return [t for t in raw]


if __name__ == "__main__":
    raise SystemExit(main())
