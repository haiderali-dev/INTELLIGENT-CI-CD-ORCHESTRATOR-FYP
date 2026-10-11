"""``HttpJenkinsClient.console_window``: the log plus Jenkins's own "still writing" answer.

A Pipeline reports ``building: false`` a moment before it writes ``Finished: SUCCESS``. Jenkins's
``X-More-Data`` header is what stays true across that gap, so these pin how it is read.
"""

from __future__ import annotations

import httpx
import pytest

from app.core.settings import Settings
from app.services.jenkins import ConsoleChunk, HttpJenkinsClient


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
