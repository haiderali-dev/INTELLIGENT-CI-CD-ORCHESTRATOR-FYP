# Decisions

Every decision taken while building, and every conflict found between `BUILD_PROMPT.md`, the report
in `docs/report/` and `legacy/m2-poc/`. Newest first within each phase.

Sources of truth, in priority order (`BUILD_PROMPT.md` 1.2): this file's parent specification
`BUILD_PROMPT.md`, then the report, then the legacy code. When sources conflict the higher one wins,
the conflict is recorded here, and any needed report change goes in `docs/report-updates.md`.

---

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
**Date:** 2026-09-29 · **Status:** decided

`BUILD_PROMPT.md` 4.2.3 lists `frontend` (5173) among the default Compose services. Phase 6 has not
run, so `frontend/Dockerfile` does not exist, and a default service with a missing build context
makes `docker compose up -d` fail outright rather than starting the nine services that are ready.

**Decision.** `frontend` carries `profiles: ["frontend"]`. `docker compose up -d` brings up the
default stack today; `docker compose --profile frontend up -d` includes it once Phase 6 builds the
image, at which point the profile line is deleted and the service becomes a default again.

The alternative, leaving it as a default and telling people to ignore the error, trains everyone to
ignore Compose errors, which is the last habit this project needs.

### D-019 JCasC sets only the optimizer's non-floating-point fields
**Date:** 2026-09-29 · **Status:** decided, consequence of D-017

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
