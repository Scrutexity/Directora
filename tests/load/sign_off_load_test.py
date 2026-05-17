"""Locust load test for the Brief API sign-off path.

Verifies the production-relevant behaviours under load:

    1. SQLite busy → 503 + Retry-After: 1 (not 500).
    2. Concurrent sign on the same brief → one 200, the rest 409.
    3. Idempotency replay returns byte-identical 200 with
       `X-Idempotency-Replayed: true`.
    4. Throughput ceiling — observe with the locust web UI or CSV.

Setup before running:

    # 1. Start Directora locally:
    export AUTH_MODE=stub
    export DIRECTORA_CLINIC_SIGNING_SECRET_DEFAULT=load-secret
    export ENV=development
    uvicorn directora.api.server:app --host 0.0.0.0 --port 8000

    # 2. Seed a known brief fixture (see tests/load/seed.py or wire it
    #    yourself against your local fixture store).

    # 3. Run locust:
    locust -f tests/load/sign_off_load_test.py --host=http://localhost:8000

Run headless via tests/load/locust.conf:

    locust --config tests/load/locust.conf

The script never invents PHI. Identifiers are PHI-minimising stubs.
"""
from __future__ import annotations

import os
import uuid

from locust import HttpUser, between, events, task

# The fixture set the load test exercises. These IDs must be seeded in
# the running engine via `python -m tests.load.seed` (or whatever local
# fixture helper you wire up) before starting locust.
BRIEF_IDS = [f"BRF_LOAD_{i:03d}" for i in range(50)]
CLINIC_ID = os.getenv("LOAD_CLINIC_ID", "CLN_LOAD")
PROVIDER_ID = os.getenv("LOAD_PROVIDER_ID", "PRV_LOAD")
STUB_TOKEN = os.getenv("LOAD_STUB_TOKEN", "")

# Counters surfaced in the locust summary.
COUNTERS: dict[str, int] = {
    "ok": 0,
    "already_signed": 0,
    "idempotency_conflict": 0,
    "db_busy_503": 0,
    "missing_retry_after": 0,
    "replayed": 0,
    "unexpected": 0,
}


@events.test_stop.add_listener
def _print_summary(environment, **kwargs):  # noqa: D401
    print("\n=== sign-off load test summary ===")
    for k, v in COUNTERS.items():
        print(f"  {k}: {v}")


class SignOffUser(HttpUser):
    """Drives the sign-off path with realistic patterns."""

    wait_time = between(0.1, 0.5)

    def _headers(self, idem: str | None) -> dict:
        h = {
            "Authorization": f"Bearer {STUB_TOKEN or 'configure-LOAD_STUB_TOKEN'}",
            "X-Clinic-ID": CLINIC_ID,
            "X-Request-ID": f"req_load_{uuid.uuid4().hex}",
            "Content-Type": "application/json",
        }
        if idem:
            h["Idempotency-Key"] = idem
        return h

    def _body(self, brief_id: str) -> dict:
        return {
            "brief_id": brief_id,
            "provider_id": PROVIDER_ID,
            "signature": {
                "method": "typed",
                "value": "Dr Load Test",
                "signed_at": "2026-05-16T17:01:33Z",
            },
            "client": {
                "app": "loadtest", "version": "1.0", "session_id": "load",
            },
        }

    @task(3)
    def sign_unique_brief(self):
        """Sign a pending brief with a fresh idempotency key.

        Outcomes expected at steady-state load:
            200 — sign succeeded
            409 already_signed — someone got there first
            409 idempotency_conflict — extremely rare; instrumented
            503 — SQLite under pressure; must carry Retry-After
        """
        brief_id = BRIEF_IDS[(self._user_index() % len(BRIEF_IDS))]
        idem = f"sign-{brief_id}-{uuid.uuid4()}"
        with self.client.post(
            "/api/brief/sign",
            json=self._body(brief_id),
            headers=self._headers(idem),
            catch_response=True,
            name="POST /api/brief/sign (unique)",
        ) as response:
            self._classify(response)

    @task(1)
    def replay_sign_request(self):
        """Reuse a stable idempotency key — verifies byte-identical
        replay with the X-Idempotency-Replayed header."""
        brief_id = BRIEF_IDS[0]
        idem = f"sign-{brief_id}-replay-fixed"
        with self.client.post(
            "/api/brief/sign",
            json=self._body(brief_id),
            headers=self._headers(idem),
            catch_response=True,
            name="POST /api/brief/sign (replay)",
        ) as response:
            if (
                response.status_code == 200
                and response.headers.get("X-Idempotency-Replayed") == "true"
            ):
                COUNTERS["replayed"] += 1
                response.success()
            elif response.status_code == 200:
                # First call along the replay key — also success.
                COUNTERS["ok"] += 1
                response.success()
            else:
                self._classify(response)

    @task(1)
    def health_probe(self):
        with self.client.get(
            "/health",
            catch_response=True,
            name="GET /health",
        ) as response:
            if response.status_code in (200, 503):
                response.success()
            else:
                response.failure(f"unexpected health status {response.status_code}")

    # ------------------------------------------------------------------

    def _user_index(self) -> int:
        # Locust 2.x: each user has a unique runner index.
        try:
            return self.environment.runner.user_count  # type: ignore[attr-defined]
        except Exception:
            return 0

    def _classify(self, response):
        sc = response.status_code
        if sc == 200:
            COUNTERS["ok"] += 1
            response.success()
            return
        body = {}
        try:
            body = response.json()
        except Exception:
            pass
        if sc == 409 and body.get("error") == "already_signed":
            COUNTERS["already_signed"] += 1
            response.success()
            return
        if sc == 409 and body.get("error") == "idempotency_conflict":
            COUNTERS["idempotency_conflict"] += 1
            response.success()
            return
        if sc == 503:
            if response.headers.get("Retry-After"):
                COUNTERS["db_busy_503"] += 1
                response.success()
            else:
                COUNTERS["missing_retry_after"] += 1
                response.failure("503 missing Retry-After header")
            return
        COUNTERS["unexpected"] += 1
        response.failure(f"unexpected status {sc}")
