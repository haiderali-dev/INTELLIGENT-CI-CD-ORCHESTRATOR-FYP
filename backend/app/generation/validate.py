"""``FreestyleValidator`` and ``PipelineValidator``: BUILD_PROMPT 4.6.3 (T5.4).

"Validation checks, in order: spec schema; service, branch, commit, suite and environment against
the catalog and Git; environment allowed; stage order (build before test before deploy); no shell
metacharacters in interpolated values; XML well-formedness or a linter pass; job name pattern and
length; and no ``production`` anywhere."

4.6's table splits the sixth check by assistant: XML well-formedness for freestyle, the declarative
linter for a Pipeline (``POST /pipeline-model-converter/validate`` through ``JenkinsClient``). A
Pipeline's config.xml is checked for well-formedness as well, because it is posted too.

Every check is reported, passed or not, because the preview shows them as a checklist (4.6.2 step
4). Each failure names its cause, because 4.6.2 treats causes differently: "errors caused by the
model's plan go back to it for at most 2 repairs. Template bugs are caught by golden-file tests,
not by the repair loop."

* ``plan``: what the stages are. The planner checks the same rules first, so for a planned spec
  these fail only if the two drift apart; for a hand-edited spec they are the user's to fix.
* ``input``: the branch, commit, repository and other values that came from the user or the edit.
* ``template``: the rendered artifact. A template bug, or Jenkins refusing what it was given.

Two rules for a hand-edited spec that 4.6.3 implies rather than states. The repository and the
agent label must be the catalog's: the YAML is editable (4.6.2 step 4), and a spec that pointed at
another repository would run someone else's code on the agents. An unreachable remote is a warning,
not a failure, as in the intent validator (D-037): Jenkins fails the checkout honestly if the
branch is wrong.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final, Literal
from xml.etree import ElementTree

from pydantic import ValidationError

from app.generation.render import NEEDS_BUILD, RenderedArtifact
from app.generation.revision import RevisionError, select_revision
from app.generation.spec import (
    Assistant,
    GenerationSpec,
    SpecError,
    StageTemplate,
    service_templates,
)
from app.services.catalog import Catalog, CatalogService
from app.services.git import GitClient, GitError
from app.services.jenkins import JOB_NAME_PATTERN, JenkinsClient, JenkinsError

Cause = Literal["plan", "input", "template"]

# Order the stages must run in (D-042). 4.6.3's "build before test before deploy" is the core of it.
STAGE_ORDER: Final = ("build", "lint", "security_scan", "test", "deploy", "smoke_test")

# Characters with a meaning to a shell, Groovy or XML, none of which a valid value needs.
SHELL_METACHARACTERS: Final = re.compile(r"[;&|$`<>(){}\[\]\\'\"*?!~#\s]")

PRODUCTION: Final = re.compile(r"production", re.IGNORECASE)


class CheckStatus(StrEnum):
    PASSED = "passed"
    WARNING = "warning"
    FAILED = "failed"


@dataclass(frozen=True)
class Check:
    """One line of the preview's validation checklist."""

    name: str
    label: str
    status: CheckStatus
    message: str = ""
    cause: Cause | None = None

    def to_record(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "status": self.status.value,
            "message": self.message,
            "cause": self.cause,
        }


@dataclass(frozen=True)
class ValidationReport:
    checks: tuple[Check, ...]

    @property
    def ok(self) -> bool:
        return all(check.status is not CheckStatus.FAILED for check in self.checks)

    @property
    def failures(self) -> tuple[Check, ...]:
        return tuple(check for check in self.checks if check.status is CheckStatus.FAILED)

    def failures_caused_by(self, cause: Cause) -> tuple[Check, ...]:
        return tuple(check for check in self.failures if check.cause == cause)

    def to_record(self) -> dict[str, Any]:
        return {"ok": self.ok, "checks": [check.to_record() for check in self.checks]}


def parse_spec(text: str) -> GenerationSpec | ValidationReport:
    """Check 1 for an edited YAML: the spec itself, or a report saying why it is not one."""
    try:
        return GenerationSpec.from_yaml(text)
    except SpecError as exc:
        message = str(exc)
    except ValidationError as exc:
        message = "; ".join(
            f"{'.'.join(str(part) for part in error['loc']) or 'spec'}: {error['msg']}"
            for error in exc.errors()
        )
    return ValidationReport(
        checks=(Check("spec_schema", "Spec schema", CheckStatus.FAILED, message, "input"),)
    )


class _Findings:
    """Collects one check's problems and warnings, then becomes that check."""

    def __init__(self) -> None:
        self.failures: list[tuple[str, Cause]] = []
        self.warnings: list[str] = []

    def fail(self, message: str, cause: Cause) -> None:
        self.failures.append((message, cause))

    def to_check(self, name: str, label: str, passed: str = "") -> Check:
        if self.failures:
            cause = self.failures[0][1]
            return Check(
                name, label, CheckStatus.FAILED, "; ".join(m for m, _ in self.failures), cause
            )
        if self.warnings:
            return Check(name, label, CheckStatus.WARNING, "; ".join(self.warnings))
        return Check(name, label, CheckStatus.PASSED, passed)


class SpecValidator:
    """The checks both assistants share. Subclasses add the artifact check (number 6)."""

    artifact_label: str = "Artifact"

    def __init__(
        self, catalog: Catalog, git: GitClient, jenkins: JenkinsClient | None = None
    ) -> None:
        self._catalog = catalog
        self._git = git
        self._jenkins = jenkins

    async def validate(self, spec: GenerationSpec, artifact: RenderedArtifact) -> ValidationReport:
        checks: list[Check] = [Check("spec_schema", "Spec schema", CheckStatus.PASSED)]
        service = self._catalog.get(spec.service)
        checks.append(await self._check_catalog_and_git(spec, service))
        checks.append(self._check_environment(spec, service))
        checks.append(self._check_stage_order(spec))
        checks.append(self._check_metacharacters(spec, artifact))
        checks.append(await self._check_artifact(spec, artifact))
        checks.append(self._check_job_names(artifact))
        checks.append(self._check_no_production(spec, artifact))
        return ValidationReport(checks=tuple(checks))

    # --- 2. Catalog and Git ---------------------------------------------------

    async def _check_catalog_and_git(
        self, spec: GenerationSpec, service: CatalogService | None
    ) -> Check:
        findings = _Findings()
        name, label = "catalog_and_git", "Service, branch, commit and suites"
        if service is None:
            findings.fail(f"There is no service called {spec.service!r} in the catalog.", "input")
            return findings.to_check(name, label)

        if spec.repo != service.repo:
            findings.fail(
                f"The repository must be {service.name}'s own ({service.repo}), not {spec.repo}.",
                "input",
            )
        if spec.agent_label != service.agent_label:
            findings.fail(
                f"{service.name} builds on the {service.agent_label!r} agents, not "
                f"{spec.agent_label!r}.",
                "input",
            )

        offered = set(service_templates(service))
        for stage in spec.stages:
            if stage.template not in offered:
                findings.fail(f"{service.name} has no {stage.template!r} stage.", "plan")
            if stage.suite is not None and service.suite(stage.suite) is None:
                findings.fail(f"{service.name} has no {stage.suite!r} test suite.", "plan")

        await self._check_refs(spec, service, findings)
        return findings.to_check(name, label, "all found in the catalog and the repository")

    async def _check_refs(
        self, spec: GenerationSpec, service: CatalogService, findings: _Findings
    ) -> None:
        try:
            revision = select_revision(spec.commit, spec.branch)
        except RevisionError as exc:  # the spec model already refuses these; kept as a backstop
            findings.fail(str(exc), "input")
            return
        try:
            branches = await self._git.list_branches(service.repo)
        except GitError:
            findings.warnings.append(
                f"Could not reach {service.name}'s repository to check {revision.branch!r}; "
                "Jenkins will report it if it does not exist."
            )
            return
        if revision.branch not in branches:
            findings.fail(f"{service.name} has no branch called {revision.branch!r}.", "input")
            return
        if revision.commit is None:
            return
        try:
            confirmed = await self._git.commit_exists(
                service.repo, revision.commit, branch=revision.branch
            )
        except GitError:
            findings.warnings.append(f"Could not confirm commit {revision.commit}.")
            return
        if not confirmed:
            # ls-remote sees branch tips only (D-024): an older commit cannot be confirmed, so this
            # warns rather than fails. Jenkins fails the checkout if it does not exist.
            findings.warnings.append(
                f"{revision.commit} is not the tip of {revision.branch}, so it could not be "
                "confirmed in advance."
            )

    # --- 3. Environment ---------------------------------------------------------

    @staticmethod
    def _check_environment(spec: GenerationSpec, service: CatalogService | None) -> Check:
        findings = _Findings()
        for stage in spec.stages:
            environment = stage.environment
            if environment is None:
                continue
            if PRODUCTION.fullmatch(environment):
                findings.fail(
                    "Deploying to production is refused: this project deploys to staging only.",
                    "plan",
                )
            elif service is not None and not service.allows(environment):
                findings.fail(f"{service.name} cannot be deployed to {environment}.", "plan")
        return findings.to_check("environment", "Environment allowed", "staging only")

    # --- 4. Stage order --------------------------------------------------------

    @staticmethod
    def _check_stage_order(spec: GenerationSpec) -> Check:
        findings = _Findings()
        templates = [stage.template for stage in spec.stages]
        ranks = [STAGE_ORDER.index(t) if t in STAGE_ORDER else -1 for t in templates]
        known = [rank for rank in ranks if rank >= 0]
        if known != sorted(known):
            findings.fail(
                "Stages must run build, then checks, then tests, then deploy: got "
                + " -> ".join(templates),
                "plan",
            )
        for index, stage in enumerate(spec.stages):
            if stage.template in NEEDS_BUILD and StageTemplate.BUILD not in templates[:index]:
                findings.fail(
                    f"{stage.name!r} needs a build stage before it: its script uses what the "
                    "build installs.",
                    "plan",
                )
                break
        names = [stage.name.strip().casefold() for stage in spec.stages]
        if len(set(names)) != len(names):
            findings.fail("Two stages have the same name.", "plan")
        return findings.to_check("stage_order", "Stage order", " -> ".join(templates))

    # --- 5. Shell metacharacters -------------------------------------------------

    @staticmethod
    def _check_metacharacters(spec: GenerationSpec, artifact: RenderedArtifact) -> Check:
        """Every value interpolated into a script, a Groovy string or a parameter."""
        findings = _Findings()
        values: list[tuple[str, str]] = [
            ("service", spec.service),
            ("agent label", spec.agent_label),
            *(("parameter " + key, value) for key, value in artifact.parameters.items()),
        ]
        values.extend(("stage name", stage.name.replace(" ", "")) for stage in spec.stages)
        for field, value in values:
            if SHELL_METACHARACTERS.search(value):
                findings.fail(
                    f"The {field} {value!r} contains a character that is not allowed.", "input"
                )
        if spec.repo != spec.repo.strip() or any(c in spec.repo for c in "'\"`$;\n\\ "):
            findings.fail("The repository URL contains a character that is not allowed.", "input")
        return findings.to_check("metacharacters", "No shell metacharacters", "none found")

    # --- 6. The artifact ----------------------------------------------------------

    async def _check_artifact(self, spec: GenerationSpec, artifact: RenderedArtifact) -> Check:
        findings = _Findings()
        self._check_well_formed(artifact, findings)
        return findings.to_check("artifact", self.artifact_label, "well-formed")

    @staticmethod
    def _check_well_formed(artifact: RenderedArtifact, findings: _Findings) -> None:
        for job in artifact.jobs:
            try:
                # Our own rendered output, every value escaped by the template, so no entity or
                # DTD from outside can be in it.
                ElementTree.fromstring(job.config_xml)  # noqa: S314
            except ElementTree.ParseError as exc:
                findings.fail(f"{job.name}'s config.xml is not well-formed XML: {exc}", "template")

    # --- 7. Job names -------------------------------------------------------------

    @staticmethod
    def _check_job_names(artifact: RenderedArtifact) -> Check:
        findings = _Findings()
        for job in artifact.jobs:
            if not JOB_NAME_PATTERN.fullmatch(job.name):
                findings.fail(
                    f"{job.name!r} is not a valid job name: letters, digits, '.', '_' and '-', "
                    "at most 128 characters.",
                    "template",
                )
        return findings.to_check(
            "job_names", "Job names", ", ".join(job.name for job in artifact.jobs)
        )

    # --- 8. No production -----------------------------------------------------------

    @staticmethod
    def _check_no_production(spec: GenerationSpec, artifact: RenderedArtifact) -> Check:
        """Everything that reaches Jenkins, and every structured value in the spec.

        The justification is the one field left out: it is the user's own words, recorded in the
        audit log and never written into a job, and "a production incident" is a fair reason to
        ask for a HIGH staging build.
        """
        findings = _Findings()
        texts = [job.config_xml for job in artifact.jobs]
        texts.append(artifact.jenkinsfile or "")
        texts.extend(artifact.parameters.values())
        texts.extend(
            value
            for stage in spec.stages
            for value in (stage.name, stage.template, stage.suite or "", stage.environment or "")
        )
        texts.extend([spec.service, spec.repo, spec.branch or "", spec.agent_label])
        if any(PRODUCTION.search(text) for text in texts):
            findings.fail("'production' appears in what would be sent to Jenkins.", "plan")
        return findings.to_check("no_production", "No production anywhere", "staging only")


class FreestyleValidator(SpecValidator):
    """Spec checks, XML well-formedness, catalog checks (4.6)."""

    artifact_label = "XML well-formed"


class PipelineValidator(SpecValidator):
    """Spec checks, the declarative linter, catalog checks (4.6)."""

    artifact_label = "Declarative linter"

    async def _check_artifact(self, spec: GenerationSpec, artifact: RenderedArtifact) -> Check:
        findings = _Findings()
        self._check_well_formed(artifact, findings)
        if artifact.jenkinsfile is None:
            findings.fail("There is no Jenkinsfile to lint.", "template")
        elif self._jenkins is None:
            findings.fail("No Jenkins client to lint with.", "template")
        else:
            try:
                result = await self._jenkins.lint_jenkinsfile(artifact.jenkinsfile)
            except JenkinsError as exc:
                # Not a pass: validation that could not run has not validated anything. The user
                # can regenerate once Jenkins answers.
                findings.fail(f"Jenkins's linter could not be reached: {exc}", "template")
            else:
                if not result.ok:
                    findings.fail(
                        f"The declarative linter rejected the Jenkinsfile: {result.message}",
                        "template",
                    )
        return findings.to_check(
            "artifact", self.artifact_label, "Jenkinsfile successfully validated"
        )


def validator_for(
    spec: GenerationSpec, catalog: Catalog, git: GitClient, jenkins: JenkinsClient
) -> SpecValidator:
    """The validator 4.6 assigns to the spec's assistant."""
    if spec.assistant is Assistant.PIPELINE:
        return PipelineValidator(catalog, git, jenkins)
    return FreestyleValidator(catalog, git, jenkins)
