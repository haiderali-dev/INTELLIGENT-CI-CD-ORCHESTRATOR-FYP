"""The schema export the frontend's API types are generated from (T6.2)."""

from __future__ import annotations

import json
from pathlib import Path

from app.openapi_export import export_schema, main, render


def test_export_is_byte_for_byte_stable() -> None:
    # A diff of the committed schema must show only real API changes.
    assert render(export_schema()) == render(export_schema())


def test_export_has_what_the_frontend_is_built_on() -> None:
    schema = export_schema()
    paths = schema["paths"]
    for path in ("/api/auth/login", "/api/auth/refresh", "/api/me", "/api/queue", "/api/health"):
        assert path in paths, path
    item = schema["components"]["schemas"]["QueueItemResponse"]["properties"]
    # The score bar is drawn from these.
    assert {"score", "components", "estimate_seconds", "wait_seconds", "blocked_reason"} <= set(
        item
    )
    assert "weights" in schema["components"]["schemas"]["QueueResponse"]["properties"]


def test_main_writes_the_file(tmp_path: Path) -> None:
    target = tmp_path / "openapi.json"
    assert main([str(target)]) == 0
    written = target.read_text(encoding="utf-8")
    assert written.endswith("}\n")
    assert json.loads(written)["info"]["title"] == "Intelligent CI/CD Orchestrator"


def test_main_needs_exactly_one_path(capsys: object) -> None:
    assert main([]) == 2
    assert main(["a.json", "b.json"]) == 2
