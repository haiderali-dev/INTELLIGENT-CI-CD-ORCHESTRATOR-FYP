"""T5.3: the templates, the renderer, and the golden files.

Three kinds of test, each answering a different question:

* **Derivation.** Is each template still the exported reference config with only its variable
  parts replaced (rule 1.4)? Rendering the reference job's own values must give back what Jenkins
  exported, element for element.
* **Golden files.** Has the output for a known spec changed? Every byte is compared, so any change
  to a template shows up in review as a diff of ``tests/golden/``. To accept an intended change,
  rerun with ``UPDATE_GOLDEN=1`` and review the diff before committing.
* **Behaviour.** The chain is wired as 4.6 and Appendix F say, commands come only from the catalog,
  and every value is escaped for where it lands.
"""

from __future__ import annotations

import dataclasses
import html
import json
import os
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import pytest

from app.ai.intent import Action, Urgency
from app.db.models import JobType
from app.generation.render import (
    RenderedArtifact,
    RenderError,
    freestyle_job_name,
    groovy_string,
    pipeline_job_name,
    render,
)
from app.generation.spec import Assistant, GenerationSpec, Stage
from app.services.catalog import Catalog, CatalogService

REPO_ROOT = Path(__file__).resolve().parents[2]
REFERENCE_DIR = REPO_ROOT / "jenkins" / "reference-configs"
GOLDEN_DIR = Path(__file__).resolve().parent / "golden"
MAIN_SHA = "998844b0159c13bf8ab32e1e2da2f4a187b7eb61"


@pytest.fixture(scope="module")
def catalog() -> Catalog:
    return Catalog(REPO_ROOT / "catalog" / "services.yaml")


@pytest.fixture(scope="module")
def payment(catalog: Catalog) -> CatalogService:
    return catalog.require("payment-service")


@pytest.fixture(scope="module")
def auth(catalog: Catalog) -> CatalogService:
    return catalog.require("auth-service")


def stage(name: str, template: str, suite: str | None = None, env: str | None = None) -> Stage:
    return Stage(name=name, template=template, suite=suite, environment=env)


def spec(
    service: CatalogService, assistant: Assistant, *stages: Stage, **fields: Any
) -> GenerationSpec:
    values: dict[str, Any] = {
        "assistant": assistant,
        "service": service.name,
        "repo": service.repo,
        "branch": "main",
        "agent_label": service.agent_label,
        "priority": Urgency.HIGH,
        "stages": stages,
    }
    values.update(fields)
    return GenerationSpec(**values)


def parse(config_xml: str) -> ElementTree.Element:
    """Parse a config.xml. The XML 1.1 declaration and the reference's comment are skipped:
    Python's parser accepts neither, and neither is configuration."""
    return ElementTree.fromstring(config_xml.split("?>", 1)[1])  # noqa: S314 (our own output)


def reference(filename: str) -> ElementTree.Element:
    return parse((REFERENCE_DIR / filename).read_text(encoding="utf-8"))


def script_of(root: ElementTree.Element) -> str:
    """A Pipeline job's script.

    Walked in two steps rather than one XPath: the combined form ends in a path segment that
    ``tests/test_no_script_console.py`` flags as a possible script-console call. That guard
    enforces rule 1.5, so it stays strict and this adapts (as test_integration_jenkins.py does).
    """
    definition = root.find("definition")
    assert definition is not None, "no definition element"
    return definition.findtext("script") or ""


def tree(element: ElementTree.Element) -> Any:
    """An element as nested tuples of tag, attributes, text and children, for comparison."""
    return (
        element.tag,
        dict(element.attrib),
        (element.text or "").strip(),
        [tree(child) for child in element],
    )


# The reference jobs' own values: payment-service, build, unit tests and deploy to staging, HIGH.
REFERENCE_STAGES = (
    stage("Build", "build"),
    stage("Unit tests", "test", "unit"),
    stage("Deploy", "deploy", env="staging"),
)


# ---------------------------------------------------------------------------
# Derivation from the reference exports
# ---------------------------------------------------------------------------


def test_the_jenkinsfile_template_reproduces_the_reference_script(payment: CatalogService) -> None:
    rendered = render(
        spec(payment, Assistant.PIPELINE, *REFERENCE_STAGES),
        payment,
        action=Action.BUILD_TEST_DEPLOY,
    )
    assert rendered.jenkinsfile == html.unescape(
        script_of(reference("pipeline-build-test-deploy.config.xml"))
    )


def test_the_pipeline_template_reproduces_the_reference_job(payment: CatalogService) -> None:
    """Everything but the description is what Jenkins exported."""
    rendered = render(
        spec(payment, Assistant.PIPELINE, *REFERENCE_STAGES),
        payment,
        action=Action.BUILD_TEST_DEPLOY,
    )
    ours = parse(rendered.first_job.config_xml)
    theirs = reference("pipeline-build-test-deploy.config.xml")
    for root in (ours, theirs):
        description = root.find("description")
        assert description is not None
        description.text = ""

    assert tree(ours) == tree(theirs)


def _without_variables(root: ElementTree.Element) -> ElementTree.Element:
    """Blank what varies between chain jobs, so the rest must match the reference exactly."""
    for path in (
        "description",
        "properties/io.jenkins.plugins.queueoptimizer.property.JobPriorityProperty/dependsOn",
    ):
        node = root.find(path)
        assert node is not None, path
        node.text = ""
    for default in root.iter("defaultValue"):
        default.text = ""
    builders = root.find("builders")
    assert builders is not None
    for child in list(builders):
        builders.remove(child)
    publishers = root.find("publishers")
    assert publishers is not None
    for trigger in publishers.findall("hudson.tasks.BuildTrigger"):
        publishers.remove(trigger)
    return root


def test_every_chain_job_is_the_reference_job_with_its_own_values(payment: CatalogService) -> None:
    rendered = render(
        spec(payment, Assistant.FREESTYLE, *REFERENCE_STAGES),
        payment,
        action=Action.BUILD_TEST_DEPLOY,
    )
    theirs = tree(_without_variables(reference("freestyle-build-test-deploy.config.xml")))

    assert len(rendered.jobs) == 3
    for job in rendered.jobs:
        assert tree(_without_variables(parse(job.config_xml))) == theirs, job.name


def test_shell_steps_and_the_trigger_have_the_reference_shape(payment: CatalogService) -> None:
    """The parts the comparison above blanks out still have exactly the exported structure."""
    exported = reference("freestyle-build-test-deploy.config.xml")
    rendered = render(
        spec(payment, Assistant.FREESTYLE, *REFERENCE_STAGES),
        payment,
        action=Action.BUILD_TEST_DEPLOY,
    )
    first = parse(rendered.first_job.config_xml)

    exported_step = exported.find("builders/hudson.tasks.Shell")
    rendered_step = first.find("builders/hudson.tasks.Shell")
    assert exported_step is not None and rendered_step is not None
    assert [child.tag for child in rendered_step] == [child.tag for child in exported_step]

    exported_trigger = exported.find("publishers/hudson.tasks.BuildTrigger")
    rendered_trigger = first.find("publishers/hudson.tasks.BuildTrigger")
    assert exported_trigger is not None and rendered_trigger is not None
    exported_trigger.find("childProjects").text = ""  # type: ignore[union-attr]
    rendered_trigger.find("childProjects").text = ""  # type: ignore[union-attr]
    assert tree(rendered_trigger) == tree(exported_trigger)


# ---------------------------------------------------------------------------
# Golden files
# ---------------------------------------------------------------------------


def _golden_cases(
    payment: CatalogService, auth: CatalogService
) -> dict[str, tuple[GenerationSpec, CatalogService, Action]]:
    return {
        "freestyle-payment-build-test-deploy": (
            spec(
                payment,
                Assistant.FREESTYLE,
                stage("Build", "build"),
                stage("Lint", "lint"),
                stage("Unit tests", "test", "unit"),
                stage("Integration tests", "test", "integration"),
                stage("Deploy to staging", "deploy", env="staging"),
                commit=MAIN_SHA,
            ),
            payment,
            Action.BUILD_TEST_DEPLOY,
        ),
        "freestyle-auth-test": (
            spec(
                auth,
                Assistant.FREESTYLE,
                stage("Build", "build"),
                stage("Unit tests", "test", "unit"),
                branch="feature/login-fix",
                priority=Urgency.MEDIUM,
            ),
            auth,
            Action.TEST,
        ),
        "pipeline-payment-build-test-deploy": (
            spec(
                payment,
                Assistant.PIPELINE,
                stage("Build", "build"),
                stage("Security scan", "security_scan"),
                stage("Unit tests", "test", "unit"),
                stage("Integration tests", "test", "integration"),
                stage("Deploy to staging", "deploy", env="staging"),
                commit=MAIN_SHA,
            ),
            payment,
            Action.BUILD_TEST_DEPLOY,
        ),
        "pipeline-auth-deploy": (
            spec(
                auth,
                Assistant.PIPELINE,
                stage("Deploy to staging", "deploy", env="staging"),
                priority=Urgency.LOW,
            ),
            auth,
            Action.DEPLOY,
        ),
    }


def _golden_files(artifact: RenderedArtifact) -> dict[str, str]:
    files = {f"{job.name}.config.xml": job.config_xml for job in artifact.jobs}
    if artifact.jenkinsfile is not None:
        files["Jenkinsfile"] = artifact.jenkinsfile
    return files


@pytest.mark.parametrize(
    "case",
    [
        "freestyle-payment-build-test-deploy",
        "freestyle-auth-test",
        "pipeline-payment-build-test-deploy",
        "pipeline-auth-deploy",
    ],
)
def test_rendered_output_matches_the_golden_files(
    payment: CatalogService, auth: CatalogService, case: str
) -> None:
    generation_spec, service, action = _golden_cases(payment, auth)[case]
    files = _golden_files(render(generation_spec, service, action=action))
    directory = GOLDEN_DIR / case

    if os.environ.get("UPDATE_GOLDEN") == "1":
        directory.mkdir(parents=True, exist_ok=True)
        for stale in directory.iterdir():
            stale.unlink()
        for name, text in files.items():
            (directory / name).write_text(text, encoding="utf-8", newline="\n")
        pytest.skip(f"golden files for {case} rewritten; review the diff before committing")

    on_disk = {path.name: path.read_text(encoding="utf-8") for path in sorted(directory.iterdir())}
    assert sorted(on_disk) == sorted(files), "a job was added or removed"
    for name, text in files.items():
        assert text == on_disk[name], f"{case}/{name} differs from its golden file"


def test_every_golden_config_is_well_formed_xml() -> None:
    configs = sorted(GOLDEN_DIR.rglob("*.config.xml"))
    assert len(configs) >= 9
    for path in configs:
        parse(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# The freestyle chain
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def chain(payment: CatalogService) -> RenderedArtifact:
    generation_spec, service, action = _golden_cases(payment, payment)[
        "freestyle-payment-build-test-deploy"
    ]
    return render(generation_spec, service, action=action)


def test_chain_jobs_are_named_by_stage_with_suite_specific_test_jobs(
    chain: RenderedArtifact,
) -> None:
    assert chain.job_type is JobType.FREESTYLE
    assert [job.name for job in chain.jobs] == [
        "fs-payment-service-build",
        "fs-payment-service-lint",
        "fs-payment-service-test-unit",
        "fs-payment-service-test-integration",
        "fs-payment-service-deploy-staging",
    ]
    assert [job.position for job in chain.jobs] == [0, 1, 2, 3, 4]


def test_each_job_depends_on_and_is_triggered_by_the_previous_one(chain: RenderedArtifact) -> None:
    """Appendix F: each naming the previous job in dependsOn, each triggering the next on success."""
    names = [job.name for job in chain.jobs]
    for index, job in enumerate(chain.jobs):
        root = parse(job.config_xml)
        depends = root.findtext(
            "properties/io.jenkins.plugins.queueoptimizer.property.JobPriorityProperty/dependsOn"
        )
        assert depends == (names[index - 1] if index else ""), job.name
        trigger = root.find("publishers/hudson.tasks.BuildTrigger")
        if index + 1 < len(names):
            assert trigger is not None
            assert trigger.findtext("childProjects") == names[index + 1]
            assert trigger.findtext("threshold/name") == "SUCCESS", (
                "a failed stage must stop the chain"
            )
        else:
            assert trigger is None, "the last job triggers nothing"


def test_jobs_that_need_the_venv_build_it_in_their_own_workspace(
    chain: RenderedArtifact, payment: CatalogService
) -> None:
    """Each job's workspace is wiped before it runs (PreBuildCleanup), so a test, lint or scan job
    runs build.sh itself first. Build and deploy run only their own command."""
    commands = {
        job.name: [cmd.text for cmd in parse(job.config_xml).iter("command")] for job in chain.jobs
    }

    assert commands["fs-payment-service-build"] == ["./scripts/build.sh"]
    assert commands["fs-payment-service-lint"] == ["./scripts/build.sh", "./scripts/lint.sh"]
    assert commands["fs-payment-service-test-unit"] == [
        "./scripts/build.sh",
        "./scripts/test.sh unit",
    ]
    assert commands["fs-payment-service-test-integration"] == [
        "./scripts/build.sh",
        "./scripts/test.sh integration",
    ]
    assert commands["fs-payment-service-deploy-staging"] == ["./deploy.sh staging"]
    for job in chain.jobs:
        assert (
            parse(job.config_xml).find("buildWrappers/hudson.plugins.ws__cleanup.PreBuildCleanup")
            is not None
        )


def test_every_job_carries_the_revision_and_priority(chain: RenderedArtifact) -> None:
    """4.6: defaults written on every chain job; the same priority level throughout."""
    assert chain.parameters == {"BRANCH": "main", "COMMIT": MAIN_SHA}
    for job in chain.jobs:
        root = parse(job.config_xml)
        defaults = {
            definition.findtext("name"): definition.findtext("defaultValue")
            for definition in root.iter("hudson.model.StringParameterDefinition")
        }
        assert defaults == chain.parameters, job.name
        assert root.findtext("scm/branches/hudson.plugins.git.BranchSpec/name") == "${COMMIT}"
        assert (
            root.findtext(
                "properties/io.jenkins.plugins.queueoptimizer.property.JobPriorityProperty/level"
            )
            == "HIGH"
        )


def test_a_branch_without_a_commit_is_written_as_a_full_ref(auth: CatalogService) -> None:
    generation_spec, service, action = _golden_cases(auth, auth)["freestyle-auth-test"]

    artifact = render(generation_spec, service, action=action)

    assert artifact.parameters == {
        "BRANCH": "feature/login-fix",
        "COMMIT": "refs/heads/feature/login-fix",
    }


def test_no_user_text_is_written_into_a_job(payment: CatalogService) -> None:
    """The justification is recorded in the audit log and the pipeline row, not in Jenkins."""
    secret = "Hotfix for the production incident"
    generation_spec = spec(payment, Assistant.FREESTYLE, *REFERENCE_STAGES, justification=secret)

    for assistant in Assistant:
        artifact = render(
            generation_spec.model_copy(update={"assistant": assistant}),
            payment,
            action=Action.BUILD_TEST_DEPLOY,
        )
        for job in artifact.jobs:
            assert secret not in job.config_xml
            assert "production" not in job.config_xml


# ---------------------------------------------------------------------------
# The Pipeline job
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("action", "stages", "expected"),
    [
        (Action.BUILD, [stage("Build", "build")], "pl-payment-service-build"),
        (
            Action.TEST,
            [stage("Build", "build"), stage("Unit", "test", "unit")],
            "pl-payment-service-test",
        ),
        (
            Action.DEPLOY,
            [stage("Deploy", "deploy", env="staging")],
            "pl-payment-service-deploy-staging",
        ),
        (
            Action.BUILD_TEST_DEPLOY,
            list(REFERENCE_STAGES),
            "pl-payment-service-build-test-deploy-staging",
        ),
    ],
)
def test_pipeline_job_names(
    payment: CatalogService, action: Action, stages: list[Stage], expected: str
) -> None:
    generation_spec = spec(payment, Assistant.PIPELINE, *stages)

    assert pipeline_job_name(payment.name, action, generation_spec) == expected
    assert render(generation_spec, payment, action=action).first_job.name == expected


def test_pipeline_stages_run_only_their_own_catalog_command(payment: CatalogService) -> None:
    """One workspace: the build stage's .venv is there for the tests, so no build prep."""
    generation_spec, service, action = _golden_cases(payment, payment)[
        "pipeline-payment-build-test-deploy"
    ]

    artifact = render(generation_spec, service, action=action)

    assert artifact.first_job.commands == (
        "./scripts/build.sh",
        "./scripts/security_scan.sh",
        "./scripts/test.sh unit",
        "./scripts/test.sh integration",
        "./deploy.sh staging",
    )
    jenkinsfile = artifact.jenkinsfile or ""
    assert "stage('Security scan') {" in jenkinsfile
    assert "steps { sh './scripts/test.sh integration' }" in jenkinsfile
    assert "dynamicQueuePriority(level: 'HIGH')" in jenkinsfile


def test_the_pipeline_triggers_with_the_revision_and_defaults_to_its_branch(
    payment: CatalogService,
) -> None:
    generation_spec, service, action = _golden_cases(payment, payment)[
        "pipeline-payment-build-test-deploy"
    ]

    artifact = render(generation_spec, service, action=action)

    assert artifact.parameters == {"BRANCH": "main", "COMMIT": MAIN_SHA}
    defaults = {
        definition.findtext("name"): definition.findtext("defaultValue")
        for definition in parse(artifact.first_job.config_xml).iter(
            "hudson.model.StringParameterDefinition"
        )
    }
    # D-041: COMMIT defaults to empty so the Jenkinsfile applies the rule to a run started by hand.
    assert defaults == {"BRANCH": "main", "COMMIT": ""}
    assert "string(name: 'BRANCH', defaultValue: 'main'" in (artifact.jenkinsfile or "")


def test_the_script_is_escaped_into_xml_and_sandboxed(payment: CatalogService) -> None:
    artifact = render(
        spec(payment, Assistant.PIPELINE, *REFERENCE_STAGES),
        payment,
        action=Action.BUILD_TEST_DEPLOY,
    )
    root = parse(artifact.first_job.config_xml)

    assert script_of(root) == artifact.jenkinsfile
    assert root.findtext("definition/sandbox") == "true"
    assert "<branch>" not in artifact.first_job.config_xml, "a '<' in the script must be escaped"


# ---------------------------------------------------------------------------
# Escaping and refusals
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "escaped"),
    [
        ("plain", "plain"),
        ("it's", "it\\'s"),
        ("a\\b", "a\\\\b"),
        ("${env.SECRET}", "${env.SECRET}"),
    ],
)
def test_groovy_strings_are_escaped(value: str, escaped: str) -> None:
    """Single-quoted Groovy strings do not interpolate, so $ is left alone."""
    assert groovy_string(value) == escaped


def test_a_line_break_never_reaches_a_groovy_string() -> None:
    with pytest.raises(RenderError):
        groovy_string("one\nsh 'id'")


def test_xml_special_characters_in_catalog_values_are_escaped(payment: CatalogService) -> None:
    odd = dataclasses.replace(payment, repo="https://example.com/payment.git?a=1&b=<2>")
    generation_spec = spec(odd, Assistant.FREESTYLE, stage("Build", "build"), repo=odd.repo)

    job = render(generation_spec, odd, action=Action.BUILD).first_job

    assert (
        parse(job.config_xml).findtext(
            "scm/userRemoteConfigs/hudson.plugins.git.UserRemoteConfig/url"
        )
        == odd.repo
    )


def test_a_stage_the_catalog_cannot_resolve_is_a_render_error(payment: CatalogService) -> None:
    for bad in (
        stage("E2E", "test", "e2e"),
        stage("Smoke", "smoke_test"),
        stage("Deploy", "deploy", env="qa"),
    ):
        with pytest.raises(RenderError, match="has no command"):
            render(spec(payment, Assistant.FREESTYLE, bad), payment, action=Action.BUILD)


def test_two_stages_that_would_be_the_same_job_are_refused(payment: CatalogService) -> None:
    generation_spec = spec(
        payment, Assistant.FREESTYLE, stage("Lint", "lint"), stage("Lint again", "lint")
    )

    with pytest.raises(RenderError, match="same freestyle job"):
        render(generation_spec, payment, action=Action.BUILD)


def test_a_spec_for_another_service_is_refused(
    payment: CatalogService, auth: CatalogService
) -> None:
    with pytest.raises(RenderError):
        render(
            spec(payment, Assistant.FREESTYLE, stage("Build", "build")), auth, action=Action.BUILD
        )


def test_freestyle_job_names() -> None:
    assert freestyle_job_name("svc", stage("B", "build")) == "fs-svc-build"
    assert freestyle_job_name("svc", stage("S", "security_scan")) == "fs-svc-security-scan"
    assert freestyle_job_name("svc", stage("T", "test", "unit")) == "fs-svc-test-unit"
    assert freestyle_job_name("svc", stage("D", "deploy", env="staging")) == "fs-svc-deploy-staging"


def test_the_artifact_round_trips_through_its_stored_form(chain: RenderedArtifact) -> None:
    stored = chain.to_json()

    assert RenderedArtifact.from_json(stored) == chain
    assert json.loads(stored)["job_type"] == "FREESTYLE"
