"""Shared fixtures for the Brief API test suite."""
from __future__ import annotations

import os
from typing import Iterator

import pytest
from fastapi.testclient import TestClient

from directora.api.auth import encode_stub_token
from directora.api import idempotency as idem_module
from directora.api.server import create_app
from directora.scrutexity import brief_store as brief_store_module
from directora.scrutexity.brief_store import (
    BriefRecord,
    BriefStatus,
    InMemoryBriefStore,
)
from directora.telemetry import outcome as ledger_module


CLINIC_ID = "CLN_TEST"
OTHER_CLINIC_ID = "CLN_OTHER"
PROVIDER_ID = "PRV_TEST"
OTHER_PROVIDER_ID = "PRV_OTHER"


@pytest.fixture(autouse=True)
def _signing_secret(monkeypatch):
    monkeypatch.setenv("DIRECTORA_CLINIC_SIGNING_SECRET_DEFAULT", "test-secret")


@pytest.fixture(autouse=True)
def fresh_stores():
    """Reset brief, idempotency, and ledger stores before each test."""
    brief_store_module.reset_store_for_tests(InMemoryBriefStore())
    idem_module.reset_store_for_tests(idem_module.InMemoryIdempotencyStore())
    ledger_module.reset_sink_for_tests(ledger_module.MemorySink())
    yield
    brief_store_module.reset_store_for_tests(None)
    idem_module.reset_store_for_tests(None)
    ledger_module.reset_sink_for_tests(None)


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app()
    with TestClient(app) as c:
        yield c


@pytest.fixture
def provider_token() -> str:
    return encode_stub_token(PROVIDER_ID, CLINIC_ID, roles=("provider",))


@pytest.fixture
def director_token() -> str:
    return encode_stub_token(
        OTHER_PROVIDER_ID, CLINIC_ID, roles=("provider", "medical_director")
    )


@pytest.fixture
def other_clinic_token() -> str:
    return encode_stub_token(OTHER_PROVIDER_ID, OTHER_CLINIC_ID)


def _seeded_brief(
    brief_id: str = "BRF_TEST_01",
    *,
    clinic_id: str = CLINIC_ID,
    provider_id: str = PROVIDER_ID,
    status: str = BriefStatus.PENDING_REVIEW,
) -> BriefRecord:
    """Create a brief record with a small canonical provider brief JSON
    payload so the sign-off path has something to hash."""
    from directora.scrutexity.canonical_json import canonical_dumps
    from directora.api.hashing import hash_brief_dict

    snippet = {
        "asset_type": "provider_brief_snippet",
        "label": "Provider Brief",
        "headline": (
            f"Provider Brief: claim-risk review for Morpheus8 at "
            f"Example Aesthetics NYC"
        ),
        "provider_facing_summary": (
            "Provider review required before publication."
        ),
        "claim_risk_review_checklist": [
            "Does the asset avoid guaranteed-outcome claims?",
            "Does the asset preserve PHI-minimizing workflows?",
        ],
        "suggested_safe_language": [
            "Always recommend provider review before publishing.",
        ],
        "selected_recommendation": {
            "reviewer_role": "Compliance Reviewer",
            "risk_level": "high",
            "finding": "Body asserts a supported (with provider review) outcome.",
            "recommended_fix": "Replace with provider-reviewed phrasing.",
            "selected_recommendation": True,
        },
        "approval_required": True,
        "human_approval_status": "human approval required",
        "ledger_counts": {
            "assets_drafted": 0,
            "claim_risk_flagged": 1,
            "human_approval_required": 1,
            "render_fallback": 0,
        },
        "next_actions": [
            "Walk the claim-risk review checklist for each drafted asset."
        ],
        "clinic_name": "Example Aesthetics NYC",
        "treatment": "Morpheus8",
        "market": "Upper East Side, NYC",
        "Primary Visibility Gap": "Did not surface in this prompt set",
        "First Fix I'd Prioritize": "Provider-led Morpheus8 content.",
        "claim_risk_notes": ["Avoid guaranteed results"],
        "disclaimer": (
            "Not a clinical, legal, or regulatory assessment. "
            "Based on sampled prompt testing."
        ),
    }
    record = BriefRecord(
        brief_id=brief_id,
        clinic_id=clinic_id,
        provider_id=provider_id,
        treatment="Morpheus8",
        market="Upper East Side, NYC",
        status=status,
        patient_ref="P_REF_001",
        encounter_ref="E_REF_001",
        engine_run_id="run-test",
        authority_brief_version="1",
        provider_brief_version="1",
        provider_brief_canonical_json=canonical_dumps(snippet),
        brief_content_hash=hash_brief_dict(snippet),
        lab_summary_flags={
            "critical_count": 0, "abnormal_count": 1, "claim_risk_flagged": 1,
        },
        results=[{"name": "vitamin_D", "value": "low", "flag": "abnormal"}],
        claim_risk_items=["Avoid guaranteed results"],
    )
    return record


@pytest.fixture
def seeded_brief():
    return _seeded_brief()


@pytest.fixture
def stored_brief(seeded_brief):
    brief_store_module.get_brief_store().put(seeded_brief)
    return seeded_brief
