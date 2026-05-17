# `directora/state.py` integration

Add the following optional fields to `DirectorState`. All default to
`None` (or an empty container) so legacy callers that don't set them
keep working.

```python
# Scrutexity inputs / outputs
receipt_input: dict | None = None
clinic_context: dict | None = None
authority_brief: dict | None = None
authority_brief_validation: dict | None = None
directora_input: dict | None = None
authority_review_summary: list[dict] | None = None
authority_review_summary_markdown: str | None = None
provider_brief: dict | None = None
owner_brief: dict | None = None
mode: Literal["scrutexity", "generic", "error"] | None = None

# Pass-through Scrutexity context that ledger + export modules read
clinic_name: str | None = None
treatment: str | None = None
market: str | None = None
primary_visibility_gap: str | None = None
competitors_surfacing_more_often: list[str] = []
first_fix_id_prioritize: str | None = None
claim_risk_notes: list[str] = []
approval_status: str | None = None

# Existing v3.1 fields (unchanged)
transcript_visible: list[dict] | None = None
transcript_markdown: str | None = None
telemetry: dict | None = field(default_factory=lambda: {"events": []})
render: dict | None = None
```

If `DirectorState` is a `TypedDict` rather than a Pydantic model, mark
every new key as `NotRequired[...]`.
