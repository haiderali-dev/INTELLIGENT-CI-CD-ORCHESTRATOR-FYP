# Raw test evidence

The files the test runs wrote, unchanged. Chapter 8's tables, Annexure A and the register of
every test in Annexure B were built from them by the scripts in `scripts/report/`.

They are stored byte for byte (see `.gitattributes`), and `SHA256SUMS` lists the hash of every
file the runs wrote, so a checkout can be checked against it. From this folder:
`sha256sum -c SHA256SUMS`.

| Folder | What it holds | Written by | Commit |
| --- | --- | --- | --- |
| `campaign-31eb935/` | The evidence campaign: every suite run once, on 22 October 2026 from 05:31 to 06:11 UTC | `python scripts/test_campaign.py` | `31eb935` |
| `load-and-recovery-4f1bb36/` | The load and recovery tests' reports, from 18:23 to 18:26 UTC that day | `python scripts/system_load_test.py`, `python scripts/recovery_test.py` | the stack as built at `4f1bb36` |
| `gate-run-7-4f1bb36-lighthouse/` | Gate run 7's 16 Lighthouse reports and their summary: every audit scored 100 for accessibility | `python scripts/verify.py --phase 6` | `4f1bb36` |
| `rehearsal-ac8305a-network-outage/` | The rehearsal's backend steps, as first run during a DNS outage: 8 of 32 integration tests, 10 of 13 end-to-end and 4 of 4 live failed; the offline suite passed | `python scripts/test_campaign.py` | `ac8305a` |

Where each is cited: the campaign throughout Chapter 8 and Annexures A and B; the load and recovery
tests in Section 8.7.1 and Annexure A.8; gate run 7 in Annexure A.3, whose log is
`../gate-run-7-4f1bb36.log`; the rehearsal in Annexure A.2, with its errors quoted in
`../rehearsal-network-outage.txt`.

## The campaign's files

- `manifest.json`: each step's command, start time, duration and exit code.
- `logs/`: each step's console output.
- `plugin/surefire-reports/` and `plugin/failsafe-reports/`: JUnit XML of the plugin's unit tests
  and its JenkinsRule tests. `plugin/jacoco.xml` and `plugin/jacoco.csv`: JaCoCo's coverage.
- `plugin-mutation/mutations.xml`: PIT's result for every mutant.
- `plugin-experiments/`: experiments E1 to E3, each CSV with the environment it ran in.
- `backend/`: JUnit XML and coverage.py's JSON for the offline, integration, end-to-end and live
  suites. Coverage accumulates across the four, so the live file covers all of them.
- `frontend/`: JUnit XML of the Vitest tests, browser flows, Lighthouse audits and stack system
  tests, and V8's coverage summary.
- `sample-services/`: JUnit XML of the two sample services' tests.

## Notes

- The campaign's own Lighthouse scores are in `campaign-31eb935/logs/lighthouse.log`. Its HTML
  reports were not kept: the audit writes them to one folder, and gate run 7 overwrote them, which
  is why that run's reports are here.
- Maven's reports record the JVM's system properties and classpath, so they show the development
  machine's paths and Windows user name.
- No file holds a credential. The key- and token-shaped strings in the two copies of
  `backend/backend-offline.xml` are the synthetic test vectors of
  `backend/tests/test_failures_redact.py`, as test names. Each was checked against that file before
  this folder was committed.
- Not kept: the run stopped at `e0c0c69`, and the rest of the rehearsal at `ac8305a`, which the
  campaign superseded (Annexure A.2 says why neither is cited).
