"""The service catalog over HTTP.

BUILD_PROMPT 4.4.4: ``GET /api/services``, ``GET /api/services/{name}/branches``, plus admin
resync.

``catalog/services.yaml`` stays the source of truth (4.6.1). These endpoints read it, and the
``services`` table is a mirror the API joins against — so the resync endpoint pushes the file into
the table and never the other way round. There is no endpoint to edit a service: a command the
model may run must be reviewable in version control, and an API that could rewrite the catalog at
runtime would move the only source of shell commands out of the repository.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser, CurrentUser
from app.core.errors import ErrorCode, not_found, unavailable
from app.core.logging import get_logger
from app.core.settings import Settings
from app.db.models import AuditLog
from app.db.seed import seed_catalog
from app.db.session import get_db
from app.services.catalog import Catalog, CatalogService
from app.services.dependencies import get_catalog, get_git_client, get_settings_dep
from app.services.git import GitClient, GitError

logger = get_logger(__name__)
router = APIRouter(tags=["services"])


class TestSuiteResponse(BaseModel):
    name: str
    approx_seconds: int


class ServiceResponse(BaseModel):
    """What the UI needs to offer a service as a choice.

    The commands are deliberately **not** included. They are the one thing in the catalog that is
    security-relevant, nothing in the UI runs them, and an endpoint that hands them out widens the
    blast radius of a stolen read-only token for no feature.
    """

    name: str
    repo: str
    default_branch: str
    agent_label: str
    test_suites: list[TestSuiteResponse]
    allowed_environments: list[str]
    extra_stages: list[str]

    @classmethod
    def of(cls, service: CatalogService) -> ServiceResponse:
        return cls(
            name=service.name,
            repo=service.repo,
            default_branch=service.default_branch,
            agent_label=service.agent_label,
            test_suites=[
                TestSuiteResponse(name=suite.name, approx_seconds=suite.approx_seconds)
                for suite in service.test_suites
            ],
            allowed_environments=list(service.allowed_environments),
            extra_stages=sorted(service.extra_stages),
        )


class ServiceListResponse(BaseModel):
    items: list[ServiceResponse]
    # The enums 4.5.2 builds the intent schema from, so the frontend's pickers and the model's
    # schema cannot drift apart.
    suite_names: list[str]
    environments: list[str]
    extra_stages: list[str]


class BranchListResponse(BaseModel):
    service: str
    default_branch: str
    branches: list[str]
    available: bool
    unavailable_reason: str | None = None


class ResyncResponse(BaseModel):
    created: int
    updated: int


@router.get("/services", response_model=ServiceListResponse, summary="The service catalog")
async def list_services(
    user: CurrentUser,
    catalog: Annotated[Catalog, Depends(get_catalog)],
) -> ServiceListResponse:
    return ServiceListResponse(
        items=[ServiceResponse.of(service) for service in catalog.services()],
        suite_names=list(catalog.suite_names()),
        environments=list(catalog.environment_names()),
        extra_stages=list(catalog.extra_stage_names()),
    )


@router.get(
    "/services/{name}/branches",
    response_model=BranchListResponse,
    summary="Branches on a service's repository",
)
async def list_branches(
    name: str,
    user: CurrentUser,
    catalog: Annotated[Catalog, Depends(get_catalog)],
    git: Annotated[GitClient, Depends(get_git_client)],
) -> BranchListResponse:
    """Live branches, so the UI only offers refs that exist.

    An unreachable repository answers 200 with ``available: false``. The two sample repositories
    are not pushed yet, and a picker that errors is less useful than one that says it could not
    reach the remote and falls back to the default branch.
    """
    service = catalog.get(name)
    if service is None:
        raise not_found(ErrorCode.SERVICE_NOT_FOUND, f"No service named {name!r}.", service=name)

    try:
        branches = await git.list_branches(service.repo)
    except GitError as exc:
        logger.info("branches_unavailable", service=name, error=str(exc)[:200])
        return BranchListResponse(
            service=service.name,
            default_branch=service.default_branch,
            branches=[],
            available=False,
            unavailable_reason="The repository could not be reached.",
        )

    return BranchListResponse(
        service=service.name,
        default_branch=service.default_branch,
        branches=list(branches),
        available=True,
    )


@router.post(
    "/services/resync",
    response_model=ResyncResponse,
    summary="Mirror the catalog file into the database",
)
async def resync_catalog(
    user: AdminUser,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    catalog: Annotated[Catalog, Depends(get_catalog)],
) -> ResyncResponse:
    """Re-read the catalog file and update the ``services`` table.

    One direction only, file to table. Rows for services no longer in the file are left alone
    rather than deleted, because ``jobs.service_id`` references them and deleting one would orphan
    the history of every job that ever built that service.
    """
    try:
        catalog.reload()
    except Exception as exc:
        raise unavailable(
            ErrorCode.VALIDATION_FAILED, f"The catalog file could not be loaded: {exc}"
        ) from exc

    created, updated = await seed_catalog(session, settings)
    session.add(
        AuditLog(
            actor_id=user.id,
            action="catalog.resynced",
            target=str(catalog.path.name),
            details={"created": created, "updated": updated},
        )
    )
    logger.info("catalog_resynced", created=created, updated=updated, actor=user.id)
    return ResyncResponse(created=created, updated=updated)
