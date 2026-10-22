"""The REST client, against a fake opener: what it sends, and how it reads Jenkins' answers."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from email.message import Message
from pathlib import Path
from typing import Any

import pytest

from experiment import jenkins
from experiment.jenkins import Credentials, JenkinsClient, JenkinsError


class FakeResponse:
    def __init__(self, status: int, body: bytes, headers: dict[str, str] | None = None) -> None:
        self.status = status
        self.headers = Message()
        for key, value in (headers or {}).items():
            self.headers[key] = value
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_: object) -> None:
        return None


class FakeOpener:
    """Answers by (method, path); records every request it was given."""

    def __init__(
        self, answers: dict[tuple[str, str], list[tuple[int, Any, dict[str, str]]]]
    ) -> None:
        self.answers = answers
        self.requests: list[urllib.request.Request] = []

    def open(self, request: urllib.request.Request, /, *, timeout: float) -> FakeResponse:
        self.requests.append(request)
        path = request.full_url.removeprefix("http://jenkins")
        queue = self.answers[(request.get_method(), path)]
        status, body, headers = queue.pop(0) if len(queue) > 1 else queue[0]
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        if status >= 400:
            raise urllib.error.HTTPError(request.full_url, status, "error", Message(), None)
        return FakeResponse(status, data, headers)


CRUMB = (200, {"crumbRequestField": "Jenkins-Crumb", "crumb": "c1"}, {})


def client(
    answers: dict[tuple[str, str], list[tuple[int, Any, dict[str, str]]]],
) -> tuple[JenkinsClient, FakeOpener]:
    opener = FakeOpener(answers)
    return JenkinsClient("http://jenkins", Credentials("bot", "s3cret"), opener=opener), opener


def test_every_request_is_authenticated() -> None:
    api, opener = client({("GET", "/api/json?tree=mode"): [(200, {}, {"X-Jenkins": "2.568.3"})]})
    assert api.jenkins_version() == "2.568.3"
    assert opener.requests[0].get_header("Authorization") == "Basic Ym90OnMzY3JldA=="


def test_a_post_carries_the_crumb_fetched_once() -> None:
    api, opener = client(
        {
            ("GET", "/crumbIssuer/api/json"): [CRUMB],
            ("POST", "/job/a/build?delay=0sec"): [
                (201, b"", {"Location": "http://jenkins/queue/item/42/"})
            ],
        }
    )
    assert api.trigger("a") == 42
    assert api.trigger("a") == 42
    posts = [r for r in opener.requests if r.get_method() == "POST"]
    assert all(r.get_header("Jenkins-crumb") == "c1" for r in posts)
    assert sum(1 for r in opener.requests if "crumbIssuer" in r.full_url) == 1


def test_a_stale_crumb_is_fetched_again_once() -> None:
    fresh = (200, {"crumbRequestField": "Jenkins-Crumb", "crumb": "c2"}, {})
    api, opener = client(
        {
            ("GET", "/crumbIssuer/api/json"): [CRUMB, fresh],
            ("POST", "/createItem?name=a"): [(200, b"", {})],
        }
    )
    answer = opener.open
    refused: list[urllib.request.Request] = []

    def refuse_the_first_post(
        request: urllib.request.Request, /, *, timeout: float
    ) -> FakeResponse:
        if request.get_method() == "POST" and not refused:
            refused.append(request)
            raise urllib.error.HTTPError(
                request.full_url, 403, "Forbidden", Message(), _Body(b"No valid crumb was included")
            )
        return answer(request, timeout=timeout)

    opener.open = refuse_the_first_post  # type: ignore[method-assign]
    api.create_job("a", "<project/>")
    retried = [r for r in opener.requests if r.get_method() == "POST"]
    assert refused[0].get_header("Jenkins-crumb") == "c1"
    assert [r.get_header("Jenkins-crumb") for r in retried] == ["c2"]
    assert retried[0].get_header("Content-type") == "application/xml; charset=utf-8"


class _Body:
    def __init__(self, data: bytes) -> None:
        self.data = data

    def read(self, *_: object) -> bytes:
        return self.data

    def close(self) -> None:
        return None


def test_without_a_crumb_issuer_a_post_goes_without_one() -> None:
    api, opener = client(
        {
            ("GET", "/crumbIssuer/api/json"): [(404, b"", {})],
            ("POST", "/job/a/doDelete"): [(200, b"", {})],
        }
    )
    api.delete_job("a")
    assert opener.requests[-1].get_header("Jenkins-crumb") is None


def test_an_unexpected_status_raises_with_the_method_and_path() -> None:
    api, _ = client({("GET", "/job/a/api/json?tree=lastBuild[number]"): [(500, b"", {})]})
    with pytest.raises(
        JenkinsError, match=r"GET /job/a/api/json\?tree=lastBuild\[number\] answered 500"
    ):
        api.last_build_number("a")


def test_the_plugins_endpoints_read_none_on_stock_jenkins() -> None:
    api, _ = client(
        {
            ("GET", "/dynamic-queue/api/json"): [(404, b"", {})],
            ("GET", "/dynamic-queue/health"): [(404, b"", {})],
        }
    )
    assert api.dynamic_queue() is None
    assert api.health() is None


def test_executors_leave_out_the_built_in_node_and_offline_agents() -> None:
    computers = {
        "computer": [
            {
                "_class": "hudson.model.Hudson$MasterComputer",
                "displayName": "Built-In Node",
                "numExecutors": 0,
                "offline": False,
            },
            {
                "_class": "hudson.slaves.SlaveComputer",
                "displayName": "plugin-agent",
                "numExecutors": 3,
                "offline": False,
            },
            {
                "_class": "hudson.slaves.SlaveComputer",
                "displayName": "spare",
                "numExecutors": 2,
                "offline": True,
            },
        ]
    }
    api, _ = client(
        {
            ("GET", "/computer/api/json?tree=computer[displayName,numExecutors,offline,_class]"): [
                (200, computers, {})
            ]
        }
    )
    assert api.executors() == {"plugin-agent": 3}


def test_last_builds_reads_every_job_in_one_request() -> None:
    jobs = {
        "jobs": [
            {"name": "a", "lastBuild": {"number": 4, "building": True}},
            {"name": "b", "lastBuild": None},
        ]
    }
    api, opener = client(
        {("GET", "/api/json?tree=jobs[name,lastBuild[number,building]]"): [(200, jobs, {})]}
    )
    assert api.last_builds() == {"a": (4, True), "b": (0, False)}
    assert len(opener.requests) == 1


def test_recent_events_asks_for_the_whole_ring() -> None:
    api, opener = client(
        {
            ("GET", "/dynamic-queue/metrics/recent?limit=500"): [
                (200, {"limit": 500, "events": [{"kind": "QUEUE_LEFT"}]}, {})
            ]
        }
    )
    assert api.recent_events() == [{"kind": "QUEUE_LEFT"}]
    assert opener.requests[0].full_url.endswith("/dynamic-queue/metrics/recent?limit=500")


def test_an_unreachable_controller_is_a_jenkins_error() -> None:
    class Refusing:
        def open(self, request: urllib.request.Request, /, *, timeout: float) -> FakeResponse:
            raise urllib.error.URLError("connection refused")

    api = JenkinsClient("http://jenkins", Credentials("bot", "x"), opener=Refusing())
    with pytest.raises(JenkinsError, match="connection refused"):
        api.jobs()


def test_only_http_urls_are_accepted() -> None:
    with pytest.raises(JenkinsError, match="not an http"):
        JenkinsClient("file:///etc/passwd", Credentials("bot", "x"))


def test_credentials_come_from_the_environment_before_dot_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("JENKINS_BOT_PASSWORD=from-file\nOTHER=1\n", encoding="utf-8")
    monkeypatch.setattr(jenkins, "REPO_ROOT", tmp_path)
    monkeypatch.delenv("JENKINS_BOT_PASSWORD", raising=False)
    assert jenkins.credentials("bot", "JENKINS_BOT_PASSWORD").secret == "from-file"
    monkeypatch.setenv("JENKINS_BOT_PASSWORD", "from-env")
    assert jenkins.credentials("bot", "JENKINS_BOT_PASSWORD").secret == "from-env"
    with pytest.raises(JenkinsError, match="MISSING_SECRET is not set"):
        jenkins.credentials("bot", "MISSING_SECRET")


def test_a_secret_never_appears_in_a_repr() -> None:
    assert "s3cret" not in repr(Credentials("bot", "s3cret"))
