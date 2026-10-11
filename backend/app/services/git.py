"""Git client: resolving branches and commits without cloning anything.

BUILD_PROMPT 4.5.3 step 3 requires that "the branch and commit resolve through ``GitClient``", and
4.6.3 repeats it among the validation checks. Every reference the assistants put into a generated
job passes through here first, so a job is never created against a branch that does not exist.

Everything is done with ``git ls-remote``. No working copy is ever created: the backend only needs
to know that a ref exists and what it points at, and cloning two repositories per validation would
add disk, latency and a cleanup problem for an answer that is one network round trip.

**This module takes untrusted input.** The branch and commit come from a chat message by way of an
LLM. Two defences, both of which have to be here rather than at the caller:

* the subprocess is invoked with an argument list and ``shell=False``, so no shell ever sees these
  values;
* refs are checked against ``REF_PATTERN`` before being passed. An argument list alone is not
  enough, because ``git`` reads a leading ``-`` as an option, and ``--upload-pack=<command>`` makes
  ``ls-remote`` execute that command. That is remote code execution through an argument that never
  touches a shell, so rejecting the shape is the actual fix.
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Final

from app.core.logging import get_logger

logger = get_logger(__name__)

TIMEOUT_SECONDS: Final = 15.0

# How long a resolved ref is trusted. Short, because the point of resolving a branch is to catch a
# name that does not exist, and a long cache would keep accepting a branch after it was deleted.
# Long enough that the several validations behind one conversation do not each hit the network.
CACHE_SECONDS: Final = 60.0

# Git's own rules for ref names are broader than this; the extra narrowness is intentional. These
# values end up in Jenkins job parameters and in a config.xml, so the set is restricted to what is
# safe in all three places. No leading dash, so the value can never be read as an option.
REF_PATTERN: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,254}$")

COMMIT_PATTERN: Final = re.compile(r"^[0-9a-f]{7,40}$")

# Only these schemes are fetched. Git supports transports that run commands by design -- `ext::`
# executes its argument, and a local path can point at a repository with hooks -- so a repo URL
# arriving from the database rather than the validated catalog cannot become code execution.
ALLOWED_URL = re.compile(r"^(https://|git@)")


class GitError(RuntimeError):
    """A git operation failed."""


@dataclass(frozen=True)
class Ref:
    """One entry from ``git ls-remote``."""

    name: str
    sha: str

    @property
    def short_name(self) -> str:
        """``refs/heads/main`` as ``main``."""
        for prefix in ("refs/heads/", "refs/tags/"):
            if self.name.startswith(prefix):
                return self.name[len(prefix) :]
        return self.name


def is_safe_ref(ref: str) -> bool:
    """Whether a branch or tag name may be passed to git."""
    return bool(REF_PATTERN.match(ref))


def is_commit_sha(value: str) -> bool:
    """Whether a string looks like a commit id rather than a branch name."""
    return bool(COMMIT_PATTERN.match(value))


class GitClient(ABC):
    """What the backend needs from Git.

    An interface so the unit suite never reaches the network: ``FakeGitClient`` answers from a
    dictionary, which is what lets validation be tested for behaviour rather than for reachability.
    """

    @abstractmethod
    async def list_refs(self, repo_url: str) -> tuple[Ref, ...]:
        """Every branch and tag on the remote."""

    async def list_branches(self, repo_url: str) -> tuple[str, ...]:
        """Branch names, short form, sorted."""
        refs = await self.list_refs(repo_url)
        return tuple(sorted(ref.short_name for ref in refs if ref.name.startswith("refs/heads/")))

    async def branch_exists(self, repo_url: str, branch: str) -> bool:
        if not is_safe_ref(branch):
            return False
        return branch in await self.list_branches(repo_url)

    async def resolve(self, repo_url: str, ref: str) -> str | None:
        """The full commit id a branch or tag points at, or None if it does not exist."""
        if not is_safe_ref(ref):
            return None
        refs = await self.list_refs(repo_url)
        for candidate in refs:
            if candidate.short_name == ref or candidate.name == ref:
                return candidate.sha
        return None

    async def commit_exists(self, repo_url: str, commit: str, *, branch: str | None = None) -> bool:
        """Whether a commit id is reachable on the remote.

        ``ls-remote`` reports ref tips, not history, so this confirms that the id *is* a tip, or is
        a prefix of one. A commit further back cannot be confirmed without fetching, and 4.5.3 only
        needs to establish that a stated commit is real before a job is generated; Jenkins fails
        the build honestly if a checkout later cannot find it.
        """
        value = commit.strip().lower()
        if not is_commit_sha(value):
            return False
        refs = await self.list_refs(repo_url)
        if branch is not None:
            refs = tuple(ref for ref in refs if ref.short_name == branch)
        return any(ref.sha.startswith(value) for ref in refs)

    async def aclose(self) -> None:
        """Release anything held. Nothing by default."""
        return None


class CliGitClient(GitClient):
    """``git ls-remote`` in a subprocess, with a short-lived cache.

    ``git`` is used rather than an HTTP call to the forge, because the catalog holds clone URLs and
    nothing in the system should need to know which forge hosts them.
    """

    def __init__(self, *, timeout: float = TIMEOUT_SECONDS, cache_seconds: float = CACHE_SECONDS):
        self._timeout = timeout
        self._cache_seconds = cache_seconds
        self._cache: dict[str, tuple[float, tuple[Ref, ...]]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def list_refs(self, repo_url: str) -> tuple[Ref, ...]:
        if not ALLOWED_URL.match(repo_url):
            raise GitError(f"refusing to fetch {repo_url!r}: only https:// and git@ are allowed")

        cached = self._cache.get(repo_url)
        now = time.monotonic()
        if cached is not None and now - cached[0] < self._cache_seconds:
            return cached[1]

        # One lock per repository, so a burst of validations for the same service makes one call
        # rather than one each -- and so the loser of the race reads the fresh cache entry.
        lock = self._locks.setdefault(repo_url, asyncio.Lock())
        async with lock:
            cached = self._cache.get(repo_url)
            now = time.monotonic()
            if cached is not None and now - cached[0] < self._cache_seconds:
                return cached[1]
            refs = await self._ls_remote(repo_url)
            self._cache[repo_url] = (time.monotonic(), refs)
            return refs

    async def _ls_remote(self, repo_url: str) -> tuple[Ref, ...]:
        command = (
            "git",
            # Never prompt. Without this a repository that has become private blocks on a
            # credential prompt until the timeout, turning a 404 into fifteen seconds of latency.
            "-c",
            "credential.helper=",
            "ls-remote",
            "--heads",
            "--tags",
            "--",
            repo_url,
        )
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=_git_env(),
            )
        except OSError as exc:  # git is not installed
            raise GitError(f"could not run git: {exc}") from exc

        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=self._timeout)
        except TimeoutError:
            process.kill()
            await process.wait()
            raise GitError(
                f"git ls-remote {repo_url} timed out after {self._timeout:.0f}s"
            ) from None

        if process.returncode != 0:
            detail = stderr.decode("utf-8", "replace").strip().splitlines()
            raise GitError(
                f"git ls-remote {repo_url} failed: " + (detail[-1] if detail else "no output")
            )

        refs = _parse_ls_remote(stdout.decode("utf-8", "replace"))
        logger.info("git_ls_remote", repo=repo_url, refs=len(refs))
        return refs

    def invalidate(self, repo_url: str | None = None) -> None:
        """Drop cached refs, for one repository or all of them."""
        if repo_url is None:
            self._cache.clear()
        else:
            self._cache.pop(repo_url, None)


def _git_env() -> dict[str, str]:
    """The environment for the subprocess: inherited, with the prompt suppressors added.

    Inherited rather than replaced. A minimal environment looks safer and is not: on Windows,
    dropping ``SystemRoot`` breaks name resolution inside the Winsock DLL, and every fetch fails
    with "getaddrinfo() thread failed to start" -- which reads like a network outage rather than a
    missing variable. ``scripts/validate_catalog.py`` had exactly this bug.

    The variables added are what stop git blocking on a credential prompt. Without them a
    repository that has been made private hangs until the timeout instead of failing at once.
    """
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_ASKPASS"] = "echo"
    env["GCM_INTERACTIVE"] = "never"
    return env


def _parse_ls_remote(output: str) -> tuple[Ref, ...]:
    """Parse ``<sha>\\t<ref>`` lines.

    ``^{}`` entries -- the commit a tag object points at -- are dropped. Keeping both would make
    an annotated tag appear twice with different ids, and the tag's own id is the one a checkout
    resolves.
    """
    refs: list[Ref] = []
    for line in output.splitlines():
        sha, _, name = line.partition("\t")
        name = name.strip()
        if not name or not sha or name.endswith("^{}"):
            continue
        refs.append(Ref(name=name, sha=sha.strip()))
    return tuple(refs)


class FakeGitClient(GitClient):
    """An in-memory remote. The default in tests."""

    def __init__(self, repositories: dict[str, dict[str, str]] | None = None) -> None:
        # {repo_url: {ref name: sha}}
        self.repositories: dict[str, dict[str, str]] = repositories or {}
        self.calls: list[str] = []
        self.fail_with: GitError | None = None

    def add_branch(self, repo_url: str, branch: str, sha: str) -> None:
        self.repositories.setdefault(repo_url, {})[f"refs/heads/{branch}"] = sha

    async def list_refs(self, repo_url: str) -> tuple[Ref, ...]:
        self.calls.append(repo_url)
        if self.fail_with is not None:
            raise self.fail_with
        if repo_url not in self.repositories:
            raise GitError(f"repository not found: {repo_url}")
        return tuple(
            Ref(name=name, sha=sha) for name, sha in sorted(self.repositories[repo_url].items())
        )
