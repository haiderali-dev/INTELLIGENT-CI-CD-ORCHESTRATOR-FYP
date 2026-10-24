# The Part 4.8.2 matrix, run on 2026-10-24

All 53 measured runs of the v2 experiment, run by `matrix_campaign.py` from 03:46 to 08:16
(+05:00), on mains power throughout, at commit `19fc287` on `phase-7-stock-jenkins`.

## What is here

- **`runs/`:** each run's folder as the harness wrote it: `run.json`, `events.jsonl`,
  `builds.json`, `health.jsonl` and `analysis.json`.
  - `analysis.json` is from the second analysis, after DF-47's fix (D-079).
  - The raw files are byte for byte (`.gitattributes`), and `SHA256SUMS` covers them.
- **`report/`:** `python -m experiment report`: `table_12_1.md`, `runs.csv` and the charts. It also
  holds the local smoke runs of 2026-10-22 and 2026-10-23, in their own `smoke` sections, whose raw
  files are not kept here.
- **`campaign-log.txt` and `progress.jsonl`:** every step, when it ran, how long it took, and each
  run's headline figures as they were first analysed. The Pipeline violation counts in them predate
  the fix.
- **`matrix_campaign.py`:** the script that ran the campaign: its order, and the controller changes
  between groups.

## How it ran

1. **Preparation:** the default stack was stopped. Every workload was set up and warmed with three
   passes, the controllers' warm-ups in parallel, since nothing was measured.
2. **The measured runs, one at a time,** each repetition's two arms back to back:
   - the main group on 1 executor (18);
   - the aging ablation (6), with `experiment-plugin.yaml`'s aging values at `"0.0"`, then
     restored and checked against git;
   - the stock sanity run (1);
   - the main group on 3 executors (18);
   - random order (4);
   - cold start last (6), each repetition after `setup --recreate`.
3. **Before each measured run:** the script checked for mains power, and it asked Windows not to
   sleep.
4. **What Windows logged:** no power-source change or sleep; Modern Standby twice, which did not
   pause the runs.

## To recompute

```
python -m experiment analyze docs/experiment/matrix-2026-10-24/runs/*
python -m experiment report --results docs/experiment/matrix-2026-10-24/runs --out <folder>
```

`analyze` overwrites each `analysis.json` and points `latest.json` beside the runs at the last one.

## Findings to carry into Chapter 12

- **Main group, optimized against observe-only:**
  - HIGH's mean wait fell 17 to 34%, and the overall mean wait 1.6 to 9.7%;
  - makespan moved +0.2 to -9.6%, worst for mixed-30 on 3 executors.
- **Aging ablation:** turning aging off changed freestyle-30's mean wait by 0.2%, which is within
  noise, as D-073's simulation predicted.
- **Sanity:** stock Jenkins, at 153.9 s mean wait and 317.9 s makespan, was within 0.5% of
  observe-only's 153.3 s and 316.8 s. So the plugin, installed and not ordering, does not change
  scheduling. Its waits are measured from the harness's trigger times (D-078).
- **Dependency violations, optimized:**
  - 0 everywhere except two cases;
  - pipeline-30 on 3 executors, 1 per run: `smoke-test-production` to `release-notes-generator`, an
    open finding about the plugin's gate (D-079);
  - random order, 5 and 2, where a downstream can be queued before its upstream exists.
- **Small samples:** three repetitions per condition, and one for random order and sanity.
