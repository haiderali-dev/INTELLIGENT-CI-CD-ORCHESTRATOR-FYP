"""The revision rule (D-041), checked where it matters: what Jenkins actually checks out.

Marked ``integration``: it needs jenkins-dev and the payment-service repository on GitHub.

    uv run python -m pytest -m integration tests/test_integration_revision.py

Two jobs derived from the exported reference configs (rule 1.4). Their Git checkout is kept exactly.
Every build step is replaced with one that prints the commit checked out, and the archiver,
downstream trigger and deploy are removed. Each case drives both job types the way the backend
will, through ``select_revision``, and asserts both land on the same commit.

The commits are resolved live with ``git ls-remote``, never hard-coded, so a push to either branch
does not break the suite.

Why each case exists, measured on 2026-10-12 against the *previous* reference configs:

- With both values blank, the old Pipeline built ``demo/failing-tests`` and reported SUCCESS. An
  empty branch spec means "any branch" to the Git plugin.
- The old freestyle job ignored BRANCH. With a branch that does not exist it built another one and
  reported SUCCESS.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncGenerator, Callable

import pytest

from app.core.settings import Environment, Settings
from app.generation.revision import RevisionError, select_revision
from app.services.git import CliGitClient
from app.services.jenkins import HttpJenkinsClient, JenkinsError
from tests.test_integration_jenkins import (
    read_env,
    recreate,
    reference,
    wait_for_build,
    wait_for_complete_log,
    wait_for_finish,
)

pytestmark = pytest.mark.integration

REPO = "https://github.com/haiderali-dev/payment-service.git"
DEMO_BRANCH = "demo/failing-tests"

FREESTYLE_JOB = "it-revision-freestyle"
PIPELINE_JOB = "it-revision-pipeline"
UPSTREAM_JOB = "it-revision-upstream"

PROBE = "echo REVISION_HEAD=$(git rev-parse HEAD)"
NO_REVISION = "Couldn't find any revision to build"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def live_settings() -> Settings:
    env = read_env()
    if not env.get("JENKINS_USER") or not env.get("JENKINS_TOKEN"):
        pytest.skip("JENKINS_USER and JENKINS_TOKEN are not configured; see .env.example")
    return Settings(
        environment=Environment.TEST,
        database_url="sqlite+aiosqlite:///:memory:",
        jenkins_url=env.get("JENKINS_URL_HOST", "http://localhost:8087"),
        jenkins_user=env["JENKINS_USER"],
        jenkins_token=env["JENKINS_TOKEN"],
    )


@pytest.fixture
async def jenkins(live_settings: Settings) -> AsyncGenerator[HttpJenkinsClient]:
    client = HttpJenkinsClient(live_settings)
    try:
        await client.version()
    except JenkinsError as exc:
        await client.aclose()
        pytest.skip(f"jenkins-dev is not reachable: {exc}")
    yield client
    await client.aclose()


@pytest.fixture(scope="module")
async def heads() -> dict[str, str]:
    """The current tip of each branch, from the remote."""
    git = CliGitClient()
    found = {}
    for branch in ("main", DEMO_BRANCH):
        sha = await git.resolve(REPO, branch)
        if sha is None:
            pytest.skip(f"{REPO} has no branch {branch}")
        found[branch] = sha
    assert found["main"] != found[DEMO_BRANCH], (
        "the two branches must differ for this to prove anything"
    )
    return found


# ---------------------------------------------------------------------------
# Jobs derived from the reference exports
# ---------------------------------------------------------------------------


def freestyle_config(defaults: dict[str, str] | None = None) -> str:
    config = reference("freestyle-build-test-deploy.config.xml")
    config = re.sub(r"<command>.*?</command>", f"<command>{PROBE}</command>", config, flags=re.S)
    for element in ("hudson.tasks.ArtifactArchiver", "hudson.tasks.BuildTrigger"):
        pattern = re.escape(element)
        config = re.sub(rf"<{pattern}>.*?</{pattern}>", "", config, flags=re.S)
    if defaults:
        # 4.6: a freestyle chain receives BRANCH and COMMIT as parameter defaults on every job,
        # because a downstream trigger passes no parameters on.
        for name, value in defaults.items():
            config, count = re.subn(
                rf"(<name>{name}</name>\s*<description>[^<]*</description>\s*<defaultValue>)[^<]*(</defaultValue>)",
                lambda m, value=value: m.group(1) + value + m.group(2),
                config,
            )
            assert count == 1, f"no default for {name} in the freestyle reference"
    return config


def pipeline_config() -> str:
    config = reference("pipeline-build-test-deploy.config.xml")
    config, count = re.subn(r"sh &apos;[^&]*?&apos;", f"sh &apos;{PROBE}&apos;", config)
    assert count == 3, f"expected three stage steps, replaced {count}"
    return config


def upstream_config() -> str:
    """A checkout-free job whose only purpose is to trigger the freestyle job without parameters,
    the way the previous job in a chain does."""
    config = reference("freestyle-downstream.config.xml")
    config = re.sub(
        r"<io\.jenkins\.plugins\.queueoptimizer\.property\.JobPriorityProperty.*?"
        r"</io\.jenkins\.plugins\.queueoptimizer\.property\.JobPriorityProperty>",
        "",
        config,
        flags=re.S,
    )
    trigger = re.search(
        r"<hudson\.tasks\.BuildTrigger>.*?</hudson\.tasks\.BuildTrigger>",
        reference("freestyle-build-test-deploy.config.xml"),
        flags=re.S,
    )
    assert trigger is not None, "the freestyle reference has no downstream trigger"
    block = re.sub(
        r"<childProjects>[^<]*</childProjects>",
        f"<childProjects>{FREESTYLE_JOB}</childProjects>",
        trigger.group(0),
    )
    return config.replace("<publishers/>", f"<publishers>{block}</publishers>")


# ---------------------------------------------------------------------------
# Running one build and reading what it checked out
# ---------------------------------------------------------------------------


async def run(
    client: HttpJenkinsClient, job: str, params: dict[str, str]
) -> tuple[str, str | None, str]:
    """Trigger with ``params``. Returns the result, the commit checked out (if any), and the log."""
    number = await wait_for_build(client, job, await client.trigger(job, params))
    result = await wait_for_finish(client, job, number)
    log = await wait_for_complete_log(client, job, number)
    heads = set(re.findall(r"REVISION_HEAD=([0-9a-f]{40})", log))
    assert len(heads) <= 1, f"{job}#{number} checked out more than one commit: {heads}"
    return result, (heads.pop() if heads else None), log


@pytest.fixture
async def jobs(jenkins: HttpJenkinsClient) -> HttpJenkinsClient:
    await recreate(jenkins, FREESTYLE_JOB, freestyle_config())
    await recreate(jenkins, PIPELINE_JOB, pipeline_config())
    return jenkins


# ---------------------------------------------------------------------------
# The rule, through the backend, on both job types
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("commit", "branch", "expected"),
    [
        pytest.param("demo", "main", "demo", id="commit wins over branch"),
        pytest.param(None, DEMO_BRANCH, "demo", id="branch head without a commit"),
        pytest.param(None, None, "main", id="main with neither"),
        pytest.param("", "", "main", id="main when both are blank"),
    ],
)
async def test_both_job_types_check_out_the_same_commit(
    jobs: HttpJenkinsClient,
    heads: dict[str, str],
    commit: str | None,
    branch: str | None,
    expected: str,
) -> None:
    sha = {"demo": heads[DEMO_BRANCH], "main": heads["main"]}
    parameters = select_revision(sha.get(commit or "", commit), branch).parameters()

    outcomes = {job: await run(jobs, job, parameters) for job in (FREESTYLE_JOB, PIPELINE_JOB)}

    for job, (result, head, _) in outcomes.items():
        assert result == "SUCCESS", f"{job} finished {result} with {parameters}"
        assert head == sha[expected], (
            f"{job} checked out {head}, expected {expected} {sha[expected]}"
        )


@pytest.mark.parametrize(
    "parameters",
    [
        pytest.param(
            {"commit": "0000000deadbeef", "branch": "main"}, id="commit that does not exist"
        ),
        pytest.param(
            {"commit": None, "branch": "no-such-branch-d041"}, id="branch that does not exist"
        ),
    ],
)
async def test_a_revision_that_does_not_exist_fails_both_job_types(
    jobs: HttpJenkinsClient, parameters: dict[str, str | None]
) -> None:
    """Well-formed, so the backend passes it on, but not in the repository. Both must fail at
    checkout. Neither may build anything else: no commit is checked out at all."""
    values = select_revision(parameters["commit"], parameters["branch"]).parameters()

    for job in (FREESTYLE_JOB, PIPELINE_JOB):
        result, head, log = await run(jobs, job, values)
        assert result == "FAILURE", f"{job} finished {result} with {values}"
        assert head is None, f"{job} fell back to {head}"
        assert NO_REVISION in log


@pytest.mark.parametrize("commit", ["latest", "not-a-sha", "3f9c2ab; id"])
async def test_an_invalid_commit_never_reaches_jenkins(commit: str) -> None:
    """Rejected before any job is touched, so there is nothing for Jenkins to fall back from."""
    with pytest.raises(RevisionError):
        select_revision(commit, "main")


# ---------------------------------------------------------------------------
# The Pipeline holds a run started by hand to the same rule
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("parameters", "expected"),
    [
        pytest.param({"BRANCH": DEMO_BRANCH, "COMMIT": ""}, "demo", id="BRANCH only"),
        pytest.param({"BRANCH": "", "COMMIT": ""}, "main", id="both blank: main, not any branch"),
        pytest.param({"BRANCH": "main", "COMMIT": "demo"}, "demo", id="raw COMMIT wins"),
    ],
)
async def test_the_pipeline_applies_the_rule_to_raw_parameters(
    jobs: HttpJenkinsClient, heads: dict[str, str], parameters: dict[str, str], expected: str
) -> None:
    sha = {"demo": heads[DEMO_BRANCH], "main": heads["main"]}
    values = {name: sha.get(value, value) for name, value in parameters.items()}

    result, head, _ = await run(jobs, PIPELINE_JOB, values)

    assert result == "SUCCESS"
    assert head == sha[expected]


@pytest.mark.parametrize(
    ("parameters", "message"),
    [
        pytest.param(
            {"BRANCH": "main", "COMMIT": "not-a-sha"}, "is not a commit SHA", id="bad COMMIT"
        ),
        pytest.param(
            {"BRANCH": "bad..branch", "COMMIT": ""}, "is not a branch name", id="bad BRANCH"
        ),
    ],
)
async def test_the_pipeline_refuses_invalid_raw_parameters_before_checkout(
    jobs: HttpJenkinsClient, parameters: dict[str, str], message: str
) -> None:
    result, head, log = await run(jobs, PIPELINE_JOB, parameters)

    assert result == "FAILURE"
    assert head is None
    assert message in log
    assert "Checking out Revision" not in log, "it must stop before the Git plugin runs"


# ---------------------------------------------------------------------------
# Freestyle: defaults written on the job, triggered without parameters
# ---------------------------------------------------------------------------


async def test_a_chain_job_checks_out_the_revision_written_into_its_defaults(
    jenkins: HttpJenkinsClient, heads: dict[str, str]
) -> None:
    """How a freestyle chain really runs (4.6): the first job is triggered, and the next ones are
    started by a downstream trigger that passes no parameters. They follow their own defaults."""
    defaults = select_revision(None, DEMO_BRANCH).parameters()
    await recreate(jenkins, FREESTYLE_JOB, freestyle_config(defaults))
    await recreate(jenkins, UPSTREAM_JOB, upstream_config())
    before = await jenkins.last_build(FREESTYLE_JOB)

    upstream = await wait_for_build(jenkins, UPSTREAM_JOB, await jenkins.trigger(UPSTREAM_JOB))
    assert await wait_for_finish(jenkins, UPSTREAM_JOB, upstream) == "SUCCESS"

    number = None
    for _ in range(90):
        latest = await jenkins.last_build(FREESTYLE_JOB)
        if latest is not None and (before is None or latest.number > before.number):
            number = latest.number
            break
        await asyncio.sleep(2)
    assert number is not None, "the downstream trigger did not start the freestyle job"
    result = await wait_for_finish(jenkins, FREESTYLE_JOB, number)
    log = await wait_for_complete_log(jenkins, FREESTYLE_JOB, number)

    assert result == "SUCCESS"
    assert f"REVISION_HEAD={heads[DEMO_BRANCH]}" in log


# ---------------------------------------------------------------------------
# Regeneration keeps the parameters
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("job", "config"),
    [
        pytest.param(FREESTYLE_JOB, freestyle_config, id="freestyle"),
        pytest.param(PIPELINE_JOB, pipeline_config, id="pipeline"),
    ],
)
async def test_regenerating_a_job_keeps_its_parameters(
    jenkins: HttpJenkinsClient, heads: dict[str, str], job: str, config: Callable[[], str]
) -> None:
    """D-034: pushing an exported Pipeline config used to wipe the parameters its first run had
    registered, so the next parameterised trigger got 400. Push twice, then trigger at once."""
    for _ in range(2):
        await recreate(jenkins, job, config())

    stored = await jenkins.get_config_xml(job)
    assert "hudson.model.ParametersDefinitionProperty" in stored
    assert "<name>BRANCH</name>" in stored
    assert "<name>COMMIT</name>" in stored

    result, head, _ = await run(jenkins, job, select_revision(None, DEMO_BRANCH).parameters())
    assert result == "SUCCESS"
    assert head == heads[DEMO_BRANCH]
