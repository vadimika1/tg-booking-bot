from __future__ import annotations

import json
import os
from datetime import date, timedelta
from urllib.parse import urlencode
from urllib.request import urlopen


API_BASE = os.getenv("API_BASE", "http://127.0.0.1:8000").rstrip("/")


def api_get(path: str, **params: str) -> object:
    query = urlencode(params)
    url = f"{API_BASE}{path}"
    if query:
        url = f"{url}?{query}"
    with urlopen(url) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    health = api_get("/health")
    if not isinstance(health, dict) or health.get("status") != "ok":
        raise SystemExit("Health check failed.")
    print("Health check: OK")

    services = api_get("/api/services")
    if not isinstance(services, list):
        raise SystemExit("/api/services returned invalid response.")
    if not services:
        raise SystemExit("No active services in catalog. Run `make seed-demo`.")
    print(f"Active services: {len(services)}")

    first_service = services[0]
    service_id = first_service.get("id")
    service_name = first_service.get("name", "unknown")
    if not service_id:
        raise SystemExit("First service has no id.")

    found_slots = 0
    found_date: str | None = None
    for offset in range(0, 14):
        target_date = (date.today() + timedelta(days=offset)).isoformat()
        slots = api_get("/api/slots", service_id=service_id, date=target_date)
        if isinstance(slots, list) and slots:
            found_slots = len(slots)
            found_date = target_date
            break

    if not found_date:
        raise SystemExit("No available slots found for next 14 days.")

    print(
        "Slots check: OK "
        f"(service='{service_name}', date={found_date}, slots={found_slots})"
    )
    print("Demo readiness check passed.")


if __name__ == "__main__":
    main()
