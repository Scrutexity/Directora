# LabBrief integration kit (v3.7, with v3.6 compatibility add-on)

Drop-in TypeScript for wiring LabBrief to the Directora Brief API.
Mirrors the shared contract snapshot at
`../shared/brief-api-contract.json`. Nothing in here mutates state
without a server response — every sign action goes through the API and
the UI consumes the response.

**v3.6 / v3.7 features the add-on covers:**

- `X-Contract-Version`, `X-Idempotency-Replayed`, `X-Request-ID`
  header capture (`extractHeaders`).
- **Contract-version gating (fail fast).** `BriefClient` compares every
  response's `X-Contract-Version` against `expectedContractVersion`;
  mismatch or missing header fires `onContractMismatch` AND logs the
  body + headers to `console.warn`. The dev-only
  `<ContractMismatchBanner>` surfaces drift visibly.
- `503 + Retry-After` backpressure handling with a **3-step backoff
  schedule (250ms / 500ms / 1000ms)** and **±15% jitter** so concurrent
  clients don't fall into lockstep retry storms.
- Same-`Idempotency-Key` retry loop (`signBriefWithRetry`).
- Authoritative non-retry on 400/401/403/404/409/422.
- `MaxRetriesExceededError` surfaces the `request_id` of the final
  failed attempt so support tickets carry the correlation id.
- Auth-error → UI copy table (`authGuidanceForError`).
- Dev-only `DiagnosticsPanel` React component.

## What's in the kit

```
labbrief_kit/
  README.md                            this file
  package.notes.md                     npm deps you need to add
  src/
    v3_6_compatibility.ts                       single import surface for v3.6+ features
    types/contract.ts                           TypeScript types mirroring the snapshot
    api/briefClient.ts                          BriefClient (requires idempotencyKey on signBrief)
    api/errorMessages.ts                        error-code → toast copy
    api/headers.ts                              extractHeaders + contract-version mismatch helper
    api/retry.ts                                signBriefWithRetry — the v3.6+ retry policy
    api/authErrors.ts                           authGuidanceForError — 401 / 403 UI guidance
    api/idempotencyStore.ts                     store-owned idempotency keys + lifecycle (REQUIRED)
    api/compatShims.ts                          signWithRetry + handleAuthError compat shims (optional)
    components/DiagnosticsPanel.tsx             dev-only floating panel
    components/useDiagnosticsState.ts           React hook wiring panel state
    components/ContractMismatchBanner.tsx       dev-only contract-drift banner
    components/useContractMismatchState.ts      React hook for the banner
    schemas/contract.ts                Zod schemas mirroring the snapshot
    schemas/contract.test.ts           Zod ↔ snapshot parity test
    __tests__/briefClient.test.ts      integration test scaffolds (mock fetch)
    __tests__/headers.test.ts              header capture + parseRetryAfter tests
    __tests__/retry.test.ts                full retry-policy test matrix
    __tests__/contractGating.test.ts       BriefClient contract-mismatch test matrix
    __tests__/idempotencyKeyStore.test.ts  store-owned key generation + clear conditions
    __tests__/compatShims.test.ts          signWithRetry + handleAuthError compat shims
    __tests__/msw-handlers.ts          MSW handler stubs satisfying the snapshot
```

## How to use it

1. Copy `src/api/briefClient.ts`, `src/api/errorMessages.ts`, and
   `src/schemas/contract.ts` into your LabBrief `src/` tree. Adjust the
   import paths to match your codebase layout.
2. Copy `../shared/brief-api-contract.json` into your LabBrief repo at
   `shared/brief-api-contract.json` (or symlink). Treat it as
   read-only — regenerate from Directora when the contract changes.
3. Add the env var:
   ```
   # labbrief/.env.local
   VITE_BRIEF_API_BASE=http://localhost:8000
   ```
4. Replace your existing MSW handlers with the stubs in
   `src/__tests__/msw-handlers.ts` (or merge fields into yours so they
   satisfy the snapshot). Keep MSW for tests.
5. Replace the Zustand sign-off mutation with a call to
   `briefClient.signBrief(briefId, providerId, signature)`. **Generate
   the idempotency key per attempt** as `sign-{briefId}-{crypto.randomUUID()}`.
6. Surface `request_id` from the `BriefApiError` in your dev-only
   "Error Details" panel.
7. Run `src/schemas/contract.test.ts` to confirm the Zod schemas match
   the snapshot exactly.

## Required npm deps

```bash
npm i zod ajv ajv-formats
npm i -D msw vitest
```

`ajv` is used in the contract parity test to validate the snapshot
JSON Schemas against Zod-derived JSON shape. `zod` powers runtime
parsing of API responses. `msw` for mocking.

## v3.6 / v3.7 compatibility — required changes in LabBrief

Directora v3.6 introduced four headers and one new HTTP status that
LabBrief must consume correctly. v3.7 adds versioning + a metrics
endpoint but does NOT change the headers or the sign-off contract.

**Headers to capture from every response:**

| Header                       | Meaning                                                                              |
| ---------------------------- | ------------------------------------------------------------------------------------ |
| `X-Contract-Version`         | Snapshot version the engine produced this response from. Warn on mismatch.           |
| `X-Idempotency-Replayed`     | `true` when this 200 is a replay of an earlier sign with the same `Idempotency-Key`. |
| `X-Request-ID`               | Opaque correlation id. Echoed on every response (success or error).                  |
| `Retry-After`                | Number of seconds to wait before retrying. Only on `503 idempotency_store_busy`.     |

**Behaviours to handle:**

| Status | Action                                                                                       |
| ------ | -------------------------------------------------------------------------------------------- |
| `503 idempotency_store_busy` | **Retry** with the same `Idempotency-Key`. Honour `Retry-After`. Up to 3 attempts. |
| `429`                       | Retry, same key, honour `Retry-After`.                                                       |
| network timeout              | Retry, same key, exponential backoff (250 ms / 1 s / 4 s).                                  |
| `409 already_signed`         | **Do NOT retry.** Show the audit trail. Body carries `ledger_event_id`.                      |
| `409 idempotency_conflict`   | **Do NOT retry.** Same key, different body → client bug. Refresh + retry as a new attempt.   |
| `422 invalid_signature`      | Do NOT retry. Re-open the signing UI.                                                        |
| `401 token_expired`          | Do NOT retry. Re-authenticate. (See `authGuidanceForError`.)                                 |
| `401 invalid_token`          | Do NOT retry. Sign out + re-authenticate.                                                    |

### Required LabBrief changes (the checklist)

1. **Capture all three headers** from every response via `extractHeaders`.
2. **Implement the retry policy**: retry on 503/429/timeouts only.
   Reuse the same `Idempotency-Key` across retries.
3. **Never retry on 409 / 422 / 4xx-auth.** Show the error.
4. **401 → re-auth flow.** Use `authGuidanceForError` for the message.
5. **Dev-only diagnostics panel.** Mount `<DiagnosticsPanel>` behind
   `import.meta.env.DEV && import.meta.env.VITE_SHOW_DIAGNOSTICS === "true"`.
6. **Contract version mismatch banner.** Wire
   `useContractMismatchState()` and pass `state` to
   `<ContractMismatchBanner>` plus `onMismatch` to the BriefClient.
   When `X-Contract-Version` differs from `EXPECTED_CONTRACT_VERSION`,
   a top-of-viewport banner surfaces the drift and the full response
   body + headers (dev-only).

### Backoff schedule (Add-on B)

```ts
BACKOFF_SCHEDULE_MS    = [250, 500, 1000]   // before attempts 2, 3, 4
BACKOFF_JITTER_PCT     = 0.15               // ±15 %
```

Overrideable per call:

```ts
signBriefWithRetry(client, {
  …,
  backoffScheduleMs: [200, 600, 1500],
  jitterPct: 0.1,
});
```

The retry helper honours `Retry-After` first (still applies jitter so
concurrent clients don't all wake at the same millisecond), then falls
back to the schedule entry for the current retry. After the budget is
exhausted, the caller receives either the final `BriefApiError` (with
its `requestId`) or `MaxRetriesExceededError` (also with `requestId`).

### Contract-version gating (Add-on A)

```ts
import { BriefClient, EXPECTED_CONTRACT_VERSION, useContractMismatchState, ContractMismatchBanner } from "labbrief/v3_6_compatibility";

function App() {
  const banner = useContractMismatchState();
  const [client] = React.useState(() => new BriefClient({
    token, clinicId, baseUrl,
    expectedContractVersion: EXPECTED_CONTRACT_VERSION,
    onContractMismatch: banner.onMismatch,
  }));
  return (
    <>
      <ContractMismatchBanner state={banner.state} />
      <Routes />
    </>
  );
}
```

When a response carries a different version (or no header at all),
the client logs the body + headers via `console.warn` and the banner
surfaces a fixed-top warning in dev. The in-flight request still
completes — gating is observability, not enforcement.

### Wiring the v3.7 kit into LabBrief

The store owns the idempotency key, not the briefClient.
`BriefClient.signBrief` throws if you call it without an `idempotencyKey`.

#### Step 1 — install the kit

```bash
cp -r labbrief_kit/src/* labbrief/src/
```

#### Step 2 — wire sign-off in your Zustand store

```ts
// stores/hybridWorkflowStore.ts
import { BriefClient, BriefApiError } from "../api/briefClient";
import { signBriefWithRetry } from "../api/retry";
import { authGuidanceForError } from "../api/authErrors";
import {
  getOrCreateIdempotencyKey,
  clearIdempotencyKey,
  shouldClearKeyForOutcome,
} from "../api/idempotencyStore";

const client = new BriefClient({
  token, clinicId, baseUrl,
  expectedContractVersion: EXPECTED_CONTRACT_VERSION,
  onContractMismatch: bannerActions.onMismatch,
});

async function submitSignOff(
  briefId: string,
  providerId: string,
  signatureValue: string,
) {
  // Store owns the key. SAME key reused across every retry.
  const idempotencyKey = getOrCreateIdempotencyKey(providerId, briefId);

  try {
    const result = await signBriefWithRetry(client, {
      briefId,
      providerId,
      idempotencyKey,                    // required, store-owned
      signature: {
        method: "typed",
        value: signatureValue,
        signed_at: new Date().toISOString(),
      },
      client: { app: "labbrief", version: "2.7.0", session_id: getSessionId() },
      onAttempt: diagnosticsActions.recordRetry,
    });

    if (shouldClearKeyForOutcome({ success: true })) {
      clearIdempotencyKey(providerId, briefId);
    }
    set((state) => ({
      briefs: state.briefs.map((b) =>
        b.brief_id === briefId
          ? { ...b, status: "signed",
              ledger_event_id: result.ledger_event_id,
              signed_at: result.signed_at }
          : b,
      ),
      signOffError: null,
    }));
    return result;
  } catch (err) {
    if (err instanceof BriefApiError) {
      if (
        shouldClearKeyForOutcome({ status: err.status, code: String(err.code) })
      ) {
        clearIdempotencyKey(providerId, briefId);
      }
      const guidance = authGuidanceForError(err);
      if (guidance?.clearSession) clearAuthState();
      set({
        signOffError: {
          code: String(err.code),
          message: guidance?.message ?? `${err.code}`,
          requestId: err.requestId,
        },
      });
      diagnosticsActions.recordError(String(err.code));
    } else if (err instanceof MaxRetriesExceededError) {
      // Budget exhausted on transient failures — no more attempts.
      if (shouldClearKeyForOutcome({ maxRetriesExceeded: true })) {
        clearIdempotencyKey(providerId, briefId);
      }
      set({
        signOffError: {
          code: "max_retries_exceeded",
          message: `Signing failed after ${err.attempts} attempts.`,
          requestId: err.requestId,
        },
      });
      diagnosticsActions.recordError("max_retries_exceeded");
    }
    throw err;
  }
}
```

#### Step 3 — mount the dev-only panels

```tsx
// App.tsx
import {
  DiagnosticsPanel, useDiagnosticsState,
  ContractMismatchBanner, useContractMismatchState,
  EXPECTED_CONTRACT_VERSION,
} from "./v3_6_compatibility";

function App() {
  const diag = useDiagnosticsState();
  const banner = useContractMismatchState();
  return (
    <>
      <ContractMismatchBanner state={banner.state} />
      <YourRoutes />
      <DiagnosticsPanel
        state={diag.state}
        expectedContractVersion={EXPECTED_CONTRACT_VERSION}
      />
    </>
  );
}
```

Pass `banner.onMismatch` into the `BriefClient` constructor's
`onContractMismatch` option, and the `diag.actions.*` callbacks into
your sign-off wrapper.

#### Step 4 — replace any client-side audit log

```ts
async function loadAuditTrail(briefId: string) {
  const audit = await briefClient.getAuditTrail(briefId);
  set({ auditEvents: audit.events });   // server ledger is the source of truth
}
```

#### Step 5 — gate MSW behind a single flag

```ts
// src/mocks/browser.ts
if (import.meta.env.VITE_ENABLE_MSW_IN_DEV === "true") {
  await worker.start();
}
```

One env var, one source of truth. Vitest enables MSW separately via
`vi.beforeAll(() => worker.listen())` inside its setup file — don't
conflate the two paths or you get drift between test and dev MSW
behaviour.

### Idempotency key — clear conditions (locked)

```
| outcome                                     | clear?  |
| ------------------------------------------- | ------- |
| 200 signed                                  | clear   |
| 409 already_signed                          | clear   |
| 409 invalid_status                          | clear   |
| 409 idempotency_conflict                    | clear   |
| 401 token_expired / invalid_token           | clear   |
| 403 permission_denied / clinic_mismatch     | clear   |
| 404 brief_not_found                         | clear   |
| 422 invalid_signature                       | clear   |
| 500 engine_or_ledger_failure                | clear   |
| MaxRetriesExceededError                     | clear   |
| 503 idempotency_store_busy                  | keep    |
| 429                                         | keep    |
| network timeout (no HTTP status)            | keep    |
```

`shouldClearKeyForOutcome({success?, status?, code?})` encodes this
table. Call it from your store on every terminal outcome; never call
`clearIdempotencyKey` directly without it.

Want the key to survive page reloads? Swap the backend:

```ts
import { setIdempotencyKeyBackend } from "./api/idempotencyStore";
setIdempotencyKeyBackend({
  get: (k) => sessionStorage.getItem(`idem:${k}`) ?? undefined,
  set: (k, v) => sessionStorage.setItem(`idem:${k}`, v),
  delete: (k) => sessionStorage.removeItem(`idem:${k}`),
});
```

## What this kit does NOT include

- LabBrief component code (your existing components stay; only the
  data-fetch and sign-off mutation layers change).
- Your Zustand store internals (only the sign-off action changes).
- Authentication beyond the bearer-token stub.

See the parent `README.md` for the full v3.5 contract, curl examples,
and the LabBrief migration note.
