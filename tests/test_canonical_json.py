"""Deterministic JSON serialisation tests."""
from __future__ import annotations

import math

import pytest

from directora.scrutexity.canonical_json import canonical_bytes, canonical_dumps


def test_dumps_is_byte_identical_across_dict_orderings():
    a = {"b": 1, "a": 2, "c": [3, 2, 1]}
    b = {"c": [3, 2, 1], "a": 2, "b": 1}
    assert canonical_dumps(a) == canonical_dumps(b)


def test_dumps_has_no_whitespace():
    out = canonical_dumps({"a": 1, "b": [2, 3], "c": {"d": 4}})
    assert " " not in out  # separators=(",", ":")


def test_dumps_preserves_utf8_natively():
    out = canonical_dumps({"name": "café"})
    assert "café" in out
    # No \uXXXX escape — ensure_ascii=False
    assert "\\u" not in out


def test_dumps_rejects_nan():
    with pytest.raises(ValueError):
        canonical_dumps({"v": float("nan")})


def test_dumps_rejects_infinity():
    with pytest.raises(ValueError):
        canonical_dumps({"v": math.inf})


def test_bytes_roundtrips_to_utf8():
    out = canonical_bytes({"name": "café", "n": 1})
    assert out.decode("utf-8") == canonical_dumps({"name": "café", "n": 1})


def test_dumps_stable_across_reserialisation():
    obj = {"z": [1, 2, {"y": True, "x": None}], "a": "café"}
    once = canonical_dumps(obj)
    import json
    twice = canonical_dumps(json.loads(once))
    assert once == twice
