# Decisions

Every decision taken while building, and every conflict found between `BUILD_PROMPT.md`, the report
in `docs/report/` and `legacy/m2-poc/`. Newest first within each phase.

Sources of truth, in priority order (`BUILD_PROMPT.md` 1.2): this file's parent specification
`BUILD_PROMPT.md`, then the report, then the legacy code. When sources conflict the higher one wins,
the conflict is recorded here, and any needed report change goes in `docs/report-updates.md`.

---

## Phase 7

### D-078 A stock-Jenkins controller for the sanity arm: the controller image without the optimizer
**Date:** 2026-10-23 · **Status:** proposed (Phase 7, branch `phase-7-stock-jenkins`), until its
pull request is approved

**The need.** Part 4.8.2's matrix ends with one sanity run: freestyle-30 on one executor, warm, on
"stock Jenkins, no plugin". Part 4.8's baseline arm is the plugin installed with
`optimizerEnabled = false` (observe-only), "plus one stock-Jenkins sanity run".
- **Why the baseline stays observe-only:** both arms then share one measurement path, the plugin's
  own events. Milestone 2's baseline was Jenkins without the plugin, so any difference between its
  arms could have come from the instrumentation rather than the scheduling.
- **What the sanity run is for:** observe-only rests on one assumption: that the plugin, installed
  and recording but not ordering, schedules as Jenkins does without it. Only Jenkins without the
  plugin can test that.
- **Why no existing controller could serve:** the controller image always installed the plugin,
  and its entrypoint reinstalls it on every start (D-028), so removing it from a home would not
  survive a restart. Every JCasC file also configures the optimizer, and with the plugin absent,
  configuration as code finds no configurator for that block and refuses to start Jenkins.
- **Why it is recorded here:** Part 4.2.3 names the Compose services: six by default, and an
  `experiment` profile of two controllers with one agent each. A third controller departs from it.

**The decision.**
- **One image, two stages.** `jenkins/controller/Dockerfile`'s `stock` stage is the pinned Jenkins
  LTS with plugins.txt's plugins, the configuration folders and environment, and the base image's
  own entrypoint (tini, then `jenkins.sh`). The `optimizer` stage is built from it, and adds only
  the plugin, the script that reinstalls it, and that script as the entrypoint.
  - Every existing controller builds the last stage, as before. `jenkins-stock` alone builds
    `stock`.
  - So the stock controller differs from the others by the plugin alone, by construction rather
    than by keeping two files in step: the same Jenkins 2.568.3, and the same 79 plugins at the same
    versions.
  - The optimizer image's content did not change. Every file in its seed folder (owner, mode and
    size), the install script, the entrypoint, the user and the ports match the image the
    one-stage Dockerfile built. The one difference is the `.hpi`'s build stamp, from a later Maven
    build of the same source.
- **One configuration file.** `jenkins/casc/experiment-stock.yaml` is `experiment-baseline.yaml`
  without the `dynamicQueueOptimizer` block, and with its own agent (`stock-agent`), URL and
  system message.
- **One Compose profile, `stock`.** It holds `jenkins-stock` (127.0.0.1:8088) and `stock-agent`,
  with the named volumes `jenkins-stock-home` and `stock-agent-work`.
  - **Its own profile:** `--profile experiment` starts nothing more than it did, so the stock
    controller's memory is spent only when asked for: about 0.5 GB, and 80 MB for its agent. This
    machine has stopped gate runs for low memory before.
  - **Port 8088:** 8087 is jenkins-dev's, and the sample services use 9001 and 9002.
  - **Shared with the other controllers:** the secrets, `AGENT_EXECUTORS`, and Compose's default
    network, on which each controller reaches only the agent its own JCasC names.
- **The harness.**
  - `--controller stock` now names the controller.
  - `smoke --controller stock` runs T7.6's smoke workload on it. `smoke` alone still runs T7.6's
    two controllers.
  - Nothing else was needed: since T7.2, the harness reads a controller with no `/dynamic-queue` as
    the stock arm and analyses its runs from REST alone.

**Two things the sanity comparison must allow for.**
- **The stock arm measures queue entry differently.** A stock run has no plugin events. Each job's
  queue entry is when the harness sent its trigger request, not the plugin's `inQueueSince`; build
  start and end come from Jenkins in every arm. So the stock arm's waits and makespan include the
  request's latency and any offset between the host's clock and the controller's, milliseconds
  against waits of tens of seconds. Compare it with observe-only first on what both measure alike:
  Jenkins' own build start and end times.
- **Stock Jenkins drops the plugin's job property.** The harness's jobs carry it, since every arm
  runs the same jobs. Stock Jenkins accepted all six with `createItem` and stored them without it,
  logging nothing. No job's dependencies are enforced there, as in observe-only.

**Three more limits, found reviewing the pull request (2026-10-24).**
- **Freestyle only.** A Pipeline job's script names the plugin's `dynamicQueuePriority` option,
  which stock Jenkins cannot resolve, so `pipeline-30` and `mixed-30` fail there. The sanity run
  is `freestyle-30`, so nothing in the matrix needs them.
- **Process supervision differs.** The stock stage keeps the base image's tini as PID 1, while the
  optimizer stage's entrypoint `exec`s `jenkins.sh`, so Java is PID 1 there, as it always was. This
  touches signal handling and zombie reaping, not scheduling.
- **The report shows the sanity run alone.** `report` groups runs by condition, group included, so
  the `sanity` run is not set beside observe-only automatically. Compare it with the `main` group's
  freestyle-30, 1-executor observe-only runs, which share its workload, executors, history and
  order.

**What it changes in verify.py (95 checks to 100).**
- **Phase 1:**
  - The Compose check now reads "matches Part 4.2.3 and D-078". It requires the `stock` profile,
    port 8088, and the stock controller's own home, configuration and agent; no two controllers may
    share a home, and no two services a port. Today it reports 12 services, 6 default and 6
    profiled.
  - The file list counts 12. The loopback check counts 7 ports.
  - **New:** the stock JCasC is the baseline's without the optimizer.
  - **New:** the Dockerfile's optimizer stage adds only the plugin, and Compose builds the stock
    stage for `jenkins-stock` alone.
- **Phase 7:**
  - **Three new checks,** which need the stock profile running:
    - the stock controller and its agent run the current build;
    - the optimizer is in neither its image, its home nor its plugin manager, and `/dynamic-queue`
      does not exist, while Jenkins and every other plugin match `jenkins-plugin`'s, where the
      optimizer is active;
    - its smoke run completes, is analysed into the same figures from the same version of the
      workload, and its dependency violations agree with a recount from `builds.json`.
  - **`latest.json`'s check** now expects the last run the gate analysed, so it passes whichever of
    the two smoke runs came last.
- **What the gate now needs running:** both profiles, so
  `docker compose --profile experiment --profile stock up -d`.

**Evidence (2026-10-23, on battery power, so short runs only; PROGRESS.md has the detail):**
- **`jenkins-stock`:**
  - healthy in 28 s, with no SEVERE line;
  - 79 plugins and no optimizer in its image and its home;
  - `/dynamic-queue` answers 404;
  - its agent is online with one executor.
- **The three existing controllers** were recreated on the two-stage image, and the plugin loaded on
  each.
- **`verify.py --phase 1`:** 33 of 33.
- **Phase 7's nine checks, in one process and in the gate's order:** 9 of 9. Freestyle-6's
  makespan and mean wait: stock 52.5 s and 18.7 s, observe-only 52.3 s and 18.5 s, optimized
  52.2 s and 20.5 s.
- **The new and changed checks fail when they should:** 16 of 16 faults in copied files, and 8 of 8
  live cases.
- **The experiment package:** 120 tests, ruff and strict mypy clean.
- **Not yet run:** the full `verify.py --phase 7`, which needs mains power.

**Not changed:** BUILD_PROMPT.md, which this record departs from; the plugin; the three existing
JCasC files; and how every existing controller behaves.

---

### D-077 A new controller home gets every plugin: the entrypoint leaves the image's REF alone
**Date:** 2026-10-23 · **Status:** accepted (Phase 7)

**Found by:** starting the experiment profile's two controllers for the first time, for T7.6. Both
came up with no agent executors and no `/dynamic-queue` (404), so the harness read them as stock
Jenkins.
- **The defect (DF-46):** `jenkins/controller/install-plugin-under-test.sh` (D-028) held the
  plugin's path in a variable named `REF`. The stock image exports `REF=/usr/share/jenkins/ref`,
  the folder `jenkins.sh` seeds a new home from, and assigning to an exported variable exports the
  new value. So `jenkins.sh` seeded each new home with one file, the optimizer:
  - its seed log lists a single INSTALLED line, and the home held 1 of the image's 80 plugins;
  - the optimizer failed to load ("Plugin is missing: structs");
  - configuration as code, itself one of the 80, was not installed, so the agent and accounts its
    YAML defines did not exist.
- **Why nothing caught it before:** the script came with T3.6 (2026-10-07). jenkins-dev's home was
  first seeded on 2026-09-29, and seeding copies only what a home lacks, so jenkins-dev never
  showed it. The experiment controllers' volumes were the first homes made since. Rebuilding the
  dev stack on a new machine, or after losing its volume, would have hit the same failure.

**The fix:** the variable is now `IMAGE_PLUGIN`, and the script explains why no variable there may
be named `REF`.
- **Guarded:** verify.py's Phase 3 check of the entrypoint now fails on any assignment to `REF`. Run
  against the old script, taken from git, it fails.

**Evidence (2026-10-23):**
- After the rebuild, each new home holds all 80 plugins.
- Both controllers report their arms, observe-only and optimized, with one executor each.
- The smoke run completed on both.
- The entrypoint check passes on the fixed script.

---

### D-076 The plugin counts a build's own executor waits, and reports its version
**Date:** 2026-10-23 · **Status:** accepted (Phase 7)

**Found by:** building the Phase 7 harness's Pipeline figures, which BUILD_PROMPT 4.8.4 asks for:
the first node block's wait and the sum of all node-block waits.
- **The defect (DF-45):** `RunMetricsRecorder` summed every QUEUE_LEFT event in its 500-event ring
  that carried the job's name. The ring also holds the job's earlier builds, such as an experiment's
  warm-up runs and earlier repetitions, so a build's waits included theirs.
  `RunMetricsRecorderTest` shows it: without the fix, a freestyle build reports 5,700 ms for its
  700, and a Pipeline 4,000 ms for its 1,000.
- **Who read the fields:** nothing yet. The backend ignores them (only a comment in
  `app/services/metrics.py` mentions them), so no figure in the product or the report was wrong.
  The experiment would have been the first reader.

**The fix:** a wait belongs to a build when it is the build's own queue item (`Run.getQueueId()`,
how a freestyle job waits), or a node block that entered the queue after the build started (how a
Pipeline waits).
- **The harness does not rely on it:** it recomputes every wait from the raw events, matched to
  each build the same way, so each figure can be checked against the rows it came from
  (`experiment/records.py`).

**And the plugin reports its version.** Every experiment run records the plugin version and the
commit it was built from (BUILD_PROMPT 4.8.3), but the bot account cannot read the plugin manager,
which answers it 403. So `/dynamic-queue/health` now gives both, to the same readers as the rest of
the endpoint:
- **`pluginVersion`:** the version without the "(private-commit-user)" note a development build
  carries. The commit is reported on its own, and the user name is no business of the experiment's.
- **`pluginBuild`:** the manifest's `Implementation-Build`, the commit.

The plugin is found by its short name: under the test harness, a lookup by class finds nothing,
which `ApiJsonIT` caught on the first attempt.

**Evidence (2026-10-23):**
- `RunMetricsRecorderTest`: 4 passed. With the fix disabled, the two tests that cover it fail as
  above.
- `ApiJsonIT.healthReportsCounters`: the version carries no build note, and the build is a commit.
- `mvn -B verify`: BUILD SUCCESS, with 125 unit tests (1 skipped, the generated harness check, as
  before) and 97 JenkinsRule tests passing, SpotBugs at 0 and Spotless clean.

---

## Phase 6

### D-075 Known vulnerabilities in Vite's development server are fixed within the cooldown
**Date:** 2026-10-22 · **Status:** accepted (hardening of Phases 1 to 6; Phase 6)

**Found by:** `npm audit`, the frontend-audit step of the testing chapter's evidence campaign at
`31eb935`.
- **The finding:** one high vulnerability, `vite` 8.3.0 to 8.3.2, made of six advisories against
  Vite's development server:
  - command execution through its editor launcher on Windows (GHSA-r825-w8mm-5pxw,
    GHSA-698v-4r3x-3vcv, GHSA-587h-7wmj-h5pm);
  - cross-origin script execution through custom middleware (GHSA-9jrq-w75r-8gcw);
  - files outside `server.fs.allow` served (GHSA-rq7h-c2jc-7f22);
  - the start of files exposed through `?vite-wasm-instance` (GHSA-vfpm-58rq-9qcg).
- **Exposure:** the stack's frontend is the static output of `vite build`, served by nginx, so the
  product as deployed was not exposed. Developers and the tools that start the development server
  were, on this Windows machine above all.

**The fix:** `vite` 8.3.4.
- **Why not 8.3.5:** npm's suggested fix was published on 2026-10-21, inside the seven-day cooldown.
- **Why 8.3.4 is enough:** it is outside the vulnerable range and is the newest release the cooldown
  allows. No exception was needed, unlike D-071.
- **What changed:** only Vite's entry in the lock. Its new dependency ranges are met by the versions
  already locked.

**Evidence (2026-10-22):**
- `npm audit`: 1 high before, 0 after.
- The frontend's lint, typecheck and build are clean, and its 296 tests pass.
- The frontend image was rebuilt with it, and the gate's Phase 6 image and nginx checks pass.

---

### D-074 The migrations are proved against the models, and every downgrade is run, on PostgreSQL
**Date:** 2026-10-22 · **Status:** accepted (hardening of Phases 1 to 6; Phase 3)

**The gap.**
- **A test that never ran.** `test_migrations.py` begins by saying it closes a gap: every other
  test builds its schema from the models, so a model changed without a matching migration would
  pass them all until it reached a real PostgreSQL. The test meant to close it,
  `test_alembic_upgrade_matches_the_models`, was a placeholder that always skipped. So every
  integration run reported one skipped test and checked nothing.
- **A gate check that ran nothing.** "Every migration is reversible" only read each `downgrade()`
  for an `op.` call, and said "all downgrade cleanly" though no downgrade had ever run.
- **How it was found:** the evidence campaign's register listed the one skipped integration test,
  and its reason pointed at the placeholder.

**What the tests now do**, on a throwaway database of their own on the stack's PostgreSQL (dropped
afterwards, so nothing the stack or the end-to-end suite stores is touched):
- **`test_alembic_upgrade_matches_the_models`:** runs `alembic upgrade head` on a fresh database,
  and asks alembic's own autogenerate comparison what it would change to match `Base.metadata`,
  types included. The answer must be nothing. Every table Part 4.4.3 names must exist.
- **`test_every_migration_downgrades_and_upgrades_again`:** upgrades, downgrades to base (which must
  leave no table but alembic's own), upgrades again, and compares again. A type or index a downgrade
  forgot would make the second upgrade fail.

Like the other integration tests, they skip without a stack. The gate's check now runs both after
its file scan, and counts a skip as a failure.

**Evidence (2026-10-22):**
- Both passed on the stack's PostgreSQL 16 in 6.6 s.
- Each was shown to catch its defect, then restored byte for byte:
  - a column added to a model with no migration failed the first test, which named it
    (`add_column`, `services`, `mutation_probe`);
  - a `drop_table` removed from the first migration's `downgrade()` failed the second, as
    `alembic downgrade base` itself failed.
- Then both passed again, and the gate's check passed through them.

---

### D-073 What experiments E1 to E3 found about three of the report's claims
**Date:** 2026-10-22 · **Status:** accepted (the testing chapter's experiments; no code change)

The testing chapter ran three experiments in its evidence campaign at `31eb935`
(`plugin/src/test/java/.../experiment/`, run on request only). Three of their findings bear on
what the report says, and none is a defect in the code. Each is recorded here, as a conflict between
the report and the built system, with its report change in `docs/report-updates.md`.

**1. The plugin's cost (E1, inside a real Jenkins).** Report Section 6.6 says every operation
completes "in microseconds to a fraction of a millisecond, so the plugin adds no measurable
overhead", assuming *h*, the history an estimate examines, is at most 50. Measured:
- **The routine pass bears the claim out.** With 30 items queued, a queue-maintenance pass took
  0.20 ms with the optimizer off and 0.25 ms with it on (medians).
- **The full rescore does not.** It took 2.1 ms at 30 items and 82 ms at 200. It runs when the queue
  changes, and at most once a rescore interval otherwise.
- **Section 6.6's *h* is the odd one out.** The code reads up to 50 builds of *every job on the
  controller*, as report Section 6.5 says ("at most the last 50 builds per candidate job"), so *h*
  grows with the number of jobs. The cost tracked queued items × history records.
  `BUILD_PROMPT.md` 4.3.5's "up to `historyWindow` recent builds across all jobs" reads either way;
  the code takes Section 6.5's reading.
- **No code change.** Only Section 6.6's *h*, and its sentence on overhead, need correcting.

**2. Aging under sustained load (E3, a simulation).** Report Section 6.2 gives the aging bonus the
job of preventing starvation. Over two hours of random arrivals on one executor:
- **The result:** with aging on and off, every mean wait agreed within 2% at each of four
  utilisations, and the LOW band's longest wait at 95% utilisation was 1,253 s both ways.
- **Why:** the bonus is the same for every band and caps at 0.15 after 15 minutes. Under load, the
  long-waiting jobs of every band sit at the cap together, and 0.15 is less than the urgency gap
  between LOW and HIGH (0.35).
- **No code change:** CLAUDE.md fixes the formula to the report's.

**3. Milestone 2's headline result (recomputed from its files, and E2).** Its HIGH band's wait fell
from 271.5 s to 39.1 s.
- **The broken edges:** the same run started a job before a job it depends on had finished on 19
  of the workload's 20 dependency edges. Milestone 2 never measured this.
- **What respecting dependencies costs:** in simulation on the same workload, no policy that
  respects dependencies got the HIGH band below 155.9 s. Version 2's optimizer reached 176.7 s
  with no edge broken, against FIFO's 271.5 s.

**Also measured, and consistent with the report:** the algorithm alone (E1b) scored, sorted and
heaped 200 items in 83 µs, and 3,200 in 1.6 ms, growing as O(n log n). The simulator was
validated against Milestone 2's measured runs before it was used: FIFO within 0.1 s a band, and a
replay of its plugin's order within 5 s a band.

---

### D-072 The optimizer has a settings page, every setting on it does something, and Maven jobs are tested
**Date:** 2026-10-22 · **Status:** accepted (hardening of Phases 1 to 6; Phase 2)

**The defect.** `BUILD_PROMPT.md` Part 2.2 lists Milestone 2's known problems, to be fixed and never
repeated. Problem 4 includes "the global configuration page", and T2.2 asks for
`OptimizerConfiguration` "(global configuration and JCasC)".
- **What existed:** the class, its fields, configuration as code and the form checks.
- **What was missing:** a view. Its resource folder had been created empty on 28 September and never
  held a file.
- **The consequence:** Manage Jenkins showed no optimizer section, so the 15 settings of report
  Appendix D could be changed only through configuration as code, and no page could reach the form
  checks that `OptimizerConfigurationValidationIT` tests.
- **How it slipped through:** T2.2 had been ticked on the class alone.

It was found while checking the testing chapter's statement that the plugin has a global
configuration form.

**What was added:**
- **A settings page.** `config.jelly` for `OptimizerConfiguration` adds a Dynamic Queue Optimizer
  section to Manage Jenkins > System, with all 15 settings in Appendix D's terms. Numbers use
  Jenkins' number input, and fractional ones pass `step="any"` through to it, so that the browser
  does not mark 0.05 invalid. The token is a password field. The titles avoid parentheses: in a
  Jelly `${%...}` text they would be read as message arguments.
- **The weight warning now follows the form.** The three weight checks summed the *saved* weights.
  That meant nothing while there was no form, and on a form it would warn about the last save, not
  the values being typed. Each check now takes the other two weights as query parameters, which the
  page sends with it.

**A setting that did nothing now does what it says.** `rescoreIntervalSeconds` (Appendix D, 60) was
reported by the API and set by configuration as code, but nothing read it: the sorter's cache key
used a fixed minute. Showing it on a page would have offered a control with no effect. The key now
uses the interval's time bucket, `DynamicQueueSorter.rescoreBucket`. At the default of 60 that is
the current minute, exactly as `BUILD_PROMPT.md` Part 4.3.7 step 2 states, and all three JCasC files
set 60, so the stack's behaviour is unchanged.

**Maven jobs had never been queued in a test.** Part 2.3 promises freestyle, Maven and Pipeline
jobs, T2.4 asks `JobResolver` to handle all three, and the resolver's comment said Maven jobs "only
ever take branch one". No test had made one.
- **The new test:** `MavenPriorityIT` queues a LOW Maven job, a MEDIUM freestyle job and a HIGH
  Maven job, in that order, on one executor, and asserts the order they are dispatched in.
- **What it needs:** the Maven Integration plugin, as a test dependency at the BOM's version. The
  builds themselves fail at once, since no Maven installation is configured, but dispatch order is
  decided first.
- **Not covered:** a Maven job's modules built in parallel. Maven jobs do that only when told to,
  and those modules queue as jobs of their own.

**Evidence (2026-10-22):**
- **Each new test failed on the defect it guards,** with the code changed back on purpose, and
  passed once restored byte for byte:
  - with the page removed, `thePageHasEverySetting` failed and `aValueTypedOnThePageIsSaved` errored;
  - with the weight check summing saved weights, `weightsAreCheckedSinglyAndTogether`,
    `theWeightWarningFollowsTheForm` and the page's weight check failed;
  - with the bucket fixed at a minute, `RescoreBucketTest` failed 2 of 3 (the third is the default
    case, unchanged by design);
  - with Maven jobs left unresolved, `MavenPriorityIT` failed, dispatching
    `[fs-medium, mvn-low, mvn-high]`.
- **`mvn -B clean verify`:** BUILD SUCCESS, 121 unit tests (1 skipped) and 97 integration tests,
  SpotBugs 0, Spotless clean. Jenkins' own `InjectedTest` now parses three views.
- **jenkins-dev was rebuilt with this plugin.** The gate's Phase 1 image check, which compares the
  page as well as the classes, passes. So do its bot-token, executor, agent, ranking, health and
  metrics checks.

---

### D-071 A known vulnerability in `certifi` is fixed inside the seven-day cooldown
**Date:** 2026-10-22 · **Status:** accepted (hardening of Phases 1 to 6; the testing chapter's
security testing)

**Found by:** `pip-audit` 2.10.1, run for the testing chapter on the 49 packages the backend image
installs (`uv export --frozen --no-dev --no-emit-project`, audited with `--require-hashes
--disable-pip`). It was the first known-vulnerability scan of the backend's dependencies; the
frontend's had been scanned with `npm audit` since T6.2.

**The vulnerability:** `certifi` 2026.7.22, which `httpx` brings in, carries PYSEC-2026-4320
(GHSA-6q48-6c7w-9gw2).
- **The flaw:** its CA bundle trusts `emSign ECC Root CA - G3`, under which eight intermediate CAs
  have compromised private keys. Anyone holding one of those keys, and on the network path, could
  present a valid-looking certificate for any host.
- **Where the backend is exposed:** it trusts that bundle when it calls the model provider over HTTPS
  (`httpx`, through the `openai` client), and its API key travels on those calls.
- **Where it is not:** it reaches Git hosting through the `git` command, which has its own trust
  store, and Jenkins over plain HTTP inside the stack.

**The conflict:** the fix, `certifi` 2026.10.19, was three days old. Every pin in this project is
the newest release at least seven days old (`docs/versions.md`), so that problems in a new release
have time to surface.

**Why it was taken anyway:** the cooldown guards against what a new release might contain, and for
this package that can be checked directly. The new wheel was downloaded beside the locked one, whose
hash matches `uv.lock`, and every file was compared:
- `core.py` is identical;
- `__init__.py` differs only in its version string;
- the CA bundle differs only by the removal of `emSign ECC Root CA - G3`: 121 roots before, 120
  after, nothing added;
- the rest is packaging metadata (the generator's setuptools version).

A known way to impersonate any host, against a change that can be read in full and removes one
certificate: the fix wins, and the exception is limited to this package.

**The lock was written by the project's own uv.** `uv lock --upgrade-package certifi` changed only
certifi's entry, and the locked wheel's hash is the one inspected. It ran with uv 0.12.20 from
`.venv-tools/`, which the backend image also uses. A first attempt with the uv on the machine's
PATH, 0.12.24, also raised the lockfile's format revision from 3 to 5. It was discarded, since an
older uv may not read the newer format.

**Evidence (2026-10-22):**
- `pip-audit` found 1 known vulnerability in 49 packages before the change and none after
  (`docs/testing/evidence/pip-audit-backend-before.json`, `-after.json`).
- The 4 live tests passed against the real model provider over TLS with the new bundle.
- The offline suite: 1730 passed.
- The backend image was rebuilt and runs `certifi` 2026.10.19, and the gate's Phase 3 image check
  passes.

---

### D-070 The gate checks that the stack runs what the current source builds
**Date:** 2026-10-22 · **Status:** accepted (hardening of Phases 1 to 6)

**The defect.** Gate checks that drive the running stack, the stack system tests among them, prove
nothing about a commit if a container runs an image built from older source, and nothing checked
for that. Preparing the testing chapter's evidence on 2026-10-21, the frontend container turned out
to be serving a build from before three frontend commits (`217c78f`, `88a6a9a`, `deded23`). The
Queue page's held-jobs list (D-066) was absent from its bundle, and the system tests had passed
against it. The backend and jenkins-dev were current.

**Three checks now ask, one per phase that first drives the container:** Phase 1 for jenkins-dev and
its agents, Phase 3 for the backend, Phase 6 for the frontend. Each fails with the command that
fixes it.

**Content, not time.** Comparing an image's build time with the last commit to its sources was tried
first and fails both ways. An image built from the working tree just before its commit reads as
stale, which is how this project usually works: the agents were built 16 minutes before their commit
and are byte for byte current. And a rebuild served from cache keeps the old build time, so "stale"
could never be cleared. Instead:
- **The backend, the frontend and the agents:** the check builds the service, and compares the
  image that results with the image digest Compose recorded on the container when it created it
  (the label `com.docker.compose.image`). Docker's build cache returns the same image when nothing
  the build reads has changed. The container's own `Image` field cannot be compared, because this
  machine runs Docker's containerd image store, where that field names the index the image arrived
  in.
- **Provenance attestations are off for every image here** (`provenance: false` in
  `docker-compose.yml`). An attestation records its build time, so each build had a new index digest
  even when served wholly from cache: two builds of an unchanged backend gave two different IDs.
  With it off, they gave the same one twice. The images are local and never pushed, so the
  attestation recorded nothing anyone reads.
- **jenkins-dev:** its image copies `plugin/target`'s `.hpi`, and every Maven build writes a new
  build time into the `.hpi`. So the image changes with every build even when no class does, and
  the build cache cannot answer. Instead the check compares the classes and resources of the plugin
  Jenkins expanded and is running with those in `plugin/target`'s `.hpi`, and the bundled jars by
  name, leaving out META-INF, where the build time is. It compares `plugins.txt` and the plugin
  installer with the copies in the image. It also fails when a plugin source file is newer than the
  `.hpi`.

**Found on the way, and fixed: the backend had no `.dockerignore`.** Its build context sent the
147 MB virtualenv to the daemon on every build, and `COPY app ./app` shipped 76 `.pyc` files from
the developer's own test runs into the image. Each local test run therefore looked like a source
change to the build cache. `backend/.dockerignore` now excludes them, along with `.env*`. A fresh
container from the rebuilt image holds no `.pyc` file.

**Evidence (2026-10-22):**
- **Before the rebuild:** the checks failed for the frontend, the backend (its context changed with
  the new `.dockerignore`) and the agents (their image metadata changed with the Compose version).
- **After the rebuild:** all three passed in two consecutive runs, in 2 to 5 seconds each.
- **Each failure path was shown to fail:**
  - a one-line change to `backend/app/__init__.py` failed the backend check, and restoring the file
    passed it again;
  - a plugin source file made newer than the `.hpi` failed the jenkins-dev check;
  - an `.hpi` with one altered class failed it, naming the class.

  Each was restored byte for byte, its modification time included, and passed again.
- The rebuilt frontend's Queue page bundle contains the held-jobs list.

---

### D-069 White-box measurement: coverage everywhere, mutation testing on the algorithms
**Date:** 2026-10-20 · **Status:** accepted (hardening of Phases 1 to 6; the testing chapter's
white-box testing)

**What is measured, and with what.** Statement and branch coverage for all three components:
JaCoCo 0.8.15 through the Jenkins parent POM's `enable-jacoco` profile for the plugin, coverage.py
through `pytest-cov` for the backend, and V8 coverage through `@vitest/coverage-v8` for the frontend
(`npm run coverage`). Mutation testing with PIT for the plugin's algorithm classes only, through an
opt-in `mutation` profile. Neither changes the ordinary build.

**The backend's coverage was under-reported until the tracer was told about greenlets.** SQLAlchemy's
async engine runs on greenlets, and coverage.py's default tracer loses the lines after a greenlet
switch: over the offline suite it reported 87% where 92% had run, and `app/services/auth.py` 67.6%
where 92.3% had. `[tool.coverage.run]` now sets `concurrency = ["thread", "greenlet"]`, so any run
of `--cov` is right without flags.

**Why PIT only targets the algorithms.** Scoring, the heap, union-find, Kahn's sort, the estimator
and the priority levels have no Jenkins imports (CLAUDE.md) and unit tests that run in
milliseconds, so every mutant meets the whole suite for its package. The Jenkins-facing classes are
covered by JenkinsRule tests that take seconds each; mutating them would cost hours for little.
`SchedulerOverheadTest` is excluded: a timing test is the wrong oracle for a mutant.

**Equivalent mutants are named, not counted as gaps.** Eleven survive the final run, and no test can
tell them from the original: the boundary of `waitMillis <= 0` (a zero wait earns nothing either
way), both boundaries in `dependencyFactor` and the two in group inheritance (a singleton group or an
equal score gives the same result), `anyKnown` in `scoreAll` (redundant whenever an estimate is
present), and five in union-find's union by rank, which change the tree's height but never which
elements are joined.

**Infeasible branches are named too.** Coverage cannot reach them because the code's own invariants
rule them out: `maxGroupSize <= 1` with a group of two or more, `!anyKnown` with an estimate, a heap
entry missing from its own index, and `current.equals(ownName)` in `JobPriorityProperty`'s cycle
walk, which an earlier check makes unreachable.

**Dead code found and removed** (no callers anywhere): `RevokedTokens.is_revoked`, which `claim()`
replaced; `constant_time_equals`, since the metrics route compares tokens with
`secrets.compare_digest` itself; and `PolicyDecision.allowed`.

**What the measurements found, and the tests now closing it:**
- **Backend:** a refresh or access token whose account no longer exists, the password rehash at
  sign-in, an unreadable stored hash, expiry of the token denylist, a WebSocket that never sends its
  auth frame, and the heartbeat of an idle one.
- **Plugin, coverage:** `MetricsPublisher` (5% of branches), the configuration form's validation
  (never run), the startup warning about a competing `QueueSorter` (Part 4.3.7), and the cycle
  walk past its first hop.
- **Plugin, PIT:** a zero aging interval; an aged job's own score; five missing `unlock()` calls the
  heap's single-threaded tests could not see; `isEmpty`; `hasUnknownEstimate`; and the estimator's
  threshold boundary and two documented tie-breaks.

**Evidence:** PIT's first run, before the new tests, killed 150 of 173 mutants (87%); after them,
162 (94%), the 11 survivors being the equivalent ones above. Those two runs used pitest-maven
1.30.1; it was then pinned to 1.30.0 under the seven-day cooldown (docs/versions.md), and 1.30.0
gave the same 173 and 162. Coverage figures and the per-test results are in the testing chapter's
annexure, from the evidence run at the commit that carries this decision.

---

### D-068 Suspicious activity the backend detects is written to the audit log
**Date:** 2026-10-20 · **Status:** accepted (hardening of Phases 1 to 6; found tracing the report's
acceptance criteria for the testing chapter)

Report 4.7.4, User Story 5, criterion 3: "Given suspicious activity occurs, when it is detected, then
the system logs the event for audit purposes." Part 4.4.3 asks for an audit entry for every policy
denial, and 4.5.5 for every denial. Failed and refused sign-ins and prompt-injection attempts were
audited already. Three events the backend detected were not:
- **A role guard refusing a request**, such as a Developer calling the Admin API: no entry and no
  log line. Now `access.denied`, naming the method and path, the role needed and the role held.
- **A spent refresh token coming back**, which signs out its whole family: a log line only. Now
  `auth.session.reused`, with the account and the caller's address.
- **A sign-in limit engaging**: nothing at all, because a refused attempt never reaches the code that
  audits sign-ins. Now `auth.login.limited`, naming the account tried, the limit (per account, or per
  address across accounts) and the address. Both sign-in limits are checked in the login route's
  body for this; the per-address one used to be a dependency.

**Bounded, so the log cannot be flooded.** A limit records at most one refusal per caller per window
(a minute, for every limit today): the one that shows it engaged, and one more for each window it
keeps engaging. Recording every 429 would let anyone hammering the sign-in page write a row per
request. Role denials are recorded every time, as 4.4.3 asks; they need a valid session, so they are
attributable, and the API's 300-a-minute limit bounds them.

**Not looked up.** A limited sign-in is recorded without loading the account, so a refusal takes the
same time whether or not the account exists.

**Evidence:**
- `test_suspicious_activity_audit.py`, 9 tests. Four mutants (no role audit, no reuse audit, every
  refusal recorded, no per-address limit) are each killed by them.
- `test_acceptance_user_stories.py` reads all of them back through `/api/admin/audit`, as an Admin.
- Gate: the Phase 3 check "suspicious activity is written to the audit log".
- The gate's "auth endpoints are rate limited" check follows the route's new shape, and now also
  runs the tests that see the 429s. It had looked for the single limit D-065 replaced, and failed
  the gate run of 2026-10-20 (84 of 85).

---

### D-067 Dependency groups are formed over the whole queue, not only the buildable items
**Date:** 2026-10-20 · **Status:** accepted (hardening of Phases 1 to 6; found planning the testing
chapter's white-box tests)

**The defect.** The sorter grouped and scored only the items Jenkins handed it, which are the
buildable ones. The dependency gate holds a consumer out of that list while its upstream is queued
or building (Part 4.3.8). So an upstream and the work waiting on it were never scored together:
every producer was a group of one, D was always 0, and group inheritance (Part 4.3.6, report
Appendix C) could not happen in a live queue. A LOW build that a HIGH deployment waited for ran
behind every MEDIUM job, and the deployment waited for all of them too.
- **Why nothing caught it:** `AppendixCExampleTest` and `ScoreComponentTest` build their groups by
  hand. No integration test queued a consumer behind its producer. The live Queue page's score bars
  never showed a dependency segment, which fits.
- **Measured before the fix** (`GroupInheritanceIT`, JenkinsRule, one executor): dispatch order
  `gi-medium-1, gi-medium-2, gi-medium-3, gi-build-api, gi-deploy-api`; the producer's D was 0.0.

**The fix.** The sorter scores the buildable items together with the items the queue is holding back:
`Queue.getItems()` filtered to `BlockedItem`, the snapshot the gate and the ranking API already
read. Queue maintenance runs as SYSTEM (`AtmostOneTaskExecutor` and `SafeTimerTask` both impersonate
`ACL.SYSTEM2`, read from the 2.568.3 bytecode), so no held item is hidden by permissions. Groups, D
and inheritance are computed over that scope; only the buildable items are ranked, put in the heap
and reordered. The formula is unchanged.
- **The cache key gains the held items, as a set of their own.** In the first version of this fix the
  key was one set of all ids. When the gate released a consumer that set did not change, the cached
  scores had none for it, and it ranked behind lower work for a pass. `GroupInheritanceIT` caught it.
- **A wrong turn, recorded so it is not repeated.** That failure was first blamed on the gate reading
  a stale queue snapshot, and the gate was changed. A diagnostic print showed the snapshot fresh
  and the gate right, so the gate change was reverted and the cache key fixed instead.

**Scope.** Part 4.3.4 already passes `List<Queue.Item>` to `DependencyGraphService.build`. Read with
4.3.7 (the sorter scores the list it is handed) and 4.3.8 (the gate) it left D dead. This follows
the report's intent, Appendix C's "the group's producer is dispatched before its consumer". T's
normalisation and `maxGroupSize` now span the held items too: they are part of the queue.

**Evidence:** `GroupInheritanceIT`, 4 tests under JenkinsRule, passed three runs in a row.
- `producerOfAHeldUrgentJobRunsFirst` and `theRankingShowsTheInheritedScore` failed on the code
  before the fix, as above.
- Two mutants of the cache key are killed: held items left out (`aLateConsumerLiftsAWaitingProducer`)
  and one set of all ids (`aReleasedJobIsRankedAtOnce`, `producerOfAHeldUrgentJobRunsFirst`).
- `mvn -B verify`: 108 unit tests (1 skipped, as before) and 77 integration tests passed; SpotBugs 0.

---

### D-066 The heap holds exactly the buildable items, scored; held jobs are listed apart
**Date:** 2026-10-20 · **Status:** accepted (hardening of Phases 1 to 6; found in T6.6)

**The sorter no longer returns early below two items.** It scores a lone buildable item, and
empties the heap when nothing is buildable or the optimizer is off. Before, a lone waiting job had
no score, or kept a score and aging bonus from an earlier pass. The heap also kept items that had
left the queue. This follows CLAUDE.md's rule that the sorter always rebuilds the heap.

**A leaving item keeps the score it was dispatched on.** The heap holds only the items buildable
at the last pass. An item handed to an executor is no longer buildable, so the next pass dropped it
before its QUEUE_LEFT event read its score. That race had always existed, with any queue of two or
more. The sorter now keeps each item's latest score in a map until the item leaves, and the
recorder takes it from there, once.

**Held jobs are a list of their own, not rows in the ranking.** The plugin's API gains
`heldItems`: every blocked item, with Jenkins's reason, plus the upstream job and its state when
the dependency gate is the reason. `/api/queue` passes it on as `held_items`, and the Queue page
lists them under "Held back" in DESIGN.md's words ("Waits for fs-payment-service-build").
- **The deviation from DESIGN.md:** its Queue sketch draws such a job as a ranked row with a score.
  A held job cannot be dispatched, and the plugin gives it no score until it is buildable. A rank
  would say it could run next, so it is listed apart.

**Evidence:**
- `ApiJsonIT.heldItemsNameTheirUpstream`, under JenkinsRule.
- A live recording from the rebuilt jenkins-dev (`backend/tests/data/plugin/ranking-held.json`).
- The backend's parser and route tests on that recording, and the Queue page's tests on its capture
  through the backend.
- `HeapFreshnessIT`: five tests, all of which fail with the old early returns.

---

### D-065 The independent security review's fixes, and the choices inside them
**Date:** 2026-10-18 · **Status:** accepted (hardening of Phases 1 to 6)

The review and every fix are in `docs/security-review-phases-3-5-6.md`. Recorded here are the
choices the fixes made, where another fix was possible.

- **One request runs once.** A request that was approved cannot be generated, regenerated or
  approved again; running it again takes a new message. This was already the rule for editing.
  The partial unique index holds it under concurrency. The alternative, a fresh justification and
  quota check on every approval, would have kept a second way to start the same HIGH chain.
- **Refresh tokens have families.** A refresh token carries `fam`, kept through every rotation. A
  spent token coming back means two parties hold the session, and neither can be told apart, so the
  whole family is signed out. Like the revocation list (D-021), families are in memory.
- **Rate-limit keys:**
  - Signed-in traffic is keyed by the access token's user. The token is verified but not looked
    up; authorisation is still `CurrentUser`'s.
  - Sign-in is keyed by address and account (5 a minute), with an address-wide cap (30 a minute).
  - `X-Forwarded-For` is still ignored. The frontend's nginx and the dev server's proxy both make
    every client one address, which is why the keys moved off the address.
- **Ports on loopback.** The stack is for the machine it runs on. A demo on another machine would
  need a reverse proxy with TLS, not a published Jenkins.
- **The frontend container is same-origin.** nginx serves the build and proxies `/api` and `/ws`,
  so the CSP keeps `connect-src 'self'`, and no CORS or build-time API URL is needed.
  `VITE_API_BASE_URL` remains for running the app against a backend elsewhere; the CSP then adds
  that origin.
- **The CSP is a meta tag added at build time.** The dev server injects inline scripts for hot
  reload, which a strict policy would block. `frame-ancestors` cannot be set by a meta tag, so nginx
  sends it as a header.
- **The plan explanation is screened by sentence.** The stream is held back to whole sentences, so
  a word split across chunks is still caught. Backticks are allowed, unlike in T5.9's suggestions,
  because an explanation quotes job names in them.
- **Health reports, but does not call, the model.** The LLM component shows the latest recorded
  call's outcome. A call made just to probe would spend the free tier's daily quota on monitoring.

---

### D-064 Lighthouse audits the signed-in assistant pages in the tab Puppeteer signed in
**Date:** 2026-10-17 · **Status:** accepted (Phase 6 acceptance)

**The problem.** Phase 6's acceptance asks for a Lighthouse accessibility score of 95 or more on both
assistant pages. Both need a session, and the session is in the tab's sessionStorage (D-054). A
Lighthouse run of its own opens a fresh tab and clears storage, so it would audit the sign-in page
and report that page's score as the assistant's.

**How it is done.** `frontend/e2e/lighthouse.spec.ts`, a Playwright project that runs only with
`LIGHTHOUSE=1`, uses the flows' harness (D-062): the production build, and the backend in fake mode
with made-up accounts.
- **The data:** made through the API first, as for the screenshots (D-063): a freestyle chain under
  way, and a Pipeline waiting to start.
- **The browser:** Puppeteer drives the installed Chrome, headless, and signs in through the form.
  Lighthouse then audits that same tab with `disableStorageReset`, so the session survives.
- **What is audited:** each assistant page empty and with a chat that has a plan and a run card, in
  light and dark, at Lighthouse's mobile (412 px) and desktop (1350 px) settings. That makes 16
  audits, accessibility only.
- **Guards against auditing the wrong page:** after each audit the spec asserts the report's final
  URL is the page asked for, and that the tab shows that assistant's heading in that theme.
- **Results:** the reports and `summary.json` go to `.tmp/lighthouse/`, which is not committed. The
  spec fails if any audit is under 0.95.
- **Dependencies:** `lighthouse` 13.5.0 and `puppeteer-core` 25.12.0, both pinned exactly as every
  frontend dependency is. puppeteer-core is the version Lighthouse itself uses, so there is one copy.
  It downloads no browser.

**Why not the alternatives.**
- **Lighthouse CLI with `--extra-headers`:** the app takes its token from storage, not from a header
  Lighthouse could add.
- **Playwright's own browser with a debugging port:** two drivers on one tab. Each sets its own
  emulation.
- **A user flow (`startFlow`):** gives the same audit as a navigation with storage kept, with more
  moving parts.

**The result, 2026-10-17:** 100 in all 16 audits. The chat pages had 27 to 30 applicable audits
against the empty pages' 25, so their content was there when audited.
- **Negative control:** a throwaway copy of the spec planted a nameless button, an image with no
  `alt` and low-contrast text. Every one of the 16 audits flagged all three (`button-name`,
  `image-alt`, `color-contrast`), scored 86 to 89, and the test failed. The copy was deleted.

**Where it runs.**
- **`verify.py --phase 6`:** a new check runs the project. It then reads the summary, which must have
  been written by that run and cover both assistants, with every score at 0.95 or more.
- **CI:** not run. It would add minutes to every push, and the gate covers it. Adding it to the
  "Browser flows" job is a small follow-up if a regression guard on every push is wanted.

---

### D-063 The screenshots are made by Playwright from the build, and the review's fixes stay small
**Date:** 2026-10-16 · **Status:** accepted (T6.9)

**How they are made.** `frontend/e2e/screenshots.spec.ts` is a Playwright project that runs only
with `SCREENSHOTS=1`, because it rewrites committed files. It uses the same harness as the flows
(D-062): the production build, and the backend in fake mode with made-up accounts.
- **The data:** it is made through the API first, the way the assistants make it. There is a
  freestyle chain under way, a failed run carrying jenkins-dev's real failing log (a new `/__e2e/builds`
  control finishes queued builds in the fake Jenkins, and the run tracker picks them up as from a real
  one), and a Pipeline waiting first in the plugin's recorded ranking.
- **The views:** each screen is loaded once, with the theme on System. The viewport and colour scheme
  then change in place, so the theme follows the scheme. Sign-ins are rate limited (D-062), and this
  needs one per role.
- **Full page or not:** every screen is captured full page, except the two assistants. They are app
  screens: on a phone the thread scrolls under a composer pinned to the bottom, and a full-page
  capture froze that composer mid-page. They are captured as the screen a person sees.
- **Coverage:** 4.7.3's nine screens, plus the Admin page as a Developer finds it, at 1440 and 390 px,
  light and dark. That makes 40 files in `docs/screenshots/`, named `<screen>-<width>-<theme>.png`.
  `verify.py` checks that each is there and is a PNG of the width its name gives.

**What the review changed.**
- **The theme switch** lost its icons and became three equal parts. With icons the three were 229px
  wide in a 192px sidebar footer, so System ran out of the sidebar. DESIGN.md names the three choices,
  not their icons, and the words carry them.
- **The chat list** printed times as "Oct 16, 09:44 AM" from the browser's locale. Every other page
  prints "09:44" or "16 Oct 09:44". It now uses the same formatter, and reads API times as UTC (D-061).
- **An active chain between jobs** said "Running" beside the name of the job that had already finished.
  It now says "Waiting to start" and names the next job.
- **The run detail's jobs list** called a job the chain never reached "Not built", beside a run card
  that called it "not started". It now says "Not started" too (principle 4: one name per thing).

**What the gate found.** The first full `verify.py --phase 6` runs after the screenshots failed, and
none of the three failures was visual.
- **A race in the assistant page (a real bug, from T6.5).** Sending the first message of a new chat
  created the chat, opened its address at once, then sent the message. Opening the address started
  the chat's own load, which could read the chat before the message was stored and arrive after the
  reply, so the page showed an empty chat. The trace of the keyboard flow showed the load start
  during the send and return empty after it. The page now opens a new chat only once its first
  exchange is stored and loaded. A Vitest test holds the send open and fails if the chat is ever
  loaded before it is stored; it failed against the old order.
- **`verify.py` read its subprocesses as cp1252.** Vitest prints the character U+276F, which cp1252
  cannot decode, so a reader thread died and a check crashed instead of reporting. It now reads them as
  UTF-8, and writes its own output as UTF-8, since printing a failure could crash the same way.
- **An assistant-page test timed out under load** at Vitest's 5 s default while the gate ran other
  suites. It now types without per-key delays, and that file allows 15 s per test.

**Left as they are, and why.**
- **The main bundle, 745 kB:** every page is in it. Loading each page lazily from the routes is the
  fix. That is a performance change, not a visual one, so it is left for a task of its own. Done
  on 2026-10-20 (hardening of Phases 1 to 6): every page, sign in included, is its own chunk,
  loaded through React Router's `lazy`; the main bundle is 419 kB (132 kB gzipped), and the build
  no longer warns. No size limit was raised to get there.
- **Lighthouse:** not run. The session lives in sessionStorage, which a Lighthouse run starts without,
  so measuring a signed-in assistant page needs a scripted user flow (Lighthouse with Puppeteer), and
  those dependencies are not in the project. Done since, by D-064.

---

### D-062 The browser flows run against the backend in fake mode, with nothing outside it
**Date:** 2026-10-16 · **Status:** accepted (T6.8)

**The backend.** 4.7.6 runs the Playwright flows "against the backend with `LLM_MODE=fake`".
`backend/browser_backend.py` starts that backend as a process of its own, and the Playwright
configuration starts it.
- **What is real:** the app with every router, the policy and the generators, the run tracker, the
  WebSocket hub, sign-in with token rotation, and the app's own seeders.
- **What is not:** the model is in fake mode. Jenkins, its plugin and Git are the in-memory
  stand-ins the backend's tests use. The database is SQLite in a temporary folder, made fresh for
  each run.
- **Why:** the flows are then the same on every run and need no Jenkins, network or credential.
  CI runs nothing that needs a Jenkins, so this is what lets CI run them. The running stack's
  backend is an older image that is not rebuilt without approval. The flows through a real Jenkins
  are T5.8's end-to-end suite, at the API.

**Accounts and secrets.**
- **Made up for each run:** `playwright.config.ts` makes up an Admin and a Developer with random
  passwords, and hands them to the backend through the environment.
- **No real secret reaches the harness:** the launcher sets every setting that could hold a secret
  (database, JWT secret, metrics token, Jenkins credentials, Groq key, seed password). A `.env` in
  the working directory is therefore never the source of one.

**Controls only the test process has.** Routes under `/__e2e`, mounted by the launcher on its own
app and never in the application, let a flow:
- set the plugin's ranking, in the plugin's own format, or make the plugin unreadable;
- switch the model off, so the chain falls back to the rule parser with `ai_fallback` set, as it
  does with Groq unreachable (a `ProviderRejectedError`, which falls back without retries or a
  quota block);
- reset, which cancels every running chain as an Admin would. Each flow then gets its own
  per-service chain lock (4.6.4).

**The real sign-in limit is kept.** Every flow signs in from 127.0.0.1, so all of them share its
limit of five sign-ins a minute (per account since the 2026-10-18 security fixes, with thirty per
address across accounts). A flow that gets a 429 waits for as long as the backend asks
(`retry_after_seconds`). The harness never loosens the limit.

**The built app, through `vite preview`.**
- **What it is:** `vite preview` has the same `/api` and `/ws` proxy as the dev server, and the
  build is what users get.
- **Why not the dev server:** against it, two flows saw the page come back empty right after
  sending a first message, with the chat already made. Against the build that never happened, in
  two full runs and 15 repeats of the assistant flows. The likely cause is the dev server
  optimising a dependency it met on demand and reloading the page; its log did not show the
  reload, so that is not confirmed.
- **Corrected in T6.9:** that guess was wrong. The empty chat was a race in the page, and the build
  only made it rarer. The Phase 6 gate then hit it against the build, and its trace showed the
  cause (D-063, "What the gate found"). The flows still use the build, because the build is what
  users get.

**Chrome as installed.** `channel: "chrome"` uses the Google Chrome on this machine and on GitHub's
runners, so no browser is downloaded.

**The queue flow's ranking** is the live plugin's recording of three waiting jobs, with its MEDIUM
job made LOW: urgency factor 0.3, and the score worked out again by the report's formula, 0.150.

**4.7.6's Vitest half was done already.** T6.4 wrote tests for the intent card (7), clarification
(3), composer (8) and score bar (9), and they still pass.

**Where the flows run.**
- **`verify.py --phase 6`:** a new check runs them, passing its own uv (D-010).
- **CI:** a "Browser flows" job runs them, keeping the traces when one fails.

**What they cannot show:** a real Jenkins building and deploying, the live plugin scoring a real
queue, real Git, the live model, and the stack's own frontend, for which there is no container yet.

---

### D-061 The last five pages show what the API reports, and say plainly what it does not
**Date:** 2026-10-16 · **Status:** accepted (T6.7)

The pages are built on the backend's contracts as they stand. Where 4.7.3 or a DESIGN.md sketch asks
for something no endpoint reports, the page says what is missing instead of making it up, and the
gap is recorded under Phase 6's open items. No backend code changed.

**Jobs and runs lists chains, not runs.**
- **Why chains:** a run from `GET /api/runs` carries no service, assistant or stages, and the API
  filters runs by one job at a time. `GET /api/jobs` names a job's service only by an id that the
  catalog API never returns. A chain carries its service, job type (which assistant made it) and
  outcome, and its run card carries the stages and the run ids whose logs can be read. Every run
  the backend tracks belongs to a chain, a re-run included.
- **Filters:** the service filter is the API's own. The assistant and result filters narrow the
  newest 200 chains, the API's largest page, and the page says so when there are more.
- **The duration column is "Start to finish",** the chain's time from start to end, queue waits
  included. The run card's "in 6s" adds up its jobs' build times. Both are honest; they are
  different measures, so they have different words.
- **The log tail** reads the 64 KB windows forward to the end, keeps the last 200 lines, and asks
  again every 2 seconds while Jenkins is still writing.

**Analytics shows run statistics, the stored experiments, and no chart yet.**
- **Run statistics** are computed by the backend from every run. A null is shown as "Not
  measured", never as 0.
- **Experiments:** a table of the stored runs, and each run's metrics (name, band, value with its
  standard deviation, sample size). None exist before Phase 7. No chart is drawn: a chart's form
  depends on which metrics the harness stores, and choosing those now would be inventing them. The
  charts, each with Show as table, and the score bar's 20 px Analytics size wait for Phase 7's data.
- **Chatbot evaluation:** no endpoint serves its results (4.4.4 lists "evaluation results"), so the
  section says so.

**Admin is for Admins, and shows the policy as fixed.**
- **Access:** the sidebar lists Admin only for an Admin, which settles T6.3's finding. Anyone else
  who opens `/admin` is told the page is for Admins, and the page asks the backend nothing.
- **Users:** an Admin changes a role, adds a user, or deactivates someone after a confirmation that
  says exactly what happens. Their own row has no controls, because the backend refuses them.
- **Policy:** the HIGH quota and 4.5.5's rules are shown read-only, as the API reports them
  (`editable: false`).
- **Rate limits are not shown.** They are constants in `app/core/ratelimit.py` (300 a minute for
  the API, 20 for the assistants) that no endpoint reports. Copying them into the UI would let it
  drift from the backend. The Admin entry's description no longer promises them.
- **Passwords:** the form sets a first password and says that it cannot be reset there later,
  because no endpoint resets one.

**The Overview.**
- **My active runs** are the active chains whose `started_by` is the signed-in user. The API lists
  every active chain, and each says who started it.
- **The AI provider line** shows `GET /api/health`'s `llm` entry as reported: its status as a word
  and an icon, and its detail. That check reads the configuration and never calls the model, so
  the page never says the model is answering. DESIGN.md's sketch, "AI provider: Groq, answering",
  cannot be shown honestly, and the Overview's description changed to match.
- **Refresh:** the jobs-waiting figure refreshes every 10 seconds, as the Queue page does (D-060).

**Shared code.**
- **One client context.** `ApiClientContext` with `useApi(factory)` replaces the two per-page
  contexts. Every page builds its requests over the client in context, so a test gives every page
  one fake backend.
- **One table.** `DataTable` draws every new table, and turns it into stacked blocks of labelled
  facts below 768 px (DESIGN.md sections 7 and 9).
- **Times.** An API timestamp without an offset is read as UTC. PostgreSQL returns offsets; the
  SQLite test database drops them, and the backend writes every time in UTC.

---

### D-060 The Queue page shows the plugin's ranking as reported, and asks again every 10 seconds
**Date:** 2026-10-16 · **Status:** accepted (T6.6)

**It polls as well as listening.** The page asks for `GET /api/queue` again on `queue.changed`,
`run.queued`, `run.started` and `run.finished`, and every 10 seconds while the tab is visible. The
events come from the backend's tracker, so they cover only runs the backend started. A build queued
any other way changes the queue without an event, and so does time: every wait grows, and so does
its aging. `src/api/queryClient.ts` still polls nothing by default; this one query sets its own
interval, which React Query pauses in a hidden tab.

**What each row shows, from what the plugin really sends.**
- **The blocked reason is Jenkins' own, shown verbatim.** Every ranked item is buildable, so its
  reason is an executor wait ("Waiting for next available executor on 'linux'", "Executor slot
  already in use"). It is in Graphite, because every waiting job has one.
- **A job held by the dependency gate never reaches the ranking.** `DependencyGate` blocks in
  `canRun`, so Jenkins keeps the item among its blocked items, and the ranking lists only buildable
  ones (`DynamicQueueApi`). DESIGN.md's Queue sketch has a row reading "Waits for
  fs-payment-service-build". The real page cannot show such a row. Recorded under Phase 6's open
  items.
- **`unresolved_dependencies` names upstream jobs that do not exist.** The gate reports them and
  never waits on them (`DependencyGate.unresolvedUpstream`). The page shows them under the job's
  name, "Upstream job not found: ...", as a mistake in configuration rather than a reason to wait.
- **Unscored items are listed below the ranking**, under "Waiting without a score", with the
  plugin's reason. The header's "N waiting" is the plugin's `queueLength`, which counts them.
- **The type is the plugin's Jenkins class in words:** FreeStyleProject is Freestyle, WorkflowJob
  is Pipeline and MavenModuleSet is Maven. Any other class is shown as sent.
- **Estimates and waits.** An estimate under half a second reads "Under 1s" rather than "0s", and
  a missing one reads "No history". A wait is in seconds for its first minute, then in whole
  minutes, because aging moves in five-minute steps.

**Show the numbers** adds four columns: "From urgency", "From dependency", "From execution time" and
"From aging". "Urgency" already names the level's column. At 1440 px, the table with these columns
is wider than its box, so it scrolls inside the box, never the page. Job names never break, and the
default view keeps each row on one 40 px line.

**The bars grow once.** `ScoreBar` takes `grow`, which the page passes for 300 ms after its first
ranking arrives.
- **What moves:** the segments and the inherited tick grow from 0 in 240 ms with ease-out. The 1.0
  tick and the empty track stay still, a live update jumps straight to the new value, and the
  global reduced-motion rule stops it.
- **Checked in headless Chrome:** `score-grow` ran for 0.24 s with ease-out, no bar was still
  growing a second later, and under reduced motion it ran for 0.01 ms.

**Shared request handling.** `answer`, `ApiRequestError` and `failureOf` moved from `assistantApi.ts`
to `src/api/request.ts`, so the queue's request and T6.7's share them. The queue's types come from
the client's return types, as D-059 does for the assistants.

---

### D-059 The assistant pages read only typed fields, from what the client returns
**Date:** 2026-10-16 · **Status:** accepted (T6.5)

**The untyped fields.** Four response fields are still `dict[str, Any]` in the schema, and T6.5
needs none of them, so none was typed and nothing reads them:
- **`PipelineResponse.plan`:** the progress line already says how the plan was made.
- **`PipelineResponse.approval`:** the page knows a plan was approved from `status` and
  `approved_at`, and follows the run from the approved-run reply, whose `chain_id` is typed.
- **`JobPreview.stage`:** the Config tab needs each job's `name` and `config_xml`.
- **`ApprovalResponse.result`:** after Approve and run the page refetches the conversation, which
  carries the same facts in the typed reply.

**The page types come from what the client returns, not `components["schemas"]`.**
openapi-fetch passes response data through `Readable<T>`, from `openapi-typescript-helpers`. That
rebuilds every object type and drops any property typed exactly `null`, because the key filter
asks whether `NonNullable<null>` (`never`) extends `$Write<any>`, which is true. The "nothing to
re-run" and "nothing to cancel" replies have `chain: null`, so they lose the key. The payload union
then has the same name as the schema's but a different shape, and TypeScript refuses to mix the
two. `src/api/assistantApi.ts` therefore takes each type from the request's return type. Nothing
reads those two keys.

**Two more.**
- **The thread orders a message before its reply when both have the same time.** The backend
  orders by `created_at`, then by a random id. One request writes a message and its reply, and
  Windows' clock can stamp both alike. The captured `/help` pair was returned reply first. The UI
  sorts by time with the user's message first on a tie. The backend defect is recorded under
  Phase 6's open items.
- **The page tests run on captured responses.** The backend was driven in fake mode against the fake
  Jenkins, and its responses were written to `src/test/fixtures/captured.ts` by a script. The
  module is typed by the client's return types, so all 19 responses are checked by the compiler,
  extra keys included.

---

### D-058 The assistant payloads are typed in the OpenAPI schema
**Date:** 2026-10-15 · **Status:** accepted (before T6.5, settling D-056)

**Problem.** D-056 found that the frontend could not read several things without hand-writing
types, which 4.7.1 forbids. Message payloads, the intent record, and a pipeline's progress line and
validation report were `dict[str, Any]` in the schema. So was the run card, which a status reply
contains.

**Decision.** Models in `backend/app/api/payloads.py` describe each one exactly as the backend
writes it, and the responses use them:
- **`MessageResponse.payload`** is a union of 11 reply models chosen by `kind`. Two kinds have two
  producers each, so for them the shape also decides:
  - `help` from `/help` carries only the help card, while the parser's help reply carries the
    whole record;
  - `run` from an approval carries `pipeline_id`, while a re-run carries the record.
- **`CommandResponse.record`** is `IntentRecord` (`ParseOutcome.to_record()`). Its `intent` is the
  parser's own `Intent` model, so the two cannot drift apart.
- **`PipelineResponse.progress` and `.validation`** are `ProgressStep` and
  `ValidationReportRecord`.
- **`GET /api/chains/{id}` and its cancel** return `RunCard` and `CancelResult`.
- **The shapes stay flat, as stored.** Stored rows and the existing tests read
  `payload["question"]["field"]`.
- **Every field a response always carries is marked required** in the schema
  (`json_schema_serialization_defaults_required`), so the frontend's types do not call it
  optional. Request schemas are unaffected.
- **A run card stored in a status message before D-057** lacks `base_score`, `own_score` and
  `weights`. It is read as not inherited and with no weights, so its bar says its parts cannot be
  shown rather than drawing wrong ones.

**How it is held.**
- **`tests/test_payloads.py` runs real flows** through the API and the fake Jenkins: every reply
  kind, a generated and approved pipeline, a failed test re-run, a status with a live run card,
  and cancelling. It then reads back everything stored. Each item must validate into its model
  and dump back unchanged, and every one of the 11 kinds must appear.
- **Removing one field from a model fails it.**
- **The 146 tests of the assistant, chain, generation, failure and router APIs** now pass
  through the typed responses as well.

**Not proven.** An audit of the stack's own database found no stored messages, commands or
pipelines (0 rows), so no older row was checked. The intent record's fields have all existed since
its first commit (T4.5), so older records have this shape.

---

### D-057 The ranking parser reads the plugin's own names, tested against recorded responses
**Date:** 2026-10-15 · **Status:** decided and applied (found in T6.4)

**Defect.** `parse_ranking` read flat `urgencyFactor`, `dependencyFactor`, `executionTimeFactor`,
`agingBonus` and `estimateSeconds`. Those are the names in the plugin's metric events
(`QueueMetricsRecorder`). The ranking endpoint (`DynamicQueueApi.renderItem`) nests the factors as
`components: {urgency, dependency, executionTime, aging}` and gives `estimateMillis`.
- **The effect:** against the live plugin every factor parsed as 0 and every estimate as unknown,
  in `/api/queue` and in the chain detail behind the run card. Every score bar would have been
  empty beside a correct score.
- **Why nothing caught it:** the parser's fixture was written from 4.3.10's prose, which names
  the fields but gives no keys. The gate's live check ran on an empty queue, so it never parsed an
  item.

**Fix.**
- **The parser reads the plugin's names** and keeps none of the invented ones, because nothing
  ever sent them.
- **It reads two things it used to drop.** `ownScore` (base plus aging, before group inheritance)
  lets the score bar mark an inherited score. `unscoredItems` is buildable work the optimizer has
  not scored. `queue_length` is now the plugin's `queueLength`, which counts those items.
- **`/api/queue` gains `components.own_score` and `unscored_items`.**
- **The chain detail's queue block gains `base_score`, `own_score` and the plugin's weights,** so
  the run card can draw its bar from that response alone.

**How it is held.**
- **Three responses recorded verbatim from the live jenkins-dev** are in
  `backend/tests/data/plugin/`: three waiting items with estimates, an item aged 300 s, and a
  dependency group with an inherited score and unscored items.
- **The tests check** every factor and estimate, and that weight times factor plus aging equals
  the plugin's own score for every recorded item. One test pins the nested shape itself.
- **Reverting the parser to the old names fails 9 of them.**
- **A fresh live response,** parsed by the fixed parser inside the backend container, matched its
  raw fields exactly.

---

### D-056 The workspace components take what they show, not API payloads
**Date:** 2026-10-15 · **Status:** accepted (T6.4). Its prerequisite for T6.5 was met by D-058,
and the view types `IntentFields`, `ProgressStep` and `ValidationCheck` are now the generated ones.

**Problem.** 4.7.1 says API types are generated from the OpenAPI schema and never hand-written.
The workspace shows several things the schema does not describe. `MessageResponse.payload`,
`CommandResponse.record` (the intent card), `PipelineResponse.progress` and `.validation`, and the
chain detail behind the run card are all `{[key: string]: unknown}`. A component that read those
dictionaries would have to declare their shape itself, which is a hand-written API type.

**Decision.** The T6.4 components take props, not payloads.
- **Typed fields are used as they are.** Where the schema types a field, the component uses the
  generated type: `ScoreComponentsResponse` and `QueueResponse.weights` for the score bar,
  `ServiceResponse` for the intent card's catalog values, `ConversationResponse` for the chat
  list, and `IntentEdit` for what an edit sends.
- **Untyped fields become small view types.** Where the schema has only a dictionary, the
  component declares what it renders: `IntentFields`, `ProgressStep` and `ValidationCheck`.
- **No component imports the API client or parses a payload.** That mapping is T6.5's.

**What T6.5 must do first.** Type those dictionaries in the backend's response models, as D-055
did for errors, so the pages map generated types onto these props instead of guessing at
dictionaries. The backend already builds each one from a fixed structure: `ParseOutcome.to_record`,
`generation._progress`, and `ValidationReport.to_record`.

---

### D-055 The error shape is part of the OpenAPI schema
**Date:** 2026-10-15 · **Status:** accepted (T6.3)

**Problem.** Every error the API sends has one shape, `{"error": {"code", "message", "details"}}`
(`app/core/errors.py`), and `ErrorCode` is an enum "so the frontend can switch on them
exhaustively". But the schema the frontend's types are generated from never mentioned it. The
sign-in page has to tell `INVALID_CREDENTIALS` from `ACCOUNT_DISABLED` and `RATE_LIMITED`, and
4.7.1 forbids hand-written API types. The schema was also wrong: FastAPI documented every 422 as
its own `HTTPValidationError`, a shape this API never sends, because `_validation_error` turns
validation failures into the error shape.

**Decision.** Two Pydantic models, `ErrorResponse` and `ErrorBody`, describe the shape. The app
declares them as every route's `4XX` and `5XX` response. Declaring `4XX` also stops FastAPI from
adding its own 422 entry (FastAPI 0.141.1, `fastapi/openapi/utils.py`). The frontend gets
`ErrorCode` as a generated union of the 35 codes.

**How it is held.** Backend tests check four things: every operation documents both ranges with
`ErrorResponse`; the schema's `ErrorCode` enum equals the Python enum; `HTTPValidationError`
appears nowhere in the schema; and `ApiError`'s payload validates against the model. The drift
checks from T6.2 keep `openapi.json` and `schema.d.ts` current.

---

### D-054 The session: the access token in memory, the refresh token in sessionStorage
**Date:** 2026-10-15 · **Status:** accepted (T6.3)

**Question.** The backend (4.4.4, T3.3) returns both tokens in the response body. The access
token lasts 15 minutes. The refresh token lasts 7 days and is rotated on every use. Where the
frontend keeps them decides two things: whether a reload signs you out, and what a script
injected into the page could take.

**Decision.**
- **The access token** stays in memory only, as in T6.2.
- **The refresh token** goes in sessionStorage, under `orchestrator.session`. A reload, which
  happens often in a live demo, keeps you signed in. Closing the tab signs you out.
- **Renewal.** The access token is renewed a minute before it expires. A 401 from any endpoint
  outside `/api/auth/` triggers one refresh and one repeat of the request. Refreshes are
  single-flight: once the first has rotated the token, a second sent with the old one would be
  refused.
- **Signing out** revokes the refresh token on the server, then forgets both tokens whatever the
  answer.

**Alternatives.**
- **An httpOnly cookie** would keep the refresh token away from page scripts entirely. It needs
  the backend to set and read the cookie, and CSRF protection on refresh and logout. That changes
  the 4.4.4 contract T3.3 built and tested, which is too much for a staging-only tool. It is the
  upgrade path.
- **localStorage** is shared by every tab. With rotation, two tabs refreshing from the same token
  race: the first revokes the token the second is about to use. sessionStorage is per tab, so each
  tab has its own chain.
- **Memory only** signs you out on every reload.

**Consequences, both accepted.**
- **A stolen refresh token outlives the page.** A script injected into the page could read it and
  keep using it after the tab closes, for up to its 7 days. Such a script could equally act with
  the in-memory access token while the page is open, so this is the extra exposure. Rotation
  limits it: whichever holder refreshes first revokes the token the other one has.
- **A duplicated tab copies sessionStorage,** so it starts with the same token. Whichever tab
  refreshes second is signed out with "Your session ended".

---

### D-053 The failure analysis does not read a checkout attempt that Jenkins retried
**Date:** 2026-10-14 · **Status:** decided and applied (found by the first Phase 6 gate run)

**What happened.** The first `verify.py --phase 6` run failed one check of 72, the end-to-end test
`test_the_failed_tests_are_explained_from_their_real_log`. Its explanation came from the rules,
because both models missed their replay recordings (`replay_miss`).
- **The build.** `fs-payment-service-test-unit` #60. Its first clone could not resolve
  `github.com` on agent-2. D-050's retry got past that 10 seconds later, and the unit test then
  failed as designed.
- **What changed the prompt.** The recovered error's lines (`ERROR: Error cloning remote repo`,
  the `GitException`) matched the excerpt's signals and were added to the excerpt.
- **Measured.** Builds #55, #56, #58 and #61 render the identical prompt; #60 rendered a
  different one, so its hash had no recording.

**Why it matters beyond replay.** Since D-050, a dropped lookup during a clone no longer fails the
build, so these lines will keep turning up in builds that fail later for other reasons. The
whole-log rules read them too: a later step that failed without printing why would have been put
down to the network.

**Decision.** `analysis._superseded` finds every checkout attempt that Jenkins retried. An attempt
runs from its start (the top of the log, a Pipeline's `[Pipeline] checkout`, or the previous
retry) to Jenkins's `Retrying after 10 seconds`. Those lines are left out of the excerpt and out of
both rule passes. An attempt that was not retried is still read, so a checkout that failed every
time is diagnosed from its last attempt, the one that failed the build.

**Checked.**
- With the fix, build #60 renders the same prompt as #55, #56, #58 and #61.
- Build #60's log is now a fixture, `payment-service-test-unit-retried-checkout.log`. Four new
  tests fail without the fix and pass with it:
  - the retried build's prompt equals that of the same build without its failed attempt;
  - a recovered error never explains a later failure;
  - a checkout that failed all three attempts is read through its last;
  - a Pipeline's retried `checkout` step leaves the excerpt unchanged.
- The offline suite: 1641 passed, 49 deselected.

**Also learned.** Build #60 is the first observed case of D-050 working. It survived a DNS failure
that would have failed it before.

---

### D-052 Six named colours for the interface; the score bar's four colours are a data scale
**Date:** 2026-10-13 · **Status:** accepted 2026-10-15, when the user approved
`frontend/DESIGN.md` as written

**Conflict.** Part 4.7.2 asks for "4 to 6 named hex values with their roles, plus separate
build-state colors". The same part makes the score bar the memorable element: one stacked bar of
four contributions, which needs four colours that can be told apart. Part 4.7.4 adds a separate
accent for each assistant. Four bar colours, two accents and the neutrals that every interface
needs do not fit in six.

**Decision.** Six named values run the interface: Ground, Panel, Ink and Graphite, plus Spruce
and Plum for the Freestyle and Pipeline assistants. The divider colour, Rule, is a mix of Graphite
into Panel rather than a seventh value. The score bar's four colours are treated like the
build-state colours: a separate scale that only score bar segments and their legend keys may use.
Section 10 of `DESIGN.md` puts this first in the list of choices to question.

**How it is held.** `verify.py --phase 6` reads the colours from `DESIGN.md`'s tables and checks
that there are 4 to 6 named values, then recomputes:
- text at 4.5:1 or more, and every meaningful graphic at 3:1, on Panel and on Ground, in both
  themes;
- adjacent score bar segments at least 15 ΔE apart, and at least 8 under simulated colour vision
  deficiency;
- every score bar colour at least 15 ΔE from every build-state colour, because 4.7.5 reserves the
  status colours.

---

### D-051 T6.8's test plan is Part 4.7.6, not 4.7.8
**Date:** 2026-10-13 · **Status:** decided; the specification is left unchanged

**Conflict.** T6.8 asks for "Vitest unit tests and Playwright flows (Part 4.7.8)", but Part 4.7
ends at 4.7.6. Part 4.7.6, "Tests", is the only test plan in Part 4.7: Vitest for the intent card,
clarification, score bar and composer, and seven Playwright flows run against the backend with
`LLM_MODE=fake`. Nothing else in the specification refers to a 4.7.8.

**Decision.** 4.7.6 is the intended reference, as with T5.8's 4.6.7 (D-040). Unlike D-040,
`BUILD_PROMPT.md` is not edited: that correction was made at the user's request, and this one has
none. Rule 1.4 asks only that the deviation be recorded. `PROGRESS.md` cites 4.7.6.

---

## Phase 5

### D-050 jenkins-dev retries a failed SCM checkout twice (`scmCheckoutRetryCount: 2`)
**Date:** 2026-10-13 · **Status:** decided and applied (requested after the Phase 5 gate's DNS
failures)

**Why.** Docker Desktop's DNS intermittently failed to resolve `github.com` from the agents. A
build then failed at its clone, and five runs of the Phase 5 gate failed that way before one
passed (PROGRESS, Known gaps).

**Decision.** `scmCheckoutRetryCount: 2` under `jenkins:` in `jenkins/casc/dev.yaml`, and nowhere
else. Jenkins core then retries a failed SCM checkout twice more, 10 seconds apart: three attempts
in all.

**It retries every checkout failure, not only DNS.** A branch or commit that does not exist, a
repository that cannot be reached, refused credentials and a dropped lookup are all retried alike.
A checkout that can never succeed now fails about 20 seconds later, with "Retrying after 10
seconds" in its log. What is not a checkout is never retried: a failing test, a failing step, or
the Jenkinsfile's own refusal of a bad `BRANCH` or `COMMIT`.

**Checked before it was applied:**
- The YAML parses with a loader that refuses duplicate keys. The change is ten added lines, and no
  other setting moved.
- Jenkins core 2.568.3 has `Jenkins.setScmCheckoutRetryCount`.
- JCasC 2130.v3ef02f16a_34b_ checked the file through its dry-run endpoint
  (`POST /configuration-as-code/check`), using the admin account from inside the container:
  - the current file and the new one both came back clean;
  - a control with the attribute misspelled was refused (HTTP 400), and the list of valid
    attributes in that refusal includes `scmCheckoutRetryCount`.
- The first attempt at that check sent the YAML form-encoded. Every input then came back clean,
  the control included, so that result was discarded.

**Applied** by restarting `jenkins-dev` (`docker compose restart jenkins-dev`). The file is
bind-mounted read-only, and JCasC applies it at boot.
- Jenkins was fully up 8 seconds later, with no JCasC error, and its own `config.xml` holds
  `<scmCheckoutRetryCount>2</scmCheckoutRetryCount>`.
- It covers both job types, as observed: on a commit that does not exist, the freestyle checkout
  and the Pipeline's `checkout` step each logged "Retrying after 10 seconds" twice, and each failed
  after about 30 seconds instead of about 5.

**Verified afterwards, on the same day:**
- `verify.py --phase 1`: ALL CHECKS PASSED.
- Every integration test: 31 passed, and 1 skipped, which needs its own PostgreSQL setup, as
  before.
- The full `verify.py --phase 5`: ALL CHECKS PASSED, 71 of 71.

That gate run proves the setting does no harm. It does **not** yet prove it cures the flakiness:
none of the run's 23 builds met a DNS error, so no checkout needed a retry.

**Consequences:**
- Logs can now hold a checkout error that a retry recovered from. T5.9 reads the failing step
  before the rest of the log (D-049), so such an error does not take the blame for a later failure.
- **Still exposed:**
  - a DNS outage longer than the roughly 20-second retry window;
  - the Git lookups the backend makes itself (`git ls-remote` from the host while parsing and
    validating), which this setting does not touch.
- Not applied to `experiment-baseline.yaml` or `experiment-plugin.yaml`. That was not requested,
  and those controllers' build timings are the experiment's measurements.
- BUILD_PROMPT 4.2.2 lists what `dev.yaml` must configure. This is an addition to that list,
  recorded here rather than by editing the specification.

### D-049 Explain failure: code decides the facts, the model words them, every quote is checked
**Date:** 2026-10-13 · **Status:** decided and implemented (T5.9)

Part 3 gives T5.9 one line: "Explain failure" for failed runs. The rest comes from the rules it
sits under:
- 4.4.4 lists the run endpoints.
- 4.5.1 asks for a strict schema, every call in `llm_calls`, and quota limits.
- 4.5.3 says "code decides, never the model".
- 4.5.6 says text inside data is data, never instructions.
- 4.5.5 confines deploys to staging.

**Surface.**
- `POST /api/runs/{id}/explain` sits with the other run endpoints. It is open to any signed-in
  user, like the log it reads, and shares the assistants' 20-a-minute limit.
- The run card gains `failed_run_id`, so Phase 6 can offer the action on a failed card.
- No new intent action: 4.5.2's action list is the report's.
- No UI: that is Phase 6.

**Redaction first** (`app/failures/redact.py`). The excerpt goes to Groq, a third party, and quoted
lines come back to the browser, so redaction runs before anything else reads the log. It masks:
- the configured secrets, by value: the Jenkins token, Groq key, JWT secret and metrics token;
- token formats: GitHub, Groq, OpenAI-style, AWS, Slack, JWT and Jenkins API tokens;
- credentials in URLs, `Authorization` and `Bearer` values, secret-named assignments, private-key
  blocks, and email addresses.

It keeps line numbers (one line in, one line out) and runs in linear time. A pathological line
written by a commit cannot stall the request: lines are capped, every pattern is literal-led or
bounded, and costly patterns are prefiltered by keyword. The real logs pass through unchanged,
and a test checks that.

**Code decides the facts** (`app/failures/analysis.py`). The rules were written against logs
captured on jenkins-dev, which are kept as test data. Code works out:
- the category: checkout, infrastructure, timeout, tests, lint, security, script, build, deploy,
  or unknown, and never a guess;
- the failed stage. For freestyle it comes from the stored artifact; for a Pipeline, from the stage
  view;
- the failing tests and their counts, the exit code, and the evidence lines numbered as Jenkins
  numbers them;
- the stages a Pipeline skipped, read from its own "skipped due to earlier failure(s)" lines;
- what a freestyle failure stopped, read from the chain's runs in the database. "The deploy job
  never started" is the Phase 5 acceptance itself, stated by the explanation.

**The excerpt is the same for every run of the same failure.** It holds the failing step or stage
plus notable lines from elsewhere, and code removes or replaces everything that varies:
- Timestamper prefixes and hidden console notes are stripped.
- Durations, temporary script names, build numbers, clock times and SHAs become placeholders.
- The `<log>` fence is defused inside the excerpt.

That makes a recorded answer replay (T5.8) and keeps the prompt small. The integration test shows
two real runs on jenkins-dev giving identical prompts.

**The model words it, and is checked** (`app/failures/explainer.py`, prompt `failure_v1`). The
schema is strict and has four fields: `cause_found`, `summary`, `evidence` and `suggestions`. The
answer is dropped for the code's own explanation if:
- any quoted line is not in the excerpt it was shown;
- it says no cause is visible when the code found one;
- the summary mentions production at all;
- it is malformed or too long.

Suggestions that look like commands, or that mention production, are dropped one by one. The
three prompt examples are rendered by the code from captured logs, and a test keeps them identical
to what the code sends.

**Failures.**
- When the log is gone (Jenkins 404), the explanation says so and the model is not asked.
- When Jenkins is unreachable, the endpoint returns 409 `JENKINS_UNAVAILABLE`, asking for a retry.
- When the model is unavailable, the code's explanation is used and the fallback is shown
  (4.7.4).
- A log Jenkins is still writing is read again for up to 5 seconds (D-039), then marked
  incomplete.
- Only the last megabyte of a log is read, streamed, so a build that prints without limit cannot
  exhaust the backend. Line numbers keep Jenkins's own numbering. This was the Phase 5 security
  review's finding 1; see `docs/security-review-phase-5.md`.
- A network or DNS fault on the agent counts as infrastructure, not a checkout error. It is
  checked first, because "check the branch was pushed" is the wrong advice for it. This was found
  on a real failure.
- The failing step is read first, against every rule. Only when it shows no cause do the
  whole-log rules (infrastructure, checkout, timeout) look at the rest of the log. A clone error
  that a retry recovered from cannot then take the blame for tests that failed afterwards. When no
  shell step ran at all, the checkout is the failing step and the whole log is its section.

Every call, including a failed attempt, is an `llm_calls` row, with the prompt version and the
command its chain came from.

**Rejected.**
- Streaming the explanation, as T5.6's does: streamed text cannot be checked before it is shown.
- Letting the model choose the category: 4.5.3.
- A response cache: an answer that fails the checks would be served again, the planner's reason.
- Storing explanations: that needs a table 4.4.3 does not have, and a log does not change once a
  run has finished, so asking again costs only quota, which the rate limit bounds.

**Found on the way, by running against real output.** The first end-to-end run explained a real
failed Pipeline as `unknown`. Jenkins prefixes every Pipeline step line with a Timestamper time
(`[2026-10-13T06:28:51.225Z] FAILED ...`), so every rule anchored at the start of a line missed.
The hand-made Pipeline fixture had no timestamps. The prefix is now stripped, and the real log is
a test fixture.

### D-048 Status, rerun and cancel act only on a service the user named
**Date:** 2026-10-13 · **Status:** decided and implemented (found by T5.8)

The first end-to-end recording showed gpt-oss-120b answering "What's the status of my last
deploy?" with `service: payment-service`, a service the message never names. The status card then
showed the wrong chain. A generating request is confirmed on its intent card before anything
runs; status, rerun and cancel are not. A guessed service there would show, re-run or cancel the
wrong chain.

**Decision.** For those three actions, `IntentParser` keeps the model's service only when the
user named it: either the rule parser finds it in the message (exact name, unique stem or close
typo), or it was a clarification answer. Otherwise it is dropped to null, with a note, and the
user's latest chain is used. This is narrow, like D-037's UNSUPPORTED rescue, and the prompt was
not tuned. The model's answer stays in `model_intent`, so the evaluation still scores it.

**Also found by the same run:** a harness bug, not a product one. Sharing one Groq client across
tests, each on its own event loop, made the next request fail with "Event loop is closed". The
e2e harness now gives each test its own provider.

### D-047 Chains: the lock, tracking, the run card and run commands
**Date:** 2026-10-13 · **Status:** decided and implemented (T5.7)

- **A `chains` table, which 4.4.3 does not list.** 4.6.4 needs a per-service lock with a 30-minute
  expiry, and the run card needs to know which builds belong to one chain. Jobs are reused by
  every chain for their service, so neither fits an existing table. One additive migration
  (`c4e1d07a5b92`) adds `chains` and a nullable `job_runs.chain_id`. Verified on the stack's
  PostgreSQL in a scratch database: upgrade, downgrade, upgrade again, and `alembic check`
  finding no difference between models and schema.
- **The lock is the row.** A RUNNING chain holds its service's lock, and a partial unique index
  allows one per service. Two approvals racing for the same service cannot both win, even if both
  checked first. Approval claims the lock in the same commit as the approval, before Jenkins is
  touched, and releases it (ABORTED) if Jenkins fails. After 30 minutes a running chain no longer
  blocks: the next claim marks it EXPIRED.
- **Tracking reads the database, not memory.** Each tick decides from the stored runs: wait while
  the current build runs; on SUCCESS find the next job's build through the `UpstreamCause` its
  downstream trigger recorded (confirmed live on jenkins-dev); on anything else stop the chain
  there. A restarted backend finds a chain's first build again through the queue item stored on
  the chain.
- **Pipeline stages** come from the stage view (`wfapi/describe`, confirmed live), without
  Declarative's own post-actions stage. The tracker publishes `chain.stages` only when they change.
- **Endpoints beyond 4.4.4's table.** `GET /api/chains`, `GET /api/chains/{id}` (the run card:
  job states, stages, and queue rank, score and waiting reason from the plugin) and
  `POST /api/chains/{id}/cancel` (4.6.4: cancels queued members and stops the running one).
  Chains are visible to any signed-in user, like runs. Cancelling is for the starter, DevOps and
  Admin.
- **Run commands act.** A confirmed STATUS shows the user's latest run card (4.6.5, "no
  generation"). RERUN re-triggers the last failed test job as a new chain from that job onward,
  with the original chain's parameters: if the tests now pass, the job's own trigger carries on
  downstream, and the chain the user sees matches what Jenkins does. CANCEL cancels the running
  chain. Each is refused by the lock and the permissions like anything else, and a refusal
  comes back as a reply rather than an error.

### D-046 Generating, approving and explaining
**Date:** 2026-10-13 · **Status:** decided and implemented (T5.6)

- **Every generation is a row, valid or not.** 4.7.4's progress line ("Understood, Planned,
  Rendered, Validated, each showing a check or the exact error") needs a failed step to be
  something to read, not an error page. A regenerate cancels the earlier rows of the same command,
  so an outdated plan cannot be approved by mistake.
- **A render failure still runs the spec checks.** 4.6.3 orders them before the artifact check.
  An edited spec that deploys to production fails "environment allowed" in the checklist, not
  only "no command for that stage".
- **Editing the YAML cannot change what policy decided.** The service, the assistant and the
  priority were checked against the role, the HIGH quota and the justification when the request
  was confirmed (4.5.5). An edited spec that changes them is invalid, and points the user to
  editing the request instead. Everything else in the spec may be edited and is re-validated.
- **Approval is idempotent, and a double click cannot start two chains (4.6.4).** The row is
  locked (`FOR UPDATE` on PostgreSQL), marked approved with the key and committed *before*
  Jenkins is touched:
  - the same key replays the first result and starts nothing;
  - another key gets `ALREADY_APPROVED`;
  - a key already used for another plan is refused;
  - if Jenkins fails before the chain starts, the approval is undone so the user can retry.
- **Jobs are saved last first** (D-044), created or updated in place. The bot has no
  `Job/Delete` (D-033), and jobs are reused across approvals for the same service and stage.
- **What approving will do is stated before it is done.** The summary follows 4.7.4's wording.
  It is worked out at generation time from which jobs already exist: "Creates 4 jobs and starts
  fs-payment-service-build on main at HIGH priority", or "updates N" when some are reused.
- **The explanation** streams from the first model that answers, using `explain_v1`. A model that
  fails partway leaves what it said, marked as cut short. With no model, and always in fake mode,
  the code writes the explanation from the same input. That input carries the rendered jobs and
  their catalog commands, and not the justification. Each explain call is recorded in `llm_calls`
  with its prompt version, through its own session, because the stream outlives the request's.
- **Approval hands over to the chain lock and tracker through two hooks,** `before_start` and
  `on_started`, which T5.7 fills.

### D-045 How a conversation turns messages into commands
**Date:** 2026-10-13 · **Status:** decided and implemented (T5.5)

- **Two reads beyond 4.4.4's list.** `GET /api/conversations/{id}` (a chat with its messages)
  and `GET /api/commands/{id}` (an intent card). The workspace in 4.7.4 opens chats from a
  history list and re-reads cards, and cannot do either with the listed endpoints alone (rule
  1.4: implement the correct endpoint and record the deviation).
- **When a reply is an answer.** 4.5.3 says to merge an answer with the original message and
  re-parse, but not how to tell an answer from a new request. A reply counts as the answer to the
  pending question if it is one of the offered buttons, is four words or fewer, or answers a
  request for a justification, which is a sentence by nature. Anything longer starts a new
  request: "deploy auth-service to staging" typed in reply to "Which service?" means the user
  started over.
- **Slash commands** (4.7.4). `/help` answers with the help card and parses nothing. `/status`
  and `/rerun` become the sentences they stand for and go through the same validation, policy
  and audit as typed words.
- **Editing an intent** (`PATCH /api/commands/{id}/intent`) reruns 4.5.3 steps 3 to 5 through
  `IntentParser.reconsider`, with no model call. It runs the same validation, policy and
  clarification as a parse, now shared with `interpret` so the two cannot drift. The action
  cannot be edited (a different action is a new request), unknown fields are refused rather than
  ignored, and a request already approved cannot be edited. The model's own parse is kept as
  `model_intent`, so the evaluation still scores the model rather than the user's correction.
- **The running-chain rule needs the service, which is known only after parsing.** A request
  that comes out READY is re-decided with the running chain for its service, reusing the parse
  rather than calling the model again.
- **Someone else's conversation or command is reported as not found**, not forbidden, so its
  existence is not disclosed.
- **Assistant traffic has its own rate limit:** 20 a minute per client. Every message can call the
  model, and Groq's 30 requests a minute per model are shared by the whole team (4.5.1).
- **Providers.** The live and replay providers are shared across the process, so there is one
  Groq client and connection pool. A fake provider is built per request because it answers from
  the catalog. The factories take `has_models` with a supplied provider, so live mode without a
  key still goes straight to the rule parser and the default plan.

### D-044 What the validators check beyond the letter of 4.6.3
**Date:** 2026-10-13 · **Status:** decided and implemented (T5.4)

`FreestyleValidator` and `PipelineValidator` run 4.6.3's eight checks in order and report every
one, passed or not, because the preview shows them as a checklist. Choices the list leaves open:

- **An edited spec must keep the catalog's repository and agent label.** The YAML is editable
  (4.6.2 step 4). A spec pointing at another repository would run someone else's code on the
  agents, and the rule that values come from the catalog would be meaningless.
- **An unreachable remote warns, and a commit that is not a branch tip warns** (D-037, D-024).
  Jenkins fails the checkout honestly if either is wrong.
- **A linter that cannot be reached fails the check.** Validation that did not run has not
  validated anything. The user regenerates once Jenkins answers.
- **"No production anywhere" covers everything that reaches Jenkins** and every structured value
  in the spec. It leaves out the justification, which is never written into a job (D-043).
- **Each failure names its cause** (`plan`, `input` or `template`), because 4.6.2 sends only plan
  errors back to the model. To make that true end to end, the planner's own checks now include
  the one plan error the validator could otherwise catch first: a stage name mentioning
  production. Every validator failure caused by the plan is therefore found during planning,
  within the repair budget. What reaches validation is the input or the template, and template
  bugs are the golden-file tests' job.
- **Jobs are created last first.** The linter integration test showed what the exporter already
  worked around: Jenkins drops a downstream trigger that names a job that does not exist yet.
  Approval (T5.6) creates a chain from its last job to its first.

### D-043 How a spec becomes Jenkins jobs
**Date:** 2026-10-13 · **Status:** decided and implemented (T5.3)

**Templates are the exports, and a test proves it.** `app/generation/templates/` holds three
Jinja2 templates: a freestyle chain job, a Pipeline job and the Jenkinsfile. Each is the matching
`jenkins/reference-configs/` export with its variable parts replaced. `test_generation_render.py`
checks the derivation, not only the output:
- The reference job's own values render the exported Jenkinsfile byte for byte.
- They render the exported Pipeline job element for element, apart from the description.
- Every chain job matches the exported freestyle job, apart from the parts that vary by design:
  the description, `dependsOn`, parameter defaults, shell steps and the downstream trigger.

**Deviations, each forced by something measured:**
1. **Test jobs are named by suite**, `fs-<service>-test-<suite>`, not Appendix F's
   `fs-<service>-test`. "Every suite" (D-042) can put two test stages in one chain, and the
   appendix's name would give both the same job.
2. **A freestyle test, lint or scan job runs the build command first.** Every chain job has its
   own workspace, wiped before each build (the reference's `PreBuildCleanup`). `test.sh`, `lint.sh`
   and `security_scan.sh` only activate the `.venv` that `build.sh` creates. The build *stage*
   still runs first in the chain, so a broken build stops everything after it. This is what the
   acceptance chain's test job always did. 4.6.3's "one shell build step per stage" holds for the
   stage's own command; the second step is preparing the workspace.
3. **The Pipeline reference now carries `JobPriorityProperty` in config.xml.** 4.6 asks for
   "property in config.xml plus `options { dynamicQueuePriority(...) }`", but the export had only
   the options block. That block applies only once the script runs, so a new job's first trip
   through the queue would have been ranked at the default level. The property was added to the
   exporter and re-exported, so it is in the template because Jenkins stored it.

**Also decided:**
- **Job names.** Freestyle: `fs-<service>-<stage>`, with `build`, `lint`, `security-scan`,
  `test-<suite>`, `deploy-<env>`. Pipeline: `pl-<service>-<action>[-<env>]`, with `build`,
  `test`, `deploy` or `build-test-deploy` as the action.
- **No user text is written into Jenkins.** Job descriptions are built from the stage names and the
  service, never the justification. The justification lives in the audit log and the pipeline
  row. A HIGH request justified by a "production incident" must not trip the "no production
  anywhere" validation (4.6.3), and free text has no place in a config file.
- **Escaping.** Every value in an XML template is XML-escaped. Jenkinsfile values go through a
  Groovy single-quote filter that escapes `\` and `'` and refuses line breaks. The script is
  XML-escaped again when it goes into `<script>`.
- **Golden files** for four specs (two chains, two Pipelines) live in `tests/golden/`. Every byte
  is compared. `UPDATE_GOLDEN=1` rewrites them for an intended change, to be reviewed as a diff.

### D-042 What the planner plans, what code checks, and when the default plan takes over
**Date:** 2026-10-13 · **Status:** decided and implemented (T5.2)

**What the specification leaves open.** 4.6.2 gives the planner two sentences: "the model turns the
intent plus catalog into the spec through a strict schema. A fixed default plan per action takes
over when the model is unavailable", and "errors caused by the model's plan go back to it for at
most 2 repairs". It does not say what each action's plan contains, which suite runs when none is
named, where extra stages go, or what happens when the repairs run out. The project owner decided
all four at the start of T5.2:

| Question | Decision |
| --- | --- |
| Stages per action | **Build first when needed.** BUILD: build. TEST: build, tests. DEPLOY: deploy. BUILD_TEST_DEPLOY: build, tests, deploy. Any test, lint or security_scan stage brings a build in front of it. |
| Test stage, no suite named | **Every suite**, one test stage each, in catalog order |
| Extra stages | **Checks before tests.** build, lint, security_scan, tests, deploy, then a smoke test |
| Plan still invalid after 2 repairs | **The default plan**, marked `ai_fallback` with the reason |

**Why a build comes first.** Measured from the repository, not assumed. `test.sh`, `lint.sh` and
`security_scan.sh` only *activate* the `.venv` that `build.sh` creates. The agent image has
Python, pip and venv but no pytest or ruff, so none of those stages can run without a build in
the same workspace. `deploy.sh` runs `docker build` itself, so a deploy needs nothing before it.

**What the model decides, and what code decides.** 4.6.1 gives the model "only stages and
templates", and 4.5.3 says "code decides, never the model". `required_stages` derives the stage
list the confirmed intent requires. The model's plan is checked against it, and the model names
the stages. A missing stage, an unrequested one, a wrong suite or environment, a wrong order or a
repeated name is a plan error, and the issues go back to the model word for word. The default plan
is the required list with standard names, so it can always take over. The prompt restates the
rules, but the code is what decides: a test fails if any few-shot example is not the code's own
default plan.

**Also decided while implementing:**
- **No free text reaches the model.** The planner's request holds the action, service, suite,
  environment and extra stages, each already checked against the catalog, plus what the service
  offers. The branch, commit and justification go straight into the spec. A justification written
  to steer a model has no model to steer.
- **Planner calls are not cached.** A first answer that fails the checks would otherwise be served
  again for ten minutes, and each repeat would start its repairs from a plan known to be wrong.
- **An unplannable request is an error, not a guess.** A non-generating action, a deploy without an
  allowed environment, or a suite or extra stage the service lacks raises `PlannerError` and is
  never sent for repair. Validation, clarification and policy should already have stopped each one.
- **Unresolved "latest".** When the validator could not reach the remote, it kept "latest" and
  warned on the intent card that the newest commit at build time would be used. The spec then
  carries no commit, so the job builds the branch head (D-041 rule 2), and the outcome repeats the
  warning.
- **Fake mode** answers through `FakeProvider` with the default plan, labelled `fake`. The intent
  parser's fake responder answers every call with an intent, so the planner has its own.
- **The evaluation hooks.** Every attempt is kept. `valid_before_repair` and `valid_after_repair`
  are `None` when no model answered, never `False`. `max_repairs=0` is 4.9's "no repair loop"
  ablation, and `include_examples=False` its "no few-shot examples".

**Noted for T5.3.**
- Each freestyle job has its own workspace, so a test, lint or scan job must run the build command
  in that job too. The acceptance chain's test job already does (`build.sh`, then `test.sh`).
- "Every suite" can give a freestyle chain more than one test job, so job names need the suite in
  them.

**Evidence, 2026-10-13.**
- `tests/test_generation_planner.py`: 64 passed. That includes every plannable combination in the
  catalog checked against the order rule.
- `tests/test_generation_planner_live.py`: 3 passed against Groq. `gpt-oss-120b` produced a valid
  plan on the first attempt for all three requests (no repairs), using about 1,700 to 1,800 tokens
  each. Each request is a combination no prompt example shows.

### D-041 One revision rule for both job types, applied by the backend
**Date:** 2026-10-12 · **Status:** decided and implemented (T5.1). Refines D-038, implements D-034

**The rule** (decided by the project owner at the start of T5.1):
1. A given `COMMIT` is checked out exactly, and wins over `BRANCH`.
2. Otherwise the head of the given `BRANCH`.
3. Otherwise the head of `main`.
4. Both job types use the same validation and error handling. A commit or branch that was given
   but is invalid or missing is an error. It never silently falls back to another revision.

**What the old references actually did.** Measured on jenkins-dev before any change, with two
probe jobs derived from the reference exports that print `git rev-parse HEAD`:

| BRANCH / COMMIT | Freestyle (`${COMMIT}`) | Pipeline (`COMMIT ?: BRANCH`) |
| --- | --- | --- |
| main / demo tip | demo tip | demo tip |
| main / missing SHA | FAILURE at checkout | FAILURE at checkout |
| demo / blank | demo tip, by accident (BRANCH ignored) | demo tip |
| missing branch / blank | **SUCCESS on another branch** | FAILURE at checkout |
| blank / blank | some branch | **SUCCESS on `demo/failing-tests`** |

An empty branch spec is not an error to the Git plugin; it means "any branch". Both job types
could therefore build an unrequested revision and report success.

**Conflict with D-038.** D-038 found that a freestyle Git SCM can follow only one variable. The Git
plugin expands `${VAR}` and nothing else, and no installed plugin can compute a value before
checkout. So "COMMIT, else BRANCH, else main" cannot be written inside a freestyle job. Spec 4.6
already points to the answer: a freestyle chain's branch and commit are "parameter defaults written
on every chain job before triggering the first". The rule is therefore applied *before* Jenkins,
where those values are chosen. The owner chose this option over a fixed verify step in every
freestyle job, or replacing the Git SCM with a shell checkout, which 4.6.3 rules out.

**Decision.**
- **One function.** `app/generation/revision.py` `select_revision(commit, branch)` applies the
  rule. A blank value counts as not given, as Jenkins trims parameters. The commit must be 7 to 40
  hexadecimal characters (lower-cased). The branch must pass the `GitClient` ref pattern, with no
  `..` and no trailing `/`. An invalid given value raises `RevisionError` naming the field. Both
  are checked even when the commit wins, because the branch is still written into the job.
- **Identical values for both job types.** `Revision.parameters()` gives `BRANCH` (the branch the
  revision belongs to) and `COMMIT` (the commit SHA, or `refs/heads/<branch>`). `COMMIT` is never
  empty, so an empty branch spec never reaches Jenkins. The fully qualified ref means a branch
  name is never read as a SHA or a tag, and a missing branch fails the checkout instead of
  matching another one.
- **Freestyle.** The Git SCM keeps `${COMMIT}`. The backend writes both values as defaults on
  every chain job. The reference default is `refs/heads/main`, the rule's third clause.
- **Pipeline.** The Jenkinsfile applies the rule itself, with the same patterns as the backend
  (a unit test compares them). It stops with `error()` *before* checkout on an invalid `COMMIT` or
  `BRANCH`. A blank pair builds `main`, not "any branch". `COMMIT` defaults to empty so a run
  started by hand with only `BRANCH` changed builds that branch. The parameters are now also in
  config.xml, which implements D-034: the job is parameterized from creation and keeps its
  parameters when the config is pushed again.
- **The spec.** `GenerationSpec` (T5.1) runs the rule at validation, so a hand-edited YAML naming
  an invalid commit or branch is rejected rather than built from something else.

**Known gap.** A freestyle job started by hand from the Jenkins UI with only `BRANCH` changed still
checks out its `COMMIT`. Nothing in the system starts a job that way. The rule holds for every
path the backend uses, and for both job types when run by hand except that one.

**Tests changed, and why.** The old reference made the Pipeline job unparameterized until a first
run. `test_integration_jenkins.py` was written around that:
- `test_a_pipeline_job_is_created_triggered_and_read` triggered *without* parameters. A
  parameterized job answers that with 400, so it now triggers with the backend's parameters, and
  gains an assertion that the job is parameterized from creation. Its other assertions are
  unchanged.
- `test_a_pipeline_job_accepts_parameters_only_after_its_first_run` described a restriction that
  no longer exists. It is renamed `test_a_pipeline_job_still_accepts_parameters_after_a_run`, its
  docstring is corrected, and its assertions are unchanged.

**Evidence, 2026-10-12.**
- Re-exported both references from jenkins-dev. Jenkins kept the Pipeline's
  `ParametersDefinitionProperty`.
- `tests/test_integration_revision.py`: 17 passed on jenkins-dev. Both job types land on the same
  commit for commit-wins, branch-head, neither and both-blank. Both fail at checkout, with nothing
  checked out, for a missing commit or branch. The Pipeline applies the rule to raw parameters and
  refuses invalid ones before checkout. A chain job triggered without parameters follows its
  written defaults. A config pushed twice keeps its parameters and accepts them straight away.

**A guard check changed, and why.** `verify.py`'s "catalog loads through one schema-validated
loader" treated any `yaml.safe_load` outside `catalog.py` as a second catalog parser. The spec is
YAML the user edits (4.6.2 step 4), so `spec.py` must parse it. The check now names
`app/generation/spec.py` as the one other YAML document allowed, with its reason, and fails if
that file ever reads the catalog file. Any other new parser still fails: proven by adding a
throwaway parser, which the check rejected.

### D-040 T5.8's command list is Part 4.6.5, not 4.6.7
**Date:** 2026-10-11 · **Status:** decided, corrects the specification

**Conflict.** T5.8 asks for end-to-end tests of "every command in Part 4.6.7", but Part 4.6 ends
at 4.6.5. The only command list in Part 4.6 is 4.6.5, "Commands version 1 must handle": nine
messages with their expected behaviour. Nothing else in the specification, report or legacy code
refers to a 4.6.7.

**Decision.** 4.6.5 is the intended reference. `BUILD_PROMPT.md` line 256 is corrected to say so.
This is the only edit to the specification since it was committed with `m2-final`, and it changes
a section number only, not the requirement. T5.8 therefore covers all nine 4.6.5 messages,
including the three that must *not* generate a job (production refusal, the status question, and
the injection attempt).

### D-038 Four defects found by the first real checkout of the service repos
**Date:** 2026-10-11 · **Status:** all fixed

`scripts/accept_failing_tests.py` assembled 4.6's freestyle chain (build -> test -> deploy-staging,
success-only triggers) from the reference export and ran it against the newly pushed repositories,
with a control run on `main` alongside each `demo/failing-tests` run. The control is what exposed
these: without it, "deploy never started" would have passed three times for the wrong reasons.

1. **The reference branch spec never worked.** `freestyle-build-test-deploy.config.xml` used
   `${COMMIT:-${BRANCH}}`. The Git plugin expands only plain `${VAR}`: it expanded `${BRANCH}` and
   left `${COMMIT:-main}` as a literal revision, so every checkout failed with "Couldn't find any
   revision to build". Unnoticed until now because the repositories did not exist and every
   checkout failed at clone anyway. **Fixed** in `export_reference_configs.py` and re-exported from
   what Jenkins stored: the branch spec is `${COMMIT}`, and `COMMIT` is the revision to check out --
   a commit SHA, or a branch name for its head, defaulting to `main`. One parameter has to carry the
   revision because no plugin-supported syntax expresses "commit if given, else branch". This also
   suits Phase 5: the validator already resolves "latest" to a SHA at approval, so the generator
   writes that SHA into `COMMIT` and the job builds exactly the approved commit. The exporter's
   `create()` was also fixed: it deleted then created, the delete silently 403'd (D-033), and every
   re-export after the first failed with "already exists". It now updates in place.
2. **No script was executable.** Every `.sh` file in both services was committed as `100644`
   (authored on Windows), so every catalog command failed with "Permission denied". **Fixed:** a
   mode-only commit on `main` of both service repositories, cherry-picked onto
   `demo/failing-tests`, and the same change in `sample-services/`.
3. **Agents could not reach the Docker socket.** Docker Desktop mounts `/var/run/docker.sock` as
   `root:root 660`; the agent's `jenkins` user is in a `docker` group (gid 1001) fixed at build
   time, which can never match a GID only known at run time. The Dockerfile's comment claimed the
   group "is overridden at run time"; nothing did that. **Fixed:** `jenkins/agent/docker-socket-access.sh`
   wraps the base `setup-sshd` entrypoint and, before sshd accepts a session, matches the socket:
   on Docker Desktop (gid 0) it hands the socket to the agent's `docker` group rather than putting
   `jenkins` in the root group; elsewhere it joins `jenkins` to whichever group owns it.
4. **The deploy health probe looked at the wrong host.** `deploy.sh` waited on
   `http://localhost:PORT/health`, but inside an agent container the service's port is published on
   the Docker host, so every deploy timed out after 60 s even with the service running. Proven with
   a throwaway container first: `localhost` gave no answer, `host.docker.internal` gave 200.
   **Fixed:** the probe host is `DEPLOY_HEALTH_HOST` (default `localhost`, so deploying from the
   host behaves as before); the agents set it to `host.docker.internal`, with `extra_hosts:
   host-gateway` so the name also resolves on a plain Linux host. Pushed to `main` of both service
   repositories and cherry-picked onto `demo/failing-tests`.

**Also learned:** each chain job checks out into its own workspace, so payment-service's test job
has no `.venv` from the build job and must run the catalog's build command first. T5.3's freestyle
template has to account for that.

## Phase 4

### D-037 The parser's ordering, and where code overrules the model
**Date:** 2026-10-09 · **Status:** decided

4.5.3 lists the steps; four choices about how they combine are not in it.

**Policy runs before clarification.** A production deploy is refused whatever service it names, so
asking "which service?" first would spend the user's time on a question whose answer cannot change
the outcome.

**Policy audit events are written only when the policy decided the outcome** — a refusal, a
request for a justification, or a request that proceeds. A HIGH request still waiting on a
clarification is not yet a request; auditing it each round would count it against the daily quota
once per question asked. The quota itself counts only entries marked `granted`.

**An unreachable remote is a warning, not a block.** A remote that answers and lacks the branch is
a known problem and gets a question. A remote that cannot be reached is an unknown: the card warns
and the request goes on, because Jenkins fails the checkout honestly if the branch is wrong — and
because blocking would make the assistant unusable whenever GitHub is slow, or today, for as long
as the catalog's sample repositories stay unpushed.

**A model's UNSUPPORTED can be overruled, narrowly.** T4.3's live smoke run found
`gpt-oss-120b` calling `"deploy it"` UNSUPPORTED at 0.9 confidence. A false UNSUPPORTED is a dead
end; a question costs one round. So if the rule parser sees a CI/CD action *applied to something* —
a service, an environment, a suite, or an object such as "it" or "the build" — the action is kept
and the missing fields are asked for. A verb in small talk ("how do I build a birdhouse") does not
qualify. The prompt was deliberately *not* edited for this: Appendix E restricts tuning to the
development split, and "deploy it" is exactly what the evaluation's missing-field category will
contain. The model's own answer is stored as `model_intent`, so the evaluation scores the model and
not this correction.

### D-036 `llm_calls` gains `prompt_version` and `outcome`
**Date:** 2026-10-09 · **Status:** decided

**Conflict.** 4.4.3 lists `llm_calls` as command id, provider, model, latency, prompt tokens,
completion tokens, fallback used, cached. 4.5.6 requires the prompt version "stored on every call",
and 4.5.1 that "every call is recorded in `llm_calls`". Neither fits the 4.4.3 column list.

**Decision.** One additive migration (`8c2f4d1e7a90`) adds two columns:

* `prompt_version` — where 4.5.6's requirement can actually be met, since this is the table with a
  row per call. The version is the prompt file's name plus a short content hash, so an edit to
  `intent_v1.md` without a version bump is still distinguishable in the data.
* `outcome` — `ok`, `rate_limited`, `unavailable`, `invalid`, `rejected`, `replay_miss`, `skipped`,
  `cached` or `error`. Recording *every* call means recording failed ones, and a failed call has no
  tokens. Without an outcome, its row reads as a successful zero-token call, and the evaluation
  chapter's latency and tokens-per-command figures would be quietly flattened by every outage.

`outcome` has a server default of `ok`, because every row written before this migration was a
successful call — failed calls could not be recorded until now. Verified on the Compose
PostgreSQL: upgrade, downgrade, re-upgrade, and an autogenerate that produced an empty diff.

**Also decided: the quota tracker trusts the server over itself.** Local per-model counters are what
4.5.1 asks for and they work before the first response. But Groq returns `x-ratelimit-*` headers on
every response (observed live: `limit-requests` 1000, `limit-tokens` 8000, matching 4.5.1 exactly),
and those see the eval harness's usage too. When the server says no requests remain, that wins.

---

## Phase 3

### D-039 A Pipeline reports itself finished before its log is complete
**Date:** 2026-10-11 · **Status:** decided, fixes a defect

(Numbered D-039 because `phase-5-assistants` already uses D-038.)

**Symptom.** `test_a_pipeline_job_is_created_triggered_and_read` failed about once in 20 runs
(2 in about 45). It failed only on `assert "Finished: SUCCESS" in log`, even though the build's
result was SUCCESS.

**Cause.** Jenkins's `WorkflowRun` marks the run completed, so the API reports `building: false`
and a result, *before* it writes `Finished: SUCCESS` to the console. Freestyle builds write the
line first, which is why only the Pipeline test failed. Measured directly on jenkins-dev by
polling every 50 ms and reading the log as soon as `building` turned false:

- The log still ended at `[Pipeline] End of Pipeline` in 3 of 25 builds, then 5 of 30.
- `progressiveText` returned `X-More-Data: true` in every one of those cases.

**The same defect was in production code.** `run_log` decided `more_data` from the run row only.
Once the tracker recorded SUCCESS, the UI stopped tailing and could lose the last line of a
Pipeline log for good.

**Decision.** Jenkins's `X-More-Data` is the authority on whether a log is complete:
- `JenkinsClient.console_window` returns a `ConsoleChunk` (text plus `more_data`). Its default
  wraps `console_text`, so the fake client and existing overrides are unchanged.
  `HttpJenkinsClient` reads the header.
- `run_log` reports `more_data` if the window was truncated, if the run is still RUNNING, **or**
  if Jenkins says it is still writing.
- The integration test reads the Pipeline log through `wait_for_complete_log`, which waits for
  `X-More-Data` to clear. Its assertions are unchanged.

**Rejected.** A sleep or retry around the assertion: it shortens the window without removing it.
Asserting less: it would stop checking the line that proves the build finished.

### D-035 The reference configs were not valid XML
**Date:** 2026-10-07 · **Status:** decided, fixes a defect

`scripts/export_reference_configs.py` wrote its provenance comment *above* the `<?xml version=...?>`
declaration. XML requires the declaration to be the very first thing in a document, so all three
files in `jenkins/reference-configs/` failed to parse.

This was not cosmetic. Rule 1.4 makes those files the source of every `config.xml` template; Phase
5's golden-file tests compare rendered output against them; and `FakeJenkinsClient` validates
well-formedness, so a template derived verbatim would have failed its own unit test. The files
looked perfectly fine in an editor, and nothing had parsed them until the Phase 3 integration tests
did.

**Decision.** The exporter emits the declaration first and the comment after it, and the three
existing files were corrected by moving the comment only — no exported content was touched, so they
remain exactly what Jenkins produced.

### D-034 A generated Pipeline job must declare its parameters in config.xml
**Date:** 2026-10-07 · **Status:** decided, constrains Phase 5

4.6 says a Pipeline job takes its branch and commit as "parameters passed at trigger time". The
live controller does not allow that on a new job: a declarative `parameters { ... }` block lives in
the *script*, so Jenkins only registers the parameters once a build has executed it. The reference
export's `<properties/>` is empty, and triggering a freshly created Pipeline job with parameters
returns **400 "is not parameterized"**.

Worse, it is not a one-time cost. Pushing the config.xml again wipes the parameters the first run
registered, because the empty `<properties/>` overwrites them — so every *regenerate* would
de-parameterize the job until its next build.

**Decision.** Phase 5's Pipeline generator writes a `ParametersDefinitionProperty` into the
config.xml rather than relying on the script's `parameters` block being discovered. That is the
only option that survives a regenerate. `test_a_pipeline_job_accepts_parameters_only_after_its_first_run`
pins the current behaviour so the constraint cannot be forgotten, and asserts the property appears
after a run — if it ever appears on a brand-new job, the generator is writing it and the
restriction is gone.

### D-033 The bot has no `Job/Delete`, and nothing in the backend may need it
**Date:** 2026-10-07 · **Status:** decided

Found directly: the Phase 3 integration tests tried to delete the jobs they created and got 403.

4.1 asks for a "least-privilege `orchestrator-bot` API token" and 4.4.5's method list does not
include deletion, so `jenkins/casc/*.yaml` grants `Job/{Read,Build,Cancel,Create,Configure}` and
deliberately not `Job/Delete`. A compromised backend token therefore cannot destroy build history —
which is the evidence the whole report rests on.

**Decision.** The permission stays off. Widening the bot's grants so a test can tidy up after
itself would be the wrong trade. `JenkinsClient.delete_job` is kept for an operator with a wider
token and its docstring now says plainly that it 403s as configured; nothing in the backend calls
it. The integration tests recreate their jobs instead of deleting them, which makes a rerun
idempotent and leaves two inert `it-` jobs on the controller.

`scripts/demo_reset.py` is the supported way to get a clean controller, using the admin account.

### D-032 Policy settings are reported, not editable
**Date:** 2026-10-07 · **Status:** decided

4.4.4 lists "policy settings" among the admin endpoints. 4.4.3 lists fourteen tables and none of
them holds policy, so there is nowhere to persist an override.

**Decision.** `GET /api/admin/policy` reports 4.5.5's five rules and the configured
`HIGH_URGENCY_DAILY_QUOTA`, and carries `editable: false`. There is no PATCH.

The rules in 4.5.5 are enforced in code and the one number is configuration. A writable endpoint
would need a table the specification does not have, and a settings page whose saves do not persist
would be worse than one that honestly says these are set elsewhere.

`production_enabled` is reported as a constant `false`. It is in the response so the Admin page can
show the state of the rule rather than omitting it, and constant because rule 1.5 refuses
production deploys outright — an admin screen implying it could be switched on would misrepresent
what the system does.

**Also decided here: the service catalog has no write endpoint.** 4.4.4 mentions admin "create,
update, resync" for the catalog, but only resync exists, and it pushes the *file* into the table.
Commands the model may run have to be reviewable in version control (4.6.1); an API that could
rewrite `catalog/services.yaml` at runtime would move the only source of shell commands out of the
repository, which is the property D-025 exists to protect.

### D-031 Run history comes from polling, with plugin metrics refining the timings
**Date:** 2026-10-07 · **Status:** decided

4.4.5 has `RunTracker` poll every three seconds; 4.4.6 has plugin metrics "fill queue timings that
polling can miss". Both, deliberately, because each alone leaves a hole.

The plugin is not the system of record and must not be: it reports only on the controller it is
installed on, only while installed, and `jenkins-baseline` runs without it on purpose. Metrics
alone would therefore lose every run on a plugin-less controller — including the baseline arm of
the experiment.

Polling alone would put a three-second error bar on every queue wait, and the waiting-time KPIs are
what the report's whole comparison rests on.

**So the precedence is fixed:** the tracker writes `queue_wait_ms` *only* when it is unset. The
plugin measured the wait from inside the queue; the tracker can only subtract two timestamps either
side of a poll. `verify.py` fails if that guard disappears, because losing it would silently coarsen
every figure rather than break anything visibly.

Both writers target the same `(job_id, build_number)`, which carries a unique constraint, so the
tracker upserts rather than inserting. A queue event always arrives before its run exists, so
unmatched timings are parked (D-027) and the tracker attaches them once the row appears.

### D-030 A slow WebSocket client loses events rather than slowing the tracker
**Date:** 2026-10-07 · **Status:** decided

`RunTracker` publishes from inside its tick, which also writes to the database. If a browser on a
bad connection could apply backpressure to that, one slow client would slow down recording run
history for everyone.

**Decision.** Each connection has its own bounded queue (256 events). `Hub.publish` is synchronous,
uses `put_nowait`, and on a full queue drops the *oldest* event to make room for the newest. A
client that cannot keep up loses intermediate states, which for a live view is the right trade: the
next event carries the current state anyway.

`verify.py` fails if `publish` becomes a coroutine or grows an `await`. Its own first version
matched the word "await" in the docstring explaining why there isn't one; it is line-anchored now.

### D-029 The WebSocket authenticates with its first frame, not a query parameter
**Date:** 2026-10-07 · **Status:** decided

4.4.4 lists `WS /ws` but not how it authenticates, and the choice matters because **a browser
cannot set headers on a WebSocket**. The common workaround is `/ws?token=...`.

**Rejected.** A query string reaches proxy and server access logs, browser history, and any
`Referer` sent onward. The access token would end up written down in several places nobody audits,
and it stays valid for fifteen minutes.

**Decision.** The socket is accepted, then has ten seconds to send one frame:
`{"type": "auth", "token": "...", "topics": [...]}`. Nothing is delivered before it arrives, and
anything else closes the connection. An unauthenticated socket can do exactly one thing.

The connection is accepted *before* authentication so a refusal can be a close code the browser can
read: 1008 means sign in again, 1011 means retry with backoff. Rejecting the handshake outright
gives the client only an opaque failure, indistinguishable from the server being down.

The close reason never says *why* a token failed — expired and forged are the same instruction, and
distinguishing them over an unauthenticated socket would reveal which tokens are real.

Cost: one extra `send` in the frontend hook (T6.2). `verify.py` fails if the endpoint ever reads
`query_params`, so the reason this was chosen cannot be quietly forgotten.

### D-028 The plugin under test is reinstalled on every controller start
**Date:** 2026-10-07 · **Status:** decided

Jenkins seeds `/usr/share/jenkins/ref/plugins` into `$JENKINS_HOME/plugins` only when a plugin is
absent, or when the image carries a *newer version*. The plugin under test is always
`2.0.0-SNAPSHOT`, so "newer" is never true. After the first boot of the `jenkins-dev-home` volume,
every later `docker compose build jenkins-dev` produced an image whose plugin was silently ignored,
and the controller kept running the `.hpi` from its first boot — with a `.pinned` marker beside it
telling Jenkins to keep it.

This was found the expensive way: the D-026 fix below appeared not to work, because the controller
being tested still had the previous build. The volume held 88,217 bytes while the image held 88,346.

**Decision.** `jenkins/controller/install-plugin-under-test.sh` wraps the stock entrypoint, removes
the exploded directory, the `.jpi`, the `.pinned` marker and `.version_from_image`, copies the
image's copy in, and then `exec`s `/usr/local/bin/jenkins.sh`. Scoped to this one plugin: everything
in `plugins.txt` is version-pinned and must keep Jenkins' own upgrade semantics, which is the whole
point of D-003.

For a plugin rebuilt on nearly every task, replacing it on start is the correct behaviour rather
than a convenience. The alternative — remembering to `docker volume rm` after each plugin change —
is a step that will be forgotten exactly when a result depends on it.

### D-027 Metric ingestion accepts what it does not understand
**Date:** 2026-10-07 · **Status:** decided

`MetricsPublisher` posts one event per request from a single background thread, counts any non-2xx
as a failure, and moves on. Nothing retries. So the status code is not a place to report a problem
with an event: a 422 on one unrecognised field makes the publisher drop that event and every later
one of the same shape.

**Decision.** `POST /api/metrics` accepts any object with a `kind`, allows unknown fields
(`extra="allow"`), accepts unknown `kind` values, and accepts events for jobs the backend does not
track — the experiment harness creates jobs straight against Jenkins and the plugin reports on
those too. What was wrong with an event is logged and reported in the response body
(`applied` / `parked` / `ignored`), not in the status.

Returns 202, not 200: the event is recorded, but what it means for a run may depend on a row that
does not exist yet.

**Queue timings are parked, not dropped.** A queue event arrives the instant an item is queued,
while `job_runs` cannot have a row until Jenkins has assigned a build number and `RunTracker` has
polled. An unmatched timing is held in memory, bounded at 2000 entries with a 30-minute TTL, and
attached when the run appears. Without that, `queue_entered_at` would essentially never be filled
from metrics, which is the one thing 4.4.6 says this endpoint is for.

### D-026 The plugin publishes metrics over HTTP/1.1, not Java's HTTP/2 default
**Date:** 2026-10-07 · **Status:** decided, fixes a defect

`HttpClient.newBuilder()` defaults to `HTTP_2`. For a cleartext `http://` URL, Java negotiates that
with an HTTP/1.1 `Upgrade: h2c` request. The backend is served by uvicorn, which does not implement
that upgrade: it logged "Unsupported upgrade request", then "Invalid HTTP request received", then
returned **422 for every single metric event**.

The metrics pipeline therefore published nothing at all. It had never been exercised, because until
T3.6 there was no backend to post to, and `metricsBackendUrl` defaults to empty (D-006) so the
publisher returned early. The only symptom was `failedMetricCount` rising, and nothing watched it.

**Decision.** `MetricsPublisher.newHttpClient()` pins `HTTP_1_1`. The fix belongs in the plugin:
uvicorn has no h2c support, and putting a proxy in front of the backend to translate a protocol
nobody needs would be a much larger change for no benefit.

`MetricsPublisherHttpVersionTest` asserts the pin, and also asserts that Java's default really is
HTTP/2 — so a later reader cannot delete the `.version()` call believing it restates a default.

Verified end to end on 2026-10-07: one triggered build produced `QUEUE_ENTERED`, `QUEUE_LEFT`,
`BUILD_STARTED` and `BUILD_COMPLETED`, with `publishedMetricCount` 4, `failedMetricCount` 0,
`droppedMetricCount` 0, and four 202s in the backend log.

### D-025 The catalog has exactly one loader, and it validates
**Date:** 2026-09-29 · **Status:** decided

`app/db/seed.py` parsed `catalog/services.yaml` itself while `app/services/catalog.py` was being
written to parse it again. Two loaders meant the seed could accept a document the API would reject,
so a catalog with a shell metacharacter in a command would reach the `services` table and fail at
request time instead of at seed time.

**Decision.** `app.services.catalog` is the only parser. It validates against
`catalog/services.schema.json` on every load and `seed.py` calls it. `verify.py` fails if any other
module under `backend/app/` calls `yaml.safe_load`, so the second loader cannot come back quietly.

The catalog is reloaded when its mtime changes rather than on restart, because adding a service
mid-demo should not need a container restart. A reload that fails validation keeps the last good
copy and logs loudly: a typo in the catalog must not take the API down.

### D-024 `GitClient` resolves refs with `ls-remote` and never clones
**Date:** 2026-09-29 · **Status:** decided

4.5.3 needs to know that a branch exists and what commit it points at. A clone would answer that
too, at the cost of disk, latency and a cleanup path, for information one network round trip
already provides.

**Consequence, accepted.** `ls-remote` reports ref tips, not history, so `commit_exists` can
confirm a commit that *is* a tip and cannot confirm one further back. That is enough for validation
before a job is generated; if a checkout later cannot find the commit, Jenkins fails the build
honestly rather than the backend guessing.

Refs are cached for 60 seconds per repository, with one lock per repository so a burst of
validations makes one call. Short deliberately: the point of resolving a branch is to catch a name
that does not exist, and a long cache would keep accepting a branch after it was deleted.

### D-023 Git refs are validated against a pattern, not only passed as arguments
**Date:** 2026-09-29 · **Status:** decided

Branch and commit values reach `GitClient` from a chat message by way of an LLM. The subprocess is
invoked with an argument list and `shell=False`, which is necessary and **not sufficient**: `git`
reads a leading `-` as an option, and `--upload-pack=<command>` makes `ls-remote` execute that
command. That is remote code execution through an argument no shell ever sees.

**Decision.** `REF_PATTERN` requires a ref to start with an alphanumeric, which makes an
option-shaped ref unrepresentable, and the check runs before the call so a hostile ref costs no
round trip either. `ALLOWED_URL` restricts transports to `https://` and `git@`, because `ext::`
executes its argument by design and a local path can point at a repository carrying hooks. That
matters because a repo URL may arrive from the `services` table rather than the validated catalog.
`verify.py` exercises the pattern against option-shaped refs directly.

**Related bug, fixed here.** The subprocess first ran with a minimal environment (`PATH` only),
which looked safer and was not: dropping `SystemRoot` breaks name resolution on Windows and every
fetch failed with `getaddrinfo() thread failed to start`, which reads like a network outage rather
than a missing variable. `scripts/validate_catalog.py` had the identical bug. The environment is
now inherited with the credential-prompt suppressors added, and a test asserts nothing is dropped.

### D-022 A refused sign-in commits its audit entry before raising
**Date:** 2026-09-29 · **Status:** decided

`get_db` commits on success and rolls back on any exception, so that a request failing halfway
leaves nothing behind. A policy denial is an exception, which meant every `auth.login.failed` and
`auth.login.denied` row was added to the session and then rolled back with the refusal — the audit
trail recorded successful sign-ins and nothing else. Part 4.4.3 asks for an entry on every policy
denial, so this was a real defect, found by `test_login_records_success_and_failure_in_the_audit_log`.

**Decision.** `app.services.auth._audit` takes `durable=True` at the three denial sites and commits
the entry immediately. Committing mid-request is safe here precisely because a refused sign-in has
written nothing else: there is no half-finished work for the commit to make permanent.

The alternative — moving auditing into the exception handler — was rejected because the session is
already closed by the time a handler runs, so the handler would need a second one, and the entry
would then be written outside the request's own transaction in every case rather than only in the
cases where that is what is wanted.

### D-021 Refresh-token revocation is held in memory
**Date:** 2026-09-29 · **Status:** decided

Part 4.4.3 lists fourteen tables and none of them holds sessions or tokens, so signing out has no
specified place to record that a refresh token is dead. `RevokedTokens` keeps the `jti` values in
process memory until the token would expire anyway.

**Consequences, both accepted.** A backend restart forgets the list, so a refresh token revoked
before the restart works again after it; and with more than one backend instance a sign-out on one
would not be seen by the others. The project runs a single backend container.

Access tokens are deliberately *not* checked against the list. Doing so would add a lookup to every
single request in order to shorten a fifteen-minute window. What sign-out has to stop is a refresh
token being replayed for seven days, and that is what this stops. Adding the table instead is the
right fix if the deployment ever grows a second instance.

### D-020 Rate limiting is in-process rather than Redis-backed
**Date:** 2026-09-29 · **Status:** decided

Part 4.4.4 requires rate limits on the auth endpoints but names no store. `app.core.ratelimit` uses
token buckets in process memory.

**Why a token bucket, not a fixed window.** A fixed window lets a caller spend its whole allowance
at the end of one window and again at the start of the next, so "5 per minute" permits 10 attempts
in two seconds across the boundary. On a login endpoint that is most of the protection gone.

**Why in-process.** The stack runs one backend container, and the report's Appendix E does not list
Redis among the version 2 dependencies. With more than one instance each would keep its own buckets
and the effective limit would multiply by the instance count — the same caveat as D-021, with the
same fix.

---

## Phase 1

### D-018 The frontend service sits behind a Compose profile until Phase 6
**Date:** 2026-09-29 · **Status:** closed 2026-10-18: `frontend/Dockerfile` exists and the profile is gone (D-065)

`BUILD_PROMPT.md` 4.2.3 lists `frontend` (5173) among the default Compose services. Phase 6 has not
run, so `frontend/Dockerfile` does not exist, and a default service with a missing build context
makes `docker compose up -d` fail outright rather than starting the nine services that are ready.

**Decision.** `frontend` carries `profiles: ["frontend"]`. `docker compose up -d` brings up the
default stack today; `docker compose --profile frontend up -d` includes it once Phase 6 builds the
image, at which point the profile line is deleted and the service becomes a default again.

The alternative, leaving it as a default and telling people to ignore the error, trains everyone to
ignore Compose errors, which is the last habit this project needs.

### D-019 JCasC sets only the optimizer's non-floating-point fields
**Date:** 2026-09-29 · **Status:** superseded 2026-10-18 by D-017's resolution: the files now set all
seven floating-point fields, quoted

The three JCasC files set `optimizerEnabled`, `agingIntervalMinutes`, `estimatorK`,
`historyWindow`, `rescoreIntervalSeconds`, `metricsEnabled`, `metricsBackendUrl` and
`metricsToken`, and deliberately omit the seven floating-point fields.

**Why.** D-017: on `configuration-as-code:2130`, importing a YAML file silently drops this
configuration's `double` fields. Writing `weightUrgency: 0.5` into `dev.yaml` would look correct,
be discarded on import, and leave the value at its code default — a configuration file that lies
about the running system. Omitting the field and documenting the intended value in a comment is
honest about what the file actually controls.

**Why it is safe here.** The code defaults *are* the report's Appendix D values, so all three
controllers run the published formula. The intended values are listed as a comment in `dev.yaml` so
the configuration remains reviewable.

**What it does not cover.** The aging-ablation arm of the Part 4.8.2 matrix needs
`agingBonusPerInterval` and `agingCap` set to non-default values. That arm cannot be configured from
JCasC until D-017 is resolved, and is tracked under Needs human.

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
**Date:** 2026-09-29 · **Status:** resolved 2026-10-18: root cause found, values quoted · **Evidence:** `ConfigAsCodeIT`

**Resolution, 2026-10-18.** The root cause is JCasC's YAML loader, not the import.
- **Where:** `io.jenkins.plugins.casc.yaml.ModelConstructor` registers scalar constructors for
  YAML's `bool`, `int` and `str` tags only. An unquoted `0.6` carries the `float` tag, falls through
  to SnakeYAML's default constructor, comes back as a `Double` instead of a model node, and is
  left out of the parsed document. So the setter is never called, no "unknown attribute" error is
  raised, and the default stays.
- **How it was found:** a debugging test in a JenkinsRule.
  - Its setter traces showed JCasC calling `setAgingIntervalMinutes`, never `setWeightUrgency`.
  - JCasC's FINE log showed no attempt to set it.
  - The attribute's own setter and the `double` converter both worked when called directly.
  - `YamlUtils.loadFrom` returned a mapping without the key.
- **The fix:** quote floating-point values (`weightUrgency: "0.6"`). A quoted value is a
  string, which JCasC converts to `double` like any other scalar.
  - All three `jenkins/casc/` files now set all seven fields, quoted, at Appendix D's values.
  - A Phase 1 `verify.py` check refuses an unquoted or missing one, and any value that is not
    the report's.
  - The aging-ablation arm can now be driven from YAML.
- **Tests (`ConfigAsCodeIT`, 9 passed):**
  - quoted values apply;
  - unquoted ones are dropped (this pins JCasC's behaviour, so it fails if a later JCasC reads
    them);
  - an exported file imports again with its floating-point values.
- **Correction:** the investigation below said quoted and unquoted forms behave identically.
  That was wrong, very likely another stale-class run of the kind described below.

The original record follows.

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
