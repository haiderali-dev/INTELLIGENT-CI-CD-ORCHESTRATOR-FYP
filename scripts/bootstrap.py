#!/usr/bin/env python3
"""One-time setup for the local stack: SSH keys, waiting for Jenkins, and the bot API token.

BUILD_PROMPT task T1.4. Three jobs, each idempotent so the script can be re-run safely:

1. Generate the ``agent-ssh-key`` pair the controller uses to launch the Linux agents, and write
   both halves into ``.env`` where docker-compose.yml and JCasC read them.
2. Wait for the controller to finish installing plugins and applying JCasC.
3. Mint an API token for ``orchestrator-bot`` and write it to ``.env`` as ``JENKINS_TOKEN``.

Deliberately not done with the Jenkins script console. Rule 1.5 forbids it, and the REST endpoint
``/me/descriptorByName/jenkins.security.ApiTokenProperty/generateNewToken`` does exactly this job
with the bot's own credentials instead of arbitrary code execution on the controller.

Usage:
    python scripts/bootstrap.py                # keys, then token if Jenkins is reachable
    python scripts/bootstrap.py --keys-only    # just the SSH key pair, before the first compose up
    python scripts/bootstrap.py --token-only   # just the token, once the controller is running
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import subprocess
import sys
import time
import http.cookiejar
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = REPO_ROOT / ".env"
KEY_DIR = REPO_ROOT / ".secrets"
PRIVATE_KEY = KEY_DIR / "agent_ssh_key"
PUBLIC_KEY = KEY_DIR / "agent_ssh_key.pub"

DEFAULT_JENKINS_URL = "http://localhost:8087"
WAIT_TIMEOUT_SECONDS = 600
POLL_SECONDS = 5


# ---------------------------------------------------------------------------
# .env handling
# ---------------------------------------------------------------------------


def read_env() -> dict[str, str]:
    """Parse .env into a mapping. Missing file yields an empty mapping."""
    if not ENV_FILE.is_file():
        return {}
    values: dict[str, str] = {}
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([A-Z_][A-Z0-9_]*)=(.*)$", line)
        if match:
            values[match.group(1)] = match.group(2)
    return values


def set_env_value(name: str, value: str) -> None:
    """Add or replace one variable in .env, preserving everything else.

    Rewrites in place rather than appending a duplicate, because a second ``JENKINS_TOKEN=`` line
    would silently win over the first and make a stale token very hard to spot.
    """
    if not ENV_FILE.is_file():
        raise SystemExit("no .env file. Copy .env.example to .env first.")

    lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    replacement = f"{name}={value}"
    for index, line in enumerate(lines):
        if re.match(rf"^{re.escape(name)}=", line):
            lines[index] = replacement
            break
    else:
        lines.append(replacement)
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. SSH keys
# ---------------------------------------------------------------------------


def generate_agent_key(*, force: bool = False) -> tuple[str, str]:
    """Create the agent SSH key pair, or reuse the existing one.

    ed25519 rather than RSA: shorter, and every OpenSSH the agent image ships supports it. The
    private key is written under .secrets/, which .gitignore excludes, and is also placed in .env
    because JCasC reads it from the environment to build the ``agent-ssh-key`` credential.
    """
    KEY_DIR.mkdir(exist_ok=True)

    if PRIVATE_KEY.is_file() and PUBLIC_KEY.is_file() and not force:
        print("  SSH key pair already exists; reusing it")
    else:
        for path in (PRIVATE_KEY, PUBLIC_KEY):
            path.unlink(missing_ok=True)
        result = subprocess.run(
            [
                "ssh-keygen",
                "-t", "ed25519",
                "-N", "",            # no passphrase: the controller must launch agents unattended
                "-C", "jenkins-agent@orchestrator",
                "-f", str(PRIVATE_KEY),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise SystemExit(
                "ssh-keygen failed. It ships with Git for Windows and with OpenSSH.\n"
                + result.stderr.strip()
            )
        print("  generated a new ed25519 key pair")

    private = PRIVATE_KEY.read_text(encoding="utf-8")
    public = PUBLIC_KEY.read_text(encoding="utf-8").strip()

    # The private key is deliberately NOT written to .env.
    #
    # A PEM key spans many lines and .env is line-oriented, so the first version stored it with the
    # newlines escaped as \n. Compose passed those two characters through literally, JCasC built a
    # credential from a single-line string, and every agent launch failed with
    #     PEM problem: it is of unknown type
    # which reads like an unsupported key algorithm rather than a formatting mistake.
    #
    # Instead it goes to .secrets/AGENT_SSH_PRIVATE_KEY, which docker-compose.yml mounts into the
    # controller as JCasC's SECRETS directory. JCasC resolves a ${NAME} placeholder from a file of
    # that name before falling back to the environment, so the newlines survive intact.
    secret_file = KEY_DIR / "AGENT_SSH_PRIVATE_KEY"
    secret_file.write_text(private, encoding="utf-8", newline="\n")

    set_env_value("AGENT_SSH_PUBLIC_KEY", public)

    print(f"  wrote AGENT_SSH_PUBLIC_KEY to {ENV_FILE.name}")
    print(f"  private key for JCasC: {secret_file.relative_to(REPO_ROOT)} (gitignored)")
    return private, public


# ---------------------------------------------------------------------------
# 2. Wait for Jenkins
# ---------------------------------------------------------------------------


# One opener with a cookie jar, shared by every call.
#
# Jenkins binds a CSRF crumb to the HTTP session that requested it. Fetching the crumb on one
# connection and POSTing it on another -- which is what happens with a bare urlopen per call --
# produces "403 No valid crumb was included in the request" even though the crumb itself is
# perfectly valid. The session cookie has to travel with it.
_OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def _request(
    url: str, *, user: str | None = None, password: str | None = None,
    data: bytes | None = None, headers: dict[str, str] | None = None, timeout: int = 15,
) -> tuple[int, str, dict[str, str]]:
    """One HTTP call returning (status, body, headers). Never raises on an HTTP error status."""
    request = urllib.request.Request(url, data=data, method="POST" if data is not None else "GET")
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    if user is not None:
        token = base64.b64encode(f"{user}:{password}".encode()).decode("ascii")
        request.add_header("Authorization", f"Basic {token}")
    try:
        with _OPENER.open(request, timeout=timeout) as response:  # noqa: S310
            return response.status, response.read().decode("utf-8", "replace"), dict(response.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace"), dict(exc.headers or {})
    except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
        return 0, str(exc), {}


def wait_for_jenkins(url: str, timeout: int = WAIT_TIMEOUT_SECONDS) -> bool:
    """Block until the controller serves its login page.

    A first start installs 16 plugins and applies JCasC before the port answers, which takes
    minutes rather than seconds, so the timeout is generous and progress is printed.
    """
    deadline = time.time() + timeout
    print(f"  waiting for {url} (up to {timeout}s)")
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        status, _, _ = _request(f"{url}/login", timeout=10)
        if status == 200:
            print(f"  controller answered after {attempt} attempt(s)")
            return True
        if attempt % 6 == 0:
            remaining = int(deadline - time.time())
            print(f"    still starting (status {status}); {remaining}s left")
        time.sleep(POLL_SECONDS)
    print(f"  timed out after {timeout}s")
    return False


# ---------------------------------------------------------------------------
# 3. Bot API token
# ---------------------------------------------------------------------------


def create_bot_token(url: str, user: str, password: str) -> str | None:
    """Mint an API token for the bot, using the bot's own credentials.

    No script console: this is the documented REST endpoint for the purpose. A crumb is fetched
    first because Jenkins rejects an unadorned POST with a 403 that looks like an auth failure.
    """
    status, body, _ = _request(f"{url}/crumbIssuer/api/json", user=user, password=password)
    crumb_header: dict[str, str] = {}
    if status == 200:
        try:
            crumb = json.loads(body)
            crumb_header = {crumb["crumbRequestField"]: crumb["crumb"]}
        except (ValueError, KeyError):
            pass
    elif status in (401, 403):
        print(f"  authentication failed for {user} (status {status})")
        print("  check JENKINS_BOT_PASSWORD in .env matches what JCasC created")
        return None

    endpoint = (
        f"{url}/user/{urllib.parse.quote(user)}"
        "/descriptorByName/jenkins.security.ApiTokenProperty/generateNewToken"
    )
    payload = urllib.parse.urlencode({"newTokenName": "orchestrator-backend"}).encode()
    status, body, _ = _request(
        endpoint,
        user=user,
        password=password,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded", **crumb_header},
    )
    if status != 200:
        print(f"  token request returned {status}")
        print(f"  {body[:300]}")
        return None

    try:
        token: str = json.loads(body)["data"]["tokenValue"]
    except (ValueError, KeyError):
        print(f"  unexpected response shape: {body[:200]}")
        return None
    return token


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=None, help="controller URL (default: JENKINS_URL or localhost:8087)")
    parser.add_argument("--keys-only", action="store_true", help="generate the SSH key pair and stop")
    parser.add_argument("--token-only", action="store_true", help="mint the API token only")
    parser.add_argument("--force-keys", action="store_true", help="replace an existing key pair")
    parser.add_argument("--timeout", type=int, default=WAIT_TIMEOUT_SECONDS)
    args = parser.parse_args()

    env = read_env()
    # The container-internal hostname is useless from the host, so prefer the published port.
    url = (args.url or env.get("BOOTSTRAP_JENKINS_URL") or DEFAULT_JENKINS_URL).rstrip("/")

    if not args.token_only:
        print("1. Agent SSH key")
        generate_agent_key(force=args.force_keys)
        if args.keys_only:
            print("\nkeys ready. Next: docker compose up -d")
            return 0

    print(f"\n2. Waiting for Jenkins at {url}")
    if not wait_for_jenkins(url, timeout=args.timeout):
        print("\n   Jenkins is not answering. Start it with `docker compose up -d jenkins-dev`,")
        print("   then re-run `python scripts/bootstrap.py --token-only`.")
        return 1

    print("\n3. Bot API token")
    bot_user = env.get("JENKINS_USER") or "orchestrator-bot"
    bot_password = env.get("JENKINS_BOT_PASSWORD", "")
    if not bot_password:
        print("  JENKINS_BOT_PASSWORD is not set in .env")
        return 1

    existing = env.get("JENKINS_TOKEN", "")
    if existing:
        status, _, _ = _request(f"{url}/api/json", user=bot_user, password=existing)
        if status == 200:
            print("  existing JENKINS_TOKEN still works; leaving it alone")
            print("\nbootstrap complete")
            return 0
        print("  existing JENKINS_TOKEN no longer works; minting a new one")

    token = create_bot_token(url, bot_user, bot_password)
    if token is None:
        return 1

    set_env_value("JENKINS_TOKEN", token)
    # Never printed. Only its length, which is enough to confirm it looks like a token.
    print(f"  minted a {len(token)}-character token and wrote JENKINS_TOKEN to {ENV_FILE.name}")

    status, _, _ = _request(f"{url}/api/json", user=bot_user, password=token)
    if status != 200:
        print(f"  warning: the new token was rejected on verification (status {status})")
        return 1
    print("  verified: the bot can authenticate with it")

    print("\nbootstrap complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
