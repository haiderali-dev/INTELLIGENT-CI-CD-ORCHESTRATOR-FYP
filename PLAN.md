# PLAN.md

Plan presented and approved on 2026-09-28, before any code was written. It follows the kickoff
message in `BUILD_PROMPT.md`. Once a phase starts, `PROGRESS.md` is the live record; this file is
the starting position and is only amended when a decision here turns out to be wrong.

---

## 1. Understanding of the target system

One monorepo producing three things that meet in the Jenkins queue.

### The plugin

`dynamic-queue-optimizer` 2.0.0 stops *gating* the queue and starts *ordering* it. That is the
pivotal architectural change from Milestone 2:

- `QueueSorter#sortBuildableItems` ranks every buildable item, so N idle executors take the top N
  compatible items in one maintenance cycle.
- `QueueTaskDispatcher#canRun` is demoted to dependency gating only.

In Milestone 2 a single `QueueTaskDispatcher#canTake` did both jobs at once, and because it allowed
only the heap root to proceed, it could never fill more than one executor per pass. Separating the
two concerns is what fixes that.

Job resolution walks `getOwnerTask()` up to five times so a Pipeline placeholder task resolves to
its `WorkflowJob`. That one step is what makes Pipeline jobs visible to the optimizer at all; in
Milestone 2 an `instanceof AbstractProject` check made them invisible.

Scoring is the report's Algorithm 1 exactly: `0.5·U + 0.3·D + 0.2·T`, with `U` = HIGH 1.0 /
MEDIUM 0.6 / LOW 0.3, plus an aging bonus of `min(0.15, 0.05 · floor(waitMinutes / 5))` and group
score inheritance. Milestone 2 shipped a different formula with different weights on a 0-100 scale.

### The assistants

Two assistants over one AI core. Parsing, clarification and policy are shared; only the renderer
differs. The division of authority is the important part:

- The LLM plans a YAML spec from catalog-constrained enums. It chooses stages and templates.
- It never writes shell commands. Those come from `catalog/services.yaml`.
- It never decides validity. Code checks the service, branch, commit, suite and environment.
- Jinja2 renders artifacts whose templates are derived from `config.xml` exported from real
  hand-made jobs, never written from memory.
- A human approves before anything is created or triggered.

The Freestyle Assistant emits a three-job chain wired by downstream triggers. The Pipeline
Assistant emits one declarative Jenkinsfile. Both hand their jobs to the same plugin.

### The measurement apparatus

The experiment harness, the chatbot evaluation and the report generators exist so that no number in
the report is ever typed by hand. `scripts/report/appendix_c.py` prints Appendix C from the same
fixture the plugin test uses, so the report cannot drift from the code.

### The through-line

The rebuild is fundamentally about honesty. In Milestone 2 the implemented formula disagreed with
the published formula, `comparison.json` was stale against its own inputs, and the dispatcher
silently degraded to FIFO. Version 2 turns each of those into a test that fails loudly:
`AppendixCExampleTest`, the `run`-always-calls-`analyze` rule, and
`CacheEvictionRegressionIT`.

---

## 2. Build order, and the risky assumptions tested first

### Order

**Phase 0 → Phase 2 → Phase 1 → 3 → 4 → 5 → 6 → 7 → 8.**

One deviation from the literal Part 3 order, approved on 2026-09-28: **Phase 2 runs before
Phase 1.** Docker is not installed on this machine, which blocks Phase 1 completely, while JDK
21.0.11 and Maven 3.9.16 are present and every Phase 2 test except T2.14 runs on `JenkinsRule`
with no Docker at all. Building the plugin first keeps the critical path moving and front-loads the
riskiest assumptions in the whole design. T2.14 (build the `.hpi` and install it on `jenkins-dev`)
defers into Phase 1, where the container exists.

Everything else follows Part 3. Phase 3 and 4 are backend and AI core, Phase 5 needs Phase 1's
exported reference configs before its templates can be honest, Phase 6 needs Phase 3's OpenAPI
schema to generate its types, and Phases 7 and 8 need a working stack.

### Risky assumptions

T2.1 writes these as failing tests before any production code, as Part 3 requires. Each one is an
assumption this design would collapse without, so each is proven against a real Jenkins before
anything is built on top of it.

| # | Assumption | First test | Why it is risky |
| --- | --- | --- | --- |
| 1 | `QueueSorter` is consulted for Pipeline placeholder tasks, and `getOwnerTask()` resolves the job without throwing | `PipelinePriorityIT` | The entire Pipeline story depends on it. Milestone 2 never tested Pipeline jobs. |
| 2 | Three idle executors consume the top three sorted items in one cycle | `MultiExecutorIT` | This is the Milestone 2 multi-executor flaw. Multi-executor behaviour was never tested. |
| 3 | Jenkins uses only the first registered `QueueSorter` | startup warning, `ObserveOnlyIT` | A second sorter from another plugin would silently disable ours. |
| 4 | `@Symbol` on a `JobProperty` descriptor enables both the `options { }` and `properties([ ])` forms | `DeclarativeOptionsIT` | Report Appendix D publishes the `properties` form; Part 4.3.2 also publishes `options`. |
| 5 | Re-scoring every cycle never degrades to arrival order while draining | `CacheEvictionRegressionIT` | This is Milestone 2 bug 6, which silently produced FIFO results. |
| 6 | Milestone 2 `config.xml` still loads after the property field rename | new back-compat test | See conflict 3 below. Old job configurations must not break. |

Assumptions verified later, in their own phases:

- **Phase 4.** That Groq still serves `openai/gpt-oss-120b` and `openai/gpt-oss-20b`, that both
  honour a strict JSON schema through `response_format`, and what the free-tier limits actually
  are. Verified against Groq's own documentation, not from memory, and recorded in
  `docs/versions.md`.
- **Phase 5.** The declarative linter's request and response shape at
  `POST /pipeline-model-converter/validate`.
- **Phase 1.** Whether Linux Docker agents over SSH can run the Docker CLI against a mounted
  socket, which `BUILD_PROMPT.md` already names as a limitation to disclose.

---

## 3. Conflicts found

Verified against the report PDF (90 pages), the legacy code and the legacy result files. Every item
is recorded in `docs/decisions.md`; the ones needing a report change are also in
`docs/report-updates.md`.

### Proven by re-running the legacy analysis (task T0.1)

The legacy `experiment/` folder was copied to `.tmp/m2-analysis/` and its analysis re-run there.
Nothing under `legacy/` was written to.

**Conflict 1: `comparison.json` is stale. Confirmed, not merely suspected.**

The committed artifact cites `baselineT0 = 1781512211965` and `pluginT0 = 1781512819559`, but the
result files on disk carry `t0 = 1781518086378` and `t0 = 1781518804085`. Both inputs were
regenerated after `analyze.py` last ran, and nobody re-ran the analysis. This is Milestone 2 known
problem 7, caught in the act.

Re-running the analysis reproduces the `BUILD_PROMPT.md` Part 2.2 table exactly, from
`plugin-results-run4.json`:

| Metric | Part 2.2 | Recomputed from run4 | Stale `comparison.json` |
| --- | --- | --- | --- |
| Makespan, baseline / plugin | 322.1 / 328.2 | **322.07 / 328.21** | 327.75 / 328.2 |
| Average wait, baseline / plugin | 156.9 / 143.0 | **156.88 / 143.02** | 159.83 / 144.06 |
| HIGH-band wait, baseline / plugin | 271.5 / 39.1 | **271.5 / 39.08** | 276.13 / 46.24 |
| LOW-band wait, baseline / plugin | about 16 / 232.9 | **15.89 / 232.94** | 16.7 / 232.82 |

Conclusion: Part 2.2's table is sound and reproducible, and the committed dashboard artifact is
wrong. The report must cite the recomputed numbers.

**Conflict 2: `plugin-results-run3.json` is an outlier that is itself evidence.**

Run 3 shows a HIGH-band wait of 353.34 s, *worse* than the 271.5 s baseline, with a LOW-band wait
of 28.12 s — close to arrival order. That is the fingerprint of Milestone 2 known problem 6, the
run where skipped heap repopulation silently degraded the plugin to FIFO. It goes into
`docs/m2-baseline.md` as evidence of the bug rather than being quietly dropped, and it is the
reason `CacheEvictionRegressionIT` exists.

Minor, same family: `baseline-results.json` holds 31 job rows against a 30-job specification, and
`analyze.py` silently discards the extra row instead of reporting it.

### Report versus `BUILD_PROMPT.md`

**Conflict 3: Appendix C scores `integration-tests-api` at 0.633; Part 4.3.10 demands 0.650.**

Neither is wrong. Report Table 13.2 prints the pre-inheritance base score, and the prose then
applies group inheritance: "Group G1 takes the maximum score of its members, 0.650." All four rows
were verified arithmetically: 0.667, 0.650, 0.633 → 0.650, 0.300.

Resolution: `AppendixCExampleTest` asserts **both** the base 0.633 and the effective 0.650, and
`scripts/report/appendix_c.py` emits both columns, so the ambiguity cannot recur in the report.

**Conflict 4: the property field name is self-contradictory inside `BUILD_PROMPT.md`.**

Part 4.3.2 names the field `level`, and both published Jenkinsfile forms need `level:`. The same
paragraph also says to keep the Milestone 2 field names so old job configurations still load — but
the Milestone 2 field is `priority`, in `JobPriorityProperty.java` and in `config.jelly`
(`field="priority"`). Both cannot hold at once.

Resolution: the data-bound field becomes `level`, because the `@Symbol` form requires it, plus an
XStream field alias from `priority` to `level` and a deprecated `getPriority()`. Old `config.xml`
still deserializes, and a back-compat test proves it.

**Conflict 5: Jenkins LTS baseline.** Report Appendix E says 2.541.x, Milestone 2 built on 2.479.3,
and the current LTS is 2.568.3, released 11 September 2026 and tested on JDK 21 and 25. Approved
on 2026-09-28: pin **2.568.3**. Local JDK 21.0.11 matches a tested configuration. 2.580.1 was due
30 September 2026 and was not yet released when this decision was taken.

**Conflict 6: report Appendix E lists Redis 7** as the live queue state cache. The version 2 stack
has no Redis. Remove it from Appendix E.

**Conflict 7: report Appendix B's experiment protocol contradicts Part 4.8 on nearly every axis.**

| Axis | Report Appendix B | Part 4.8 | Legacy `jobs.json` |
| --- | --- | --- | --- |
| Jobs | 25 | 30 | **30** |
| Bands | 8 HIGH / 9 MEDIUM / 8 LOW | 9 / 15 / 6 | **9 / 15 / 6** |
| Executors | 2, on 1 agent | 1 and 3, 2 agents of 2 | — |
| Durations | 30 s to 4 min | sleeps | **4 to 25 s** |
| Aggregation | median pair of 3 | mean and standard deviation of 3 | — |

The legacy workload sides with `BUILD_PROMPT.md` on every axis it can speak to. Appendix B needs a
full rewrite.

**Conflict 8: report section 12.1.3 overclaims Milestone 2**, stating that the PostgreSQL metrics
pipeline, the FastAPI backend and the React analytical dashboard were built. Part 2.2 and the
legacy tree, which holds one static HTML dashboard and no backend, say otherwise. This is the most
important report correction, because it is a claim about what was delivered.

**Conflict 9: report section 5.14's twelve-table schema** includes `job_dependencies` and
`dependency_groups`, and lacks `services`, `conversations`, `messages` and `llm_calls`. Part 4.4.3
supersedes it. Dependencies live on `jobs.depends_on` and in the plugin's runtime snapshot rather
than in two tables.

**Conflict 10: report Appendix D defaults `metricsBackendUrl`** to
`http://backend:8000/api/metrics`; Part 4.3.1 defaults it empty. Empty wins, so metrics stay off
until deliberately configured and a fresh install never posts to a host that may not exist.

**Conflict 11: report Table 12.1 is an empty skeleton**, marked "to be completed from the
dashboard export before submission". Task T7.4 generates it.

### Conflicts looked for and not found

Chapter 6 agrees with `BUILD_PROMPT.md` on all four algorithms, including the weights, the aging
bonus and cap, the `UNKNOWN` neutral value of 0.5, the similarity feature weights of 0.5 / 0.3 /
0.2, `k = 5`, the 0.35 threshold, `lambda = 0.1` per day and the 50-build window. Where Part 4 is
silent, Chapter 6 is followed. Chapter 6.3.3 says the heap adapts Java's `PriorityQueue` with a
custom comparator, which is what Milestone 2's `PriorityJobHeap` does and what version 2 keeps.

---

## 4. Questions for a human, and what happens meanwhile

### Answered on 2026-09-28, before work began

1. **Repository preparation.** Human setup steps 1 to 3 had never been run. Approved: prepare it
   fully — initialise Git, move the Milestone 2 folders into `legacy/m2-poc/`, move the report into
   `docs/report/`, write the root configuration files, commit, and tag `m2-final`.
2. **Docker is missing.** Approved: proceed on Phase 0 and Phase 2, which need no Docker, and put
   installing Docker Desktop under Needs human.
3. **LTS baseline.** Approved: pin 2.568.3.

### Open, tracked under Needs human in `PROGRESS.md`

1. **Install Docker Desktop and start it.** Blocks Phase 1 entirely and every acceptance check from
   Phase 3 onward. *Meanwhile:* Phase 0, then Phase 2 in full except T2.14.
2. **Provide `.env` secrets.** `GROQ_API_KEY`, `JENKINS_ADMIN_PASSWORD`, `JENKINS_BOT_PASSWORD`,
   `JWT_SECRET`, `METRICS_TOKEN`, `POSTGRES_PASSWORD`, `SEED_ADMIN_EMAIL`, `SEED_ADMIN_PASSWORD`.
   *Meanwhile:* `.env.example` carries placeholders, and Phase 4 uses `FakeProvider` and
   `ReplayProvider`, which need no key.
3. **Create the two sample-service GitHub repositories**, push them, create the
   `demo/failing-tests` branch, and put the URLs in the catalog. *Meanwhile:* the services are
   built locally and the catalog is validated against local paths.
4. **Install `gh`, or open pull requests by hand.** *Meanwhile:* each phase ends on its branch and
   "Open pull request for phase-*n*" goes under Needs human.
5. **Approve `frontend/DESIGN.md`** before any screen is built, as task T6.1 requires.
6. **Label and review the evaluation gold answers.** At most 30 drafted items, each marked
   `needs_review: true` and excluded from scoring until a human clears the flag.
7. **Schedule the long runs:** the full experiment matrix of about 50 runs, and the final live
   chatbot evaluation. `BUILD_PROMPT.md` keeps both with humans.
8. **The report's Word source is missing.** Only the PDF is present, so `docs/report-updates.md`
   records changes as a checklist against the PDF rather than editing the document.

### Decided without asking, and recorded in `docs/decisions.md`

- **Python version for the backend.** The system interpreter is 3.14.2 and the report targets 3.12.
  `uv` will manage a pinned 3.12 interpreter for `backend/`, because 3.14 is new enough that some
  dependencies may lack wheels and the report's stated version should hold.
- **`uv` and `gh` are not installed.** `uv` is installed project-locally when Phase 3 starts, since
  rule 1.5 permits project-local dependencies but not system-wide software.
- **Build output is not committed.** `legacy/m2-poc/` keeps its sources, scripts, results,
  dashboard and logs, but `target/` build output is excluded. Conflict 1 needs the result files, and
  nothing needs a rebuilt Jetty webapp.
