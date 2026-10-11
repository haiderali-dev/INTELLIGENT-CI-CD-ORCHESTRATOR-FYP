"""The service catalog: the only place shell commands come from.

BUILD_PROMPT 4.6.1: "Each template resolves to a command from the catalog, so the model never
writes shell commands." That makes this module a security boundary, not a convenience. Every
command the system ever runs on an agent is read from ``catalog/services.yaml`` here, and the
generator interpolates only values that came back from one of these lookups.

Two consequences shape the design:

* the file is validated against ``catalog/services.schema.json`` on every load, so a hand-edit that
  introduces a shell metacharacter or a ``production`` environment fails at load rather than at the
  moment a job would run it;
* lookups return ``None`` for anything absent rather than a default, because a silent default here
  would mean running a command nobody wrote for a service nobody named.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

import jsonschema
import yaml

from app.core.logging import get_logger
from app.core.settings import Settings

logger = get_logger(__name__)

# 4.5.2 fixes the extra_stages enum; the schema enforces it, and this mirrors it for the intent
# schema builder so the two cannot drift apart unnoticed.
EXTRA_STAGES: Final = ("lint", "security_scan", "integration_tests", "smoke_test")

SCHEMA_FILENAME: Final = "services.schema.json"


class CatalogError(RuntimeError):
    """The catalog is missing, unreadable or does not satisfy its schema."""


# ---------------------------------------------------------------------------
# Typed view of one entry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TestSuite:
    name: str
    command: str
    approx_seconds: int


@dataclass(frozen=True)
class DeployTarget:
    command: str
    url: str


@dataclass(frozen=True)
class CatalogService:
    """One service, exactly as the YAML declares it."""

    name: str
    repo: str
    default_branch: str
    agent_label: str
    build_command: str
    test_suites: tuple[TestSuite, ...]
    deploy: dict[str, DeployTarget]
    allowed_environments: tuple[str, ...]
    extra_stages: dict[str, str] = field(default_factory=dict)

    def suite(self, name: str) -> TestSuite | None:
        """The named suite, or None. 4.5.3 checks that a suite belongs to *this* service."""
        return next((suite for suite in self.test_suites if suite.name == name), None)

    def allows(self, environment: str) -> bool:
        return environment in self.allowed_environments

    def deploy_target(self, environment: str) -> DeployTarget | None:
        """The deploy command for an environment, but only if that environment is allowed.

        The allow-list is checked here as well as in the policy layer. A deploy target present in
        the file but absent from ``allowed_environments`` is a contradiction, and resolving it to a
        runnable command would make the allow-list advisory.
        """
        if not self.allows(environment):
            return None
        return self.deploy.get(environment)

    def extra_stage_command(self, stage: str) -> str | None:
        return self.extra_stages.get(stage)

    @classmethod
    def from_mapping(cls, entry: dict[str, Any]) -> CatalogService:
        return cls(
            name=entry["name"],
            repo=entry["repo"],
            default_branch=entry.get("default_branch", "main"),
            agent_label=entry.get("agent_label", "linux"),
            build_command=entry["build_command"],
            test_suites=tuple(
                TestSuite(
                    name=suite["name"],
                    command=suite["command"],
                    approx_seconds=suite["approx_seconds"],
                )
                for suite in entry.get("test_suites", [])
            ),
            deploy={
                environment: DeployTarget(command=target["command"], url=target["url"])
                for environment, target in entry.get("deploy", {}).items()
            },
            allowed_environments=tuple(entry.get("allowed_environments", [])),
            extra_stages=dict(entry.get("extra_stages", {})),
        )


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def catalog_path(settings: Settings) -> Path:
    """Resolve the configured catalog path.

    The backend runs from ``backend/`` on a developer machine and from ``/app`` in the container,
    where the catalog is mounted at ``/app/catalog``. Both work without a conditional in settings.
    """
    configured = Path(settings.catalog_path)
    if configured.is_absolute():
        return configured
    for base in (Path.cwd(), Path.cwd().parent, Path(__file__).resolve().parents[3]):
        candidate = base / configured
        if candidate.is_file():
            return candidate
    return Path.cwd() / configured


def _schema_for(path: Path) -> dict[str, Any] | None:
    """The JSON Schema sitting beside the catalog, if it is there.

    An absent schema is a warning rather than a failure: the container mounts the catalog
    directory, so the schema is normally present, but refusing to start because a validation aid is
    missing would turn a lint into an outage.
    """
    schema_path = path.with_name(SCHEMA_FILENAME)
    if not schema_path.is_file():
        logger.warning("catalog_schema_missing", path=str(schema_path))
        return None
    loaded: dict[str, Any] = json.loads(schema_path.read_text(encoding="utf-8"))
    return loaded


def load_document(path: Path) -> dict[str, Any]:
    """Read and validate the catalog file. Raises ``CatalogError`` on any problem."""
    if not path.is_file():
        raise CatalogError(f"catalog not found at {path}. Set CATALOG_PATH or check the mount.")

    try:
        # safe_load, never load: the catalog is a data file, and full YAML can construct arbitrary
        # Python objects.
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise CatalogError(f"{path} is not valid YAML: {exc}") from exc

    if not isinstance(document, dict):
        raise CatalogError(f"{path} does not contain a mapping")

    schema = _schema_for(path)
    if schema is not None:
        try:
            jsonschema.validate(document, schema)
        except jsonschema.ValidationError as exc:
            location = "/".join(str(part) for part in exc.absolute_path) or "(root)"
            raise CatalogError(f"{path} fails its schema at {location}: {exc.message}") from exc

    services = document.get("services") or []
    if not services:
        raise CatalogError(f"{path} declares no services")
    return document


# ---------------------------------------------------------------------------
# The service
# ---------------------------------------------------------------------------


class Catalog:
    """A loaded catalog, reloaded when the file changes on disk.

    Reloading on mtime rather than on a restart is deliberate: adding a service is a routine
    operation during a demo, and requiring a container restart would mean the catalog and the
    running system disagree for as long as it takes someone to notice.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._services: dict[str, CatalogService] = {}
        self._loaded_mtime: float | None = None
        self.reload()

    @property
    def path(self) -> Path:
        return self._path

    def reload(self) -> None:
        """Read the file now, whatever its mtime."""
        document = load_document(self._path)
        services = {
            entry["name"]: CatalogService.from_mapping(entry) for entry in document["services"]
        }
        with self._lock:
            self._services = services
            self._loaded_mtime = self._path.stat().st_mtime
        logger.info("catalog_loaded", path=str(self._path), services=len(services))

    def _refresh_if_changed(self) -> None:
        try:
            mtime = self._path.stat().st_mtime
        except OSError:
            # The file went away after a successful load. Keep serving what we have: the previously
            # validated copy is better than failing every request until someone restores it.
            logger.warning("catalog_stat_failed", path=str(self._path))
            return
        if mtime == self._loaded_mtime:
            return
        try:
            self.reload()
        except CatalogError as exc:
            # A broken edit must not take the API down. The last good copy stays in use and the
            # problem is logged loudly, which is what an operator can act on.
            logger.error("catalog_reload_failed", path=str(self._path), error=str(exc))

    # --- Lookups ----------------------------------------------------------

    def services(self) -> tuple[CatalogService, ...]:
        self._refresh_if_changed()
        with self._lock:
            return tuple(self._services.values())

    def get(self, name: str) -> CatalogService | None:
        """One service by name, or None if the catalog does not declare it."""
        self._refresh_if_changed()
        with self._lock:
            return self._services.get(name)

    def require(self, name: str) -> CatalogService:
        """One service by name, raising ``CatalogError`` when absent.

        For callers that have already validated the name and want the failure to be loud.
        """
        service = self.get(name)
        if service is None:
            raise CatalogError(f"no service named {name!r} in {self._path}")
        return service

    # --- Enums for the intent schema (4.5.2) ------------------------------

    def service_names(self) -> tuple[str, ...]:
        return tuple(service.name for service in self.services())

    def suite_names(self) -> tuple[str, ...]:
        """Every suite name across the catalog, as 4.5.2's ``test_suite`` enum requires.

        A union rather than per-service, because the enum is built before the service is known.
        That a suite exists somewhere does not mean it belongs to the chosen service, which is why
        4.5.3 checks the pairing in code afterwards.
        """
        names = {suite.name for service in self.services() for suite in service.test_suites}
        return tuple(sorted(names))

    def environment_names(self) -> tuple[str, ...]:
        names = {
            environment
            for service in self.services()
            for environment in service.allowed_environments
        }
        return tuple(sorted(names))

    def extra_stage_names(self) -> tuple[str, ...]:
        """The extra stages actually configured, within 4.5.2's fixed enum and in its order."""
        configured = {stage for service in self.services() for stage in service.extra_stages}
        return tuple(stage for stage in EXTRA_STAGES if stage in configured)
