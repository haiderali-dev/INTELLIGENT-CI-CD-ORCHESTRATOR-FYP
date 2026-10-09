"""The per-request intent schema.

The schema is the first of two defences against an invented service: with strict decoding the
model cannot emit a value outside the enum. These tests pin the strict-mode rules that make that
true, and that ``production`` stays expressible -- a schema that narrowed it away would force a
production request into staging, the silent rewrite Appendix E forbids.
"""

from __future__ import annotations

from pathlib import Path

import jsonschema
import pytest
import yaml

from app.ai.intent import Action, ExtraStage, Intent, TargetEnvironment, Urgency
from app.ai.schema import build_intent_schema, catalog_context, catalog_fingerprint
from app.services.catalog import Catalog

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_CATALOG = REPO_ROOT / "catalog" / "services.yaml"
SCHEMA_FILE = REPO_ROOT / "catalog" / "services.schema.json"


@pytest.fixture
def catalog() -> Catalog:
    return Catalog(REAL_CATALOG)


def catalog_with(directory: Path, *names: str) -> Catalog:
    """A catalog of the named services, using the repository's real schema."""
    services = [
        {
            "name": name,
            "repo": f"https://github.com/example/{name}.git",
            "default_branch": "main",
            "agent_label": "linux",
            "build_command": "./scripts/build.sh",
            "test_suites": [
                {"name": "unit", "command": "./scripts/test.sh unit", "approx_seconds": 5}
            ],
            "deploy": {
                "staging": {"command": "./deploy.sh staging", "url": "http://localhost:9001"}
            },
            "allowed_environments": ["staging"],
        }
        for name in names
    ]
    path = directory / "services.yaml"
    path.write_text(yaml.safe_dump({"version": 1, "services": services}), encoding="utf-8")
    (directory / "services.schema.json").write_text(
        SCHEMA_FILE.read_text(encoding="utf-8"), encoding="utf-8"
    )
    return Catalog(path)


# ---------------------------------------------------------------------------
# Strict-mode structure
# ---------------------------------------------------------------------------


def test_every_property_is_required_and_nothing_else_is_allowed(catalog: Catalog) -> None:
    """Strict decoding refuses a schema with optional properties or open objects."""
    schema = build_intent_schema(catalog)

    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])


def test_the_schema_covers_exactly_the_ten_fields_of_4_5_2(catalog: Catalog) -> None:
    """One definition of the fields: the schema and the Intent model must not drift apart."""
    schema = build_intent_schema(catalog)

    assert set(schema["properties"]) == set(Intent.model_fields)


def test_nullable_enums_also_list_null(catalog: Catalog) -> None:
    """Strict mode needs null in the enum as well as the type, or it rejects null outright."""
    schema = build_intent_schema(catalog)

    for name in ("service", "environment", "test_suite", "urgency"):
        prop = schema["properties"][name]
        assert prop["type"] == ["string", "null"], name
        assert None in prop["enum"], name


# ---------------------------------------------------------------------------
# Catalog injection
# ---------------------------------------------------------------------------


def test_services_and_suites_come_from_the_catalog(catalog: Catalog) -> None:
    schema = build_intent_schema(catalog)

    assert set(schema["properties"]["service"]["enum"]) == {*catalog.service_names(), None}
    assert set(schema["properties"]["test_suite"]["enum"]) == {*catalog.suite_names(), None}


def test_a_service_added_to_the_catalog_appears_in_the_next_schema(tmp_path: Path) -> None:
    """Built per request: a new service is reachable at once, not after a restart."""
    before = build_intent_schema(catalog_with(tmp_path, "payment-service"))
    after = build_intent_schema(catalog_with(tmp_path, "payment-service", "billing-service"))

    assert "billing-service" not in before["properties"]["service"]["enum"]
    assert "billing-service" in after["properties"]["service"]["enum"]


def test_production_stays_expressible(catalog: Catalog) -> None:
    """If the enum held only the catalog's allowed environments, the decoder would turn a
    production request into staging -- the silent rewrite Appendix E forbids."""
    schema = build_intent_schema(catalog)

    assert "production" in schema["properties"]["environment"]["enum"]
    # ...even though no service allows it.
    assert all("production" not in service.allowed_environments for service in catalog.services())


def test_the_fixed_enums_match_the_intent_model(catalog: Catalog) -> None:
    schema = build_intent_schema(catalog)

    assert schema["properties"]["action"]["enum"] == [action.value for action in Action]
    assert schema["properties"]["urgency"]["enum"] == [*[u.value for u in Urgency], None]
    assert schema["properties"]["extra_stages"]["items"]["enum"] == [s.value for s in ExtraStage]
    assert schema["properties"]["environment"]["enum"] == [
        *[e.value for e in TargetEnvironment],
        None,
    ]


# ---------------------------------------------------------------------------
# The "no catalog enums" ablation (4.9)
# ---------------------------------------------------------------------------


def test_the_ablation_drops_only_the_catalog_enums(catalog: Catalog) -> None:
    """Isolating one change is what makes the ablation's number mean something."""
    full = build_intent_schema(catalog)
    ablated = build_intent_schema(catalog, include_enums=False)

    assert "enum" not in ablated["properties"]["service"]
    assert "enum" not in ablated["properties"]["test_suite"]
    for name in set(full["properties"]) - {"service", "test_suite"}:
        assert ablated["properties"][name] == full["properties"][name], name


# ---------------------------------------------------------------------------
# The schema accepts what the code produces
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "intent",
    [
        Intent(action=Action.BUILD, service="payment-service", branch="main", confidence=0.9),
        Intent(
            action=Action.DEPLOY,
            service="auth-service",
            environment=TargetEnvironment.PRODUCTION,
            urgency=Urgency.HIGH,
            justification="hotfix",
            confidence=0.8,
        ),
        Intent(
            action=Action.BUILD_TEST_DEPLOY,
            service="payment-service",
            commit="latest",
            environment=TargetEnvironment.STAGING,
            test_suite="unit",
            extra_stages=(ExtraStage.LINT, ExtraStage.SECURITY_SCAN),
            confidence=0.7,
        ),
        Intent.unsupported(),
    ],
)
def test_a_valid_intent_validates_against_the_schema(catalog: Catalog, intent: Intent) -> None:
    """If the schema rejected a well-formed intent, the model could never produce it."""
    jsonschema.validate(intent.to_card(), build_intent_schema(catalog))


def test_an_invented_service_does_not_validate(catalog: Catalog) -> None:
    """The structural defence: outside the enum is invalid."""
    card = Intent(action=Action.BUILD, service="made-up-service").to_card()

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(card, build_intent_schema(catalog))


# ---------------------------------------------------------------------------
# Fingerprint and context
# ---------------------------------------------------------------------------


def test_the_fingerprint_changes_with_the_catalog(tmp_path: Path) -> None:
    """It keys the response cache, so a stale answer cannot survive a catalog edit."""
    one = catalog_fingerprint(catalog_with(tmp_path, "payment-service"))
    two = catalog_fingerprint(catalog_with(tmp_path, "payment-service", "billing-service"))

    assert one != two


def test_the_fingerprint_is_stable(catalog: Catalog) -> None:
    assert catalog_fingerprint(catalog) == catalog_fingerprint(Catalog(REAL_CATALOG))


def test_the_context_lists_every_service_without_any_command(catalog: Catalog) -> None:
    """The model needs names to choose from, never the commands: it must not write shell."""
    context = catalog_context(catalog)

    for name in catalog.service_names():
        assert name in context
    assert "./scripts" not in context
    assert "deploy.sh" not in context
