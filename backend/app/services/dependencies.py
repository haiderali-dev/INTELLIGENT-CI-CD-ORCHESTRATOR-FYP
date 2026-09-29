"""FastAPI dependency providers.

Every outbound client is reached through a provider here so a test can substitute a fake with
``app.dependency_overrides`` rather than by patching module globals. BUILD_PROMPT 4.4.1 requires
that tests never need the network; this module is how that is enforced structurally.
"""

from __future__ import annotations

from app.core.settings import Settings, get_settings
from app.services.jenkins import HttpJenkinsClient, JenkinsClient

_jenkins_client: JenkinsClient | None = None


def get_settings_dep() -> Settings:
    """Settings as a dependency, so tests can override them per app instance."""
    return get_settings()


def get_jenkins_client() -> JenkinsClient:
    """The process-wide Jenkins client.

    One client, so its connection pool is reused rather than rebuilt per request.
    """
    global _jenkins_client
    if _jenkins_client is None:
        _jenkins_client = HttpJenkinsClient(get_settings())
    return _jenkins_client


def set_jenkins_client(client: JenkinsClient | None) -> None:
    """Install a client, or clear it. Used by the lifespan and by tests."""
    global _jenkins_client
    _jenkins_client = client


async def close_clients() -> None:
    """Release every outbound client on shutdown."""
    global _jenkins_client
    if _jenkins_client is not None:
        await _jenkins_client.aclose()
    _jenkins_client = None
