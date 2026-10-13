# Failure logs for the T5.9 tests

Real console logs from jenkins-dev, copied from `docs/evidence/2026-10-11-demo-failing-tests/`.
Two changes were made to each:

- The acceptance script's `acc-fs-*` job names became the names the assistant gives the same jobs
  (D-043).
- Line endings became LF, as Jenkins writes them.

| File | Source | What failed |
| --- | --- | --- |
| `payment-service-test-unit.log` | `demo-payment-service-test-4.log` | pytest: the intentional failing unit test on `demo/failing-tests` |
| `auth-service-test-unit.log` | `demo-auth-service-test-4.log` | Node's test runner: the same, in auth-service |
| `payment-service-build-checkout.log` | `attempt-1-branch-spec-defect/demo-payment-service-build-2.log` | Git found no revision to build (the D-038 branch spec defect) |
| `payment-service-build-not-executable.log` | `attempt-2-scripts-not-executable/demo-payment-service-build-4.log` | `build.sh` was not executable |
| `payment-service-deploy-docker.log` | `attempt-3-deploy-could-not-reach-docker/control-payment-service-deploy-staging-1.log` | The agent was refused the Docker socket |

One more was captured during T5.9's first end-to-end run (2026-10-13), from
`pl-payment-service-build-test-deploy-staging` #1 on `demo/failing-tests`:

| File | What failed |
| --- | --- |
| `payment-service-pipeline-unit-tests.log` | A Pipeline's "Unit tests" stage. The later stages were skipped. |

It is stored as Jenkins served it, apart from line endings: Jenkins sent CRLF, and the file uses
LF like the others. It keeps every Timestamper prefix and every hidden console note
(`ESC[8mha:...ESC[0m`), because those are what the analysis must read through.

One file is constructed rather than captured:

- `auth-service-build-silent.log` has the real header and build step of
  `demo-auth-service-build-8.log`, cut off after `[build] auth-service` with the closing lines of
  a failed step. It stands for a script that fails without printing why, which no captured log
  shows.

The failure prompt's three examples (`app/ai/prompts/failure_v1.md`) are rendered from
`auth-service-test-unit.log`, `payment-service-deploy-docker.log` and `auth-service-build-silent.log`.
`tests/test_failures_explainer.py` checks that each example still matches what the code would send.
