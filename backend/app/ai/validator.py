"""``IntentValidator``: BUILD_PROMPT 4.5.3 step 3.

"Check in code: the service exists; the branch and commit resolve through ``GitClient``; the suite
belongs to that service; the environment is allowed for it. Code decides, never the model."

Two kinds of finding come out, and the difference matters:

* **Issues** block generation. Each names the field and offers candidates, so the clarification
  service can turn it straight into one question with buttons.
* **Warnings** do not block. They are shown on the intent card the user confirms, so nothing is
  silently decided for them.

The line between them is drawn at *what we know*. A remote that answers and does not have the branch
is a known problem: ask. A remote that cannot be reached is an unknown: warn and go on, because
Jenkins will fail the checkout honestly if the branch is wrong, and because blocking on an
unreachable remote would make the whole assistant unusable whenever GitHub is slow -- or, today,
for as long as the catalog's sample repositories remain unpushed.

``production`` is deliberately not an issue here. It is not "missing" or "ambiguous" -- the user
asked for it plainly -- so asking which environment they meant would be the wrong response. The
policy layer refuses it with the staging-only explanation, which is what 4.6.5 specifies.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

from app.ai.intent import ExtraStage, Intent, TargetEnvironment
from app.services.catalog import Catalog, CatalogService
from app.services.git import GitClient, GitError, is_commit_sha, is_safe_ref

MAX_CANDIDATES: Final = 4


class IssueKind(StrEnum):
    UNKNOWN = "unknown"  # names something that does not exist
    NOT_ALLOWED = "not_allowed"  # exists, but not for this service
    UNSAFE = "unsafe"  # a value that may not be passed on at all


@dataclass(frozen=True)
class ValidationIssue:
    field: str
    kind: IssueKind
    message: str
    candidates: tuple[str, ...] = ()


@dataclass(frozen=True)
class ValidationResult:
    intent: Intent
    issues: tuple[ValidationIssue, ...] = ()
    warnings: tuple[str, ...] = ()
    #: What the branch and commit resolve to, for the intent card. The intent itself keeps what
    #: the user asked for -- "latest", a null branch -- so the card can show both.
    resolved_branch: str | None = None
    resolved_commit: str | None = None

    @property
    def ok(self) -> bool:
        return not self.issues


@dataclass
class _Findings:
    issues: list[ValidationIssue] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def closest(
    value: str, options: list[str] | tuple[str, ...], limit: int = MAX_CANDIDATES
) -> tuple[str, ...]:
    """Up to ``limit`` options, the nearest to ``value`` first, then the rest in order."""
    ranked = difflib.get_close_matches(value, list(options), n=limit, cutoff=0.0)
    return tuple(ranked[:limit])


class IntentValidator:
    def __init__(self, catalog: Catalog, git: GitClient) -> None:
        self._catalog = catalog
        self._git = git

    async def validate(self, intent: Intent) -> ValidationResult:
        findings = _Findings()
        service = self._check_service(intent, findings)
        current = intent
        resolved_branch: str | None = None
        resolved_commit: str | None = None

        if service is not None:
            current = self._check_suite(current, service, findings)
            self._check_environment(current, service, findings)
            current = self._check_stages(current, service, findings)
            resolved_branch, resolved_commit = await self._check_refs(current, service, findings)

        return ValidationResult(
            intent=current,
            issues=tuple(findings.issues),
            warnings=tuple(findings.warnings),
            resolved_branch=resolved_branch,
            resolved_commit=resolved_commit,
        )

    # --- Service ----------------------------------------------------------

    def _check_service(self, intent: Intent, findings: _Findings) -> CatalogService | None:
        if intent.service is None:
            return None
        service = self._catalog.get(intent.service)
        if service is None:
            # Strict decoding makes this impossible for a live model, but a replayed fixture or a
            # provider that ignores `strict` must not get an invented service through either.
            findings.issues.append(
                ValidationIssue(
                    field="service",
                    kind=IssueKind.UNKNOWN,
                    message=f"There is no service called {intent.service!r} in the catalog.",
                    candidates=closest(intent.service, self._catalog.service_names()),
                )
            )
        return service

    # --- Suite ------------------------------------------------------------

    def _check_suite(self, intent: Intent, service: CatalogService, findings: _Findings) -> Intent:
        if intent.test_suite is None:
            return intent
        if service.suite(intent.test_suite) is None:
            names = tuple(suite.name for suite in service.test_suites)
            findings.issues.append(
                ValidationIssue(
                    field="test_suite",
                    kind=IssueKind.NOT_ALLOWED,
                    message=(
                        f"{service.name} has no {intent.test_suite!r} test suite. "
                        f"It has: {', '.join(names) or 'none'}."
                    ),
                    candidates=names[:MAX_CANDIDATES],
                )
            )
        return intent

    # --- Environment ------------------------------------------------------

    def _check_environment(
        self, intent: Intent, service: CatalogService, findings: _Findings
    ) -> None:
        environment = intent.environment
        if environment is None or environment is TargetEnvironment.PRODUCTION:
            return  # null asks a question elsewhere; production is the policy's to refuse
        if not service.allows(environment.value):
            findings.issues.append(
                ValidationIssue(
                    field="environment",
                    kind=IssueKind.NOT_ALLOWED,
                    message=f"{service.name} cannot be deployed to {environment.value}.",
                    candidates=tuple(service.allowed_environments)[:MAX_CANDIDATES],
                )
            )

    # --- Extra stages -----------------------------------------------------

    def _check_stages(self, intent: Intent, service: CatalogService, findings: _Findings) -> Intent:
        """Keep only stages the service configures, and say which were dropped.

        Dropped with a visible warning rather than blocked: asking a question about an optional
        stage is out of proportion, and dropping it silently would mean the user approves a plan
        that differs from what they asked for without knowing.
        """
        kept: list[ExtraStage] = []
        for stage in intent.extra_stages:
            # integration_tests is satisfied by an integration *suite* as well as a stage.
            available = stage.value in service.extra_stages or (
                stage is ExtraStage.INTEGRATION_TESTS and service.suite("integration") is not None
            )
            if available:
                kept.append(stage)
            else:
                findings.warnings.append(
                    f"{stage.value} is not configured for {service.name}, so that stage is skipped."
                )
        if len(kept) == len(intent.extra_stages):
            return intent
        return intent.with_changes(extra_stages=tuple(kept))

    # --- Branch and commit through Git -----------------------------------

    async def _check_refs(
        self, intent: Intent, service: CatalogService, findings: _Findings
    ) -> tuple[str | None, str | None]:
        branch = intent.branch or service.default_branch

        if intent.branch is not None and not is_safe_ref(intent.branch):
            # Not a question: a value of this shape is refused outright, because it could be read
            # as an option by git (D-023) or break the job's XML.
            findings.issues.append(
                ValidationIssue(
                    field="branch",
                    kind=IssueKind.UNSAFE,
                    message="That branch name contains characters that are not allowed.",
                )
            )
            return None, None

        try:
            branches = await self._git.list_branches(service.repo)
        except GitError:
            findings.warnings.append(
                f"Could not reach {service.name}'s repository to check the branch; "
                f"Jenkins will report it if {branch!r} does not exist."
            )
            return branch, intent.commit

        if branch not in branches:
            findings.issues.append(
                ValidationIssue(
                    field="branch",
                    kind=IssueKind.UNKNOWN,
                    message=f"{service.name} has no branch called {branch!r}.",
                    candidates=closest(branch, branches),
                )
            )
            return None, None

        commit = intent.commit
        if commit is None:
            return branch, None

        if commit.lower() == "latest":
            # 4.6.5: "commit resolved to a SHA". Resolved now, so the job that runs is the commit
            # the user approved, not whatever the branch points at by the time it is scheduled.
            sha = await self._resolve(service, branch, findings)
            return branch, sha or "latest"

        if not is_commit_sha(commit.lower()):
            findings.issues.append(
                ValidationIssue(
                    field="commit",
                    kind=IssueKind.UNSAFE,
                    message=(
                        f"{commit!r} is not a commit SHA. "
                        "Give at least 7 hex characters, or say latest."
                    ),
                )
            )
            return branch, None

        try:
            found = await self._git.commit_exists(service.repo, commit.lower(), branch=branch)
        except GitError:
            findings.warnings.append(f"Could not verify commit {commit} against the repository.")
            return branch, commit

        if not found:
            # ls-remote only sees branch tips (D-024), so an older commit cannot be confirmed.
            # That is a warning, not an issue: the commit may well exist further back.
            findings.warnings.append(
                f"{commit} is not the tip of {branch}; it could not be confirmed, and the build "
                "will fail at checkout if it does not exist."
            )
        return branch, commit

    async def _resolve(
        self, service: CatalogService, branch: str, findings: _Findings
    ) -> str | None:
        try:
            return await self._git.resolve(service.repo, branch)
        except GitError:
            findings.warnings.append(
                f"Could not resolve the latest commit of {branch}; the newest commit at build time "
                "will be used."
            )
            return None
