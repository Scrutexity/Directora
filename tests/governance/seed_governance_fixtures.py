"""Seed fixtures for `directora-governance-check.sh`.

Inserts brief records directly into the configured BriefStore so the
shell script can sign them. We drive the real `provider_brief_node` so
the persisted canonical JSON + brief_content_hash are produced the same
way as in production — never hand-rolled.

Usage:
    python3 tests/governance/seed_governance_fixtures.py \\
        --clinic CLN_GOV --provider PRV_GOV \\
        --brief BRF_GOV_01 --brief BRF_GOV_02

This script is idempotent: re-seeding a brief overwrites the prior
record (the engine treats `put` as upsert in every backend).
"""
from __future__ import annotations

import argparse
import os
import sys


class _FixtureState:
    """Plain attribute bag that satisfies provider_brief_node.run().

    NOT a dataclass — a dataclass nested in a function captures its
    field defaults at class-definition time, which means it cannot
    reference the enclosing function's parameters without a NameError.
    Plain `__init__` assignment sidesteps that whole issue.
    """

    def __init__(self, brief_id: str, clinic_id: str, provider_id: str):
        self.brief_id = brief_id
        self.run_id = f"gov-seed-{brief_id}"
        self.clinic_id = clinic_id
        self.provider_id = provider_id
        self.clinic_name = "Governance Aesthetics NYC"
        self.treatment = "Morpheus8"
        self.market = "Upper East Side, NYC"
        self.authority_brief = {
            "clinic_name": "Governance Aesthetics NYC",
            "market": "Upper East Side, NYC",
            "treatment": "Morpheus8",
            "primary_visibility_gap": (
                "Did not surface in this prompt set "
                "(governance seed fixture)"
            ),
            "first_fix_id_prioritize": (
                "Provider-led Morpheus8 content with safe expectations"
            ),
            "claim_risk_notes": [
                "Avoid guaranteed results",
                "Avoid unqualified before/after promises",
            ],
            "competitors_surfacing_more_often": ["Competitor A"],
            "approval_required": True,
            "content_outputs_needed": ["short_form_script", "faq_block"],
        }
        self.authority_review_summary: list = []
        self.patient_ref = "P_REF_GOV"
        self.encounter_ref = "E_REF_GOV"
        self.authority_brief_version = "1"
        self.provider_brief_version = "1"
        self.results: list = []
        self.lab_summary_flags = {
            "critical_count": 0,
            "abnormal_count": 0,
            "claim_risk_flagged": 0,
        }
        self.telemetry = {"events": []}


def _build_state(brief_id: str, clinic_id: str, provider_id: str) -> _FixtureState:
    return _FixtureState(brief_id, clinic_id, provider_id)


def _seed_one(brief_id: str, clinic_id: str, provider_id: str) -> None:
    # Lazy import — defers env-driven backend selection until after the
    # caller has set BRIEF_STORE_BACKEND / DIRECTORA_BRIEF_DB_PATH /
    # DIRECTORA_CLINIC_SIGNING_SECRET_DEFAULT.
    from directora.nodes import provider_brief_node

    state = _build_state(brief_id, clinic_id, provider_id)
    provider_brief_node.run(state)
    print(
        f"  seeded brief_id={brief_id} "
        f"clinic={clinic_id} provider={provider_id}",
        flush=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clinic", required=True)
    parser.add_argument("--provider", required=True)
    parser.add_argument(
        "--brief",
        action="append",
        required=True,
        help="Brief id to seed. May be passed multiple times.",
    )
    args = parser.parse_args(argv or sys.argv[1:])

    os.environ.setdefault(
        "DIRECTORA_CLINIC_SIGNING_SECRET_DEFAULT",
        "governance-seed-secret",
    )
    # Use the same SQLite DB the running Directora reads from.
    os.environ.setdefault(
        "DIRECTORA_BRIEF_DB_PATH",
        "./.directora/briefs.db",
    )
    os.environ.setdefault("BRIEF_STORE_BACKEND", "sqlite")

    print(f"Seeding {len(args.brief)} brief(s) into "
          f"{os.environ['DIRECTORA_BRIEF_DB_PATH']}:", flush=True)
    for brief_id in args.brief:
        _seed_one(brief_id, args.clinic, args.provider)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
