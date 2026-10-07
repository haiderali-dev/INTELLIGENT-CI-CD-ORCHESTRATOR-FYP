"""Jenkins REST client.

BUILD_PROMPT 4.4.5 fixes the method list, the auth, the timeout and the retry policy. Rule 1.5
fixes what must never appear: the Jenkins script console. Every operation here is an ordinary REST
call, and ``tests/test_no_script_console.py`` fails the build if either script-console endpoint is
ever referenced under ``backend/``.

The interface exists so the whole backend can be tested without a Jenkins. ``FakeJenkinsClient``
keeps jobs and runs in memory and is the default in tests, which is what lets the unit suite run in
seconds with no container.
"""

from __future__ import annotations

import asyncio
import random
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Final
from xml.etree import ElementTree

import httpx

from app.core.errors import ErrorCode, unavailable
from app.core.logging import get_logger
from app.core.settings import Settings

logger = get_logger(__name__)

TIMEOUT_SECONDS: Final = 10.0
MAX_ATTEMPTS: Final = 3

# Jenkins job names appear in URLs and on disk. Anything outside this set risks a path traversal or
# an unusable job, so names are checked before they are sent rather than after Jenkins complains.
JOB_NAME_PATTERN: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

LINT_SUCCESS_PREFIX: Final = "Jenkinsfile successfully validated"


@dataclass(frozen=True)
class QueueItem:
    """A queued build. ``build_number`` appears once Jenkins has assigned an executor."""

    id: int
    blocked: bool
    buildable: bool
    stuck: bool
    why: str | None
    cancelled: bool = False
    build_number: int | None = None
    job_name: str | None = None


@dataclass(frozen=True)
class BuildInfo:
    number: int
    building: bool
    result: str | None
    duration_ms: int
    timestamp_ms: int
    queue_id: int | None = None
    url: str = ""


@dataclass(frozen=True)
class LintResult:
    ok: bool
    message: str


class JenkinsError(RuntimeError):
    """A Jenkins call failed in a way the caller may want to distinguish."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class JobAlreadyExistsError(JenkinsError):
    """Creating a job whose name is taken."""


class JobNotFoundError(JenkinsError):
    """Operating on a job Jenkins does not have."""


def validate_job_name(name: str) -> str:
    """Reject a job name that cannot safely go in a URL."""
    if not JOB_NAME_PATTERN.match(name):
        raise JenkinsError(
            f"invalid job name {name!r}: letters, digits, dot, underscore and hyphen only, "
            "starting with a letter or digit, at most 128 characters"
        )
    return name


class JenkinsClient(ABC):
    """What the backend needs from Jenkins.

    Narrow on purpose. Anything not here is something the backend does not do, and the absence of a
    script-console method is part of the design rather than an oversight.
    """

    @abstractmethod
    async def version(self) -> str: ...

    @abstractmethod
    async def job_exists(self, name: str) -> bool: ...

    @abstractmethod
    async def create_job(self, name: str, config_xml: str) -> None: ...

    @abstractmethod
    async def update_job(self, name: str, config_xml: str) -> None: ...

    @abstractmethod
    async def get_config_xml(self, name: str) -> str: ...

    @abstractmethod
    async def delete_job(self, name: str) -> None: ...

    @abstractmethod
    async def trigger(self, name: str, params: dict[str, str] | None = None) -> int: ...

    @abstractmethod
    async def queue_item(self, item_id: int) -> QueueItem: ...

    @abstractmethod
    async def build(self, name: str, number: int) -> BuildInfo: ...

    @abstractmethod
    async def last_build(self, name: str) -> BuildInfo | None: ...

    @abstractmethod
    async def console_text(self, name: str, number: int, start: int = 0) -> str: ...

    @abstractmethod
    async def cancel_queue_item(self, item_id: int) -> None: ...

    @abstractmethod
    async def stop_build(self, name: str, number: int) -> None: ...

    @abstractmethod
    async def list_labels(self) -> list[str]: ...

    @abstractmethod
    async def lint_jenkinsfile(self, text: str) -> LintResult: ...

    @abstractmethod
    async def ranking(self) -> dict[str, Any]: ...

    async def aclose(self) -> None:
        """Release any transport. A no-op for implementations that hold none."""
        return None


class HttpJenkinsClient(JenkinsClient):
    """The real client.

    Basic auth with the least-privilege bot token, a 10-second timeout, and three attempts with
    exponential backoff on connection errors and 5xx. A 4xx is not retried: it will fail the same
    way again and retrying only delays the error the caller needs to see.
    """

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self._base = settings.jenkins_url.rstrip("/")
        self._auth = (settings.jenkins_user, settings.jenkins_token)
        self._client = client or httpx.AsyncClient(
            base_url=self._base,
            auth=self._auth,
            timeout=httpx.Timeout(TIMEOUT_SECONDS),
            follow_redirects=True,
        )
        self._crumb: tuple[str, str] | None = None

    async def aclose(self) -> None:
        await self._client.aclose()

    # --- transport ---------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        content: str | bytes | None = None,
        headers: dict[str, str] | None = None,
        expected: tuple[int, ...] = (200, 201),
    ) -> httpx.Response:
        last_error: Exception | None = None

        for attempt in range(1, MAX_ATTEMPTS + 1):
            request_headers = dict(headers or {})
            if method != "GET" and self._crumb:
                request_headers[self._crumb[0]] = self._crumb[1]

            try:
                response = await self._client.request(
                    method, path, params=params, data=data, content=content, headers=request_headers
                )
            except (
                httpx.ConnectError,
                httpx.ReadError,
                httpx.WriteError,
                httpx.PoolTimeout,
            ) as exc:
                last_error = exc
                await self._backoff(attempt, path, type(exc).__name__)
                continue
            except httpx.TimeoutException as exc:
                last_error = exc
                await self._backoff(attempt, path, "timeout")
                continue

            # A missing crumb looks like a 403. Fetch one and retry exactly once, as 4.4.5 says.
            if (
                response.status_code == 403
                and self._crumb is None
                and method != "GET"
                and await self._fetch_crumb()
            ):
                continue

            if response.status_code >= 500:
                last_error = JenkinsError(
                    f"Jenkins returned {response.status_code} for {path}",
                    status_code=response.status_code,
                )
                await self._backoff(attempt, path, str(response.status_code))
                continue

            if response.status_code not in expected:
                self._raise_for_status(method, path, response)
            return response

        raise unavailable(
            ErrorCode.JENKINS_UNAVAILABLE,
            f"Jenkins at {self._base} did not respond after {MAX_ATTEMPTS} attempts.",
            path=path,
            last_error=str(last_error),
        )

    @staticmethod
    def _raise_for_status(method: str, path: str, response: httpx.Response) -> None:
        if response.status_code == 404:
            raise JobNotFoundError(f"not found: {path}", status_code=404)
        if response.status_code == 400 and "already exists" in response.text.lower():
            raise JobAlreadyExistsError(f"already exists: {path}", status_code=400)
        raise JenkinsError(
            f"{method} {path} returned {response.status_code}: {response.text[:200]}",
            status_code=response.status_code,
        )

    @staticmethod
    async def _backoff(attempt: int, path: str, reason: str) -> None:
        if attempt >= MAX_ATTEMPTS:
            return
        # Jitter so several concurrent callers do not retry in lockstep and re-create the spike.
        delay = (2 ** (attempt - 1)) * 0.5 + random.uniform(0, 0.25)  # noqa: S311
        logger.warning(
            "jenkins_retry", path=path, attempt=attempt, reason=reason, delay=round(delay, 2)
        )
        await asyncio.sleep(delay)

    async def _fetch_crumb(self) -> bool:
        """Fetch a CSRF crumb. Returns whether one was obtained."""
        try:
            response = await self._client.get("/crumbIssuer/api/json")
            if response.status_code != 200:
                return False
            payload = response.json()
            self._crumb = (payload["crumbRequestField"], payload["crumb"])
            logger.info("jenkins_crumb_acquired")
            return True
        except (httpx.HTTPError, KeyError, ValueError):
            return False

    # --- API ---------------------------------------------------------------

    async def version(self) -> str:
        response = await self._request("GET", "/api/json", params={"tree": "mode"})
        # Jenkins reports its version in a response header rather than the JSON body.
        return str(response.headers.get("X-Jenkins", "unknown"))

    async def job_exists(self, name: str) -> bool:
        validate_job_name(name)
        try:
            await self._request("GET", f"/job/{name}/api/json", params={"tree": "name"})
            return True
        except JobNotFoundError:
            return False

    async def create_job(self, name: str, config_xml: str) -> None:
        validate_job_name(name)
        await self._request(
            "POST",
            "/createItem",
            params={"name": name},
            content=config_xml.encode("utf-8"),
            headers={"Content-Type": "application/xml; charset=utf-8"},
        )
        logger.info("jenkins_job_created", job=name)

    async def update_job(self, name: str, config_xml: str) -> None:
        validate_job_name(name)
        await self._request(
            "POST",
            f"/job/{name}/config.xml",
            content=config_xml.encode("utf-8"),
            headers={"Content-Type": "application/xml; charset=utf-8"},
        )
        logger.info("jenkins_job_updated", job=name)

    async def get_config_xml(self, name: str) -> str:
        validate_job_name(name)
        response = await self._request("GET", f"/job/{name}/config.xml")
        return response.text

    async def delete_job(self, name: str) -> None:
        """Delete a job. **Returns 403 with the bot token as configured.**

        ``Job/Delete`` is deliberately not among the bot's grants in ``jenkins/casc/*.yaml``:
        BUILD_PROMPT 4.1 calls for a "least-privilege ``orchestrator-bot`` API token", and 4.4.5's
        method list does not include deletion, so a compromised backend token cannot destroy build
        history.

        The method is kept because an operator with a wider token may want it, but nothing in the
        backend may depend on it. Callers that need a job gone should disable it, and callers that
        want a clean slate should use ``scripts/demo_reset.py`` with the admin account. Discovered
        the direct way: the Phase 3 integration tests tried to clean up after themselves and got a
        403 (docs/decisions.md D-033).
        """
        validate_job_name(name)
        await self._request("POST", f"/job/{name}/doDelete", expected=(200, 302))
        logger.info("jenkins_job_deleted", job=name)

    async def trigger(self, name: str, params: dict[str, str] | None = None) -> int:
        """Start a build and return its queue item id.

        The id comes from the ``Location`` header, which is the only way to correlate a trigger with
        the build it eventually becomes; polling for "the newest build" races other submissions.
        """
        validate_job_name(name)
        path = f"/job/{name}/buildWithParameters" if params else f"/job/{name}/build"
        response = await self._request("POST", path, data=params or None, expected=(200, 201))

        location = response.headers.get("Location", "")
        match = re.search(r"/queue/item/(\d+)/?$", location.rstrip("/"))
        if not match:
            raise JenkinsError(f"triggered {name} but Jenkins returned no queue item: {location!r}")
        item_id = int(match.group(1))
        logger.info("jenkins_triggered", job=name, queue_item=item_id)
        return item_id

    async def queue_item(self, item_id: int) -> QueueItem:
        response = await self._request("GET", f"/queue/item/{item_id}/api/json")
        payload = response.json()
        executable = payload.get("executable") or {}
        task = payload.get("task") or {}
        return QueueItem(
            id=int(payload.get("id", item_id)),
            blocked=bool(payload.get("blocked", False)),
            buildable=bool(payload.get("buildable", False)),
            stuck=bool(payload.get("stuck", False)),
            why=payload.get("why"),
            cancelled=bool(payload.get("cancelled", False)),
            build_number=executable.get("number"),
            job_name=task.get("name"),
        )

    async def build(self, name: str, number: int) -> BuildInfo:
        validate_job_name(name)
        response = await self._request("GET", f"/job/{name}/{number}/api/json")
        return self._to_build_info(response.json())

    async def last_build(self, name: str) -> BuildInfo | None:
        validate_job_name(name)
        try:
            response = await self._request("GET", f"/job/{name}/lastBuild/api/json")
        except JobNotFoundError:
            return None
        return self._to_build_info(response.json())

    @staticmethod
    def _to_build_info(payload: dict[str, Any]) -> BuildInfo:
        return BuildInfo(
            number=int(payload["number"]),
            building=bool(payload.get("building", False)),
            result=payload.get("result"),
            duration_ms=int(payload.get("duration", 0)),
            timestamp_ms=int(payload.get("timestamp", 0)),
            queue_id=payload.get("queueId"),
            url=payload.get("url", ""),
        )

    async def console_text(self, name: str, number: int, start: int = 0) -> str:
        """Fetch the console log from ``start``.

        ``progressiveText`` rather than ``consoleText`` so the run view can tail a long log without
        re-downloading it on every poll.
        """
        validate_job_name(name)
        response = await self._request(
            "GET", f"/job/{name}/{number}/logText/progressiveText", params={"start": start}
        )
        return response.text

    async def cancel_queue_item(self, item_id: int) -> None:
        await self._request(
            "POST", "/queue/cancelItem", params={"id": item_id}, expected=(200, 204, 302, 404)
        )

    async def stop_build(self, name: str, number: int) -> None:
        validate_job_name(name)
        await self._request("POST", f"/job/{name}/{number}/stop", expected=(200, 302))

    async def list_labels(self) -> list[str]:
        """Every label offered by an online node.

        Checks that a service's ``agent_label`` actually exists, so a job is never created that
        can never be scheduled.

        ``/computer/api/json``, **not** ``/api/json``. The root endpoint reports only the
        controller's own labels and has no ``nodes`` field, so querying it returned just
        ``built-in`` and ``controller`` while both agents were online and carrying ``linux``.
        ``scripts/validate_catalog.py`` had the identical bug and its fix never reached here.

        Offline nodes are excluded: a label that exists only on a disconnected agent is a label no
        build can be scheduled onto, which is exactly what this is asked to rule out.
        """
        response = await self._request(
            "GET",
            "/computer/api/json",
            params={"tree": "computer[displayName,offline,assignedLabels[name]]"},
        )
        payload = response.json()
        labels: set[str] = set()
        for computer in payload.get("computer", []):
            if computer.get("offline", False):
                continue
            for entry in computer.get("assignedLabels", []):
                if name := entry.get("name"):
                    labels.add(name)
        return sorted(labels)

    async def lint_jenkinsfile(self, text: str) -> LintResult:
        """Validate a declarative Jenkinsfile through the converter.

        4.4.5 fixes the contract: anything not starting with "Jenkinsfile successfully validated" is
        a failure, and the message is returned rather than swallowed, because it is what the
        generator's repair loop feeds back to the model.
        """
        response = await self._request(
            "POST", "/pipeline-model-converter/validate", data={"jenkinsfile": text}
        )
        body = response.text.strip()
        return LintResult(ok=body.startswith(LINT_SUCCESS_PREFIX), message=body)

    async def ranking(self) -> dict[str, Any]:
        """The plugin's queue ranking, with score breakdowns."""
        response = await self._request("GET", "/dynamic-queue/api/json")
        payload: dict[str, Any] = response.json()
        return payload


# ---------------------------------------------------------------------------
# Fake
# ---------------------------------------------------------------------------


@dataclass
class _FakeJob:
    config_xml: str
    builds: list[BuildInfo] = field(default_factory=list)
    logs: dict[int, str] = field(default_factory=dict)


class FakeJenkinsClient(JenkinsClient):
    """In-memory Jenkins for tests.

    Behaves like the real client at the level the backend cares about: names are validated, a
    trigger returns a queue item id that later resolves to a build number, and unknown jobs raise
    the same errors. It deliberately does not simulate scheduling; that is the plugin's job and is
    tested against a real Jenkins in the plugin's own suite.
    """

    def __init__(self, *, version: str = "2.568.3") -> None:
        self._version = version
        self.jobs: dict[str, _FakeJob] = {}
        self.queue: dict[int, QueueItem] = {}
        self.labels: list[str] = ["built-in", "linux"]
        self.lint_ok = True
        self.lint_message = LINT_SUCCESS_PREFIX
        self.ranking_payload: dict[str, Any] = {"configuration": {}, "queueLength": 0, "items": []}
        # Recorded so tests can assert what the backend asked Jenkins to do.
        self.calls: list[tuple[str, str]] = []
        self._next_queue_id = 1

    def _record(self, action: str, target: str) -> None:
        self.calls.append((action, target))

    async def version(self) -> str:
        return self._version

    async def job_exists(self, name: str) -> bool:
        validate_job_name(name)
        return name in self.jobs

    async def create_job(self, name: str, config_xml: str) -> None:
        validate_job_name(name)
        if name in self.jobs:
            raise JobAlreadyExistsError(f"already exists: {name}", status_code=400)
        # Well-formedness is checked here too, so a template bug fails in the unit suite rather
        # than only against a live Jenkins.
        ElementTree.fromstring(config_xml)  # noqa: S314
        self.jobs[name] = _FakeJob(config_xml=config_xml)
        self._record("create_job", name)

    async def update_job(self, name: str, config_xml: str) -> None:
        validate_job_name(name)
        if name not in self.jobs:
            raise JobNotFoundError(f"not found: {name}", status_code=404)
        ElementTree.fromstring(config_xml)  # noqa: S314
        self.jobs[name].config_xml = config_xml
        self._record("update_job", name)

    async def get_config_xml(self, name: str) -> str:
        validate_job_name(name)
        if name not in self.jobs:
            raise JobNotFoundError(f"not found: {name}", status_code=404)
        return self.jobs[name].config_xml

    async def delete_job(self, name: str) -> None:
        validate_job_name(name)
        self.jobs.pop(name, None)
        self._record("delete_job", name)

    async def trigger(self, name: str, params: dict[str, str] | None = None) -> int:
        validate_job_name(name)
        if name not in self.jobs:
            raise JobNotFoundError(f"not found: {name}", status_code=404)
        item_id = self._next_queue_id
        self._next_queue_id += 1
        self.queue[item_id] = QueueItem(
            id=item_id, blocked=False, buildable=True, stuck=False, why=None, job_name=name
        )
        self._record("trigger", name)
        return item_id

    def complete_queue_item(self, item_id: int, *, result: str = "SUCCESS") -> BuildInfo:
        """Test helper: turn a queued item into a finished build."""
        item = self.queue[item_id]
        name = item.job_name or ""
        job = self.jobs[name]
        number = len(job.builds) + 1
        info = BuildInfo(
            number=number,
            building=False,
            result=result,
            duration_ms=1234,
            timestamp_ms=0,
            queue_id=item_id,
        )
        job.builds.append(info)
        job.logs[number] = f"Started {name} #{number}\nFinished: {result}\n"
        self.queue[item_id] = QueueItem(
            id=item_id,
            blocked=False,
            buildable=False,
            stuck=False,
            why=None,
            build_number=number,
            job_name=name,
        )
        return info

    async def queue_item(self, item_id: int) -> QueueItem:
        if item_id not in self.queue:
            raise JobNotFoundError(f"no queue item {item_id}", status_code=404)
        return self.queue[item_id]

    async def build(self, name: str, number: int) -> BuildInfo:
        validate_job_name(name)
        job = self.jobs.get(name)
        if job is None:
            raise JobNotFoundError(f"not found: {name}", status_code=404)
        for info in job.builds:
            if info.number == number:
                return info
        raise JobNotFoundError(f"no build {name} #{number}", status_code=404)

    async def last_build(self, name: str) -> BuildInfo | None:
        job = self.jobs.get(name)
        return job.builds[-1] if job and job.builds else None

    async def console_text(self, name: str, number: int, start: int = 0) -> str:
        job = self.jobs.get(name)
        if job is None:
            raise JobNotFoundError(f"not found: {name}", status_code=404)
        return job.logs.get(number, "")[start:]

    async def cancel_queue_item(self, item_id: int) -> None:
        if item_id in self.queue:
            current = self.queue[item_id]
            self.queue[item_id] = QueueItem(
                id=current.id,
                blocked=False,
                buildable=False,
                stuck=False,
                why="cancelled",
                cancelled=True,
                job_name=current.job_name,
            )
        self._record("cancel_queue_item", str(item_id))

    async def stop_build(self, name: str, number: int) -> None:
        self._record("stop_build", f"{name}#{number}")

    async def list_labels(self) -> list[str]:
        return list(self.labels)

    async def lint_jenkinsfile(self, text: str) -> LintResult:
        self._record("lint_jenkinsfile", f"{len(text)} chars")
        return LintResult(ok=self.lint_ok, message=self.lint_message)

    async def ranking(self) -> dict[str, Any]:
        return dict(self.ranking_payload)
