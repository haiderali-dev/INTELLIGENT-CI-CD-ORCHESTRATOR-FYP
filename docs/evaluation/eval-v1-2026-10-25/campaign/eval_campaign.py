"""The Phase 8 live evaluation campaign: every live run 4.9 asks for, one queue per model.

From the repository root, in PowerShell (a terminal of your own: Claude Code stops its background
commands when memory runs short, and stopped this one at 05:59 on 2026-10-25):

    & .venv-tools\\Scripts\\python.exe docs\\evaluation\\eval-v1-2026-10-25\\campaign\\eval_campaign.py

    python eval_campaign.py            # all queues, in parallel; rerun to resume
    python eval_campaign.py 120b       # one queue
    python eval_campaign.py --stop-on-quota  # save progress and exit when quota blocks a queue

The models' quotas are separate (Groq counts per model), so the three queues run side by side;
within a queue the steps run one after another, in the order below, the headline first. Every step
is a `python -m eval` command, which resumes where it stopped. When a step stops for quota (exit
3) the queue waits for the time Groq asked for (or 20 minutes when it said nothing) and runs the
same command again. Any other failure is retried three times, then the queue moves on and says so.

State, beside this file: campaign-log.txt (every event), progress.jsonl (one line per step
finished), steps/<queue>-<n>-<id>.log (each attempt's output). Nothing here reads .env: the
commands do, and never print the key.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

STATE = Path(__file__).resolve().parent
REPO = STATE.parents[3]
LOCAL_UV = REPO / ".venv-tools" / ("Scripts/uv.exe" if os.name == "nt" else "bin/uv")
UV = str(LOCAL_UV) if LOCAL_UV.is_file() else shutil.which("uv") or "uv"
LOG = STATE / "campaign-log.txt"
PROGRESS = STATE / "progress.jsonl"
V1 = "eval/datasets/eval-v1.jsonl"
DEFAULT_WAIT = 20 * 60
MAX_FAILURES = 3

M120 = "groq:openai/gpt-oss-120b"
M20 = "groq:openai/gpt-oss-20b"
QWEN = "groq:qwen/qwen3.8-27b"


def run_args(parser: str, *extra: str) -> list[str]:
    return ["run", "--parser", parser, "--file", V1, "--include-unreviewed", *extra]


QUEUES: dict[str, list[tuple[str, list[str]]]] = {
    "120b": [
        ("test", run_args(M120, "--split", "test")),
        ("e2e", ["e2e", "--parser", M120]),
        ("ablation-no-examples", run_args(M120, "--subset", "ablation", "--no-examples")),
        ("ablation-no-enums", run_args(M120, "--subset", "ablation", "--no-enums")),
        ("ablation-no-repair", run_args(M120, "--subset", "ablation", "--no-repair")),
        ("ablation-full", run_args(M120, "--subset", "ablation")),
        ("dev", run_args(M120, "--split", "dev")),
    ],
    "20b": [
        ("test", run_args(M20, "--split", "test")),
        ("dev", run_args(M20, "--split", "dev")),
    ],
    "qwen": [
        ("test", run_args(QWEN, "--split", "test")),
        ("dev", run_args(QWEN, "--split", "dev")),
    ],
}

_lock = threading.Lock()


def say(message: str) -> None:
    line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {message}"
    with _lock:
        print(line, flush=True)
        with LOG.open("a", encoding="utf-8") as sink:
            sink.write(line + "\n")


def finished() -> set[str]:
    done: set[str] = set()
    if PROGRESS.is_file():
        for line in PROGRESS.read_text(encoding="utf-8").splitlines():
            if line.strip():
                entry = json.loads(line)
                if entry.get("gave_up"):
                    done.discard(entry["step"])
                else:
                    done.add(entry["step"])
    return done


def record(step: str, **fields: object) -> None:
    with _lock, PROGRESS.open("a", encoding="utf-8") as sink:
        sink.write(json.dumps({"step": step, "at": datetime.now().isoformat(), **fields}) + "\n")


_DURATION = re.compile(r"for (\d+(?:\.\d+)?) (h|min|s)\b")


def wait_for(output: str) -> float:
    """The wait Groq asked for, from the stop message ("rate limited for 13 min"), plus a margin.

    "still rate limited after N attempts" is the minute's limit, not the day's: two minutes.
    """
    if "still rate limited after" in output:
        return 120.0
    found = _DURATION.search(output)
    if not found:
        return DEFAULT_WAIT
    amount, unit = float(found.group(1)), found.group(2)
    seconds = amount * {"h": 3600, "min": 60, "s": 1}[unit]
    return min(max(seconds + 60, 120), 6 * 3600)


def run_queue(name: str, *, stop_on_quota: bool = False) -> int:
    done = finished()
    failed = False
    for number, (step_id, args) in enumerate(QUEUES[name], 1):
        step = f"{name}/{step_id}"
        if step in done:
            continue
        failures = 0
        previous = (STATE / "steps").glob(f"{name}-{number:02d}-{step_id}-*.log")
        attempt = max((int(path.stem.rsplit("-", 1)[1]) for path in previous), default=0)
        while True:
            attempt += 1
            log = STATE / "steps" / f"{name}-{number:02d}-{step_id}-{attempt:02d}.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            say(f"{step}: attempt {attempt}")
            started = time.monotonic()
            with log.open("x", encoding="utf-8") as sink:
                result = subprocess.run(
                    [UV, "run", "--no-sync", "--project", "backend", "python", "-m", "eval", *args],
                    cwd=REPO,
                    stdout=sink,
                    stderr=subprocess.STDOUT,
                    check=False,
                )
            took = round(time.monotonic() - started)
            output = log.read_text(encoding="utf-8", errors="replace")
            tail = " | ".join(
                line.strip()
                for line in output.splitlines()[-4:]
                if line.strip() and "[info" not in line
            )
            if result.returncode == 0:
                say(f"{step}: DONE in {took} s: {tail[:400]}")
                record(step, seconds=took, attempts=attempt)
                break
            if result.returncode == 3:
                pause = wait_for(output)
                if stop_on_quota:
                    say(f"{step}: DEFERRED for quota; retry in {pause / 60:.0f} min: {tail[:300]}")
                    return 1 if failed else 3
                say(f"{step}: QUOTA after {took} s, waiting {pause / 60:.0f} min: {tail[:300]}")
                time.sleep(pause)
                continue
            failures += 1
            say(f"{step}: FAILED (exit {result.returncode}) after {took} s: {tail[:400]}")
            if failures >= MAX_FAILURES:
                say(f"{step}: GIVING UP after {failures} failures; the queue moves on")
                record(step, seconds=took, attempts=attempt, gave_up=True)
                failed = True
                break
            time.sleep(120)
    say(f"queue {name}: finished")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("queues", nargs="*", help=f"model queues: {', '.join(QUEUES)}")
    parser.add_argument("--stop-on-quota", action="store_true")
    args = parser.parse_args(argv)
    names = args.queues or list(QUEUES)
    if any(name not in QUEUES for name in names) or len(set(names)) != len(names):
        parser.error("name each queue at most once: " + ", ".join(QUEUES))
    if os.name == "nt":
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)
    try:
        say(f"CAMPAIGN: queues {', '.join(names)}; done so far: {sorted(finished())}")
        with ThreadPoolExecutor(max_workers=len(names)) as executor:
            futures = [
                executor.submit(run_queue, name, stop_on_quota=args.stop_on_quota) for name in names
            ]
            results = []
            for name, future in zip(names, futures, strict=True):
                try:
                    results.append(future.result())
                except Exception as exc:
                    say(f"queue {name}: FAILED: {type(exc).__name__}: {exc}")
                    results.append(1)
        status = 1 if 1 in results else 3 if 3 in results else 0
        say("CAMPAIGN: " + ("every queue finished" if status == 0 else "unfinished queues remain"))
        return status
    finally:
        if os.name == "nt":
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)


if __name__ == "__main__":
    raise SystemExit(main())
