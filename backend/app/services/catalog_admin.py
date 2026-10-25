"""Admin-authored service registration; YAML remains the catalog's source of truth."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError, ErrorCode, conflict, unavailable
from app.core.settings import Settings
from app.db.models import AuditLog, User
from app.db.seed import seed_catalog
from app.services.catalog import Catalog, CatalogError, CatalogService, DuplicateServiceError
from app.services.git import is_safe_ref

Identifier = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{0,63}$")]
ShellCommand = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=512, pattern=r"^[^;&|`$><\r\n\x00]+$"
    ),
]
ExtraStage = Literal["lint", "security_scan", "integration_tests", "smoke_test"]


class CatalogInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class NewTestSuite(CatalogInput):
    name: Identifier
    command: ShellCommand
    approx_seconds: int = Field(ge=1, le=3600)


class NewDeployTarget(CatalogInput):
    command: ShellCommand
    url: str = Field(pattern=r"^https?://[^\s]+$", max_length=2048)


class NewDeploy(CatalogInput):
    staging: NewDeployTarget


class CreateServiceRequest(CatalogInput):
    name: Identifier
    repo: str = Field(pattern=r"^(https://|git@)[^\s]+\.git$", max_length=2048)
    default_branch: str = Field(min_length=1, max_length=255)
    agent_label: str = Field(min_length=1, max_length=255)
    build_command: ShellCommand
    test_suites: list[NewTestSuite] = Field(min_length=1, max_length=30)
    deploy: NewDeploy
    allowed_environments: list[Literal["staging"]] = Field(min_length=1, max_length=1)
    extra_stages: dict[ExtraStage, ShellCommand] = Field(default_factory=dict)

    @field_validator("default_branch")
    @classmethod
    def safe_branch(cls, value: str) -> str:
        if not is_safe_ref(value):
            raise ValueError("Enter a branch name such as main or release/v1.")
        return value

    @field_validator("test_suites")
    @classmethod
    def unique_suites(cls, value: list[NewTestSuite]) -> list[NewTestSuite]:
        if len({suite.name for suite in value}) != len(value):
            raise ValueError("Each test suite needs a unique name.")
        return value


async def resync_services(
    session: AsyncSession, *, user: User, catalog: Catalog, settings: Settings
) -> tuple[int, int]:
    """Serialize resync with registration so their database mirrors cannot race."""
    async with catalog.write_lock:
        try:
            catalog.reload()
        except (CatalogError, OSError) as exc:
            raise unavailable(
                ErrorCode.VALIDATION_FAILED,
                "The catalog file could not be loaded. Check it and retry.",
            ) from exc
        created, updated = await seed_catalog(session, settings)
        session.add(
            AuditLog(
                actor_id=user.id,
                action="catalog.resynced",
                target=catalog.path.name,
                details={"created": created, "updated": updated},
            )
        )
        await session.commit()
        return created, updated


async def create_service(
    session: AsyncSession,
    *,
    user: User,
    catalog: Catalog,
    settings: Settings,
    body: CreateServiceRequest,
) -> CatalogService:
    async with catalog.write_lock:
        try:
            with catalog.adding(body.model_dump()) as service:
                await seed_catalog(session, settings)
                session.add(
                    AuditLog(
                        actor_id=user.id,
                        action="catalog.service.created",
                        target=body.name,
                        details={"repo": body.repo, "default_branch": body.default_branch},
                    )
                )
                # Commit while the file can still be restored on failure, before HTTP success.
                await session.commit()
            return service
        except DuplicateServiceError as exc:
            raise conflict(
                ErrorCode.VALIDATION_FAILED, str(exc), fields={"name": str(exc)}
            ) from exc
        except CatalogError as exc:
            raise ApiError(ErrorCode.VALIDATION_FAILED, str(exc), status_code=422) from exc
        except OSError as exc:
            raise unavailable(
                ErrorCode.VALIDATION_FAILED,
                "The catalog could not be saved. "
                "Check that its directory is writable, then try again.",
            ) from exc
