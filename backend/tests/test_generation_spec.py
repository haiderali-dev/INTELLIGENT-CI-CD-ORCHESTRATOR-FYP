"""T5.1: the shared spec (BUILD_PROMPT 4.6.1), its YAML round-trip, and the planner schema."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.ai.intent import Urgency
from app.generation.revision import Revision, RevisionSource
from app.generation.spec import (
    Assistant,
    GenerationSpec,
    PlannerOutput,
    SpecError,
    Stage,
    build_planner_schema,
    service_templates,
)
from app.services.catalog import Catalog

# BUILD_PROMPT 4.6.1, verbatim apart from the placeholder org.
SPEC_461 = """\
version: 1
assistant: pipeline            # or freestyle
service: payment-service
repo: https://github.com/<org>/payment-service.git
branch: main
commit: 3f9c2ab
agent_label: linux
priority: HIGH
justification: Hotfix for checkout timeout
stages:
  - name: Build
    template: build
  - name: Unit tests
    template: test
    suite: unit
  - name: Deploy
    template: deploy
    environment: staging
"""


def spec(**overrides: Any) -> GenerationSpec:
    data: dict[str, Any] = {
        "assistant": "freestyle",
        "service": "payment-service",
        "repo": "https://github.com/haiderali-dev/payment-service.git",
        "branch": "main",
        "agent_label": "linux",
        "stages": [{"name": "Build", "template": "build"}],
    }
    data.update(overrides)
    return GenerationSpec.model_validate(data)


# ---------------------------------------------------------------------------
# The model
# ---------------------------------------------------------------------------


def test_the_spec_in_4_6_1_parses() -> None:
    parsed = GenerationSpec.from_yaml(SPEC_461)

    assert parsed.version == 1
    assert parsed.assistant is Assistant.PIPELINE
    assert parsed.priority is Urgency.HIGH
    assert [stage.template for stage in parsed.stages] == ["build", "test", "deploy"]
    assert parsed.stages[1].suite == "unit"
    assert parsed.stages[2].environment == "staging"
    assert parsed.revision == Revision(RevisionSource.COMMIT, "main", "3f9c2ab")


@pytest.mark.parametrize("assistant", ["freestyle", "pipeline"])
def test_yaml_round_trip(assistant: str) -> None:
    original = spec(
        assistant=assistant,
        commit="3f9c2ab",
        priority="HIGH",
        justification="Hotfix for checkout timeout",
        stages=[
            {"name": "Build", "template": "build"},
            {"name": "Unit tests", "template": "test", "suite": "unit"},
            {"name": "Deploy", "template": "deploy", "environment": "staging"},
        ],
    )

    text = original.to_yaml()

    assert GenerationSpec.from_yaml(text) == original
    assert GenerationSpec.from_yaml(text).to_yaml() == text


def test_yaml_keeps_the_order_of_4_6_1_and_leaves_out_absent_fields() -> None:
    text = spec(branch=None).to_yaml()

    keys = [line.split(":", 1)[0] for line in text.splitlines() if not line.startswith(" ")]
    assert keys == ["version", "assistant", "service", "repo", "agent_label", "priority", "stages"]


def test_the_dumped_yaml_reads_like_4_6_1() -> None:
    """The preview shows this text, so it should look like the spec the user has seen."""
    expected = SPEC_461.replace("            # or freestyle", "")

    assert GenerationSpec.from_yaml(SPEC_461).to_yaml() == expected


def test_normalisation_survives_the_round_trip() -> None:
    """An edited YAML with a padded, upper-case SHA is stored the way the rule reads it."""
    parsed = spec(commit="  3F9C2AB ", branch=" main ", justification="  ")

    assert parsed.commit == "3f9c2ab"
    assert parsed.branch == "main"
    assert parsed.justification is None
    assert GenerationSpec.from_yaml(parsed.to_yaml()) == parsed


# --- the revision rule on the spec (D-041) -----------------------------------------------------


@pytest.mark.parametrize("assistant", ["freestyle", "pipeline"])
@pytest.mark.parametrize(
    ("commit", "branch", "expected"),
    [
        ("3f9c2ab", "develop", {"BRANCH": "develop", "COMMIT": "3f9c2ab"}),
        (None, "develop", {"BRANCH": "develop", "COMMIT": "refs/heads/develop"}),
        (None, None, {"BRANCH": "main", "COMMIT": "refs/heads/main"}),
        ("", "", {"BRANCH": "main", "COMMIT": "refs/heads/main"}),
    ],
)
def test_both_assistants_get_the_same_parameters(
    assistant: str, commit: str | None, branch: str | None, expected: dict[str, str]
) -> None:
    """Parity: the job type never changes which revision is checked out."""
    assert spec(assistant=assistant, commit=commit, branch=branch).revision.parameters() == expected


def test_freestyle_and_pipeline_specs_differ_only_in_the_assistant() -> None:
    freestyle = spec(assistant="freestyle", commit="3f9c2ab")
    pipeline = spec(assistant="pipeline", commit="3f9c2ab")

    assert freestyle.revision == pipeline.revision
    assert freestyle.model_copy(update={"assistant": Assistant.PIPELINE}) == pipeline


@pytest.mark.parametrize(
    ("field", "value"), [("commit", "latest"), ("commit", "nope"), ("branch", "bad branch")]
)
def test_an_invalid_revision_rejects_the_spec(field: str, value: str) -> None:
    """No fallback: a spec naming an unusable commit or branch is not a spec."""
    with pytest.raises(ValidationError, match=field):
        spec(**{field: value})


def test_a_hand_edited_yaml_is_held_to_the_rule() -> None:
    edited = SPEC_461.replace("commit: 3f9c2ab", "commit: HEAD~1")

    with pytest.raises(ValidationError, match="commit"):
        GenerationSpec.from_yaml(edited)


# --- the rest of the shape ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"version": 2},
        {"assistant": "maven"},
        {"service": "Payment Service"},
        {"service": "-payment"},
        {"repo": "ext::sh -c id"},
        {"repo": "/srv/repos/payment.git"},
        {"agent_label": "linux && windows"},
        {"priority": "URGENT"},
        {"justification": "fix\x00now"},
        {"justification": "x" * 501},
        {"stages": []},
        {"unexpected": "field"},
    ],
)
def test_an_invalid_field_rejects_the_spec(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        spec(**overrides)


@pytest.mark.parametrize(
    "stage",
    [
        {"name": "Tests", "template": "test"},
        {"name": "Deploy", "template": "deploy"},
        {"name": "Build", "template": "build", "suite": "unit"},
        {"name": "Build", "template": "build", "environment": "staging"},
        {"name": "Tests", "template": "test", "suite": "unit", "environment": "staging"},
        {"name": "Build", "template": "Build; rm -rf /"},
        {"name": "$(id)", "template": "build"},
        {"name": "Build", "template": "build", "command": "./scripts/build.sh"},
    ],
)
def test_an_invalid_stage_is_rejected(stage: dict[str, Any]) -> None:
    """Including a stage that tries to carry its own command: commands come only from the catalog."""
    with pytest.raises(ValidationError):
        Stage.model_validate(stage)


@pytest.mark.parametrize("text", ["version: [1", "- just\n- a list\n", "plain text", ""])
def test_unreadable_yaml_is_a_spec_error(text: str) -> None:
    with pytest.raises(SpecError):
        GenerationSpec.from_yaml(text)


def test_the_spec_is_immutable() -> None:
    with pytest.raises(ValidationError):
        spec().commit = "3f9c2ab"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# The planner schema
# ---------------------------------------------------------------------------


def _walk_objects(schema: dict[str, Any]) -> list[dict[str, Any]]:
    found = [schema] if schema.get("type") == "object" else []
    for value in schema.get("properties", {}).values():
        found.extend(_walk_objects(value))
    if "items" in schema:
        found.extend(_walk_objects(schema["items"]))
    return found


def test_the_planner_schema_is_strict(catalog: Catalog) -> None:
    """Groq strict mode: every property required and no additional properties, at every level."""
    schema = build_planner_schema(catalog.require("payment-service"))

    objects = _walk_objects(schema)
    assert len(objects) == 2
    for obj in objects:
        assert obj["additionalProperties"] is False
        assert set(obj["required"]) == set(obj["properties"])
    for nullable in ("suite", "environment"):
        field = schema["properties"]["stages"]["items"]["properties"][nullable]
        assert field["type"] == ["string", "null"]
        assert None in field["enum"]


def test_the_planner_only_chooses_stages_and_templates(catalog: Catalog) -> None:
    """4.6.1: no commands, no branch, no commit, no repo. Those come from the intent and catalog."""
    schema = build_planner_schema(catalog.require("payment-service"))

    assert set(schema["properties"]) == {"stages"}
    stage = schema["properties"]["stages"]["items"]["properties"]
    assert set(stage) == {"name", "template", "suite", "environment"}


def test_the_planner_enums_come_from_the_service(catalog: Catalog) -> None:
    payment = build_planner_schema(catalog.require("payment-service"))
    auth = build_planner_schema(catalog.require("auth-service"))

    payment_stage = payment["properties"]["stages"]["items"]["properties"]
    auth_stage = auth["properties"]["stages"]["items"]["properties"]
    assert payment_stage["template"]["enum"] == ["build", "test", "deploy", "lint", "security_scan"]
    assert auth_stage["template"]["enum"] == ["build", "test", "deploy", "lint"]
    assert payment_stage["suite"]["enum"] == ["integration", "unit", None]
    assert auth_stage["suite"]["enum"] == ["unit", None]
    # Only allowed environments: production has already been refused by policy (4.5.5).
    assert payment_stage["environment"]["enum"] == ["staging", None]
    assert "production" not in str(payment)


def test_service_templates_follow_the_catalog(catalog: Catalog) -> None:
    assert service_templates(catalog.require("auth-service")) == ["build", "test", "deploy", "lint"]


def test_a_plan_is_checked_again_in_code() -> None:
    """A replayed fixture or a provider that ignores strict must not get an invalid stage through."""
    plan = PlannerOutput.model_validate(
        {
            "stages": [
                {"name": "Build", "template": "build", "suite": None, "environment": None},
                {"name": "Unit tests", "template": "test", "suite": "unit", "environment": None},
            ]
        }
    )
    assert [stage.template for stage in plan.stages] == ["build", "test"]

    with pytest.raises(ValidationError):
        PlannerOutput.model_validate(
            {
                "stages": [
                    {"name": "Deploy", "template": "deploy", "suite": None, "environment": None}
                ]
            }
        )
    with pytest.raises(ValidationError):
        PlannerOutput.model_validate({"stages": []})
