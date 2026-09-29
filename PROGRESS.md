# Progress

Updated: 2026-09-29 · Current phase: 1 and 3 · Branch: phase-3-backend

## Needs human
- [ ] **Create the two sample-service GitHub repositories**, push them, create the
      `demo/failing-tests` branch, and put the URLs in `catalog/services.yaml`. Blocks T1.8's
      `git ls-remote` check and the Phase 5 failing-branch acceptance test.
- [ ] **Resolve or work around the JCasC floating-point defect (D-017).** Importing a YAML file
      silently ignores `weightUrgency`, `weightDependency`, `weightExecutionTime`,
      `agingBonusPerInterval`, `agingCap`, `similarityThreshold` and `recencyLambdaPerDay`, while
      every other field applies. `optimizerEnabled` works, so the main baseline-versus-optimized
      comparison is unaffected and Table 12.1 stays reproducible from YAML. The **aging-ablation arm**
      of the Part 4.8.2 matrix varies `agingBonusPerInterval` and `agingCap`, so it cannot be driven
      from JCasC and needs another route (the global configuration form, or a decision to drop that
      arm). `ConfigAsCodeIT.floatingPointAttributesAreNotAppliedKnownDefect` pins the current
      behaviour and will fail loudly when it is fixed.
- [ ] **Install `gh`, or open pull requests by hand.** Not blocking; each phase still ends on its
      own branch.
- [ ] **Approve `frontend/DESIGN.md`** when T6.1 produces it. No screen is built before that.
- [ ] **Label and review the evaluation gold answers** (Phase 8). At most 30 drafted items, each
      marked `needs_review: true` and excluded from scoring until a human clears the flag.
- [ ] **Schedule the long runs:** the full experiment matrix, about 50 runs (Phase 7), and the final
      live chatbot evaluation (Phase 8).
- [ ] **Supply the report's Word source**, or confirm the PDF is the only copy. Only
      `INTELLIGENT CI-CD ORCHESTRATOR FYP Report.pdf` was provided, so `docs/report-updates.md`
      tracks changes as a checklist rather than editing the document.

## Phase 0: Repository foundation
- [x] T0.1 Verify `legacy/m2-poc/`, re-run the M2 analysis in `.tmp/m2-analysis/`, compare with the
      stored `comparison.json` — evidence: `python analyze.py --plugin-results plugin-results-run4.json`
      in `.tmp/m2-analysis/scripts` → reproduced BUILD_PROMPT Part 2.2 exactly (makespan 322.07 /
      328.21, avg wait 156.88 / 143.02, HIGH 271.5 / 39.08, LOW 15.89 / 232.94). The stored
      `comparison.json` disagrees on every figure and is stale: it cites `baselineT0=1781512211965`
      and `pluginT0=1781512819559` while the result files on disk carry `t0=1781518086378` and
      `t0=1781518804085`. Nothing under `legacy/` was written to.
- [x] T0.2 Write `docs/m2-baseline.md` — evidence: `python scripts/verify.py --phase 0` → check
      "M2 baseline figures match the legacy result files" PASS. The check recomputes the HIGH-band
      mean wait straight from the frozen result files and asserts the figure appears in the document:
      271.50 s baseline → 39.08 s plugin. The document cannot drift from the data it describes.
- [x] T0.3 Monorepo skeleton, `.gitignore`, `.gitattributes`, `.editorconfig`, `.env.example`,
      `README.md` — evidence: `python scripts/verify.py --phase 0` → "skeleton folders exist" all 22
      present, "root documents exist" all 9 present, ".gitattributes sets LF for the required types"
      all 7 types pinned, "legacy/ is exempt from line-ending normalisation" PASS.
- [x] T0.4 `.github/workflows/ci.yml` with plugin, backend and frontend jobs, each skipped until its
      folder holds a build file — evidence: `python scripts/verify.py --phase 0` → "CI workflow
      parses" PASS, 5 jobs (detect, verify, plugin, backend, frontend). A `detect` job sets an output
      per component from the presence of `pom.xml`, `pyproject.toml` and `package.json`, and the
      three build jobs are gated on it, so an unbuilt component reports as skipped rather than as
      success.
- [x] T0.5 `scripts/verify.py` following Appendix D, with the Phase 0 checks — evidence:
      `python scripts/verify.py --phase 0` → ALL CHECKS PASSED, exit code 0. 11 checks.
      `--list` shows them without running them. A phase with no checks registered fails loudly
      rather than passing vacuously.
- [x] T0.6 `docs/decisions.md`, `docs/report-updates.md`, `docs/versions.md` — evidence:
      `python scripts/verify.py --phase 0` → "tracking documents exist" all 4 present. 13 decisions
      recorded (D-001 to D-013), including all eleven conflicts found.

**Acceptance:** `python scripts/verify.py --phase 0` prints ALL CHECKS PASSED.
**Met** on 2026-09-28: 11 of 11 checks pass, exit code 0.

## Phase 1: Infrastructure
Branch `phase-3-backend` (the Docker layer was written here while Phase 3 was in progress; it
belongs to Phase 1 and is listed under it).

- [x] T1.1 Controller image in `jenkins/controller/` — evidence: `python scripts/verify.py --phase 1`
      → "Docker and Compose files exist" all 9 present, "the controller image installs the built
      plugin" PASS, "controller plugins are pinned" 16 plugins all pinned. Jenkins 2.568.3-lts-jdk21,
      plugins installed with `jenkins-plugin-cli`, setup wizard disabled, `CASC_JENKINS_CONFIG` set,
      and the built `.hpi` copied to `/usr/share/jenkins/ref/plugins/`.
- [x] T1.2 Agent image in `jenkins/agent/` — `jenkins/ssh-agent:6.31.0-jdk21` plus Git, Python 3,
      Node.js 24, the Docker CLI, curl and jq, with a build-time smoke check on each tool.
- [x] T1.3 JCasC files `dev.yaml`, `experiment-baseline.yaml`, `experiment-plugin.yaml` — evidence:
      `verify.py --phase 1` → "JCasC files are valid and the two arms differ only in
      optimizerEnabled" PASS and "JCasC sets no floating-point optimizer field (D-017)" PASS.
      Controller `numExecutors: 0`, local realm with `admin` and `orchestrator-bot`, matrix auth
      granting the bot no `Overall/Administer`, both agents on credential `agent-ssh-key`.
- [x] T1.5 `docker-compose.yml` with the default services and the `experiment` profile — evidence:
      `verify.py --phase 1` → "docker-compose.yml is valid and matches Part 4.2.3" (10 services,
      5 default, 5 profiled) and "Compose refuses to start rather than defaulting a secret" PASS.
      Every build context and `COPY` source resolves except `frontend`, which is profile-gated until
      Phase 6 (D-018).
- [x] T1.10 Phase 1 checks in `verify.py` — 12 checks, **all passing**: the 9 offline ones plus
      three live ones added once the stack was up (jenkins-dev answers with the bot token, the
      controller runs zero executors, both agents online with the `linux` label).
- [x] T1.4 `scripts/bootstrap.py`: SSH keys, waiting for Jenkins, creating the bot API token —
      evidence: `python scripts/bootstrap.py` → generated an ed25519 pair, waited for the
      controller, minted a 34-character token and verified the bot can authenticate with it.
      No script console: the token comes from
      `/user/<id>/descriptorByName/jenkins.security.ApiTokenProperty/generateNewToken`.
- [ ] T1.6 Sample service `payment-service` (Python)
- [ ] T1.7 Sample service `auth-service` (Node.js)
- [ ] T1.8 `catalog/services.yaml` plus its JSON Schema and `scripts/validate_catalog.py`
- [ ] T1.9 Export reference `config.xml` from hand-made jobs — **needs a running Jenkins**

**Acceptance:** `verify.py --phase 1` confirms `jenkins-dev` answers with the bot token, both agents
online, controller executors 0, reference configs exist, the catalog validates, and both services'
tests pass. **Partially met** on 2026-09-29: the first three clauses pass live
(`python scripts/verify.py --phase 2` → ALL CHECKS PASSED, 12 Phase 1 checks). The reference-config,
catalog and sample-service clauses need T1.6 to T1.9.

## Phase 2: Plugin v2
Branch `phase-2-plugin`, stacked on the unmerged `phase-0-foundation`.

- [x] T2.1 Maven project on the current LTS baseline with the plugin BOM; `PipelinePriorityIT` and
      `MultiExecutorIT` written first, as failing tests — evidence:
      `mvn -B -ntp failsafe:integration-test -Dit.test='PipelinePriorityIT,MultiExecutorIT'` →
      `Tests run: 5, Failures: 3`, each failing on arrival order with the dispatch order printed:
      Pipeline `[pl-low, pl-high]`, multi-executor
      `[fs-low-1, fs-low-2, fs-low-3, fs-high-1, fs-high-2, fs-high-3]`, mixed
      `[fs-low, pl-high-mixed]`. The two passing tests are the ones that prove the platform
      assumption rather than the unbuilt feature: placeholder tasks resolve to their job in one
      `getOwnerTask()` hop with the priority property readable, and nothing is throttled yet.
- [x] T2.2 `OptimizerConfiguration` (global configuration and JCasC) — evidence: `mvn -B verify` →
      BUILD SUCCESS. Every report Appendix D default present; `@Symbol("dynamicQueueOptimizer")` for
      JCasC. `metricsBackendUrl` defaults to empty, not the report's URL (D-006). Mismatched weights
      warn rather than error, because the report's ablation varies them.
- [x] T2.3 `PriorityLevel`, `JobPriorityProperty` Jelly form and validation, M2 back-compat test —
      evidence: `mvn failsafe:integration-test -Dit.test=Milestone2CompatibilityIT` →
      `Tests run: 4, Failures: 0`. A Milestone 2 `config.xml` carrying `<priority>HIGH</priority>`
      loads as HIGH, round-trips to `<level>HIGH</level>` on save, and survives a reload.
      `doCheckDependsOn` rejects unknown names, self-references and cycles.
- [x] T2.4 `JobResolver` for freestyle, Maven and Pipeline queue items — evidence:
      `PipelinePriorityIT.placeholderTasksResolveToTheirJob` PASS. Both branches are exercised, and
      both are needed: see D-014.
- [x] T2.5 `UnionFind`, `KahnTopologicalSort`, `DependencyGraphService` — evidence:
      `mvn test -Dtest=UnionFindKahnTest` → `Tests run: 18, Failures: 0`.
- [x] T2.6 `BuildHistoryService`, `RecordedLabelAction`, `SimilarityEstimator` — evidence:
      `mvn -B verify` → BUILD SUCCESS; exercised end to end through the sorter by the green
      integration tests. `SimilarityEstimatorTest` covers the maths (T2.13).
- [x] T2.7 `PriorityScoreCalculator` and `AppendixCExampleTest` — evidence:
      `mvn test -Dtest=AppendixCExampleTest,ScoreComponentTest,AgingTest` →
      `Tests run: 62, Failures: 0`. The report's four scores reproduce at 0.667, 0.650, 0.650 and
      0.300, with 0.633 asserted as the pre-inheritance value too (D-004).
- [x] T2.8 `PriorityJobHeap` — evidence: `mvn -B verify` → BUILD SUCCESS. Ported from Milestone 2,
      keeping its item-id tie-break, and now sharing one comparator with the sorter so the two
      cannot disagree about order. `PriorityJobHeapTest` is ported and passing (T2.13).
- [x] T2.9 `DynamicQueueSorter` with the per-cycle cache — evidence:
      `mvn failsafe:integration-test -Dit.test='PipelinePriorityIT,MultiExecutorIT'` →
      `Tests run: 5, Failures: 0`. The three tests that failed on arrival order in T2.1 now pass.
      The heap is rebuilt on every pass including a cache hit; the cache key includes the current
      minute so aging refreshes at least once a minute.
- [x] T2.10 `DependencyGate` — evidence: `mvn -B verify` → `DependencyGateIT` 7/7 and
      `MissingUpstreamIT` 9/9 pass. A HIGH downstream job waits for its LOW upstream despite
      outranking it; a three-job chain runs in order; a missing upstream is reported unresolved and
      never blocks; a failed upstream does not block; a self-dependency and a runtime cycle do not
      deadlock.
- [x] T2.11 `QueueMetricsRecorder`, `RunMetricsRecorder`, `MetricsPublisher` — evidence:
      `mvn -B verify` → `ObserveOnlyIT` 6/6 pass, including that all four event kinds are recorded
      with the optimizer disabled and every event is labelled with which arm produced it. Publishing
      uses a bounded queue of 1000 on a daemon thread that drops and counts on overflow, so an
      unreachable backend can never block queue maintenance or leak memory.
- [x] T2.12 `DynamicQueueApi` (ranking and metrics endpoints) — evidence: `mvn -B verify` →
      `ApiJsonIT` 10/10 pass. All three endpoints answer, the ranking lists items in the order the
      sorter applied, every documented field and score-bar component is present, the metrics
      `Secret` is never rendered, a malformed `limit` is rejected with 400, and an anonymous caller
      receives no payload while an authenticated reader does.
- [x] T2.13 Every test in Part 4.3.10 exists and passes; SpotBugs clean — evidence:
      `mvn -B -ntp verify` → BUILD SUCCESS. All 17 required tests are present:
      `AppendixCExampleTest`, `ScoreComponentTest`, `AgingTest`, `UnionFindKahnTest`,
      `SimilarityEstimatorTest`, `PriorityJobHeapTest`, `SchedulerOverheadTest`,
      `FreestylePriorityIT`, `PipelinePriorityIT`, `MultiExecutorIT`, `DependencyGateIT`,
      `MissingUpstreamIT`, `DeclarativeOptionsIT`, `ObserveOnlyIT`, `CacheEvictionRegressionIT`,
      `ConfigAsCodeIT`, `ApiJsonIT`. Plus `Milestone2CompatibilityIT` and `QueueShapeProbeIT`,
      which are not required but earned their place.
- [x] T2.14 Build the `.hpi`, install it on `jenkins-dev`, add Phase 2 checks to `verify.py` —
      evidence: `docker compose build jenkins-dev && docker compose up -d` →
      `dynamic-queue-optimizer 2.0.0-SNAPSHOT` reports `active=true enabled=true` among 80 plugins;
      `python scripts/verify.py --phase 2` → "the ranking endpoint answers with the bot token" 200
      with weights 0.5/0.3/0.2 and aging 0.05 cap 0.15, and "the plugin health and metrics endpoints
      answer" both 200. A live end-to-end check created LOW, MEDIUM and HIGH freestyle jobs on the
      `linux` label, filled all four executors with blockers, and confirmed the plugin ranked them
      HIGH 0.600 / MEDIUM 0.400 / LOW 0.250 and dispatched them in that order despite worst-first
      arrival.

**Acceptance:** `mvn -B verify` passes; every test named in Part 4.3.10 exists and passes;
`GET /dynamic-queue/api/json` on `jenkins-dev` returns 200 with the bot token.
**MET in full**, 2026-09-29. The endpoint clause is now verified live; earlier detail: `mvn -B -ntp verify` →
BUILD SUCCESS. Every one of the 17 tests named in Part 4.3.10 exists and passes. The remaining
clause, `GET /dynamic-queue/api/json` returning 200 on `jenkins-dev` with the bot token, needs a
running container; the endpoint itself is covered by `ApiJsonIT` against `JenkinsRule`.

## Phase 3: Backend foundation
Branch `phase-3-backend`, stacked on the unmerged `phase-2-plugin`.

- [x] T3.1 Project skeleton with `uv`, settings, structured logging, error format, CORS and health
      endpoint — evidence: `uv run ruff check .` → All checks passed; `uv run ruff format --check .`
      → 23 files already formatted; `uv run mypy app` → no issues in 19 files (strict);
      `uv run pytest -m "not live and not e2e"` → 16 passed. `uv` 0.12.20 installed into
      `.venv-tools/` and Python 3.12.14 managed by it, per D-010.
- [x] T3.4 `JenkinsClient` with a fake implementation for tests — evidence: the same pytest run.
      `FakeJenkinsClient` keeps jobs, queue items and logs in memory and validates job names and
      `config.xml` well-formedness, so a template bug fails in the unit suite rather than only
      against a live Jenkins. The real client does basic auth with the bot token, a 10-second
      timeout, three attempts with jittered backoff on connection errors and 5xx, and one crumb
      retry on a 403.
- [ ] T3.2 SQLAlchemy models and Alembic migrations; seed scripts — models written, migrations and
      seeds still to do
- [ ] T3.3 Auth: login, refresh, logout, current user, role dependencies, rate limits
- [ ] T3.5 `GitClient` and `CatalogService`
- [ ] T3.6 `PluginClient` for the ranking endpoint and `POST /api/metrics` ingestion
- [ ] T3.7 `RunTracker` background worker and the WebSocket hub
- [ ] T3.8 Jobs, runs, queue, analytics and admin routers
- [x] T3.9 (part) The `/scriptText` guard test — evidence: `pytest tests/test_no_script_console.py`
      → 4 passed. Scans `backend/` and `experiment/`, proves it detects a planted call, and proves
      it does not flag prose. Integration tests and the Phase 3 `verify.py` checks remain.

**Acceptance:** all backend quality bars pass, `GET /api/health` reports database, Jenkins and LLM
provider on the Compose stack, and integration tests create, trigger and read one freestyle job and
one Pipeline job. **Two of three met** on 2026-09-29: quality bars pass, and `GET /api/health` on
the Compose stack returns `status: up` with database up, jenkins up (2.568.3, reached with the bot
token) and llm disabled (fake mode). The integration-test clause needs T3.8's routers, which are
not written yet.

## Decisions taken while building
- 2026-09-28 Build order deviates from Part 3: Phase 2 runs before Phase 1, because Docker is not
  installed and every Phase 2 test except T2.14 runs on JenkinsRule without it. Approved by the user.
- 2026-09-28 Jenkins LTS pinned to 2.568.3 (released 11 Sep 2026, tested on JDK 21 and 25). The
  report's Appendix E says 2.541.x and is wrong. Approved by the user.
- 2026-09-28 The job property field is renamed from M2's `priority` to `level`, because the
  `@Symbol("dynamicQueuePriority")` form published in both the report and Part 4.3.2 uses `level:`.
  An XStream field alias keeps old `config.xml` loading. Resolves a contradiction inside Part 4.3.2.
- 2026-09-28 `AppendixCExampleTest` asserts both the pre-inheritance base score (0.633 for
  `integration-tests-api`) and the effective score after group inheritance (0.650), because the
  report's table and Part 4.3.10 each state one of the two.
- 2026-09-28 `legacy/m2-poc/` is committed without `target/` build output. The result files that
  prove the staleness finding are kept; a rebuilt Jetty webapp has no evidential value.
- 2026-09-28 The backend will run on a `uv`-managed Python 3.12, not the system 3.14.2, because the
  report states 3.12 and some dependencies may not yet ship 3.14 wheels.

Details in `docs/decisions.md`.

- 2026-09-29 Maven Failsafe is now bound to the lifecycle in `plugin/pom.xml`. It was not, so
  `mvn verify` ran only the 67 surefire unit tests and silently skipped every `*IT` class while
  reporting BUILD SUCCESS. The phase's acceptance criterion is "`mvn -B verify` passes", so that
  criterion was passing vacuously.
- 2026-09-28 `verify.py`'s CI-workflow check falls back to a dependency-free structural scan when
  PyYAML is absent, instead of failing. PyPI's download host would not resolve from this machine, and
  a phase gate that fails because an unrelated package could not be downloaded is a broken gate. The
  full parse still runs wherever PyYAML is present, including CI, and the fallback message says which
  path ran.

## Known gaps
- Docker-gated work is untested on this machine: all of Phase 1, T2.14, and every acceptance check
  from Phase 3 onward that needs a live Jenkins or PostgreSQL. Tracked under Needs human.
- `plugin-results-run3.json` is a Milestone 2 outlier whose HIGH-band wait (353.34 s) is worse than
  the baseline (271.5 s). It is evidence of M2 known problem 6, the silent FIFO degradation, and is
  written up in `docs/m2-baseline.md` rather than discarded. `CacheEvictionRegressionIT` is the guard
  against it recurring.
- `legacy/experiment/results/baseline-results.json` holds 31 job rows against a 30-job spec, and the
  legacy `analyze.py` silently discards the extra row. Noted in `docs/m2-baseline.md`.
- The report's Word source was not provided, so report changes are tracked as a checklist.
- PyYAML is not installed locally and PyPI's download host does not resolve from this machine, so the
  CI-workflow check runs its structural fallback rather than a full YAML parse. CI installs PyYAML and
  runs the full parse.
- The JCasC floating-point import defect (D-017) blocks configuring the experiment's aging-ablation
  arm from YAML. Root cause inside JCasC not identified; ruled out the YAML scalar form,
  integer-valued floats, the `doCheck*` validators, boxing as `Double`, and the JVM locale.
- `docs/versions.md` still has `pending` rows for every plugin, backend and frontend dependency. Each
  is filled by the task that pins it, against the official source, per rule 1.4.

- 2026-09-28 The job property field is `level`, with an XStream/`readResolve` fallback onto M2's
  `priority`, so old job configurations still load. Decided in D-005, implemented in T2.1.
- 2026-09-28 Ordering assertions measure queue dispatch order via a `QueueListener`, never
  `Run#getStartTimeInMillis()`. A Pipeline run starts before its node block is ever queued, so start
  time measures submission order for Pipeline jobs. See D-015.

- 2026-09-29 The similarity threshold filters weakly on a homogeneous controller: two
  unparameterised builds sharing an agent label score 0.5 before their names are compared, clearing
  the 0.35 threshold. That is the experiment's exact workload. Formula kept as specified; the
  consequence is recorded in D-016 and queued as a report correction.

## Session log
- 2026-09-28 Read BUILD_PROMPT.md in full. Explored `legacy/m2-poc/` (plugin sources, experiment
  harness, result files) and the report PDF (Chapter 6 algorithms, Chapter 12, Appendices B to F).
  Confirmed M2 known problems 1, 2, 3, 6 and 7 directly in the code and data. Found eleven conflicts
  across BUILD_PROMPT.md, the report and the legacy code, including one contradiction internal to
  Part 4.3.2. Verified the current Jenkins LTS against jenkins.io. Wrote PLAN.md, CLAUDE.md and this
  file.
- 2026-09-28 Prepared the repository, which the human setup steps had never done: initialised Git,
  moved the M2 folders into `legacy/m2-poc/` and the report into `docs/report/`, wrote the root
  configuration files and the Appendix A guard rails, committed and tagged `m2-final`. Caught two
  problems while staging: Jenkins credential stores were about to be committed, and the repo-wide
  `text=auto eol=lf` rule would have rewritten the frozen copy. Both fixed before the first commit.
  The frozen copy went from 328 MB to 2 MB by excluding regenerable runtime output.
  Then completed Phase 0: T0.1 to T0.6 all checked, `verify.py --phase 0` prints ALL CHECKS PASSED.
  Next: open the Phase 0 pull request (needs `gh`), then start Phase 2 with the failing-test spike —
  `PipelinePriorityIT` and `MultiExecutorIT` before any production code.
- 2026-09-28 Phase 2 started on `phase-2-plugin`. T2.1 done: Maven project on Jenkins LTS 2.568.3
  with parent POM 6.2236 and plugin BOM `bom-2.568.x`, all three checked against
  repo.jenkins-ci.org before pinning. The failing-test spike paid for itself twice. First, the queue
  does not have the shape the specification describes: a Pipeline job passes through it twice, once
  as a flyweight task where `item.task` IS a `Job`, then as a placeholder where it is not, so the
  first version of the test measured the wrong window (D-014, proven by `QueueShapeProbeIT`).
  Second, comparing run start times is invalid for Pipeline, because a Pipeline run starts before
  its node block is queued; that made one test pass for no reason and would have made another fail
  forever however correct the sorter became (D-015). Both fixed before any production code was
  written, which is the entire point of doing the spike first. Next: T2.2 to T2.8, the pure-logic
  classes, then T2.9 turns these tests green.
