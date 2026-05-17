"""Quality Render Step tests (refactored Seedance render node)."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from directora.nodes import render_seedance
from directora.telemetry import outcome


class _Shot:
    def __init__(self, prompt="wide", duration_s=2.0):
        self.visual_prompt = prompt
        self.duration_s = duration_s
        self.camera = "static"
        self.subject_ref = None


class _State:
    def __init__(self, tier="quality"):
        self.tier = tier
        self.run_id = "run-test"
        self.prompt = "neon city at dusk"
        self.shot_plan = [_Shot(), _Shot("close-up")]
        self.use_seedance = True
        self.clinic_name = "Example Aesthetics NYC"
        self.treatment = "Morpheus8"
        self.market = "Upper East Side, NYC"
        self.approval_status = "human approval required"
        self.telemetry = {"events": []}


def test_skips_quality_on_fast_tier(memory_ledger, monkeypatch):
    state = _State(tier="fast")
    delta = render_seedance.render(state)
    assert delta["render"]["engine"] == "happyhorse"
    assert delta["render"]["label"] == "Fallback Render Draft"


def test_quality_render_uses_label_on_success(memory_ledger, monkeypatch):
    state = _State(tier="quality")
    fake = MagicMock()
    fake.call.return_value = {
        "video_url": "https://higgsfield.example/v.mp4",
        "frames": ["f1", "f2"],
        "duration_s": 4.0,
    }
    monkeypatch.setattr(render_seedance, "MCPClient", lambda: fake)
    delta = render_seedance.render(state)
    assert delta["render"]["engine"] == "seedance"
    assert delta["render"]["label"] == "Quality Render Step"
    assert delta["render"]["video_url"].endswith("v.mp4")


def test_seedance_failure_records_fallback(memory_ledger, monkeypatch):
    state = _State(tier="quality")
    fake = MagicMock()
    fake.call.side_effect = render_seedance.MCPError("boom")
    monkeypatch.setattr(render_seedance, "MCPClient", lambda: fake)
    delta = render_seedance.render(state)
    # Output is fallback, not skipped/missing — pipeline continues.
    assert delta["render"]["engine"] == "happyhorse"
    assert delta["render"]["label"] == "Fallback Render Draft"
    # Ledger captured the fallback.
    kinds = [e.kind for e in memory_ledger.read_all()]
    assert "render_fallback" in kinds


def test_force_seedance_overrides_tier(memory_ledger, monkeypatch):
    monkeypatch.setenv("FORCE_SEEDANCE", "1")
    state = _State(tier="fast")
    fake = MagicMock()
    fake.call.return_value = {"video_url": "u", "frames": []}
    monkeypatch.setattr(render_seedance, "MCPClient", lambda: fake)
    delta = render_seedance.render(state)
    assert delta["render"]["engine"] == "seedance"
    assert delta["render"]["label"] == "Quality Render Step"


def test_render_failure_does_not_block_pipeline(memory_ledger, monkeypatch):
    """A render failure must always return a usable state delta."""
    state = _State(tier="quality")
    fake = MagicMock()
    fake.call.side_effect = RuntimeError("network exploded")
    monkeypatch.setattr(render_seedance, "MCPClient", lambda: fake)
    delta = render_seedance.render(state)
    assert "render" in delta
    # Pipeline-relevant downstream fields are NOT mutated by render here.
    # The Authority Brief / Owner Brief paths are independent.


def test_render_label_uses_clinic_facing_language():
    """Sanity: the constants exposed by the module are the clinic-facing ones."""
    assert render_seedance.QUALITY_RENDER_LABEL == "Quality Render Step"
    assert render_seedance.FALLBACK_RENDER_LABEL == "Fallback Render Draft"
