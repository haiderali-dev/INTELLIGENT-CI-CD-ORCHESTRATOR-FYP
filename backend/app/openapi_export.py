"""Write the API's OpenAPI schema to a file, with no server, no database and no ``.env``.

BUILD_PROMPT 4.7.1: "API types are generated from the backend OpenAPI schema; never hand-write
them." The frontend generates its types from the file this writes. Exporting from the app object,
rather than fetching ``/openapi.json`` from a running backend, means the types can be regenerated
and checked for drift on a machine with no stack running, which is every CI runner.

    uv run --no-sync python -m app.openapi_export ../frontend/openapi.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from app.core.settings import Environment, LlmMode, Settings
from app.main import create_app


def export_schema() -> dict[str, Any]:
    """The schema the running app serves at ``/openapi.json``.

    The settings are placeholders that only satisfy validation; nothing in the schema depends on
    them. ``_env_file=None`` keeps a developer's ``.env`` out of it entirely.
    """
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        environment=Environment.TEST,
        database_url="sqlite+aiosqlite:///:memory:",
        llm_mode=LlmMode.FAKE,
        jenkins_url="http://jenkins-dev:8080",
        jenkins_user="schema-export",
        jenkins_token="schema-export",
        seed_admin_email="schema-export@example.com",
        seed_admin_password="schema-export-only",
    )
    return create_app(settings).openapi()


def render(schema: dict[str, Any]) -> str:
    """Stable text: sorted keys, two-space indent, one trailing newline, so a diff shows only real
    API changes."""
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: python -m app.openapi_export <output.json>", file=sys.stderr)
        return 2
    target = Path(args[0])
    schema = export_schema()
    target.write_text(render(schema), encoding="utf-8", newline="\n")
    print(f"wrote {target}: {len(schema['paths'])} paths, OpenAPI {schema['openapi']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
