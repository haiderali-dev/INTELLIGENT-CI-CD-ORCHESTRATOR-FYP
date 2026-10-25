"""Print report Appendix C, the worked example of the priority score, from the plugin itself.

    python scripts/report/appendix_c.py --build      # run the plugin's export test, then print
    python scripts/report/appendix_c.py              # print from the last export
    python scripts/report/appendix_c.py --json       # the export as JSON

BUILD_PROMPT 4.10: "prints the Appendix C table from the same fixture AppendixCExampleTest uses,
so the report can never drift from the code."

The numbers are not computed here. ``AppendixCExportTest`` runs the plugin's own
``PriorityScoreCalculator`` on ``AppendixCFixture`` -- the fixture ``AppendixCExampleTest`` asserts
-- and writes ``plugin/target/appendix-c.json``; this script only formats that file. A Python copy
of the formula would have reopened Milestone 2's failure: a published formula and an implemented
one, with nothing to say they differ.

The table has both scores (docs/decisions.md D-004): the score on the job's own merit, which the
report's printed table showed, and the effective score after group inheritance, which its prose
gave. A single column is what made 0.633 and 0.650 read as a contradiction.

An export older than the fixture or the calculator is refused: rebuild with ``--build``.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN = REPO_ROOT / "plugin"
EXPORT = PLUGIN / "target" / "appendix-c.json"
SCORING = PLUGIN / "src" / "main" / "java" / "io" / "jenkins" / "plugins" / "queueoptimizer"
SOURCES = (
    PLUGIN / "src" / "test" / "java" / "io" / "jenkins" / "plugins" / "queueoptimizer" / "scoring"
    / "AppendixCFixture.java",
    SCORING / "scoring" / "PriorityScoreCalculator.java",
)
EXPORT_TEST = "AppendixCExportTest"


def build() -> None:
    """Run the export test, and the example test beside it, in the plugin's own build."""
    mvn = "mvn.cmd" if os.name == "nt" else "mvn"
    result = subprocess.run(
        [
            mvn,
            "-B",
            "-q",
            "-o",
            f"-Dtest={EXPORT_TEST},AppendixCExampleTest",
            "-Dsurefire.failIfNoSpecifiedTests=false",
            "-Djacoco.skip=true",
            "test",
        ],
        cwd=PLUGIN,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        tail = [line for line in (result.stdout + result.stderr).splitlines() if line.strip()]
        raise SystemExit("the plugin's Appendix C tests failed:\n  " + "\n  ".join(tail[-8:]))


def load() -> dict[str, Any]:
    if not EXPORT.is_file():
        raise SystemExit(f"{EXPORT.relative_to(REPO_ROOT)} does not exist; run with --build")
    newest = max(source.stat().st_mtime for source in SOURCES)
    if EXPORT.stat().st_mtime < newest:
        raise SystemExit(
            f"{EXPORT.relative_to(REPO_ROOT)} is older than the fixture or the calculator; "
            "run with --build"
        )
    data: dict[str, Any] = json.loads(EXPORT.read_text(encoding="utf-8"))
    return data


def _three(value: float) -> str:
    return f"{value:.3f}"


def render(data: dict[str, Any]) -> str:
    rows = data["rows"]
    lines = [
        "Table 13.2: Worked example of the priority score",
        "",
        "Score = 0.5·U + 0.3·D + 0.2·T, plus an aging bonus of min(0.15, 0.05·floor(wait minutes",
        "/ 5)), none of which has accumulated in this snapshot. U is 1.0 for HIGH, 0.6 for MEDIUM",
        "and 0.3 for LOW. D is (group size - 1) / (largest group size - 1), and 0 for an",
        "independent job. T is 1 - (estimate - shortest) / (longest - shortest) over the queue, and",
        "0.5 when no estimate is usable. A job in a group takes the best score of its members.",
        "",
        "| Job | Priority | Estimate (min) | Group | U | D | T | Own score | Score after "
        "inheritance | Dispatch order |",
        "| --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        group = row["group"] if row["group_size"] > 1 else "none"
        estimate = row["estimate_minutes"]
        lines.append(
            f"| {row['job']} | {row['level']} | "
            f"{'unknown' if estimate is None else f'{estimate:g}'} | {group} "
            f"| {row['U']:.1f} | {row['D']:.1f} | {_three(row['T'])} "
            f"| {_three(row['own'])} | {_three(row['effective'])}"
            f"{' (inherited)' if row['inherited'] else ''} | {row['dispatch_position']} |"
        )
    groups = sorted({row["group"] for row in rows if row["group_size"] > 1})
    for group in groups:
        members = [row for row in rows if row["group"] == group]
        best = max(row["effective"] for row in members)
        names = " and ".join(row["job"] for row in sorted(members, key=lambda r: r["rank_in_group"]))
        lines += [
            "",
            f"Group {group} ({names}) takes the maximum score of its members, {_three(best)}; "
            "within the group, producers dispatch before their consumers.",
        ]
    order = [row["job"] for row in sorted(rows, key=lambda r: r["dispatch_position"])]
    lines += ["", "Dispatch order: " + ", ".join(order) + "."]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--build", action="store_true", help="run the plugin's export test first")
    parser.add_argument("--json", action="store_true", help="print the export as JSON")
    args = parser.parse_args(argv)
    if args.build:
        build()
    data = load()
    sys.stdout.write(json.dumps(data, indent=2) + "\n" if args.json else render(data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
