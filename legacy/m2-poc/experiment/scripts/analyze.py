#!/usr/bin/env python3
"""
Reads jobs.json (static job spec: priority/category/dependsOn/duration) plus
baseline-results.json and plugin-results.json (runtime measurements from
run_experiment.py) and writes results/comparison.json for the dashboard.
"""

import argparse
import json
import os

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = os.path.abspath(os.path.join(SCRIPTS_DIR, "..", "results"))


def load_json(name):
    with open(os.path.join(RESULTS_DIR, name), "r", encoding="utf-8") as f:
        return json.load(f)


def load_spec():
    with open(os.path.join(SCRIPTS_DIR, "jobs.json"), "r", encoding="utf-8") as f:
        return json.load(f)


def build_run_view(run, spec_by_name):
    """Returns {jobName: {start, wait, exec, completion, order, result}} in seconds."""
    t0 = run["t0"]
    rows = []
    for j in run["jobs"]:
        name = j["name"]
        if name not in spec_by_name:
            continue
        start_ms = j.get("startTime")
        dur_ms = j.get("duration") or 0
        if start_ms is None:
            continue
        wait_s = (start_ms - t0) / 1000.0
        exec_s = dur_ms / 1000.0
        completion_s = wait_s + exec_s
        rows.append({
            "name": name,
            "result": j.get("result"),
            "wait": round(wait_s, 2),
            "exec": round(exec_s, 2),
            "completion": round(completion_s, 2),
            "startSec": round(wait_s, 2),
        })

    rows.sort(key=lambda r: r["completion"])
    for idx, r in enumerate(rows):
        r["order"] = idx + 1

    return {r["name"]: r for r in rows}


def avg(values):
    return round(sum(values) / len(values), 2) if values else 0.0


def pct_change(before, after):
    if before == 0:
        return 0.0
    return round(100.0 * (before - after) / before, 1)


def throughput_series(view):
    points = sorted((r["completion"] for r in view.values()))
    series = [[0.0, 0]]
    for i, t in enumerate(points, start=1):
        series.append([t, i])
    return series


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-results", default="baseline-results.json")
    parser.add_argument("--plugin-results", default="plugin-results.json")
    parser.add_argument("--output", default="comparison.json")
    args = parser.parse_args()

    spec = load_spec()
    spec_by_name = {s["name"]: s for s in spec}

    baseline_run = load_json(args.baseline_results)
    plugin_run = load_json(args.plugin_results)

    baseline_view = build_run_view(baseline_run, spec_by_name)
    plugin_view = build_run_view(plugin_run, spec_by_name)

    # ---- Per-job table ------------------------------------------------
    jobs_out = []
    for s in spec:
        name = s["name"]
        b = baseline_view.get(name)
        p = plugin_view.get(name)
        entry = {
            "name": name,
            "category": s["category"],
            "priority": s["priority"],
            "duration": s["duration"],
            "dependsOn": s["dependsOn"],
            "baseline": b,
            "plugin": p,
        }
        if b and p:
            entry["waitDeltaPct"] = pct_change(b["wait"], p["wait"])
            entry["orderDelta"] = b["order"] - p["order"]
        jobs_out.append(entry)

    # ---- Priority band aggregates --------------------------------------
    bands = {}
    for band in ("HIGH", "MEDIUM", "LOW"):
        names = [s["name"] for s in spec if s["priority"] == band]
        b_waits = [baseline_view[n]["wait"] for n in names if n in baseline_view]
        p_waits = [plugin_view[n]["wait"] for n in names if n in plugin_view]
        b_comps = [baseline_view[n]["completion"] for n in names if n in baseline_view]
        p_comps = [plugin_view[n]["completion"] for n in names if n in plugin_view]
        bands[band] = {
            "count": len(names),
            "avgWaitBaseline": avg(b_waits),
            "avgWaitPlugin": avg(p_waits),
            "waitImprovementPct": pct_change(avg(b_waits), avg(p_waits)),
            "avgCompletionBaseline": avg(b_comps),
            "avgCompletionPlugin": avg(p_comps),
            "completionImprovementPct": pct_change(avg(b_comps), avg(p_comps)),
        }

    # ---- Category aggregates (similar-job groupings) -------------------
    categories = sorted(set(s["category"] for s in spec))
    category_stats = {}
    for cat in categories:
        names = [s["name"] for s in spec if s["category"] == cat]
        b_waits = [baseline_view[n]["wait"] for n in names if n in baseline_view]
        p_waits = [plugin_view[n]["wait"] for n in names if n in plugin_view]
        category_stats[cat] = {
            "count": len(names),
            "avgDuration": avg([s["duration"] for s in spec if s["category"] == cat]),
            "avgWaitBaseline": avg(b_waits),
            "avgWaitPlugin": avg(p_waits),
        }

    # ---- Dependency chain analysis --------------------------------------
    dependency_chains = []
    for s in spec:
        if not s["dependsOn"]:
            continue
        name = s["name"]
        chain = {"name": name, "dependsOn": s["dependsOn"], "priority": s["priority"]}
        for label, view in (("baseline", baseline_view), ("plugin", plugin_view)):
            job_row = view.get(name)
            if not job_row:
                continue
            dep_completions = [view[d]["completion"] for d in s["dependsOn"] if d in view]
            honored = all(dc <= job_row["startSec"] for dc in dep_completions) if dep_completions else True
            chain[label] = {
                "jobStart": job_row["startSec"],
                "depCompletions": [round(dc, 2) for dc in dep_completions],
                "honored": honored,
            }
        dependency_chains.append(chain)

    # ---- Overall summary --------------------------------------------------
    makespan_baseline = max((r["completion"] for r in baseline_view.values()), default=0)
    makespan_plugin = max((r["completion"] for r in plugin_view.values()), default=0)
    avg_wait_baseline = avg([r["wait"] for r in baseline_view.values()])
    avg_wait_plugin = avg([r["wait"] for r in plugin_view.values()])

    comparison = {
        "meta": {
            "baselineT0": baseline_run["t0"],
            "pluginT0": plugin_run["t0"],
            "jobCount": len(spec),
        },
        "summary": {
            "makespanBaseline": round(makespan_baseline, 2),
            "makespanPlugin": round(makespan_plugin, 2),
            "makespanDeltaPct": pct_change(makespan_baseline, makespan_plugin),
            "avgWaitBaseline": avg_wait_baseline,
            "avgWaitPlugin": avg_wait_plugin,
            "avgWaitImprovementPct": pct_change(avg_wait_baseline, avg_wait_plugin),
            "priorityBands": bands,
        },
        "categories": category_stats,
        "jobs": jobs_out,
        "throughput": {
            "baseline": throughput_series(baseline_view),
            "plugin": throughput_series(plugin_view),
        },
        "dependencyChains": dependency_chains,
    }

    out_path = os.path.join(RESULTS_DIR, args.output)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(comparison, f, indent=2)

    print(f"Wrote {out_path}")
    print(f"Makespan: baseline={makespan_baseline:.1f}s plugin={makespan_plugin:.1f}s")
    print(f"Avg wait: baseline={avg_wait_baseline:.1f}s plugin={avg_wait_plugin:.1f}s "
          f"({pct_change(avg_wait_baseline, avg_wait_plugin)}% change)")
    for band, stats in bands.items():
        print(f"  {band}: avgWait {stats['avgWaitBaseline']}s -> {stats['avgWaitPlugin']}s "
              f"({stats['waitImprovementPct']}%)")


if __name__ == "__main__":
    main()
