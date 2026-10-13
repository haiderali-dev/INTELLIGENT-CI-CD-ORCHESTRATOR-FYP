"""Rendering a spec into Jenkins jobs: BUILD_PROMPT 4.6.2 step 2 and 4.6.3 (T5.3).

"Derive every template from the exported reference configs." The three templates in
``templates/`` are the files in ``jenkins/reference-configs/`` with their variable parts replaced,
and ``tests/test_generation_render.py`` holds them to it: what a template renders for the
reference job's own values must be what Jenkins exported, element for element.

**Freestyle** (4.6, Appendix F): one job per stage, ``fs-<service>-<stage>``, each carrying the
priority property at the spec's level and naming the previous job in ``dependsOn``, each
triggering the next on success. Only the first is triggered directly. The branch and commit are
written as parameter defaults on every job, because a downstream trigger passes no parameters on.

Two things the chain has to get right that a single job does not:

* **Every job has its own workspace**, wiped before each build (the reference's
  ``PreBuildCleanup``). ``test.sh``, ``lint.sh`` and ``security_scan.sh`` only activate the
  ``.venv`` that ``build.sh`` creates (D-042), so a test, lint or scan job runs the build command
  first, in its own workspace. The acceptance chain's test job always did. The build *stage*
  still runs first in the chain, so a broken build stops everything after it.
* **Test jobs are named by suite**, ``fs-<service>-test-<suite>``. "Every suite" (D-042) can put
  two test stages in one chain, and Appendix F's ``fs-<service>-test`` would name both the same.

**Pipeline**: one job, ``pl-<service>-<action>[-<env>]``, whose sandboxed script is the rendered
Jenkinsfile. The stages share one workspace, so each runs only its own command.

Commands come from the catalog and nothing else: "Each template resolves to a command from the
catalog, so the model never writes shell commands" (4.6.1).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from app.ai.intent import Action
from app.db.models import JobType
from app.generation.spec import Assistant, GenerationSpec, Stage, StageTemplate
from app.services.catalog import CatalogService

TEMPLATES_DIR: Final = Path(__file__).resolve().parent / "templates"

# Stages whose script activates the .venv that build.sh creates (D-042).
NEEDS_BUILD: Final = frozenset({StageTemplate.TEST.value, "lint", "security_scan"})

_ACTION_KEYS: Final = {
    Action.BUILD: "build",
    Action.TEST: "test",
    Action.DEPLOY: "deploy",
    Action.BUILD_TEST_DEPLOY: "build-test-deploy",
}


class RenderError(ValueError):
    """The spec names something the catalog cannot resolve to a command.

    A template or catalog problem, never the model's: the planner's stages were already checked
    against the same catalog. 4.6.2: template bugs are caught by tests, not by the repair loop.
    """


def groovy_string(value: object) -> str:
    """Escape a value for a single-quoted Groovy string literal.

    Single-quoted Groovy strings do not interpolate ``$``, so only the backslash and the quote need
    escaping. A newline cannot appear in any value that reaches here (the spec's patterns forbid
    it), and is refused rather than escaped so a template can never be split across lines.
    """
    text = str(value)
    if "\n" in text or "\r" in text:
        raise RenderError("a value for a Groovy string contains a line break")
    return text.replace("\\", "\\\\").replace("'", "\\'")


def _environment() -> Environment:
    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        # XML templates escape every value; the Jenkinsfile is Groovy and escapes through the
        # `groovy` filter instead, then is escaped again as XML when it goes into <script>.
        autoescape=select_autoescape(enabled_extensions=("xml.j2",), default_for_string=False),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    env.filters["groovy"] = groovy_string
    return env


_ENV: Final = _environment()


@dataclass(frozen=True)
class RenderedJob:
    """One Jenkins job: its name, its config.xml, and its place in a chain."""

    name: str
    config_xml: str
    position: int
    #: The stage this job runs (freestyle), or None for a Pipeline job, which runs them all.
    stage: Stage | None = None
    commands: tuple[str, ...] = ()
    depends_on: str = ""
    triggers: str | None = None

    def to_record(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "position": self.position,
            "stage": self.stage.model_dump(mode="json") if self.stage is not None else None,
            "commands": list(self.commands),
            "depends_on": self.depends_on,
            "triggers": self.triggers,
            "config_xml": self.config_xml,
        }


@dataclass(frozen=True)
class RenderedArtifact:
    """What a spec renders to: a freestyle chain, or one Pipeline job and its Jenkinsfile."""

    job_type: JobType
    jobs: tuple[RenderedJob, ...]
    jenkinsfile: str | None = None
    #: The parameters every trigger and every chain job's defaults carry (D-041).
    parameters: dict[str, str] = field(default_factory=dict)

    @property
    def first_job(self) -> RenderedJob:
        return self.jobs[0]

    def to_json(self) -> str:
        """For ``generated_pipelines.rendered_artifact``."""
        return json.dumps(
            {
                "job_type": self.job_type.value,
                "jobs": [job.to_record() for job in self.jobs],
                "jenkinsfile": self.jenkinsfile,
                "parameters": self.parameters,
            },
            indent=2,
        )

    @classmethod
    def from_json(cls, text: str) -> RenderedArtifact:
        data = json.loads(text)
        return cls(
            job_type=JobType(data["job_type"]),
            jobs=tuple(
                RenderedJob(
                    name=job["name"],
                    config_xml=job["config_xml"],
                    position=job["position"],
                    stage=Stage.model_validate(job["stage"]) if job.get("stage") else None,
                    commands=tuple(job.get("commands") or ()),
                    depends_on=job.get("depends_on") or "",
                    triggers=job.get("triggers"),
                )
                for job in data["jobs"]
            ),
            jenkinsfile=data.get("jenkinsfile"),
            parameters=dict(data.get("parameters") or {}),
        )


# ---------------------------------------------------------------------------
# Names and commands
# ---------------------------------------------------------------------------


def freestyle_job_name(service: str, stage: Stage) -> str:
    """``fs-<service>-<stage>``: build, test-<suite>, deploy-<env>, lint, security-scan."""
    if stage.template == StageTemplate.TEST:
        key = f"test-{stage.suite}"
    elif stage.template == StageTemplate.DEPLOY:
        key = f"deploy-{stage.environment}"
    else:
        key = stage.template.replace("_", "-")
    return f"fs-{service}-{key}"


def pipeline_job_name(service: str, action: Action, spec: GenerationSpec) -> str:
    """``pl-<service>-<action>[-<env>]`` (4.6)."""
    if action not in _ACTION_KEYS:
        raise RenderError(f"{action.value} does not generate a job")
    environments = [stage.environment for stage in spec.stages if stage.environment is not None]
    name = f"pl-{service}-{_ACTION_KEYS[action]}"
    return f"{name}-{environments[0]}" if environments else name


def stage_command(service: CatalogService, stage: Stage) -> str:
    """The catalog's command for a stage. Never anything else."""
    command: str | None
    if stage.template == StageTemplate.BUILD:
        command = service.build_command
    elif stage.template == StageTemplate.TEST:
        suite = service.suite(stage.suite or "")
        command = suite.command if suite is not None else None
    elif stage.template == StageTemplate.DEPLOY:
        target = service.deploy_target(stage.environment or "")
        command = target.command if target is not None else None
    else:
        command = service.extra_stage_command(stage.template)
    if not command:
        raise RenderError(
            f"{service.name} has no command for stage {stage.name!r} ({stage.template})"
        )
    return command


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render(spec: GenerationSpec, service: CatalogService, *, action: Action) -> RenderedArtifact:
    """Render a spec for its assistant. Raises ``RenderError``."""
    if spec.service != service.name:
        raise RenderError(f"the spec is for {spec.service}, not {service.name}")
    if spec.assistant is Assistant.FREESTYLE:
        return render_freestyle(spec, service)
    return render_pipeline(spec, service, action=action)


def render_freestyle(spec: GenerationSpec, service: CatalogService) -> RenderedArtifact:
    parameters = spec.revision.parameters()
    names = [freestyle_job_name(service.name, stage) for stage in spec.stages]
    if len(set(names)) != len(names):
        raise RenderError("two stages would become the same freestyle job")
    template = _ENV.get_template("freestyle-job.xml.j2")
    total = len(spec.stages)

    jobs: list[RenderedJob] = []
    for index, stage in enumerate(spec.stages):
        command = stage_command(service, stage)
        commands = (service.build_command, command) if stage.template in NEEDS_BUILD else (command,)
        depends_on = names[index - 1] if index > 0 else ""
        next_job = names[index + 1] if index + 1 < total else None
        config = template.render(
            description=(
                f"Generated by the Freestyle Assistant: {stage.name} for {service.name}, "
                f"job {index + 1} of {total} in its chain."
            ),
            priority=spec.priority.value,
            depends_on=depends_on,
            branch=parameters["BRANCH"],
            commit=parameters["COMMIT"],
            repo=service.repo,
            agent_label=spec.agent_label,
            commands=commands,
            next_job=next_job,
        )
        jobs.append(
            RenderedJob(
                name=names[index],
                config_xml=config,
                position=index,
                stage=stage,
                commands=commands,
                depends_on=depends_on,
                triggers=next_job,
            )
        )
    return RenderedArtifact(job_type=JobType.FREESTYLE, jobs=tuple(jobs), parameters=parameters)


def render_jenkinsfile(spec: GenerationSpec, service: CatalogService) -> str:
    stages = [
        {"name": stage.name, "command": stage_command(service, stage)} for stage in spec.stages
    ]
    return _ENV.get_template("Jenkinsfile.j2").render(
        agent_label=spec.agent_label,
        priority=spec.priority.value,
        branch=spec.revision.branch,
        repo=service.repo,
        stages=stages,
    )


def render_pipeline(
    spec: GenerationSpec, service: CatalogService, *, action: Action
) -> RenderedArtifact:
    jenkinsfile = render_jenkinsfile(spec, service)
    names = ", ".join(stage.name for stage in spec.stages)
    config = _ENV.get_template("pipeline-job.xml.j2").render(
        description=f"Generated by the Pipeline Assistant: {names} for {service.name}.",
        priority=spec.priority.value,
        branch=spec.revision.branch,
        jenkinsfile=jenkinsfile,
    )
    job = RenderedJob(
        name=pipeline_job_name(service.name, action, spec),
        config_xml=config,
        position=0,
        commands=tuple(stage_command(service, stage) for stage in spec.stages),
    )
    return RenderedArtifact(
        job_type=JobType.PIPELINE,
        jobs=(job,),
        jenkinsfile=jenkinsfile,
        parameters=spec.revision.parameters(),
    )
