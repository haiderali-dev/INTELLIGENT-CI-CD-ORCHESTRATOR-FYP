# Progress

Updated: 2026-09-29 · Current phase: 3 · Branch: phase-3-backend

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
- [ ] T4.8 One opt-in live test and Phase 4 checks in `verify.py`

**Acceptance:** AI unit and policy tests pass; with Groq unreachable, the rule parser answers and the
response carries `ai_fallback: true`; `python -m eval run --parser rules --file
eval/datasets/sample.jsonl` writes a metrics file.

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
