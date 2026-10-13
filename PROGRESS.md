# Progress

Updated: 2026-10-14 · Current phase: 6 (T6.1 done and awaiting approval; T6.2 next) ·
Branch: phase-6-frontend

## Needs human
- [x] **Create the two sample-service GitHub repositories**, push them, create the
      `demo/failing-tests` branch, and put the URLs in `catalog/services.yaml`. Blocks T1.8's
      `git ls-remote` check and the Phase 5 failing-branch acceptance test.
      Done, checked 2026-10-11 with `git ls-remote`. `haiderali-dev/payment-service` has `main`
      998844b and `demo/failing-tests` da997c8. `haiderali-dev/auth-service` has `main` 6413c6f
      and `demo/failing-tests` d4c4560. `catalog/services.yaml` points at both.
- [ ] **Resolve or work around the JCasC floating-point defect (D-017).** Importing a YAML file
      silently ignores `weightUrgency`, `weightDependency`, `weightExecutionTime`,
      `agingBonusPerInterval`, `agingCap`, `similarityThreshold` and `recencyLambdaPerDay`, while
      every other field applies. `optimizerEnabled` works, so the main baseline-versus-optimized
      comparison is unaffected and Table 12.1 stays reproducible from YAML. The **aging-ablation arm**
      of the Part 4.8.2 matrix varies `agingBonusPerInterval` and `agingCap`, so it cannot be driven
      from JCasC and needs another route (the global configuration form, or a decision to drop that
      arm). `ConfigAsCodeIT.floatingPointAttributesAreNotAppliedKnownDefect` pins the current
      behaviour and will fail loudly when it is fixed.
- [x] **Install `gh`, or open pull requests by hand.** Not blocking; each phase still ends on its
      own branch. Done, checked 2026-10-11: `gh` 2.102.0 is logged in as `haiderali-dev`. PRs
      #5 to #9 were opened with it. Open each phase PR against `main`, never against the previous
      phase branch: stacking them is what kept Phases 2 to 4 out of `main` (PRs #2 to #4).
- [x] **Review and merge the Phase 5 PR (#10) into `main`.** Done 2026-10-13, at the user's
      request: merged as merge commit `8da58b9` (`gh pr merge 10 --merge`, the method PR #9 used,
      so every commit the Phase 5 records cite is in `main`'s history). CI on `main` passed:
      Backend, Plugin and the phase checks. Frontend was skipped, as designed until Phase 6 adds
      it.
- [x] **Decide on a checkout retry for transient DNS failures** (Known gaps, "Agent DNS").
      Decided on 2026-10-13: `scmCheckoutRetryCount: 2` under `jenkins:` in
      `jenkins/casc/dev.yaml` (D-050).
      - **What it retries:** every SCM checkout failure, not only DNS. Two more attempts,
        10 seconds apart.
      - **Accepted:** JCasC's dry-run check accepted it, and refused a misspelled control.
      - **Applied:** by restarting jenkins-dev, which was fully up in 8 s with no JCasC error.
        `config.xml` holds the value.
      - **Seen working on both job types:** freestyle and a Pipeline's `checkout` step each retried
        twice. So the separate Pipeline `retry` step proposed earlier is not needed.
      - **Checks after applying it:**
        - `verify.py --phase 1`: ALL CHECKS PASSED;
        - every integration test: 31 passed, 1 skipped, as before;
        - the full `verify.py --phase 5`: ALL CHECKS PASSED, 71 of 71.
      - **Not yet proven:** that it cures the flakiness. No build in that gate run met a DNS error,
        so none needed a retry.
- [ ] **Re-run the Phase 5 security review independently.** The reviewer agent stopped on an
      account usage limit, so `docs/security-review-phase-5.md` was written by the agent that
      wrote the code.
- [ ] **Approve `frontend/DESIGN.md`.** T6.1 wrote it on 2026-10-13. Its section 10 lists the
      choices most worth questioning, and D-052 records how its palette reads 4.7.2's "4 to 6
      named hex values". No screen (T6.3 onward) is built before approval. T6.2's plumbing does
      not wait for it.
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
- [x] T1.10 Phase 1 checks in `verify.py` — 17 checks, **all passing**: 9 offline, 3 live against
      the running controller, and 5 covering the sample services, the catalog and the reference
      configs.
- [x] T1.4 `scripts/bootstrap.py`: SSH keys, waiting for Jenkins, creating the bot API token —
      evidence: `python scripts/bootstrap.py` → generated an ed25519 pair, waited for the
      controller, minted a 34-character token and verified the bot can authenticate with it.
      No script console: the token comes from
      `/user/<id>/descriptorByName/jenkins.security.ApiTokenProperty/generateNewToken`.
- [x] T1.6 Sample service `payment-service` (Python) — evidence: `pytest tests/test_unit.py` →
      7 passed in 9.01s and `pytest tests/test_integration.py` → 5 passed in 20.89s, matching the
      catalog's approx_seconds of 8 and 20; `ruff check app tests` → All checks passed. FastAPI with
      `/health` and `/version` (the latter returning the commit baked in at image build), build,
      test, lint and security-scan scripts, a Dockerfile and `deploy.sh staging` on port 9001.
- [x] T1.7 Sample service `auth-service` (Node.js) — evidence: `node --test test/*.test.js` →
      7 passed in 6.11s, matching approx_seconds 6. Node standard library only, `/health`,
      `/version`, `/login`, `/verify`, Dockerfile and `deploy.sh staging` on port 9002. Deliberately
      the shorter service so the execution-time factor T has a real spread to normalise over.
- [x] T1.8 `catalog/services.yaml` plus its JSON Schema and `scripts/validate_catalog.py` —
      evidence: `python scripts/validate_catalog.py` → schema valid, production absent, both agent
      labels exist on the live controller. The two repo-reachability checks fail because the GitHub
      repositories do not exist yet (Needs human). The schema rejects `production` in
      `allowed_environments` outright, so it cannot be enabled by editing the catalog alone.
- [x] T1.9 Export reference `config.xml` from hand-made jobs — evidence:
      `python scripts/export_reference_configs.py` created one freestyle and one Pipeline job
      through the REST API on the live `jenkins-dev`, exported what Jenkins stored, and removed
      them. `verify.py --phase 1` → "reference configs were exported from Jenkins" PASS. The
      exports carry Jenkins' own `plugin="name@version"` stamps
      (`dynamic-queue-optimizer@2.0.0-SNAPSHOT`, `git@5.10.1`, `timestamper@1.30`,
      `ws-cleanup@0.49`), which is the evidence they were produced by Jenkins rather than written
      by hand — exactly what rule 1.4 requires.

**Acceptance:** `verify.py --phase 1` confirms `jenkins-dev` answers with the bot token, both agents
online, controller executors 0, reference configs exist, the catalog validates, and both services'
tests pass. **MET** on 2026-09-29: `python scripts/verify.py --phase 2` → ALL CHECKS PASSED,
34 checks across phases 0, 1 and 2. The one outstanding item is outside the check: the two GitHub
repositories do not exist, so `validate_catalog.py` reports both `git ls-remote` probes as failing
until a human creates and pushes them.

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
- [x] T3.2 SQLAlchemy models and Alembic migrations for every table in Part 4.4.3; seed scripts for
      the admin user and the catalog — evidence: `alembic upgrade head` against the Compose
      PostgreSQL created all 14 tables (`\dt` shows them plus `alembic_version`);
      `alembic downgrade base` then `upgrade head` proved the migration reversible; a second
      `--autogenerate` produced an empty upgrade/downgrade, proving the models and the migration
      agree with no drift. `python -m app.db.seed` run twice, in the container, reported
      `2 created, 0 updated` then `0 created, 0 updated`. `verify.py --phase 3` → 6 Phase 3 checks
      pass; `pytest` → 30 passed, 1 skipped (the `integration`-marked live upgrade).
- [x] T3.3 Auth: login, refresh, logout, current user, role dependencies, rate limits — evidence:
      `uv run pytest -m "not live and not e2e"` → 67 passed, 1 skipped (37 of them auth tests);
      `ruff check`, `ruff format --check` and `mypy app` (strict, 24 files) all clean;
      `verify.py --phase 3` → 8 Phase 3 checks pass, including two new ones for the endpoint
      surface and the rate limits. `POST /api/auth/login`, `/refresh`, `/logout` and `GET /api/me`
      confirmed registered in the OpenAPI schema. Two real defects were found and fixed rather
      than asserted around:
      * failed sign-ins were audited into the session and then rolled back with the refusal, so
        the trail held successes only — `get_db` rolls back on any exception. Denials now commit
        their entry before raising (D-022). Verified by reverting the fix: both the test and the
        new gate fail.
      * the role-guard test returned 422 instead of 403 because it imported `DevOpsUser` inside
        the test function; under postponed annotations FastAPI resolves endpoint hints against
        module globals, so the name was unresolvable and `user` was read as a query parameter.
        The guard itself was correct; the import moved to module scope. No assertion changed.
      Sign-in returns one generic error whether the account is absent or the password is wrong,
      and hashes even when there is no user, so the endpoint is not an account-existence oracle.
      Refresh rotates and revokes the old token (D-021); deactivating an account ends its session
      on the next request because the user is re-read each time rather than trusted from the token.
- [x] T3.5 `GitClient` and `CatalogService` — evidence: `uv run pytest -m "not live and not e2e"`
      → 130 passed, 1 skipped (22 catalog tests, 41 git tests); `ruff check`, `ruff format --check`
      and `mypy app` (strict, 26 files) all clean; `verify.py --phase 3` → 10 checks pass, two of
      them new. `python -m app.db.seed --catalog` in the container → `0 created, 0 updated`, so the
      refactor kept the seed idempotent. `pytest -m integration tests/test_git.py` resolved a real
      remote: 7 branches, `master` → a 40-character sha, and a bogus branch correctly absent.
      * `app/services/catalog.py` is now the only parser of `catalog/services.yaml`; `seed.py` used
        to parse it separately, which let the seed accept a document the API would reject (D-025).
        It validates against the JSON Schema on every load and reloads on mtime, keeping the last
        good copy when an edit is broken.
      * `app/services/git.py` resolves refs with `git ls-remote` and never clones (D-024). Refs are
        pattern-checked *before* the call, because an argument list is not sufficient on its own:
        git reads a leading `-` as an option and `--upload-pack=<command>` makes ls-remote execute
        it, which is code execution through an argument no shell sees (D-023).
      One real bug found and fixed while checking against a live remote: the subprocess ran with a
      minimal environment, and dropping `SystemRoot` broke DNS on Windows — every fetch failed with
      `getaddrinfo() thread failed to start`. `scripts/validate_catalog.py` had the identical bug.
      A test now asserts nothing is dropped from the inherited environment; reverting the fix fails
      it.
      Both new `verify.py` gates were negative-tested: loosening `REF_PATTERN` to allow a leading
      dash fails the ref gate, and reintroducing a second `yaml.safe_load` fails the loader gate.
- [x] T3.6 `PluginClient` for the ranking endpoint and `POST /api/metrics` ingestion — evidence:
      `uv run python -m pytest -m "not live and not e2e"` → 179 passed, 1 skipped (25 metrics
      tests, 24 plugin-client tests); `ruff`, `ruff format --check` and `mypy app` (strict, 29
      files) clean; `cd plugin && mvn -B verify` → 65 integration tests, BUILD SUCCESS;
      `verify.py --phase 0/1/2/3` → all four pass, with four new Phase 3 checks.
      **Three real defects found, two of them pre-existing and invisible until now:**
      * **The metrics pipeline had never worked at all** (D-026). Java's `HttpClient` defaults to
        HTTP/2 and negotiates it over cleartext with `Upgrade: h2c`, which uvicorn does not
        implement — it logged "Unsupported upgrade request" and returned **422 for every single
        event**. This was undetectable before T3.6 because `metricsBackendUrl` defaults to empty
        (D-006), so the publisher returned early and never posted. Fixed by pinning `HTTP_1_1` in
        `MetricsPublisher`, guarded by `MetricsPublisherHttpVersionTest`.
      * **A rebuilt plugin never reached the running controller** (D-028). Jenkins seeds
        `ref/plugins` only when a plugin is absent or the image is *newer*, and the plugin is
        always `2.0.0-SNAPSHOT`, so a persistent home kept the `.hpi` from its first boot with a
        `.pinned` marker beside it. The D-026 fix appeared not to work for this reason: the volume
        held 88,217 bytes while the image held 88,346. `install-plugin-under-test.sh` now wraps the
        stock entrypoint and replaces that one plugin on every start.
      * `parse_health` read `droppedMetrics`, but the endpoint sends `droppedMetricCount`, so the
        backend reported **zero dropped events however many were lost** — the one number whose
        purpose is to say data went missing. Found by reading the live endpoint instead of the
        specification's prose; the health test is now built from a recorded live payload.
      Also fixed: `store = pending or _pending` silently discarded the injected store, because the
      class defines `__len__` and an *empty* store is therefore falsy; and the process-wide state
      reset moved into `conftest.py`, after `test_auth`'s rate-limit tests exhausted the five-a-
      minute login bucket for the whole suite and a later file's sign-in got an unexplained 429
      that reproduced only in a full run.
      **Verified end to end on the live stack:** one triggered build produced `QUEUE_ENTERED`,
      `QUEUE_LEFT`, `BUILD_STARTED` and `BUILD_COMPLETED` with `publishedMetricCount` 4,
      `failedMetricCount` 0, `droppedMetricCount` 0, and four 202s in the backend log. A new
      `verify.py` check reads those counters, so a refusing backend fails the gate rather than
      quietly losing experiment data.
- [x] T3.7 `RunTracker` background worker and the WebSocket hub — evidence:
      `uv run python -m pytest -m "not live and not e2e"` → 229 passed, 1 skipped (27 ws tests,
      23 tracker tests); `ruff`, `ruff format --check` and `mypy app` (strict, 32 files) clean;
      `verify.py --phase 3` → all pass, with four new checks.
      * `app/ws/hub.py` fans out to connected clients on four topics. `publish` is synchronous and
        drops the *oldest* event on a full 256-deep queue, because the tracker publishes from
        inside its tick: a browser on a bad connection must not become backpressure on recording
        run history (D-030).
      * `app/ws/routes.py` authenticates with the first frame rather than `?token=` — a browser
        cannot set WebSocket headers, and a query string reaches proxy logs, browser history and
        `Referer` (D-029). The socket is accepted first so a refusal is a readable close code;
        1008 means sign in again, 1011 retry. The reason never says *why* a token failed.
      * `app/services/tracker.py` polls every 3 s, maps queue item ids to build numbers, upserts
        `job_runs` and publishes events. It fills `queue_wait_ms` only when unset, so a polled
        estimate can never overwrite the plugin's in-queue measurement (D-031).
      Two real bugs found while testing, both on paths that exist to prevent failures:
      * the `/ws` endpoint called `get_settings_dep()` directly, bypassing `dependency_overrides`
        and falling back to a bare `Settings()` that fails validation — every endpoint test failed
        on it. FastAPI supports `Depends` on WebSocket routes; it uses that now.
      * `logger.exception("tracker_publish_failed", event=...)` raised `TypeError`, because
        structlog reserves `event` for the message. The handler that exists so a hub fault cannot
        crash a tick was itself crashing the tick. Caught by the test that breaks the hub on purpose.
      The hub-blocking `verify.py` check also had a bug of its own: it matched the word "await" in
      `publish`'s docstring, which explains why there isn't one. It is line-anchored now and was
      negative-tested by making `publish` actually await.
- [x] T3.8 Jobs, runs, queue, analytics and admin routers — evidence:
      `uv run python -m pytest -m "not live and not e2e"` → 283 passed, 1 skipped (54 router
      tests); `ruff`, `ruff format --check` and `mypy app` (strict, 38 files) clean;
      `verify.py --phase 3` → all pass, three checks new. 25 endpoints registered; every one
      exercised against the live Compose stack as the seeded admin, including `GET /api/queue`
      reading the real plugin (`available=true`, weights 0.5/0.3/0.2) and
      `GET /api/services/payment-service/branches` degrading to `available=false` for the
      repositories that are not pushed yet.
      Decisions taken rather than guessed:
      * cancelling needs DevOps. 4.5.5 does not name a role for it, but it says a Developer may
        not cancel a running chain and an Admin may, so stopping someone else's build is not a
        Developer action. The guard is the narrowest reading of that table.
      * `GET /api/queue` answers 200 with `available: false` when the plugin cannot be read.
        `jenkins-baseline` runs without it deliberately, and that controller is the baseline arm
        of the experiment; a 500 there would look like a broken backend.
      * `ServiceResponse` omits every shell command. They are the one security-relevant part of
        the catalog, nothing in the UI runs them, and serving them would widen what a stolen
        read-only token is worth. A test asserts no command string appears in the payload.
      * policy settings are read-only and the catalog has no write endpoint (D-032): 4.4.3 has no
        table for policy, and an API that could rewrite `services.yaml` would move the only source
        of shell commands out of version control.
      * analytics returns null, never zero, where nothing was measured — a 0 ms queue wait is a
        build that started at once, and a chart drawing the two alike would be lying. The success
        rate excludes runs still building, so reliability does not appear to drop when a build
        starts.
      The new role-guard gate was negative-tested by downgrading `cancel` to any signed-in user;
      it fails with `found no role guard`.
- [x] T3.9 Integration tests and the Phase 3 `verify.py` checks — evidence:
      `uv run --no-sync python -m pytest tests/test_integration_jenkins.py -m integration` →
      8 passed against the live `jenkins-dev`; `verify.py --phase 3` → ALL CHECKS PASSED, which
      now includes running that suite; the fast bar is
      `pytest -m "not live and not e2e and not integration"` → 282 passed, 10 deselected.
      The `/scriptText` guard test (4 passed) scans `backend/` and `experiment/`, proves it
      detects a planted call, and proves it does not flag prose.
      **Four defects found by running against the real controller:**
      * `list_labels()` queried `/api/json`, which reports only the controller's own labels and has
        no `nodes` field — so it returned `['built-in', 'controller']` while both agents were
        online carrying `linux`. `validate_catalog.py` had the identical bug and its fix had never
        reached the client. Now `/computer/api/json`, excluding offline nodes.
      * all three `jenkins/reference-configs/*.xml` were **invalid XML**: the exporter wrote its
        provenance comment above the `<?xml?>` declaration (D-035). Rule 1.4 makes those files the
        source of every template, Phase 5's golden-file tests parse them, and
        `FakeJenkinsClient` validates well-formedness — so this would have broken all three.
        Nothing had parsed them until now.
      * the bot has no `Job/Delete` and must not (D-033): cleanup attempts returned 403. The
        permission stays off, `delete_job` now documents that it 403s as configured, and the tests
        recreate their jobs instead.
      * a Pipeline job cannot be triggered with parameters until a build has run, and pushing its
        config.xml again **wipes** the parameters a run registered (D-034). So Phase 5's Pipeline
        generator must write a `ParametersDefinitionProperty` into config.xml — that is now the
        only workable option, not one of two.
      Also fixed: the fast quality bar was silently running the integration tests, triggering real
      builds and taking a minute, although the marker says "Opt in with `-m integration`". The bar
      excludes them and a separate acceptance check runs them, reporting an all-skip as a failure —
      an acceptance clause that passes because it could not run is worse than no check. Every
      `uv run` in `verify.py` now passes `--no-sync`, after an unrelated `pyproject.toml` edit made
      every bar fail with "Application Control policy has blocked this file" rather than a lint
      error.

**Acceptance:** all backend quality bars pass, `GET /api/health` reports database, Jenkins and LLM
provider on the Compose stack, and integration tests create, trigger and read one freestyle job and
one Pipeline job. **All three met** on 2026-10-07: `verify.py --phase 3` passes every check,
including the one that runs the integration suite (8 passed against the live controller). Earlier
note, kept for the record — **two of three** on 2026-09-29: quality bars pass, and `GET /api/health` on
the Compose stack returns `status: up` with database up, jenkins up (2.568.3, reached with the bot
token) and llm disabled (fake mode). The integration-test clause needed T3.8's routers, which is
what closed it.

**Follow-up 2026-10-11, flaky Pipeline integration test (D-039).**
`test_a_pipeline_job_is_created_triggered_and_read` failed about once in 20 runs. The cause is a
real race: a Pipeline reports `building: false` before it writes `Finished: SUCCESS`. The same
race could cut the last line off a Pipeline log in `GET /api/runs/{id}/log`. Both now wait on
Jenkins's `X-More-Data`.

Evidence, all run on 2026-10-11:
- A 50 ms stress probe hit the race window 3 times in 40 builds. Every time, the log was complete
  once read.
- The integration file passed 40/40 runs in a row.
- The offline suite passed: 1159 passed, 6 of them new.
- `verify.py --phase 4` passed.

## Phase 4: AI core

- [x] T4.1 `LLMProvider` with `GroqProvider`, `ReplayProvider` and `FakeProvider`; fallback chain;
      token accounting; response cache — evidence: `uv run --no-sync python -m pytest -m "not live
      and not e2e and not integration"` → 353 passed (40 provider tests, 31 chain/quota/cache
      tests); `ruff`, `ruff format --check` and `mypy app` (strict, 47 files) clean. Migration
      `8c2f4d1e7a90` verified on the Compose PostgreSQL: upgrade, downgrade, re-upgrade, and an
      autogenerate that came back empty (D-036).
      Written against the live API, not assumptions: one call to `openai/gpt-oss-120b` on
      2026-10-09 confirmed strict JSON schemas (including nullable enums) are honoured, that usage
      counts reasoning tokens inside `completion_tokens`, and that every response carries
      `x-ratelimit-*` headers — `limit-requests` 1000 and `limit-tokens` 8000, matching 4.5.1.
      The quota tracker therefore trusts the server's headers over its own counters.
      `GroqProvider` is tested through the real `openai` SDK (3.27.0) over a stubbed `httpx2`
      transport, so the tests pin what the SDK actually raises for a 429 or a 503 rather than what
      a mock was told to raise. The SDK's own retries are off (`max_retries=0`): left on, they
      would double-count against the quota and hide the 429s the chain needs to see.
      Acceptance clause pinned by `test_with_groq_unreachable_the_rule_parser_answers_with_ai_fallback`:
      every model unreachable, three attempts each, rule parser answers, `ai_fallback` true.
      Fixed along the way: replay fixture reads and writes ran synchronously inside async methods,
      which would stall the server's event loop; they go through `asyncio.to_thread` now.
- [x] T4.2 Dynamic intent schema builder — evidence: `pytest` → 369 passed (16 schema tests);
      `ruff`, `ruff format --check`, `mypy app` (48 files) clean. Verified live before the tests
      were written: Groq's strict mode accepted the full schema both with and without the catalog
      enums, and `gpt-oss-120b` parsed 4.6.5's hotfix command correctly under each (DEPLOY,
      auth-service, staging, HIGH, justification captured; ~1 s, ~520 prompt tokens).
      Catalog services and suites are injected as enums, so strict decoding *cannot* emit an
      invented service; the validator checks again in code as the second defence. `environment`
      is deliberately not narrowed to the catalog's allowed environments: `production` has to stay
      expressible, or the decoder would force a production request into staging — the silent
      rewrite Appendix E forbids. `include_enums=False` implements 4.9's "no catalog enums"
      ablation and is tested to change nothing else. `catalog_fingerprint` keys the response cache
      so an answer built against an older catalog is never served.
- [x] T4.3 Versioned prompts in `backend/app/ai/prompts/`, starting from Appendix E — evidence:
      `pytest tests/test_ai_prompts.py` → 19 passed; `ruff`, `mypy app` (49 files) clean.
      `intent_v1.md` is Appendix E verbatim plus 12 few-shot examples (4.5.6 asks for 8 to 12)
      covering clarification, refusal, multi-stage, both injection styles and unsupported. The
      version stored on every call is `intent_v1@<sha256 prefix>` — currently
      `intent_v1@9457338e` — so an edit without a rename is still distinguishable in `llm_calls`.
      The examples deliberately do **not** reuse 4.6.5's wording: those commands will be in the
      evaluation set, and an example matching an eval item would let the model copy the answer.
      A test enforces it.
      **Live smoke run** through the real `ModelChain`, on ten fresh phrasings that are neither
      few-shots nor 4.6.5 commands (so it is not tuning against evaluation material): 9 of 10
      correct — branch and suite extraction, HIGH urgency with the user's own justification,
      production parsed faithfully rather than rewritten, a quoted "deploy to prod" inside a commit
      message ignored, STATUS, CANCEL, UNSUPPORTED for a joke.
      **One real failure, deliberately not fixed in the prompt:** `"deploy it"` → `UNSUPPORTED` at
      0.9 confidence, where DEPLOY with a null service (one clarifying question) is right. Appendix
      E says to tune against the development split only, and "deploy it" is exactly what a human
      would put in the evaluation's missing-field category, so editing the prompt for it now could
      contaminate that item. Handled in T4.5's parser logic instead, where it can be measured
      separately.
      **Measured cost:** ~1,700 prompt tokens per request with the 12 examples (~900 of them the
      examples). Against 8,000 tokens a minute, the fifth request in any minute waited ~58 s in
      this run; interactively the chain caps waits at 10 s, so that request falls to the 20b model.
      This is what 4.9's "no few-shot examples" ablation will put a price on.
- [x] T4.4 `RuleBasedParser` — evidence: `pytest` → 435 passed (47 rule-parser tests); `ruff`,
      `ruff format --check`, `mypy app` (50 files) clean. All nine rows of 4.6.5's command table
      parse as the specification expects, including `"run the tests"` with service and suite both
      null so both get asked, production parsed faithfully, and the injection row parsing the
      deploy around the instruction. It applies Appendix E's rules in code: quoted text, code spans
      and commit-message tails are stripped before any keyword is matched; nothing outside the
      catalog is produced; a bare action word (`"deploy it"`) is that action with null fields rather
      than UNSUPPORTED — the exact case the model got wrong in T4.3's smoke run. Confidence is
      capped at 0.85 so a rules answer is always distinguishable from a model's.
      Three heuristics were cut before testing because they were wrong in ways the tests would not
      have caught: single quotes as quote marks (an apostrophe in "auth-service's" would have
      deleted the service name), `live` as production, and `make` as build ("make a coffee").
- [x] T4.5 `IntentParser` orchestration, `IntentValidator`, `ClarificationService` — evidence:
      `pytest` → 1110 passed (47 guard/validator/clarifier tests, 24 parser tests); `ruff`,
      `ruff format --check`, `mypy app` (strict, 56 files) clean.
      **All nine rows of 4.6.5 run through the whole pipeline** — guard, chain, validator, policy,
      clarification — and each produces the behaviour the table specifies: builds and tests READY
      with branch and suite resolved, `"run the tests"` asking service then suite over two rounds,
      the hotfix READY at HIGH with its justification, "latest" resolved to the tip SHA, production
      REFUSED, the status question READY without generating, the rerun READY, and the injection
      REFUSED with the attempt logged. The acceptance clause holds through the real factory: Groq
      unreachable → rules answer → `ai_fallback: true`, and `LLM_MODE=live` with no key degrades
      the same way instead of failing to start.
      `interpret` (steps 1-5) touches no database and `record` (step 6) writes `nl_commands`, one
      `llm_calls` row per attempt — failed ones included, each with `prompt_version` and `outcome`
      — and the audit entries. Ordering decisions recorded as D-037: policy before clarification,
      policy audit only when policy decided, an unreachable remote warns instead of blocking, and a
      narrow, separately measurable correction for the model's false UNSUPPORTED on "deploy it".
      The guard strips Unicode `Cc`/`Cf` characters, not just ASCII controls: bidirectional
      overrides can make a message display differently from what the model reads.
- [x] T4.6 `PolicyService` with table-driven tests — evidence: `pytest tests/test_ai_policy.py` →
      604 passed; full suite 1039 passed; `ruff`, `mypy app` (51 files) clean. Built ahead of T4.5
      because the parser's step 5 *is* this layer.
      4.5.5's rows are tested as a table, and then the full product — 3 roles × 8 actions ×
      3 environments × 4 urgencies × 2 justification states, 576 cases — is checked against
      invariants taken from 4.5.5's *wording* rather than recomputed by the same logic as the code,
      which would only prove the code agrees with itself. Mutation-tested: letting admins deploy to
      production fails exactly 17 cases — the explicit admin row plus the 16 sweep cases for
      admin × {DEPLOY, BUILD_TEST_DEPLOY} × production — so the sweep engages where it should.
      The service is pure (context in, decision and audit events out), so no database is needed
      to test it. Every rule is evaluated even after one refuses, so the user sees every reason at
      once. Production is refused only for deploy actions: building "for production" deploys
      nothing.
      One bug caught before it existed: every HIGH request writes the audit entry 4.4.3 requires,
      but if the daily quota counted those, a developer asking five times without a reason would
      spend the quota without ever getting HIGH. The entry now records `granted`, decided after all
      rules have run, and only granted ones count.
- [x] T4.7 `eval/` package skeleton — evidence: `uv run --project backend python -m eval run
      --parser rules --file eval/datasets/sample.jsonl` writes
      `eval/results/sample__rules/metrics.json` (Phase 4 acceptance clause 3); `pytest` → 1153
      passed (43 eval tests); `ruff` and strict `mypy` now run over `eval/` too, via an
      `eval/ruff.toml` that extends the backend's config.
      **Integrity rules, enforced in code rather than trusted:** the 30 drafted items (4.9's
      ceiling, in its category mix) are all `needs_review: true`, and the loader *rejects* a
      Claude Code draft that claims to be reviewed — so the acceptance run honestly scores zero
      items, with every metric `null` and a note saying nothing was measured, rather than 0.
      `--include-unreviewed` exercises the pipeline end to end but stamps the run
      `for_reporting: false`, and `python -m eval report` lists such runs only under "Not
      reportable". A model run uses a single-model chain, so a model failure is recorded as an
      error — never scored with the rule parser's fallback answer in its place. The runner checks
      dataset items against the prompt's few-shot examples and refuses to run on an overlap.
      **Quota safety (4.9):** a disk cache by prompt hash in the replay-fixture format (so a
      finished run doubles as a fixture set), 25 live calls a minute, per-item writes so an
      interrupted run resumes, and a clean stop at a model's daily budget with progress saved.
      **Methodology fix found by a test:** answers served from cache were being averaged into the
      model's latency p50/p95; they are excluded from latency now, while still counted elsewhere.
      Smoke run of the rule baseline over the unreviewed drafts — *not for reporting* — action
      0.90, behaviour 0.90, refusal 1.00; its misses are in typos and ambiguity, as a baseline's
      should be, and the rules were deliberately not tuned to those drafts.
- [x] T4.8 One opt-in live test and Phase 4 checks in `verify.py` — evidence:
      `uv run python -m pytest -m live tests/test_ai_live.py` → 1 passed against the real
      `gpt-oss-120b`: the real factory in live mode, the real prompt and strict schema, a correct
      BUILD / payment-service / release/2.1 parse, READY, recorded as an `ok` call with real token
      counts. The default selection deselects it. `verify.py --phase 4` → ALL CHECKS PASSED, 66
      checks across phases 0-4, ten of them new: the AI modules, the prompt's 8-12 examples and
      Appendix E rules, that neither the prompt context nor the schema ever reads a shell command,
      that the SDK's retries stay off, the `llm_calls` migration, the draft cap, and the three
      acceptance clauses each *run* rather than inferred. `eval/` is now linted and strictly
      type-checked by the gate.
      **A gate bug found and fixed:** the first `--phase 4` run failed one check and every rerun
      passed. Not flaky — state-dependent. Confirmed by restarting `jenkins-dev`: the Phase 3 check
      "a live plugin event reaches the backend" needs the plugin to have published something, the
      plugin's counters reset on restart, and the check ran *before* the integration check that
      triggers builds — so it passed only when another check had run first. It now triggers a build
      itself when nothing has been published. Re-verified against the state that broke it: fresh
      controller, first run, `4 published, 0 failed, 0 dropped`, gate green.

**Acceptance:** AI unit and policy tests pass; with Groq unreachable, the rule parser answers and the
response carries `ai_fallback: true`; `python -m eval run --parser rules --file
eval/datasets/sample.jsonl` writes a metrics file. **All three met** on 2026-10-09, each checked
by running it: 828 AI tests pass across eight files; the fallback tests pass through the real factory
(Groq unreachable, and live mode with no key); and the eval command writes
`eval/results/sample__rules/metrics.json` — scoring 0 items, honestly, because none of the 30 drafts
has been reviewed by a human yet.

## Phase 5: Freestyle Assistant and Pipeline Assistant

Done. Built on `phase-5-assistants`, merged into `main` as `8da58b9` on 2026-10-13 (PR #10).

- [x] T5.1 Spec model (Pydantic) with YAML round-trip and the planner schema, plus one revision
      rule for both job types (D-041). Evidence, all run on 2026-10-12:
      - **Code:**
        - `app/generation/spec.py`: `GenerationSpec`, the 4.6.1 spec field for field, and
          `Stage`. A suite is only valid on a test stage and an environment only on a deploy.
          Stages cannot carry their own commands. YAML is dumped in 4.6.1's own layout.
          `build_planner_schema` is strict, per service, and offers only stages and templates,
          with catalog enums. `PlannerOutput` re-checks the plan in code.
        - `app/generation/revision.py`: `select_revision`. COMMIT wins, else the head of BRANCH,
          else main. An invalid given value is an error, never a fallback. Both job types get the
          same `BRANCH` and `COMMIT` (a SHA or `refs/heads/<branch>`, never empty).
      - **Reference configs:** re-exported from jenkins-dev. Freestyle `COMMIT` defaults to
        `refs/heads/main`. The Pipeline Jenkinsfile applies the same rule and validation, stopping
        before checkout on bad input. Its parameters are now in config.xml, which implements D-034.
      - **Offline tests:** `test_generation_spec.py` and `test_generation_revision.py`, 82 passed.
        They cover 4.6.1 parsing, round-trip and layout, commit priority, branch fallback, default
        main, blank values, invalid commits and branches, parity, and the reference configs
        carrying the rule.
      - **Live tests:** `pytest -m integration tests/test_integration_revision.py`, 17 passed on
        jenkins-dev:
        - Both job types check out the same commit for commit-wins, branch-head, neither and
          both-blank.
        - Both fail at checkout with nothing checked out for a missing commit or branch.
        - The Pipeline applies the rule to raw parameters, and refuses invalid ones before checkout.
        - A chain job triggered without parameters follows its written defaults.
        - A config pushed twice keeps its parameters.
      - **Existing integration suite:** 8 passed. Two Pipeline tests were updated for the
        parameterized-from-creation job; why is recorded in D-041.
      - **Regression checks:**
        - Offline suite: 1241 passed.
        - `accept_failing_tests.py`: 4/4.
        - `verify.py --phase 4`: 66/66.
        - The catalog-loader check now names the spec as the one other YAML document allowed. It
          still fails a stray parser: proven with a throwaway file.
      - **Known gap (D-041):** a freestyle job started by hand in the Jenkins UI with only BRANCH
        changed follows its COMMIT.
- [x] T5.2 Planner with default plans per action and a repair loop (D-042). Evidence, all run on
      2026-10-13:
      - **Code:**
        - `app/generation/planner.py`: `required_stages` derives the stages a confirmed intent
          needs, using the owner's four decisions (build first when needed; every suite when none
          is named; checks before tests; the default plan after 2 failed repairs). `check_plan`
          lists what is wrong with a model's plan. `Planner` plans through the existing
          `ModelChain`, sends issues back for at most 2 repairs, and builds the `GenerationSpec`
          with the stages from the plan and everything else from the intent and catalog.
        - `app/generation/factory.py`: `build_planner`, with fake mode answering with the
          default plan.
        - `app/ai/prompts/planner_v1.md`: 7 examples, each the code's own default plan.
        - `app/ai/prompting.py`: the example parser also accepts `Plan:`. The intent prompt is
          unchanged, with the same 12 examples and the same version.
      - **Offline tests:** `test_generation_planner.py`, 64 passed. They cover:
        - default plans per action, every suite, extra-stage order and the smoke test;
        - errors for unplannable requests, and every plannable catalog combination against the
          order rule;
        - plan checks;
        - the repair loop: valid first, repaired, exhausted, ablation, model unavailable, second
          model, model lost mid-repair;
        - no free text reaching the model, no caching, the spec built from intent and catalog;
        - the prompt agreeing with the code;
        - fake, live-without-key and replay-miss modes, and a parsed command planned end to end.
      - **Live test:** `pytest -m live tests/test_generation_planner_live.py`, 3 passed.
        `gpt-oss-120b` gave a valid plan on the first attempt for all three requests (0 repairs),
        about 1,700 to 1,800 tokens each.
      - **Regression checks:**
        - ruff, ruff format and mypy: clean.
        - Offline suite: 1305 passed.
        - `verify.py --phase 4`: 66/66, after starting Docker Desktop and the stack, which were
          down after a restart.
- [x] T5.3 Jinja2 templates derived from the reference configs, with golden-file tests (D-043).
      Evidence, all run on 2026-10-13:
      - **Code:**
        - `app/generation/templates/`: `freestyle-job.xml.j2`, `pipeline-job.xml.j2` and
          `Jenkinsfile.j2`, each the reference export with its variable parts replaced.
        - `app/generation/render.py`: freestyle chains (`fs-<service>-<stage>`, suite-specific
          test jobs, `dependsOn` the previous job, a SUCCESS-only trigger of the next, defaults on
          every job, build prep in test, lint and scan jobs) and Pipeline jobs
          (`pl-<service>-<action>[-<env>]`). Commands come only from the catalog.
        - The Pipeline reference gained `JobPriorityProperty` in config.xml, re-exported from
          jenkins-dev.
      - **Tests:** `test_generation_render.py`, 33 passed. Derivation: the reference values
        reproduce the exported Jenkinsfile byte for byte, the Pipeline job element for element,
        and every chain job's static parts. Also golden files for 4 specs (9 config.xml files
        and 2 Jenkinsfiles), chain wiring, escaping and refusals.
      - **Regression checks:**
        - Offline suite: 1338 passed.
        - `pytest -m integration` (the Jenkins suite and the revision suite) against the
          re-exported references: 25 passed.
- [x] T5.4 `FreestyleValidator` and `PipelineValidator`, including the declarative linter call
      (D-044). Evidence, all run on 2026-10-13:
      - **Code:** `app/generation/validate.py` runs 4.6.3's eight checks in order: spec schema;
        catalog and Git (including the catalog's own repository and label); environment
        allowed; stage order and build-first; shell metacharacters; XML well-formedness or,
        for a Pipeline, the declarative linter through `JenkinsClient`; job names; and no
        production in anything sent to Jenkins. Each failure is classed plan, input or
        template. `parse_spec` handles an edited YAML. The planner now also sends a stage name
        mentioning production back for repair.
      - **Offline tests:** `test_generation_validate.py`, 32 passed.
      - **Linter integration test:** `pytest -m integration tests/test_integration_generation.py`,
        4 passed against jenkins-dev:
        - every rendered Jenkinsfile (each service, each generating action, with and without
          extra stages) passes the real declarative linter;
        - a broken Jenkinsfile is rejected;
        - a chain created last-first keeps its triggers, `dependsOn`, priority and defaults, and
          the Pipeline job keeps its parameters, sandbox and priority.
      - **Regression checks:** offline suite 1371 passed; ruff, format and mypy clean.
- [x] T5.5 Conversation and message endpoints for both assistants; intent editing (D-045).
      Evidence, all run on 2026-10-13:
      - **Code:**
        - `app/api/assistants.py`: `POST /api/assistants/{freestyle|pipeline}/conversations`,
          `GET /api/conversations`, `GET /api/conversations/{id}`,
          `POST /api/conversations/{id}/messages`, `GET /api/commands/{id}` and
          `PATCH /api/commands/{id}/intent`.
        - `app/services/conversations.py`: the message flow (clarification answers merged and
          re-parsed, slash commands, the policy context, `IntentParser.record`) and intent
          editing through the new `IntentParser.reconsider`.
      - **Tests:** `test_assistants_api.py`, 21 passed in fake mode. They cover:
        - conversation lifecycle and ownership;
        - a clear request recorded with its `llm_calls`;
        - "run the tests" asking for the service, then the suite (4.6.5);
        - a new request in reply to a question starting over;
        - production refused, and the injection attempt refused and audited;
        - the HIGH justification flow, `/help`, `/status` and the 1,000-character guard;
        - editing: re-decided, outside the catalog, to production, action locked, approved
          locked, ownership.
      - **Regression checks:** offline suite 1392 passed; ruff, format and mypy clean.
      - **Running-chain lookup:** returned "no chain" until the per-service lock existed. Wired in
        T5.7, and tested there.
- [x] T5.6 Generate, regenerate, streamed explain, and approve with an idempotency key (D-046).
      Evidence, all run on 2026-10-13:
      - **Code:**
        - `app/services/generation.py` and `app/api/generation.py`:
          `POST /api/commands/{id}/generate`, `GET /api/pipelines/{id}`, and
          `POST /api/pipelines/{id}/regenerate`, `/explain` (streamed) and `/approve`
          (`Idempotency-Key`).
        - The flow: plan, render, validate, then a `generated_pipelines` row with the progress
          steps, checklist, plan record and approval summary, plus `llm_calls` for the planner
          and the explanation.
        - Approval: the row is locked and claimed before Jenkins, jobs are saved last-first, the
          `jobs` rows are upserted, the first job is triggered and handed to the tracker, and
          the audit log and a "Run started" message are written.
        - `app/ai/prompts/explain_v1.md`.
      - **Tests:**
        - `test_generation_api.py`, 22 passed: both assistants, readiness, a linter rejection
          shown as a failed step, privacy, regenerate superseding, edited YAML (valid; policy
          fields locked; schema; production), explain, and approve (key required, last-first,
          replay, second key refused, invalid refused, Jenkins failure undone and retried,
          locked after approval).
        - `test_generation_explain.py`, 6 passed.
      - **Regression checks:** offline suite 1420 passed; ruff, format and mypy clean.
      - **Chain lock at approval and tracking past the first job:** wired in T5.7.
- [x] T5.7 Per-service chain lock; chain triggering and tracking; stage tracking for Pipeline
      (D-047). Evidence, all run on 2026-10-13:
      - **Code:**
        - `app/services/chains.py`: claim and expiry, `advance` (downstream builds found through
          `UpstreamCause`, the chain stopped at the first non-SUCCESS), the run card, cancel, and
          rerun of the last failed test job.
        - `chains` table and `job_runs.chain_id` (migration `c4e1d07a5b92`).
        - `RunTracker`: chains advanced each tick, `chain.updated`, `chain.finished` and
          `chain.stages` events.
        - `JenkinsClient`: `downstream_build`, `pipeline_stages` (`wfapi`) and `queued_items`,
          their shapes confirmed live first.
        - Approval claims the lock in its own commit.
        - `/api/chains` endpoints; STATUS, RERUN and CANCEL messages act.
      - **Migration:** on a scratch PostgreSQL database, upgrade, downgrade, upgrade and
        `alembic check` all succeed, with no model or schema difference.
      - **Tests:** `test_chains.py`, 18 passed:
        - the lock, its expiry, the Admin cancel offer, and the policy and approval refusing
          while a chain runs;
        - a failed test stopping the chain with the deploy job never started (fake);
        - a full chain succeeding and releasing the lock;
        - restart safety;
        - Pipeline stages published only on change;
        - the run card with queue rank and waiting reason;
        - cancel stopping the running job and dequeuing the rest, and cancel permissions;
        - status and rerun messages.
      - **Regression checks:** offline suite 1438 passed; ruff, format and mypy clean.
- [x] T5.8 End-to-end backend tests (`e2e`) for every command in Part 4.6.5. Evidence, all run
      on 2026-10-13:
      - **The gate:** `python scripts/verify.py --phase 5` printed **ALL CHECKS PASSED, 71 of 71**
        (Phases 0 to 4: 66; Phase 5: 5), on `b662871` with a clean tree. The Phase 5 checks were:
        - golden templates: 33 passed;
        - linter integration: 4 passed;
        - `pytest -m e2e`: 12 passed;
        - the failing-branch chain: the test job failed and the deploy job never started;
        - T5.9: 163 passed.
      - **Five earlier gate runs failed,** each on a DNS lookup that never resolved, not on the
        code:
        - runs 1 to 3: one check failed each;
        - run 4: three end-to-end tests;
        - run 5: four tests across two checks.

        The builds' own logs say `Could not resolve host: github.com` (Known gaps, "Agent DNS").
        Run 3's one failure came before Jenkins was reached and left no reason, so `verify.py` now
        keeps a failed check's whole output under `.tmp/verify/`.
      - **Tests:** `tests/test_e2e_assistants.py` and `tests/e2e_support.py` cover all nine 4.6.5
        commands, the failing-branch acceptance through the generator, and one Pipeline with its
        stages tracked. They run against the real app, the stack's PostgreSQL (a migrated
        `orchestrator_e2e` database), jenkins-dev and its agents, and real deploys.
      - **Results:**
        - Record mode against live Groq: 11 passed.
        - Replay mode, no model access: **11 passed, 0 replay misses**.
        - The failing branch: the test job failed, and the deploy job's last build number was
          unchanged.
      - **Fixtures:** recorded into `app/ai/fixtures/`.
      - **Branch created:** `feature/refund` in payment-service, at `main` (998844b), because the
        4.6.5 command names it.
      - **Parser guard (D-048), found by e2e:** gpt-oss-120b invented a service for "status of my
        last deploy". STATUS, RERUN and CANCEL now act only on a service the user named. 4 new
        parser tests; parser suite 32 passed.
      - **`verify.py`:** Phase 5 checks added (golden templates, linter integration, e2e,
        failing branch), and `IMPLEMENTED_PHASES` now includes 5.
      - **Modes, kept apart:**
        - Live Groq (record mode) passed every e2e test that calls the model, at least once each.
        - Replay, which is what the gate uses, passed with 0 replay misses.
        - The offline suite uses the fake provider and the fake Jenkins.
- [x] T5.9 Stretch: "Explain failure" for failed runs (D-049). Evidence, all run on 2026-10-13:
      - **The gate:** its T5.9 check passed with 163 tests in the 71-of-71 run above. Those are
        the 162 offline tests plus the live jenkins-dev integration test.
      - **Surface:** `POST /api/runs/{id}/explain` (any signed-in user, the assistants' rate limit)
        and `failed_run_id` on the run card. Live in the rebuilt backend container.
      - **How it works:**
        - Redaction runs first.
        - Code decides the category, stage, failing tests, counts, exit code, evidence lines,
          the Pipeline's skipped stages, and the chain jobs the failure stopped.
        - The model words it through a strict schema (`failure_v1`). Its answer is dropped for
          the code's own if a quote is not in the log, it contradicts the code, it mentions
          production, or it is malformed.
      - **Tests, offline:** 162 across `test_failures_redact.py` (46), `test_failures_analysis.py`
        (46), `test_failures_explainer.py` (56) and `test_failures_api.py` (14), plus the
        streaming tail read's tests in `test_jenkins_console.py`. They run on seven logs captured
        from jenkins-dev, plus one constructed log (see `tests/data/failure_logs/README.md`).
        Offline suite **1630 passed**, 49 deselected; ruff, format and mypy clean.
      - **Integration, live jenkins-dev:** `test_integration_failures.py` passed (63 s). The
        generated payment-service test job ran twice on `demo/failing-tests`, and both real logs
        gave the model **byte-identical prompts**.
      - **End to end:** a failed freestyle test job and a failed Pipeline stage, each explained
        through the API.
        - Record mode, live Groq: both passed. The model's answers survived every check, and every
          quoted line matched the real log.
        - Replay mode: the whole suite, **13 passed, 0 replay misses**.
        - The freestyle explanation lists the integration-test and deploy jobs as never started.
        - The Pipeline explanation names "Unit tests" and the two skipped stages, with exit code 1.
      - **Found by the first live run:** Jenkins prefixes every Pipeline step line with a
        Timestamper time, so the real failure read as `unknown`. Fixed, and the real log is now a
        fixture. Also: the Edit tool decoded a `\u` escape into the literal character
        (CLAUDE.md lesson).
      - **Refined by the DNS failures:** the failing step is read before the rest of the log. A
        clone error that a retry recovered from cannot then take the blame for tests that failed
        afterwards (D-049, `b662871`).

Phase 5 close-out, 2026-10-13. Every item ran in this session:
- **Security review:** `docs/security-review-phase-5.md`. Six findings were fixed, each with a
  regression test:
  - T5.9 read whole logs into memory; it now streams the last 1 MB;
  - rerun's test-job check could match a deploy job;
  - redaction missed command-line credentials;
  - two policy denials were not audited;
  - network faults were classed as checkout errors;
  - the `.log` fixtures were hidden from git, so CI failed until they were committed.

  Nine residual risks are recorded. **The review is not independent:** the reviewer agent stopped
  on a usage limit (Needs human).
- **Database:** `alembic upgrade head` ran in the backend container on the Compose database, from
  `8c2f4d1e7a90` to `c4e1d07a5b92`.
  - `alembic current` reports `c4e1d07a5b92 (head)`, and `alembic check` reports no new upgrade
    operations.
  - Checked with psql: `chains` has its partial unique index `uq_chains_one_running_per_service`,
    and `job_runs.chain_id` is nullable with `ON DELETE SET NULL`.
- **Backend container:** rebuilt from `b662871` and healthy. `/api/health` reports the database up
  and Jenkins up (2.568.3), with the LLM disabled, as Compose's default `LLM_MODE=fake` sets it.
  Every Phase 5 route is in its OpenAPI, and each refuses an unauthenticated request with 401.
- **CI:** green on `b662871`, both the push and PR #10. It had been red on `f787450` until the
  fixtures were committed.
- **PR:** #10 (`phase-5-assistants` → `main`) was retitled and described, then **merged on
  2026-10-13 as merge commit `8da58b9`**, at the user's request. `main`'s tree is identical to the
  branch head, `93b38cf`. CI on `main` passed after the merge: Backend, Plugin and the phase
  checks, with Frontend skipped. `phase-5-assistants` is kept, and the `m2-final` tag is
  untouched.

Audit of T5.1 to T5.8, 2026-10-13. I re-read Part 3, 4.4.3 to 4.4.5, 4.5.5, 4.6 and 4.7.4
against the code. Five gaps were found and fixed, each with a regression test that fails without
its fix:
- **Audit, chain lock:** an approval refused by the chain lock was never audited, but 4.4.3 says
  "audit every ... policy denial", and `get_db` rolled the refusal back. `chains.claim` now writes
  `policy.chain_running`, in the policy layer's shape plus `at: approval`, and approval commits it
  before re-raising (the D-022 pattern).
- **Audit, cancel:** a refused cancel (not the starter, below DevOps) is now audited as
  `chain.cancel_refused`.
- **Command status:** generating left the command `PARSED`. Choosing Generate is the user
  confirming the intent card, so it now becomes `CONFIRMED` (4.4.3's status column).
- **Run card link:** the card lacked 4.7.4's "Jenkins link". Each run now carries the URL that
  Jenkins reports for its build. The fake reports URLs the same way.
- **e2e mode default:** the suite defaulted to replay even with a key. T5.8 says replay "when no
  Groq key is set", so it is now live with a key and replay without one. `verify.py` still pins
  replay, so the gate spends no quota.
- **Checks:** offline suite 1450 passed, 46 deselected; ruff, format and mypy clean.

The rest matched the spec, and three items were checked with no change needed:
- The run card has all five 4.6.2 items.
- Cancel dequeues members and stops the running build.
- An unreachable plugin degrades to `queue: null` instead of failing the card.

Groundwork recorded on 2026-10-11, before T5.1:

- `demo/failing-tests` exists in both service repositories: one intentional failing unit test each
  (`auth-service` ab50e0e, `payment-service` 2b4e686), every other test still passing.
- `python scripts/accept_failing_tests.py` → 4 of 4 verdicts pass, on the fourth attempt (the
  first three are kept in `docs/evidence/2026-10-11-demo-failing-tests/` as evidence of what each
  exposed). **Control on `main`:** build, test and deploy-staging all SUCCESS for both services,
  the deploy log reports healthy, and from the host `localhost:9001/health` and
  `localhost:9002/health` answer 200 with `/version` reporting the exact `main` commits pushed
  (payment `998844b`, auth `6413c6f`). **Demo on `demo/failing-tests`:** the test job fails on the
  intentional assertion (1 failed, 7 passed in each service) and the deploy job never starts.
- Four defects found and fixed (D-038): the reference branch spec never worked (now `${COMMIT}`,
  re-exported from Jenkins), no service script was executable, agents could not reach Docker
  Desktop's socket, and the deploy health probe looked at the agent's own localhost.
- `verify.py --phase 4` re-run after the agent and compose changes → ALL CHECKS PASSED, 66 checks.

Preparation, 2026-10-11, after PR #9 merged. Still **no task checked off**.
- **Branch:** `phase-5-assistants` was fast-forwarded to `main` (357f1aa: Phases 0 to 4, the
  D-039 log fix and the Phase 5 groundwork).
- **Agent images:** rebuilt and the agents force-recreated. The `jenkins` user reaches Docker in
  both, and both are online.
- **Spec reference:** T5.8's "Part 4.6.7" corrected to 4.6.5, the nine-command list (D-040).
- **Acceptance script:** `accept_failing_tests.py` exited 1 after all four verdicts passed whenever
  `--out` was outside the repo or relative. A `relative_to` call raised on the final print. Fixed
  with `display_path`. Rerun on the rebuilt agents with `--out` outside the repo: 4/4 verdicts
  pass, exit 0.
- **Left for the start of T5.1:** one revision rule for the shared spec. The freestyle reference
  checks out `${COMMIT}` (default `main`, D-038). The Pipeline reference uses
  `params.COMMIT ?: params.BRANCH`. Settled in T5.1 by D-041.
- **Not a Phase 5 prerequisite:** labelling the evaluation set is Phase 8. All 30 drafts are still
  `needs_review: true`, and no Phase 5 acceptance clause uses them.

## Phase 6: Frontend

In progress on `phase-6-frontend`, branched from `main` at `8da58b9`. T6.1 is done and waiting
for approval (Needs human); T6.2 next.

- [x] T6.1 Write `frontend/DESIGN.md` using the process in Part 4.7.2, then stop and add "Approve
      DESIGN.md" under Needs human. Build no screens before approval. Work on T6.2
      infrastructure meanwhile. Evidence, all run on 2026-10-13 and 2026-10-14:
      - **The document:** subject and audience, a palette of six named values plus the score
        bar's four colours and three build-state colours (D-052), type, three wireframed
        layouts, five principles with the score bar as the memorable element, the score bar's
        own specification, and the review against 4.7.2's generic traits with what changed.
        "Approve frontend/DESIGN.md" is under Needs human.
      - **Its check:** a new Phase 6 check in `verify.py` reads the document's own tables and
        recomputes everything it claims. In the gate run below it passed: "6 named colours, 4
        score bar and 3 build-state colours; worst text contrast 6.86:1 (Graphite on Ground,
        light); score bar neighbours at least 20.0 apart, 11.9 under CVD; 5 principles;
        wireframes for Assistant workspace, Queue, Overview".
      - **The check is negative-tested.** Eight edited copies each failed for their own reason:
        - a paler Graphite;
        - a dependency colour equal to the failure red;
        - the first success green;
        - no review section;
        - seven named colours;
        - a 92ch measure;
        - two principles;
        - no queue wireframe.
      - **It caught one real defect.** The first success green, `#0ca30c`, was 2.96:1 on Ground,
        the colour of a hovered row; the document now uses `#069c07`. Its section 9 records this
        and the two other changes that came from measuring.
      - **Colours:** the score bar passed the dataviz skill's `validate_palette.js` in both
        themes, against this product's panels. Light: worst adjacent CVD ΔE 15.3. Dark: 11.9.
        Every contrast pair was measured with WCAG's formula, with zero failures.
      - **The gate, `verify.py --phase 6`, did not pass as a whole:** 71 of 72 checks passed.
        The one failure was Phase 5's end-to-end test of Explain failure, whose explanation fell
        back to rules after a replay miss. The cause was a checkout that Jenkins had retried
        (D-053), fixed in the next commit. A full re-run after that fix was stopped by Claude
        Code because the machine ran low on memory, and has not been repeated.
- [ ] T6.2 Vite, React and TypeScript project; tokens; app shell; routing; API client generated
      from the backend OpenAPI schema; WebSocket hook.
- [ ] T6.3 Sign in and session handling.
- [ ] T6.4 Shared assistant workspace components (Part 4.7.4).
- [ ] T6.5 Freestyle Assistant and Pipeline Assistant pages.
- [ ] T6.6 Queue page with score bars.
- [ ] T6.7 Jobs and runs, Analytics, Service catalog, Admin and Overview pages.
- [ ] T6.8 Vitest unit tests and Playwright flows (Part 4.7.6), run against the backend in fake
      mode.
- [ ] T6.9 Screenshots of every screen in light and dark themes at 1440 px and 390 px, saved to
      `docs/screenshots/`, reviewed against `DESIGN.md`, with fixes applied.

**Acceptance:** all frontend quality bars pass; Lighthouse accessibility score of 95 or more on
both assistant pages; screenshots committed.

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
- **Agent DNS on this machine (2026-10-13).** Docker Desktop's resolver intermittently fails to
  resolve `github.com` from the agents, and the host showed a 2 s lookup in the same period.
  - **Effect:** a build then fails at its Git clone (`Could not resolve host: github.com`). Five
    gate runs on 2026-10-13 met at least one; each time the code under test was correct.
  - **What T5.9 does:** it reports these failures as infrastructure.
  - **What the tests do:** the T5.9 integration test re-runs such a build. The end-to-end tests do
    not, because a chain that fails is what they check, so a run that meets one must be repeated.
  - **Mitigated, not removed (D-050):** jenkins-dev now retries a failed checkout twice,
    10 seconds apart. Still exposed: an outage longer than that window, and the backend's own
    `git ls-remote` calls from the host.

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
- 2026-10-13 Phase 5 finished on `phase-5-assistants`. T5.1 to T5.9 are checked off, and
  `verify.py --phase 5` printed ALL CHECKS PASSED (71 of 71) on `b662871`. Also done:
  - the T5.1 to T5.8 audit (five fixes);
  - T5.9, Explain failure;
  - the security review (six fixes);
  - the backend container rebuilt, and the Compose database migrated;
  - PR #10 updated, not merged.

  Five gate runs failed first, each on an intermittent DNS failure on this machine; the
  mitigations are under Needs human. Next: review and merge PR #10, then Phase 6, starting
  with T6.1's `DESIGN.md`.
- 2026-10-13 PR #10 merged into `main` as merge commit `8da58b9` at the user's request; CI on
  `main` passed. Phase 6 started on `phase-6-frontend`, branched from `main`:
  - this file gains the Phase 6 tasks;
  - T6.8's wrong section reference is recorded as D-051.

  Next: T6.1's `frontend/DESIGN.md`, then stop for approval, with T6.2's infrastructure
  meanwhile.
- 2026-10-14 T6.1 done: `frontend/DESIGN.md` is written, measured and checked by a new Phase 6
  `verify.py` check. It now waits for a person's approval; no screen is built before it. The
  Phase 6 gate passed 71 of 72. Its one failure, in Phase 5's Explain failure, is D-053. A
  re-run after the fix was stopped by Claude Code for low memory. Next: T6.2.
