"""``HttpJenkinsClient.console_window``: the log plus Jenkins's own "still writing" answer.

A Pipeline reports ``building: false`` a moment before it writes ``Finished: SUCCESS``. Jenkins's
``X-More-Data`` header is what stays true across that gap, so these pin how it is read.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest

from app.core.settings import Settings
from app.services.jenkins import ConsoleChunk, HttpJenkinsClient, JobNotFoundError, keep_tail


def client_with(handler: httpx.MockTransport, settings: Settings) -> HttpJenkinsClient:
    """An HttpJenkinsClient whose transport is a stub."""
    return HttpJenkinsClient(
        settings, client=httpx.AsyncClient(base_url="http://jenkins-dev:8080", transport=handler)
    )


def progressive(text: str, headers: dict[str, str]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/job/it-pipeline/7/logText/progressiveText"
        return httpx.Response(200, text=text[int(request.url.params["start"]) :], headers=headers)

    return httpx.MockTransport(handler)


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ({"X-More-Data": "true"}, True),
        ({"X-More-Data": "True"}, True),
        ({"X-More-Data": "false"}, False),
        ({}, False),
    ],
)
async def test_more_data_comes_from_the_header(
    settings: Settings, headers: dict[str, str], expected: bool
) -> None:
    jenkins = client_with(progressive("[Pipeline] End of Pipeline\n", headers), settings)

    chunk = await jenkins.console_window("it-pipeline", 7)

    assert chunk == ConsoleChunk(text="[Pipeline] End of Pipeline\n", more_data=expected)
    await jenkins.aclose()


async def test_console_text_is_the_window_text_from_the_offset(settings: Settings) -> None:
    """``console_text`` keeps its contract: the text from ``start``, nothing else."""
    jenkins = client_with(
        progressive("Started\nFinished: SUCCESS\n", {"X-More-Data": "false"}), settings
    )

    assert await jenkins.console_text("it-pipeline", 7, start=8) == "Finished: SUCCESS\n"
    await jenkins.aclose()


# ---------------------------------------------------------------------------
# console_tail: the end of a log of any size, without holding the rest (T5.9)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("data", "max_bytes", "kept", "dropped"),
    [
        (b"one\ntwo\nthree\n", 100, b"one\ntwo\nthree\n", 0),  # small enough: untouched
        (b"one\ntwo\nthree\n", 6, b"three\n", 2),  # an exact line boundary
        (b"one\ntwo\nthree\n", 8, b"three\n", 2),  # the cut falls inside "two": all of it goes
        (b"no newline at all", 4, b"", 0),  # nothing whole to keep
    ],
)
def test_keep_tail_keeps_whole_lines_and_counts_what_it_dropped(
    data: bytes, max_bytes: int, kept: bytes, dropped: int
) -> None:
    buffer = bytearray(data)

    assert keep_tail(buffer, max_bytes) == dropped
    assert bytes(buffer) == kept


def streamed(body: bytes, *, chunk: int = 4096, status: int = 200) -> httpx.MockTransport:
    """A progressiveText endpoint that sends ``body`` in pieces, as a real response would."""

    async def pieces() -> AsyncIterator[bytes]:
        for start in range(0, len(body), chunk):
            yield body[start : start + chunk]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/job/it-failure/3/logText/progressiveText"
        assert request.url.params["start"] == "0"
        return httpx.Response(status, content=pieces(), headers={"X-More-Data": "false"})

    return httpx.MockTransport(handler)


async def test_console_tail_keeps_the_end_of_a_long_log_with_true_line_numbers(
    settings: Settings,
) -> None:
    lines = [f"line {number:07d}" for number in range(1, 200_001)]  # about 2.6 MB
    body = ("\n".join(lines) + "\n").encode()
    jenkins = client_with(streamed(body), settings)

    tail = await jenkins.console_tail("it-failure", 3, max_bytes=10_000)

    assert len(tail.text.encode()) <= 10_000
    kept = tail.text.splitlines()
    assert kept[-1] == "line 0200000"
    assert kept[0] == lines[tail.lines_before], "the first kept line is numbered as in Jenkins"
    assert tail.lines_before + len(kept) == len(lines)
    assert tail.more_data is False
    await jenkins.aclose()


async def test_console_tail_reports_a_missing_build(settings: Settings) -> None:
    jenkins = client_with(streamed(b"", status=404), settings)

    with pytest.raises(JobNotFoundError):
        await jenkins.console_tail("it-failure", 3, max_bytes=1000)
    await jenkins.aclose()


async def test_console_tail_retries_a_server_error(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    answers = iter([503, 200])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(next(answers), content=b"Finished: FAILURE\n")

    async def no_wait(*_: object) -> None:
        return None

    monkeypatch.setattr(HttpJenkinsClient, "_backoff", staticmethod(no_wait))
    jenkins = client_with(httpx.MockTransport(handler), settings)

    tail = await jenkins.console_tail("it-failure", 3, max_bytes=1000)

    assert tail.text == "Finished: FAILURE\n"
    await jenkins.aclose()
