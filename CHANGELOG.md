# Changelog

## v3.7.1 — Engine patch (byte-identical replay + /health field rename)

**Scope:** engine-only. **CONTRACT_VERSION unchanged at 3.7.0.**
LabBrief and other consumers do not need to update.

### Breaking change for `/health` consumers (ops-only)

`/health` now exposes `contract_version` AND `engine_release` as
DISTINCT fields. The legacy bare `version` field was getting read as
"engine version" by on-call, which is confusing because it actually
held the consumer-facing contract version. Renamed for clarity.

| Before                                  | After                                                              |
| --------------------------------------- | ------------------------------------------------------------------ |
| `{"version": "3.7.0", ...}`             | `{"contract_version": "3.7.0", "engine_release": "3.7.1", ...}`    |

Ops dashboards consuming `/health` must read `contract_version` (or
`engine_release` when they want the patch level). The Brief API
contract is unchanged — `X-Contract-Version` still serves `3.7.0` on
every response.

### Fix

`POST /api/brief/sign` now returns byte-identical bodies on the
success path and every idempotent replay.

**Before:** the success path serialised the response via
`JSONResponse(content=dict)`, which used pydantic's
field-declaration order. The replay path serialised the same dict
*after* it had been round-tripped through `canonical_dumps` (sorted
keys), so FastAPI emitted bytes in a different order. The two responses
were dict-equal but not byte-equal. `.json() == .json()` passed,
`.content == .content` did not.

**After:** both paths route through:

```python
Response(
    content=canonical_dumps(payload),
    media_type="application/json",
)
```

Same canonicalising function applied to both bodies, so the wire bytes
are now genuinely identical.

### Why this matters

LabBrief's HMAC-binding verification chains the response body bytes
into the integrity check. A response body that varies in key order
between original and replay breaks `cmp -s` even though both responses
are semantically correct. The fix anchors the byte stream so the
client can rely on `content == content` as the strongest possible
replay proof.

### Detection

Caught by the v3.7 governance script's Test 3:
```
=== Test 3: byte-identical idempotent replay ===
❌ Replay body differs from the original sign response
   original sign body : /tmp/gov_sign_body.XXXXXX
   replay body 1      : /tmp/gov_replay_1_body.XXXXXX
```

The script's `cmp -s` against the original sign body file (not just
the two replays against each other) was what surfaced the divergence.

### Regression coverage

`tests/api/test_byte_identical_replay.py` (3 cases):

| Case | Locks down |
|---|---|
| `test_sign_and_replay_are_byte_identical` | `.content == .content`, replay header travels, contract-version parity |
| `test_replay_third_call_is_also_byte_identical` | drift on the third+ call |
| `test_byte_identical_check_catches_a_deliberate_break` | the check itself has teeth — a monkey-patched canonicaliser drift fails the assertion |

The mutation test (third case) prevents future refactors that
accidentally weaken the byte-equality check from passing CI under a
false-clean signal.

### Files touched

- `directora/api/routes/brief.py` — sign success + replay paths use
  `Response(canonical_dumps(payload), media_type="application/json")`
  instead of `JSONResponse(content=dict)`.

### CI

Caught at unit-test layer in <50 ms via the new regression test, AND
at E2E layer by `tests/governance/directora-governance-check.sh`
Test 3, AND by the GitHub Actions workflow's meta-runner step. Three
independent gates.

---

## v3.7.0 — Brief API governance v3.7

See `HANDOFF.md` for the full v3.7 surface (metrics, JWKS, contract
versioning, chaos switches, governance scripts).

## v3.6.0

See `HANDOFF.md`.

## v3.5.0

See `HANDOFF.md`.

## v3.4.0

See `HANDOFF.md`.

## v3.3.0

See `README.md` Provider Brief section.

## v3.2.0

See `README.md` v3.2 receipt schema validation.
