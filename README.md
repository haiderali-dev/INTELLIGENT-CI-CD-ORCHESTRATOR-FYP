# Intelligent CI/CD Orchestrator

Final year project, UIT University, Batch 2023, Group 04. Supervisor: Engr. Laiba Mughal.

Two AI assistants turn plain English into real Jenkins jobs, and a Jenkins plugin reorders the build
queue so urgent work stops waiting behind routine work. Staging environments only; production
deployment is refused by policy, not merely unimplemented.

- **Dynamic Queue Optimizer v2** — a Jenkins plugin that scores and orders freestyle, Maven and
  Pipeline jobs by the report's weighted formula, fills every idle executor in priority order, and
  holds a job whose upstream is still running.
- **Freestyle Assistant** — chat that creates a chained freestyle build, test and deploy.
- **Pipeline Assistant** — chat that creates one Pipeline job with a declarative Jenkinsfile.
- **Dashboard** — live queue with a score breakdown per job, run tracking, and analytics covering the
  scheduling experiment and the chatbot evaluation.

Full specification: [`BUILD_PROMPT.md`](BUILD_PROMPT.md). Current state:
[`PROGRESS.md`](PROGRESS.md). Plan and conflicts found: [`PLAN.md`](PLAN.md).

---

## Quick start

### Prerequisites

| Tool | Version | Needed for |
| --- | --- | --- |
| Docker Desktop, with Compose | 24 or newer | The whole stack |
| JDK (Temurin) | 21 | Building the plugin |
| Apache Maven | 3.9 or newer | Building the plugin |
| Node.js | 24 LTS | The frontend |
| Python | 3.12 or newer | Tooling and the backend |
| `uv` | latest | Backend dependencies |

Everything is developed and tested on both Windows 10/11 with PowerShell and on Linux. All tooling is
written as Python scripts rather than shell scripts, so the same commands work on both.

### Run it

```bash
# 1. Secrets. Copy the template and fill it in. .env is gitignored and must stay local.
cp .env.example .env

# 2. Build the plugin. The controller image picks the .hpi up from plugin/target/.
cd plugin && mvn -B verify && cd ..

# 3. Start everything.
docker compose up -d

# 4. Create the SSH keys, wait for Jenkins, and mint the bot's API token.
python scripts/bootstrap.py
```

Then open:

| Service | URL |
| --- | --- |
| Frontend | <http://localhost:5173> |
| Backend API docs | <http://localhost:8000/docs> |
| Jenkins | <http://localhost:8087> |

Sign in with the `SEED_ADMIN_EMAIL` and `SEED_ADMIN_PASSWORD` from your `.env`.

> **No Groq API key?** Set `LLM_MODE=fake` for deterministic canned answers, or `LLM_MODE=replay` to
> serve recorded fixtures. Both run the whole flow with no network access and no key.

### Check a phase

```bash
python scripts/verify.py --phase 0    # or any phase up to 8
python scripts/verify.py --phase 0 --list    # show the checks without running them
```

It prints one line per check and ends with `ALL CHECKS PASSED` or `<n> CHECKS FAILED`, exiting 0 or 1.

---

## Layout

```text
plugin/            Dynamic Queue Optimizer v2 (Java, Maven)
jenkins/           Controller and agent images, JCasC, exported reference configs
backend/           FastAPI, PostgreSQL, the AI core and the job generators
frontend/          Vite, React, TypeScript
sample-services/   payment-service (Python), auth-service (Node.js)
catalog/           services.yaml and its JSON Schema
experiment/        Scheduling experiment harness v2, workloads, results
eval/              Chatbot test set, runner and metrics
scripts/           bootstrap.py, verify.py, demo_reset.py, report/
docs/              The report, decisions, report updates, versions, screenshots
legacy/m2-poc/     Milestone 2, frozen and read-only
```

## Per-component commands

```bash
# Plugin
cd plugin && mvn -B verify

# Backend
cd backend && uv run ruff check . && uv run mypy app && uv run pytest -m "not live and not e2e"

# Frontend
cd frontend && npm run lint && npm run typecheck && npm run test

# Scheduling experiment
python -m experiment setup && python -m experiment warmup && python -m experiment run

# Chatbot evaluation
python -m eval run --parser rules --file eval/datasets/sample.jsonl
```

## How it works

A message goes to one shared AI core. The model's only job is to fill a structured intent whose
enums come from `catalog/services.yaml`, and then to plan a YAML spec of stages. It never writes a
shell command and never decides whether something is valid:

1. **Parse.** The model returns a structured intent, or the rule-based parser does when the model is
   unavailable. Either way the response says which answered.
2. **Check in code.** The service, branch, commit, test suite and environment are verified against
   the catalog and Git. Code decides, never the model.
3. **Clarify.** A missing required field becomes one question with up to four answer buttons.
4. **Apply policy.** Roles, the HIGH-urgency daily quota and the staging-only rule. Every denial
   returns a reason and writes an audit entry.
5. **Render.** Jinja2 templates, derived from `config.xml` exported from real hand-made jobs, produce
   either a freestyle chain or a Jenkinsfile. Stage commands come from the catalog.
6. **Preview and approve.** Editable YAML, the rendered artifact, a validation checklist and a
   plain-English explanation. A human approves before anything is created.
7. **Schedule.** The plugin scores every queued job as `0.5·U + 0.3·D + 0.2·T` plus an aging bonus,
   orders the queue, and holds any job whose declared upstream is still queued or building.

## The score bar

The queue page shows, for every waiting job, how its score was built: urgency, dependency,
execution-time and aging contributions as one compact stacked bar. It is the answer to the only
question that matters when a build is waiting — *why is mine not running yet?* — and it appears on
the queue, the run card and the analytics page.

## Reproducing the numbers

No figure in the report is typed by hand. Each one is generated from data:

| Figure | Generated by |
| --- | --- |
| Appendix C worked example | `python scripts/report/appendix_c.py`, from the same fixture `AppendixCExampleTest` asserts |
| Table 12.1 and the Chapter 12 charts | `python -m experiment report` |
| Chatbot evaluation tables | `python -m eval report` |
| Appendix E tools and versions | `python scripts/report/versions.py` |

Milestone 2's results are carried forward as a clearly labelled series, "M2 dispatcher v1", and are
never mixed into version 2 aggregates. Their provenance, including a stale-artifact finding and one
run where the old plugin silently degraded to FIFO, is written up in
[`docs/m2-baseline.md`](docs/m2-baseline.md).

## Contributing

- Work phase by phase. Each phase lives on `phase-<n>-<slug>` and ends with a pull request reviewed
  by someone from a different track.
- A task is done only when its acceptance check has actually been run. Record the command and its
  result in `PROGRESS.md` in the same commit.
- Conventional Commits.
- `legacy/` is read-only. `.env` never leaves your machine. The Jenkins script console
  (`/script`, `/scriptText`) is never called from our code, and a check in `verify.py` fails the
  build if it appears.
