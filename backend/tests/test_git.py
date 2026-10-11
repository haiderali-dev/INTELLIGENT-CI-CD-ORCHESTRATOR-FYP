"""The Git client.

Branch and commit values reach this module from a chat message by way of an LLM, so the tests that
matter are the ones about what it refuses to pass to ``git``. An argument list alone is not enough:
``git`` reads a leading ``-`` as an option, and ``--upload-pack=<command>`` makes ``ls-remote`` run
that command. That is remote code execution through an argument no shell ever sees.
"""

from __future__ import annotations

import asyncio
import os

import pytest

from app.services.git import (
    CliGitClient,
    FakeGitClient,
    GitError,
    Ref,
    _git_env,
    _parse_ls_remote,
    is_commit_sha,
    is_safe_ref,
)

REPO = "https://github.com/example/payment-service.git"
SHA = "3f786850e387550fdab836ed7e6dc881de23001b"
OTHER_SHA = "89e6c98d92887913cadf06b2adb97f26cde4849b"


@pytest.fixture
def git() -> FakeGitClient:
    client = FakeGitClient()
    client.add_branch(REPO, "main", SHA)
    client.add_branch(REPO, "demo/failing-tests", OTHER_SHA)
    return client


# ---------------------------------------------------------------------------
# What is refused before git is ever invoked
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ref",
    [
        "--upload-pack=touch /tmp/pwned",
        "-u",
        "--exec=sh",
        "",
        " ",
        "main;rm -rf /",
        "main$(whoami)",
        "main`id`",
        "main branch",
        "main\nrefs/heads/other",
        "a" * 256,
    ],
)
def test_dangerous_refs_are_rejected(ref: str) -> None:
    """Especially the option-shaped ones: those are code execution, not just a bad name."""
    assert not is_safe_ref(ref)


@pytest.mark.parametrize("ref", ["main", "develop", "demo/failing-tests", "release-1.2", "v1.0.0"])
def test_ordinary_refs_are_accepted(ref: str) -> None:
    assert is_safe_ref(ref)


async def test_an_option_shaped_branch_never_reaches_git(git: FakeGitClient) -> None:
    """The check happens before the call, so a hostile ref costs no network round trip either."""
    assert not await git.branch_exists(REPO, "--upload-pack=touch /tmp/pwned")
    assert await git.resolve(REPO, "--upload-pack=touch /tmp/pwned") is None


async def test_only_https_and_ssh_urls_are_fetched() -> None:
    """``ext::`` runs its argument by design, and a local path can carry hooks."""
    client = CliGitClient()

    for url in ("ext::sh -c whoami", "file:///etc", "/etc/passwd", "http://insecure/x.git"):
        with pytest.raises(GitError, match="only https"):
            await client.list_refs(url)


# ---------------------------------------------------------------------------
# Resolving
# ---------------------------------------------------------------------------


async def test_an_existing_branch_resolves_to_its_commit(git: FakeGitClient) -> None:
    assert await git.branch_exists(REPO, "main")
    assert await git.resolve(REPO, "main") == SHA


async def test_an_absent_branch_does_not_resolve(git: FakeGitClient) -> None:
    """4.5.3 needs this to be a clean no, so a job is never created against a missing branch."""
    assert not await git.branch_exists(REPO, "no-such-branch")
    assert await git.resolve(REPO, "no-such-branch") is None


async def test_branches_come_back_short_and_sorted(git: FakeGitClient) -> None:
    assert await git.list_branches(REPO) == ("demo/failing-tests", "main")


async def test_an_unknown_repository_raises(git: FakeGitClient) -> None:
    with pytest.raises(GitError, match="not found"):
        await git.list_refs("https://github.com/example/nothing.git")


async def test_a_commit_at_a_branch_tip_is_confirmed(git: FakeGitClient) -> None:
    assert await git.commit_exists(REPO, SHA)
    assert await git.commit_exists(REPO, SHA[:10])


async def test_a_commit_is_confirmed_against_the_named_branch(git: FakeGitClient) -> None:
    """A real commit on the wrong branch is still the wrong commit for this job."""
    assert await git.commit_exists(REPO, SHA, branch="main")
    assert not await git.commit_exists(REPO, SHA, branch="demo/failing-tests")


@pytest.mark.parametrize("value", ["", "zzzz", "12345", "not-a-sha", "3f78685 ; rm -rf /"])
async def test_things_that_are_not_commit_ids_are_refused(git: FakeGitClient, value: str) -> None:
    assert not await git.commit_exists(REPO, value)
    assert not is_commit_sha(value)


# ---------------------------------------------------------------------------
# Parsing ls-remote
# ---------------------------------------------------------------------------


def test_ls_remote_output_is_parsed() -> None:
    output = f"{SHA}\trefs/heads/main\n{OTHER_SHA}\trefs/tags/v1.0.0\n"

    refs = _parse_ls_remote(output)

    assert refs == (
        Ref(name="refs/heads/main", sha=SHA),
        Ref(name="refs/tags/v1.0.0", sha=OTHER_SHA),
    )
    assert [ref.short_name for ref in refs] == ["main", "v1.0.0"]


def test_peeled_tag_entries_are_dropped() -> None:
    """An annotated tag appears twice; keeping both gives one name two different commit ids."""
    output = f"{SHA}\trefs/tags/v1.0.0\n{OTHER_SHA}\trefs/tags/v1.0.0^{{}}\n"

    refs = _parse_ls_remote(output)

    assert refs == (Ref(name="refs/tags/v1.0.0", sha=SHA),)


def test_blank_and_malformed_lines_are_ignored() -> None:
    output = f"\n{SHA}\trefs/heads/main\ngarbage-without-a-tab\n\n"

    assert _parse_ls_remote(output) == (Ref(name="refs/heads/main", sha=SHA),)


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------


async def test_repeated_lookups_reuse_one_call() -> None:
    """A conversation validates several times; each should not be a network round trip."""
    calls: list[str] = []

    class CountingClient(CliGitClient):
        async def _ls_remote(self, repo_url: str) -> tuple[Ref, ...]:
            calls.append(repo_url)
            return (Ref(name="refs/heads/main", sha=SHA),)

    client = CountingClient()

    for _ in range(5):
        await client.branch_exists(REPO, "main")

    assert calls == [REPO]


async def test_concurrent_lookups_collapse_into_one_call() -> None:
    """Without the per-repository lock, a burst would make one call each."""
    calls: list[str] = []

    class SlowClient(CliGitClient):
        async def _ls_remote(self, repo_url: str) -> tuple[Ref, ...]:
            calls.append(repo_url)
            await asyncio.sleep(0.05)
            return (Ref(name="refs/heads/main", sha=SHA),)

    client = SlowClient()

    await asyncio.gather(*(client.list_refs(REPO) for _ in range(6)))

    assert calls == [REPO]


async def test_invalidate_forces_the_next_lookup_to_refetch() -> None:
    calls: list[str] = []

    class CountingClient(CliGitClient):
        async def _ls_remote(self, repo_url: str) -> tuple[Ref, ...]:
            calls.append(repo_url)
            return (Ref(name="refs/heads/main", sha=SHA),)

    client = CountingClient()
    await client.list_refs(REPO)
    client.invalidate(REPO)
    await client.list_refs(REPO)

    assert calls == [REPO, REPO]


async def test_a_deleted_branch_is_noticed_once_the_cache_expires() -> None:
    """The cache exists to save round trips, not to keep accepting a branch that is gone."""
    state = {
        "refs": (Ref(name="refs/heads/main", sha=SHA), Ref(name="refs/heads/temp", sha=OTHER_SHA))
    }

    class ChangingClient(CliGitClient):
        async def _ls_remote(self, repo_url: str) -> tuple[Ref, ...]:
            return state["refs"]

    client = ChangingClient(cache_seconds=0.0)
    assert await client.branch_exists(REPO, "temp")

    state["refs"] = (Ref(name="refs/heads/main", sha=SHA),)

    assert not await client.branch_exists(REPO, "temp")


# ---------------------------------------------------------------------------
# Failure reporting
# ---------------------------------------------------------------------------


async def test_a_failing_git_reports_its_last_line() -> None:
    """ "git failed" sends someone to the logs; the remote's own message usually explains it."""

    class FailingClient(CliGitClient):
        async def _ls_remote(self, repo_url: str) -> tuple[Ref, ...]:
            raise GitError("git ls-remote failed: Repository not found.")

    with pytest.raises(GitError, match="Repository not found"):
        await FailingClient().list_refs(REPO)


async def test_the_fake_can_be_made_to_fail(git: FakeGitClient) -> None:
    """So callers can be tested for how they behave when the remote is unreachable."""
    git.fail_with = GitError("network down")

    with pytest.raises(GitError, match="network down"):
        await git.list_refs(REPO)


# ---------------------------------------------------------------------------
# The subprocess environment
# ---------------------------------------------------------------------------


def test_the_subprocess_environment_is_inherited_not_replaced() -> None:
    """A minimal environment looks safer and is not.

    Handing git only PATH broke name resolution on Windows -- every fetch failed with
    "getaddrinfo() thread failed to start", which reads like a network outage rather than a missing
    ``SystemRoot``. ``scripts/validate_catalog.py`` had the same bug. This asserts the whole
    environment is carried over, so the next person to "tidy" it has to delete a test first.
    """
    env = _git_env()

    for name, value in os.environ.items():
        if name not in {"GIT_TERMINAL_PROMPT", "GIT_ASKPASS", "GCM_INTERACTIVE"}:
            assert env.get(name) == value, f"{name} was dropped from the git environment"


def test_the_subprocess_environment_suppresses_credential_prompts() -> None:
    """Without these, a repository that has gone private hangs until the timeout."""
    env = _git_env()

    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["GIT_ASKPASS"] == "echo"


@pytest.mark.integration
async def test_a_real_remote_resolves() -> None:
    """The real client against a real repository. Opt in with -m integration."""
    client = CliGitClient()
    url = "https://github.com/jenkinsci/ssh-agent-plugin.git"

    branches = await client.list_branches(url)
    sha = await client.resolve(url, "master")

    assert "master" in branches
    assert sha is not None and len(sha) == 40
    assert await client.commit_exists(url, sha, branch="master")
    assert not await client.branch_exists(url, "no-such-branch-xyz")
