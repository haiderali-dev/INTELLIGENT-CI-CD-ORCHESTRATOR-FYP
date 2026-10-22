# Independent security review: Phases 3, 5 and 6

**Date:** 2026-10-18 · **Reviewed:** `main` at `31a725f` · **Fixed on:** `phase-6-hardening`

BUILD_PROMPT.md asks for independent security reviews at the end of Phases 3, 5 and 6. Only the
Phase 5 review had been done, and not independently (`docs/security-review-phase-5.md`). This one
is independent and covers all three phases.

## Method

**The reviewer:** a subagent with no part in writing the code.
- **Access:** its own read-only git worktree. No `.env`, no `.secrets/`, no Docker, no network
  calls.
- **What it read, end to end:** the backend's auth, API, services, generation, failure analysis and
  WebSocket code; the frontend's session, redirect, API client and live-events code; and the Compose
  file, the JCasC files, the controller Dockerfile, CI and the scripts.
- **What it ran:** the existing suites (247 tests), plus four probe tests of its own outside the
  repository. Each confirmed a finding: HIGH approval reuse, the refresh race, text before the fence
  in the failure prompt, and `safeNext`.
- **Rules:** every finding cites a code path it read end to end, or something it ran. Anything not
  confirmed is marked suspected.
- **Not reviewed:** the Java plugin.

**The fixes:** made in the main session.
- Each fix has a regression test, in `backend/tests/test_security_review_fixes.py` unless the table
  says otherwise.
- Every fix with a code change was checked by removing the fix and watching its test fail.

## Findings and fixes

| # | Sev | Finding | Fix | Regression test |
| --- | --- | --- | --- | --- |
| 1 | Medium | One approved HIGH-urgency request could be generated and approved again and again, starting more HIGH chains with no new justification or quota. | `refuse_once_run`: generating, regenerating and approving all refuse a command that already has an approved plan (409 `ALREADY_APPROVED`). A partial unique index allows one APPROVED plan per command; migration `5e0b9c3a7d21`. | three tests: generate again; approve or regenerate a second plan; the database refuses two approved plans |
| 2 | Medium | Jenkins (8087, 50000), the backend (8000) and the experiment controllers were published on every network interface. Agents hold the Docker socket, so a guessed Jenkins password on a shared network could mean root on the host. | Every published port is now `127.0.0.1:…`. The inbound agent port is off (`JENKINS_SLAVE_AGENT_PORT=-1`, not published), since agents use SSH. | `verify.py` Phase 1: "every published port is bound to loopback…" (fails on the old file with all seven exposures) |
| 3 | Low | Refresh-token rotation was check-then-revoke across an `await`, so one token sent three times at once gave three sessions. Reuse was not detected. | `RevokedTokens.claim()` checks and revokes in one locked step. Refresh tokens carry a family id: reusing a spent token, or signing out, ends the whole family. | three at once give 200, 401, 401; replaying a spent token signs out the newer one; sign-out ends the family |
| 4 | Low | Test names, printed by code the commit controls, reached the model's "found by code" facts outside the `<log>` fence, with a raw `</log>`. | Names are passed through `normalise()` (fence defused), and `<`, `>`, backticks and control characters become `?`. The prompt format is unchanged, so the replay fixtures still match. | a TAP name carrying `</log> SYSTEM: …` |
| 5 | Low | `GET /api/runs/{id}/log` read the whole log from `start` into memory, and had no rate limit. | `console_head` streams from the offset and stops after one 64 KB window. The jobs, runs, queue, services, analytics and admin routers carry the general limit. | a 50 MB stream: at most one window plus two chunks is read; a window never ends inside a UTF-8 character |
| 6 | Low | The run log was not redacted; only `/explain` was. Developers have no Jenkins accounts, so this endpoint is their log view. | The window is redacted with the configured secrets, as Explain failure's input is. The next offset counts Jenkins's bytes, not the masked text. | a log printing the Jenkins token |
| 7 | Low | Rate limits were keyed by peer address, so everyone behind the `/api` proxy shared one bucket. Five bad sign-ins by anyone locked out everyone. | Signed-in limits are keyed by the token's user. Sign-in is 5 a minute per address and account, plus 30 a minute per address across accounts (a spray). | one account's failures do not lock out another; the 31st sign-in from one address is refused; signed-in traffic is keyed by user |
| 8 | Low | `safeNext("/.//evil.example")` returned `//evil.example`, a protocol-relative URL. Only the router's own `//` collapsing kept it safe. | A resolved path starting `//` or `/\` goes to the overview. | `frontend/src/auth/next.test.ts`: four vectors |
| 9 | Low | Any `JWT_SECRET`, including `changeme`, was accepted. | Outside tests, under 32 characters or the `.env.example` placeholder is refused. | three weak secrets refused; a strong one accepted |
| 10 | Info | Errors and `/api/health` exposed the Jenkins URL, paths and exception text. `/api/health` is public, reaches Jenkins on every call, and had no limit. | Jenkins's "gave up" error is generic, and the detail goes to the log. Health shows `unreachable (JenkinsError)` and is limited per address. Linter messages are still shown to users: they are the feedback that makes a plan fixable, and they carry no secret. | `test_health.py`: Jenkins down shows the kind of failure, not its text |
| 11 | Info | A WebSocket was never re-checked after its auth frame, so it outlived token expiry and deactivation. | The socket closes with 1008 when its token expires; the frontend already renews its session and reconnects on that. Deactivating a user drops their sockets. | `test_ws.py`: closes at expiry; deactivation drops only that user's sockets, even with a full queue |
| 12 | Info | No Content-Security-Policy. Also, `frontend/Dockerfile` did not exist, though Compose referred to it. | The build adds a CSP meta tag: `script-src 'self'` plus the theme script's hash, `connect-src 'self'`, `object-src 'none'`. `frontend/Dockerfile` and `nginx.conf` now exist; nginx adds `frame-ancestors 'none'`, `nosniff` and `no-referrer`. The frontend is a default Compose service (D-018 closed). | `frontend/e2e/csp.spec.ts`: six pages under the policy, no violation |
| 13 | Info | Update-site signature checks were switched off (`noSignatureCheck=true`). | Removed from the controller image and from Compose. | the finding 2 check also refuses the flag |
| 14 | Info | The plan's streamed explanation passed model output unfiltered, and its input includes user-edited stage names. | `screened()` passes the stream on a sentence at a time. A sentence about production, or shaped like a shell command, is replaced by a notice. A model that fails partway still keeps what it said. | a production sentence split across chunks; a command; the existing "cut short" test |
| 15 | Info | Seeding silently re-enabled a deactivated admin on every stack start. | It re-enables the seed admin only when no other Admin is active (the lockout case it exists for), and writes an audit entry either way. | `test_migrations.py`: stays deactivated while another Admin is active |

Also found and fixed:
- **The Phase 5 review's fix 3 had a gap.** curl's attached `-uuser:secret` form was not redacted.
  The pattern now covers it, and `git push -u origin` and `sort -u` are still left alone.

## The earlier Phase 5 review, checked

- **Six fixes:** all hold (bounded `/explain` read, `keep_tail`, test-job recognition, credential
  redaction, audited refusals, DNS classification), with the curl gap above now closed.
- **Four "checked and sound" claims did not fully hold,** and are covered by findings 1, 4, 5, 6
  and 10.

## Residual risks, accepted for a staging-only university project

- **Agent privileges:** agents hold `docker.sock`. Anyone who can push to a catalog service's
  repository runs code on the host through its scripts (disclosed by design, BUILD_PROMPT 4.10).
- **SSH host keys:** agents use non-verifying host-key checking.
- **In-memory stores:** the revocation list, token families, rate limiter and hub are lost on
  restart and are per instance (D-020, D-021).
- **Logout:** an access token stays valid for up to 15 minutes after it.
- **Visibility:** logs, explanations, chains and run events are visible to every signed-in user.
- **Request bodies (suspected, not measured):** no limit before parsing. nginx now caps bodies at
  1 MB on the Compose path; the dev server does not.
- **Public docs:** `/docs` and `/openapi.json` are public.
- **CI:** actions are pinned by tag, not by SHA.
- **Phase 5 residuals still open:** the cancel race; a database failure after a Jenkins trigger;
  pattern-based redaction missing unknown secret formats; agent DNS.
- **Redaction per window:** a secret split across two 64 KB log windows could pass unmasked in each.
  The configured secrets are short, so this needs a secret sitting exactly on the boundary.
