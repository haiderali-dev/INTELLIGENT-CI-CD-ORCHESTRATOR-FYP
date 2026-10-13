"""Rendered jobs against a live ``jenkins-dev``: the linter integration test (Phase 5 acceptance).

Marked ``integration``:

    uv run python -m pytest -m integration tests/test_integration_generation.py

Two questions only a real controller can answer:

* **Does the declarative linter accept every Jenkinsfile the generator can produce?** Each service,
  each generating action, with and without extra stages, through the default plan and the real
  renderer. A deliberately broken Jenkinsfile must be rejected, or a pass would mean nothing.
* **Does Jenkins keep what the templates write?** Jenkins drops a downstream trigger that names a
  job that does not exist yet (the reason the exporter creates its downstream job first), so the
  chain is created last job first, and the stored config.xml is read back to confirm the
  triggers, dependency names, priority and parameter defaults all survived.
"""

from __future__ import annotations

import itertools
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest

from app.ai.intent import Action, ExtraStage, Intent, TargetEnvironment, Urgency
from app.core.settings import Environment, Settings
from app.generation.planner import PlannerError, default_plan
from app.generation.render import RenderedArtifact, render
from app.generation.spec import Assistant, GenerationSpec
from app.services.catalog import Catalog, CatalogService
from app.services.jenkins import HttpJenkinsClient, JenkinsError
from tests.test_integration_jenkins import read_env, recreate

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]
ACTIONS = (Action.BUILD, Action.TEST, Action.DEPLOY, Action.BUILD_TEST_DEPLOY)


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
def catalog() -> Catalog:
    return Catalog(REPO_ROOT / "catalog" / "services.yaml")


def generated(
    catalog: Catalog, service: CatalogService, intent: Intent, assistant: Assistant
) -> tuple[GenerationSpec, RenderedArtifact]:
    plan = default_plan(intent, service)
    spec = GenerationSpec(
        assistant=assistant,
        service=service.name,
        repo=service.repo,
        branch=service.default_branch,
        agent_label=service.agent_label,
        priority=intent.urgency or Urgency.MEDIUM,
        stages=plan.stages,
    )
    return spec, render(spec, service, action=intent.action)


def every_pipeline(catalog: Catalog) -> list[tuple[str, RenderedArtifact]]:
    """Each service and generating action, with no extra stages and with every one it offers."""
    found = []
    for service, action in itertools.product(catalog.services(), ACTIONS):
        offered = tuple(
            stage
            for stage in (ExtraStage.LINT, ExtraStage.SECURITY_SCAN, ExtraStage.INTEGRATION_TESTS)
            if stage.value in service.extra_stages
            or (stage is ExtraStage.INTEGRATION_TESTS and service.suite("integration"))
        )
        for extras in ((), offered):
            intent = Intent(
                action=action,
                service=service.name,
                environment=TargetEnvironment.STAGING,
                urgency=Urgency.HIGH,
                extra_stages=extras,
            )
            try:
                _, artifact = generated(catalog, service, intent, Assistant.PIPELINE)
            except PlannerError:
                continue
            label = f"{service.name} {action.value} {'+'.join(e.value for e in extras) or 'plain'}"
            found.append((label, artifact))
    return found


async def test_the_linter_accepts_every_jenkinsfile_the_generator_produces(
    jenkins: HttpJenkinsClient, catalog: Catalog
) -> None:
    pipelines = every_pipeline(catalog)
    assert len(pipelines) >= 14

    rejected = []
    for label, artifact in pipelines:
        result = await jenkins.lint_jenkinsfile(artifact.jenkinsfile or "")
        if not result.ok:
            rejected.append(f"{label}: {result.message}")

    assert not rejected, rejected


async def test_the_linter_rejects_a_broken_jenkinsfile(
    jenkins: HttpJenkinsClient, catalog: Catalog
) -> None:
    """Without this, a linter that accepted anything would make the test above meaningless."""
    _, artifact = every_pipeline(catalog)[0]
    broken = (artifact.jenkinsfile or "").replace("stages {", "stagez {", 1)

    result = await jenkins.lint_jenkinsfile(broken)

    assert not result.ok


async def test_jenkins_keeps_the_chain_the_templates_write(
    jenkins: HttpJenkinsClient, catalog: Catalog
) -> None:
    service = catalog.require("payment-service")
    intent = Intent(
        action=Action.BUILD_TEST_DEPLOY,
        service=service.name,
        environment=TargetEnvironment.STAGING,
        urgency=Urgency.HIGH,
        extra_stages=(ExtraStage.LINT,),
    )
    _, artifact = generated(catalog, service, intent, Assistant.FREESTYLE)

    # Last job first: a trigger naming a job that does not exist yet is dropped on save.
    for job in reversed(artifact.jobs):
        await recreate(jenkins, job.name, job.config_xml)

    for job in artifact.jobs:
        stored = await jenkins.get_config_xml(job.name)
        assert "<level>HIGH</level>" in stored, job.name
        assert f"<dependsOn>{job.depends_on}</dependsOn>" in stored, job.name
        if job.triggers is not None:
            assert f"<childProjects>{job.triggers}</childProjects>" in stored, job.name
        else:
            assert "hudson.tasks.BuildTrigger" not in stored, job.name
        assert f"<defaultValue>{artifact.parameters['COMMIT']}</defaultValue>" in stored, job.name


async def test_jenkins_keeps_the_pipeline_job_the_templates_write(
    jenkins: HttpJenkinsClient, catalog: Catalog
) -> None:
    service = catalog.require("auth-service")
    intent = Intent(
        action=Action.DEPLOY,
        service=service.name,
        environment=TargetEnvironment.STAGING,
        urgency=Urgency.LOW,
    )
    _, artifact = generated(catalog, service, intent, Assistant.PIPELINE)
    job = artifact.first_job

    await recreate(jenkins, job.name, job.config_xml)
    stored = await jenkins.get_config_xml(job.name)

    assert "<level>LOW</level>" in stored
    assert "hudson.model.ParametersDefinitionProperty" in stored
    assert "<sandbox>true</sandbox>" in stored
    assert "dynamicQueuePriority(level: &apos;LOW&apos;)" in stored
