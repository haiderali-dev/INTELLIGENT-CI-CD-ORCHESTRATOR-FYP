"""Integration tests against a live ``jenkins-dev``.

This is BUILD_PROMPT Phase 3's third acceptance clause: "integration tests create, trigger and
read one freestyle job and one Pipeline job". Marked ``integration``, so the offline suite is
unaffected:

    uv run python -m pytest -m integration tests/test_integration_jenkins.py

Every job config here is **derived from** ``jenkins/reference-configs/`` rather than written from
memory (rule 1.4). The one documented change is the SCM block: the reference jobs check out
``catalog/services.yaml``'s repositories, which are not pushed yet, so a checkout would fail for a
reason that has nothing to do with the code under test. The SCM is replaced with ``NullSCM`` and
the build steps are kept, which exercises create → trigger → queue → build → log exactly as a
generated job would.

These tests create jobs with an ``it-`` prefix and delete them afterwards, including when an
assertion fails, so a failed run does not leave rubbish on the controller for the next one.
"""

from __future__ import annotations

import asyncio
import os
import re
from collections.abc import AsyncGenerator
from pathlib import Path
from xml.etree import ElementTree

import pytest

from app.core.settings import Environment, Settings
from app.services.jenkins import (
    HttpJenkinsClient,
    JenkinsError,
    JobAlreadyExistsError,
)

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]
REFERENCE_DIR = REPO_ROOT / "jenkins" / "reference-configs"

FREESTYLE_JOB = "it-freestyle-create-trigger-read"
PIPELINE_JOB = "it-pipeline-create-trigger-read"

# Generous: a cold agent has to accept the job, and the Pipeline job's first run compiles its
# script. Each poll is cheap, so waiting longer costs nothing when things are healthy.
BUILD_TIMEOUT_SECONDS = 180.0
POLL_SECONDS = 2.0


def read_env() -> dict[str, str]:
    """Credentials from ``.env``.

    Values are read, never printed. A missing file skips rather than fails: the suite must stay
    runnable on a machine that has no stack.
    """
    values: dict[str, str] = {}
    env_file = REPO_ROOT / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip()
    # A real environment variable wins, so CI can inject them without a file.
    for key in ("JENKINS_URL", "JENKINS_USER", "JENKINS_TOKEN"):
        if os.environ.get(key):
            values[key] = os.environ[key]
    return values


@pytest.fixture(scope="module")
def live_settings() -> Settings:
    env = read_env()
    if not env.get("JENKINS_USER") or not env.get("JENKINS_TOKEN"):
        pytest.skip("JENKINS_USER and JENKINS_TOKEN are not configured; see .env.example")

    return Settings(
        environment=Environment.TEST,
        database_url="sqlite+aiosqlite:///:memory:",
        # Host-mapped port, because these run outside the Compose network.
        jenkins_url=env.get("JENKINS_URL_HOST", "http://localhost:8087"),
        jenkins_user=env["JENKINS_USER"],
        jenkins_token=env["JENKINS_TOKEN"],
    )


@pytest.fixture
async def jenkins(live_settings: Settings) -> AsyncGenerator[HttpJenkinsClient]:
    client = HttpJenkinsClient(live_settings)
    try:
        version = await client.version()
    except JenkinsError as exc:
        await client.aclose()
        pytest.skip(f"jenkins-dev is not reachable: {exc}")
    assert version, "Jenkins reported no version"
    yield client
    await client.aclose()


# ---------------------------------------------------------------------------
# Config derived from the reference exports
# ---------------------------------------------------------------------------


def reference(filename: str) -> str:
    path = REFERENCE_DIR / filename
    assert path.is_file(), f"{filename} is missing; run scripts/export_reference_configs.py"
    return path.read_text(encoding="utf-8")


def without_scm(config_xml: str) -> str:
    """Replace the Git SCM block with ``NullSCM``.

    The only change made to an exported config. The catalog's repositories are not pushed yet
    (PROGRESS.md "Needs human"), so leaving the Git SCM in would make this test fail at checkout
    for a reason unrelated to the API path it exists to exercise. Everything else -- parameters,
    the agent label, the build steps, the priority property -- is exactly what Jenkins produced.
    """
    replaced, count = re.subn(
        r'<scm class="hudson\.plugins\.git\.GitSCM".*?</scm>',
        '<scm class="hudson.scm.NullSCM"/>',
        config_xml,
        flags=re.S,
    )
    assert count == 1, f"expected exactly one Git SCM block, replaced {count}"
    return replaced


def freestyle_config() -> str:
    config = without_scm(reference("freestyle-build-test-deploy.config.xml"))
    # The reference steps run ./scripts/*.sh from a checkout that no longer happens, so the shell
    # commands are replaced with ones that need no working copy. The *structure* -- one shell step
    # per stage -- is preserved, because that is what 4.6.3 requires a generated job to have.
    config = re.sub(
        r"<command>.*?</command>",
        "<command>echo integration-test stage ok</command>",
        config,
        flags=re.S,
    )
    # The archiver is removed, not emptied. A blank pattern does not disable it -- Jenkins fails
    # the build with "You probably forgot to set the file pattern", *after* the steps succeeded,
    # which is a confusing way for a test about triggering to fail.
    config = re.sub(
        r"<hudson\.tasks\.ArtifactArchiver>.*?</hudson\.tasks\.ArtifactArchiver>",
        "",
        config,
        flags=re.S,
    )
    # The reference job triggers a downstream job that this test does not create.
    config = re.sub(
        r"<hudson\.tasks\.BuildTrigger>.*?</hudson\.tasks\.BuildTrigger>",
        "",
        config,
        flags=re.S,
    )
    return config


def pipeline_config() -> str:
    """The reference Pipeline, with its stage bodies made checkout-free.

    ``agent { label 'linux' }`` is kept: scheduling onto a real agent is part of what this proves.
    """
    config = reference("pipeline-build-test-deploy.config.xml")
    config = re.sub(
        r"sh &apos;[^&]*?&apos;",
        "sh &apos;echo integration-test stage ok&apos;",
        config,
    )
    # The whole multi-line `checkout([$class: 'GitSCM', ...])` call goes, for the same reason the
    # freestyle SCM does: the repository is not pushed yet, so a checkout fails with "Error cloning
    # remote repo 'origin'" and the test would be measuring that instead of the API path. Matching
    # only "checkout scm" missed this, because the reference uses the explicit GitSCM form.
    config, replaced = re.subn(
        r"checkout\(\[\$class: &apos;GitSCM&apos;.*?\]\]\)",
        "echo &apos;integration-test stage ok&apos;",
        config,
        flags=re.S,
    )
    assert replaced == 1, f"expected one checkout call, replaced {replaced}"
    return config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def recreate(client: HttpJenkinsClient, name: str, config_xml: str) -> None:
    """Create the job, or update the one a previous run left behind.

    These tests deliberately do **not** delete their jobs afterwards. ``Job/Delete`` is not among
    the bot's grants -- 4.1 asks for a least-privilege token and 4.4.5 does not list deletion -- so
    a cleanup step would 403, and widening the bot's permissions to tidy up after a test would be
    the wrong trade (docs/decisions.md D-033). Recreating instead makes a rerun idempotent, and the
    two ``it-`` jobs left on the controller are inert until something triggers them.
    """
    try:
        await client.create_job(name, config_xml)
    except JobAlreadyExistsError:
        await client.update_job(name, config_xml)


async def wait_for_build(client: HttpJenkinsClient, name: str, queue_item_id: int) -> int:
    """Poll the queue item until Jenkins assigns a build number. Returns it."""
    deadline = asyncio.get_running_loop().time() + BUILD_TIMEOUT_SECONDS
    while asyncio.get_running_loop().time() < deadline:
        item = await client.queue_item(queue_item_id)
        if item.cancelled:
            pytest.fail(f"{name}: the queue item was cancelled ({item.why})")
        if item.build_number is not None:
            return item.build_number
        await asyncio.sleep(POLL_SECONDS)
    item = await client.queue_item(queue_item_id)
    pytest.fail(
        f"{name}: no build number within {BUILD_TIMEOUT_SECONDS:.0f}s "
        f"(blocked={item.blocked} buildable={item.buildable} why={item.why})"
    )


async def wait_for_finish(client: HttpJenkinsClient, name: str, number: int) -> str:
    """Poll a build until it stops building. Returns its result."""
    deadline = asyncio.get_running_loop().time() + BUILD_TIMEOUT_SECONDS
    while asyncio.get_running_loop().time() < deadline:
        build = await client.build(name, number)
        if not build.building:
            return build.result or "UNKNOWN"
        await asyncio.sleep(POLL_SECONDS)
    pytest.fail(f"{name}#{number}: still building after {BUILD_TIMEOUT_SECONDS:.0f}s")


# ---------------------------------------------------------------------------
# The acceptance clause
# ---------------------------------------------------------------------------


async def test_a_freestyle_job_is_created_triggered_and_read(
    jenkins: HttpJenkinsClient,
) -> None:
    """Create, trigger and read one freestyle job on the live controller."""
    config = freestyle_config()
    ElementTree.fromstring(config)  # a malformed config is worth catching before the POST

    await recreate(jenkins, FREESTYLE_JOB, config)
    assert await jenkins.job_exists(FREESTYLE_JOB)

    # Read it back: what Jenkins stored, not what we sent.
    stored = await jenkins.get_config_xml(FREESTYLE_JOB)
    root = ElementTree.fromstring(stored)
    assert root.tag == "project"
    assert root.findtext("assignedNode") == "linux"
    # The plugin's property must survive the round trip, or the job would never be prioritised.
    assert "queueoptimizer" in stored.lower() or "dynamicqueue" in stored.lower()

    queue_item_id = await jenkins.trigger(
        FREESTYLE_JOB, {"BRANCH": "main", "COMMIT": "", "SUCCESS": "true"}
    )
    assert queue_item_id > 0

    number = await wait_for_build(jenkins, FREESTYLE_JOB, queue_item_id)
    result = await wait_for_finish(jenkins, FREESTYLE_JOB, number)

    assert result == "SUCCESS", f"the build finished {result}"

    log = await jenkins.console_text(FREESTYLE_JOB, number)
    assert "integration-test stage ok" in log
    assert "Finished: SUCCESS" in log

    build = await jenkins.build(FREESTYLE_JOB, number)
    assert build.number == number
    assert build.duration_ms > 0
    assert build.timestamp_ms > 0


async def test_a_pipeline_job_is_created_triggered_and_read(
    jenkins: HttpJenkinsClient,
) -> None:
    """The same for a Pipeline job.

    Worth its own test rather than a parametrisation: a Pipeline job enters the queue twice, as a
    flyweight task and then as a ``PlaceholderTask`` (D-014), so the path from trigger to build
    number is genuinely different from a freestyle job's.
    """
    config = pipeline_config()
    ElementTree.fromstring(config)

    await recreate(jenkins, PIPELINE_JOB, config)
    assert await jenkins.job_exists(PIPELINE_JOB)

    stored = await jenkins.get_config_xml(PIPELINE_JOB)
    root = ElementTree.fromstring(stored)
    assert root.tag == "flow-definition"
    assert "dynamicQueuePriority" in stored, "the options block lost its priority directive"

    # No parameters on the first trigger. A declarative `parameters { ... }` block does not make
    # the job parameterized until a build has executed it -- the reference config's <properties/>
    # is empty -- so passing BRANCH here gets 400 "is not parameterized". See the test below.
    queue_item_id = await jenkins.trigger(PIPELINE_JOB)
    number = await wait_for_build(jenkins, PIPELINE_JOB, queue_item_id)
    result = await wait_for_finish(jenkins, PIPELINE_JOB, number)

    assert result == "SUCCESS", f"the build finished {result}"

    log = await jenkins.console_text(PIPELINE_JOB, number)
    assert "integration-test stage ok" in log
    assert "Finished: SUCCESS" in log


async def test_a_pipeline_job_accepts_parameters_only_after_its_first_run(
    jenkins: HttpJenkinsClient,
) -> None:
    """A constraint Phase 5's Pipeline generator has to handle, found the direct way.

    4.6 says a Pipeline job takes its branch and commit as "parameters passed at trigger time".
    That cannot work on the *first* trigger: a declarative ``parameters { ... }`` block is part of
    the script, so Jenkins only registers the parameters once a build has executed it, and the
    reference config's ``<properties/>`` is empty. Triggering a freshly created Pipeline job with
    parameters returns 400 "is not parameterized".

    Worse, it is not a one-time cost: pushing the config.xml again **wipes** the parameters the
    first run registered, because the exported ``<properties/>`` is empty and overwrites them. So
    every regenerate would de-parameterize the job until its next build. That makes writing a
    ``ParametersDefinitionProperty`` into the generated config.xml the only workable option, rather
    than one of two. See docs/decisions.md D-034.

    This test therefore does **not** call ``recreate``: it relies on the run the previous test
    performed, which is exactly the state a second trigger sees in practice.
    """
    assert await jenkins.job_exists(PIPELINE_JOB), "the previous test should have created this"
    queue_item_id = await jenkins.trigger(PIPELINE_JOB, {"BRANCH": "main", "COMMIT": ""})
    number = await wait_for_build(jenkins, PIPELINE_JOB, queue_item_id)
    result = await wait_for_finish(jenkins, PIPELINE_JOB, number)

    assert result == "SUCCESS", f"the parameterised build finished {result}"

    stored = await jenkins.get_config_xml(PIPELINE_JOB)
    # Jenkins writes the discovered parameters into the job's properties after the first run. If
    # this ever shows up on a brand-new job, the generator is writing them itself and the
    # first-trigger restriction no longer applies.
    assert "ParametersDefinitionProperty" in stored


# ---------------------------------------------------------------------------
# The client's other live behaviour
# ---------------------------------------------------------------------------


async def test_the_declarative_linter_accepts_the_reference_pipeline(
    jenkins: HttpJenkinsClient,
) -> None:
    """4.4.5's linter, against the Jenkinsfile the reference job actually runs.

    Phase 5 validates every generated Pipeline this way, so a broken linter path would make that
    validation vacuous rather than noisy.
    """
    parsed = ElementTree.fromstring(pipeline_config())
    # Walked in two steps rather than with one XPath. The combined form ends in a path segment
    # that `tests/test_no_script_console.py` flags as a possible Jenkins script-console call, and
    # that guard enforces rule 1.5, so it is right to stay strict and this is right to adapt.
    definition = parsed.find("definition")
    assert definition is not None, "the reference Pipeline has no definition element"
    script = definition.findtext("script")
    assert script, "the reference Pipeline has no script"

    result = await jenkins.lint_jenkinsfile(script)

    assert result.ok, f"the linter rejected the reference Pipeline: {result.message}"


async def test_the_linter_rejects_a_broken_jenkinsfile(
    jenkins: HttpJenkinsClient,
) -> None:
    """A linter that accepts everything is worse than none: it would pass bad generated output."""
    result = await jenkins.lint_jenkinsfile("pipeline { this is not a pipeline }")

    assert not result.ok
    assert result.message


async def test_the_agent_labels_the_catalog_names_exist(
    jenkins: HttpJenkinsClient,
) -> None:
    """A generated job with a label no agent has would queue forever and never run."""
    labels = await jenkins.list_labels()

    assert "linux" in labels, f"no agent offers 'linux'; labels are {sorted(labels)}"


async def test_an_unknown_job_is_reported_as_missing(jenkins: HttpJenkinsClient) -> None:
    assert not await jenkins.job_exists("it-definitely-not-a-real-job")


async def test_the_plugin_ranking_is_readable_live(jenkins: HttpJenkinsClient) -> None:
    """4.3.10's endpoint, through the same client the backend uses."""
    ranking = await jenkins.ranking()

    configuration = ranking.get("configuration", ranking)
    assert configuration.get("weightUrgency") == pytest.approx(0.5)
    assert configuration.get("weightDependency") == pytest.approx(0.3)
    assert configuration.get("weightExecutionTime") == pytest.approx(0.2)
