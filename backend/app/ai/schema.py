"""The intent schema, built per request from the catalog.

BUILD_PROMPT 4.5.2: "Built per request with catalog values injected as enums."

Injecting the catalog as enums is a structural guarantee, not a hint. With a strict schema the model
*cannot* name a service the catalog does not have: the decoder only permits the enum's values. That
is the first of two independent defences against invented services -- the second is the validator,
which checks again in code (4.5.3 step 3), because a replayed fixture or a provider that ignores
``strict`` must not be able to get one through either.

Strict mode, as Groq implements it for ``gpt-oss`` (verified live before this was written), needs:
every property listed in ``required``, ``additionalProperties: false``, and nullability expressed as
a type list with ``null`` also present in any ``enum``. Bounds such as ``minimum`` and ``maximum``
are not relied on; ``Intent.from_untrusted`` clamps confidence instead.

``environment`` is deliberately *not* narrowed to the catalog's allowed environments. ``production``
has to be expressible, or a request for it would be forced into ``staging`` by the decoder -- the
silent rewrite Appendix E forbids. The policy layer refuses it instead.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.ai.intent import Action, ExtraStage, TargetEnvironment, Urgency
from app.services.catalog import Catalog


def _nullable_enum(values: list[str], description: str) -> dict[str, Any]:
    return {
        "type": ["string", "null"],
        # null must be in the enum as well as in the type list, or strict mode rejects null.
        "enum": [*values, None],
        "description": description,
    }


def _nullable_string(description: str) -> dict[str, Any]:
    return {"type": ["string", "null"], "description": description}


def build_intent_schema(catalog: Catalog, *, include_enums: bool = True) -> dict[str, Any]:
    """The JSON schema for one request.

    ``include_enums=False`` drops the catalog enums for 4.9's "no catalog enums" ablation, which
    measures how much of the accuracy comes from the decoder being unable to answer outside the
    catalog. Everything else stays the same so the ablation isolates that one change.
    """
    services = sorted(catalog.service_names())
    suites = sorted(catalog.suite_names())

    properties: dict[str, Any] = {
        "action": {
            "type": "string",
            "enum": [action.value for action in Action],
            "description": "UNSUPPORTED when the message is not a CI/CD request.",
        },
        "service": (
            _nullable_enum(services, "A catalog service, or null if none is clearly named.")
            if include_enums
            else _nullable_string("The service named, or null if none is clearly named.")
        ),
        "branch": _nullable_string("The branch named, or null for the service's default branch."),
        "commit": _nullable_string('"latest", a commit SHA prefix, or null.'),
        "environment": _nullable_enum(
            [environment.value for environment in TargetEnvironment],
            "The deploy target exactly as requested. Never change production to staging.",
        ),
        "test_suite": (
            _nullable_enum(suites, "A test suite from the catalog, or null.")
            if include_enums
            else _nullable_string("The test suite named, or null.")
        ),
        "urgency": _nullable_enum(
            [urgency.value for urgency in Urgency],
            "HIGH, MEDIUM or LOW when the message signals it, otherwise null.",
        ),
        "extra_stages": {
            "type": "array",
            "items": {"type": "string", "enum": [stage.value for stage in ExtraStage]},
            "description": "Additional stages explicitly asked for; empty if none.",
        },
        "justification": _nullable_string("The user's own reason for HIGH urgency, or null."),
        "confidence": {
            "type": "number",
            "description": "Your estimate, between 0 and 1, that the whole intent is right.",
        },
    }

    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(properties),
        "properties": properties,
    }


def catalog_fingerprint(catalog: Catalog) -> str:
    """A short hash of what the schema and prompt are built from.

    Feeds the response cache key, so an answer built against yesterday's catalog is never served
    after a service is added or a suite renamed. Branch names are not included: they come from Git
    at validation time, not from the catalog, and do not appear in the schema.
    """
    material = [
        {
            "name": service.name,
            "default_branch": service.default_branch,
            "suites": sorted(suite.name for suite in service.test_suites),
            "environments": sorted(service.allowed_environments),
            "extra_stages": sorted(service.extra_stages),
        }
        for service in sorted(catalog.services(), key=lambda entry: entry.name)
    ]
    digest = hashlib.sha256(json.dumps(material, sort_keys=True).encode("utf-8")).hexdigest()
    return digest[:16]


def catalog_context(catalog: Catalog) -> str:
    """The catalog as the prompt's ``{{catalog}}`` placeholder renders it.

    Compact, one service per line: every token here is paid on every request, and the free tier
    allows 8,000 a minute.
    """
    lines: list[str] = []
    for service in sorted(catalog.services(), key=lambda entry: entry.name):
        suites = ", ".join(suite.name for suite in service.test_suites) or "none"
        environments = ", ".join(service.allowed_environments) or "none"
        stages = ", ".join(sorted(service.extra_stages)) or "none"
        lines.append(
            f"- {service.name}: default branch {service.default_branch}; test suites: {suites}; "
            f"environments: {environments}; extra stages: {stages}"
        )
    return "\n".join(lines)
