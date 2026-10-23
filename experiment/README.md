# Experiment v2

The harness that compares the optimizer with its observe-only control on real Jenkins controllers
(BUILD_PROMPT Part 4.8). It uses only the Jenkins REST API and the plugin's `/dynamic-queue`
endpoints: no Groovy and no script console (rule 1.5), which is how Milestone 2's harness worked
and why this one replaced it.

```
python -m experiment setup  --controller plugin --workload freestyle-30 [--recreate]
python -m experiment warmup --controller plugin --workload freestyle-30 --passes 3
python -m experiment run    --controller plugin --workload freestyle-30 --executors 1 --group main --repetition 1
python -m experiment analyze experiment/results/<run folder>
python -m experiment report [--out <folder>]
python -m experiment smoke    # T7.6: freestyle-6, 1 executor, 1 repetition, on both controllers
```

It needs Python 3.12 or later and nothing else. The bot's password and, for `--recreate` only,
the admin's are read from the environment (`JENKINS_BOT_PASSWORD`, `JENKINS_ADMIN_PASSWORD`) or
else from `.env`; they are never printed.

## The controllers and the arms

`docker compose --profile experiment up -d` starts two controllers from the same image, with one
agent each and separate Jenkins homes, so neither sees the other's history:

| Controller | URL | Configuration | Arm |
| --- | --- | --- | --- |
| `baseline` | http://127.0.0.1:8085 | `jenkins/casc/experiment-baseline.yaml` | observe-only: the plugin installed, ordering nothing |
| `plugin` | http://127.0.0.1:8086 | `jenkins/casc/experiment-plugin.yaml` | optimized: the report's algorithm |

The executor count is set when the controllers start: `AGENT_EXECUTORS=3 docker compose --profile
experiment up -d --force-recreate jenkins-baseline jenkins-plugin`. A run checks it, with the arm,
before it starts, and refuses if either is not what was asked for.

Two arms of the matrix need a controller prepared by hand, and a run detects both from the
configuration in force:

- **aging-off** (the aging ablation): the `plugin` controller with `agingBonusPerInterval` and
  `agingCap` set to `"0.0"` in its configuration file, quoted (D-017). Restore them afterwards.
- **stock** (the sanity run): Jenkins without the plugin. The Compose image always installs it,
  so this arm needs a controller built without it, which does not exist yet.

## The matrix (Part 4.8.2)

| Group | Workloads | Executors | History | Order | Repetitions | Arms |
| --- | --- | --- | --- | --- | --- | --- |
| `main` | freestyle-30, pipeline-30, mixed-30 | 1 and 3 | warm | LOW, MEDIUM, HIGH | 3 | observe-only, optimized |
| `cold-start` | freestyle-30 | 1 | fresh | LOW, MEDIUM, HIGH | 3 | both |
| `random-order` | mixed-30 | 3 | warm | seeds 1 and 2 | 1 per seed | both |
| `aging-ablation` | freestyle-30 | 1 | warm | LOW, MEDIUM, HIGH | 3 | optimized, aging-off |
| `sanity` | freestyle-30 | 1 | warm | LOW, MEDIUM, HIGH | 1 | stock |

For each controller and workload: `setup`, then `warmup --passes 3`, then one `run` per
repetition. The history must be warm, except in `cold-start`, where `setup --recreate` comes
first. That deletes every experiment job on the controller, of every workload, with its history,
because the estimator learns from every job on a controller. Pass `--history fresh` to that run,
and `--history warm` to the others, so a mistake stops the run instead of recording it.

## Results

Each run writes `results/<UTC time>-<group>-<workload>-<arm>-<N>x-r<repetition>/` (not tracked):

- `run.json`: what was run and on what (plugin version and build commit, Jenkins version, executor
  count, the workload itself and its digest, the configuration in force, the order queued);
- `events.jsonl`, `builds.json` and `health.jsonl`: the raw data;
- `analysis.json`: the KPIs, which `analyze` can recompute from the three files.

`results/latest.json` (tracked) names the latest analysed run and holds its KPIs. `report` writes
`table_12_1.md`, `runs.csv` and the charts to `results/report/` by default. Repetitions are
averaged with their standard deviation, and n is printed beside them: three repetitions is a small
sample. Milestone 2's five runs appear in a section of their own, recomputed from its result files,
and never in a v2 figure.
