"""Byte-identical replay regression test.

The unit-test equivalent of governance Test 3.

Background: in v3.7 we caught a regression where the engine's
`POST /api/brief/sign` original-success path returned a JSONResponse
serialised in pydantic field-declaration order, while the replay path
returned a JSONResponse serialised in sorted-key order (because the
idempotency store had round-tripped the body through
`canonical_dumps`). The two responses were DICT-equal but not
BYTE-equal — which silently broke the "byte-identical replay"
guarantee LabBrief's diff-on-wire integrity checks depend on.

Fix in `directora/api/routes/brief.py`: both paths now return
`Response(content=canonical_dumps(payload), media_type="application/json")`,
so the bytes are produced by the same canonicalising function in both
cases. This regression test asserts the property at the unit-test
layer so a refactor that re-introduces the bug fails here in ~50 ms
without needing to spin up uvicorn + the governance script.
"""
from __future__ import annotations

import uuid

import pytest

from tests.api.conftest import CLINIC_ID, PROVIDER_ID


def _hdrs(token: str, idem: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-Clinic-ID": CLINIC_ID,
        "Idempotency-Key": idem,
        "Content-Type": "application/json",
    }


def _body(value: str = "Dr Byte Identical") -> dict:
    return {
        "brief_id": "BRF_TEST_01",
        "provider_id": PROVIDER_ID,
        "signature": {
            "method": "typed",
            "value": value,
            "signed_at": "2026-05-16T17:01:33Z",
        },
        "client": {
            "app": "pytest", "version": "1.0", "session_id": "test",
        },
    }


def test_sign_and_replay_are_byte_identical(
    client, provider_token, stored_brief,
):
    """Sign once, replay once, assert raw response bytes are equal.

    A regression that re-introduces dict-order serialisation will fail
    here even though `.json() == .json()` would still pass.
    """
    idem = f"sign-BRF_TEST_01-{uuid.uuid4()}"

    # Sign — capture raw bytes.
    sign_resp = client.post(
        "/api/brief/sign", headers=_hdrs(provider_token, idem), json=_body(),
    )
    assert sign_resp.status_code == 200, sign_resp.text
    sign_bytes = sign_resp.content

    # Replay — capture raw bytes.
    replay_resp = client.post(
        "/api/brief/sign", headers=_hdrs(provider_token, idem), json=_body(),
    )
    assert replay_resp.status_code == 200, replay_resp.text
    replay_bytes = replay_resp.content

    # Byte-identical assertion. This is the property; the .json() check
    # below is a sanity guard for the diagnostic.
    assert sign_bytes == replay_bytes, (
        "Byte-identical replay regression detected.\n"
        f"  sign content-length:    {len(sign_bytes)}\n"
        f"  replay content-length:  {len(replay_bytes)}\n"
        f"  sign body:    {sign_bytes!r}\n"
        f"  replay body:  {replay_bytes!r}\n"
        "Check directora/api/routes/brief.py: both sign-success and "
        "replay paths must return Response(canonical_dumps(payload), "
        "media_type='application/json'). JSONResponse(content=dict) "
        "serialises with the dict's current key order, which differs "
        "between pydantic.model_dump() and the canonicalised stored "
        "response."
    )

    # Sanity: parsed dicts are equal (otherwise .content equality would
    # have already failed, but this gives a clear pytest diff when the
    # regression is subtle).
    assert sign_resp.json() == replay_resp.json()

    # The replay carries the X-Idempotency-Replayed header.
    assert (
        replay_resp.headers.get("X-Idempotency-Replayed") == "true"
    ), "Replay must surface X-Idempotency-Replayed: true"

    # X-Contract-Version travels on both responses (header parity).
    assert (
        sign_resp.headers.get("X-Contract-Version")
        == replay_resp.headers.get("X-Contract-Version")
    ), "Contract-version header must match across original and replay"


def test_replay_third_call_is_also_byte_identical(
    client, provider_token, stored_brief,
):
    """Three calls with the same key all produce the same bytes.

    Guards against an off-by-one canonicalisation path that produces
    different bytes on the third+ replay.
    """
    idem = f"sign-BRF_TEST_01-{uuid.uuid4()}"
    bodies = []
    for i in range(3):
        res = client.post(
            "/api/brief/sign",
            headers=_hdrs(provider_token, idem),
            json=_body(),
        )
        assert res.status_code == 200
        bodies.append(res.content)
    assert bodies[0] == bodies[1] == bodies[2], (
        "Replay drift across multiple calls — third call differs from first."
    )


def test_byte_identical_check_catches_a_deliberate_break(
    client, provider_token, stored_brief, monkeypatch,
):
    """Sanity: if we deliberately broke canonicalisation in one path,
    this test family would catch it.

    We monkey-patch `canonical_dumps` to add a trailing space when the
    replay path calls it. The test must observe the divergence. If
    this test ever stops failing on the simulated break, the
    byte-identical check has lost its teeth.
    """
    from directora.api.routes import brief as brief_module

    original = brief_module.canonical_dumps
    call_count = {"n": 0}

    def drifted(payload):
        call_count["n"] += 1
        out = original(payload)
        # Add a trailing space on the second call (the replay path).
        if call_count["n"] >= 2:
            return out + " "
        return out

    monkeypatch.setattr(brief_module, "canonical_dumps", drifted)

    idem = f"sign-BRF_TEST_01-{uuid.uuid4()}"
    sign_resp = client.post(
        "/api/brief/sign", headers=_hdrs(provider_token, idem), json=_body(),
    )
    replay_resp = client.post(
        "/api/brief/sign", headers=_hdrs(provider_token, idem), json=_body(),
    )

    # If the byte-identical check were toothless, sign.content ==
    # replay.content would still pass. We deliberately broke it; the
    # bytes MUST differ now. If they don't, the check has regressed.
    assert sign_resp.content != replay_resp.content, (
        "Deliberate canonicalisation drift was not detected. The "
        "byte-identical replay check has lost its teeth — see "
        "test_byte_identical_check_catches_a_deliberate_break."
    )
