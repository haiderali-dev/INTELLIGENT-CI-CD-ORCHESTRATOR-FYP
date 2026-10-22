"""``analyze``: a run folder's raw files to its KPIs, ``analysis.json``, then ``latest.json``.

It works from the run's own record of what it ran: the workload is rebuilt from ``run.json``,
not read from today's file, so a run analysed again a month later gives the same figures.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from experiment import kpis, records, results, workload


class AnalysisError(ValueError):
    """A run folder that cannot be analysed as it stands."""


def condition(meta: dict[str, Any]) -> dict[str, Any]:
    """The experimental condition a run measured, which ``report`` groups repetitions by."""
    order = meta["order"]
    return {
        "group": meta["group"],
        "workload": meta["workload"]["name"],
        "executors": meta["executors"],
        "history": meta["history"]["kind"],
        "order": "fixed" if order["seed"] is None else f"seed {order['seed']}",
        "arm": meta["arm"],
        "repetition": meta["repetition"],
        "controller": meta["controller"],
        "jenkinsVersion": meta.get("jenkinsVersion"),
        "pluginVersion": meta.get("pluginVersion"),
        "pluginBuild": meta.get("pluginBuild"),
    }


def analyze(run_dir: Path, update_latest: bool = True) -> dict[str, Any]:
    """Compute the run's KPIs, write ``analysis.json``, and point ``latest.json`` at it."""
    if not (run_dir / "run.json").is_file():
        raise AnalysisError(f"{run_dir}: no run.json, so not a run folder")
    meta = results.read_json(run_dir / "run.json")
    if not meta.get("complete"):
        reason = meta.get("incompleteReason") or "no reason recorded"
        raise AnalysisError(f"{run_dir.name}: the run did not complete ({reason})")
    loaded = workload.parse(json.loads(meta["workload"]["source"]))
    if loaded.digest != meta["workload"]["digest"]:
        raise AnalysisError(f"{run_dir.name}: the recorded workload does not match its digest")

    events = results.read_jsonl(run_dir / "events.jsonl")
    builds = results.read_json(run_dir / "builds.json")
    health = results.read_jsonl(run_dir / "health.jsonl")
    try:
        found = records.records_from_events(loaded, events, builds, meta.get("triggeredMs"))
    except records.RecordError as exc:
        raise AnalysisError(f"{run_dir.name}: {exc}") from exc

    analysis = {
        "run": run_dir.name,
        "analyzedAt": datetime.now(UTC).isoformat(timespec="seconds"),
        "condition": condition(meta),
        "kpis": kpis.run_kpis(found, loaded.edges, int(meta["executors"]), health),
        "jobs": [record.as_dict() for record in found],
    }
    results.write_json(run_dir / "analysis.json", analysis)
    if update_latest:
        results.update_latest(run_dir, analysis)
    return analysis
