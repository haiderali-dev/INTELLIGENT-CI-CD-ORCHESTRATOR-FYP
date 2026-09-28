# Progress

Updated: 2026-09-28 · Current phase: 0 · Branch: phase-0-foundation

## Needs human
- [ ] **Install Docker Desktop and start it.** Blocks Phase 1 entirely (T1.1 to T1.10) and every
      acceptance check from Phase 3 onward. Waiting on it: `jenkins-dev`, the reference-config export
      (T1.9), the `.hpi` install (T2.14), and all integration and end-to-end tests.
- [ ] **Put the secrets in `.env`.** Needed: `GROQ_API_KEY`, `JENKINS_ADMIN_PASSWORD`,
      `JENKINS_BOT_PASSWORD`, `JWT_SECRET`, `METRICS_TOKEN`, `POSTGRES_PASSWORD`, `SEED_ADMIN_EMAIL`,
      `SEED_ADMIN_PASSWORD`. Never paste them into the chat. Blocks the live AI path in Phase 4 and
      the whole stack in Phase 1. Fakes and replay fixtures cover everything else meanwhile.
- [ ] **Create the two sample-service GitHub repositories**, push them, create the
      `demo/failing-tests` branch, and put the URLs in `catalog/services.yaml`. Blocks T1.8's
      `git ls-remote` check and the Phase 5 failing-branch acceptance test.
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
- [ ] T0.2 Write `docs/m2-baseline.md`
- [ ] T0.3 Monorepo skeleton, `.gitignore`, `.gitattributes`, `.editorconfig`, `.env.example`, `README.md`
- [ ] T0.4 `.github/workflows/ci.yml` with plugin, backend and frontend jobs, each skipped until its
      folder holds a build file
- [ ] T0.5 `scripts/verify.py` following Appendix D, with the Phase 0 checks
- [ ] T0.6 `docs/decisions.md`, `docs/report-updates.md`, `docs/versions.md`

**Acceptance:** `python scripts/verify.py --phase 0` prints ALL CHECKS PASSED.

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

## Session log
- 2026-09-28 Read BUILD_PROMPT.md in full. Explored `legacy/m2-poc/` (plugin sources, experiment
  harness, result files) and the report PDF (Chapter 6 algorithms, Chapter 12, Appendices B to F).
  Confirmed M2 known problems 1, 2, 3, 6 and 7 directly in the code and data. Found eleven conflicts
  across BUILD_PROMPT.md, the report and the legacy code, including one contradiction internal to
  Part 4.3.2. Verified the current Jenkins LTS against jenkins.io. Wrote PLAN.md, CLAUDE.md and this
  file. Next: finish Phase 0 (T0.2 to T0.6), then the Phase 2 failing-test spike.
