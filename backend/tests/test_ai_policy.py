"""``PolicyService``, table-driven.

T4.6: "table-driven tests covering every role, action, environment and urgency combination."

Two layers. First, 4.5.5's rows written out as a table. Second, a sweep of the full product --
3 roles x 8 actions x 3 environments x 4 urgencies x 2 justification states, 576 cases -- that
checks invariants taken from 4.5.5's *wording*, not from the implementation. A sweep whose expected
values were computed by the same logic as the code would only prove the code agrees with itself.
"""

from __future__ import annotations

import itertools

import pytest

from app.ai.intent import Action, Intent, TargetEnvironment, Urgency
from app.ai.policy import (
    DEPLOY_ACTIONS,
    HIGH_URGENCY_AUDIT_ACTION,
    PolicyContext,
    PolicyOutcome,
    PolicyService,
    RunningChain,
)
from app.core.errors import ErrorCode
from app.db.models import Role

ROLES = tuple(Role)
ACTIONS = tuple(Action)
ENVIRONMENTS = (None, TargetEnvironment.STAGING, TargetEnvironment.PRODUCTION)
URGENCIES = (None, Urgency.LOW, Urgency.MEDIUM, Urgency.HIGH)
JUSTIFICATIONS = (None, "checkout is down for customers")

policy = PolicyService()


def intent_for(
    action: Action = Action.DEPLOY,
    *,
    environment: TargetEnvironment | None = TargetEnvironment.STAGING,
    urgency: Urgency | None = None,
    justification: str | None = None,
    service: str = "payment-service",
) -> Intent:
    return Intent(
        action=action,
        service=service,
        environment=environment,
        urgency=urgency,
        justification=justification,
        confidence=0.9,
    )


def codes(decision: object) -> set[ErrorCode]:
    return {reason.code for reason in decision.reasons}  # type: ignore[attr-defined]


def audit_actions(decision: object) -> list[str]:
    return [event.action for event in decision.audit]  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# 4.5.5, row by row
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("role", ROLES)
def test_deploy_to_staging_is_allowed_for_every_role(role: Role) -> None:
    decision = policy.evaluate(intent_for(), PolicyContext(role=role))

    assert decision.outcome is PolicyOutcome.ALLOW
    assert decision.reasons == ()


@pytest.mark.parametrize("role", ROLES)
def test_deploy_to_production_is_refused_for_every_role_including_admin(role: Role) -> None:
    """ "Refused (disabled for this project)" -- the Admin column too."""
    decision = policy.evaluate(
        intent_for(environment=TargetEnvironment.PRODUCTION), PolicyContext(role=role)
    )

    assert decision.outcome is PolicyOutcome.REFUSE
    assert codes(decision) == {ErrorCode.PRODUCTION_REFUSED}
    assert "policy.production_refused" in audit_actions(decision)


@pytest.mark.parametrize(
    ("role", "justification", "expected"),
    [
        (Role.DEVELOPER, None, PolicyOutcome.NEEDS_JUSTIFICATION),
        (Role.DEVELOPER, "checkout is down", PolicyOutcome.ALLOW),
        (Role.DEVOPS, None, PolicyOutcome.ALLOW),
        (Role.ADMIN, None, PolicyOutcome.ALLOW),
    ],
)
def test_high_urgency_needs_a_reason_only_from_a_developer(
    role: Role, justification: str | None, expected: PolicyOutcome
) -> None:
    decision = policy.evaluate(
        intent_for(urgency=Urgency.HIGH, justification=justification), PolicyContext(role=role)
    )

    assert decision.outcome is expected
    assert decision.intent.urgency is Urgency.HIGH


@pytest.mark.parametrize(
    ("used_today", "outcome", "urgency", "granted"),
    [
        (0, PolicyOutcome.ALLOW, Urgency.HIGH, True),
        (2, PolicyOutcome.ALLOW, Urgency.HIGH, True),
        (3, PolicyOutcome.ALLOW_WITH_CHANGES, Urgency.MEDIUM, False),
        (9, PolicyOutcome.ALLOW_WITH_CHANGES, Urgency.MEDIUM, False),
    ],
)
def test_a_developer_past_the_daily_quota_is_downgraded_to_medium_with_a_reason(
    used_today: int, outcome: PolicyOutcome, urgency: Urgency, granted: bool
) -> None:
    """ "HIGH_URGENCY_DAILY_QUOTA per day, then downgraded to MEDIUM with an explanation"."""
    decision = policy.evaluate(
        intent_for(urgency=Urgency.HIGH, justification="checkout is down"),
        PolicyContext(
            role=Role.DEVELOPER, high_urgency_used_today=used_today, high_urgency_quota=3
        ),
    )

    assert decision.outcome is outcome
    assert decision.intent.urgency is urgency
    high = [event for event in decision.audit if event.action == HIGH_URGENCY_AUDIT_ACTION]
    assert len(high) == 1
    assert high[0].details["granted"] is granted
    if not granted:
        assert codes(decision) == {ErrorCode.QUOTA_EXCEEDED}


def test_a_downgrade_does_not_need_a_justification_first() -> None:
    """Asking for a reason, only to then downgrade anyway, would waste a round trip."""
    decision = policy.evaluate(
        intent_for(urgency=Urgency.HIGH, justification=None),
        PolicyContext(role=Role.DEVELOPER, high_urgency_used_today=3, high_urgency_quota=3),
    )

    assert decision.outcome is PolicyOutcome.ALLOW_WITH_CHANGES
    assert ErrorCode.JUSTIFICATION_REQUIRED not in codes(decision)


def test_requests_without_a_reason_do_not_use_up_the_quota() -> None:
    """Counting every HIGH request would let five unjustified attempts spend the quota."""
    decision = policy.evaluate(
        intent_for(urgency=Urgency.HIGH, justification=None), PolicyContext(role=Role.DEVELOPER)
    )

    high = [event for event in decision.audit if event.action == HIGH_URGENCY_AUDIT_ACTION]
    assert high[0].details["granted"] is False


@pytest.mark.parametrize(
    ("role", "outcome", "flagged"),
    [
        (Role.DEVELOPER, PolicyOutcome.REFUSE, False),
        (Role.DEVOPS, PolicyOutcome.ALLOW, True),
        (Role.ADMIN, PolicyOutcome.ALLOW, True),
    ],
)
def test_custom_shell_steps(role: Role, outcome: PolicyOutcome, flagged: bool) -> None:
    """ "Refused" / "Allowed, flagged in the preview"."""
    decision = policy.evaluate(intent_for(), PolicyContext(role=role, has_custom_steps=True))

    assert decision.outcome is outcome
    assert ("custom_steps" in decision.flags) is flagged


@pytest.mark.parametrize(
    ("role", "can_cancel"),
    [(Role.DEVELOPER, False), (Role.DEVOPS, False), (Role.ADMIN, True)],
)
def test_a_running_chain_blocks_a_new_request_and_only_admin_may_cancel(
    role: Role, can_cancel: bool
) -> None:
    """ "Refused, with the running chain linked" / "Same" / "May cancel the running chain first"."""
    chain = RunningChain(service="payment-service", chain_id="chain-42")

    decision = policy.evaluate(intent_for(), PolicyContext(role=role, running_chain=chain))

    assert decision.outcome is PolicyOutcome.REFUSE
    assert codes(decision) == {ErrorCode.CHAIN_ALREADY_RUNNING}
    assert decision.running_chain == chain
    assert decision.can_cancel_running is can_cancel


def test_a_chain_for_another_service_does_not_block() -> None:
    chain = RunningChain(service="auth-service", chain_id="chain-7")

    decision = policy.evaluate(
        intent_for(service="payment-service"),
        PolicyContext(role=Role.DEVELOPER, running_chain=chain),
    )

    assert decision.outcome is PolicyOutcome.ALLOW


@pytest.mark.parametrize("action", [Action.STATUS, Action.CANCEL, Action.UNSUPPORTED])
def test_reading_or_stopping_runs_is_never_blocked_by_a_running_chain(action: Action) -> None:
    """Asking for status while a chain runs is the whole point of asking."""
    chain = RunningChain(service="payment-service", chain_id="chain-42")

    decision = policy.evaluate(
        intent_for(action, environment=None),
        PolicyContext(role=Role.DEVELOPER, running_chain=chain),
    )

    assert ErrorCode.CHAIN_ALREADY_RUNNING not in codes(decision)


def test_every_reason_is_reported_at_once() -> None:
    """Fixing one problem only to meet the next is a poor way to learn the rules."""
    chain = RunningChain(service="payment-service", chain_id="chain-42")

    decision = policy.evaluate(
        intent_for(environment=TargetEnvironment.PRODUCTION),
        PolicyContext(role=Role.DEVELOPER, running_chain=chain, has_custom_steps=True),
    )

    assert codes(decision) == {
        ErrorCode.PRODUCTION_REFUSED,
        ErrorCode.CHAIN_ALREADY_RUNNING,
        ErrorCode.CUSTOM_STEPS_REFUSED,
    }


# ---------------------------------------------------------------------------
# The full product: 576 combinations, checked against 4.5.5's wording
# ---------------------------------------------------------------------------

PRODUCT = list(itertools.product(ROLES, ACTIONS, ENVIRONMENTS, URGENCIES, JUSTIFICATIONS))


def test_the_sweep_covers_every_combination() -> None:
    assert len(PRODUCT) == 3 * 8 * 3 * 4 * 2


@pytest.mark.parametrize(("role", "action", "environment", "urgency", "justification"), PRODUCT)
def test_every_combination_obeys_4_5_5(
    role: Role,
    action: Action,
    environment: TargetEnvironment | None,
    urgency: Urgency | None,
    justification: str | None,
) -> None:
    intent = intent_for(
        action, environment=environment, urgency=urgency, justification=justification
    )
    decision = policy.evaluate(intent, PolicyContext(role=role))
    reason_codes = codes(decision)
    deploys_to_production = action in DEPLOY_ACTIONS and environment is TargetEnvironment.PRODUCTION

    # "Deploy to production: Refused" -- for every role.
    if deploys_to_production:
        assert decision.outcome is PolicyOutcome.REFUSE
        assert ErrorCode.PRODUCTION_REFUSED in reason_codes
    else:
        # Production is a deploy rule; building "for production" deploys nothing.
        assert ErrorCode.PRODUCTION_REFUSED not in reason_codes

    # "Deploy to staging: Allowed" -- nothing about staging itself ever refuses.
    if environment is TargetEnvironment.STAGING and urgency is not Urgency.HIGH:
        assert decision.outcome is PolicyOutcome.ALLOW

    # HIGH urgency: only a developer is ever asked for a reason, and only without one.
    asked = ErrorCode.JUSTIFICATION_REQUIRED in reason_codes
    expect_asked = (
        urgency is Urgency.HIGH
        and role is Role.DEVELOPER
        and justification is None
        and action is not Action.UNSUPPORTED
    )
    assert asked is expect_asked

    # DevOps and Admin keep HIGH: "Allowed".
    if urgency is Urgency.HIGH and role is not Role.DEVELOPER:
        assert decision.intent.urgency is Urgency.HIGH
        assert ErrorCode.QUOTA_EXCEEDED not in reason_codes

    # Nothing below HIGH is ever asked to justify itself or counted against the quota.
    if urgency is not Urgency.HIGH:
        assert not reason_codes & {ErrorCode.JUSTIFICATION_REQUIRED, ErrorCode.QUOTA_EXCEEDED}
        assert HIGH_URGENCY_AUDIT_ACTION not in audit_actions(decision)

    # "Every denial returns a reason the UI can show and an audit entry."
    if decision.outcome is not PolicyOutcome.ALLOW:
        assert decision.reasons, "a denial with no reason"
        assert decision.audit, "a denial with no audit entry"
        assert all(reason.message for reason in decision.reasons)

    # 4.4.3: an audit entry for every HIGH-urgency request.
    if urgency is Urgency.HIGH and action is not Action.UNSUPPORTED:
        assert audit_actions(decision).count(HIGH_URGENCY_AUDIT_ACTION) == 1

    # The policy only ever changes urgency; everything else the user asked for is kept.
    for name in ("action", "service", "branch", "environment", "justification"):
        assert getattr(decision.intent, name) == getattr(intent, name), name
