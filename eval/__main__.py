"""``python -m eval``: run a parser over a dataset, or write the report.

Run with the backend's environment, which has the dependencies::

    uv run --project backend python -m eval run --parser rules --file eval/datasets/sample.jsonl
    uv run --project backend python -m eval run --parser groq:openai/gpt-oss-120b --file ...
    uv run --project backend python -m eval check --file eval/datasets/sample.jsonl
    uv run --project backend python -m eval report
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from pathlib import Path

try:
    from app.ai.prompting import load_prompt
    from app.services.catalog import Catalog
except ImportError as exc:  # pragma: no cover - a usage error, not a code path
    raise SystemExit(
        f"{exc}. Run with the backend's environment:\n  uv run --project backend python -m eval ..."
    ) from exc

from eval.dataset import DatasetError, load_dataset, overlap_with_examples
from eval.report import write_report
from eval.runner import REPO_ROOT, RunConfig, default_out_dir, run

CATALOG = REPO_ROOT / "catalog" / "services.yaml"


def _groq_key() -> str | None:
    """From the environment, else from .env. Never printed."""
    if os.environ.get("GROQ_API_KEY"):
        return os.environ["GROQ_API_KEY"]
    env_file = REPO_ROOT / ".env"
    if env_file.is_file():
        found = re.search(r"^GROQ_API_KEY=(.*)$", env_file.read_text(encoding="utf-8"), re.M)
        if found and found.group(1).strip():
            return found.group(1).strip()
    return None


def _check(path: Path) -> int:
    dataset = load_dataset(path)
    print(
        f"{len(dataset.items)} item(s): {len(dataset.scorable)} reviewed, "
        f"{len(dataset.needs_review)} awaiting review"
    )
    for warning in dataset.warnings:
        print(f"  warning: {warning}")
    clash = overlap_with_examples(dataset, [example.user for example in load_prompt().examples])
    if clash:
        print(f"  ERROR: these items repeat a few-shot example in the prompt: {clash}")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m eval")
    commands = parser.add_subparsers(dest="command", required=True)

    run_cmd = commands.add_parser("run", help="score one parser on a dataset")
    run_cmd.add_argument("--parser", required=True, help="rules, fake, or groq:<model>")
    run_cmd.add_argument("--file", required=True, type=Path)
    run_cmd.add_argument("--out", type=Path, help="results directory (default: per configuration)")
    run_cmd.add_argument(
        "--include-unreviewed",
        action="store_true",
        help="also score items marked needs_review; the output is stamped not-for-reporting",
    )
    run_cmd.add_argument(
        "--no-examples", action="store_true", help="4.9 ablation: no few-shot examples"
    )
    run_cmd.add_argument("--no-enums", action="store_true", help="4.9 ablation: no catalog enums")
    run_cmd.add_argument(
        "--fresh", action="store_true", help="discard saved progress and start over"
    )

    check_cmd = commands.add_parser("check", help="validate a dataset without running anything")
    check_cmd.add_argument("--file", required=True, type=Path)

    commands.add_parser("report", help="write report.json and report.md from finished runs")

    args = parser.parse_args(argv)

    try:
        if args.command == "check":
            return _check(args.file)

        if args.command == "report":
            json_path, md_path = write_report()
            print(f"wrote {json_path.relative_to(REPO_ROOT)} and {md_path.relative_to(REPO_ROOT)}")
            return 0

        dataset = load_dataset(args.file)
        if _check(args.file) != 0:
            return 1
        # Resolved, so a relative --out works from any directory and prints cleanly below.
        out_dir = (
            args.out.resolve()
            if args.out
            else default_out_dir(
                args.parser,
                args.file,
                include_examples=not args.no_examples,
                include_enums=not args.no_enums,
            )
        )
        config = RunConfig(
            parser=args.parser,
            dataset=args.file.resolve(),
            out_dir=out_dir,
            include_unreviewed=args.include_unreviewed,
            include_examples=not args.no_examples,
            include_enums=not args.no_enums,
            fresh=args.fresh,
        )
        report = asyncio.run(run(config, dataset, Catalog(CATALOG), groq_key=_groq_key()))
    except DatasetError as exc:
        print(f"dataset error: {exc}", file=sys.stderr)
        return 2

    metrics = report["metrics"]
    print(f"scored {metrics['n']} item(s), {metrics['errors']} error(s)")
    print(
        f"action accuracy {metrics['action_accuracy']}, "
        f"behaviour accuracy {metrics['behavior_accuracy']}"
    )
    if "warning" in report:
        print(f"note: {report['warning']}")
    print(f"metrics: {(out_dir / 'metrics.json').relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
