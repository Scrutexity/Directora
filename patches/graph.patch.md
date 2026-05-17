# `directora/graph.py` integration

Apply in order. All edits keep the existing v3.0 node names so the
legacy edges still work; the Scrutexity flow is layered on top.

## 1. Imports

```python
from directora.nodes import render_seedance
from directora.nodes import authority_brief_node
from directora.nodes import owner_brief_node
from directora.nodes import provider_brief_node
from directora.mirror import transcript as authority_review
from directora.telemetry import outcome as governed_ledger
```

## 2. Register the Scrutexity nodes

Add these node registrations alongside the existing v3.0 nodes:

```python
workflow.add_node("authority_brief", authority_brief_node.run)
workflow.add_node("authority_review_summary", authority_review.attach_to_state)
workflow.add_node("quality_render_optional", render_seedance.render)
workflow.add_node("provider_brief", provider_brief_node.run)
workflow.add_node("owner_brief", owner_brief_node.run)
workflow.add_node("telemetry_finalize", governed_ledger.finalize_node)
```

If your existing v3.0 graph already binds a `render` node to
`render_happyhorse.render`, swap that binding to point at
`render_seedance.render` — the new module falls back to HappyHorse
internally when tier is not `quality`, so existing edges keep working:

```python
# BEFORE
workflow.add_node("render", render_happyhorse.render)

# AFTER
workflow.add_node("render", render_seedance.render)
```

## 3. Wire the Scrutexity pipeline

Insert the Scrutexity flow between `receipt_input` (assumed entry node)
and the existing content-generation node (assumed: `"generate_script"`):

```python
workflow.add_edge("receipt_input", "authority_brief")
workflow.add_edge("authority_brief", "generate_script")     # legacy content generation
workflow.add_edge("generate_script", "authority_review")    # existing review node
workflow.add_edge("authority_review", "authority_review_summary")
workflow.add_edge("authority_review_summary", "quality_render_optional")
workflow.add_edge("quality_render_optional", "provider_brief")
workflow.add_edge("provider_brief", "owner_brief")
workflow.add_edge("owner_brief", "telemetry_finalize")
workflow.add_edge("telemetry_finalize", "final")
```

The Provider Brief is generated **before** the Owner Brief so the Owner
Brief can reference the Provider Brief's `human_approval_status` and
`selected_recommendation`. Both sit in the Brief Path; both pull from
the same Authority Brief + Authority Review Summary + Governed Workflow
Ledger; neither generates Authority Assets.

Rename references in your local copy if the node names differ:

| Reference here          | Likely v3.0 name        |
| ----------------------- | ----------------------- |
| `receipt_input`         | new entry; bind to your existing input collector |
| `generate_script`       | your existing script / content generation node |
| `authority_review`      | `decide_winner` or `mirror_review` |
| `final`                 | terminal node |

## 4. Generic-mode fallback

`authority_brief_node.run` already handles missing `receipt_input` by
emitting `mode="generic"` and an empty brief. No conditional edge is
required — the downstream nodes treat a missing brief as a no-op.
