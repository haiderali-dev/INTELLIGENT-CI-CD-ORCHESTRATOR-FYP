"""Check that every test the testing chapter cites ran and passed, by the test register.

    python scripts/report/check_citations.py [docs/testing/chapter-8-software-testing.md]

The chapter names tests three ways, and each is looked up in ``docs/testing/data/test-register.csv``:

- by identifier, in backticks: a test class (``AgingTest``, ``DependencyGateIT``), a class and method
  (``AgingTest.bonusStepsAndCaps``) or a Python test function (``test_login_is_rate_limited``). A
  parameterised test matches all its cases, and every case must have passed;
- by file, in backticks (``test_ws.py``, ``RunCard.test.tsx``): every test in it must have passed, and
  a count the chapter gives with it, as "`test_x.py` (9" or "25 in `test_x.py`", must be right;
- by title: browser flows, system tests, frontend tests and gate checks, listed in TITLES below with
  the suite they belong to. Each title must still be in the chapter, so the list follows the text.

Exits 1 when anything is not found, did not pass, or is miscounted.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTER = REPO_ROOT / "docs" / "testing" / "data" / "test-register.csv"
CHAPTER = REPO_ROOT / "docs" / "testing" / "chapter-8-software-testing.md"

# Tests the chapter names by their titles: (the words, as both the chapter and the test have them,
# the suite the test is in).
TITLES = [
    ("a freestyle deploy, with a clarification, through to Run started", "Browser flows"),
    ("refuses a production deploy and says why", "Browser flows"),
    ("shows a HIGH job above a LOW job, in the plugin's order", "Browser flows"),
    ("returns to the page that was asked for", "Browser flows"),
    ("a Developer is not offered Admin", "Browser flows"),
    ("with the keyboard alone", "Browser flows"),
    ("the app runs under its Content-Security-Policy without a single violation", "Browser flows"),
    ("a freestyle build runs on the real Jenkins, and its run card follows it live", "System tests on the running stack"),
    ("a Pipeline build is linted and run by the real Jenkins, its stages followed live", "System tests on the running stack"),
    ("follows queue events", "Frontend unit and component tests"),
    ("asks again on every event that moves a run in or out of the queue", "Frontend unit and component tests"),
    ("asks again every 10 seconds", "Frontend unit and component tests"),
    ("opens a failed run", "Frontend unit and component tests"),
    ("follows the runs as events arrive", "Frontend unit and component tests"),
    ("a live plugin event reaches the backend", "Phase acceptance gate"),
    ("every published port is bound to loopback", "Phase acceptance gate"),
]
# Frontend tests the chapter names by the component they test ("`RunCard` tests").
COMPONENTS = ["RunCard", "LiveEventsClient"]

IDENTIFIER = re.compile(r"`([A-Za-z_][A-Za-z0-9_]*(?:Test|IT)(?:\.[A-Za-z0-9_]+)?|test_[a-z0-9_]+)`")
TEST_FILE = re.compile(r"`([\w.-]+(?:\.test\.tsx?|\.spec\.ts)|test_[\w]+\.py)`")
COUNT_AFTER = re.compile(r"`([\w.-]+)` \((\d+)[):]")
COUNT_BEFORE = re.compile(r"\b(\d+) in `([\w.-]+)`")


def base_name(test: str) -> str:
    """'AgingTest.bonusStepsAndCaps(long, double)[3]' -> 'AgingTest.bonusStepsAndCaps'; 'test_x[a]' -> 'test_x'."""
    return re.sub(r"\(.*\)$", "", test.split("[", 1)[0])


def verdict(rows: list[dict[str, str]]) -> str | None:
    """None when every row passed; otherwise what is wrong."""
    if not rows:
        return "not in the register"
    results = sorted({row["result"] for row in rows})
    return None if results == ["passed"] else f"results {results}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("chapter", type=Path, nargs="?", default=CHAPTER)
    args = parser.parse_args()
    text = args.chapter.read_text(encoding="utf-8")
    with REGISTER.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    by_name: dict[str, list[dict[str, str]]] = defaultdict(list)
    by_file: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        file_name = Path(row["file"]).name
        by_file[file_name].append(row)
        base = base_name(row["test"])
        by_name[base].append(row)
        if "." in base:
            by_name[f"{Path(file_name).stem.split('.')[0]}.{base.rsplit('.', 1)[-1]}"].append(row)
        if row["component"] == "Plugin":
            by_name[Path(file_name).stem].append(row)

    problems: list[str] = []
    identifiers = sorted(set(IDENTIFIER.findall(text)))
    for name in identifiers:
        if (wrong := verdict(by_name.get(name, []))) is not None:
            problems.append(f"`{name}`: {wrong}")

    files = sorted(set(TEST_FILE.findall(text)))
    for name in files:
        if (wrong := verdict(by_file.get(name, []))) is not None:
            problems.append(f"`{name}`: {wrong}")
    counts = [(name, int(n)) for name, n in COUNT_AFTER.findall(text)] + [(name, int(n)) for n, name in COUNT_BEFORE.findall(text)]
    miscounted = [f"`{name}`: the chapter says {stated} tests, the register has {len(by_file[name])}"
                  for name, stated in counts if name in by_file and len(by_file[name]) != stated]

    for title, suite in TITLES:
        if title not in text:
            problems.append(f"title no longer in the chapter (update TITLES): {title}")
            continue
        found = [row for row in rows if row["suite"].startswith(suite) and title in row["test"]]
        if (wrong := verdict(found)) is not None:
            problems.append(f"{suite}, {title!r}: {wrong}")
    for component in COMPONENTS:
        found = [row for row in rows if row["test"].startswith(f"{component} > ")]
        if f"`{component}` tests" not in text:
            problems.append(f"component no longer in the chapter (update COMPONENTS): {component}")
        elif (wrong := verdict(found)) is not None:
            problems.append(f"`{component}` tests: {wrong}")

    named = len(identifiers) + len(files) + len(TITLES) + len(COMPONENTS)
    print(f"{args.chapter.name}: {len(identifiers)} test names, {len(files)} test files, {len(TITLES)} titles and "
          f"{len(COMPONENTS)} components cited; {named - len(problems)} of {named} ran and passed in the register "
          f"({len(rows)} tests); {len(counts) - len(miscounted)} of {len(counts)} stated counts right")
    for problem in problems + miscounted:
        print("  " + problem)
    return 1 if problems or miscounted else 0


if __name__ == "__main__":
    sys.exit(main())
