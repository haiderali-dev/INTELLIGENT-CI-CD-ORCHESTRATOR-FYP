"""Which revision a generated job checks out. One rule, shared by both assistants (D-041).

1. A commit, when given, is checked out exactly. It wins over the branch.
2. Otherwise the head of the given branch.
3. Otherwise the head of ``main``.
4. A value that was given but is not valid is an error. It never falls back to another revision.

Why the rule lives here rather than in each job. Measured on jenkins-dev on 2026-10-12 (D-041):

- A freestyle job's Git SCM can follow only one variable. The Git plugin expands ``${VAR}`` and
  nothing more (D-038), and no installed plugin can compute a value before checkout. "COMMIT, else
  BRANCH" cannot be written inside a freestyle job.
- An empty branch spec is not an error to the Git plugin. It means "any branch". With both values
  blank, the old Pipeline reference built ``demo/failing-tests`` and reported SUCCESS.

So the backend decides, and both job types are handed the same two parameter values:

- ``COMMIT`` is the revision to check out, never empty: the commit SHA, or ``refs/heads/<branch>``.
  A fully qualified ref, so a branch name can never be read as a SHA or a tag, and a branch that
  does not exist fails the checkout instead of matching something else.
- ``BRANCH`` is the branch the revision belongs to.

A freestyle chain gets them as parameter defaults on every job, because a downstream trigger passes
no parameters on (4.6). A Pipeline gets them at trigger time, and its Jenkinsfile applies the same
rule again, so a Pipeline run started by hand in Jenkins is held to it too. A freestyle job run by
hand cannot be: it checks out whatever its ``COMMIT`` says.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Literal

from app.services.git import is_commit_sha, is_safe_ref

DEFAULT_BRANCH: Final = "main"

# Prefix that makes a branch unambiguous in a Git plugin branch spec.
BRANCH_REF_PREFIX: Final = "refs/heads/"

RevisionField = Literal["commit", "branch"]


class RevisionSource(StrEnum):
    """Which clause of the rule chose the revision."""

    COMMIT = "commit"
    BRANCH = "branch"
    DEFAULT = "default"


class RevisionError(ValueError):
    """A commit or branch was given but cannot be checked out as written.

    Raised instead of falling back. Naming the field lets the caller point the user at it.
    """

    def __init__(self, field: RevisionField, value: str, message: str) -> None:
        super().__init__(message)
        self.field: RevisionField = field
        self.value = value


@dataclass(frozen=True)
class Revision:
    """The outcome of the rule."""

    source: RevisionSource
    branch: str
    commit: str | None = None

    @property
    def checkout(self) -> str:
        """The Git branch spec: the commit, or the branch as a fully qualified ref."""
        return self.commit if self.commit is not None else f"{BRANCH_REF_PREFIX}{self.branch}"

    def parameters(self) -> dict[str, str]:
        """``BRANCH`` and ``COMMIT``, identical for a freestyle and a Pipeline job."""
        return {"BRANCH": self.branch, "COMMIT": self.checkout}


def _given(value: str | None) -> str | None:
    """A value counts as given only if something is left after trimming.

    Jenkins trims string parameters, so a blank or whitespace-only value is treated the same way
    here. Treating ``""`` as a value would hand the Git plugin an empty spec, which means "any
    branch".
    """
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def select_revision(commit: str | None, branch: str | None) -> Revision:
    """Apply the rule. Raises ``RevisionError`` for a given value that is not valid.

    Both values are checked when both are given. A valid commit does not excuse an invalid branch,
    because the branch is still written into the job and shown to the user.
    """
    given_commit = _given(commit)
    given_branch = _given(branch)

    if given_branch is not None:
        if given_branch.startswith(BRANCH_REF_PREFIX):
            given_branch = given_branch[len(BRANCH_REF_PREFIX) :]
        if not is_safe_ref(given_branch) or ".." in given_branch or given_branch.endswith("/"):
            raise RevisionError(
                "branch", given_branch, f"{given_branch!r} is not a branch name that can be used."
            )

    if given_commit is not None:
        normalised = given_commit.lower()
        if not is_commit_sha(normalised):
            raise RevisionError(
                "commit",
                given_commit,
                f"{given_commit!r} is not a commit SHA (7 to 40 hexadecimal characters).",
            )
        return Revision(RevisionSource.COMMIT, given_branch or DEFAULT_BRANCH, normalised)

    if given_branch is not None:
        return Revision(RevisionSource.BRANCH, given_branch)

    return Revision(RevisionSource.DEFAULT, DEFAULT_BRANCH)
