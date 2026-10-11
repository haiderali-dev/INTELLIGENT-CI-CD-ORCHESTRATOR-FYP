"""Admin: users, the audit log and the policy settings in force.

BUILD_PROMPT 4.4.4 groups these under "Analytics and admin". Every endpoint here needs the Admin
role, and every change writes an audit entry — 4.4.3 requires one for "admin changes", and an
admin surface whose own use is unaudited is the one place where that matters most.

**Policy settings are read-only.** 4.4.3 lists fourteen tables and none holds policy, so there is
nowhere to persist an override. The rules in 4.5.5 are code and the one number
(``HIGH_URGENCY_DAILY_QUOTA``) is configuration, so this endpoint reports what is in force and does
not pretend to change it. A writable endpoint would need a table the specification does not have;
see docs/decisions.md D-032.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser
from app.core.errors import ErrorCode, conflict, not_found
from app.core.logging import get_logger
from app.core.security import hash_password
from app.core.settings import Settings
from app.db.models import AuditLog, Role, User
from app.db.session import get_db
from app.services.dependencies import get_settings_dep
from app.services.runs import MAX_PAGE_SIZE, clamp_page

logger = get_logger(__name__)
router = APIRouter(tags=["admin"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class AdminUserResponse(BaseModel):
    id: str
    email: str
    role: Role
    active: bool
    created_at: datetime

    @classmethod
    def of(cls, user: User) -> AdminUserResponse:
        return cls(
            id=user.id,
            email=user.email,
            role=Role(user.role),
            active=user.active,
            created_at=user.created_at,
        )


class UserPage(BaseModel):
    items: list[AdminUserResponse]
    total: int
    limit: int
    offset: int


class CreateUserRequest(BaseModel):
    email: EmailStr
    # A floor here, unlike at sign-in: this is the moment a password is chosen, so a weak one can
    # still be refused without telling an attacker anything about an existing account.
    password: str = Field(min_length=12, max_length=256)
    role: Role = Role.DEVELOPER


class UpdateUserRequest(BaseModel):
    role: Role | None = None
    active: bool | None = None


class AuditEntryResponse(BaseModel):
    id: str
    actor_id: str | None
    actor_email: str | None
    action: str
    target: str
    details: dict[str, Any]
    created_at: datetime


class AuditPage(BaseModel):
    items: list[AuditEntryResponse]
    total: int
    limit: int
    offset: int


class PolicyRule(BaseModel):
    rule: str
    developer: str
    devops: str
    admin: str


class PolicyResponse(BaseModel):
    """4.5.5's table, plus the configured quota, as the UI shows it on the Admin page."""

    high_urgency_daily_quota: int
    production_enabled: bool = Field(
        default=False, description="Always false; refused by policy (rule 1.5)"
    )
    rules: list[PolicyRule]
    editable: bool = Field(
        default=False,
        description="False: 4.4.3 has no table for policy, so these are code and configuration",
    )


POLICY_RULES: tuple[PolicyRule, ...] = (
    PolicyRule(rule="Deploy to staging", developer="Allowed", devops="Allowed", admin="Allowed"),
    PolicyRule(
        rule="Deploy to production",
        developer="Refused",
        devops="Refused",
        admin="Refused (disabled for this project)",
    ),
    PolicyRule(
        rule="HIGH urgency",
        developer="Needs a justification; quota per day, then downgraded to MEDIUM",
        devops="Allowed",
        admin="Allowed",
    ),
    PolicyRule(
        rule="Custom shell steps",
        developer="Refused",
        devops="Allowed, flagged in the preview",
        admin="Allowed, flagged in the preview",
    ),
    PolicyRule(
        rule="New request while the same service's chain is running",
        developer="Refused, with the running chain linked",
        devops="Same",
        admin="May cancel the running chain first",
    ),
)


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


@router.get("/admin/users", response_model=UserPage, summary="All users")
async def list_users(
    admin: AdminUser,
    session: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int | None, Query(ge=1, le=MAX_PAGE_SIZE)] = None,
    offset: Annotated[int | None, Query(ge=0)] = None,
) -> UserPage:
    resolved_limit, resolved_offset = clamp_page(limit, offset)
    total = int(await session.scalar(select(func.count()).select_from(User)) or 0)
    rows = (
        await session.scalars(
            select(User).order_by(User.created_at).limit(resolved_limit).offset(resolved_offset)
        )
    ).all()
    return UserPage(
        items=[AdminUserResponse.of(user) for user in rows],
        total=total,
        limit=resolved_limit,
        offset=resolved_offset,
    )


@router.post(
    "/admin/users", response_model=AdminUserResponse, status_code=201, summary="Create a user"
)
async def create_user(
    payload: CreateUserRequest,
    admin: AdminUser,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> AdminUserResponse:
    email = payload.email.strip().lower()
    existing = await session.scalar(select(User).where(User.email == email))
    if existing is not None:
        raise conflict(
            ErrorCode.VALIDATION_FAILED, "A user with that email already exists.", email=email
        )

    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        role=payload.role.value,
        active=True,
    )
    session.add(user)
    await session.flush()

    session.add(
        AuditLog(
            actor_id=admin.id,
            action="admin.user.created",
            target=email,
            details={"role": payload.role.value},
        )
    )
    logger.info("admin_user_created", actor=admin.id, email=email, role=payload.role.value)
    return AdminUserResponse.of(user)


@router.patch(
    "/admin/users/{user_id}",
    response_model=AdminUserResponse,
    summary="Change a role or deactivate",
)
async def update_user(
    user_id: str,
    payload: UpdateUserRequest,
    admin: AdminUser,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> AdminUserResponse:
    """Change a user's role, or activate and deactivate them.

    An admin cannot deactivate or demote themselves. Not paternalism: the last admin locking
    themselves out leaves an installation with no way to grant the role back, and recovering from
    that means editing the database by hand.
    """
    user = await session.get(User, user_id)
    if user is None:
        raise not_found(ErrorCode.USER_NOT_FOUND, "No such user.", user_id=user_id)

    if user.id == admin.id and (payload.active is False or payload.role not in (None, Role.ADMIN)):
        raise conflict(
            ErrorCode.VALIDATION_FAILED,
            "You cannot remove your own administrator access. Ask another admin to do it.",
            user_id=user_id,
        )

    changed: dict[str, Any] = {}
    if payload.role is not None and payload.role.value != user.role:
        changed["role"] = {"from": user.role, "to": payload.role.value}
        user.role = payload.role.value
    if payload.active is not None and payload.active != user.active:
        changed["active"] = {"from": user.active, "to": payload.active}
        user.active = payload.active

    if changed:
        session.add(
            AuditLog(
                actor_id=admin.id,
                action="admin.user.updated",
                target=user.email,
                details=changed,
            )
        )
        logger.info("admin_user_updated", actor=admin.id, target=user.id, changed=list(changed))

    return AdminUserResponse.of(user)


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------


@router.get("/admin/audit", response_model=AuditPage, summary="The audit log")
async def list_audit(
    admin: AdminUser,
    session: Annotated[AsyncSession, Depends(get_db)],
    action: Annotated[str | None, Query(max_length=64)] = None,
    actor_id: Annotated[str | None, Query(max_length=64)] = None,
    limit: Annotated[int | None, Query(ge=1, le=MAX_PAGE_SIZE)] = None,
    offset: Annotated[int | None, Query(ge=0)] = None,
) -> AuditPage:
    """Newest first, filterable by action and actor.

    Read-only, and there is deliberately no delete: an append-only record that can be pruned
    through the API is not a record of anything.
    """
    resolved_limit, resolved_offset = clamp_page(limit, offset)

    statement = select(AuditLog)
    if action:
        statement = statement.where(AuditLog.action == action)
    if actor_id:
        statement = statement.where(AuditLog.actor_id == actor_id)

    total = int(
        await session.scalar(select(func.count()).select_from(statement.order_by(None).subquery()))
        or 0
    )
    rows = (
        await session.scalars(
            statement.order_by(AuditLog.created_at.desc())
            .limit(resolved_limit)
            .offset(resolved_offset)
        )
    ).all()

    emails = await _actor_emails(session, rows)
    return AuditPage(
        items=[
            AuditEntryResponse(
                id=entry.id,
                actor_id=entry.actor_id,
                actor_email=emails.get(entry.actor_id or ""),
                action=entry.action,
                target=entry.target,
                details=entry.details or {},
                created_at=entry.created_at,
            )
            for entry in rows
        ],
        total=total,
        limit=resolved_limit,
        offset=resolved_offset,
    )


async def _actor_emails(session: AsyncSession, entries: object) -> dict[str, str]:
    """Emails for a page of entries, in one query.

    An entry whose actor has since been deleted keeps a null ``actor_id`` (SET NULL), so the page
    shows the action without a name rather than hiding it.
    """
    ids = {entry.actor_id for entry in entries if entry.actor_id}  # type: ignore[attr-defined]
    if not ids:
        return {}
    rows = (await session.scalars(select(User).where(User.id.in_(ids)))).all()
    return {user.id: user.email for user in rows}


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------


@router.get("/admin/policy", response_model=PolicyResponse, summary="The policy in force")
async def get_policy(
    admin: AdminUser,
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> PolicyResponse:
    """4.5.5's rules and the configured quota.

    Reported rather than editable: see this module's docstring and D-032.
    """
    return PolicyResponse(
        high_urgency_daily_quota=settings.high_urgency_daily_quota,
        rules=list(POLICY_RULES),
    )


# Weakest first. `tests/test_admin.py` checks this against `role_allows`, so the Admin page's
# dropdown cannot disagree with what the guards actually enforce. A test rather than an assertion
# in the handler: it is a fact about the code, not about a request.
ROLE_ORDER: tuple[Role, ...] = (Role.DEVELOPER, Role.DEVOPS, Role.ADMIN)


@router.get("/admin/roles", response_model=list[str], summary="The role ordering")
async def get_roles(admin: AdminUser) -> list[str]:
    """The roles, weakest first, in the order the guards treat as cumulative."""
    return [role.value for role in ROLE_ORDER]
