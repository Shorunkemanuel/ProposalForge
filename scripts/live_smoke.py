"""Live provider smoke test (NOT part of the automated suite).

This script performs a real inference call against the configured
Ollama-compatible endpoint. Run it only when the endpoint and any
authentication are verified and available. A mocked test result is not a
substitute for this.

    export PROPOSALFORGE_MODEL=<verified-model>
    python scripts/live_smoke.py

Exit codes:
    0  live generation succeeded and the draft validated
    1  live generation failed (provider, timeout, or invalid output)
    2  configuration missing
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.proposal import InvalidModelOutput, build_proposal  # noqa: E402
from app.providers import ProviderError, ProviderConfig, get_provider  # noqa: E402
from app.validation import ValidationError  # noqa: E402

PAYLOAD = {
    "client_name": "Live Smoke Test",
    "brief": "A local smoke test of the proposal drafting pipeline.",
    "scope": "Generate a short proposal draft from supplied facts only.",
    "timeline": "Two weeks.",
    "hourly_rate": "50.00",
    "estimated_hours": "4",
    "expenses": "0",
    "currency": "USD",
}


def main() -> int:
    config = ProviderConfig.from_env()
    if not config.model:
        print("FAIL: PROPOSALFORGE_MODEL is not set.", file=sys.stderr)
        return 2

    print(f"Provider: {config.provider}")
    print(f"Endpoint: {config.base_url}")
    print(f"Model:    {config.model}")
    print(f"Timeout:  {config.timeout}s")

    try:
        provider = get_provider(config)
        result = build_proposal(PAYLOAD, provider)
    except ValidationError as exc:
        print(f"FAIL: input validation error: {exc.errors}", file=sys.stderr)
        return 1
    except InvalidModelOutput as exc:
        print(f"FAIL: invalid model output: {exc}", file=sys.stderr)
        return 1
    except ProviderError as exc:
        print(f"FAIL: provider error: {exc}", file=sys.stderr)
        return 1

    print("PASS: live generation succeeded.")
    print("Authoritative pricing:", json.dumps(result["pricing"]))
    print("Draft fields:", ", ".join(sorted(result["draft"].keys())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
