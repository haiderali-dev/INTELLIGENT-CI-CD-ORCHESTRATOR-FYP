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
python -m experiment smoke --controller stock    # the same on the stock-Jenkins controller
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
| `stock` | http://127.0.0.1:8088 | `jenkins/casc/experiment-stock.yaml` | stock: Jenkins without the plugin (the `stock` profile) |

The executor count is set when the controllers start: `AGENT_EXECUTORS=3 docker compose --profile
experiment up -d --force-recreate jenkins-baseline jenkins-plugin`. A run checks it, with the arm,
before it starts, and refuses if either is not what was asked for.

A run detects the arm from the configuration in force. Two arms of the matrix need a controller
prepared first:

- **aging-off** (the aging ablation): the `plugin` controller with `agingBonusPerInterval` and
  `agingCap` set to `"0.0"` in its configuration file, quoted (D-017). Restore them afterwards.
  While they are changed, Phase 1's JCasC checks fail, as they should: commit nothing and run no
  gate until the file is restored.
- **stock** (the sanity run): the `stock` controller below, which has no plugin at all.

## The stock-Jenkins controller (D-078)

The sanity run needs Jenkins without the plugin, to test the assumption the observe-only control
rests on: that the plugin, installed and recording but not ordering, schedules as Jenkins does
without it. `jenkins-stock` is that controller:
- its image is the controller image's `stock` stage, the one the others' image is built on: the
  same Jenkins and plugins, without the optimizer;
- its configuration is `experiment-baseline.yaml` without the optimizer's block;
- it has its own agent, `stock-agent`, and its own home, `jenkins-stock-home`.

It sits in a Compose profile of its own, so `--profile experiment` starts no more than before. It
takes about 0.5 GB of memory, and 80 MB for its agent.

```
# Build it, and again whenever jenkins/controller/ or jenkins/agent/ changes. It needs no .hpi.
docker compose build jenkins-stock stock-agent

# Start it: healthy in about 30 s on this machine.
docker compose --profile stock up -d --wait jenkins-stock stock-agent

# Check it: freestyle-6 on one executor; the run must report the stock arm.
python -m experiment smoke --controller stock

# The sanity run of the matrix: freestyle-30, one executor, warm history, one repetition.
python -m experiment setup  --controller stock --workload freestyle-30
python -m experiment warmup --controller stock --workload freestyle-30 --passes 3
python -m experiment run    --controller stock --workload freestyle-30 --executors 1 --group sanity --repetition 1 --arm stock --history warm

# Stop it. The containers and the home stay.
docker compose --profile stock stop jenkins-stock stock-agent

# Remove the containers. The named volumes, and with them its build history, stay.
docker compose --profile stock rm -f jenkins-stock stock-agent
```

**Start it by its two service names.** A bare `docker compose --profile stock up -d` starts the
default stack as well, and recreates any of its services whose image has changed.

**Never remove its volumes:** `docker compose down -v` and `docker volume rm` are forbidden here
(rule 1.5).

`verify.py --phase 7` checks it with three checks, so a Phase 7 gate needs both profiles running:
`docker compose --profile experiment --profile stock up -d`.

**Comparing it with observe-only.** A stock run has no plugin events, so each job's queue entry is
the time the harness sent its trigger request, not the plugin's `inQueueSince`. Its waits and
makespan therefore include that request's latency and any offset between the host's clock and the
controller's: milliseconds, against waits of tens of seconds. Jenkins' own build start and end
times are measured alike in every arm, so compare on those first.

Stock Jenkins cannot load the plugin's job property, which every arm's jobs carry. It accepts the
jobs and stores them without it, so nothing enforces their dependencies there, as in observe-only.

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
