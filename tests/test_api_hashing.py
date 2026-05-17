"""Hash chain tests — content, signature normalisation, and HMAC binding."""
from __future__ import annotations

import os
import hashlib
import hmac

import pytest

from directora.api import hashing as h
from directora.scrutexity.canonical_json import canonical_bytes


@pytest.fixture(autouse=True)
def _signing_secret(monkeypatch):
    monkeypatch.setenv("DIRECTORA_CLINIC_SIGNING_SECRET_DEFAULT", "test-secret")


def test_brief_content_hash_deterministic_across_dict_order():
    a = {"b": 1, "a": 2, "c": [3, 2, 1]}
    b = {"c": [3, 2, 1], "a": 2, "b": 1}
    assert h.hash_brief_dict(a) == h.hash_brief_dict(b)


def test_brief_content_hash_changes_on_any_field_change():
    base = {"a": 1, "b": "x"}
    edited = {"a": 1, "b": "y"}
    assert h.hash_brief_dict(base) != h.hash_brief_dict(edited)


def test_signature_normalisation_collapses_whitespace_and_nfkc():
    a = "Dr Jane Doe"
    b = "  Dr   Jane   Doe   "
    c = "Dr\tJane\nDoe"
    assert (
        h.normalise_signature_value(a)
        == h.normalise_signature_value(b)
        == h.normalise_signature_value(c)
    )
    assert h.compute_signature_value_hash(a) == h.compute_signature_value_hash(b)


def test_binding_hash_includes_v1_prefix():
    payload = h.build_binding_payload(
        brief_content_hash="x" * 64,
        signature_value_hash="y" * 64,
        engine_run_id="run-1",
        authority_brief_version="1",
        provider_brief_version="1",
        clinic_id="CLN",
        provider_id="PRV",
        signed_at="2026-05-16T17:01:33.000Z",
    )
    assert payload.startswith("v1:")


def test_binding_hash_changes_with_engine_run_id():
    """A brief regenerated under a different run_id must NOT match the
    binding hash from the prior run — defends against stale-context signing."""
    kw = dict(
        brief_content_hash="a" * 64,
        signature_value_hash="b" * 64,
        authority_brief_version="1",
        provider_brief_version="1",
        clinic_id="CLN",
        provider_id="PRV",
        signed_at="2026-05-16T17:01:33.000Z",
    )
    one = h.compute_binding_hash(engine_run_id="run-1", **kw)
    two = h.compute_binding_hash(engine_run_id="run-2", **kw)
    assert one != two


def test_binding_hash_keyed_by_clinic_secret(monkeypatch):
    kw = dict(
        brief_content_hash="a" * 64,
        signature_value_hash="b" * 64,
        engine_run_id="run-1",
        authority_brief_version="1",
        provider_brief_version="1",
        clinic_id="CLN_A",
        provider_id="PRV",
        signed_at="2026-05-16T17:01:33.000Z",
    )
    one = h.compute_binding_hash(**kw)
    monkeypatch.setenv("DIRECTORA_CLINIC_SIGNING_SECRET_CLN_A", "rotated-secret")
    two = h.compute_binding_hash(**kw)
    assert one != two


def test_request_hash_matches_canonical_bytes_sha256():
    body = {"a": 1, "b": [1, 2]}
    assert h.request_hash(body) == hashlib.sha256(canonical_bytes(body)).hexdigest()
