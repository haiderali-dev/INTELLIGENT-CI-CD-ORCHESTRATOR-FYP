# The targeted re-run after DF-48's fix, 2026-10-24

Ten measured runs on experiment controllers running the fixed plugin (build `c01e744`, D-080), from
13:36 to 14:11 (+05:00), on mains power. The user approved them on 2026-10-24 as the check of the
fix on real Jenkins. They do not repeat the matrix, whose evidence in `../matrix-2026-10-24/` stays
as recorded.

## What it ran

- **pipeline-30 on 3 executors:** 3 repetitions, both arms, group `main-rerun`.
- **Random order:** mixed-30 on 3 executors, seeds 1 and 2, both arms, group
  `random-order-rerun`.

The jobs were new, because the matrix's cold start had deleted the earlier ones. They were set up
and warmed with three passes, then measured one run at a time, each condition's two arms back to
back. `rerun_campaign.py` ran it on `matrix_campaign.py`'s machinery, and both are kept here.

## What is here

- **`runs/`:** each run's folder as the harness wrote it. The raw files are byte for byte
  (`.gitattributes`), and `SHA256SUMS` covers them.
- **`report/`:** `python -m experiment report` over these ten runs.
- **`campaign-log.txt` and `progress.jsonl`:** every step and each run's headline figures.

**The analysis has DF-47's fix.** The harness ran from PR #16's branch, `phase-7-matrix` at
`7d9c090`, whose `kpis.py` judges a Pipeline's violation by when its work starts (D-079). When this
was written `main` had not got that fix yet. It has since: PR #16 merged as `535330f` on
2026-10-24, so `main`'s `kpis.py` reproduces these counts.

## Result

| Optimized arm, 3 executors | Matrix, plugin `cd6b1e3` | Re-run, plugin `c01e744` |
| --- | --- | --- |
| pipeline-30, r1, r2, r3 | 1, 1, 1 | **0, 0, 0** |
| Random order, seed 1 | 5 | 2 |
| Random order, seed 2 | 2 | 1 |

- **The fixed edge.** In each pipeline-30 run, `release-notes-generator` is still queued a moment
  before `smoke-test-production`, and its run still starts at once. Its node block now waits until
  the upstream has finished.
  - **In all three runs:** it took an executor at 91.2 to 91.3 s, 2.8 to 2.9 s after the upstream
    ended at 88.4 to 88.5 s.
  - **In the matrix:** it ran at 15.5 to 17 s.

  Re-analysing these runs' raw files with DF-47's `kpis.py` reproduces their KPIs, 10 of 10.
- **The three left are the limit D-080 records.** In random order, a freestyle downstream took an
  idle executor 132 to 1,040 ms before its upstream had been queued at all, on the same three edges
  as in the matrix:
  - `build-notification-service` to `test-notification-service`;
  - `test-catalog-service` to `deploy-catalog-service`;
  - `test-payment-service` to `deploy-payment-service`.
- **Observe-only** counted as in the matrix: 3, 3 and 3 on pipeline-30, and 14 and 10 in random
  order. That arm has no gate.
- **Scheduling efficiency on pipeline-30, 3 executors** (the matrix's figures in brackets):

  | Measure | Re-run | Matrix |
  | --- | --- | --- |
  | Mean wait | +9.6% | +9.7% |
  | HIGH mean wait | +24.2% | +17.0% |
  | Makespan | -3.8% | -3.9% |

  Holding the downstream cost no makespan. These are three repetitions, and random order has one
  run per seed.

## Conditions

- **Power:** mains throughout. Windows logged no power-source change and no sleep. Modern Standby
  came and went, and each pipeline-30 run still took 125 to 132 s.
- **The rest of the stack:** the default stack and the stock controller were stopped for the runs,
  and started again after.
- **Afterwards:** the experiment controllers were returned to 1 executor.

To recompute, with DF-47's `kpis.py`:

```
python -m experiment analyze docs/experiment/gate-fix-rerun-2026-10-24/runs/*
python -m experiment report --results docs/experiment/gate-fix-rerun-2026-10-24/runs --out <folder>
```
