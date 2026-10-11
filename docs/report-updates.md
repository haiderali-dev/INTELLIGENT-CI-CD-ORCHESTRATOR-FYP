# Report updates

Every change the report in `docs/report/` needs so that it matches the built system. A checklist, per
`BUILD_PROMPT.md` Part 4.10.

Only the PDF was supplied, not the Word source, so this file records *what* to change and *why*
rather than editing the document. Ask the report owner for the `.docx` before the editing pass, or
tick items off against the PDF page numbers given here.

Page numbers are PDF page numbers, with the report's own printed page number in brackets where they
differ.

---

## Blocking: claims about delivered work

- [ ] **Section 12.1.3, p. 82 [81]: remove or requalify the Milestone 2 overclaim.** The text states
      the team "built the metrics pipeline that records every scheduling decision and build outcome
      into PostgreSQL through a FastAPI backend, and the React analytical dashboard that visualizes
      the live queue". None of that existed at Milestone 2: the deliverable was one static HTML file
      reading `comparison.json`. Either move the claim to the Milestone 3 chapter or mark it as
      planned. See `docs/decisions.md` D-013. *This is the most important item in this file, because
      it is a claim about delivered work rather than a detail.*
- [ ] **Section 12.1.3, p. 82 [81]: the experiment is described as 25 jobs.** It was 30. See
      Appendix B below.
- [ ] **Section 12.1.3, p. 82 [81]: "three dependency chains".** The workload declares 17 dependency
      edges across seven `build → test → deploy` chains plus two fan-in jobs.

## Blocking: the formula the report publishes was not the formula that ran

- [ ] **Chapter 6 and Appendix C: state that Milestone 2's implementation diverged, and that
      version 2 does not.** The published formula is `0.5·U + 0.3·D + 0.2·T` with U = 1.0 / 0.6 / 0.3.
      Milestone 2's code computed `0.5·urgency + 0.3·executionTime + 0.2·dependency` with urgency
      100 / 50 / 10, no aging and no group inheritance — the dependency and execution-time weights
      were transposed. Evidence and a comparison table are in `docs/m2-baseline.md` section 4.3.
      Version 2 is guarded by `AppendixCExampleTest`, which shares its fixture with
      `scripts/report/appendix_c.py`, so the report and the code cannot drift again. Say so.

## Abstract and Chapter 1

- [ ] **Scope:** state staging-only explicitly, and that production deployment is refused by policy
      rather than merely unimplemented.
- [ ] **Scope:** the system has *two* assistants sharing one AI core — a Freestyle Assistant
      producing chained freestyle jobs and a Pipeline Assistant producing declarative Jenkinsfiles —
      not one command console.
- [ ] **Scope:** the plugin covers freestyle, Maven *and* Pipeline jobs under one scoring formula.
      Milestone 2 covered only `AbstractProject`, so Pipeline jobs bypassed the optimizer entirely.

## Chapter 4: architecture figures

- [ ] **Figure 4.1 and Figure 4.2: redraw.** Both must show the split that defines version 2:
      `DynamicQueueSorter` (a `QueueSorter`) *orders* every buildable item, while `DependencyGate`
      (a `QueueTaskDispatcher`) only *gates* on dependencies. Milestone 2 did both jobs in one
      `QueueTaskDispatcher#canTake`, which is why it could fill only one executor per maintenance
      pass.
- [ ] **Figures 4.1 and 4.2:** add both assistants and the shared AI core.
- [ ] **Remove Redis.** It appears in Appendix E as the "live queue state cache". The version 2 stack
      has no Redis; live queue state comes from the plugin's API and the WebSocket hub.

## Chapter 5: use cases and schema

- [ ] **Split UC-02 and UC-03 into freestyle and Pipeline variants** (pp. 42–48), with real
      screenshots from `docs/screenshots/` rather than mockups.
- [ ] **Section 5.12, p. 65 [64]: update the navigation.** The report lists Home, Command Console,
      Submit Job, Queue, Pipelines, Analytics, Admin. Version 2 replaces Command Console with the
      Freestyle Assistant and adds a separate Pipeline Assistant page.
- [ ] **Section 5.14 and Figure 5.44, pp. 66–68: replace the schema.** The report describes twelve
      tables including `job_dependencies` and `dependency_groups`, and lacks `services`,
      `conversations`, `messages`, `nl_commands` as specified, `generated_pipelines` as specified,
      `llm_calls`, `jobs` as specified and `audit_logs` as specified. Use the table in
      `BUILD_PROMPT.md` Part 4.4.3. Dependency grouping is computed per queue cycle by the plugin and
      is not persisted; see `docs/decisions.md` D-011.

## Chapter 6: algorithms

Chapter 6's algorithm definitions are correct and need no mathematical change. What they lack is how
each one attaches to Jenkins.

- [ ] **Add, for each of the four algorithms, the Jenkins extension point it runs inside**, and at
      what moment. Chapter 6 currently analyses the algorithms as if they ran in a vacuum.
- [ ] **Add the Pipeline queue-item explanation.** A Pipeline `node` block enters the queue as a
      placeholder task, not as the job, so the job is resolved by walking `getOwnerTask()`. This is
      the single most important implementation fact in the plugin and it appears nowhere in the
      report. Note also that gating applies to whole jobs and never to node blocks of a run already
      in progress.
- [ ] **Section 6.2: document the aging bonus as implemented**, including that `waitMinutes` comes
      from `getInQueueSince()` and that including the current minute in the sorter's cache key is what
      refreshes aging at least once a minute.
- [ ] **Section 6.3: note that only the first registered `QueueSorter` is consulted**, and that the
      plugin warns at startup if another is present.
- [ ] **Section 6.5.1: qualify the cold-start claim.** The text says a job with nothing similar
      returns UNKNOWN and takes the neutral factor 0.5. That is true, but reaching it requires the
      history to differ in **agent label** as well as in name. Because two unparameterised builds
      have identical (empty) parameter sets, the parameter term contributes its full 0.3 and a shared
      label adds 0.2, so any two unparameterised builds on the same label score 0.5 and clear the
      0.35 threshold before their names are compared. On a single-label, unparameterised workload —
      which is exactly what `freestyle-30` is — the threshold filters almost nothing and name
      similarity acts as a ranking weight instead. Measured in `SimilarityEstimatorTest`; see
      `docs/decisions.md` D-016.
- [ ] **Section 6.4: state that a missing upstream job is flagged unresolved and never treated as
      satisfied.** Milestone 2 counted a missing upstream as satisfied, which is the opposite of safe.
      State also that a declared cycle never blocks at runtime; it is rejected by form validation and
      by the backend, and reported through the API.

## Chapter 12 and Table 12.1

- [ ] **Table 12.1, p. 83 [82] is an empty skeleton** marked "to be completed from the dashboard
      export before submission". Replace it with the generated `experiment/results/table_12_1.md`.
- [ ] **Add the version 2 KPIs** that Appendix F lacks: dependency violations (target 0), maximum LOW
      wait, and scheduler overhead per cycle. For Pipeline runs, report the first node block's wait
      and the sum of all node-block waits separately.
- [ ] **Report mean and standard deviation across repetitions**, and state plainly that three
      repetitions is a small sample.
- [ ] **Add the Milestone 2 numbers as a labelled series, "M2 dispatcher v1"**, using the recomputed
      figures in `docs/m2-baseline.md` section 3.1 — *not* the figures in the stored
      `comparison.json`, which is stale against its own inputs (`docs/decisions.md` D-008). Never mix
      this series into version 2 aggregates.
- [ ] **Report the honest shape of the Milestone 2 result.** HIGH-band wait fell from 271.5 s to
      39.1 s, but makespan got slightly worse, average wait improved by under 9 %, and LOW-band wait
      rose from 16 s to 233 s. On a single executor, reordering moves waiting around rather than
      removing it. Saying so strengthens the report; omitting it invites the obvious question in a
      viva.
- [ ] **Add a chatbot evaluation section** from `python -m eval report`.

## Appendices

- [ ] **Appendix B, pp. 84–85 [83–84]: rewrite the protocol.** It contradicts the built experiment on
      nearly every parameter. Correct values: 30 jobs (9 HIGH / 15 MEDIUM / 6 LOW, confirmed against
      the legacy workload file), durations 4 to 25 s, 1 and 3 executors across two agents of two
      executors each, the controller running zero builds, three repetitions reported as mean and
      standard deviation, and the baseline arm being the same plugin with `optimizerEnabled = false`
      plus one stock-Jenkins sanity run. The full comparison is in `docs/decisions.md` D-012.
- [ ] **Appendix C, pp. 85–86 [84–85]: regenerate from `scripts/report/appendix_c.py`.** Add a column
      so the table shows *both* the base score and the effective score after group inheritance. The
      current single-column table gives `integration-tests-api` 0.633 while the prose says the group
      takes 0.650, which reads as a contradiction. See `docs/decisions.md` D-004.
- [ ] **Appendix D, pp. 86–87 [85–86]: extend.** Add the `options { dynamicQueuePriority(...) }`
      declarative form beside the existing `properties([...])` form. Add `rescoreIntervalSeconds`,
      `metricsToken` and the metrics settings. Correct the `metricsBackendUrl` default to empty
      (`docs/decisions.md` D-006). Note that a property declared inside a Jenkinsfile only takes
      effect once that build has run, which is why the backend also writes the property into
      `config.xml` at creation time.
- [ ] **Appendix E, p. 87 [86]: replace with real versions** from `scripts/report/versions.py`.
      Known wrong today: Jenkins LTS is 2.568.3, not 2.541.x (`docs/decisions.md` D-003), and Redis 7
      is not part of the system at all. The React, Python and Java lines are whatever
      `docs/versions.md` records once each component is pinned; do not hand-edit them.
- [ ] **Appendix F, p. 87 [86–87]: add the version 2 KPI definitions** listed under Chapter 12 above.

## New: limitations and disclosure

- [ ] **Add a limitations section** covering: the Docker socket mounted into local agents and what
      that means for isolation; staging-only scope; three repetitions being a small sample; a single
      controller, so no cross-controller behaviour is measured; Groq free-tier rate and token limits
      shaping the evaluation design; and the estimator's cold-start path returning UNKNOWN.
- [ ] **Disclose AI-assisted development**, stating what was generated, what was reviewed by hand,
      and how correctness was checked (the test suites and `scripts/verify.py`).
