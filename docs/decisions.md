# Decisions

Every decision taken while building, and every conflict found between `BUILD_PROMPT.md`, the report
in `docs/report/` and `legacy/m2-poc/`. Newest first within each phase.

Sources of truth, in priority order (`BUILD_PROMPT.md` 1.2): this file's parent specification
`BUILD_PROMPT.md`, then the report, then the legacy code. When sources conflict the higher one wins,
the conflict is recorded here, and any needed report change goes in `docs/report-updates.md`.

---

## Phase 2

### D-014 A Pipeline job passes through the queue twice, not once
**Date:** 2026-09-28 · **Status:** measured, task T2.1 · **Evidence:** `QueueShapeProbeIT`

`BUILD_PROMPT.md` 4.3.3 says a Pipeline job "enters the queue as a placeholder task rather than as
the job". That is true of a `node` block but it is not the whole picture, and the missing half
produced a test that failed for the wrong reason before it was found.

Measured with a diagnostic test that prints the real queue shape in three scenarios (controller with
zero executors, an offline labelled agent, a busy labelled agent). In every case:

```
item state=BuildableItem  isJob=false  flyweight=false
  hop 0: ExecutorStepExecution$PlaceholderTask
  hop 1: org.jenkinsci.plugins.workflow.job.WorkflowJob   <-- IS A Job
```

So the specification's core claim holds: the job is exactly **one** `getOwnerTask()` hop away, and
`JobResolver`'s five-hop walk is comfortably sufficient.

**What the specification omits.** A Pipeline job appears in the queue in two shapes, at different
times:

1. First as the `WorkflowJob` itself, a **flyweight task** waiting to start the run. Here
   `item.task instanceof Job` is **true**.
2. Then, once the script reaches a `node` block, as a `PlaceholderTask`. Here it is **false**.

The window for shape 1 is short but real. Both of `JobResolver`'s branches are therefore load
bearing, and neither is dead code.

**Consequences.**

- A test that waits for "N buildable items" can sample during shape 1 and measure the wrong thing.
  `QueueTestSupport.waitUntilNodeBlocksBuildable` waits on the item *shape*, not the count.
- The sorter will see flyweight items among its buildable items. Ordering them is harmless but
  meaningless, because a flyweight task runs on a one-off executor and never competes for an
  executor slot. T2.9 should not treat them as scheduling decisions.
- `QueueShapeProbeIT` stays in the suite. When a future Jenkins baseline changes queue behaviour,
  its output is what will explain what moved.

### D-017 JCasC silently ignores the optimizer's floating-point fields
**Date:** 2026-09-29 · **Status:** open defect, worked around · **Evidence:** `ConfigAsCodeIT`

On `configuration-as-code:2121.v86fe99d4b_b_a_b_` with Jenkins 2.568.3, importing a YAML file into
`OptimizerConfiguration` applies every `int`, `boolean`, `String` and `Secret` attribute and
silently ignores every floating-point one. No warning is logged and the import reports success, so
the instance keeps its defaults while the file says otherwise.

Affected: `weightUrgency`, `weightDependency`, `weightExecutionTime`, `agingBonusPerInterval`,
`agingCap`, `similarityThreshold`, `recencyLambdaPerDay`. Unaffected: `optimizerEnabled`,
`agingIntervalMinutes`, `estimatorK`, `historyWindow`, `rescoreIntervalSeconds`, `metricsEnabled`,
`metricsBackendUrl`, `metricsToken`.

**Ruled out**, each with a verified compile: the YAML scalar form (quoted and unquoted behave
identically); integer-valued floats such as `weightUrgency: 2`; the `doCheck*` form validators
(renaming them away changes nothing); boxing the field, getter and setter as `Double`; and the JVM
locale, which is en/US. Attribute discovery is correct — JCasC reports all fifteen attributes with
their proper types, including `weightUrgency : double`. Only the import silently fails. The root
cause inside JCasC was not identified within a proportionate time budget.

**A note on how this was investigated,** because it cost more than it should have. Three
intermediate experiments were run with the Maven compile output suppressed, and a broken diagnostic
in the test file meant they never compiled; each one re-ran the previously compiled classes and
produced identical output, which read as "the fix had no effect" rather than "the fix was never
built". Compile output is not noise when the next step depends on it.

**Decision: keep the specified `double` fields and pin the defect with a test.**
`ConfigAsCodeIT.floatingPointAttributesAreNotAppliedKnownDefect` asserts the current, wrong
behaviour, with a comment saying so. It fails the moment JCasC starts applying these values, which
turns a silent limitation into a loud prompt to delete it. Changing the field types to `String` to
work around it would corrupt the global configuration form and the report's Appendix D.

**Impact, and why the project is not blocked.** `optimizerEnabled` applies, so the main
baseline-versus-optimized comparison — the one Table 12.1 reports — is fully reproducible from
`jenkins/casc/experiment-baseline.yaml` and `experiment-plugin.yaml`. The aging-ablation arm of the
Part 4.8.2 matrix varies `agingBonusPerInterval` and `agingCap`, so it cannot be driven from JCasC
until this is resolved and must be configured another way. Tracked under Needs human in
`PROGRESS.md`.

### D-016 The similarity threshold filters weakly on a homogeneous controller
**Date:** 2026-09-29 · **Status:** measured, task T2.13 · **Evidence:** `SimilarityEstimatorTest`

Found while writing the estimator's tests, from an assertion that turned out to be wrong about the
implementation the specification asks for.

`BUILD_PROMPT.md` 4.3.5 fixes the similarity formula:

```
sim = 0.5 * jaccard(nameTokens) + 0.3 * jaccard(params) + 0.2 * (labels equal ? 1 : 0)
```

Two builds that both take **no parameters** have identical, empty parameter sets. Jaccard of two
empty sets is 1.0 — the only sensible reading, since "neither build takes parameters" is a genuine
match rather than missing information, and the alternative would score a job 0 on that term against
its own history. So the parameter term contributes its full 0.3, a shared agent label adds 0.2, and
**any two unparameterised builds on the same label score 0.5 before their names are compared at
all**, comfortably clearing the 0.35 threshold.

**Consequences.**

- On a homogeneous controller — every job unparameterised, one agent label — the threshold excludes
  almost nothing. Name similarity becomes a ranking weight rather than a filter.
- That description is exactly the experiment's workload: `freestyle-30` is 30 unparameterised sleep
  jobs on one `linux` label. So in the experiment, every historical build is a candidate for every
  estimate.
- The report's cold-start claim is narrower than it reads. Report section 6.5.1 says a job with
  nothing similar returns UNKNOWN and takes the neutral factor; reaching that path requires the
  history to differ in **agent label** as well as name, because a label mismatch is what brings the
  total to 0.3 and under the threshold.

**Decision: keep the formula exactly as specified.** It is stated in the higher source of truth
(`BUILD_PROMPT.md` 4.3.5) and in report Algorithm 6.4, and rule 1.2 says the higher source wins.
Renormalising the weights over only the comparable features would be more principled — an
unparameterised pair would then score 0.2/0.7 = 0.286 and be excluded — but it is a different
algorithm from the published one, and silently substituting it is precisely the Milestone 2 failure
this project exists to correct.

**Why it is tolerable rather than harmful.** The weak filtering costs accuracy only if weak
candidates distort the estimate, and they do not dominate: an exact name match scores 1.0 against a
weak candidate's 0.5, and the top-k selection prefers it, so the weighted mean stays anchored to the
closest builds. `SimilarityEstimatorTest.closerMatchesDominate` asserts that.

**Report change.** Section 6.5.1's cold-start description should state the condition under which
UNKNOWN actually occurs, and Chapter 6 should note that on a single-label, unparameterised workload
the threshold is not doing the filtering the prose implies. Tracked in `docs/report-updates.md`.

### D-015 Ordering is measured by dispatch order, never by run start time
**Date:** 2026-09-28 · **Status:** decided, task T2.1

The first version of the Phase 2 integration tests compared `Run#getStartTimeInMillis()`. That is
valid for freestyle jobs and **invalid for Pipeline**, which made one test pass for no reason and
would have made another fail permanently however correct the sorter became.

A Pipeline run starts as a flyweight task the instant it is scheduled, well before its `node` block
reaches the front of the queue. Its start time therefore records when the script began executing,
which no scheduling decision influences. Ranking two Pipeline jobs by start time measures the order
they were submitted in.

**Decision.** `DispatchRecorder`, a `QueueListener` watching `onLeft`, is the single ground truth for
every ordering assertion. It records the order in which items leave the queue onto an executor,
which is precisely what the sorter controls, and it works identically for freestyle tasks and
Pipeline placeholders.

It ignores two kinds of event: cancelled items, which left without being dispatched, and flyweight
tasks. Including flyweight tasks recorded the order `[pl-low, pl-high, pl-high, pl-low]` for two
Pipeline jobs, where the first two entries are just the submission order. Filtering them yields
`[pl-low, pl-high]`, the actual node-block dispatch order, which is the thing under test.

**Why this is worth a decision entry.** An ordering test that passes by accident is worse than no
test, because it will be trusted. Milestone 2 had no dispatcher test at all; a scheduling test that
measures the wrong clock would have been no better.

---

## Phase 0

### D-001 Build order: Phase 2 before Phase 1
**Date:** 2026-09-28 · **Status:** approved by the user

Docker is not installed on the build machine, which blocks all of Phase 1 and every acceptance check
from Phase 3 onward. JDK 21.0.11 and Maven 3.9.16 are present, and every Phase 2 test except T2.14
runs on `JenkinsRule`, which needs no Docker.

**Decision.** Run Phase 0, then Phase 2, then Phase 1, then Phases 3 to 8. T2.14 — build the `.hpi`
and install it on `jenkins-dev` — defers into Phase 1, where the container exists.

**Why.** It keeps the critical path moving while the blocker is resolved, and it front-loads the six
riskiest assumptions in the design (see D-002), which are all plugin assumptions. Discovering that
Pipeline placeholder tasks behave differently than assumed is far cheaper in week 2 than in week 6.

### D-002 The six assumptions proven before anything is built on them
**Date:** 2026-09-28 · **Status:** in progress

`BUILD_PROMPT.md` T2.1 requires `PipelinePriorityIT` and `MultiExecutorIT` as failing tests first.
Four more assumptions are equally load-bearing, so all six are written as failing tests before the
production code they justify.

1. `QueueSorter` is consulted for Pipeline placeholder tasks and `getOwnerTask()` resolves the job.
2. Three idle executors consume the top three sorted items in one maintenance cycle.
3. Jenkins consults only the first registered `QueueSorter`.
4. `@Symbol` on a `JobProperty` descriptor enables both the `options { }` and `properties([ ])` forms.
5. Re-scoring every cycle never degrades to arrival order while a queue drains.
6. Milestone 2 `config.xml` still loads after the property field rename (D-005).

**Why.** Assumptions 1 and 2 are the two Milestone 2 defects that made the plugin ineffective
(Part 2.2 problems 1 and 2), and assumption 5 is the defect that silently faked its results
(problem 6, with the run-3 evidence in `docs/m2-baseline.md`). None of them had a test in Milestone 2.

### D-003 Jenkins LTS pinned to 2.568.3
**Date:** 2026-09-28 · **Status:** approved by the user

**Conflict.** Report Appendix E states Jenkins LTS 2.541.x. Milestone 2 built against 2.479.3. The
current LTS at the time of this decision is 2.568.3, released 11 September 2026 and tested on JDK 21
and 25. Release 2.580.1 was scheduled for 30 September 2026 and was not yet published.

**Decision.** Pin 2.568.3. Rule 1.4 forbids pinning a version without checking its official source,
so this was checked against jenkins.io rather than assumed. The local JDK 21.0.11 matches a tested
configuration. 2.580.1 was rejected because an unreleased baseline cannot be verified against the
plugin BOM, and 2.541.3 was rejected because it is an older LTS chosen only because it was already
in the local Maven cache.

**Report change.** Appendix E must state 2.568.3. Tracked in `docs/report-updates.md`.

### D-004 `AppendixCExampleTest` asserts both the base and the effective score
**Date:** 2026-09-28 · **Status:** decided

**Conflict.** Report Appendix C (Table 13.2) gives `integration-tests-api` a score of **0.633**.
`BUILD_PROMPT.md` Part 4.3.10 requires the test to assert **0.650**.

**Resolution: neither is wrong.** The report's table prints the score before group inheritance, and
its prose then applies inheritance: "Group G1 takes the maximum score of its members, 0.650." Part
4.3.6 states the same rule as `score = max(score, best score in the group)`. All four rows were
verified arithmetically against the report's own inputs (estMin 2.0, estMax 8.0, maxGroupSize 2):

| Job | U | D | T | base | effective |
| --- | --- | --- | --- | --- | --- |
| `deploy-payment-service` | 1.0 | 0 | 0.833 | 0.667 | 0.667 |
| `build-api` | 0.3 | 1.0 | 1.000 | 0.650 | 0.650 |
| `integration-tests-api` | 0.6 | 1.0 | 0.167 | **0.633** | **0.650** |
| `build-frontend` | 0.6 | 0 | 0.000 | 0.300 | 0.300 |

**Decision.** `AppendixCExampleTest` asserts both columns, and `scripts/report/appendix_c.py` prints
both. A single-column table is what allowed the ambiguity in the first place, so the generated
Appendix C removes it.

### D-005 The job property field is renamed from `priority` to `level`
**Date:** 2026-09-28 · **Status:** decided

**Conflict, internal to `BUILD_PROMPT.md`.** Part 4.3.2 says `JobPriorityProperty` holds `level`, and
both published Jenkinsfile forms need `level:`:

```groovy
options { dynamicQueuePriority(level: 'HIGH', dependsOn: 'build-api') }
```

The same paragraph also says to "keep the Milestone 2 field names in the Jelly form so old job
configurations still load". But Milestone 2's field is `priority`, in
`legacy/m2-poc/dynamic-queue-optimizer/src/main/java/.../property/JobPriorityProperty.java` and in
its `config.jelly` (`field="priority"`). Both instructions cannot hold at once. Report Appendix D
also publishes `level:`.

**Decision.** The data-bound field is `level`, because the `@Symbol` form requires it and that form
is published in two sources of truth. Backward compatibility is kept by mechanism instead of by
name: an XStream field alias maps the old `priority` element to `level`, and a deprecated
`getPriority()` remains. A back-compat test loads a Milestone 2 `config.xml` and asserts the level
survives.

**Why not keep `priority` and alias `level`?** Because `@Symbol` derives the Groovy parameter name
from the data-bound constructor parameter, so the published `level:` syntax would not work.

### D-006 `metricsBackendUrl` defaults to empty
**Date:** 2026-09-28 · **Status:** decided

**Conflict.** Report Appendix D defaults it to `http://backend:8000/api/metrics`. Part 4.3.1 defaults
it empty.

**Decision.** Empty, per the higher source. A fresh install must not post to a host that may not
exist, and metrics stay off until deliberately configured. `jenkins/casc/dev.yaml` sets the real URL,
so the working stack is unaffected.

### D-007 The frozen copy excludes runtime output and key material
**Date:** 2026-09-28 · **Status:** decided

`BUILD_PROMPT.md` human step 1 says to copy the Milestone 2 folder in "unchanged", but the folder is
328 MB, of which 316 MB is regenerable runtime output and some is credential material.

**Decision.** `legacy/m2-poc/` is committed at 2 MB. Excluded: `dynamic-queue-optimizer/target/`
(105 MB of build output including an exploded Jetty webapp), `experiment/*-home/war/` (105 MB each,
the exploded Jenkins WAR), `*-home/updates/` (update-center cache), and every Jenkins credential
store (`secret.key*`, `secrets/`). Also excluded is `dynamic-queue-optimizer/work/`, the
`mvn hpi:run` scratch home.

Kept: all sources, `pom.xml`, the Jelly forms, the experiment scripts, the dashboard, the run logs,
every result file, and the build history under `*-home/jobs/`. The result files are the evidence
behind the staleness finding (D-008) and the build history is the evidence behind the M2 numbers.

Excluding the credential stores is not a judgement call — rule 1.5 forbids committing secrets, and
that rule does not have a frozen-directory exemption.

`.gitattributes` pins `legacy/** -text` so the copy is stored byte for byte. Without it, the
repository-wide `text=auto eol=lf` rule would rewrite line endings in files that rule 1.5 forbids
modifying, and would make the working copy differ from the `m2-final` tag that
`verify.py --phase 0` checks it against.

### D-008 The Milestone 2 `comparison.json` is stale and must not be cited
**Date:** 2026-09-28 · **Status:** decided, evidence in `docs/m2-baseline.md`

**Finding, task T0.1.** `legacy/m2-poc/experiment/results/comparison.json` disagrees with a fresh
analysis of the files beside it on every figure. The cause is in the timestamps: the file cites
`baselineT0 = 1781512211965` and `pluginT0 = 1781512819559`, while the result files on disk carry
`t0 = 1781518086378` and `t0 = 1781518804085`. Both inputs were re-run about 98 minutes after the
analysis that produced `comparison.json`, and `analyze.py` was never run again. Milestone 2 known
problem 7, caught on the record.

**Decision.** The report cites the recomputed figures, which reproduce `BUILD_PROMPT.md` Part 2.2
exactly from `plugin-results-run4.json`. The stored `comparison.json` is kept as a frozen artifact
but is never a source for any number. Version 2 prevents a recurrence structurally: `run` always
calls `analyze` (Part 4.8.3), and a Phase 7 check asserts `results/latest.json` is newer than its raw
inputs.

### D-009 Milestone 2 run 3 is retained as evidence, not discarded as noise
**Date:** 2026-09-28 · **Status:** decided

`plugin-results-run3.json` shows a HIGH-band wait of 353.34 s against a FIFO baseline of 271.50 s,
with a LOW-band wait of 28.12 s against a baseline of 15.89 s. The plugin performed worse than the
thing it was meant to beat, on the exact metric it targeted, in a profile matching arrival order.

**Decision.** It is written up in `docs/m2-baseline.md` as evidence of Milestone 2 known problem 6 —
the change that skipped heap repopulation and silently degraded the dispatcher to FIFO — rather than
dropped as an outlier. It is the only surviving trace that the defect occurred, because the plugin
had no test that would have caught it. `CacheEvictionRegressionIT` is that test in version 2.

**Why this matters beyond bookkeeping.** Dropping the run that disagrees is how a project ends up
publishing a formula it does not implement. Rule 1.3 forbids presenting results dishonestly, and
silently excluding an inconvenient measurement is exactly that.

### D-010 The backend targets a `uv`-managed Python 3.12
**Date:** 2026-09-28 · **Status:** decided

The system interpreter is Python 3.14.2; report Appendix E states 3.12.

**Decision.** `uv` manages a pinned 3.12 interpreter for `backend/`. Python 3.14 is new enough that
some dependencies may not ship wheels for it, and the report's stated version should hold rather than
drift to whatever the build machine happens to have. `uv` itself is installed project-locally when
Phase 3 starts, since rule 1.5 permits project-local dependencies but not system-wide software.

### D-011 Dependencies are not modelled as two database tables
**Date:** 2026-09-28 · **Status:** decided

**Conflict.** Report section 5.14 describes a twelve-table schema including `job_dependencies` and
`dependency_groups`, and lacking `services`, `conversations`, `messages` and `llm_calls`.
Part 4.4.3 supersedes it.

**Decision.** Follow Part 4.4.3. Declared dependencies live on `jobs.depends_on`, and grouping is a
runtime property computed by the plugin per queue cycle and exposed through
`GET /dynamic-queue/api/json`, not persisted state. Persisting a derived grouping would let the
database disagree with the scheduler, which is the same class of bug as D-008.

**Report change.** Tracked in `docs/report-updates.md`.

### D-012 Report Appendix B's experiment protocol is superseded
**Date:** 2026-09-28 · **Status:** decided

**Conflict.** Report Appendix B and Part 4.8 disagree on nearly every parameter. The legacy workload
file settles each point it can speak to:

| Axis | Report Appendix B | Part 4.8 | `legacy/.../jobs.json` |
| --- | --- | --- | --- |
| Jobs | 25 | 30 | **30** |
| Bands | 8 / 9 / 8 | 9 / 15 / 6 | **9 / 15 / 6** |
| Executors | 2, on one agent | 1 and 3 | — |
| Durations | 30 s to 4 min | sleeps | **4 to 25 s** |
| Aggregation | median of 3 pairs | mean and standard deviation of 3 | — |

**Decision.** Follow Part 4.8. Appendix B needs a full rewrite, tracked in
`docs/report-updates.md`.

### D-013 Report section 12.1.3 overclaims what Milestone 2 delivered
**Date:** 2026-09-28 · **Status:** decided

**Conflict.** Report section 12.1.3 states that the team "built the metrics pipeline that records
every scheduling decision and build outcome into PostgreSQL through a FastAPI backend, and the React
analytical dashboard". Part 2.2 states that no chatbot, backend, database or React app exists, and
`legacy/m2-poc/` contains one static HTML file reading a JSON file.

**Decision.** The report must be corrected. This is the highest-priority item in
`docs/report-updates.md`, because unlike a stale version number it is a claim about delivered work.
Version 2 does build all three, so the correction is to state when.
