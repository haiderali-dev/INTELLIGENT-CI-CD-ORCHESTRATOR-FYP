"""The schema export the frontend's API types are generated from (T6.2)."""

from __future__ import annotations

import json
from pathlib import Path

from app.core.errors import ApiError, ErrorCode, ErrorResponse
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


def test_every_operation_documents_the_one_error_shape() -> None:
    # D-055: the frontend switches on error codes, so they must reach its generated types.
    schema = export_schema()
    expected = {"$ref": "#/components/schemas/ErrorResponse"}
    operations = 0
    for path, item in schema["paths"].items():
        for method, operation in item.items():
            operations += 1
            for status in ("4XX", "5XX"):
                content = operation["responses"][status]["content"]["application/json"]
                assert content["schema"] == expected, (method, path, status)
    assert operations >= 39
    documented = schema["components"]["schemas"]["ErrorCode"]["enum"]
    assert sorted(documented) == sorted(code.value for code in ErrorCode)


def test_no_operation_promises_a_shape_the_api_never_sends() -> None:
    # FastAPI documents 422 as its own HTTPValidationError unless told otherwise. This API sends
    # validation failures in the error shape (app/core/errors.py), so that entry would be false.
    assert "HTTPValidationError" not in render(export_schema())


def test_the_documented_error_shape_is_the_one_sent() -> None:
    error = ApiError(
        ErrorCode.RATE_LIMITED,
        "Too many requests.",
        status_code=429,
        details={"retry_after_seconds": 12, "limit": "login"},
    )
    payload = error.to_payload()
    assert ErrorResponse.model_validate(payload).model_dump(mode="json") == payload


def test_main_writes_the_file(tmp_path: Path) -> None:
    target = tmp_path / "openapi.json"
    assert main([str(target)]) == 0
    written = target.read_text(encoding="utf-8")
    assert written.endswith("}\n")
    assert json.loads(written)["info"]["title"] == "Intelligent CI/CD Orchestrator"


def test_main_needs_exactly_one_path(capsys: object) -> None:
    assert main([]) == 2
    assert main(["a.json", "b.json"]) == 2
