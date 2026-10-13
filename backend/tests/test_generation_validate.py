"""T5.4: ``FreestyleValidator`` and ``PipelineValidator`` (BUILD_PROMPT 4.6.3).

The checks run in 4.6.3's order and every one is reported, because the preview shows them as a
checklist. Failures name their cause (plan, input or template), because only plan errors go back
to the model for repair (4.6.2).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.ai.intent import Action, Urgency
from app.generation.render import RenderedArtifact, RenderedJob, render
from app.generation.spec import Assistant, GenerationSpec, Stage
from app.generation.validate import (
    CheckStatus,
    FreestyleValidator,
    PipelineValidator,
    ValidationReport,
    parse_spec,
    validator_for,
)
from app.services.catalog import Catalog
from app.services.git import FakeGitClient, GitError
from app.services.jenkins import FakeJenkinsClient, JenkinsError, LintResult

REPO_ROOT = Path(__file__).resolve().parents[2]
PAYMENT_REPO = "https://github.com/haiderali-dev/payment-service.git"
MAIN_SHA = "998844b0159c13bf8ab32e1e2da2f4a187b7eb61"
OLD_SHA = "1111111111111111111111111111111111111111"

ORDER = [
    "spec_schema",
    "catalog_and_git",
    "environment",
    "stage_order",
    "metacharacters",
    "artifact",
    "job_names",
    "no_production",
]


@pytest.fixture
def catalog() -> Catalog:
    return Catalog(REPO_ROOT / "catalog" / "services.yaml")


@pytest.fixture
def git() -> FakeGitClient:
    client = FakeGitClient()
    client.add_branch(PAYMENT_REPO, "main", MAIN_SHA)
    client.add_branch(PAYMENT_REPO, "feature/refund", OLD_SHA)
    return client


@pytest.fixture
def jenkins() -> FakeJenkinsClient:
    return FakeJenkinsClient()


def stage(name: str, template: str, suite: str | None = None, env: str | None = None) -> Stage:
    return Stage(name=name, template=template, suite=suite, environment=env)


GOOD_STAGES = (
    stage("Build", "build"),
    stage("Unit tests", "test", "unit"),
    stage("Deploy to staging", "deploy", env="staging"),
)


def spec(
    assistant: Assistant = Assistant.FREESTYLE, *stages: Stage, **fields: Any
) -> GenerationSpec:
    values: dict[str, Any] = {
        "assistant": assistant,
        "service": "payment-service",
        "repo": PAYMENT_REPO,
        "branch": "main",
        "commit": MAIN_SHA,
        "agent_label": "linux",
        "priority": Urgency.HIGH,
        "stages": stages or GOOD_STAGES,
    }
    values.update(fields)
    return GenerationSpec(**values)


async def check(
    catalog: Catalog,
    git: FakeGitClient,
    jenkins: FakeJenkinsClient,
    generation_spec: GenerationSpec,
    artifact: RenderedArtifact | None = None,
) -> ValidationReport:
    if artifact is None:
        artifact = render(
            generation_spec,
            catalog.require(generation_spec.service),
            action=Action.BUILD_TEST_DEPLOY,
        )
    return await validator_for(generation_spec, catalog, git, jenkins).validate(
        generation_spec, artifact
    )


def status(report: ValidationReport, name: str) -> CheckStatus:
    return next(item.status for item in report.checks if item.name == name)


def message(report: ValidationReport, name: str) -> str:
    return next(item.message for item in report.checks if item.name == name)


# ---------------------------------------------------------------------------
# A valid spec, both assistants
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("assistant", list(Assistant))
async def test_a_valid_spec_passes_every_check_in_order(
    catalog: Catalog, git: FakeGitClient, jenkins: FakeJenkinsClient, assistant: Assistant
) -> None:
    report = await check(catalog, git, jenkins, spec(assistant))

    assert [item.name for item in report.checks] == ORDER
    assert report.ok, [item for item in report.checks if item.status is not CheckStatus.PASSED]
    assert all(item.status is CheckStatus.PASSED for item in report.checks)


def test_each_assistant_gets_its_validator(
    catalog: Catalog, git: FakeGitClient, jenkins: FakeJenkinsClient
) -> None:
    assert isinstance(
        validator_for(spec(Assistant.FREESTYLE), catalog, git, jenkins), FreestyleValidator
    )
    assert isinstance(
        validator_for(spec(Assistant.PIPELINE), catalog, git, jenkins), PipelineValidator
    )


# ---------------------------------------------------------------------------
# 1. Spec schema
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "version: [1",
        "- a list",
        "version: 1\nassistant: freestyle\n",
        spec().to_yaml().replace("commit: " + MAIN_SHA, "commit: HEAD~1"),
        spec().to_yaml().replace("template: build", "template: build\n    command: rm -rf /"),
    ],
)
def test_an_edited_spec_that_is_not_a_spec_fails_the_first_check(text: str) -> None:
    parsed = parse_spec(text)

    assert isinstance(parsed, ValidationReport)
    assert [item.name for item in parsed.checks] == ["spec_schema"]
    assert not parsed.ok
    assert parsed.checks[0].cause == "input"


def test_a_valid_edit_parses() -> None:
    assert parse_spec(spec().to_yaml()) == spec()


# ---------------------------------------------------------------------------
# 2. Catalog and Git
# ---------------------------------------------------------------------------


async def test_the_repository_and_label_must_be_the_catalogs(
    catalog: Catalog, git: FakeGitClient, jenkins: FakeJenkinsClient
) -> None:
    """An edited YAML must not point the agents at someone else's code."""
    edited = spec(repo="https://github.com/attacker/payment-service.git", agent_label="windows")
    artifact = render(spec(), catalog.require("payment-service"), action=Action.BUILD_TEST_DEPLOY)

    report = await check(catalog, git, jenkins, edited, artifact)

    assert status(report, "catalog_and_git") is CheckStatus.FAILED
    assert "attacker" in message(report, "catalog_and_git")
    assert "'linux' agents" in message(report, "catalog_and_git")


async def test_an_unknown_branch_fails(
    catalog: Catalog, git: FakeGitClient, jenkins: FakeJenkinsClient
) -> None:
    report = await check(catalog, git, jenkins, spec(branch="nope", commit=None))

    assert status(report, "catalog_and_git") is CheckStatus.FAILED
    assert "no branch called 'nope'" in message(report, "catalog_and_git")


async def test_an_unreachable_remote_warns_without_failing(
    catalog: Catalog, git: FakeGitClient, jenkins: FakeJenkinsClient
) -> None:
    """D-037: Jenkins fails the checkout honestly if the branch is wrong."""
    git.fail_with = GitError("timed out")

    report = await check(catalog, git, jenkins, spec())

    assert status(report, "catalog_and_git") is CheckStatus.WARNING
    assert report.ok


async def test_a_commit_that_is_not_a_tip_warns(
    catalog: Catalog, git: FakeGitClient, jenkins: FakeJenkinsClient
) -> None:
    report = await check(catalog, git, jenkins, spec(commit="2222222"))

    assert status(report, "catalog_and_git") is CheckStatus.WARNING
    assert "could not be confirmed" in message(report, "catalog_and_git")


async def test_a_stage_or_suite_the_service_lacks_is_a_plan_failure(
    catalog: Catalog, git: FakeGitClient, jenkins: FakeJenkinsClient
) -> None:
    edited = spec(
        Assistant.FREESTYLE,
        stage("Build", "build"),
        stage("E2E", "test", "e2e"),
        stage("Smoke", "smoke_test"),
    )
    artifact = render(spec(), catalog.require("payment-service"), action=Action.BUILD_TEST_DEPLOY)

    report = await check(catalog, git, jenkins, edited, artifact)

    failed = next(item for item in report.checks if item.name == "catalog_and_git")
    assert failed.status is CheckStatus.FAILED
    assert failed.cause == "plan"
    assert "no 'e2e' test suite" in failed.message
    assert "no 'smoke_test' stage" in failed.message


async def test_an_unknown_service_fails(
    catalog: Catalog, git: FakeGitClient, jenkins: FakeJenkinsClient
) -> None:
    artifact = render(spec(), catalog.require("payment-service"), action=Action.BUILD_TEST_DEPLOY)

    report = await check(catalog, git, jenkins, spec(service="billing-service"), artifact)

    assert status(report, "catalog_and_git") is CheckStatus.FAILED


# ---------------------------------------------------------------------------
# 3. Environment, 4. stage order
# ---------------------------------------------------------------------------


def test_a_capitalised_production_is_not_even_a_valid_spec() -> None:
    """Environments are lower case by pattern, so this never reaches the validator."""
    with pytest.raises(ValueError, match="environment"):
        stage("Ship", "deploy", env="Production")


@pytest.mark.parametrize("environment", ["production", "qa"])
async def test_a_deploy_outside_staging_fails(
    catalog: Catalog, git: FakeGitClient, jenkins: FakeJenkinsClient, environment: str
) -> None:
    edited = spec(
        Assistant.FREESTYLE, stage("Build", "build"), stage("Ship", "deploy", env=environment)
    )
    artifact = render(spec(), catalog.require("payment-service"), action=Action.BUILD_TEST_DEPLOY)

    report = await check(catalog, git, jenkins, edited, artifact)

    assert status(report, "environment") is CheckStatus.FAILED


@pytest.mark.parametrize(
    "stages",
    [
        (stage("Deploy", "deploy", env="staging"), stage("Build", "build")),
        (
            stage("Build", "build"),
            stage("Deploy", "deploy", env="staging"),
            stage("Unit", "test", "unit"),
        ),
        (stage("Unit", "test", "unit"), stage("Deploy", "deploy", env="staging")),
        (stage("Lint", "lint"), stage("Build", "build")),
        (stage("Build", "build"), stage("build", "test", "unit")),
    ],
    ids=[
        "deploy first",
        "test after deploy",
        "test without a build",
        "check before build",
        "same name",
    ],
)
async def test_stage_order_and_names(
    catalog: Catalog, git: FakeGitClient, jenkins: FakeJenkinsClient, stages: tuple[Stage, ...]
) -> None:
    edited = spec(Assistant.FREESTYLE, *stages)
    artifact = render(spec(), catalog.require("payment-service"), action=Action.BUILD_TEST_DEPLOY)

    report = await check(catalog, git, jenkins, edited, artifact)

    failed = next(item for item in report.checks if item.name == "stage_order")
    assert failed.status is CheckStatus.FAILED
    assert failed.cause == "plan"


# ---------------------------------------------------------------------------
# 5. Metacharacters, 6. the artifact, 7. job names, 8. no production
# ---------------------------------------------------------------------------


def _artifact(jobs: tuple[RenderedJob, ...], **parameters: str) -> RenderedArtifact:
    from app.db.models import JobType

    return RenderedArtifact(
        job_type=JobType.FREESTYLE,
        jobs=jobs,
        parameters=parameters or {"BRANCH": "main", "COMMIT": MAIN_SHA},
    )


GOOD_XML = (
    '<?xml version="1.1" encoding="UTF-8"?>\n<project><description>ok</description></project>\n'
)


async def test_a_metacharacter_in_a_parameter_fails(
    catalog: Catalog, git: FakeGitClient, jenkins: FakeJenkinsClient
) -> None:
    """A backstop: the spec's patterns stop these first, but this is the last line before Jenkins."""
    artifact = _artifact(
        (RenderedJob("fs-payment-service-build", GOOD_XML, 0),),
        BRANCH="main",
        COMMIT="refs/heads/main;curl evil",
    )

    report = await check(catalog, git, jenkins, spec(), artifact)

    assert status(report, "metacharacters") is CheckStatus.FAILED


async def test_malformed_xml_is_a_template_failure(
    catalog: Catalog, git: FakeGitClient, jenkins: FakeJenkinsClient
) -> None:
    artifact = _artifact(
        (RenderedJob("fs-payment-service-build", "<project><unclosed></project>", 0),)
    )

    report = await check(catalog, git, jenkins, spec(), artifact)

    failed = next(item for item in report.checks if item.name == "artifact")
    assert failed.status is CheckStatus.FAILED
    assert failed.cause == "template"
    assert report.failures_caused_by("template") == (failed,)


async def test_an_invalid_job_name_fails(
    catalog: Catalog, git: FakeGitClient, jenkins: FakeJenkinsClient
) -> None:
    artifact = _artifact((RenderedJob("fs payment/build", GOOD_XML, 0),))

    report = await check(catalog, git, jenkins, spec(), artifact)

    assert status(report, "job_names") is CheckStatus.FAILED


async def test_production_anywhere_in_what_reaches_jenkins_fails(
    catalog: Catalog, git: FakeGitClient, jenkins: FakeJenkinsClient
) -> None:
    edited = spec(Assistant.FREESTYLE, stage("Build", "build"), stage("Production check", "lint"))
    artifact = render(spec(), catalog.require("payment-service"), action=Action.BUILD_TEST_DEPLOY)

    report = await check(catalog, git, jenkins, edited, artifact)

    assert status(report, "no_production") is CheckStatus.FAILED


async def test_a_justification_may_mention_production(
    catalog: Catalog, git: FakeGitClient, jenkins: FakeJenkinsClient
) -> None:
    """The user's own reason is recorded, never sent to Jenkins, so it is not checked."""
    report = await check(
        catalog, git, jenkins, spec(justification="Fixes the production checkout outage")
    )

    assert status(report, "no_production") is CheckStatus.PASSED
    assert report.ok


# ---------------------------------------------------------------------------
# The declarative linter
# ---------------------------------------------------------------------------


async def test_the_pipeline_is_linted_and_the_chain_is_not(
    catalog: Catalog, git: FakeGitClient, jenkins: FakeJenkinsClient
) -> None:
    await check(catalog, git, jenkins, spec(Assistant.FREESTYLE))
    assert not [call for call in jenkins.calls if call[0] == "lint_jenkinsfile"]

    await check(catalog, git, jenkins, spec(Assistant.PIPELINE))
    assert [call for call in jenkins.calls if call[0] == "lint_jenkinsfile"]


async def test_a_jenkinsfile_the_linter_rejects_fails(
    catalog: Catalog, git: FakeGitClient, jenkins: FakeJenkinsClient
) -> None:
    jenkins.lint_ok = False
    jenkins.lint_message = "WorkflowScript: 3: Unknown stage section"

    report = await check(catalog, git, jenkins, spec(Assistant.PIPELINE))

    failed = next(item for item in report.checks if item.name == "artifact")
    assert failed.status is CheckStatus.FAILED
    assert failed.cause == "template"
    assert "Unknown stage section" in failed.message


async def test_a_linter_that_cannot_be_reached_is_not_a_pass(
    catalog: Catalog,
    git: FakeGitClient,
    jenkins: FakeJenkinsClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def unreachable(text: str) -> LintResult:
        raise JenkinsError("connection refused")

    monkeypatch.setattr(jenkins, "lint_jenkinsfile", unreachable)

    report = await check(catalog, git, jenkins, spec(Assistant.PIPELINE))

    assert status(report, "artifact") is CheckStatus.FAILED
    assert "could not be reached" in message(report, "artifact")


async def test_the_report_is_stored_as_json(
    catalog: Catalog, git: FakeGitClient, jenkins: FakeJenkinsClient
) -> None:
    record = (await check(catalog, git, jenkins, spec())).to_record()

    assert record["ok"] is True
    assert [item["name"] for item in record["checks"]] == ORDER
    json.dumps(record)
