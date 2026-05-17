"""
Governed Workflow Ledger (formerly: outcome telemetry).

Append-only, non-blocking. Records every meaningful pipeline event so
the Weekly Owner Brief, the claim-risk review surface, and the human
approval workflow all read from the same ground truth.

The module path remains `directora.telemetry.outcome` for backwards
compatibility with v3.0 graph wiring. The conceptual identity in any
clinic-facing surface is "Governed Workflow Ledger".

Public API:
    OutcomeEvent              dataclass — one ledger entry
    record_outcome(state, *, kind=..., **extra)
                              best-effort write — never raises
    summarise(run_id=None)    rollup with risk + approval + render counts
    finalize_node(state)      LangGraph node — writes summary onto state
    reset_sink_for_tests()    test hook
    EVENT_KINDS               canonical tuple of supported event kinds
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional, Protocol

log = logging.getLogger(__name__)

# Canonical event kinds. Other strings are accepted but flagged as
# "unknown_kind" in summaries so noise in the ledger is visible.
EVENT_KINDS: tuple[str, ...] = (
    "authority_brief_created",
    "receipt_invalid",
    "asset_drafted",
    "authority_review_completed",
    "claim_risk_flagged",
    "human_approval_required",
    "human_approved",
    "render_ok",
    "render_fallback",
    "owner_brief_ready",
    "provider_brief_ready",
    "provider_brief_signed",            # v3.4 sign-off API
    "provider_brief_finalize_failed",   # v3.7 neutral finalize-failure note
    "export_completed",
)


# Reserved Treatment Plan signing event kinds — defined but never
# emitted. Phase 3 reserves the namespace so v4 can land routes without
# bumping the event-kind contract.
RESERVED_EVENT_KINDS: tuple[str, ...] = (
    "treatment_plan_ready",
    "treatment_plan_signed",
    "treatment_plan_amended",
    "treatment_plan_voided",
)


@dataclass
class OutcomeEvent:
    ts: float
    run_id: str
    kind: str
    event_id: str = field(default_factory=lambda: f"evt_{uuid.uuid4().hex}")
    clinic_name: Optional[str] = None
    treatment: Optional[str] = None
    market: Optional[str] = None
    tier: Optional[str] = None
    engine: Optional[str] = None
    latency_s: Optional[float] = None
    reason: Optional[str] = None
    approval_status: Optional[str] = None
    risk_level: Optional[str] = None
    # v3.4 sign-off fields (optional, only populated on sign-off events).
    clinic_id: Optional[str] = None
    provider_id: Optional[str] = None
    brief_id: Optional[str] = None
    extra: dict = field(default_factory=dict)


class TelemetrySink(Protocol):
    def write(self, event: OutcomeEvent) -> None: ...
    def flush(self) -> None: ...
    def read_all(self) -> list[OutcomeEvent]: ...


class JsonlSink:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def write(self, event: OutcomeEvent) -> None:
        line = json.dumps(asdict(event), separators=(",", ":"))
        with self._lock, self.path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    def flush(self) -> None:
        pass

    def read_all(self) -> list[OutcomeEvent]:
        if not self.path.exists():
            return []
        out: list[OutcomeEvent] = []
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                out.append(OutcomeEvent(**json.loads(line)))
        return out


class MemorySink:
    def __init__(self) -> None:
        self.events: list[OutcomeEvent] = []
        self._lock = threading.Lock()

    def write(self, event: OutcomeEvent) -> None:
        with self._lock:
            self.events.append(event)

    def flush(self) -> None:
        pass

    def read_all(self) -> list[OutcomeEvent]:
        with self._lock:
            return list(self.events)


class NoopSink:
    def write(self, event: OutcomeEvent) -> None: pass
    def flush(self) -> None: pass
    def read_all(self) -> list[OutcomeEvent]: return []


_sink: TelemetrySink | None = None
_sink_lock = threading.Lock()


def _build_sink() -> TelemetrySink:
    name = os.getenv("DIRECTORA_TELEMETRY_SINK", "jsonl").lower()
    if name == "memory":
        return MemorySink()
    if name == "noop":
        return NoopSink()
    path = Path(
        os.getenv("DIRECTORA_TELEMETRY_PATH", "./.directora/ledger.jsonl")
    )
    return JsonlSink(path)


def get_sink() -> TelemetrySink:
    global _sink
    if _sink is None:
        with _sink_lock:
            if _sink is None:
                _sink = _build_sink()
    return _sink


def reset_sink_for_tests(sink: TelemetrySink | None = None) -> None:
    """Test hook only — never call from production code."""
    global _sink
    with _sink_lock:
        _sink = sink


def _safe_getattr(state: Any, name: str, default: Any = None) -> Any:
    try:
        return getattr(state, name, default)
    except Exception:
        return default


def record_outcome(state: Any, *, kind: str, **fields: Any) -> Optional[str]:
    """Best-effort: never raises into the pipeline.

    Pulls clinic_name / treatment / market / tier from state so callers
    don't have to pass them every time. Anything else goes into `extra`.

    Returns the generated `event_id` so callers that need to surface it
    to a client (e.g. the Brief API sign-off path) can do so. Returns
    None if the write was suppressed by an internal failure or by the
    FAULT_LEDGER_APPEND chaos switch.
    """
    # Chaos switch — only active when FAULT_LEDGER_APPEND env var is set.
    try:
        from directora.api.chaos import maybe_fault_ledger_append
        maybe_fault_ledger_append()
    except Exception as exc:
        log.warning("FAULT_LEDGER_APPEND injected ledger failure: %s", exc)
        return None
    try:
        event = OutcomeEvent(
            ts=time.time(),
            run_id=_safe_getattr(state, "run_id", "unknown") or "unknown",
            kind=str(kind),
            clinic_name=fields.pop(
                "clinic_name", _safe_getattr(state, "clinic_name")
            ),
            treatment=fields.pop(
                "treatment", _safe_getattr(state, "treatment")
            ),
            market=fields.pop("market", _safe_getattr(state, "market")),
            tier=fields.pop("tier", _safe_getattr(state, "tier")),
            engine=fields.pop("engine", None),
            latency_s=fields.pop("latency_s", None),
            reason=fields.pop("reason", None),
            approval_status=fields.pop(
                "approval_status",
                _safe_getattr(state, "approval_status"),
            ),
            risk_level=fields.pop("risk_level", None),
            clinic_id=fields.pop("clinic_id", None),
            provider_id=fields.pop("provider_id", None),
            brief_id=fields.pop("brief_id", None),
            extra=fields,
        )
        get_sink().write(event)

        # Surface on state.telemetry["events"] so the Owner Brief can read it
        # without having to re-query the sink.
        bucket = _safe_getattr(state, "telemetry", None)
        if isinstance(bucket, dict):
            bucket.setdefault("events", []).append(asdict(event))
        return event.event_id
    except Exception:
        log.exception("Governed Workflow Ledger record_outcome failed (suppressed)")
        return None


def _iter_events(
    run_id: str | None = None,
) -> list[OutcomeEvent]:
    events = get_sink().read_all()
    if run_id:
        events = [e for e in events if e.run_id == run_id]
    return events


def summarise(run_id: str | None = None) -> dict:
    """Roll-up consumed by the Owner Brief.

    Includes the headline counts the brief surfaces near the top of the
    page: claim risks, approvals required, render fallbacks, and the
    set of treatments touched in this run.
    """
    events = _iter_events(run_id)
    by_kind: dict[str, int] = {}
    total_latency = 0.0
    treatments: set[str] = set()
    claim_risk = 0
    approval_required = 0
    render_fallback = 0
    receipt_invalid = 0

    for e in events:
        key = e.kind if e.kind in EVENT_KINDS else "unknown_kind"
        by_kind[key] = by_kind.get(key, 0) + 1
        if e.latency_s:
            total_latency += e.latency_s
        if e.treatment:
            treatments.add(e.treatment)
        if e.kind == "claim_risk_flagged":
            claim_risk += 1
        if e.kind == "human_approval_required":
            approval_required += 1
        if e.kind == "render_fallback":
            render_fallback += 1
        if e.kind == "receipt_invalid":
            receipt_invalid += 1

    return {
        "event_count": len(events),
        "by_kind": by_kind,
        "total_latency_s": round(total_latency, 3),
        "claim_risk_count": claim_risk,
        "human_approval_required_count": approval_required,
        "render_fallback_count": render_fallback,
        "receipt_invalid_count": receipt_invalid,
        "treatments_processed": sorted(treatments),
    }


def finalize_node(state: Any) -> dict:
    """LangGraph node — attach the rolled-up summary to state."""
    run_id = _safe_getattr(state, "run_id", None)
    return {"telemetry": {"summary": summarise(run_id)}}


def list_events_for_brief(brief_id: str) -> list[dict]:
    """Return every ledger event tagged with the given brief_id.

    Powers the /api/labs/audit endpoint. Read-only; never raises.
    """
    out: list[dict] = []
    try:
        for e in get_sink().read_all():
            if e.brief_id == brief_id or e.extra.get("brief_id") == brief_id:
                out.append(asdict(e))
    except Exception:
        log.exception("list_events_for_brief failed (suppressed)")
    return sorted(out, key=lambda e: e["ts"])


__all__ = [
    "OutcomeEvent",
    "EVENT_KINDS",
    "JsonlSink",
    "MemorySink",
    "NoopSink",
    "record_outcome",
    "summarise",
    "finalize_node",
    "reset_sink_for_tests",
    "get_sink",
]
