"""Every test the chapter names must have run and passed in the register.

    check_cited_tests.py <chapter.md> <test-register.csv>

A name is a backticked identifier that is a test class (ends in Test or IT), a class and method
(Class.method), or a Python test function (test_...). A class passes when every test of it in the
register passed; a method or function, when it did. Anything not found, or not passed, is listed.
"""

import csv
import re
import sys
from collections import defaultdict

chapter, register = sys.argv[1], sys.argv[2]
text = open(chapter, encoding="utf-8").read()
rows = list(csv.DictReader(open(register, encoding="utf-8")))

by_class = defaultdict(list)
by_name = defaultdict(list)
for row in rows:
    file = row["file"].replace("\\", "/")
    stem = file.rsplit("/", 1)[-1].split(".", 1)[0]
    by_class[stem].append(row)
    test = row["test"]
    # Java: "Class.method" or a display name; Python: "test_x" or "test_x[param]".
    base = test.split("[", 1)[0]
    by_name[base].append(row)
    by_name[base.rsplit(".", 1)[-1]].append(row)
    by_name[f"{stem}.{base.rsplit('.', 1)[-1]}"].append(row)

cited = sorted(set(re.findall(r"`([A-Za-z_][A-Za-z0-9_]*(?:Test|IT)(?:\.[A-Za-z0-9_]+)?|test_[a-z0-9_]+)`", text)))
problems = []
for name in cited:
    found = by_name.get(name) or (by_class.get(name) if "." not in name else None)
    if not found:
        problems.append(f"not in the register: {name}")
        continue
    results = {row["result"] for row in found}
    if results != {"passed"}:
        problems.append(f"{name}: {sorted(results)}")
print(f"{len(cited)} tests or classes cited; {len(cited) - len(problems)} ran and passed")
for problem in problems:
    print("  " + problem)
sys.exit(1 if problems else 0)
