"""The shared spec both assistants generate from (BUILD_PROMPT 4.6.1), and the planner's schema.

One model for both assistants: they differ only after the intent is confirmed (4.6), so a freestyle
chain and a Pipeline are rendered from the same spec, and the spec is the YAML the preview shows
and the user edits (4.6.2 step 4). That makes ``from_yaml`` a trust boundary: the text may have
been edited by hand, so every field is checked here, not only the ones the model fills.

What is checked here is the spec's *shape*. Whether the service, suite and environment exist in
the catalog, and whether the branch exists in Git, belong to the validators (T5.4), which have the
catalog and a Git client. The revision rule is applied here, because a spec that names an invalid
commit or branch is wrong whatever the catalog says (D-041).

The planner schema is what the model fills (4.6.2 step 1). "The model chooses only stages and
templates" (4.6.1), so that is all the schema offers it, with the catalog's names as enums. Every
other field comes from the validated intent.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Any, Final, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.ai.intent import MAX_JUSTIFICATION, Urgency
from app.generation.revision import Revision, RevisionError, select_revision
from app.services.catalog import CatalogService

SPEC_VERSION: Final = 1

# Service names become job names (`fs-<service>-build`, `pl-<service>-<action>`), so they are held
# to a job-name-safe subset.
SERVICE_PATTERN: Final = r"^[a-z0-9][a-z0-9-]{0,62}$"
LABEL_PATTERN: Final = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
# The same schemes GitClient will fetch (app/services/git.py ALLOWED_URL).
REPO_PATTERN: Final = r"^(https://|git@)\S+$"
TEMPLATE_PATTERN: Final = r"^[a-z][a-z_]{0,31}$"
NAME_PATTERN: Final = r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}$"
ENVIRONMENT_PATTERN: Final = r"^[a-z][a-z0-9_-]{0,31}$"

# Characters that never belong in a single-line field. The justification is free text written into
# an audit entry and a job description, so control characters are rejected rather than stored.
CONTROL_CHARACTERS: Final = re.compile(r"[\x00-\x1f\x7f]")


class Assistant(StrEnum):
    FREESTYLE = "freestyle"
    PIPELINE = "pipeline"


class StageTemplate(StrEnum):
    """Templates with a fixed meaning. A catalog extra stage (``lint``, ``security_scan``) is also
    a valid template; it is not listed here because the catalog decides which exist."""

    BUILD = "build"
    TEST = "test"
    DEPLOY = "deploy"


class _SpecDumper(yaml.SafeDumper):
    """Indents list items under their key, as 4.6.1 prints them (`  - name: Build`).

    PyYAML's default puts them flush with the key. Both are valid YAML; this one matches what the
    report and the specification show, which is what a user editing the preview will expect.
    """

    def increase_indent(self, flow: bool = False, indentless: bool = False) -> None:
        super().increase_indent(flow, False)


class SpecError(ValueError):
    """A spec could not be read at all: not YAML, or not a mapping."""


class Stage(BaseModel):
    """One stage: a freestyle chain job, or one ``stage`` in a Jenkinsfile."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(pattern=NAME_PATTERN)
    template: str = Field(pattern=TEMPLATE_PATTERN)
    suite: str | None = Field(default=None, pattern=ENVIRONMENT_PATTERN)
    environment: str | None = Field(default=None, pattern=ENVIRONMENT_PATTERN)

    @model_validator(mode="after")
    def _fields_match_template(self) -> Self:
        # A suite only means something to a test stage, and an environment only to a deploy. A
        # stray one is rejected rather than ignored, because an edited YAML that moves
        # `environment` onto the wrong stage would otherwise deploy somewhere unintended.
        if self.template == StageTemplate.TEST:
            if self.suite is None:
                raise ValueError("a test stage needs a suite")
        elif self.suite is not None:
            raise ValueError(f"only a test stage takes a suite, not {self.template!r}")
        if self.template == StageTemplate.DEPLOY:
            if self.environment is None:
                raise ValueError("a deploy stage needs an environment")
        elif self.environment is not None:
            raise ValueError(f"only a deploy stage takes an environment, not {self.template!r}")
        return self


class GenerationSpec(BaseModel):
    """BUILD_PROMPT 4.6.1, field for field and in the same order, so the YAML reads the same."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[1] = SPEC_VERSION
    assistant: Assistant
    service: str = Field(pattern=SERVICE_PATTERN)
    repo: str = Field(pattern=REPO_PATTERN)
    branch: str | None = None
    commit: str | None = None
    agent_label: str = Field(pattern=LABEL_PATTERN)
    priority: Urgency = Urgency.MEDIUM
    justification: str | None = Field(default=None, max_length=MAX_JUSTIFICATION)
    stages: tuple[Stage, ...] = Field(min_length=1)

    @field_validator("branch", "commit", "justification", mode="before")
    @classmethod
    def _blank_is_absent(cls, value: object) -> object:
        """Trim, and treat a blank value as absent, the way Jenkins treats a blank parameter."""
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value

    @field_validator("commit")
    @classmethod
    def _lowercase_commit(cls, value: str | None) -> str | None:
        return value.lower() if value is not None else None

    @field_validator("justification")
    @classmethod
    def _no_control_characters(cls, value: str | None) -> str | None:
        if value is not None and CONTROL_CHARACTERS.search(value):
            raise ValueError("the justification contains control characters")
        return value

    @model_validator(mode="after")
    def _revision_is_valid(self) -> Self:
        # D-041 rule 4: a commit or branch that was given but is invalid is an error, never a
        # fallback to another revision. Checked here so a hand-edited YAML is held to it too.
        try:
            select_revision(self.commit, self.branch)
        except RevisionError as exc:
            raise ValueError(f"{exc.field}: {exc}") from exc
        return self

    @property
    def revision(self) -> Revision:
        """What the jobs check out, and the ``BRANCH``/``COMMIT`` values both job types receive."""
        return select_revision(self.commit, self.branch)

    # --- YAML -----------------------------------------------------------------------------------

    def to_yaml(self) -> str:
        """The spec as the preview shows it. Absent optional fields are left out."""
        data = self.model_dump(mode="json", exclude_none=True)
        return yaml.dump(
            data,
            Dumper=_SpecDumper,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
        )

    @classmethod
    def from_yaml(cls, text: str) -> GenerationSpec:
        """Parse an edited spec. Raises ``SpecError`` or pydantic's ``ValidationError``."""
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise SpecError(f"the spec is not valid YAML: {exc}") from exc
        if not isinstance(data, dict):
            raise SpecError("the spec must be a YAML mapping")
        return cls.model_validate(data)


# ---------------------------------------------------------------------------
# The planner's schema
# ---------------------------------------------------------------------------


def service_templates(service: CatalogService) -> list[str]:
    """The templates the catalog can resolve to a command for this service (4.6.1)."""
    templates = [StageTemplate.BUILD.value]
    if service.test_suites:
        templates.append(StageTemplate.TEST.value)
    if service.deploy:
        templates.append(StageTemplate.DEPLOY.value)
    templates.extend(sorted(service.extra_stages))
    return templates


def _nullable_enum(values: list[str], description: str) -> dict[str, Any]:
    # Strict mode needs null in the enum as well as the type list (app/ai/schema.py).
    return {"type": ["string", "null"], "enum": [*values, None], "description": description}


def build_planner_schema(service: CatalogService) -> dict[str, Any]:
    """The strict JSON schema for the planner's output, built per service from the catalog.

    The same strict-mode conventions as the intent schema: every property required,
    ``additionalProperties: false``, nullability as a type list with ``null`` in the enum. The
    environment enum is the service's *allowed* environments: by the time a plan is made, policy
    has already refused anything else (4.5.5), so the planner has no reason to name it.
    """
    stage = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Short stage name shown to the user."},
            "template": {
                "type": "string",
                "enum": service_templates(service),
                "description": "Which catalog command this stage runs.",
            },
            "suite": _nullable_enum(
                sorted(suite.name for suite in service.test_suites),
                "Test suite, for a test stage only; null otherwise.",
            ),
            "environment": _nullable_enum(
                sorted(service.allowed_environments),
                "Target environment, for a deploy stage only; null otherwise.",
            ),
        },
        "required": ["name", "template", "suite", "environment"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {"stages": {"type": "array", "items": stage}},
        "required": ["stages"],
        "additionalProperties": False,
    }


class PlannerOutput(BaseModel):
    """The planner's answer, parsed. Checked again in code, as the intent is (4.5.3), because a
    replayed fixture or a provider that ignores ``strict`` must not get an invalid stage through."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    stages: tuple[Stage, ...] = Field(min_length=1)
