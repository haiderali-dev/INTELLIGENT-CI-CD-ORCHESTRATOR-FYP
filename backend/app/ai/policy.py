"""``PolicyService``: BUILD_PROMPT 4.5.5, as code.

================================  ============  ================  ===================
Rule                              Developer     DevOps            Admin
================================  ============  ================  ===================
Deploy to staging                 Allowed       Allowed           Allowed
Deploy to production              Refused       Refused           Refused (disabled)
HIGH urgency                      Justified;    Allowed           Allowed
                                  quota a day,
                                  then MEDIUM
Custom shell steps                Refused       Allowed, flagged  Allowed, flagged
New request while its chain runs  Refused,      Same              May cancel it first
                                  linked
================================  ============  ================  ===================

"Every denial returns a reason the UI can show and an audit entry."

The service is pure: everything it needs arrives in ``PolicyContext`` -- how many HIGH requests
the user has made today, whether a chain is running for the service -- and the audit entries come
back in the decision for the caller to write. That is what makes 4.5.5's table testable as a table:
every role against every action, environment and urgency, with no database in sight.

Decisions are taken by the code, never by the model (4.5.3 step 3). A model can be talked into
anything; a lookup on a role cannot.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final

from app.ai.intent import Action, Intent, TargetEnvironment, Urgency
from app.core.errors import ErrorCode
from app.db.models import Role

# Actions that put something on an environment.
DEPLOY_ACTIONS: Final = frozenset({Action.DEPLOY, Action.BUILD_TEST_DEPLOY})

# The audit action every HIGH request writes. The quota counts only those marked granted.
HIGH_URGENCY_AUDIT_ACTION: Final = "intent.high_urgency"

# Actions that start work for a service, and so can collide with a chain already running for it.
STARTS_WORK: Final = frozenset(
    {Action.BUILD, Action.TEST, Action.DEPLOY, Action.BUILD_TEST_DEPLOY, Action.RERUN}
)


class PolicyOutcome(StrEnum):
    ALLOW = "ALLOW"
    #: Allowed, but not as asked -- a HIGH request downgraded to MEDIUM.
    ALLOW_WITH_CHANGES = "ALLOW_WITH_CHANGES"
    #: Not refused, but cannot proceed until the user gives a reason.
    NEEDS_JUSTIFICATION = "NEEDS_JUSTIFICATION"
    REFUSE = "REFUSE"


# Severity order for combining several rules' outcomes: the strictest wins.
_SEVERITY: Final = {
    PolicyOutcome.ALLOW: 0,
    PolicyOutcome.ALLOW_WITH_CHANGES: 1,
    PolicyOutcome.NEEDS_JUSTIFICATION: 2,
    PolicyOutcome.REFUSE: 3,
}


@dataclass(frozen=True)
class RunningChain:
    """A chain already running for the service the request names."""

    service: str
    chain_id: str
    started_by: str | None = None


@dataclass(frozen=True)
class PolicyContext:
    role: Role
    high_urgency_used_today: int = 0
    high_urgency_quota: int = 3
    running_chain: RunningChain | None = None
    has_custom_steps: bool = False


@dataclass(frozen=True)
class PolicyReason:
    """Something the UI can show: a stable code to switch on and a sentence to display."""

    code: ErrorCode
    message: str


@dataclass(frozen=True)
class AuditEvent:
    """An ``audit_logs`` row for the caller to write."""

    action: str
    target: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PolicyDecision:
    outcome: PolicyOutcome
    #: The intent to proceed with -- the one asked for, or a modified one (a downgrade).
    intent: Intent
    reasons: tuple[PolicyReason, ...] = ()
    #: Shown in the preview without blocking anything, such as custom shell steps.
    flags: tuple[str, ...] = ()
    audit: tuple[AuditEvent, ...] = ()
    running_chain: RunningChain | None = None
    #: An Admin may cancel the running chain and go ahead (4.5.5); the UI offers it when true.
    can_cancel_running: bool = False

    @property
    def allowed(self) -> bool:
        return self.outcome in (PolicyOutcome.ALLOW, PolicyOutcome.ALLOW_WITH_CHANGES)


class PolicyService:
    def evaluate(self, intent: Intent, context: PolicyContext) -> PolicyDecision:
        """Apply every rule and combine them; the strictest outcome wins.

        Rules are evaluated even after one refuses, so the user sees every reason at once rather
        than fixing one problem only to meet the next.
        """
        outcome = PolicyOutcome.ALLOW
        current = intent
        reasons: list[PolicyReason] = []
        flags: list[str] = []
        audit: list[AuditEvent] = []
        running: RunningChain | None = None
        can_cancel = False
        target = intent.service or "(no service)"

        def escalate(to: PolicyOutcome) -> None:
            nonlocal outcome
            if _SEVERITY[to] > _SEVERITY[outcome]:
                outcome = to

        # --- Production: refused for everyone (rule 1.5, 4.5.5) ------------------
        if intent.action in DEPLOY_ACTIONS and intent.environment is TargetEnvironment.PRODUCTION:
            escalate(PolicyOutcome.REFUSE)
            reasons.append(
                PolicyReason(
                    ErrorCode.PRODUCTION_REFUSED,
                    "This project deploys to staging only. Production deployment is disabled "
                    "for every role, including administrators.",
                )
            )
            audit.append(
                AuditEvent(
                    "policy.production_refused",
                    target,
                    {"role": context.role.value, "action": intent.action.value},
                )
            )

        # --- A chain already running for this service ---------------------------
        if (
            intent.action in STARTS_WORK
            and context.running_chain is not None
            and context.running_chain.service == intent.service
        ):
            running = context.running_chain
            escalate(PolicyOutcome.REFUSE)
            if context.role is Role.ADMIN:
                can_cancel = True
                message = (
                    f"A chain is already running for {intent.service}. As an administrator you "
                    "may cancel it and then go ahead."
                )
            else:
                message = (
                    f"A chain is already running for {intent.service}. Wait for it to finish, "
                    "or ask an administrator to cancel it."
                )
            reasons.append(PolicyReason(ErrorCode.CHAIN_ALREADY_RUNNING, message))
            audit.append(
                AuditEvent(
                    "policy.chain_running",
                    target,
                    {"role": context.role.value, "chain_id": running.chain_id},
                )
            )

        # --- Custom shell steps -------------------------------------------------
        if context.has_custom_steps:
            if context.role is Role.DEVELOPER:
                escalate(PolicyOutcome.REFUSE)
                reasons.append(
                    PolicyReason(
                        ErrorCode.CUSTOM_STEPS_REFUSED,
                        "Custom shell steps need the DevOps role. Every standard stage's command "
                        "comes from the service catalog.",
                    )
                )
                audit.append(
                    AuditEvent("policy.custom_steps_refused", target, {"role": context.role.value})
                )
            else:
                # Allowed, but never invisibly: the preview shows it.
                flags.append("custom_steps")

        # --- HIGH urgency: DevOps and Admin are simply allowed ---------------------
        if (
            intent.urgency is Urgency.HIGH
            and intent.action is not Action.UNSUPPORTED
            and context.role is Role.DEVELOPER
        ):
            if context.high_urgency_used_today >= context.high_urgency_quota:
                # Downgraded, not refused: the work still happens, at the priority the
                # quota allows, and the user is told why.
                current = current.with_changes(urgency=Urgency.MEDIUM)
                escalate(PolicyOutcome.ALLOW_WITH_CHANGES)
                reasons.append(
                    PolicyReason(
                        ErrorCode.QUOTA_EXCEEDED,
                        f"You have used today's {context.high_urgency_quota} HIGH-urgency "
                        "requests, so this one runs at MEDIUM. DevOps can raise it if it is "
                        "genuinely urgent.",
                    )
                )
                audit.append(
                    AuditEvent(
                        "policy.urgency_downgraded",
                        target,
                        {
                            "used_today": context.high_urgency_used_today,
                            "quota": context.high_urgency_quota,
                        },
                    )
                )
            elif not intent.justification:
                escalate(PolicyOutcome.NEEDS_JUSTIFICATION)
                reasons.append(
                    PolicyReason(
                        ErrorCode.JUSTIFICATION_REQUIRED,
                        "HIGH urgency jumps the queue for everyone, so it needs a reason. "
                        "Why is this urgent?",
                    )
                )
                audit.append(
                    AuditEvent(
                        "policy.justification_required", target, {"role": context.role.value}
                    )
                )

        # 4.4.3 requires an audit entry for every HIGH-urgency request, granted or not -- so it is
        # written after every rule has run, and records which. The daily quota counts only
        # entries with ``granted: true``: counting every request would let a developer who asks
        # five times without a reason use up the quota without ever getting HIGH once.
        if intent.urgency is Urgency.HIGH and intent.action is not Action.UNSUPPORTED:
            granted = (
                outcome in (PolicyOutcome.ALLOW, PolicyOutcome.ALLOW_WITH_CHANGES)
                and current.urgency is Urgency.HIGH
            )
            audit.append(
                AuditEvent(
                    HIGH_URGENCY_AUDIT_ACTION,
                    target,
                    {
                        "role": context.role.value,
                        "granted": granted,
                        "justification": intent.justification,
                    },
                )
            )

        return PolicyDecision(
            outcome=outcome,
            intent=current,
            reasons=tuple(reasons),
            flags=tuple(flags),
            audit=tuple(audit),
            running_chain=running,
            can_cancel_running=can_cancel,
        )
