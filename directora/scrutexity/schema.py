"""
AI Visibility Receipt schema — protects the Authority Engine from
malformed inputs before any other node runs.

Public API:
    AIVisibilityReceipt         pydantic model (v2)
    CONTENT_OUTPUT_TYPES        canonical Literal of valid asset slugs
    ReceiptValidationError      raised when strict validation fails
    validate_receipt(raw, *, strict=True) -> dict
    json_schema()               -> dict (for export to docs / contract surface)

Design rules:
    - Strict by default. Malformed receipts raise ReceiptValidationError
      with field-level details. No best-effort defaulting in strict mode.
    - Lenient mode is available for migration / debugging only.
    - The receipt may sample multiple treatments via `treatments_tested`,
      but each Authority Brief run targets EXACTLY ONE treatment. The
      validator resolves a single `treatment` focus or raises a
      structured "ambiguous treatment" error.
    - Extra fields are tolerated (passed through under `extra`) so
      upstream Receipt versions can ship additional context without
      breaking the engine.
"""
from __future__ import annotations

from typing import Any, List, Literal, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)


CONTENT_OUTPUT_TYPES = Literal[
    "short_form_script",
    "faq_block",
    "gbp_post",
    "landing_page_section",
    "provider_quote",
    "owner_brief_snippet",
    "provider_brief_snippet",
]


class ReceiptValidationError(ValueError):
    """Raised when strict receipt validation fails.

    Carries the structured pydantic error list so the brief node can
    record it in the Governed Workflow Ledger and surface a clean
    error response.
    """

    def __init__(self, errors: List[dict], *, raw_receipt: Optional[dict] = None):
        self.errors = errors
        self.raw_receipt = raw_receipt
        super().__init__(self._summary())

    def _summary(self) -> str:
        fields = sorted(
            {
                ".".join(str(p) for p in e.get("loc", ())) or "<model>"
                for e in self.errors
            }
        )
        msgs = [e.get("msg", "") for e in self.errors if e.get("msg")]
        head = (
            f"AI Visibility Receipt failed validation "
            f"({len(self.errors)} error(s) on fields: {fields})"
        )
        if msgs:
            head += f"; first: {msgs[0]}"
        return head

    def to_dict(self) -> dict:
        return {
            "errors": self.errors,
            "summary": str(self),
        }


class AIVisibilityReceipt(BaseModel):
    """Canonical AI Visibility Receipt shape consumed by the Authority Engine."""

    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)

    # Required core fields.
    clinic_name: str = Field(min_length=1)
    market: str = Field(min_length=1)
    primary_visibility_gap: str = Field(min_length=1)
    first_fix_id_prioritize: str = Field(min_length=1)

    # Treatment focus — provide explicit `treatment` or a single-item
    # `treatments_tested`. Otherwise the model_validator raises.
    treatment: Optional[str] = None
    treatments_tested: List[str] = Field(default_factory=list)

    # Optional context.
    visibility_gap: Optional[str] = None
    competitors_surfacing_more_often: List[str] = Field(default_factory=list)
    patient_intent: Optional[str] = None
    trust_gap: Optional[str] = None
    booking_friction: Optional[str] = None
    claim_risk_notes: List[str] = Field(default_factory=list)
    content_outputs_needed: List[CONTENT_OUTPUT_TYPES] = Field(default_factory=list)
    tone: Optional[str] = None

    @field_validator(
        "treatments_tested",
        "competitors_surfacing_more_often",
        "claim_risk_notes",
        mode="before",
    )
    @classmethod
    def _coerce_str_to_singleton_list(cls, v: Any) -> Any:
        if isinstance(v, str):
            return [v] if v else []
        return v

    @model_validator(mode="after")
    def _resolve_treatment_focus(self) -> "AIVisibilityReceipt":
        if self.treatment:
            return self
        if not self.treatments_tested:
            raise ValueError(
                "Receipt must specify a focus 'treatment' or a non-empty "
                "'treatments_tested' list."
            )
        if len(self.treatments_tested) == 1:
            # Trivial case — promote the lone tested treatment to the focus.
            self.treatment = self.treatments_tested[0]
            return self
        raise ValueError(
            f"Ambiguous treatment focus: 'treatments_tested' has "
            f"{len(self.treatments_tested)} items "
            f"({self.treatments_tested}) but no 'treatment' field is set. "
            f"Specify exactly one treatment for this Authority Brief run."
        )


def validate_receipt(raw: Optional[dict], *, strict: bool = True) -> dict:
    """Validate a raw receipt dict.

    Returns the validated dict (with `treatment` resolved if it had to be
    inferred). In strict mode, raises ReceiptValidationError on any
    failure. In lenient mode, returns the original raw dict on failure
    (with `_lenient_validation_failed` set so callers can detect it).
    """
    if raw is None:
        if strict:
            raise ReceiptValidationError(
                [{"loc": ("__root__",), "msg": "receipt is None", "type": "value_error"}],
                raw_receipt=None,
            )
        return {}

    try:
        model = AIVisibilityReceipt.model_validate(raw)
    except ValidationError as exc:
        errs = exc.errors()
        if strict:
            raise ReceiptValidationError(errs, raw_receipt=raw) from exc
        return {**raw, "_lenient_validation_failed": errs}

    # Use mode="json" so list[Literal] is serialised as plain strings.
    return model.model_dump(mode="json")


def json_schema() -> dict:
    """Export the receipt JSON Schema for contract surfaces / docs."""
    return AIVisibilityReceipt.model_json_schema()


__all__ = [
    "AIVisibilityReceipt",
    "CONTENT_OUTPUT_TYPES",
    "ReceiptValidationError",
    "validate_receipt",
    "json_schema",
]
