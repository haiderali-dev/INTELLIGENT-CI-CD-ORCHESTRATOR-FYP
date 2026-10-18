# Progress

Updated: 2026-10-17 · Current phase: 6 (all tasks done; acceptance met; the gate passed 78 of 78 on
`ff70254`) ·
Branch: phase-6-frontend

## Needs human
- [x] **Create the two sample-service GitHub repositories**, push them, create the
      `demo/failing-tests` branch, and put the URLs in `catalog/services.yaml`. Blocks T1.8's
      `git ls-remote` check and the Phase 5 failing-branch acceptance test.
      Done, checked 2026-10-11 with `git ls-remote`. `haiderali-dev/payment-service` has `main`
      998844b and `demo/failing-tests` da997c8. `haiderali-dev/auth-service` has `main` 6413c6f
      and `demo/failing-tests` d4c4560. `catalog/services.yaml` points at both.
- [x] **Resolve or work around the JCasC floating-point defect (D-017).** Resolved on 2026-10-18,
      at the user's request to find the root cause.
      - **Cause:** JCasC's YAML loader builds nodes only for the bool, int and str tags, so an
        unquoted float is dropped from the parsed document. Quoted values apply.
      - **Fix:** the three `jenkins/casc/` files set all seven fields, quoted, at Appendix D's
        values. The aging-ablation arm can now be driven from YAML.
      - **Checks:**
        - `mvn -Dit.test=ConfigAsCodeIT verify`: 9 passed. Quoted values apply, unquoted ones are
          dropped (JCasC's behaviour, pinned), and an exported file imports again with its floats.
        - verify.py's Phase 1 check "JCasC quotes every floating-point optimizer value" passed,
          failed with one value unquoted, and passed again once it was restored.
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
      - **Seen working once, 2026-10-14:** in the first Phase 6 gate run, agent-2's clone for
        `fs-payment-service-test-unit` #60 could not resolve `github.com`. The retry got past it
        10 seconds later, and the build went on to its intended test failure. The error the
        retry left in the log then broke Explain failure's replay, which D-053 fixed.
- [ ] **Re-run the Phase 5 security review independently.** The reviewer agent stopped on an
      account usage limit, so `docs/security-review-phase-5.md` was written by the agent that
      wrote the code.
- [x] **Approve `frontend/DESIGN.md`.** T6.1 wrote it on 2026-10-13. Its section 10 lists the
      choices most worth questioning, and D-052 records how its palette reads 4.7.2's "4 to 6
      named hex values". No screen (T6.3 onward) is built before approval. T6.2's plumbing does
      not wait for it. Done 2026-10-15: the user approved the design as written ("Frontend
      design is approved"), with no changes. D-052 is now accepted; T6.3 onward may build screens.
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

In progress on `phase-6-frontend`, branched from `main` at `8da58b9`. T6.1 is done and was
approved on 2026-10-15; T6.2 to T6.9 are done. The phase gate passed 77 of 77 on `86d9a8d`
(2026-10-17). Lighthouse scored 100 for accessibility on both assistant pages (D-064), and the gate
gained a check for it: it passed 78 of 78 on `ff70254` (2026-10-17).

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
      - **The gate, `verify.py --phase 6`, did not pass as a whole at first:** 71 of 72 checks
        passed. The one failure was Phase 5's end-to-end test of Explain failure, whose
        explanation fell back to rules after a replay miss. The cause was a checkout that Jenkins
        had retried (D-053), fixed in the next commit. A full re-run after that fix was stopped
        by Claude Code because the machine ran low on memory.
      - **Re-run on 2026-10-15, on `c2b7e4f`: ALL CHECKS PASSED, 75 of 75.** That includes Phase
        5's Explain failure (170 passed) and all four Phase 6 checks. Before it ran, the host had
        2.5 GB free of 16 GB, and Docker's VM had 7.6 GB with the containers using about 1 GB. Free
        memory stayed between 1.9 and 2.8 GB throughout.
- [x] T6.2 Vite, React and TypeScript project; tokens; app shell; routing; API client generated
      from the backend OpenAPI schema; WebSocket hook. Evidence, all run on 2026-10-14:
      - **Project:** Vite 8, React 19 and TypeScript 5.9 in strict mode, with
        `noUncheckedIndexedAccess`. Every version is exact and recorded in `docs/versions.md`,
        including why three trail the newest release.
      - **Tokens:** `src/styles/tokens.css` holds DESIGN.md's colours for both themes. Tailwind's
        own palette, radii, shadows, breakpoints and type scale are cleared, so only DESIGN.md's
        values exist as utilities. A test compares all 13 colours with DESIGN.md's tables.
      - **Shell and routing:** React Router 8 with a sidebar of every page. The two assistants
        are separate entries in Spruce and Plum. The footer says Staging and has the
        Light/Dark/System switch. Below 768 px a menu button opens the same sidebar as a Radix
        dialog. Every route is a placeholder that names the task building it; no screen is
        built before DESIGN.md's approval.
      - **API client:** the schema is exported from the app object by
        `python -m app.openapi_export`, needing no server and no `.env`, into
        `frontend/openapi.json`. `openapi-typescript` turns that into `src/api/schema.d.ts`, the
        only API types. The client, `openapi-fetch`, adds the bearer token, held in memory only.
      - **WebSocket hook:** one shared `LiveEventsClient`:
        - it authenticates in its first frame;
        - it stops on close 1008;
        - otherwise it reconnects with backoff from 1 s to 30 s;
        - it closes a socket that misses two heartbeats.
        `useLiveEvent` and `useLiveStatus` expose it.
      - **Checks:** verify.py has three new Phase 6 checks, each run directly and each passing:
        - "lint, typecheck and build clean; 49 tests passed";
        - "openapi.json is the backend's schema (39 paths), and schema.d.ts is its output";
        - "12 event types and 4 topics, the same on both sides".
      - **The checks are negative-tested.** Four drifted copies each failed with the command
        that fixes them: a stale `openapi.json`, a hand-edited `schema.d.ts`, a missing event
        type, and no `node_modules`.
      - **CI:** the backend job now fails if `openapi.json` is stale, and the frontend job fails if
        `schema.d.ts` was hand-edited.
      - **Backend:** ruff, format and mypy are clean, and the offline suite passed 1641, with 4 new
        export tests.
      - **Not yet done:** the shell has not been looked at in a browser; T6.9's screenshots cover
        that. The full `verify.py --phase 6` ran with these checks on 2026-10-15 and passed
        (see T6.1).
- [x] T6.3 Sign in and session handling. Evidence, all run on 2026-10-15:
      - **Session (D-054):**
        - The access token is in memory only. The refresh token is in this tab's
          sessionStorage, so a reload keeps you signed in and closing the tab signs you out.
        - The access token is renewed a minute before its 15 minutes run out.
        - A 401 from anything outside `/api/auth/` gets one single-flight refresh and one repeat
          of the request.
        - Sign-out revokes the refresh token on the server, then forgets both tokens whatever
          the answer.
        - The live-events connection reopens with the new token on sign-in and closes on
          sign-out. Cached server data is dropped on sign-out. A connection the server refuses
          (1008) gets one refresh and one retry, never a loop.
      - **Routing:** every page except Sign in sits behind `RequireSession`.
        - Without a session you are sent to `/sign-in?next=<page>`, and back there afterwards.
        - `next` is followed only to a path on this site, so the page cannot be used to
          redirect elsewhere.
        - After an explicit sign-out, `next` is dropped, because whoever signs in next may be
          someone else.
        - A reload shows "Restoring your session" until the refresh answers.
      - **Sign in page (4.7.3: specific errors, no dead ends):**
        - Built with react-hook-form and zod, as 4.7.1 asks.
        - Each failure says what happened and what to do: a missing or malformed email, a
          missing or over-long password, a wrong email or password (the email is kept, the
          password cleared and focused), a disabled account, "wait N seconds" after the rate
          limit, and a server that did not answer.
        - It also says why you arrived: you signed out, your session ended, your account was
          disabled, or the session could not be restored.
        - Errors are in Ink with an icon, not red, because DESIGN.md reserves the state colours.
        - The sidebar's footer now says who is signed in, with their role and Sign out.
      - **Error codes (D-055):** the API's one error shape is now in the OpenAPI schema on every
        route, so `ErrorCode` is generated rather than hand-written. FastAPI's false 422
        `HTTPValidationError` entries are gone. `openapi.json` and `schema.d.ts` were regenerated.
        - Three new backend tests. The two schema tests were confirmed to fail without the
          change.
      - **Frontend checks:** `verify.py`'s four Phase 6 checks, run directly, all passed.
        - "lint, typecheck and build clean; 92 tests passed". 43 of those are new: the session
          14, sign-in page 16, API client 5, next address 3, the provider and live connection 2,
          and the shell 3.
        - The API types are the backend's schema (39 paths).
        - The DESIGN.md and WebSocket checks pass unchanged.
        - No test printed a warning.
      - **Backend:** ruff, format and mypy are clean. The offline suite passed 1644, with 49
        deselected. Its 5 warnings predate this task: they come from `_validation_error`'s use
        of the deprecated `HTTP_422_UNPROCESSABLE_ENTITY` constant.
      - **Live check:** through the Vite dev server, against the running Compose backend:
        - `/sign-in` serves the app.
        - A malformed sign-in through the `/api` proxy came back 422 with
          `details.fields.email`, the shape the page maps to the email field.
        - No real credentials were used.
      - **Dependencies:** react-hook-form 7.89.0, zod 4.6.5 and @hookform/resolvers 5.9.1, under
        the seven-day cooldown, recorded in `docs/versions.md`. `npm audit --omit=dev` found
        no vulnerabilities.
      - **Not done:**
        - **The sign-in page has not been looked at in a browser.** T6.9's screenshots cover
          that.
        - **Mutation checks on the session's security tests were not run.** Weakening the
          redirect check or the auth-endpoint exemption to watch the tests fail was refused by
          Claude Code's auto mode, and the code was restored at once. The tests assert those
          behaviours directly.
- [x] T6.4 Shared assistant workspace components (Part 4.7.4). Evidence, all run on 2026-10-15:
      - **Built, in `src/workspace/` and `src/components/`:**
        - the workspace layout: chats, thread and preview side by side from 1280 px; a drawer
          below that; a bottom sheet with a one-line summary below 768 px;
        - the chat list, the thread (`aria-live="polite"`), and the empty state with one
          sentence, four example commands from 4.6.5, and the services it knows;
        - the intent card, whose editor offers only catalog values through react-hook-form and
          zod, and sends only the fields that changed;
        - clarification with at most four answers, and the progress line (Understood, Planned,
          Rendered, Validated, each with a check or the exact error);
        - Approve and run: the dialog states the backend's own sentence, the button says
          Approve and run, and the toast says Run started;
        - the run card, the composer and the fallback notice;
        - the preview: Spec, Config or Jenkinsfile, Checks, Explanation.
      - **Shared pieces:**
        - the score bar, to DESIGN.md section 6;
        - build states as an icon and a word;
        - toasts, sheets and button styles;
        - code views on CodeMirror 6: read-only `config.xml` and Jenkinsfile, editable spec
          YAML with inline errors and a written list of them, and a diff after a regenerate.
        - Each assistant's identity (name, glyph, accent, sentence, examples, placeholder) has
          one source, which the sidebar now reads too.
      - **DESIGN.md in code:**
        - **Score bar:** a fixed 0 to 1.15 scale. Segments are weight times factor, with the
          weights taken from the queue API, never written in the UI. There is a 2px gap, only
          the data end is rounded, a factor of zero draws nothing, and there is a Graphite tick
          at 1.0. An inherited score gets an Ink tick, and the bar's name uses section 6's words.
        - **No state colours outside build states:** code views are Ink and Graphite only, and
          their errors and diffs are never red or green. The progress line and checklist use
          Ink icons and words.
        - **Floating layers:** 8px corners with the one shadow, or a Rule border in dark mode.
        - **Touch targets:** at least 44px under 768 px.
        - **Type:** `text-xs` only for the keyboard hint.
        - **Motion:** a 120 ms message fade and a 160 ms toast, both off under reduced motion.
      - **Tests:** `npm run test` passed 179, 87 of them new: score bar 14, code views 10,
        composer 12, preview 9, intent card 7, run card 6, layout 5, progress line 5, build
        states 5, workspace parts 5, approval 3, clarification 3, formats 3. 4.7.6 asks for
        Vitest tests of the intent card, clarification, score bar and composer; all four have
        them.
        - The approval test goes from the button to Run started with the keyboard alone.
        - No test printed a warning. Two full runs passed back to back after one fix: a test
          that waited one second for the lazily loaded editor timed out under load, and now
          loads it first.
      - **Checks:** `npm run lint`, `npm run typecheck` and `npm run build` are clean.
        `verify.py`'s four Phase 6 checks, run directly, passed with "179 tests passed", and
        `verify.py --phase 0` passed.
      - **Dependencies:** ten CodeMirror packages, recorded in `docs/versions.md`. `npm audit
        --omit=dev` found no vulnerabilities.
      - **D-056:** the components take props rather than API payloads, because four payloads
        are untyped dictionaries in the schema.
      - **Not done:**
        - **Not seen in a browser.** No page uses these components until T6.5, and T6.9
          screenshots them.
        - **The editor's split into its own chunk is unconfirmed.** It is lazily loaded, but
          the build has nothing to split until T6.5 imports the preview. The build's existing
          500 kB chunk warning (556 kB, 555 in T6.3) predates this task.
        - **Left to later tasks:** the score bar's 20 px Analytics size with an axis (T6.7) and
          its one-time growth on the queue page (T6.6).
- [x] T6.5 Freestyle Assistant and Pipeline Assistant pages. Evidence, all run on 2026-10-16:
      - **The page** (`src/pages/AssistantPage.tsx`) is one component used by both assistants,
        each with its own sidebar entry, header, empty state, composer placeholder and preview.
        The chat is in the address, `/assistants/<assistant>/<chat id>`. A chat is created only
        when its first message is sent.
      - **The thread** shows each reply by its payload kind (D-058):
        - the intent card, read from the command's current record, so an edit shows and a
          justification question after an edit is asked;
        - the clarification, with only the newest question answerable;
        - a refusal's reasons, and an Admin's offer to cancel the running chain (4.5.5);
        - help as a list;
        - a status reply's run card, and the run card after Approve and run or a re-run;
        - the fallback notice when the rule parser answered.
        - Sending shows the message at once with "Working on it". Stop cancels the wait. A
          message that was not sent keeps its text and says why.
      - **The preview** shows the newest plan:
        - the spec as editable YAML, with the backend's schema errors on their lines;
        - each job's config.xml, or the Jenkinsfile;
        - the checks and progress line;
        - the explanation, streamed as it arrives;
        - a diff against the plan it replaced.
        - "Generate from this spec" re-validates an edit. Approve and run sends one
          idempotency key per plan, says Run started, and shows "Approved and started" after.
      - **Live updates:** run cards refetch their typed `RunCard` whenever a run, chain or queue
        event arrives on the WebSocket.
      - **D-059:**
        - the untyped `plan`, `approval`, `stage` and approval `result` are not needed and are
          not read;
        - the page's API types come from the client's return types, because openapi-fetch's
          `Readable` drops properties typed exactly `null`;
        - the thread orders a message before its reply on a timestamp tie.
      - **Tests** run against the real API responses: the backend was driven in fake mode, and
        19 responses were captured into `src/test/fixtures/captured.ts` and type-checked.
        - The page has 14 tests: first message to intent card, example commands, thread order,
          editing, generate and preview, approve, live run card refresh, an inline spec error, a
          clarification, a streamed explanation, a refused send, Stop, the Pipeline Assistant,
          and a chat that cannot be opened.
        - The helpers have 12: spec problems, thread order, the run card view and the preview
          summary.
      - **Checks:** `npm run lint`, `typecheck` and `build` are clean, and `npm run test` passed
        206 with no warning. `verify.py`'s four Phase 6 checks, run directly, all passed,
        including "206 tests passed" and "openapi.json is the backend's schema (39 paths), and
        schema.d.ts is its output".
      - **The build:** CodeMirror is now its own lazy chunk, 395 kB. The main chunk is 683 kB,
        against 556 kB before T6.5, so the over-500 kB warning that predates T6.5 is still there.
        Splitting routes would fix it.
      - **Not done:**
        - **Not seen in a browser.** No browser tool was available in this session. Signing in
          to the stack needs the seeded admin password, which is in `.env`. T6.8's Playwright
          flows and T6.9's screenshots are where this gets seen.
        - **The running backend container is still the old image,** without D-057 and D-058.
          It was not rebuilt.
      - **The full gate, re-run on 2026-10-16 on `f43f0db`: ALL CHECKS PASSED, 75 of 75,
        exit 0.** By phase: 11, 17, 6, 22, 10, 5 and 4 passed, none failed. A first run on
        2026-10-15 was stopped by Claude Code for low memory after 39 checks, all passing.
        - **CI run 38792947715 on `f43f0db`:** all five jobs passed. Backend 1662 passed;
          frontend 206; plugin 108 unit tests and 65 integration tests with no failure.
        - **Memory during the re-run:** it started with 3.4 GB of 16 GB free and 3.0 GB of
          commit headroom. Headroom fell to 368 MB during Phase 6's frontend checks, so the
          machine runs this gate with little to spare.
        - **What took the memory:** Docker's VM grows as the end-to-end builds run, and Chrome
          and VS Code held about 3 GB between them. The pagefile is 1.86 GB.
- [x] T6.6 Queue page with score bars. Evidence, all run on 2026-10-16:
      - **The page** (`src/pages/QueuePage.tsx`) is the plugin's live ranking:
        - one row per waiting job, giving rank, job, type, urgency, score bar, estimate, wait and
          blocked reason, as 4.7.3 lists;
        - the header says how many are waiting, whether the optimizer is on ("Optimizer off:
          Jenkins' own order" when it is not), and whether live events are arriving;
        - a key to the bar's colours, and a Show the numbers switch that adds each contribution
          as a column;
        - a table from 768 px, and below that one stacked block per job, with the bar on its own
          line and labelled facts.
      - **What the plugin sends, shown as sent (D-060):**
        - the blocked reason verbatim;
        - a missing upstream job under the job's name;
        - unscored items listed as "Waiting without a score" and counted in the waiting total;
        - "Ranking unavailable" with the backend's reason, never an empty bar.
        - An empty queue invites a build through either assistant.
        - A failed load says why and offers Try again. A failed refresh keeps the last ranking
          and says from when.
      - **Live:** it asks again on `queue.changed`, `run.queued`, `run.started` and
        `run.finished`, and every 10 seconds, because the events cover only runs the backend
        started, and waits and aging grow between them (D-060). The bars grow once on first load
        and jump on a live update.
      - **Tests** run on 6 real `GET /api/queue` responses (`src/test/fixtures/queue.ts`).
        - **What they are:** the three rankings recorded from the live plugin
          (`backend/tests/data/plugin/`), each passed through the backend's own parser and
          endpoint in its test configuration. Three more: the same ranking with the optimizer off,
          an empty queue, and the plugin unreadable, with the real HTTP client's reason for a 404.
        - **The tests:** 14 for the page, 6 for the queue model, and one each for the score bar's
          growth and the time format.
        - **They catch breakage:** three mutations of the page each failed the test meant for
          them, and the file was restored byte for byte. The three were: no 10-second refresh, no
          live events, and bars that always grow.
      - **Checks:** `npm run lint`, `typecheck` and `build` are clean, and `npm run test` passed
        228 with no warning. `verify.py`'s four Phase 6 checks, run directly, all passed,
        including "228 tests passed" and "openapi.json is the backend's schema (39 paths)".
      - **Seen in a real browser:** headless Chrome, driven over its DevTools protocol. It loaded
        the built app from a throwaway server in the session's scratch folder, which answered
        sign-in and served the captured queue responses.
        - **Twelve screenshots** at 1440, 1024, 390 and 360 px, light and dark, covering every
          state. No page scrolled sideways, no console error was logged, and the live status
          reached Live.
        - **Faults found and fixed:**
          - with the numbers shown, job names broke at every hyphen into rows 140 px tall;
          - the table's first column sat 12 px off the page's 24 px gutter;
          - fixing that wrapped the blocked reason at 1440 px, until inner padding went from 12
            to 8 px.
        - **The growth, measured in Chrome:** `score-grow` ran for 0.24 s with ease-out, no bar
          was still growing a second later, and under reduced motion it ran for 0.01 ms.
        - The screenshots were not committed; T6.9 makes the real ones.
      - **The build:** the main chunk is 697 kB, against 683 kB before T6.6. The over-500 kB
        warning that predates T6.6 is still there.
      - **Not done:**
        - **Not seen against the running stack.** Signing in there needs the seeded admin
          password, which is in `.env`.
        - **The running backend container is still the old image,** from before D-057. Against it,
          this page would draw every bar empty beside the right score. It was not rebuilt.
- [x] T6.7 Jobs and runs, Analytics, Service catalog, Admin and Overview pages. Evidence, all run on
      2026-10-16 (D-061):
      - **Overview** (`/`), to DESIGN.md's sketch:
        - "jobs waiting" as the lead figure, then my active runs and how many of the last ten
          finished runs failed;
        - my active runs, each with its queue position and score bar, or its current stage;
        - the latest results, with Explain failure on a failed run;
        - the AI provider's status and detail, exactly as `/api/health` reports them.
      - **Jobs and runs** (`/runs`):
        - every chain, filtered by service, assistant and result, with the filters in the
          address;
        - a chosen run shows its run card (stages, result, Jenkins link), each job's run, the
          last 200 lines of its log (followed while Jenkins writes), and Explain failure.
      - **Analytics** (`/analytics`):
        - the run statistics, with "Not measured" where the backend measured nothing;
        - the stored experiments and each one's metrics;
        - the chatbot evaluation, which says that no endpoint serves its results yet.
      - **Service catalog** (`/catalog`): each service's repository, reachability with its live
        branches, default branch, agent label, suites, environments and extra stages, and an
        Admin-only resync.
      - **Admin** (`/admin`), listed and usable only for Admins:
        - users and roles, with no controls on your own row;
        - deactivation after a confirmation that says what happens;
        - adding a user, with the backend's refusals placed under the right field;
        - the HIGH quota and the rules in force, read-only;
        - the audit log, a page of 50 at a time.
      - **Shared:**
        - one API client context instead of one per page;
        - `DataTable`, which stacks every new table into labelled facts below 768 px;
        - the shared request helper of T6.6.
      - **Tests** run on 39 real responses (`src/test/fixtures/pages.ts`).
        - **How they were captured:** a temporary backend test, deleted after use, drove the
          backend in its test configuration. Approvals ran a freestyle chain whose unit tests
          failed on jenkins-dev's real recorded log. A second chain was left queued and a Pipeline
          left building. Users were created, changed and refused. The capture also read the
          catalog, health in three modes, and analytics.
        - **Experiments:** the two experiment rows were inserted the way the backend's own tests
          insert them. They are not results.
        - **Counts:** 62 new tests. The five pages have 44; the run, log, audit, catalog and role
          models 14; the time and percentage formats 3; and the role-based sidebar 1.
        - **They catch breakage:** three mutations each failed the tests meant for them, and every
          file was restored byte for byte. The three: everyone treated as an Admin (3 tests
          failed), the assistant filter ignored (2), and every active chain counted as mine (1).
      - **Checks:** `npm run lint`, `typecheck` and `build` are clean, and `npm run test` passed
        290 with no warning. `verify.py`'s four Phase 6 checks, run directly, all passed,
        including "290 tests passed" and "openapi.json is the backend's schema (39 paths)".
      - **Seen in a real browser:** headless Chrome, driven over its DevTools protocol, against a
        throwaway server in the session's scratch folder serving the built app and the captures.
        - **Fourteen screenshots** at 1440 and 390 px, light and dark, as an Admin and as a
          Developer. No page scrolled sideways, no table outgrew its box, and no console error
          was logged.
        - **Faults found and fixed:**
          - the run detail and its run card had the same accessible name, so the detail is now
            titled by its service and start time;
          - the audit log broke names mid-word, so targets now stay whole and details wrap;
          - a long id could overflow a stacked block at 360 px;
          - a duration that read "Took 0s" beside the card's "in 6s" is now "Start to finish";
          - the Overview's description promised "whether the AI provider is answering".
        - The screenshots were not committed; T6.9 makes the real ones.
      - **The build:** the main chunk is 746 kB, against 697 kB before T6.7. The over-500 kB
        warning that predates T6.6 is still there; splitting the routes would fix it.
      - **Not done:**
        - **Not seen against the running stack,** for the same reason as T6.5 and T6.6.
        - **No charts on Analytics:** no experiment data exists before Phase 7 (D-061).
- [x] T6.8 Vitest unit tests and Playwright flows (Part 4.7.6), run against the backend in fake
      mode. Evidence, all run on 2026-10-16 (D-062):
      - **The backend:** `backend/browser_backend.py`, the real app with LLM_MODE=fake.
        - **Stand-ins:** the backend tests' own in-memory Jenkins, plugin and Git, and a fresh
          SQLite database for each run.
        - **Accounts:** an Admin and a Developer, made up for each run by
          `frontend/playwright.config.ts`.
        - **Controls:** routes under `/__e2e`, on that process alone, set the plugin's ranking,
          switch the model off, and cancel running chains between flows.
        - **Sign-in keeps its real limit,** which the flows wait out.
      - **Eleven flows** (`frontend/e2e/`) in Google Chrome, against the built app served by
        `vite preview`:
        - **4.7.6's seven:**
          - sign in;
          - a freestyle deploy with a clarification ("Which service should I deploy?");
          - a Pipeline deploy with its Jenkinsfile;
          - the production refusal;
          - the AI fallback notice, with the model switched off;
          - approval with the keyboard alone;
          - the queue with a HIGH job above a LOW one.
        - **Failure states and roles:**
          - a wrong password answered precisely;
          - returning to the page that was asked for;
          - "Ranking unavailable" when the plugin cannot be read;
          - a Developer not offered Admin, and told why `/admin` is closed;
          - an Admin adding a user, which shows in the audit log.
      - **Results:**
        - all 11 passed in two consecutive full runs (1.6 minutes each), and the five assistant
          flows passed 15 of 15 when repeated three times;
        - three mutations of the app each failed the flow meant for them, and every file was
          restored byte for byte. The three were: the queue drawn in reverse, Admin offered to
          every role, and the fallback notice never shown.
      - **Faults the flows found in their own first drafts, fixed:**
        - wrong locators;
        - a toast matched twice, once in its screen-reader announcement;
        - a deploy expected to make three jobs when it makes one;
        - "Creates" expected where a second run truly says "Updates";
        - the sign-in limit hit by flows that did not wait.
        - Against the dev server, two flows saw the page come back empty after sending. They never
          did against the build, so the flows run against the build (D-062).
      - **4.7.6's Vitest half:** T6.4's tests for the intent card (7), clarification (3), composer
        (8) and score bar (9) still pass.
      - **Checks:**
        - **verify.py:** a new Phase 6 check, "the browser flows of 4.7.6 pass against the backend
          in fake mode", passed when run alone ("11 flows passed", 97 s). `--phase 6` now lists 76
          checks. `--phase 0` passes, and it now also requires the new "flows" job in CI.
        - **CI:** a new "Browser flows" job.
        - **The frontend:** `npm run lint`, `typecheck`, `test` (290) and `build` are clean.
        - **The launcher:** ruff, its format check and mypy are clean on it.
      - **Not done: flows that need the real stack.** None of these is covered in a browser:
        - a real Jenkins building and deploying;
        - the live plugin scoring a real queue;
        - real Git branches;
        - the live model (`GROQ_API_KEY`);
        - signing in as the stack's seeded Admin (its password is in `.env`).
        - Running the flows against the stack needs approval for rebuilding the backend image,
          which still has pre-D-057 code, and a frontend container (`frontend/Dockerfile` is still
          open).
- [x] T6.9 Screenshots of every screen in light and dark themes at 1440 px and 390 px, saved to
      `docs/screenshots/`, reviewed against `DESIGN.md`, with fixes applied. Evidence, all run on
      2026-10-16 (D-063):
      - **40 screenshots** in `docs/screenshots/`: 4.7.3's nine screens and the Admin page as a
        Developer finds it, each at 1440 and 390 px, light and dark.
        - **How:** `SCREENSHOTS=1 npx playwright test --project=screenshots` in frontend/, from the
          production build against the backend in fake mode, with made-up accounts.
        - **The data:** a freestyle chain under way, a failed run carrying jenkins-dev's real
          failing log, and a Pipeline first in the recorded ranking.
        - **Roles:** Developer for every screen but Admin, which is shown both as an Admin and as a
          Developer.
      - **Reviewed against DESIGN.md, screen by screen. Fixed, then the whole set made again from
        the final code and looked at:**
        - the theme switch ran 37px past the sidebar (229px in 192px); it is now three equal
          parts, words only;
        - the chat list printed 12-hour locale times ("Oct 16, 09:44 AM"), unlike every other page,
          and read API times as local; it now uses the shared 24-hour formatter;
        - an active chain between jobs read "Running" beside a job that had finished; it now says
          "Waiting to start" and names the next job;
        - the run detail's jobs list said "Not built" where the run card said "not started"; both
          now say "Not started".
      - **What the review found sound:**
        - no page scrolls sideways at 390 px, and wide tables and code views scroll in their own
          boxes;
        - both themes keep their contrast;
        - the stacked tables and the queue's bars read correctly.
        - The assistants' 390 px full-page capture showed the composer mid-page. That was the capture
          freezing a sticky bar, not the layout, so the assistants are captured as the screen a
          person sees.
      - **Checks:**
        - **verify.py:** a new Phase 6 check, "screenshots are present for every screen, in both
          themes at 1440 and 390 px", passed (40). All six Phase 6 checks passed when run directly,
          including "290 tests passed" and "11 flows passed", and `--phase 0` passes.
        - **The frontend:** `npm run lint`, `typecheck` and `build` are clean.
        - **One unit test timed out once.** `npm run test` failed one test in one of four runs, at
          its 5-second limit ("invites a first request, and makes the chat only when one is sent").
          It passed alone and in the next two full runs, 290 of 290. Recorded, not loosened.
      - **What the full gate found after a5519fa, and fixed (run on 2026-10-17, D-063):**
        - **Run 1, 75 of 76:** `verify.py` read subprocess output as cp1252, and Vitest's U+276F
          crashed the quality-bars check. It now reads UTF-8.
        - **Run 2, stopped after 72 checks:** printing a failure crashed on cp1252 stdout (now
          UTF-8). The failure was the test above, timed out at 5 s under the gate's load. It now
          types without per-key delays, and its file allows 15 s per test.
        - **Run 3, 76 of 77:** the keyboard flow showed an empty chat against the build. Its trace
          showed a race from T6.5: a new chat's address was opened before its first message was
          stored, and the chat's own load landed empty after the reply. The page now opens a new
          chat only once its first exchange is stored. A new Vitest test failed against the old
          order and passes now. D-062's guess (a dev-server reload) is corrected.
        - **After the fixes:** `npm run lint`, `typecheck` and `build` are clean; `npm run test`
          291 passed; `npx playwright test` 11 flows passed; the screenshots were made again from
          this code (16 of 40 changed, in times and ids only) and looked at.
        - **Run 4, on `86d9a8d` with a clean tree: ALL CHECKS PASSED, 77 of 77, exit code 0**
          (`python -u scripts/verify.py --phase 6`, 15:52 to 16:24). The real-Jenkins end-to-end
          suite took 16 minutes, and the plugin reported builds throughout. CI run 39026561925
          passed all six jobs on the same commit.
      - **Not done:**
        - **Lighthouse** (Phase 6 acceptance: 95 or more on both assistant pages) was not run in
          T6.9. A signed-in page needs Lighthouse driven through Puppeteer, whose dependencies the
          project did not have (D-063). Done on 2026-10-17; see the acceptance evidence below.
        - **The 745 kB main bundle:** loading pages lazily from the routes would fix it. It is
          documented, not done in T6.9 (D-063).
        - **Not seen against the running stack,** for the same reasons as T6.5 to T6.8.

**Acceptance:** all frontend quality bars pass; Lighthouse accessibility score of 95 or more on
both assistant pages; screenshots committed.

Acceptance evidence, all run on 2026-10-17:
- **Quality bars and screenshots:** `verify.py --phase 6` passed 77 of 77 on `86d9a8d`.
- **Lighthouse: 100 on both assistant pages, in all 16 audits (D-064).**
  - **How:** `LIGHTHOUSE=1 npx playwright test --project=lighthouse` in frontend/, with Lighthouse
    13.5.0 and puppeteer-core 25.12.0 (new, pinned dev dependencies). It runs against the build and
    the backend in fake mode.
  - **What:** Puppeteer signs in through the form in Chrome, and Lighthouse audits the same tab with
    storage reset off. Each assistant page is audited empty and with a chat that has a plan and a run
    card, in light and dark, at mobile and desktop settings.
  - **Guards:** each audit's final URL, heading and theme are asserted. The chat pages had 27 to 30
    applicable audits against the empty pages' 25.
  - **Negative control:** a throwaway copy of the spec planted a nameless button, an image with no
    alt and low-contrast text. All 16 audits flagged all three, scoring 86 to 89, and the test
    failed. The copy was deleted.
  - **verify.py:** a new Phase 6 check, "Lighthouse scores both assistant pages 95 or more for
    accessibility", passed when run on its own ("16 audits; lowest accessibility score 100
    (Freestyle), 100 (Pipeline)"). The gate now has 78 checks.
  - **Other checks after the change:** `npm run lint` and `typecheck` clean; `npx playwright test`
    11 flows passed; the screenshot spec, now using the helpers it shares with the Lighthouse spec,
    passed 4 of 4. Its output was not kept, since no screen changed.
- **The full gate, on `ff70254` with a clean tree: ALL CHECKS PASSED, 78 of 78, exit code 0**
  (`python -u scripts/verify.py --phase 6`, 16:47 to 17:13). Among them, the Lighthouse check:
  "16 audits; lowest accessibility score 100 (Freestyle), 100 (Pipeline)". CI run 39030064897
  passed all six jobs on the same commit.

Open in Phase 6, outside any one task: `frontend/Dockerfile`, and removing the `frontend` service's
Compose profile, which D-018 left for "once Phase 6 builds the image". Best done once the
screens exist, before T6.8's Playwright flows run against the stack.

Found in T6.3, for T6.7's Admin page:
- **There is no way to reset a password.** The sign-in page says "Forgotten your password? Ask an
  administrator", but no endpoint lets an administrator set a new password: `PATCH
  /api/admin/users/{id}` changes only the role and whether the account is active. An admin
  password reset needs a backend endpoint.
- [x] **The Admin entry is shown to every role.** The backend refuses non-admins, so this is not
      a hole. But a sidebar entry that ends in a refusal is a dead end. Fixed in T6.7 (D-061):
      only an Admin sees the entry, and anyone else who opens `/admin` is told why it is closed.

Found in T6.8 (D-062):
- **The backend uses a constant Starlette 1.7 deprecates.** `app/core/errors.py` line 197 sends
  validation errors with `status.HTTP_422_UNPROCESSABLE_ENTITY`, and every 422 logs a
  `StarletteDeprecationWarning` naming `HTTP_422_UNPROCESSABLE_CONTENT` instead. The status is still
  422, so nothing breaks yet. A one-line change, left for a backend task.

Found in T6.7 (D-061), for decisions outside the frontend:
- **No endpoint serves the chatbot evaluation's results,** though 4.4.4 lists "evaluation results"
  under analytics. T8.2 writes them; the Analytics page needs an endpoint (or a published file) to
  read them from.
- **No endpoint reports the rate limits** that 4.7.3 lists for the Admin page. They are constants
  in `app/core/ratelimit.py`. Reporting them, as the policy endpoint reports the HIGH quota, would
  let the page show them without copying them.
- **The health check cannot say whether the AI provider answers.** By design it reads the
  configuration and never calls the model, to save quota. DESIGN.md's Overview sketch ("Groq,
  answering") needs a signal the backend does not have, such as the outcome of the latest model
  call.
- **The API filters chains by service only, and runs by one job only.** Jobs and runs filters the
  newest 200 chains by assistant and result on the page, and says so when there are more. Filters
  on `GET /api/chains` would make them exact.
- **`JobResponse.service_id` names a service by an id the catalog never returns,** so a job cannot
  be shown with its service's name. Jobs and runs reads chains instead.

Found in T6.6 (D-060):
- **The Queue page cannot show a job held for its upstream.** `DependencyGate` blocks in
  `canRun`, so Jenkins keeps the held item among its blocked items. The plugin's ranking lists only
  buildable items, so the held job is neither ranked nor listed as unscored, and the page cannot say
  why it waits. DESIGN.md's Queue sketch has such a row ("Waits for fs-payment-service-build"). To
  show it, the plugin's API would have to list blocked items with their reason, a Phase 2 change.
- **A lone waiting job can show as unscored, or with an old score.** The sorter scores nothing when
  the optimizer is off or fewer than two items are buildable. `DynamicQueueSorter` returns early in
  both cases, and nothing else writes the heap. The ranking's wait is computed when it is asked
  for, but the score and the aging come from the last sort. With one job waiting, the page can show
  it as "Not scored by the optimizer", or show an aging bonus older than its wait. The run card's
  score comes from the same heap.
- **The sidebar's System theme button runs 13 px past the 240 px sidebar,** seen in Chrome at
  1440 px. This is T6.2's shell, for T6.9's review.

Found in T6.5:
- **The backend can return a reply before the message it answers.** `list_messages` orders by
  `created_at`, then by message id. The id is a random UUID. A message and its reply are written in
  one request, and on Windows both were stamped with the same time: the captured `/help` pair came
  back reply first. The thread now sorts user-before-reply on a tie (D-059). The backend fix is
  still to do: a sequence column, or a reply stamped after its message.

Found in T6.4, to settle before T6.5 and T6.6 show real scores:
- [x] **The backend read the plugin's score factors under the wrong names.** Fixed on 2026-10-15
      (D-057).
      - **The defect:** the backend read flat `urgencyFactor`, `agingBonus` and
        `estimateSeconds`. Those are the names of the plugin's metric events. The ranking
        endpoint nests the factors under `components` and gives `estimateMillis`. Against the
        live plugin every factor parsed as 0 and every estimate as unknown.
      - **Inspected:** `DynamicQueueApi.renderItem` and the plugin's own `ApiJsonIT`, which
        asserts the nested keys, against `parse_ranking`. 4.3.10 names the fields but gives no
        keys, so the backend's names had been guessed.
      - **Recorded:** three live responses from jenkins-dev, verbatim, in
        `backend/tests/data/plugin/`, recorded through the backend container's own client
        without handling the token:
        - three waiting items with real estimates (3.6 s, 2.9 s, 22.6 s);
        - an item that waited 300.8 s and earned 0.05 aging;
        - a dependency group of two, where the MEDIUM upstream inherits 0.979994 over its own
          0.800, with three unscored Pipeline items counted in `queueLength` 8.
      - **Fixed:**
        - the parser reads the plugin's names, plus `ownScore` and `unscoredItems`;
        - `/api/queue` gains `components.own_score` and `unscored_items`;
        - the chain detail's queue block gains `base_score`, `own_score` and the weights;
        - the frontend's score bar uses the plugin's own score for the inherited tick.
      - **Checked:**
        - 16 tests on the recordings, 15 for the parser and client and one through
          `/api/queue`, including that weight times factor plus aging equals the plugin's own
          score for every recorded item;
        - 9 of them fail with the old names;
        - a fresh live response parsed by the fixed parser inside the container matched its raw
          fields;
        - backend: ruff, format and mypy clean, offline suite 1653 passed;
        - frontend: lint, typecheck and build clean, 180 tests.
      - **Not done:** the running backend container still has the old parser until its image
        is rebuilt (`docker compose build backend`). Nothing reads `/api/queue` from the stack
        until T6.5 and T6.6.
- [x] **T6.5 needed the assistant payloads typed in the API schema first (D-056).** Done on
      2026-10-15 (D-058).
      - **Inspected:** every producer:
        - `ParseOutcome.to_record`;
        - `describe`, the `/help` shortcut and the status, rerun and cancel handlers in
          `conversations.py`;
        - the pipeline and approval messages, `_progress` and `ValidationReport.to_record` in
          the generation code;
        - `run_card` and `cancel` in `chains.py`.
      - **Typed** in `backend/app/api/payloads.py`:
        - the message payload as a union of 11 reply models (`help` and `run` each have two
          producers);
        - the intent record, using the parser's own `Intent`;
        - the progress line and the validation report;
        - the run card the status reply carries, and the cancel result.
        - They are used by `MessageResponse`, `CommandResponse`, `PipelineResponse`,
          `GET /api/chains/{id}` and its cancel. The shapes stay flat, as stored.
      - **Checked:**
        - `test_payloads.py` runs real flows through the API, reads back everything stored, and
          requires each item to dump back unchanged and all 11 kinds to appear. Removing one
          field from a model fails it.
        - The 146 API tests that produce these shapes pass through the typed responses.
        - Backend: ruff, format and mypy clean, offline suite 1658 passed.
        - The frontend's `IntentFields`, `ProgressStep` and `ValidationCheck` are now the
          generated types. Lint, typecheck and build are clean, and 180 tests pass.
      - **Not proven:** the stack's database held no messages, commands or pipelines (0 rows),
        so no older stored row could be checked.

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
- ~~The JCasC floating-point import defect (D-017)~~ Resolved 2026-10-18: quote the values.
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
  - **What a recovered failure leaves behind:** its error stays in the build's log. Since D-053,
    Explain failure does not read a checkout attempt that Jenkins retried, so the error neither
    reaches the model nor takes the blame for a later failure.

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
- 2026-10-14 T6.2 done: the frontend project, tokens, shell, routing, generated API client and
  WebSocket client, with three new `verify.py` checks run directly and passing, and CI guarding
  the API types. Next: T6.3 onward builds screens, so it waits for DESIGN.md's approval. The full
  Phase 6 gate also needs a re-run once the machine has the memory for it.
- 2026-10-15 The user approved `frontend/DESIGN.md` as written; D-052 is accepted (`c2b7e4f`).
  `verify.py --phase 6` then printed ALL CHECKS PASSED, 75 of 75, on `c2b7e4f`. Next: T6.3.
- 2026-10-15 T6.3 done: sign in, session handling and sign-out (D-054), with the API's error
  shape now in the OpenAPI schema (D-055). The four Phase 6 checks pass when run directly, with
  92 frontend tests. The offline backend suite passed 1644. Found for T6.7: there is no password
  reset, and the Admin entry is shown to every role. Next: T6.4.
- 2026-10-15 T6.4 done: the shared assistant workspace components, the score bar, and CodeMirror
  code views, with 87 new tests (179 in all) and the four Phase 6 checks passing when run
  directly. Found: the backend reads the plugin's score factors under names the plugin never
  sends, so live score bars would be empty (Phase 6 open items). Also, T6.5 needs the assistant
  payloads typed in the API schema first (D-056). Next: those two, then T6.5.
- 2026-10-15 The ranking parser fix (D-057): the plugin's real names, three live responses
  recorded as fixtures, and `own_score` and `unscored_items` in `/api/queue`. Next: type the
  assistant payloads (D-056), then T6.5.
- 2026-10-15 The assistant payloads are typed in the OpenAPI schema (D-058): message payloads,
  the intent record, the progress line, the validation report and the run card. Each was checked
  against what real flows store. Next: T6.5.
- 2026-10-16 T6.5 done: both assistant pages on the shared workspace, tested against 19 captured
  real responses, with 206 frontend tests and the four Phase 6 checks passing when run directly
  (D-059). Found: the backend can order a reply before its message. Next: T6.6.
- 2026-10-16 `verify.py --phase 6` printed ALL CHECKS PASSED, 75 of 75, on `f43f0db`. The first
  attempt had been stopped for low memory. CI run 38792947715 passed all five jobs. Next: T6.6.
- 2026-10-16 T6.6 done: the Queue page, tested against 6 real queue responses, with 228 frontend
  tests and the four Phase 6 checks passing when run directly, and seen in headless Chrome at four
  widths in both themes (D-060). Found: a job held for its upstream never reaches the ranking, and a
  lone waiting job can go unscored. Next: T6.7.
- 2026-10-16 T6.7 done: the Overview, Jobs and runs, Analytics, Service catalog and Admin pages,
  tested against 39 captured real responses, with 290 frontend tests and the four Phase 6 checks
  passing when run directly, and seen in headless Chrome (D-061). The Admin entry now shows for
  Admins only. Found: no endpoint serves the evaluation results or the rate limits, and the health
  check cannot say whether the AI provider answers. Next: T6.8.
- 2026-10-16 T6.8 done: eleven browser flows in Chrome against the backend in fake mode
  (`backend/browser_backend.py`), passing in two full runs and 15 repeats, with a new Phase 6 check
  and a "Browser flows" CI job (D-062). 4.7.6's Vitest half was already covered. Not covered in a
  browser: a real Jenkins, the live plugin, the live model and the stack's own frontend. Next: T6.9.
- 2026-10-16 T6.9 done: 40 screenshots of ten screens at 1440 and 390 px in both themes, made from
  the build and reviewed against DESIGN.md. The review fixed four faults, among them the theme
  switch running out of the sidebar, and a new Phase 6 check covers the screenshots (D-063).
  Lighthouse and the 745 kB bundle are recorded, not done. Next: the full Phase 6 gate.
- 2026-10-17 The full Phase 6 gate failed three times, and each failure is fixed: `verify.py` now
  reads and writes UTF-8, a slow unit test no longer types key by key, and a race in the assistant
  page that could show a new chat empty, there since T6.5, is fixed with a test that catches it
  (D-063). 291 unit tests and 11 flows pass; the screenshots were made again.
- 2026-10-17 `verify.py --phase 6` printed ALL CHECKS PASSED, 77 of 77, exit code 0, on `86d9a8d`.
  Open in Phase 6: Lighthouse. Next: Lighthouse on both assistant pages.
- 2026-10-17 Lighthouse: 100 for accessibility on both assistant pages, in 16 audits (empty and with
  a chat, light and dark, mobile and desktop), signed in through Puppeteer in the audited tab. A
  planted-violation control was caught in every audit. A new Phase 6 check runs it (D-064). Next:
  the full 78-check gate.
- 2026-10-17 `verify.py --phase 6` printed ALL CHECKS PASSED, 78 of 78, exit code 0, on `ff70254`.
  Phase 6's acceptance is met. Still open in Phase 6, outside any task: `frontend/Dockerfile` and
  the Compose profile, and the flows against the running stack (needs approval to rebuild the
  backend image).
