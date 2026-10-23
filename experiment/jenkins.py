"""The harness's only way into Jenkins: its REST API and the plugin's ``/dynamic-queue`` endpoints.

No Groovy and no script console (rule 1.5). Milestone 2's harness drove both controllers by
posting Groovy to the script console; every operation here has a REST equivalent instead:
``createItem`` with a ``config.xml``, ``/job/<name>/build``, ``/api/json`` trees, and the plugin's
ranking, health and recent-events endpoints.

Credentials come from the environment, or else from the repository's ``.env``, and are never
printed. The bot account creates, configures and builds jobs; only ``setup --recreate`` uses the
admin account, because the bot deliberately holds no Job/Delete (``jenkins/casc/``).
"""

from __future__ import annotations

import base64
import http.cookiejar
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from email.message import Message
from pathlib import Path
from typing import Any, Final, Protocol

REPO_ROOT: Final = Path(__file__).resolve().parents[1]
#: The two experiment controllers of the Compose ``experiment`` profile (BUILD_PROMPT 4.2.3).
CONTROLLERS: Final = {"baseline": "http://127.0.0.1:8085", "plugin": "http://127.0.0.1:8086"}
BOT_USER: Final = "orchestrator-bot"
ADMIN_USER: Final = "admin"
#: The plugin keeps its last 500 events; asking for more returns 500.
RECENT_LIMIT: Final = 500
_TIMEOUT_SECONDS: Final = 30


class JenkinsError(RuntimeError):
    """A request Jenkins refused or that failed, naming what the harness was trying to do."""


@dataclass(frozen=True)
class Credentials:
    """A user and its password or token. The secret never appears in a repr."""

    user: str
    secret: str = field(repr=False)

    def header(self) -> str:
        token = base64.b64encode(f"{self.user}:{self.secret}".encode()).decode("ascii")
        return f"Basic {token}"


def env_file(path: Path | None = None) -> dict[str, str]:
    """The repository's ``.env`` as a dict, read when needed and never printed."""
    target = path or REPO_ROOT / ".env"
    if not target.is_file():
        return {}
    values: dict[str, str] = {}
    for line in target.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([A-Z_][A-Z0-9_]*)=(.*)$", line)
        if match:
            values[match.group(1)] = match.group(2)
    return values


def credentials(user: str, variable: str) -> Credentials:
    """The secret named ``variable``, from the environment first and ``.env`` second."""
    secret = os.environ.get(variable) or env_file().get(variable)
    if not secret:
        raise JenkinsError(f"{variable} is not set, in the environment or in .env")
    return Credentials(user=user, secret=secret)


class Opener(Protocol):
    """What the client needs from urllib's opener; tests pass a fake one."""

    def open(self, request: urllib.request.Request, /, *, timeout: float) -> Any: ...


@dataclass(frozen=True)
class Response:
    """A completed request: its status, headers and body."""

    status: int
    headers: Message
    body: bytes

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8"))


class JenkinsClient:
    """One controller, one account. Not thread-safe; the harness drives one controller at a time."""

    def __init__(self, base_url: str, creds: Credentials, opener: Opener | None = None) -> None:
        if urllib.parse.urlsplit(base_url).scheme not in ("http", "https"):
            raise JenkinsError(f"{base_url!r} is not an http or https URL")
        self.base_url = base_url.rstrip("/")
        self._creds = creds
        jar = http.cookiejar.CookieJar()
        self._opener: Opener = opener or urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(jar)
        )
        self._crumb: tuple[str, str] | None = None

    # ------------------------------------------------------------------------------------------
    # Requests
    # ------------------------------------------------------------------------------------------

    def request(
        self,
        method: str,
        path: str,
        data: bytes | None = None,
        content_type: str | None = None,
        accept: tuple[int, ...] = (200,),
    ) -> Response:
        """One request. A status outside ``accept`` raises, naming the method and path."""
        response = self._send(method, path, data, content_type)
        if method == "POST" and response.status == 403 and b"crumb" in response.body.lower():
            # A crumb lives as long as its session; when that ends, fetch a new one, once.
            self._crumb = None
            response = self._send(method, path, data, content_type)
        if response.status not in accept:
            detail = response.body[:200].decode("utf-8", "replace").strip()
            raise JenkinsError(f"{method} {path} answered {response.status}: {detail}")
        return response

    def _send(
        self, method: str, path: str, data: bytes | None, content_type: str | None
    ) -> Response:
        headers = {"Authorization": self._creds.header()}
        if content_type:
            headers["Content-Type"] = content_type
        if method == "POST":
            headers.update(self._crumb_header())
        # The scheme was checked in __init__, and the path is the harness's own.
        request = urllib.request.Request(  # noqa: S310
            self.base_url + path, data=data, headers=headers, method=method
        )
        try:
            with self._opener.open(request, timeout=_TIMEOUT_SECONDS) as raw:
                return Response(raw.status, raw.headers, raw.read())
        except urllib.error.HTTPError as error:
            return Response(error.code, error.headers, error.read() if error.fp else b"")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            raise JenkinsError(f"{method} {self.base_url}{path}: {error}") from error

    def get_json(self, path: str) -> Any:
        return self.request("GET", path).json()

    def _crumb_header(self) -> dict[str, str]:
        """Jenkins' CSRF crumb, fetched once per client; its session cookie stays in the jar."""
        if self._crumb is None:
            response = self.request("GET", "/crumbIssuer/api/json", accept=(200, 404))
            if response.status == 404:
                return {}
            data = response.json()
            self._crumb = (str(data["crumbRequestField"]), str(data["crumb"]))
        return {self._crumb[0]: self._crumb[1]}

    # ------------------------------------------------------------------------------------------
    # The controller
    # ------------------------------------------------------------------------------------------

    def jenkins_version(self) -> str | None:
        return self.request("GET", "/api/json?tree=mode").headers.get("X-Jenkins")

    def executors(self) -> dict[str, int]:
        """Executors per online agent; the built-in node, set to 0 executors, is left out."""
        data = self.get_json(
            "/computer/api/json?tree=computer[displayName,numExecutors,offline,_class]"
        )
        return {
            str(node["displayName"]): int(node["numExecutors"])
            for node in data["computer"]
            if not node.get("offline") and "MasterComputer" not in str(node.get("_class", ""))
        }

    def busy(self) -> tuple[int, int]:
        """(busy executors, items in the queue): both 0 when the controller is idle."""
        computers = self.get_json("/computer/api/json?tree=busyExecutors")
        queue = self.get_json("/queue/api/json?tree=items[id]")
        return int(computers["busyExecutors"]), len(queue["items"])

    # ------------------------------------------------------------------------------------------
    # Jobs and builds
    # ------------------------------------------------------------------------------------------

    def jobs(self) -> dict[str, str]:
        """Every top-level job's name and description."""
        data = self.get_json("/api/json?tree=jobs[name,description]")
        return {str(job["name"]): str(job.get("description") or "") for job in data["jobs"]}

    def create_job(self, name: str, config_xml: str) -> None:
        query = urllib.parse.urlencode({"name": name})
        self.request(
            "POST",
            f"/createItem?{query}",
            data=config_xml.encode("utf-8"),
            content_type="application/xml; charset=utf-8",
        )

    def delete_job(self, name: str) -> None:
        # Jenkins redirects after deleting; the redirect itself is the success.
        self.request("POST", f"/job/{_quote(name)}/doDelete", accept=(200, 302))

    def trigger(self, name: str) -> int | None:
        """Queue one build now, with no quiet period, and return its queue item's id if known."""
        response = self.request("POST", f"/job/{_quote(name)}/build?delay=0sec", accept=(200, 201))
        location = response.headers.get("Location") or ""
        match = re.search(r"/queue/item/(\d+)/?$", location)
        return int(match.group(1)) if match else None

    def last_builds(self) -> dict[str, tuple[int, bool]]:
        """Every job's last build number (0 if none) and whether it is building, in one request."""
        data = self.get_json("/api/json?tree=jobs[name,lastBuild[number,building]]")
        latest: dict[str, tuple[int, bool]] = {}
        for job in data["jobs"]:
            last = job.get("lastBuild") or {}
            latest[str(job["name"])] = (int(last.get("number") or 0), bool(last.get("building")))
        return latest

    def last_build_number(self, name: str) -> int:
        """The job's last build number, or 0 when it has never built."""
        data = self.get_json(f"/job/{_quote(name)}/api/json?tree=lastBuild[number]")
        return int(data["lastBuild"]["number"]) if data.get("lastBuild") else 0

    def build(self, name: str, number: int) -> dict[str, Any]:
        tree = "number,timestamp,duration,result,building,builtOn,queueId"
        data: dict[str, Any] = self.get_json(f"/job/{_quote(name)}/{number}/api/json?tree={tree}")
        return data

    # ------------------------------------------------------------------------------------------
    # The plugin
    # ------------------------------------------------------------------------------------------

    def dynamic_queue(self) -> dict[str, Any] | None:
        """The plugin's ranking and configuration, or None without the plugin (stock Jenkins)."""
        response = self.request("GET", "/dynamic-queue/api/json", accept=(200, 404))
        return None if response.status == 404 else dict(response.json())

    def health(self) -> dict[str, Any] | None:
        response = self.request("GET", "/dynamic-queue/health", accept=(200, 404))
        return None if response.status == 404 else dict(response.json())

    def recent_events(self, limit: int = RECENT_LIMIT) -> list[dict[str, Any]]:
        """The plugin's last ``limit`` recorded events, oldest first."""
        data = self.get_json(f"/dynamic-queue/metrics/recent?limit={limit}")
        return list(data["events"])


def _quote(name: str) -> str:
    return urllib.parse.quote(name, safe="")
