"""Load and stress test of the running stack's API, through its own frontend.

    python scripts/system_load_test.py [--out .tmp/system]

Structural system testing in Perry's sense (2007, ch. 8): execution (how fast the API answers
under normal load) and stress (what happens past a limit). Requests go through the frontend
container's nginx, the way a browser reaches the API.

1. **Load.** 1, 5 and then 10 Developers at once, each sending 3 requests a second for 30 seconds
   across the read endpoints the pages poll (queue, runs, chains, services, analytics).
   Three a second is 180 a minute, inside the 300-a-minute API limit, so this measures latency, not
   the limiter.
2. **Stress.** One Developer sends 450 requests as fast as 30 threads allow. The limit is 300 a
   minute, so about 300 should succeed and the rest be refused with 429 and a wait. What must not
   happen is a 5xx, a hang or a crash.

The accounts are throwaway Developers made and deactivated inside the backend container, as the
stack's system tests make theirs (scripts/stack_system_test.py); their passwords are never printed.
"""

from __future__ import annotations

import argparse
import json
import secrets
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stack_system_test import CREATE, DEACTIVATE, REPO_ROOT, in_backend  # noqa: E402

BASE = "http://127.0.0.1:5173"
# The signed-in reads the pages poll. /api/health is left out: it is public and limited per address,
# and through nginx every user shares one address, so it would measure the limiter, not latency.
ENDPOINTS = ["/api/queue", "/api/runs", "/api/chains", "/api/services", "/api/analytics/runs"]


def request(path: str, token: str | None = None, body: dict | None = None) -> tuple[int, float]:
    """One request; returns its status and how long it took, in milliseconds."""
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(urllib.request.Request(BASE + path, data=data, headers=headers), timeout=60) as reply:
            reply.read()
            status = reply.status
    except urllib.error.HTTPError as error:
        error.read()
        status = error.code
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        status = 0
    return status, (time.perf_counter() - started) * 1000


def sign_in(email: str, password: str) -> str:
    data = json.dumps({"email": email, "password": password}).encode()
    request_ = urllib.request.Request(BASE + "/api/auth/login", data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request_, timeout=60) as reply:
        return json.loads(reply.read())["access_token"]


def paced_user(token: str, seconds: float, rate: float, samples: list[dict], lock: threading.Lock, offset: int) -> None:
    deadline = time.monotonic() + seconds
    index = offset
    while time.monotonic() < deadline:
        began = time.monotonic()
        path = ENDPOINTS[index % len(ENDPOINTS)]
        status, millis = request(path, token)
        with lock:
            samples.append({"endpoint": path, "status": status, "ms": round(millis, 2)})
        index += 1
        time.sleep(max(0.0, 1 / rate - (time.monotonic() - began)))


def summarise(samples: list[dict]) -> dict:
    by_endpoint: dict[str, list[dict]] = {}
    for sample in samples:
        by_endpoint.setdefault(sample["endpoint"], []).append(sample)

    def stats(group: list[dict]) -> dict:
        times = sorted(sample["ms"] for sample in group)
        statuses: dict[str, int] = {}
        for sample in group:
            statuses[str(sample["status"])] = statuses.get(str(sample["status"]), 0) + 1
        return {
            "requests": len(group),
            "p50_ms": round(statistics.median(times), 1),
            "p95_ms": round(times[min(len(times) - 1, int(len(times) * 0.95))], 1),
            "max_ms": round(times[-1], 1),
            "statuses": statuses,
        }

    return {"all": stats(samples), **{path: stats(group) for path, group in sorted(by_endpoint.items())}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=REPO_ROOT / ".tmp" / "system")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    accounts = [(f"load-test-{secrets.token_hex(4)}@example.com", secrets.token_urlsafe(24)) for _ in range(11)]
    for email, password in accounts:
        in_backend(CREATE, email, password)
    report: dict = {"base": BASE, "endpoints": ENDPOINTS, "levels": [], "stress": {}}
    try:
        tokens = [sign_in(email, password) for email, password in accounts]
        for users in (1, 5, 10):
            samples: list[dict] = []
            lock = threading.Lock()
            started = time.monotonic()
            with ThreadPoolExecutor(max_workers=users) as pool:
                for number in range(users):
                    pool.submit(paced_user, tokens[number], 30.0, 3.0, samples, lock, number)
            took = time.monotonic() - started
            level = {"users": users, "seconds": round(took, 1), "throughput_rps": round(len(samples) / took, 1),
                     **summarise(samples)}
            report["levels"].append(level)
            print(f"load {users:2d} users: {len(samples)} requests, p50 {level['all']['p50_ms']} ms, "
                  f"p95 {level['all']['p95_ms']} ms, statuses {level['all']['statuses']}", flush=True)

        burst_token = tokens[10]
        started = time.monotonic()
        with ThreadPoolExecutor(max_workers=30) as pool:
            results = list(pool.map(lambda n: request(ENDPOINTS[n % 5], burst_token), range(450)))
        took = time.monotonic() - started
        samples = [{"endpoint": ENDPOINTS[n % 5], "status": s, "ms": round(m, 2)} for n, (s, m) in enumerate(results)]
        report["stress"] = {"requests": 450, "threads": 30, "seconds": round(took, 1),
                            "throughput_rps": round(450 / took, 1), **summarise(samples)}
        print(f"stress: 450 requests in {took:.1f} s, statuses {report['stress']['all']['statuses']}", flush=True)
    finally:
        for email, _ in accounts:
            in_backend(DEACTIVATE, email)

    (args.out / "load-test.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    server_errors = sum(
        count for level in [*report["levels"], report["stress"]] for status, count in level["all"]["statuses"].items()
        if status.startswith("5") or status == "0"
    )
    print(f"report: {args.out / 'load-test.json'}; server errors or failed connections: {server_errors}")
    return 1 if server_errors else 0


if __name__ == "__main__":
    sys.exit(main())
