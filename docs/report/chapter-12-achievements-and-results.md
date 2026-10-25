# Chapter 12: Achievements and Results

<!-- The tables in this chapter are generated, never typed (BUILD_PROMPT Part 6). Each sits between
     a pair of chapter_12.py markers, and `python scripts/report/chapter_12.py` rewrites them from
     the archived run files; `--check` fails if any is stale. Edit the prose freely; edit a table
     only by changing its data or the generator. -->

## 12.1 Overview

This chapter records what the team achieved across the project's three milestones and reports the
results of the two evaluations the final milestone ran:

- **the controlled experiment** on real Jenkins controllers, which compares the Dynamic Queue
  Optimization plugin with its own observe-only control;
- **the chatbot evaluation**, which measures how well the two assistants turn a plain-English
  request into the right intent and the right response.

Milestones 1 and 2 are summarised for completeness (Sections 12.2 and 12.3). The record of Milestone
2 is corrected where the earlier version of this chapter claimed more than was delivered. Section
12.4 lists what the final milestone built. Sections 12.5 and 12.6 give the results, Section 12.7
reads them against the project's objectives, and Section 12.8 states their limits.

Every figure in Sections 12.5 and 12.6 comes from a file in the repository, recomputed by the
script named under its table, and every run behind it is archived with a checksum. Three
repetitions of a condition is a small sample. A difference smaller than about two standard
deviations is therefore not treated as established.

## 12.2 Achievements of Milestone 1

- We completed and submitted Chapters 1 to 4 of this report:
  - the introduction;
  - a literature review of 21 referenced sources covering LLM-driven CI/CD automation and queue
    optimization;
  - the aim and statement of the problem;
  - the hardware and software analysis, with justified technology choices.
- We produced:
  - the initial system diagram;
  - the activity diagram with swimlanes, covering the full flow from a natural-language command to
    a monitored execution;
  - the actor use-case diagram, with twelve use cases.
- We presented a non-working prototype and defended the project's scope before the FYP committee.
  The committee then assigned the Dynamic Queue Optimization module to us as the Proof of Concept
  for Milestone 2.

## 12.3 Achievements of Milestone 2

### 12.3.1 Design and modelling

- We adopted the Layered Architecture described by Richards and restructured our class designs to
  follow its four class types (Chapter 5).
- We revised the use-case model from twelve use cases to eight that reflect the assigned Proof of
  Concept. For each use case we produced:
  - a class diagram conforming to the architecture;
  - an interface design;
  - a sequence diagram whose objects match the class diagram;
  - an object diagram, with an ERD wherever the use case touches PostgreSQL.

### 12.3.2 Algorithms

- We designed, wrote pseudocode for and analysed the four algorithms of the Proof of Concept:
  - weighted priority scoring;
  - max-heap scheduling;
  - union-find dependency grouping with topological ordering;
  - recency-weighted top-k similarity estimation.
- We justified each against named alternatives, with best, average and worst-case time and space
  complexities (Chapter 6).

### 12.3.3 Proof of Concept implementation

- We built a Jenkins plugin with the official Maven archetype. It intercepted the build queue
  through the `QueueTaskDispatcher` extension point and implemented:
  - a job property holding a High, Medium or Low priority and the job's dependencies;
  - dependency checking and grouping;
  - execution-time estimation from build history;
  - a weighted score;
  - heap-ordered dispatch.
- We ran an experiment of **30 jobs** (9 HIGH, 15 MEDIUM, 6 LOW) with 20 dependency edges, once
  under default Jenkins scheduling and once with the plugin, on one executor.
- **What Milestone 2 did not deliver, contrary to this chapter's earlier version.**
  - It had no metrics pipeline into PostgreSQL through a FastAPI backend, and no React dashboard.
    The deliverable was a single static HTML page reading one JSON file (`docs/decisions.md`
    D-013). Both were built in the final milestone (Section 12.4).
  - The experiment had 30 jobs, not 25, and its dependencies were 20 edges on 17 jobs, not "three
    dependency chains".

Re-examined in the final milestone, Milestone 2's plugin had three faults, and the version 2
experiment was designed to avoid each (Section 12.5.9):

1. **The formula.** It computed `0.5·urgency + 0.3·executionTime + 0.2·dependency`, transposing
   the published weights, on a 0 to 100 urgency scale and with no aging (D-008).
2. **Executors.** Ordering and gating were one `canTake` decision, so it filled only one executor
   per maintenance pass.
3. **Dependencies.** Its dependency factor was a score, not a hold. The run the report quoted
   started jobs before their upstream had finished on 19 of the workload's 20 edges.

### 12.3.4 Skills and process

- **Technically,** we learned Jenkins plugin development in Java (extension points, job properties,
  global configuration, listeners), the Jenkins build and queue APIs, practical complexity analysis,
  and full-stack integration between a Java plugin, a Python backend and a React frontend.
- **As a team,** we worked in a shared Git repository with feature branches and reviewed merges. A
  single naming registry kept the report, diagrams and code consistent. We held weekly progress
  meetings with our supervisor, Engr. Laiba Mughal, whose feedback shaped the revised use-case
  model.

## 12.4 Achievements of the final milestone

The final milestone rebuilt the Proof of Concept as version 2 and delivered the rest of the system
the report designs. The work ran in eight phases, each ending in an automated acceptance gate
(`scripts/verify.py`). The gate now has 107 checks across Phases 0 to 8.

| Component | What was built | Where it is verified |
| --- | --- | --- |
| Plugin v2 | `DynamicQueueSorter` (a `QueueSorter`) orders every buildable item by the report's formula, `0.5·U + 0.3·D + 0.2·T` plus aging, rebuilding its heap on every pass, so every idle executor is filled in priority order. `DependencyGate` (a `QueueTaskDispatcher`) only gates, and holds a job while an upstream is queued or building. It covers freestyle, Maven and Pipeline jobs, the last through `getOwnerTask()` and, since D-080, by holding a Pipeline's first node block. | Chapter 8; `AppendixCExampleTest` guards the formula against Appendix C |
| Two assistants | A Freestyle Assistant that builds chains of freestyle jobs, and a Pipeline Assistant that writes a declarative Jenkinsfile. They share one AI core: a guard, a model chain (`gpt-oss-120b`, then `gpt-oss-20b`, then a rule parser), a validator and a clarifier that decide in code, a role-based policy that refuses production, and a planner that chooses stages but never writes a shell command. | Chapter 8; Section 12.6 |
| Backend | FastAPI with PostgreSQL: authentication and roles, the conversation and generation flow, approval with idempotency and per-service locks, run tracking over WebSocket, Explain failure from real logs, and the plugin's metrics. | Chapter 8 |
| Frontend | React pages for the Overview, both assistants, the queue with the score bar, jobs and runs, analytics, the service catalog and administration. Lighthouse scores 100 for accessibility on the assistant pages. | Chapter 8 |
| Experiment v2 | A harness using only Jenkins' REST API and the plugin's endpoints, with no script console. It ran the full matrix on real controllers (Section 12.5). | `experiment/` tests; `docs/experiment/` |
| Evaluation | A 250-item dataset and a harness that scores any parser through the same pipeline, with comparisons, ablations, plan validity and an end-to-end sample (Section 12.6). | `eval/` tests; `docs/evaluation/` |
| Report and demo tooling | Generators for Appendix C, Appendix E and this chapter's tables, so the report cannot drift from the code. A demo reset that restores `jenkins-dev` and the database to a snapshot, and a scripted demo that replays the model's answers offline. | Phase 8's gate checks |

## 12.5 The controlled experiment

### 12.5.1 Method

The experiment compares arms that differ in one thing (Part 4.8):

- **observe-only (the baseline):** the plugin installed and recording, ordering nothing;
- **optimized:** the plugin ordering the queue, as the report's algorithm specifies;
- **aging-off:** optimized with the aging bonus set to zero, for the aging ablation;
- **stock:** Jenkins without the plugin at all, for the sanity run.

Each arm ran on its own controller, built from the same image, with one Linux agent and a home of
its own, so no arm saw another's build history.

| Parameter | Value |
| --- | --- |
| Jenkins | 2.568.3 LTS on JDK 21 |
| Plugin | build `cd6b1e3` for the matrix; build `c01e744` for the re-run after DF-48's fix |
| Workloads | `freestyle-30`: Milestone 2's 30 jobs, 9 HIGH, 15 MEDIUM and 6 LOW, durations 4 to 25 s, 20 dependency edges. `pipeline-30`: the same as Pipeline jobs. `mixed-30`: 15 of each. |
| Order | LOW, then MEDIUM, then HIGH: the arrival order that is worst for first-come-first-served. Two seeded shuffles in the random-order group. |
| Executors | 1 and 3 |
| History | warm: three warm-up passes before measuring. Fresh in the cold-start group. |
| Repetitions | 3 per condition and arm; 1 per seed in random order, and 1 for the sanity run |
| Runs | 53 in the matrix, on 2026-10-24 from 03:46 to 08:16, on mains power; 10 in the re-run, from 13:36 to 14:11 |

The KPIs are report Appendix F's, plus version 2's:

- **Appendix F:** queue waiting time, completion time, makespan, throughput, executor utilisation,
  and scheduling efficiency, `(baseline - optimized) / baseline × 100`.
- **Version 2:**
  - dependency violations: a downstream whose work started before its upstream finished;
  - the longest LOW wait;
  - the scheduler's overhead per cycle;
  - for Pipelines, the first node block's wait.

The raw files are in `docs/experiment/matrix-2026-10-24/` and
`docs/experiment/gate-fix-rerun-2026-10-24/`, with `SHA256SUMS`.

### 12.5.2 Table 12.1: the report's experiment, repeated on version 2

Table 12.1 is the condition Milestone 2 measured and this table was designed for: `freestyle-30`
on one executor, from a warm history.

**Table 12.1: Baseline versus optimized on `freestyle-30`, one executor (generated by
`scripts/report/chapter_12.py` from the matrix's run files)**

<!-- chapter_12.py: table-12-1 -->
| KPI | Baseline (observe-only) | Optimized (our plugin) | Change (%) |
| --- | ---: | ---: | ---: |
| Average queue waiting time (s) | 153.3 ± 0.0 | 150.2 ± 0.5 | +2.0% |
| Maximum queue waiting time (s) | 307.7 ± 0.0 | 291.6 ± 0.1 | +5.2% |
| Average build completion time (s) | 163.8 ± 0.0 | 160.7 ± 0.5 | +1.9% |
| Average waiting time of High priority jobs (s) | 265.3 ± 0.0 | 176.0 ± 4.3 | +33.7% |
| Average waiting time of Medium priority jobs (s) | 141.2 ± 0.0 | 105.1 ± 1.7 | +25.6% |
| Average waiting time of Low priority jobs (s) | 15.3 ± 0.0 | 224.3 ± 0.3 | -1363.7% |
| Longest wait of a Low priority job (s) | 41.0 ± 0.0 | 291.6 ± 0.1 | -611.8% |
| Makespan (s) | 316.8 ± 0.0 | 316.9 ± 0.1 | -0.1% |
| Throughput (jobs per hour) | 341.0 ± 0.0 | 340.7 ± 0.1 | +0.1% |
| Average executor utilization (%) | 99.7 ± 0.0 | 99.6 ± 0.0 | +0.1% |
| Dependency violations | 1.0 ± 0.0 | 0.0 ± 0.0 | +100.0% |
| Scheduler overhead per cycle, median (ms) | not applicable | 3.58 ± 0.79 | |

Mean ± standard deviation over 3 repetitions of each arm. Change is report Appendix F's (baseline - optimized) / baseline x 100: positive when the optimized arm's figure is lower, which is better for waits and makespan and worse for throughput and utilization.
<!-- /chapter_12.py -->

**The HIGH band improves by about a third.** HIGH-priority jobs waited 33.7% less, and MEDIUM jobs
25.6% less. That is what the plugin is for: urgent work no longer queues behind work that merely
arrived first.

**The mean wait barely moves, and makespan does not move at all.** On one executor that is always
busy, the total work is fixed, so the order cannot finish it sooner. What changes is *who* waits.
The six LOW jobs, first to arrive and so first to run under the baseline, wait 224 s instead of
15 s. The longest of them waits 292 s.

**Priority scheduling redistributes waiting; it does not remove it.** The report should say so
plainly, because it is the honest shape of the result. The six LOW jobs paid for the gains of the
other 24.

**Dependencies:**
- The baseline let one downstream start before its upstream had finished, because observe-only
  does not gate.
- The optimized arm let none.
- The scheduler's own cost was a median of 3.6 ms a cycle.

### 12.5.3 Across the workloads and executor counts

**Table 12.2: Scheduling efficiency in every condition (generated by
`scripts/report/chapter_12.py`)**

<!-- chapter_12.py: table-12-2 -->
| Condition | n | Mean wait, observe-only / optimized (s) | Change | HIGH wait change | LOW wait, observe-only / optimized (s) | Makespan change | Violations, observe-only / optimized |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main: freestyle-30 1x | 3 | 153.3 / 150.2 | +2.0% | +33.7% | 15.3 / 224.3 | -0.1% | 1.00 / 0.00 |
| main: freestyle-30 3x | 3 | 46.9 / 43.7 | +6.8% | +28.0% | 2.5 / 43.9 | -3.0% | 3.00 / 0.00 |
| main: mixed-30 1x | 3 | 159.2 / 156.5 | +1.6% | +29.5% | 22.6 / 237.0 | +0.2% | 2.00 / 0.00 |
| main: mixed-30 3x | 3 | 47.9 / 45.9 | +4.2% | +23.5% | 3.6 / 46.7 | -9.6% | 3.00 / 0.00 |
| main: pipeline-30 1x | 3 | 167.6 / 163.2 | +2.6% | +31.3% | 18.2 / 248.7 | -0.3% | 2.00 / 0.00 |
| main: pipeline-30 3x | 3 | 53.0 / 47.9 | +9.7% | +17.0% | 18.1 / 64.0 | -3.9% | 5.33 / 1.00 |
| cold-start: freestyle-30 1x | 3 | 153.2 / 149.9 | +2.1% | +32.9% | 15.4 / 224.2 | -0.0% | 1.00 / 0.00 |
| random-order: mixed-30 3x seed 1 | 1 | 47.0 / 48.0 | -2.3% | -4.9% | 54.0 / 87.3 | -7.4% | 14.00 / 5.00 |
| random-order: mixed-30 3x seed 2 | 1 | 47.1 / 45.7 | +2.9% | +2.4% | 44.3 / 60.0 | -7.6% | 10.00 / 2.00 |

Means over the repetitions (3 for main and cold start, 1 per seed for random order). Change is Appendix F's scheduling efficiency, positive when the optimized arm did better. The violations are the matrix's, on plugin build `cd6b1e3`; Table 12.4 has the re-run after DF-48's fix.
<!-- /chapter_12.py -->

**The HIGH band improves in every condition with the fixed order,** by 17% to 34%. The mean wait
improves by 1.6% to 9.7%. The gain is largest on three executors, where the order decides which
three jobs share the machine.

**On three executors, makespan worsens by 3% to 10%,** and executor utilisation falls with it. On
`mixed-30`, utilisation fell from 98.5% to 90.0%. The reason is the dependency gate. The baseline
starts a downstream as soon as an executor is free, whether or not its upstream has finished; the
optimized arm holds it, and an executor waits while it does. The baseline's shorter makespan is
partly bought with its 3 to 5 dependency violations per run. The optimized arm keeps the
dependency order and pays for it in idle time.

**In random order the mean wait barely changes** (-2.3% and +2.9%). When arrivals are already
mixed, there is little for priority ordering to correct.

**Pipelines.** A Pipeline run leaves the queue in milliseconds, so its real wait is its first node
block's (D-015):

**Table 12.3: The first node block's wait, Pipeline and mixed workloads (generated by
`scripts/report/chapter_12.py`)**

<!-- chapter_12.py: table-12-3 -->
| Condition | n | First node-block wait, observe-only (s) | Optimized (s) | Change |
| --- | ---: | ---: | ---: | ---: |
| mixed-30 1x | 3 | 179.6 ± 8.6 | 107.7 ± 0.6 | +40.0% |
| mixed-30 3x | 3 | 52.7 ± 0.1 | 27.2 ± 4.9 | +48.3% |
| pipeline-30 1x | 3 | 167.3 ± 3.8 | 103.2 ± 2.1 | +38.3% |
| pipeline-30 3x | 3 | 51.8 ± 2.4 | 23.8 ± 5.0 | +54.0% |

A Pipeline's wait is its first node block's: the run itself leaves the queue within milliseconds (D-015). Every Pipeline in these workloads has one node block, so the sum of all node-block waits equals the first.
<!-- /chapter_12.py -->

Pipelines gain more than the mean suggests. Their node blocks waited 38% to 54% less, because the
sorter ranks a node block by its job's score, as it ranks a freestyle job (Chapter 6).

### 12.5.4 Dependency violations, and the fix the matrix led to

The matrix found one edge the plugin did not hold. On `pipeline-30` with three executors,
`release-notes-generator` ran before `smoke-test-production` had finished, in all three
repetitions.

- **The defect (DF-48):** the gate checked a Pipeline only as its run, which leaves the queue at
  once, and never checked its node blocks.
- **The fix (D-080):** the gate now holds a Pipeline's first node block until the run's work
  begins, and never a later one, so no run is stopped mid-build.
- **Its check:** a targeted re-run on real Jenkins, approved for the purpose.

**Table 12.4: Dependency violations of the optimized arm, before and after the fix (generated by
`scripts/report/chapter_12.py`)**

<!-- chapter_12.py: table-12-4 -->
| Optimized arm, 3 executors | Matrix, plugin `cd6b1e3` | Re-run, plugin `c01e744` |
| --- | ---: | ---: |
| pipeline-30, 3 executors, fixed order | 1, 1, 1 | 0, 0, 0 |
| Random order, seed 1 | 5 | 2 |
| Random order, seed 2 | 2 | 1 |

Violations per run: a downstream job starting its work before its upstream finished. On pipeline-30 the three violations were one edge, held by the fix (D-080). The three left in random order are freestyle downstreams that took an idle executor before their upstream had been queued at all, which no gate inside the queue can prevent.
<!-- /chapter_12.py -->

The fixed edge now waits for its upstream: in all three re-run repetitions it took an executor 2.8
to 2.9 s after its upstream finished. Holding it cost no makespan (-3.8% against the matrix's
-3.9%). The three violations left in random
order show a limit of any queue-side gate. Each was a freestyle downstream that took an idle
executor before its upstream had been *requested* at all, and nothing in the queue can wait for a
build nobody has asked for. The system itself never meets this case, because a freestyle chain is
triggered one job at a time, each by the one before.

### 12.5.5 The aging ablation

**Table 12.5: Aging on against aging off, `freestyle-30`, one executor (generated by
`scripts/report/chapter_12.py`)**

<!-- chapter_12.py: table-12-5 -->
| KPI | Aging on | Aging off | Difference |
| --- | ---: | ---: | ---: |
| Mean wait (s) | 149.9 ± 0.0 | 150.3 ± 0.3 | +0.3 |
| HIGH mean wait (s) | 173.5 ± 0.0 | 173.8 ± 0.3 | +0.3 |
| LOW mean wait (s) | 224.1 ± 0.0 | 224.6 ± 0.5 | +0.4 |
| Longest LOW wait (s) | 291.5 ± 0.0 | 292.0 ± 0.5 | +0.5 |
| Makespan (s) | 316.9 ± 0.1 | 317.6 ± 0.8 | +0.7 |

Mean ± standard deviation over 3 repetitions of each arm.
<!-- /chapter_12.py -->

**Turning aging off changes nothing measurable.** Every difference is under a second, within the
noise between repetitions. This was predicted before the run:

- The bonus steps every 5 minutes of waiting.
- In this 5-minute burst, no job waits 5 minutes. The longest LOW wait is 292 s.
- So the bonus is never earned.

The simulation in Chapter 8 (E3) found a stronger limit. Under sustained load, aging as specified
does not prevent starvation either, because the bonus is the same for every band and caps at the
LOW-to-MEDIUM gap. The formula is unchanged, because it is the report's. Section 12.8 lists
band-aware aging as future work.

### 12.5.6 The sanity run and the cold start

**The observe-only baseline schedules as stock Jenkins does.** The sanity run asks whether
installing the plugin, without ordering anything, changes Jenkins' scheduling. If it did, every
comparison above would measure the wrong thing.

**Table 12.6: Stock Jenkins against the observe-only arm, `freestyle-30`, one executor (generated
by `scripts/report/chapter_12.py`)**

<!-- chapter_12.py: table-12-6 -->
| KPI | Stock Jenkins (n = 1) | Observe-only (n = 3) | Difference |
| --- | ---: | ---: | ---: |
| Mean wait (s) | 153.9 | 153.3 ± 0.0 | +0.4% |
| HIGH mean wait (s) | 266.1 | 265.3 ± 0.0 | +0.3% |
| LOW mean wait (s) | 15.8 | 15.3 ± 0.0 | +3.3% |
| Makespan (s) | 317.9 | 316.8 ± 0.0 | +0.4% |
| Dependency violations | 1.0 | 1.0 ± 0.0 | -0.0% |

Difference is stock against observe-only. The stock run's waits start at the harness's trigger request, because it has no plugin to report queue entry (D-078).
<!-- /chapter_12.py -->

Stock Jenkins was within 0.4% of observe-only on the mean wait and the makespan, and broke the
same edge. The small differences are of the size its measurement predicts: with no plugin to report
when a job entered the queue, the stock run's waits start at the harness's trigger request.

**The cold start matched the warm runs** within 0.2% on the mean wait and about 1% on the HIGH
band (Table 12.2). On this workload the estimator's history barely changes the order. Every job is unparameterised and runs on one label, so the
similarity threshold filters little (D-016).

### 12.5.7 Comparison with Milestone 2

**Table 12.7: Milestone 2's runs, recomputed from its own files, beside version 2 (generated by
`scripts/report/chapter_12.py`)**

<!-- chapter_12.py: table-12-7 -->
| Series | Mean wait (s) | HIGH mean wait (s) | LOW mean wait (s) | Makespan (s) | Dependency violations |
| --- | ---: | ---: | ---: | ---: | ---: |
| M2 stock Jenkins, stock Jenkins (FIFO) | 156.9 | 271.5 | 15.9 | 322.1 | 1 |
| M2 dispatcher v1, run 1 | 140.9 | 44.9 | 228.3 | 322.4 | 10 |
| M2 dispatcher v1, run 2 | 158.9 | 51.3 | 246.3 | 344.4 | 18 |
| M2 dispatcher v1, run 3 | 212.3 | 353.3 | 28.1 | 407.5 | 1 |
| M2 dispatcher v1, run 4 (the report's) | 143.0 | 39.1 | 232.9 | 328.2 | 19 |
| v2 observe-only, mean of 3 | 153.3 | 265.3 | 15.3 | 316.8 | 1 |
| v2 optimized, mean of 3 | 150.2 | 176.0 | 224.3 | 316.9 | 0 |

Milestone 2's runs are recomputed from its own result files and labelled "M2 dispatcher v1"; they are never averaged with version 2 (Part 4.8.4). One executor, freestyle-30.
<!-- /chapter_12.py -->

Milestone 2 reported a HIGH-band wait of 39 s against stock Jenkins' 272 s, which version 2 does
not match. Version 2 gets 176 s. The difference is the dependency order:

- **The run Milestone 2 reported** started jobs before their upstream had finished on 19 of the
  workload's 20 edges. The deploy jobs ran before their builds.
- **Its other runs** broke 10 and 18 edges, and one fell back to first-come-first-served.
- **Version 2 breaks none.**

In Chapter 8's simulation of the same workload (E2), no policy that respects the dependencies
brought the HIGH band below 156 s. Version 2 is within 13% of that bound while keeping every
dependency. Milestone 2's figure should be quoted only with its violation count beside it.

## 12.6 The chatbot evaluation

### 12.6.1 The dataset, and who labelled it

The evaluation set, `eval-v1`, has 250 messages a user might type into either assistant. Each has a
gold label: the intent it should parse to, and whether the system should generate, ask or refuse.

- **No public dataset covers this task.** The nearest, DeployIntentD (Wijesinghe et al., 2025), has
  no public release, so the set was written for this system's catalog and rules.
- **Human-written text where the task allows it:**
  - eight out-of-scope requests from CLINC150 (Larson et al., 2019; CC BY 3.0), chosen because
    they share a verb with a CI/CD action ("check the status of my amazon orders");
  - seven injection attempts from deepset/prompt-injections (deepset, 2023; Apache-2.0).
- **The mix and split are Part 4.9's:**
  - by category: 100 clear, 50 paraphrase and typos, 38 missing field, 25 ambiguous, 25 unsafe or
    out of scope, and 12 prompt injections;
  - by split: 100 for development and 150 for test, each stratified by action and behaviour;
  - a 75-item ablation subset and a 20-item end-to-end sample, both from the test split.

**The gold labels were written by Claude Code, an AI assistant, and no person has reviewed them.**
Part 4.9 asks for human labels. The project owner had no dataset and no labeller, and asked for one
to be created (D-081).

**How the labels were made and checked:**
- Every label applies twelve stated rules. The dataset's datasheet (`eval/datasets/eval-v1.card.md`,
  after Gebru et al., 2021) states them.
- A builder checks each label against those rules in code that does not import the system's own
  validator or policy.
- It also refuses repeats, any copy of a few-shot example from the prompt, and near-duplicates
  across the splits. That last check found nine pairs, all reworded before any parser was run.
- The set was frozen, with its checksum in git, before the first run.

**What the figures mean.** They measure agreement with one author's labels. They are not accuracy
against human judgement, and Section 12.8 returns to this.

### 12.6.2 Method

**One pipeline for every parser.** Every parser ran through the same pipeline the backend uses:
guard, parse, validator, clarifier and policy. Only the parse step differed:

- **the rule baseline:** the system's own fallback parser;
- **`gpt-oss-120b`**, the production chain's first model;
- **`gpt-oss-20b`**, its second;
- **`qwen3.8-27b`**, the only other Groq model available to this account that supports the strict
  JSON schema.

**No model is rescued.** A model run has one model and no fallback, so a model that did not answer
is counted as an error, never scored with the rules' answer in its place. Answers were cached by
prompt hash, throttled to Groq's free-tier limits, and resumed after each daily limit.

**Plan validity** was measured on each generating item's gold intent, after the validator, so a
parse error could not count against the planner. Plan validity is the share of plans that passed
the system's own checks: first time, and after up to two repairs.

**The 20 end-to-end commands** ran through the real stack against `jenkins-dev`. Each was:
1. understood and planned;
2. generated as asked;
3. approved and run to success on the agents;
4. for a deploy, answering on staging.

### 12.6.3 Results

**Table 12.8: The parsers compared on the test split (generated by `scripts/report/chapter_12.py`
from `python -m eval report`)**

<!-- chapter_12.py: table-12-8 -->
The evaluation archive is not in `docs/evaluation/` yet; this table is generated from it.
<!-- /chapter_12.py -->

**Table 12.9: Accuracy by field and by category, on the test split (generated by
`scripts/report/chapter_12.py`)**

<!-- chapter_12.py: table-12-9 -->
The evaluation archive is not in `docs/evaluation/` yet; this table is generated from it.
<!-- /chapter_12.py -->

**Table 12.10: Plan validity before and after repair, on the test split's generating items
(generated by `scripts/report/chapter_12.py`)**

<!-- chapter_12.py: table-12-10 -->
The evaluation archive is not in `docs/evaluation/` yet; this table is generated from it.
<!-- /chapter_12.py -->

**Table 12.11: Ablations on the 75-item subset (generated by `scripts/report/chapter_12.py`)**

<!-- chapter_12.py: table-12-11 -->
The evaluation archive is not in `docs/evaluation/` yet; this table is generated from it.
<!-- /chapter_12.py -->

**Table 12.12: End-to-end success against `jenkins-dev` (generated by
`scripts/report/chapter_12.py`)**

<!-- chapter_12.py: table-12-12 -->
The evaluation archive is not in `docs/evaluation/` yet; this table is generated from it.
<!-- /chapter_12.py -->

<!-- EVALUATION-DISCUSSION -->

## 12.7 Reading the results against the objectives

<!-- OBJECTIVES -->

## 12.8 Limitations

- **Small samples.** Three repetitions per condition, and one per seed in random order and for the
  sanity run. A difference smaller than about two standard deviations is not established.
- **One controller per arm, on one machine.** The experiment measures scheduling within a
  controller; nothing here measures behaviour across controllers or at a larger scale. The laptop
  ran on mains power for every measured run, and Windows was asked not to sleep.
- **Staging only.** Deploys go to staging containers on the agents. Production is refused by
  policy, and no production behaviour was measured.
- **The Docker socket.** The local agents mount the Docker socket to build and run the sample
  services, which gives a job root-equivalent access to the host. That is acceptable on a
  single-user laptop and must not be repeated on shared infrastructure.
- **Aging.** As specified, it does not act on a five-minute burst and does not prevent starvation
  under sustained load (Section 12.5.5; Chapter 8, E3).
- **The dependency gate's limit.** It cannot hold a job whose upstream has not been requested at
  all (Section 12.5.4).
- **The evaluation's labels.** One AI author wrote and labelled the dataset, and no person has
  reviewed it (D-081). There is no inter-annotator agreement, and the author's reading of the rules
  is built into the labels. The authored messages may be more regular than real users' messages,
  and the catalog has two services. A person's review of at least the test split is the most
  valuable next step; the datasheet says how.
- **Free-tier model limits.** Groq's free tier allows about 110 intent parses a day per model at
  this prompt's size: 200,000 tokens a day, and about 1,800 tokens a parse. That shaped the evaluation: the test split only for the comparisons, and the
  ablations on one model. Quota waits are excluded from the latency figures, but a paid tier's
  latency may differ.
- **AI-assisted development.** Claude Code, an AI assistant, wrote most of the code, the tests, the
  evaluation dataset and this chapter's tables, under the team's direction and review. Correctness
  was checked by the test suites, by the acceptance gate (`scripts/verify.py`, 107 checks), and by
  the experiment and evaluation themselves. Chapter 8 lists the defects that checking found.

## 12.9 Chapter summary

- **What was built.** The final milestone delivered the system the report designs: a plugin that
  orders the queue by the published formula and holds dependency order, two assistants that turn
  plain English into Jenkins jobs, and the backend, frontend and tooling around them.
- **The experiment** on real controllers shows the plugin doing what it claims: HIGH-priority
  waits fell 17% to 34% in every fixed-order condition, and after DF-48's fix it broke no dependency
  edge it could see. It also shows the costs:
  - waiting moves to the LOW band;
  - holding dependants costs up to 10% of makespan on three executors;
  - aging, as specified, never acts on this workload.
- **The comparison with Milestone 2** is honest only with the dependency column beside it.

<!-- SUMMARY-EVALUATION -->

## References

- deepset (2023) *prompt-injections* [dataset]. Hugging Face. Available at:
  https://huggingface.co/datasets/deepset/prompt-injections.
- Gebru, T., Morgenstern, J., Vecchione, B., Vaughan, J.W., Wallach, H., Daumé III, H. and
  Crawford, K. (2021) 'Datasheets for datasets', *Communications of the ACM*, 64(12), pp. 86–92.
  doi:10.1145/3458723.
- Larson, S., Mahendran, A., Peper, J.J., Clarke, C., Lee, A., Hill, P., Kummerfeld, J.K., Leach,
  K., Laurenzano, M.A., Tang, L. and Mars, J. (2019) 'An Evaluation Dataset for Intent
  Classification and Out-of-Scope Prediction', *Proceedings of EMNLP-IJCNLP 2019*, pp. 1311–1316.
  doi:10.18653/v1/D19-1131.
- Wijesinghe, S.P., Gimhan, K.R., Sahassaka, M.A.T. and Perera, I. (2025) 'Intent classification
  for automated software deployment plan generation: a transformer-based approach', *MERCon 2025*.
  IEEE. Available at: https://dl.lib.uom.lk/handle/123/24508.
