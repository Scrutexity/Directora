# Directora Architecture

Directora is a governed commit system for clinical-adjacent sign-off workflows.

## Core Flow

1. LabBrief UI sends a sign-off request.
2. Directora validates the request signature.
3. The idempotency engine checks for prior identical commits.
4. The ledger append becomes the commit point.
5. A binding hash ties the event to the signed contract state.
6. The TypeScript kit receives a stable response and handles retry/drift behavior.

## Design Priorities

- Atomicity
- Idempotency
- Contract integrity
- Immutable event references
- PHI-minimizing storage
- Fail-closed governance
- Client/server zero-drift enforcement

## Diagram Source

See `docs/directora-architecture.mmd`.
