"""The service catalog.

The catalog is the only place shell commands come from (BUILD_PROMPT 4.6.1), so the tests that
matter here are the ones about what it refuses: a document that fails its schema, a command with a
shell metacharacter, and an environment that is not on the service's allow-list.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import yaml

from app.core.settings import Settings
from app.services.catalog import (
    EXTRA_STAGES,
    Catalog,
    CatalogError,
    CatalogService,
    DeployTarget,
    catalog_path,
    load_document,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_CATALOG = REPO_ROOT / "catalog" / "services.yaml"
REAL_SCHEMA = REPO_ROOT / "catalog" / "services.schema.json"


def minimal_service(**overrides: object) -> dict[str, object]:
    service: dict[str, object] = {
        "name": "payment-service",
        "repo": "https://github.com/example/payment-service.git",
        "default_branch": "main",
        "agent_label": "linux",
        "build_command": "./scripts/build.sh",
        "test_suites": [{"name": "unit", "command": "./scripts/test.sh unit", "approx_seconds": 8}],
        "deploy": {"staging": {"command": "./deploy.sh staging", "url": "http://localhost:9001"}},
        "allowed_environments": ["staging"],
    }
    service.update(overrides)
    return service


def write_catalog(directory: Path, *services: dict[str, object]) -> Path:
    """Write a catalog plus the real schema beside it, as the repository lays them out."""
    path = directory / "services.yaml"
    path.write_text(yaml.safe_dump({"version": 1, "services": list(services)}), encoding="utf-8")
    (directory / "services.schema.json").write_text(
        REAL_SCHEMA.read_text(encoding="utf-8"), encoding="utf-8"
    )
    return path


# ---------------------------------------------------------------------------
# The repository's own catalog
# ---------------------------------------------------------------------------


def test_the_shipped_catalog_loads_and_validates() -> None:
    """The file the stack actually mounts must satisfy its own schema."""
    document = load_document(REAL_CATALOG)

    assert document["version"] == 1
    assert len(document["services"]) >= 2


def test_catalog_path_finds_the_file_from_the_backend_directory(settings: Settings) -> None:
    """The backend runs from backend/ locally and /app in the container; both must resolve."""
    resolved = catalog_path(settings)

    assert resolved.is_file()
    assert resolved.name == "services.yaml"


def test_no_service_allows_production() -> None:
    """Rule 1.5: production deploys are refused by policy, starting with the catalog."""
    catalog = Catalog(REAL_CATALOG)

    for service in catalog.services():
        assert "production" not in service.allowed_environments
        assert "production" not in service.deploy


# ---------------------------------------------------------------------------
# What the loader refuses
# ---------------------------------------------------------------------------


def test_a_missing_catalog_names_the_path_it_looked_for(tmp_path: Path) -> None:
    with pytest.raises(CatalogError) as exc:
        load_document(tmp_path / "absent.yaml")

    assert "absent.yaml" in str(exc.value)


def test_malformed_yaml_is_reported_as_such(tmp_path: Path) -> None:
    path = tmp_path / "services.yaml"
    path.write_text("version: 1\nservices: [\n", encoding="utf-8")

    with pytest.raises(CatalogError, match="not valid YAML"):
        load_document(path)


def test_a_catalog_with_no_services_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "services.yaml"
    path.write_text(yaml.safe_dump({"version": 1, "services": []}), encoding="utf-8")

    with pytest.raises(CatalogError):
        load_document(path)


def test_a_command_with_a_shell_metacharacter_fails_the_schema(tmp_path: Path) -> None:
    """The catalog is the trusted source of commands, so it is checked rather than trusted."""
    path = write_catalog(tmp_path, minimal_service(build_command="./build.sh; rm -rf /"))

    with pytest.raises(CatalogError) as exc:
        load_document(path)

    assert "schema" in str(exc.value)


def test_production_in_allowed_environments_fails_the_schema(tmp_path: Path) -> None:
    """Enabling production must take more than editing one line of YAML."""
    path = write_catalog(tmp_path, minimal_service(allowed_environments=["staging", "production"]))

    with pytest.raises(CatalogError):
        load_document(path)


def test_an_unknown_extra_stage_fails_the_schema(tmp_path: Path) -> None:
    """4.5.2 fixes the extra_stages enum; anything else could never be rendered."""
    path = write_catalog(tmp_path, minimal_service(extra_stages={"deploy_prod": "./x.sh"}))

    with pytest.raises(CatalogError):
        load_document(path)


def test_the_schema_error_names_where_the_problem_is(tmp_path: Path) -> None:
    """An error saying only "invalid" makes someone bisect the file by hand."""
    path = write_catalog(tmp_path, minimal_service(name="Payment_Service"))

    with pytest.raises(CatalogError) as exc:
        load_document(path)

    assert "services/0/name" in str(exc.value)


def test_a_missing_schema_is_a_warning_not_a_failure(tmp_path: Path) -> None:
    """The catalog still loads without its schema: a missing lint should not be an outage."""
    path = tmp_path / "services.yaml"
    path.write_text(
        yaml.safe_dump({"version": 1, "services": [minimal_service()]}), encoding="utf-8"
    )

    document = load_document(path)

    assert document["services"][0]["name"] == "payment-service"


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------


def test_an_unknown_service_is_none_rather_than_a_default() -> None:
    """A default here would mean running a command nobody wrote for a service nobody named."""
    catalog = Catalog(REAL_CATALOG)

    assert catalog.get("no-such-service") is None
    with pytest.raises(CatalogError, match="no service named"):
        catalog.require("no-such-service")


def test_a_suite_is_looked_up_on_its_own_service(tmp_path: Path) -> None:
    """4.5.3: the suite must belong to *that* service, not merely exist somewhere."""
    path = write_catalog(
        tmp_path,
        minimal_service(),
        minimal_service(
            name="auth-service",
            repo="https://github.com/example/auth-service.git",
            test_suites=[
                {"name": "unit", "command": "./scripts/test.sh unit", "approx_seconds": 6}
            ],
        ),
    )
    catalog = Catalog(path)

    payment = catalog.require("payment-service")
    auth = catalog.require("auth-service")

    assert payment.suite("unit") is not None
    # "integration" is a real suite name in the union enum, but not on auth-service.
    assert auth.suite("integration") is None


def test_a_deploy_target_outside_the_allow_list_does_not_resolve(tmp_path: Path) -> None:
    """Otherwise the allow-list would be advice rather than a control."""
    path = write_catalog(
        tmp_path,
        minimal_service(
            deploy={"staging": {"command": "./deploy.sh staging", "url": "http://localhost:9001"}},
            allowed_environments=["staging"],
        ),
    )
    service = Catalog(path).require("payment-service")

    assert service.deploy_target("staging") is not None
    assert service.deploy_target("production") is None
    assert not service.allows("production")


def test_a_deploy_target_present_but_not_allowed_is_refused() -> None:
    """A contradiction between deploy and allowed_environments resolves against running it."""
    service = CatalogService(
        name="s",
        repo="https://github.com/example/s.git",
        default_branch="main",
        agent_label="linux",
        build_command="./b.sh",
        test_suites=(),
        deploy={"staging": DeployTarget(command="./d.sh", url="http://x")},
        allowed_environments=(),
    )

    assert service.deploy_target("staging") is None


# ---------------------------------------------------------------------------
# Enums for the intent schema (4.5.2)
# ---------------------------------------------------------------------------


def test_the_enums_are_built_from_the_file() -> None:
    """4.5.2 builds the intent schema's enums per request, so they must come from the catalog."""
    catalog = Catalog(REAL_CATALOG)

    assert "payment-service" in catalog.service_names()
    assert "unit" in catalog.suite_names()
    assert catalog.environment_names() == ("staging",)
    assert set(catalog.extra_stage_names()) <= set(EXTRA_STAGES)


def test_extra_stage_names_keep_the_specified_order() -> None:
    """4.5.2 lists the enum in a fixed order; a set would make it vary between runs."""
    catalog = Catalog(REAL_CATALOG)

    names = catalog.extra_stage_names()

    assert list(names) == [stage for stage in EXTRA_STAGES if stage in names]


def test_suite_names_are_the_union_across_services() -> None:
    catalog = Catalog(REAL_CATALOG)

    per_service = {suite.name for s in catalog.services() for suite in s.test_suites}

    assert set(catalog.suite_names()) == per_service


# ---------------------------------------------------------------------------
# Reloading
# ---------------------------------------------------------------------------


def test_editing_the_file_is_picked_up_without_a_restart(tmp_path: Path) -> None:
    """Adding a service during a demo should not need the container restarted."""
    path = write_catalog(tmp_path, minimal_service())
    catalog = Catalog(path)
    assert catalog.service_names() == ("payment-service",)

    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["services"].append(
        minimal_service(name="auth-service", repo="https://github.com/example/auth-service.git")
    )
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    # mtime has one-second resolution on some filesystems, so make the change unambiguous.
    stat = path.stat()
    os.utime(path, (stat.st_atime, stat.st_mtime + 10))

    assert set(catalog.service_names()) == {"payment-service", "auth-service"}


def test_a_broken_edit_keeps_the_last_good_copy(tmp_path: Path) -> None:
    """A typo in the catalog must not take the API down mid-demo."""
    path = write_catalog(tmp_path, minimal_service())
    catalog = Catalog(path)

    path.write_text("version: 1\nservices: [\n", encoding="utf-8")
    import os

    stat = path.stat()
    os.utime(path, (stat.st_atime, stat.st_mtime + 10))

    # Still serving the copy that validated.
    assert catalog.service_names() == ("payment-service",)


def test_a_deleted_file_keeps_the_last_good_copy(tmp_path: Path) -> None:
    path = write_catalog(tmp_path, minimal_service())
    catalog = Catalog(path)

    path.unlink()

    assert catalog.service_names() == ("payment-service",)


def test_the_schema_file_itself_is_valid_json() -> None:
    """A schema that does not parse would silently disable every check above."""
    schema = json.loads(REAL_SCHEMA.read_text(encoding="utf-8"))

    assert schema["$schema"].startswith("https://json-schema.org/")
