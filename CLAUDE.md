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
- Backend: `cd backend && uv run ruff check . && uv run mypy app && uv run pytest -m "not live and not e2e"`
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

## Environment facts (this machine, checked 2026-09-28)
- Present: Java 21.0.11, Maven 3.9.16, Node 24.12.0, Python 3.14.2, Git.
- Missing: docker, gh, uv. Docker blocks Phase 1 and every acceptance check from Phase 3 on.
- Build order is Phase 0 → 2 → 1 → 3..8. Phase 2 comes first because JenkinsRule needs no Docker.
- The Bash tool's sandbox blocks DNS. Network-touching commands (mvn, npm, pip) need the sandbox off.
- Jenkins LTS baseline is pinned to 2.568.3. The report's Appendix E says 2.541.x and must be updated.

## Lessons (add one line whenever a mistake repeats)
- Pipeline queue items are placeholder tasks; resolve the job with getOwnerTask().
- The M2 job property field is `priority`; v2 renames it to `level` for @Symbol and keeps an XStream
  alias, so old config.xml still loads. Do not "fix" this back.
- Report Appendix C prints the pre-inheritance score (0.633); the effective score after group
  inheritance is 0.650. Assert both.
