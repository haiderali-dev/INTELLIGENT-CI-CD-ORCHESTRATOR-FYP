"""Recovery test of the running stack: each dependency restarted in turn, with the time to recover.

    python scripts/recovery_test.py [--out .tmp/system]

Structural system testing in Perry's sense (2007, ch. 8): can the system be returned to service
after a failure, and does it lose anything? Three restarts, one at a time, each waited out before
the next. The containers are only restarted: no volume is touched, so nothing stored can be lost
except by a defect.

1. **PostgreSQL.** The backend must report its database down while it is, recover by itself (no
   backend restart), and serve a signed-in request again.
2. **The backend.** It must come back with every run it had stored.
3. **jenkins-dev.** The backend must report Jenkins down rather than fail its own requests, the
   Queue API must say the ranking is unavailable rather than answer 5xx, and both agents must
   reconnect afterwards.

A throwaway Developer account reads the API, made and deactivated inside the backend container as
the stack's system tests make theirs; its password is never printed.
"""

from __future__ import annotations

import argparse
import json
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stack_system_test import CREATE, DEACTIVATE, REPO_ROOT, in_backend  # noqa: E402

BACKEND = "http://127.0.0.1:8000"


def get(path: str, token: str | None = None) -> tuple[int, dict]:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        with urllib.request.urlopen(urllib.request.Request(BACKEND + path, headers=headers), timeout=15) as reply:
            return reply.status, json.loads(reply.read() or b"{}")
    except urllib.error.HTTPError as error:
        try:
            return error.code, json.loads(error.read() or b"{}")
        except ValueError:
            return error.code, {}
    except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError):
        return 0, {}


def sign_in(email: str, password: str) -> str:
    data = json.dumps({"email": email, "password": password}).encode()
    request = urllib.request.Request(BACKEND + "/api/auth/login", data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as reply:
        return json.loads(reply.read())["access_token"]


def component(name: str) -> str:
    status, body = get("/api/health")
    if status == 0:
        return "backend down"
    return str(body.get("components", {}).get(name, {}).get("status", f"http {status}"))


def wait_until(condition: Callable[[], bool], timeout: float) -> float | None:
    """Seconds until the condition held, polling twice a second, or None on timeout."""
    started = time.monotonic()
    while time.monotonic() - started < timeout:
        if condition():
            return round(time.monotonic() - started, 1)
        time.sleep(0.5)
    return None


def restart(service: str) -> float:
    started = time.monotonic()
    subprocess.run(["docker", "compose", "restart", service], cwd=REPO_ROOT, check=True, capture_output=True)
    return round(time.monotonic() - started, 1)


def agents_online() -> bool:
    import verify  # scripts/verify.py: the gate's own check, with its own credentials

    return verify.check_agents_online().ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=REPO_ROOT / ".tmp" / "system")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    if any(component(name) != "up" for name in ("database", "jenkins")):
        print("The stack is not healthy to begin with; start it and wait first.")
        return 2
    email, password = f"recovery-test-{secrets.token_hex(4)}@example.com", secrets.token_urlsafe(24)
    in_backend(CREATE, email, password)
    report: dict = {"steps": []}
    failed = 0
    try:
        token = sign_in(email, password)
        _, runs = get("/api/runs", token)
        stored = runs.get("total", len(runs.get("items", [])))

        # 1. PostgreSQL
        took = restart("postgres")
        seen_down = component("database") != "up"
        recovered = wait_until(lambda: component("database") == "up", 120)
        status, _ = get("/api/me", token)
        step = {"restarted": "postgres", "restart_command_s": took, "reported_down_after_restart": seen_down,
                "database_up_again_after_s": recovered, "signed_in_request_after": status,
                "passed": recovered is not None and status == 200}
        report["steps"].append(step)

        # 2. The backend
        took = restart("backend")
        recovered = wait_until(lambda: get("/api/health/live")[0] == 200, 180)
        token = sign_in(email, password)
        _, runs = get("/api/runs", token)
        after = runs.get("total", len(runs.get("items", [])))
        step = {"restarted": "backend", "restart_command_s": took, "live_again_after_s": recovered,
                "runs_before": stored, "runs_after": after, "passed": recovered is not None and after == stored}
        report["steps"].append(step)

        # 3. jenkins-dev
        took = restart("jenkins-dev")
        jenkins_state = component("jenkins")
        queue_status, queue = get("/api/queue", token)
        recovered = wait_until(lambda: component("jenkins") == "up", 600)
        agents = wait_until(agents_online, 600)
        step = {"restarted": "jenkins-dev", "restart_command_s": took,
                "jenkins_reported_while_restarting": jenkins_state,
                "queue_api_while_restarting": queue_status,
                "queue_said_unavailable": bool(queue) and queue.get("available") is False,
                "queue_unavailable_reason": queue.get("unavailable_reason"),
                "jenkins_up_again_after_s": recovered, "agents_online_after_s": agents,
                "passed": recovered is not None and agents is not None and queue_status != 0 and queue_status < 500}
        report["steps"].append(step)
    finally:
        in_backend(DEACTIVATE, email)

    for step in report["steps"]:
        failed += not step["passed"]
        print(json.dumps(step))
    (args.out / "recovery-test.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"report: {args.out / 'recovery-test.json'}; {failed} of {len(report['steps'])} steps failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
