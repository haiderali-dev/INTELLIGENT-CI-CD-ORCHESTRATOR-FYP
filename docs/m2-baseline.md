# Milestone 2 baseline

What Milestone 2 actually measured, checked against the result files in
`legacy/m2-poc/experiment/results/` rather than copied from the report. Task T0.2.

Method: `legacy/m2-poc/experiment/` was copied to `.tmp/m2-analysis/` (gitignored) and its
`analyze.py` re-run there against each stored plugin result file. Nothing under `legacy/` was
written to.

---

## 1. The Milestone 2 environment

| Property | Value | Source |
| --- | --- | --- |
| Jenkins | 2.479.3, run from the cached WAR via `mvn hpi:run` | `legacy/m2-poc/dynamic-queue-optimizer/pom.xml`, `commands.txt` |
| Plugin | `dynamic-queue-optimizer` 1.0-SNAPSHOT, Java 17 bytecode | `pom.xml` (`java.level` 17) |
| Plugin parent POM | `org.jenkins-ci.plugins:plugin:5.9` | `pom.xml` |
| Controller | One local Jenkins, **1 executor**, builds on the controller itself | `experiment/*-home/config.xml` |
| Agents | None | — |
| Job type | 30 freestyle jobs | `experiment/scripts/jobs.json` |
| Job bodies | Windows `ping -n <seconds+1> 127.0.0.1 > nul` sleeps | `create-jobs-*.groovy.tmpl` |
| Job creation and triggering | Groovy posted to `/scriptText` | `run_experiment.py:73` |
| Baseline arm | A separate Jenkins home with the plugin absent | `commands.txt` |
| Ports | baseline 8085, plugin 8086, dashboard 8000 | `commands.txt` |
| Dashboard | One static HTML file reading `comparison.json` | `experiment/dashboard/index.html` |
| Version control | None. There was no Git repository. | — |

Two of these are the reason version 2 exists in its current shape. The single executor means the
multi-executor path was never exercised, and `/scriptText` means the harness ran with full script
console privileges — both are prohibited in version 2 (`BUILD_PROMPT.md` rule 1.5, target decisions
in Part 2.3).

## 2. The workload

30 freestyle jobs, from `legacy/m2-poc/experiment/scripts/jobs.json`:

| Band | Count | Durations |
| --- | --- | --- |
| HIGH | 9 | 4 to 25 s |
| MEDIUM | 15 | 4 to 25 s |
| LOW | 6 | 5 to 20 s |

Submitted in band order, LOW first, then MEDIUM, then HIGH — the arrival pattern that makes FIFO
look worst and the optimizer look best. 17 dependency edges are declared, mostly
`build-X → test-X → deploy-X` chains, plus `integration-test-suite` depending on three test jobs and
`smoke-test-production → release-notes-generator`.

This confirms `BUILD_PROMPT.md` Part 4.8.1 and contradicts report Appendix B, which describes 25
jobs as 8 HIGH / 9 MEDIUM / 8 LOW with durations of 30 s to 4 minutes. The files agree with
`BUILD_PROMPT.md`. See `docs/report-updates.md`.

## 3. Results

### 3.1 The figures that belong in the report

Reproduced by re-running `analyze.py` against `baseline-results.json` and
`plugin-results-run4.json`, the final run:

| Metric | Baseline FIFO | Plugin, final run | Change |
| --- | --- | --- | --- |
| Makespan | 322.07 s | 328.21 s | −1.9 % |
| Average wait | 156.88 s | 143.02 s | +8.8 % |
| HIGH-band wait | 271.50 s | 39.08 s | **+85.6 %** |
| MEDIUM-band wait | 144.49 s | 169.42 s | −17.3 % |
| LOW-band wait | 15.89 s | 232.94 s | −1366.0 % |

These match `BUILD_PROMPT.md` Part 2.2 to the rounding, so Part 2.2's table is sound.

Honest reading of this result: the plugin did the one thing it was built to do — HIGH-priority jobs
stopped waiting behind routine work, dropping from 271.5 s to 39.1 s. Everything else is the cost of
that. Makespan got slightly *worse*, average wait improved only marginally, and LOW-band jobs paid
for all of it, going from a 16 s wait to 233 s. On a single executor with a fixed set of jobs, total
makespan is bounded below by the sum of durations no matter what order you choose, so reordering can
only move waiting around, never remove it. The LOW-band collapse is also why the aging bonus, which
Milestone 2 never implemented, is mandatory in version 2.

### 3.2 Every stored run, and one that matters

| Result file | Makespan | Avg wait | HIGH wait | MEDIUM wait | LOW wait |
| --- | --- | --- | --- | --- | --- |
| Baseline (FIFO) | 322.07 | 156.88 | 271.50 | 144.49 | 15.89 |
| `plugin-results.json` | 322.43 | 140.88 | 44.88 | 163.50 | 228.31 |
| `plugin-results-run2.json` | 344.35 | 158.92 | 51.27 | 188.57 | 246.30 |
| **`plugin-results-run3.json`** | **407.49** | **212.31** | **353.34** | **201.36** | **28.12** |
| `plugin-results-run4.json` | 328.21 | 143.02 | 39.08 | 169.42 | 232.94 |

**Run 3 is not noise, and it is not being discarded.** Its HIGH-band wait of 353.34 s is *worse*
than the FIFO baseline's 271.50 s, while its LOW-band wait of 28.12 s is close to the baseline's
15.89 s. That profile is the signature of arrival order, not priority order: the plugin was loaded
and enabled, and it produced FIFO results anyway.

This is Milestone 2 known problem 6 caught on the record — the change that skipped heap
repopulation and silently degraded the dispatcher to FIFO. The plugin had no test that would have
noticed, so the only evidence it ever happened is this one result file. It is the reason
`CacheEvictionRegressionIT` is a required test in version 2, and the reason
`DynamicQueueSorter` must rebuild the heap on every pass including a cache hit
(`BUILD_PROMPT.md` Part 4.3.7 step 3).

## 4. Differences found in T0.1

### 4.1 `comparison.json` is stale, and it is provable

The committed `legacy/m2-poc/experiment/results/comparison.json` disagrees with a fresh analysis of
the files sitting next to it, on every figure:

| Metric | Stored `comparison.json` | Recomputed | Difference |
| --- | --- | --- | --- |
| Makespan baseline | 327.75 | 322.07 | 5.68 s |
| Makespan plugin | 328.20 | 328.21 | 0.01 s |
| Avg wait baseline | 159.83 | 156.88 | 2.95 s |
| Avg wait plugin | 144.06 | 143.02 | 1.04 s |
| HIGH wait baseline | 276.13 | 271.50 | 4.63 s |
| HIGH wait plugin | 46.24 | 39.08 | 7.16 s |
| LOW wait baseline | 16.70 | 15.89 | 0.81 s |
| LOW wait plugin | 232.82 | 232.94 | 0.12 s |

The cause is not rounding or a different analysis version. It is visible in the timestamps:

| | `comparison.json` claims | Result file on disk |
| --- | --- | --- |
| Baseline `t0` | 1781512211965 | **1781518086378** |
| Plugin `t0` | 1781512819559 | **1781518804085** |

Both inputs were re-run roughly 98 minutes after the analysis that produced `comparison.json`, and
`analyze.py` was never run again. The dashboard has therefore been showing numbers from a pair of
runs whose raw files no longer exist. This is Milestone 2 known problem 7 exactly as described.

It also explains a detail that would otherwise look like a contradiction: `comparison.json`'s plugin
makespan of 328.20 happens to match run 4's 328.21, while its HIGH-band plugin wait of 46.24 matches
no run at all. The file is a mixture, not a snapshot.

**Consequence for version 2.** `BUILD_PROMPT.md` Part 4.8.3 makes `run` always call `analyze` at the
end and always update `results/latest.json`. A `verify.py --phase 7` check asserts that
`results/latest.json` is newer than its raw inputs, so this specific failure cannot recur silently.

### 4.2 A 31st job row in a 30-job experiment

`baseline-results.json` holds 31 job entries; the specification and the plugin runs hold 30. The
extra row is a leftover job in the baseline Jenkins home that is not in `jobs.json`.

`analyze.py` drops it silently, with `if name not in spec_by_name: continue` and no warning or
count. The arithmetic above is unaffected, but a harness that quietly discards measured data is a
harness that cannot be trusted to report what it measured. Version 2's `analyze` fails loudly on any
job present in one arm and absent in the other.

### 4.3 Formula drift between code and report

Not a difference in the data, but found while reading the same code, and the most consequential
finding of all: the Milestone 2 implementation did not compute the report's formula.

| | Report Chapter 6 / Appendix C | Milestone 2 code |
| --- | --- | --- |
| Weights | 0.5·U + 0.3·**D** + 0.2·**T** | 0.5·U + 0.3·**T** + 0.2·**D** |
| Urgency values | 1.0 / 0.6 / 0.3 | **100 / 50 / 10** |
| Score range | [0, 1.15] | [0, 100] |
| Aging | 0.05 per 5 min, capped 0.15 | **absent** |
| Dependency factor | (groupSize−1)/(maxGroupSize−1) | a soft score from the upstream job's last build ever |
| Group inheritance | group takes its members' maximum | **absent** |

Sources: `PriorityScoreCalculator.java` lines 33 to 35 for the weights,
`model/JobPriority.java` lines 9 to 11 for the urgency values.

The dependency and execution-time weights are transposed, so every score Milestone 2 ever computed
weighted the two factors the wrong way round. The published formula and the running code were
different algorithms. `AppendixCExampleTest` exists in version 2 so that this can never be true
again: it asserts the four report values from the same fixture that
`scripts/report/appendix_c.py` prints into the report.

## 5. What carries forward, and what does not

**Kept.** The 30-job workload with its bands, durations and dependency edges, ported to
`freestyle-30`. The per-pass score memo, which fixed a genuine O(n³) problem. `PriorityJobHeap`,
including its item-id tie-break, which prevented a livelock among tied scores. The result files
above, imported into the version 2 analytics as the labelled series "M2 dispatcher v1" and never
mixed into version 2 aggregates.

**Not kept.** `/scriptText`. Windows `ping` sleeps. Recreating jobs on every run, which wiped the
build history the estimator depends on. Analysis that runs separately from the run that produced its
data. Gating the queue from `QueueTaskDispatcher#canTake`, which is what limited Milestone 2 to one
dispatch per maintenance pass. The `instanceof AbstractProject` check that made Pipeline jobs
invisible to the optimizer. And the formula in section 4.3.
