"""The chatbot evaluation's results, for the Analytics page (T8.2).

``python -m eval report`` writes ``eval/results/report.json``, and this reads it. Nothing is
computed here: the figures are the evaluation harness's, as it wrote them, so the page and Chapter
12 cannot disagree (``eval/report.py`` builds both from the same function).

A missing or unreadable file is "not available", with the reason, never an empty table. An empty
table would read as "nothing was measured", or worse as zeros.

The file is found the way the catalog is: from ``backend/`` on a developer machine, and from
``/app`` in the container, where Compose mounts ``eval/results`` read-only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.settings import Settings


def evaluation_report_path(settings: Settings) -> Path:
    configured = Path(settings.evaluation_report_path)
    if configured.is_absolute():
        return configured
    for base in (Path.cwd(), Path.cwd().parent, Path(__file__).resolve().parents[3]):
        candidate = base / configured
        if candidate.is_file():
            return candidate
    return Path.cwd() / configured


def read_report(settings: Settings) -> tuple[dict[str, Any] | None, str | None]:
    """The report, or None and why there is none. Synchronous; call it through ``to_thread``."""
    path = evaluation_report_path(settings)
    if not path.is_file():
        return None, (
            "No evaluation report has been generated yet. Run `python -m eval report` after the "
            "evaluation runs."
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, f"The evaluation report could not be read: {type(exc).__name__}."
    if not isinstance(data, dict):
        return None, "The evaluation report is not in the expected format."
    return data, None
