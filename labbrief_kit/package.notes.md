# LabBrief — npm changes required for the v3.5 kit

Add to `labbrief/package.json`:

```json
{
  "dependencies": {
    "zod": "^3.23.0"
  },
  "peerDependencies": {
    "react": ">=18.0.0"
  },
  "devDependencies": {
    "ajv": "^8.13.0",
    "ajv-formats": "^3.0.1",
    "msw": "^2.4.0",
    "vitest": "^1.6.0",
    "@types/react": ">=18.0.0",
    "@testing-library/react": ">=14.0.0"
  }
}
```

`react` is required at runtime only if you import `DiagnosticsPanel`
or `useDiagnosticsState`. The rest of the kit (briefClient, retry,
headers, auth-error helpers, schemas) is framework-free TypeScript.

Then:

```bash
cd labbrief/
npm install
```

## Env file

```dotenv
# labbrief/.env.local
VITE_BRIEF_API_BASE=http://localhost:8000
```

## Integration steps in LabBrief

1. Copy these files into your tree (adjust import paths to match):
   - `src/types/contract.ts`
   - `src/schemas/contract.ts`
   - `src/api/briefClient.ts`
   - `src/api/errorMessages.ts`
2. Copy or symlink `shared/brief-api-contract.json` from Directora.
3. Add the env var above.
4. Wire your existing Zustand store to call `briefClient.signBrief(...)`
   and consume the parsed response — no local state mutation before the
   server returns 200.
5. Surface `error.requestId` in your dev-only Error Details panel.
6. Replace MSW handlers with the stubs in `src/__tests__/msw-handlers.ts`.
7. Add the parity test in `src/schemas/contract.test.ts` to your Vitest
   config — it will fail loudly if the snapshot and Zod drift apart.

## Where the Zustand mutation moves to

Before (mock direct mutation — bad):
```ts
useBriefStore.setState((s) => ({ briefs: s.briefs.map(b => b.id === id ? { ...b, status: "signed" } : b) }));
```

After (server is the source of truth — good):
```ts
const response = await briefClient.signBrief({ briefId, providerId, signature, client });
// Only after the API succeeds do we update local state.
useBriefStore.setState((s) => ({
  briefs: s.briefs.map(b => b.brief_id === briefId ? {
    ...b,
    status: "signed",
    signed_at: response.signed_at,
    ledger_event_id: response.ledger_event_id,
  } : b)
}));
```

## Errors → UI

```ts
import { copyForError } from "./api/errorMessages";

try {
  await briefClient.signBrief(...);
} catch (err) {
  if (err instanceof BriefApiError) {
    const copy = copyForError(err.code);
    showToast({
      title: copy.title,
      body: copy.body,
      action: copy.action,
      // dev-only:
      devDetail: `request_id=${err.requestId} status=${err.status}`,
    });
  } else {
    throw err;
  }
}
```
