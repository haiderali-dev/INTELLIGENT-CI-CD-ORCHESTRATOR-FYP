"""FastAPI dependency providers.

Every outbound client is reached through a provider here so a test can substitute a fake with
``app.dependency_overrides`` rather than by patching module globals. BUILD_PROMPT 4.4.1 requires
that tests never need the network; this module is how that is enforced structurally.
"""

from __future__ import annotations

from typing import Literal

from app.ai.factory import build_provider
from app.ai.providers import FakeProvider, LLMProvider
from app.ai.rules import RuleBasedParser
from app.core.settings import LlmMode, Settings, get_settings
from app.generation.planner import default_plan_responder
from app.services.catalog import Catalog, catalog_path
from app.services.git import CliGitClient, GitClient
from app.services.jenkins import HttpJenkinsClient, JenkinsClient
from app.services.plugin import HttpPluginClient, PluginClient

_jenkins_client: JenkinsClient | None = None
_git_client: GitClient | None = None
_catalog: Catalog | None = None
_plugin_client: PluginClient | None = None
# Live and replay providers, by mode: one Groq client and its connection pool for the process.
_llm_providers: dict[LlmMode, tuple[LLMProvider, bool]] = {}


def get_llm_provider(
    settings: Settings, catalog: Catalog, purpose: Literal["intent", "plan"]
) -> tuple[LLMProvider, bool]:
    """The model provider, and whether it has models behind it.

    Live and replay providers are shared: they answer any prompt, so the intent parser and the
    planner use the same one. A fake provider is built per call instead, because it answers from
    the catalog -- with an intent for the parser, with the default plan for the planner -- and a
    test may hand in a different catalog.
    """
    if settings.llm_mode is LlmMode.FAKE:
        if purpose == "plan":
            return FakeProvider(responder=default_plan_responder(catalog)), True
        return build_provider(settings, RuleBasedParser(catalog))
    if settings.llm_mode not in _llm_providers:
        _llm_providers[settings.llm_mode] = build_provider(settings, RuleBasedParser(catalog))
    return _llm_providers[settings.llm_mode]


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


def get_git_client() -> GitClient:
    """The process-wide Git client.

    One instance, because its ref cache is the thing that keeps a conversation from making a
    network call per validation round.
    """
    global _git_client
    if _git_client is None:
        _git_client = CliGitClient()
    return _git_client


def set_git_client(client: GitClient | None) -> None:
    """Install a client, or clear it. Used by tests."""
    global _git_client
    _git_client = client


def get_plugin_client() -> PluginClient:
    """The process-wide plugin client.

    Separate from the Jenkins client although it talks to the same host: its timeout is shorter and
    it never retries, because the ranking decorates a page that has already loaded.
    """
    global _plugin_client
    if _plugin_client is None:
        _plugin_client = HttpPluginClient(get_settings())
    return _plugin_client


def set_plugin_client(client: PluginClient | None) -> None:
    """Install a client, or clear it. Used by tests."""
    global _plugin_client
    _plugin_client = client


def get_catalog() -> Catalog:
    """The process-wide catalog.

    Loaded once and refreshed from disk when the file changes, so this provider is cheap enough to
    depend on from any route.
    """
    global _catalog
    if _catalog is None:
        _catalog = Catalog(catalog_path(get_settings()))
    return _catalog


def set_catalog(catalog: Catalog | None) -> None:
    """Install a catalog, or clear it. Used by tests."""
    global _catalog
    _catalog = catalog


async def close_clients() -> None:
    """Release every outbound client on shutdown."""
    global _jenkins_client, _git_client, _plugin_client
    if _jenkins_client is not None:
        await _jenkins_client.aclose()
    _jenkins_client = None
    if _git_client is not None:
        await _git_client.aclose()
    _git_client = None
    if _plugin_client is not None:
        await _plugin_client.aclose()
    _plugin_client = None
    for provider, _ in _llm_providers.values():
        await provider.aclose()
    _llm_providers.clear()
