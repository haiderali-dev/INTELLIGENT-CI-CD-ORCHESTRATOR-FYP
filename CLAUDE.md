# Intelligent CI/CD Orchestrator

University final year project (UIT, Group 04). Full specification: BUILD_PROMPT.md. Progress: PROGRESS.md.

## What this is
Two AI assistants create Jenkins jobs from plain English; one Jenkins plugin prioritizes the queue for
freestyle, Maven and Pipeline jobs. Staging only.

## Layout
plugin/ (Java) · jenkins/ (images, JCasC) · backend/ (FastAPI) · frontend/ (React) ·
experiment/ · eval/ · catalog/ · sample-services/ · scripts/ · docs/ · legacy/m2-poc/ (read-only)

## Commands
- Plugin: `cd plugin && mvn -B verify`
- Backend: `cd backend && uv run python -m ruff check . && uv run python -m mypy app && uv run python -m pytest -m "not live and not e2e"`
- Frontend: `cd frontend && npm run lint && npm run typecheck && npm run test`
- Stack: `docker compose up -d` · Reset demo: `python scripts/demo_reset.py`
- Phase check: `python scripts/verify.py --phase N`

## Rules that must not be broken
- Never use the Jenkins script console (/script, /scriptText) anywhere.
- Never edit anything under legacy/.
- Never commit secrets; .env is local only.
- The scoring formula must match the report exactly: 0.5*U + 0.3*D + 0.2*T, U = HIGH 1.0 / MEDIUM 0.6 /
  LOW 0.3, aging = min(0.15, 0.05 * floor(waitMinutes / 5)). AppendixCExampleTest is the guard.
- The sorter always rebuilds the heap, including on a cache hit.
- The LLM never writes shell commands; commands come from catalog/services.yaml.
- Production deploys are refused by policy.
- Jenkins XML templates are derived from jenkins/reference-configs/, never written from memory.
- Every task ends with its check run and PROGRESS.md updated in the same commit.
- Never check a task off in PROGRESS.md on reasoning alone. Only a command that ran in this session counts.

## Conventions
- Python: type hints, ruff format, services hold logic, routers stay thin.
- TypeScript: strict mode, API types generated from OpenAPI.
- Java: one class per file, no Jenkins imports in heap or scoring packages.
- Commits: Conventional Commits. Branches: phase-<n>-<slug>.

## Environment facts (this machine, checked 2026-10-07)
- Present: Java 21.0.11, Maven 3.9.16, Node 24.12.0, Python 3.14.2, Git, Docker 29.8.0,
  uv 0.12.20 at `.venv-tools/` (project-local; the backend venv is `backend/.venv`, Python 3.12.14).
- Missing: gh. Four stacked PRs must be opened by hand until it is installed.
- Docker Desktop does not start with Windows here. Launch
  `%LOCALAPPDATA%/Programs/DockerDesktop/Docker Desktop.exe` and wait for `docker info` to succeed
  (about 30 s) before any Phase 1 or Phase 3+ acceptance check.
- A Windows Application Control policy blocks the console-script `.exe` shims in
  `backend/.venv/Scripts` (pytest.exe, mypy.exe). Use `uv run python -m pytest` / `-m mypy`, never
  `uv run pytest`. The packages themselves import and run fine; only the shims are blocked.
- The Bash tool's sandbox blocks DNS. Network-touching commands (mvn, npm, pip, git ls-remote) need
  the sandbox off.
- Jenkins LTS baseline is pinned to 2.568.3. The report's Appendix E says 2.541.x and must be updated.
- Build order was Phase 0 → 2 → 1 → 3..8, because JenkinsRule needs no Docker. Phases 0-2 are done.

## Lessons (add one line whenever a mistake repeats)
- Pipeline queue items are placeholder tasks; resolve the job with getOwnerTask().
- The M2 job property field is `priority`; v2 renames it to `level` for @Symbol and keeps an XStream
  alias, so old config.xml still loads. Do not "fix" this back.
- Report Appendix C prints the pre-inheritance score (0.633); the effective score after group
  inheritance is 0.650. Assert both.
- Never hand a subprocess a minimal env. Dropping `SystemRoot` breaks DNS on Windows and reports
  itself as `getaddrinfo() thread failed to start`, which reads like a network outage. Inherit
  `os.environ` and overlay. This bit both validate_catalog.py and GitClient.
