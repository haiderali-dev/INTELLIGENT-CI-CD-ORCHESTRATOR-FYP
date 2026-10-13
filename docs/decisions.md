# Decisions

Every decision taken while building, and every conflict found between `BUILD_PROMPT.md`, the report
in `docs/report/` and `legacy/m2-poc/`. Newest first within each phase.

Sources of truth, in priority order (`BUILD_PROMPT.md` 1.2): this file's parent specification
`BUILD_PROMPT.md`, then the report, then the legacy code. When sources conflict the higher one wins,
the conflict is recorded here, and any needed report change goes in `docs/report-updates.md`.

---

## Phase 6

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
**Date:** 2026-10-13 · **Status:** proposed in `frontend/DESIGN.md`; final when a person approves
that file (Needs human)

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
