# Phase 5 security review

**Date:** 2026-10-13 · **Branch:** `phase-5-assistants` · **Scope:** everything Phase 5 added on top
of `main` (357f1aa). That covers:
- generation: spec, revision rule, planner, templates, validators;
- conversations and the assistants API;
- generate, regenerate, explain and approve;
- chains: the lock, tracking, cancel, rerun and the run card;
- T5.9 Explain failure;
- the wiring and the Phase 5 migration.

## Method, and its limit

BUILD_PROMPT.md Part 1 asks for an independent review by a subagent at the end of Phase 5. One
was started with the checklist below and read-only access. It stopped before reporting, on an
account usage limit (HTTP 429, "session limit"). Starting another would have hit the same limit.
The review was therefore done in the main session, by the same agent that wrote the code.

**It is not independent.** Re-running an independent review once the limit resets is recommended
(residual risk 1).

Every claim below was checked by reading the code path end to end or by running something. Each
fix has a regression test that fails without it.

The checklist covered:
- authentication and authorization;
- input validation;
- the generated XML and Jenkinsfiles;
- the LLM boundary;
- secrets;
- approval idempotency and concurrency;
- cancel and rerun;
- whether a failing test can ever lead to a deploy;
- error handling;
- denial of service.

## Findings and fixes

| # | Severity | Finding | Fix | Regression test |
| --- | --- | --- | --- | --- |
| 1 | Medium | T5.9 read a build's **whole log** into memory, up to five times while waiting for Jenkins to close it. The log is written by whoever pushed the commit, so one that prints without limit could exhaust the backend through an authenticated endpoint. | `JenkinsClient.console_tail` streams the log and keeps its end: at most 2 MB in memory, starting on a whole line, with the dropped line count, so line numbers still match Jenkins. (7149e51) | `test_jenkins_console.py`: keep_tail cases, a 2.6 MB streamed log, 404, retry on 503. `test_failures_api.py`: a 7 MB log explained with true line numbers. |
| 1a | — | Found by finding 1's tests: `keep_tail` dropped one whole line too many when the cut fell exactly on a line boundary. | Only a cut *inside* a line drops the rest of that line. | `test_keep_tail_keeps_whole_lines_and_counts_what_it_dropped` |
| 2 | Low | Rerun recognised a test job by its **whole name** (`"-test-" in name`). A service named like `load-test-service` would make its *deploy* job count as a test job, so "rerun the failed tests" would re-run a deploy. No service in today's catalog is named like that. | The name is read after the service's own prefix, and the owner comes from the run's chain. (7149e51) | `test_a_test_job_is_recognised_after_its_service_s_name` (11 cases) |
| 3 | Low | Redaction missed **credentials on a command line**: `curl -u user:secret`, `--user=user:secret`, `--password value`, the commonest way a build prints one. | Two linear-time patterns. A `user:secret` pair is required after `-u`, so `git push -u origin` and `sort -u` are untouched. (7149e51) | `test_secret_shaped_values_are_masked`, `test_ordinary_log_lines_are_left_alone` |
| 4 | Low | Two **policy denials were not audited** (4.4.3): an approval refused by the chain lock, which the request's rollback discarded, and a refused cancel. | Both are written and committed before the refusal (the D-022 pattern). (b22ece2, from the T5.1 to T5.8 audit) | `test_an_approval_refused_by_the_lock_is_audited`, `test_a_refused_cancel_is_audited` |
| 5 | Info | A network fault on the agent (DNS dropped `github.com`, captured live) was reported as a checkout error. Its advice, "check the branch was pushed", sent the developer the wrong way. | Network and DNS failures are now infrastructure, checked before the checkout rule. (7149e51) | `payment-service-test-unit-dns.log` in the analysis table; `test_a_network_fault_on_the_agent_points_at_the_agent_not_the_branch` |
| 6 | Info | The T5.9 fixtures were **never committed**, because `*.log` is ignored. The tests passed locally and failed CI on a clean checkout. | A narrow re-include rule. No other ignored file under `backend/`, `scripts/`, `catalog/` or `jenkins/` is outside a cache or virtualenv. (5f96bda) | CI on a clean checkout |

## Checked and found sound

**Authentication and authorization**
- Every Phase 5 route requires a signed-in user and carries a rate limit. Model-calling routes
  share the assistants' 20 a minute.
- Conversations, commands and pipelines are owner-scoped: another user's id is a 404, which does
  not disclose that it exists.
- Chains and runs are readable by any signed-in user, as runs already were in Phase 3.
- Cancelling needs the chain's starter, or DevOps and above (D-047). Approving needs the
  pipeline's owner.

**Input validation**
- Messages are capped at 4,000 characters, and edited YAML at 20,000.
- A YAML alias bomb (387 million references) is rejected in under 10 ms, with a message of about
  1 KB.
- Service, assistant and priority are locked on regenerate. `repo` and `agent_label` are pinned to
  the catalog.
- Intent edits use `extra="forbid"`, the Idempotency-Key is bounded, and job names are validated
  before any URL is built.

**Generated jobs**
- The XML templates autoescape.
- Every value in the Jenkinsfile passes through `groovy_string`, which escapes `\` and `'` and
  refuses line breaks.
- Shell commands come only from the catalog.
- The validator checks for metacharacters and runs the declarative linter.
- Only a `VALIDATED` plan can be approved.
- "No production anywhere" is enforced three times: by the policy, the validator, and T5.9's
  output check.

**The LLM boundary**
- Model output never becomes a command, a job name, a Jenkins parameter or an action.
- Planner output is checked against patterns and the catalog.
- T5.9's output is display-only, and it is checked:
  - every quote must be in the excerpt;
  - a "no cause" answer that contradicts the code's finding is refused;
  - a summary mentioning production is dropped, as is a suggestion that looks like a command.
- The log is fenced as data, and the fence is defused inside the excerpt.
- A test in which an injected log line asks for a production deploy gets the code's explanation.

**Secrets**
- Redaction runs before any use of a log.
- The configured secrets are masked by value, along with token formats, URL credentials, auth
  headers, secret assignments, private keys and emails.
- It is line-preserving and linear-time. A hostile 1 MB input is redacted in well under the 5 s
  guard.
- No Phase 5 log call records message text, prompts, logs, configs or tokens.
- Fixtures store only the model's answer and a prompt hash.

**Approval and concurrency**
- The row is locked, and a key reused for a different plan is refused.
- The approval and the chain lock are committed before Jenkins is touched.
- The partial unique index (one RUNNING chain per service, checked on the migrated stack database)
  settles races.
- A Jenkins failure aborts the chain, releasing the lock, and undoes the approval.

**A failing test never deploys**
- The backend starts builds in exactly two places: approval starts a chain's *first* job, and
  rerun starts a failed *test* job.
- Freestyle downstream triggers fire only on SUCCESS (ordinal 0), so UNSTABLE, FAILURE and ABORTED
  all stop the chain.
- The Jenkinsfile has no `catchError`, `unstable`, `junit` or `try` that could let a failed stage
  continue.
- Shown live in the end-to-end suite: the freestyle deploy job never started, and the Pipeline's
  deploy stage was skipped.

**Error handling**
- Refusals are audited and committed before raising.
- Jenkins being unavailable is a 503, or a 409 for log reads, telling the user to retry.
- An unexpected error is a generic 500 (Phase 3's handler).

**Denial of service**
- Every model-calling endpoint is rate limited, and page sizes are capped (chains at 200).
- Regexes are linear-time.
- Log reads are bounded (finding 1).

## Residual risks

1. **This review is not independent** (see Method). Re-run it with a reviewer that did not write
   the code.
2. **Phase 3's `GET /api/runs/{id}/log`** still reads from `start` to the end before cutting its
   64 KB window. The risk predates Phase 5. Reading with `console_tail`'s streaming approach,
   stopping after the window, would bound it.
3. **Cancel racing a passing job.** If an upstream job succeeds in the same instant a cancel
   sweeps the queue, its downstream job can be queued after the sweep. The chain is already
   ABORTED and stops tracking it. This is a cancel race, not a failed-test deploy.
4. **Rerun inherits priority.** Re-running another user's HIGH test job runs it at HIGH, because
   priority lives in the job's config. That sidesteps the per-user HIGH quota, but only for
   re-runs of an already-justified job.
5. **Database failure after a trigger.** If the database fails after Jenkins accepted a trigger,
   the chain stays RUNNING, untracked, until its 30-minute lock expires (4.6.4).
6. **Redaction is pattern-based.** An unknown secret format with no recognisable name around it is
   not masked. The configured secrets are always masked, by value.
7. **Untrusted text for the frontend.** Model output and log lines are untrusted. Phase 6 must
   render them as text, never as HTML (React's default; no `dangerouslySetInnerHTML`).
8. **Open logs.** Anyone signed in can read any run's log and its explanation, as in Phase 3.
   Jenkins's own UI shows the same logs to its users.
9. **Agent DNS** (environment, not code). Docker Desktop's DNS drops lookups from the agents now
   and then (4 of 5 resolved in one probe), so a build can fail at checkout. T5.9 reports these
   as infrastructure, and the T5.9 integration test re-runs such a build. The end-to-end tests do
   not retry, so a run that meets one fails and must be repeated.
