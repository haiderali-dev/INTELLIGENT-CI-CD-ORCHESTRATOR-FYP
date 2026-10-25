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
- [ ] **Section 12.1.3, p. 82 [81]: "three dependency chains".** The workload declares 20 dependency
      edges, on 17 dependent jobs: seven `build → test → deploy` chains (14 edges), two fan-in jobs
      (5 edges) and a release-notes job after the smoke test (1 edge).

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
      is not persisted; see `docs/decisions.md` D-011. Add the `chains` table and
      `job_runs.chain_id` too: they hold the per-service chain lock and chain tracking (D-047).
- [ ] **Add the "Explain failure" use case (T5.9, D-049).** The report has no use case for it. A
      user asks why a run failed. Code reads the redacted log and decides the cause category, the
      failing tests, the evidence lines, and what the failure stopped. The model only words the
      explanation, and an answer quoting a line that is not in the log is replaced by the code's
      own. Worth a sentence in the limitations section as well: the explanation is an aid, and the
      evidence lines, not the summary, are what can be trusted.

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
- [ ] **Section 6.4: the gate holds a Pipeline until its work starts (D-080).** It checks a Pipeline's
      first node block as it checks the job, and never its later ones, so a run is not stopped
      mid-build.
      - **State its limit:** a downstream that takes an executor before its upstream has been
        requested at all is not held, since no gate in the queue can wait for an unrequested build.
      - **Why the system never meets it:** a freestyle chain is triggered one job at a time, each
        by the one before.
- [ ] **Sections 6.5 and 6.6: the estimator's history and the plugin's cost, as built and as
      measured (D-073; Chapter 8, experiment E1).** Three sentences disagree with the
      implementation or with each other:
      - **Section 6.5 says history is "at most the last 50 builds per candidate job",** and the code
        agrees: `BuildHistoryService` reads up to `historyWindow` (50) builds from every job on the
        controller. So *h*, the builds one estimate examines, is up to 50 × the number of jobs: 1,500
        for the POC's 30 jobs.
      - **Section 6.6 says "h up to 50".** Replace it with "h up to 50 per job, so up to 1,500 for
        the POC's 30 jobs".
      - **Section 6.5 says estimates "are cached per job and refreshed only when a new build of a
        similar job completes".** The implementation caches a whole scoring pass instead
        (`BUILD_PROMPT.md` Part 4.3.7 step 2). The pass is keyed on the queued items and the rescore
        interval, and on a miss it estimates every queued job against the whole history.
      - **Section 6.6's "adds no measurable overhead ..., which we verify experimentally in the
        testing chapter".** Replace it with E1's measurement:
        - with 30 items queued, a queue-maintenance pass took 0.20 ms with the optimizer off and
          0.25 ms with it on (medians);
        - a full rescore took 2.1 ms at 30 items and 82 ms at 200 (with 340 history records);
        - it runs when the queue changes, and at most once a minute otherwise;
        - the algorithm alone took 83 µs at 200 items.
- [ ] **Section 6.2: aging does not prevent starvation under sustained load, with Appendix D's
      parameters (D-073; Chapter 8, experiment E3, a simulation).**
      - **What was measured:** over two hours of random arrivals at 95% utilisation on one
        executor, the LOW band's longest wait was 1,253 s with aging and the same without it, and
        every mean wait agreed within 2%.
      - **Why:**
        - the bonus is the same for every band and reaches its cap of 0.15 after 15 minutes, so
          under load the long-waiting jobs of every band sit at the cap together;
        - the cap equals the LOW–MEDIUM urgency gap (0.15) and is below the LOW–HIGH gap (0.35).
      - **What to write:** do not change the formula (Appendix C and the code agree on it). State
        this limitation in Section 6.2, and name band-aware aging, or a cap above 0.35, as future
        work.
      - **Note for the experiment:** in a 30-job burst of about five minutes, aging never acts at
        all (E2). An aging-ablation arm on `freestyle-30` should be expected to show no
        difference, and the report should say why.

## Chapter 12 and Table 12.1

- [ ] **Replace Chapter 12 with `docs/report/chapter-12-achievements-and-results.md`** (written in
      Phase 8). It keeps the old chapter's Milestone 1 and 2 record, corrected as listed below, and
      adds the final milestone's achievements, the experiment (Section 12.5) and the chatbot
      evaluation (Section 12.6).
      - **Its twelve tables are generated, never typed:** `python scripts/report/chapter_12.py`
        recomputes them from the archived run files, and `--check` fails if one is stale.
        Regenerate before pasting, and paste them as they are.
      - **The old chapter numbered Milestone 2's subsections 12.1.1 to 12.1.4 under 12.3.** The new
        one numbers them 12.3.1 to 12.3.4.
- [ ] **Table 12.1, p. 83 [82] is an empty skeleton** marked "to be completed from the dashboard
      export before submission". Replace it with Table 12.1 of the new chapter: the same KPIs, on
      the same condition Milestone 2 measured (`freestyle-30`, one executor), with mean ± standard
      deviation over 3 repetitions. The full per-condition tables are
      `docs/experiment/matrix-2026-10-24/report/table_12_1.md`.
- [ ] **State the experiment's findings as the evidence gives them** (Section 12.5):
      - **The gain:** HIGH-band waits fell 17% to 34% in every fixed-order condition, and mean waits
        1.6% to 9.7%.
      - **The cost to the LOW band:** on one executor, the six LOW jobs waited 224 s instead of 15 s.
        Priority scheduling moves waiting; it does not remove it.
      - **The cost in makespan:** on three executors, makespan worsened 3% to 10%, because holding
        dependants leaves executors idle that the baseline fills by breaking dependency order.
      - **Dependencies:** after DF-48's fix (D-080), the optimized arm broke no dependency edge it
        could see. The three violations left in random order are downstreams whose upstream had not
        been requested yet.
      - **Aging:** turning it off changed nothing measurable, as predicted.
      - **The sanity run:** stock Jenkins was within 0.4% of observe-only, so the baseline is
        sound.
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
- [ ] **Say what Milestone 2's HIGH-band improvement cost in dependency order (D-073; Chapter 8,
      Section 8.8.4).** The figure is 271.5 s down to 39.1 s.
      - **The broken edges:** recomputed from its result files, the run that produced it started a
        job before a job it depends on had finished on 19 of the workload's 20 dependency edges.
        Runs 1 and 2 broke 10 and 18; FIFO broke 1.
      - **Why:** Milestone 2's dependency factor was a score, not a hold, and "met" meant the
        upstream's last build ever had succeeded.
      - **The comparison with version 2:** its gate breaks none. In simulation on the same
        workload, no policy that respects dependencies got the HIGH band below 155.9 s. Compare
        version 2 with "M2 dispatcher v1" only with that column beside it.
- [ ] **Add a chatbot evaluation section:** Section 12.6 of the new chapter. Its tables (12.8 to
      12.12) are generated from the archived `python -m eval report` output in
      `docs/evaluation/`. They cover 4.9's comparisons, plan validity, the ablations and the
      end-to-end sample.
      - **Keep the provenance statement beside the figures.** The gold labels were written by
        Claude Code, and no person has reviewed them (D-081). The figures measure agreement with
        those labels, not accuracy against human judgement.
      - **Cite the dataset's sources:** CLINC150 (Larson et al., 2019; CC BY 3.0) and
        deepset/prompt-injections (deepset, 2023; Apache-2.0). Their attribution is in
        `eval/datasets/eval-v1.card.md`.

## Appendices

- [ ] **Appendix B, pp. 84–85 [83–84]: rewrite the protocol.** It contradicts the built experiment on
      nearly every parameter. Correct values: 30 jobs (9 HIGH / 15 MEDIUM / 6 LOW, confirmed against
      the legacy workload file), durations 4 to 25 s, 1 and 3 executors across two agents of two
      executors each, the controller running zero builds, three repetitions reported as mean and
      standard deviation, and the baseline arm being the same plugin with `optimizerEnabled = false`
      plus one stock-Jenkins sanity run. The full comparison is in `docs/decisions.md` D-012.
      - **The sanity run's controller (D-078):** a third controller from the same image, without the
        plugin: the same Jenkins and plugins, and the baseline's configuration without the
        optimizer's block.
      - **How its waits are measured:** it has no plugin events, so each job's queue entry is the
        harness's trigger time; build start and end come from Jenkins, as in every arm. Say so
        beside its figures.
- [ ] **Appendix C, pp. 85–86 [84–85]: regenerate from `scripts/report/appendix_c.py --build`.**
      It prints Table 13.2 from what the plugin's own calculator computes on the fixture
      `AppendixCExampleTest` asserts, so the numbers cannot drift from the code. The table shows
      *both* the score on the job's own merit and the score after group inheritance. The current
      single-column table gives `integration-tests-api` 0.633 while the prose says the group takes
      0.650, which reads as a contradiction (D-004). Paste its explanation of D and T too: the
      report's prose does not define D as `(group size - 1) / (largest group size - 1)`.
- [ ] **Appendix D, pp. 86–87 [85–86]: extend.** Add the `options { dynamicQueuePriority(...) }`
      declarative form beside the existing `properties([...])` form. Add `rescoreIntervalSeconds`,
      `metricsToken` and the metrics settings. Correct the `metricsBackendUrl` default to empty
      (`docs/decisions.md` D-006). Note that a property declared inside a Jenkinsfile only takes
      effect once that build has run, which is why the backend also writes the property into
      `config.xml` at creation time.
- [ ] **Appendix E, p. 87 [86]: replace with real versions:** paste the output of
      `python scripts/report/versions.py --appendix-e` (Table 13.3), which reads every version from
      the build files. Known wrong today: Jenkins LTS is 2.568.3, not 2.541.x (`docs/decisions.md`
      D-003), and Redis 7 is not part of the system at all. Do not hand-edit any version;
      `versions.py --check` fails when `docs/versions.md` disagrees with the build.
- [ ] **Appendix F, p. 87 [86–87]: add the version 2 KPI definitions** listed under Chapter 12 above.

## New: limitations and disclosure

- [ ] **Add a limitations section** covering: the Docker socket mounted into local agents and what
      that means for isolation; staging-only scope; three repetitions being a small sample; a single
      controller, so no cross-controller behaviour is measured; Groq free-tier rate and token limits
      shaping the evaluation design; and the estimator's cold-start path returning UNKNOWN.
- [ ] **Disclose AI-assisted development**, stating what was generated, what was reviewed by hand,
      and how correctness was checked (the test suites and `scripts/verify.py`).

## New: from the hardening of Phases 1 to 6 (2026-10-18 to 2026-10-20)

- [ ] **Testing chapter: report the independent security review.** It covered Phases 3, 5 and 6 and
      found 15 issues (2 Medium, 7 Low, 6 Info), all fixed with regression tests. The two Medium:
      a HIGH-urgency request could be re-approved without a new justification or quota, and
      Jenkins and the backend were published on every network interface. Source:
      `docs/security-review-phases-3-5-6.md`, D-065.
- [ ] **Limitations section: add the review's accepted residual risks** from the same file:
      in-memory token and rate-limit stores, logs visible to every signed-in user, public API docs,
      CI actions pinned by tag, and pattern-based redaction.
- [ ] **Appendix D: floating-point settings must be quoted in JCasC YAML.** JCasC drops an unquoted
      float without a warning (`weightUrgency: "0.5"`, not `0.5`). D-017 records the root cause in
      JCasC's YAML loader. The aging-ablation arm depends on this.
- [ ] **Chapter 4 / deployment: the frontend runs as its own container.** It is nginx serving the
      build and proxying `/api` and `/ws`, with a Content-Security-Policy, and every port is bound
      to 127.0.0.1 (D-065). Redraw the deployment view with it.
- [ ] **Appendix E: add the image versions** from `docs/versions.md` "Images" (Python 3.12.15,
      PostgreSQL 16.15, Node 24.21.0 for the build, nginx-unprivileged 1.30.4).
- [ ] **Chapter 6, Algorithm 3, and Appendix C: dependency groups span the whole queue.** State that
      groups are formed over every queued item, including those the dependency gate is holding, and
      that only buildable items are ranked. Until D-067 the plugin grouped the buildable items only.
      The gate keeps a consumer out of that list, so D was always 0 and Appendix C's inheritance
      could never happen in a live queue. Say so in the Testing chapter too: it is a defect that
      unit tests could not find, because they build their groups by hand.
- [ ] **Testing chapter: User Story 5, criterion 3 needed a fix to pass.** A role guard's refusal, a
      replayed refresh token and an engaged sign-in limit were detected but not audited (D-068).
      They are now audited, at most once a minute per caller for a limit.
- [ ] **Usability and accessibility: Lighthouse scores 100 for accessibility** on both assistant
      pages, in all 16 audits (empty and with a chat, light and dark, mobile and desktop). Measured
      signed in (D-064), and checked in CI on every push since 2026-10-20.

## New: from Phase 8 (2026-10-24 to 2026-10-25)

- [ ] **Limitations section: the evaluation's labels (D-081).**
      - **Who labelled it:** one AI author, Claude Code, wrote and labelled `eval-v1`, and no person
        has reviewed it. There is no inter-annotator agreement, and the author's reading of the
        labelling rules is built into the labels.
      - **How it was checked:** the labels were checked against twelve stated rules by code. That
        catches slips, not misreadings.
      - **Other limits:** the catalog has two services, and the authored messages may be more
        regular than real users' messages.
      - **What to recommend:** a person's review of at least the test split, as the datasheet
        describes.
- [ ] **Limitations section: free-tier limits shaped the evaluation.**
      - **The cost:** about 1,800 tokens an intent parse.
      - **What it shaped:** the comparisons used the test split only, and the ablations one model.
      - **Latency:** quota waits are excluded from the figures, but a paid tier may differ.
- [ ] **Limitations section: the dependency gate cannot hold a job whose upstream has not been
      requested at all** (D-080). Random order met it three times. The system's own chains never
      meet it, because each job triggers the next.
- [ ] **AI-assisted development disclosure: name the Phase 8 work too.** Claude Code wrote:
      - the evaluation dataset and every gold label;
      - the evaluation harness;
      - Chapter 12's draft and the generators of its tables, of Appendix C and of Appendix E.

      The team directed the work and reviewed it. The tests and `scripts/verify.py` (107 checks
      across Phases 0 to 8) checked it.
- [ ] **Testing chapter, Section 8.8.5 "Experiment v2 (Phase 7): not yet run":** replace with a
      pointer to Chapter 12, Section 12.5. The matrix ran on 2026-10-24 (53 runs), and so did the
      re-run after DF-48's fix (10 runs).
- [ ] **Testing chapter, Section 8.10's last paragraph** says the chatbot evaluation "needs the
      drafted evaluation items reviewed by people". Replace it with what was done (D-081): a
      machine-labelled evaluation, reported as such in Chapter 12, Section 12.6, with a person's
      review still recommended.
- [ ] **Chapter 6, Algorithm 1: define D as the plugin computes it,** `(group size - 1) /
      (largest group size - 1)`, and 0 for an independent job or when no group has more than one
      member. Define T as `1 - (estimate - shortest) / (longest - shortest)`, and 0.5 when the
      estimate is unknown or every estimate is equal. Appendix C's generated explanation states
      both; the chapter should match it.
- [ ] **A demonstration section, or an appendix:** the scripted demo (`docs/demo-script.md`) runs
      from a known state (`scripts/demo_reset.py`), with the model's answers replayed from
      fixtures, so it needs no model access on the day.
