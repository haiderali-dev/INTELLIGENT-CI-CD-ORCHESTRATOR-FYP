# Phase 8 completion audit

Date: 2026-10-25. This is a continuation audit by the implementation agent, not an independent
security review. Scope: BUILD_PROMPT.md Part 4.9, Part 4.10 and the final Phase 8 acceptance.

| Requirement | Evidence | Status |
| --- | --- | --- |
| Frozen 250-item dataset, 100 development / 150 test | `eval/datasets/eval-v1.*`, archived dataset and checksum | Complete, machine-labelled under D-081; human review remains open |
| Rules, GPT-OSS-120B, GPT-OSS-20B, another available model | Archived 150-item test runs, including Qwen | Complete; two GPT-OSS-20B responses rejected |
| Four configurations on a 75-item subset | Full, no enums, no examples, no repair | Complete; one rejected parse in each of no enums and no examples |
| Plan validity before and after repair | 74 test items per model, 20 distinct requests per model | Complete; GPT-OSS-20B needed repair on nine items |
| Twenty commands through live Jenkins | `runs/eval-v1-end-to-end__groq-openai-gpt-oss-120b/` | Complete; 18 successful, with both build failures preserved |
| Generated report and Analytics data | Archived JSON/markdown, response-schema validation, refreshed frontend fixture | Complete |
| Generated report chapter tables | `scripts/report/chapter_12.py --check` | 12 tables current |
| Appendix C, versions and demo tooling | T8.3–T8.5 evidence in PROGRESS.md | Built; cumulative gate rechecks them |
| Final cumulative acceptance | Archived gate run 14: all 108 checks passed, exit 0 | Complete |

The dataset is authored and labelled by Claude Code, with no person's review. Every result
retains that provenance. Accuracy and refusal percentages exclude parser errors, which are
shown separately. Repeated gold intents share cached plans, so item counts are not independent
model samples. Chapter 12 explains these limits and the incomplete additional development runs.

The audit fixed these issues, with regression coverage:

- Campaign failures were incorrectly counted as finished on resume.
- Worker exceptions and unfinished queues could leave a successful campaign exit status.
- A missing attempt log could cause a later log to be overwritten.
- The campaign hardcoded this Windows checkout and called Windows APIs on every platform.
- Report generation alone could pass the acceptance gate with incomplete measurements.
- Generated chapter tables could lose incomplete markers.
- Ablation errors were absent from the Analytics table, and accuracy denominators were unclear.
- Git line-ending conversion would invalidate the new archive's byte checksums; its hashed
  evidence now follows the existing experiment/test evidence convention in `.gitattributes`.
- Archived reports previously read the working dataset card; they now use the frozen card and
  reject a mismatched checksum, so later label reviews cannot rewrite historical provenance.

Focused validation: 111 evaluation/campaign tests and nine Analytics page tests passed.
Backend/evaluation lint and formatting passed (152 files); strict evaluation typing passed
for eight source files. All 12 generated-table freshness checks passed. The full gate is the
final validation record.

Gate run 12 completed 104 of 108 checks. The outdated plugin artifact and two formatter findings
are corrected; all three optimizer controllers now run the verified plugin. The fourth failure
was demo step 1: agent-2 could not resolve GitHub even after the configured SCM retries.
`docs/testing/evidence/gate-run-12-phase-8-working-tree.log`, `gate-run-12-demo-replay.log` and
`gate-run-12-demo-failure.txt` preserve the failures. Both agents subsequently fetched the sample
repository successfully. Run 13 repeats the complete gate on mains power; no test is skipped or
weakened to work around the infrastructure failure.

Run 13 completed 106 of 108 checks (exit 1). It exposed a real transaction race (D-083):
generation returned 201 before its message was committed, and the following conversation read
missed it, leaving the preview empty. Function-scoped session dependencies fix the cause across
all endpoints. Three new regressions pass at the ASGI response-start boundary and across the
registered dependency graph; the complete offline backend suite passes 1,805 tests. The original
browser trace, with authentication values redacted, is retained under
`docs/testing/evidence/raw/gate-run-13-preview/`.

The other run-13 failure was again agent DNS: demo step 4's deploy checkout could not resolve
GitHub after the configured retries. Its exact console and replay output are archived separately
from the evaluation's two measured lint failures.

After D-083's fix, the affected live Pipeline browser flow passed in 17.4 seconds; the complete
demo then passed both tests in 347.07 seconds, with its log archived as
`docs/testing/evidence/demo-replay-after-transaction-fix.log`. Gate run 14 completed the final
cumulative rerun on mains power, with Windows kept awake: all 108 checks passed, exit 0,
in 42m 27s (2026-10-25, 22:31:56 to 23:14:23 PKT). The unmodified UTF-8 output is archived as
`docs/testing/evidence/gate-run-14-phase-8-working-tree.log`; start/end timestamps and exit status
are in `docs/testing/evidence/gate-run-14-result.json`. This includes the backend quality checks,
299 frontend tests, 12 fake-provider browser flows, three real-stack browser flows, 111 evaluation
regressions, all experiment-controller checks and both demo replay tests.

The live failures were both payment-service lint checks, after successful understanding,
planning and generation. Jenkins' archived consoles identify formatting differences in
`tests/test_integration.py` and `tests/test_unit.py` in the sample repository. The 18/20 result
is retained; changing that separate repository would require another measured run with its
revision recorded.

Human work still open: gold-label review, usability study, team demo rehearsal, and applying
the report-update checklist to the report's missing Word source. Additional GPT-OSS-120B and
Qwen development runs are quota-deferred; their partial figures do not enter the test comparison.
