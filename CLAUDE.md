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
- Backend: `cd backend && uv run python -m ruff check . && uv run python -m mypy app && uv run python -m pytest -m "not live and not e2e and not integration"`
- Frontend: `cd frontend && npm run lint && npm run typecheck && npm run test`
- Browser flows: `cd frontend && npx playwright test` (Google Chrome; starts its own backend in fake
  mode from `backend/browser_backend.py`, and needs no Docker or credential)
- System tests on the running stack: `python scripts/stack_system_test.py` (a throwaway account,
  deactivated afterwards). Lighthouse: `cd frontend && LIGHTHOUSE=1 npx playwright test
  --project=lighthouse`
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

## Environment facts (this machine, checked 2026-10-09)
- Present: Java 21.0.11, Maven 3.9.16, Node 24.12.0, Python 3.14.2, Git, Docker 29.8.1,
  uv 0.12.20 at `.venv-tools/` (project-local; the backend venv is `backend/.venv`, Python 3.12.14).
- gh 2.102.0 is installed and logged in (checked 2026-10-11). Open each phase PR against `main`:
  stacked PRs merged into intermediate branches and kept Phases 2 to 4 out of `main`.
- This is a laptop. On battery its CPU runs at about half speed, and it suspends when idle: gate run
  6 (2026-10-22) went onto battery, was suspended for 22 minutes in Phase 3, and timed out in the
  backend suite. Start a gate or a measurement only on mains power:
  `(Get-CimInstance Win32_Battery).BatteryStatus` is 2 on mains and 1 on battery.
- Claude Code stops a background command when memory runs short. It stopped full gates here on
  2026-10-14, 2026-10-16 and 2026-10-23 (run 8, with the experiment profile up); run 9 then passed
  in the user's own PowerShell window. Windows PowerShell's `*>` writes UTF-16, so transcode such a
  log to UTF-8 before keeping it in `docs/testing/evidence/`.
- Docker Desktop does not start with Windows here. Launch
  `%LOCALAPPDATA%/Programs/DockerDesktop/Docker Desktop.exe` and wait for `docker info` to succeed
  (about 30 s) before any Phase 1 or Phase 3+ acceptance check.
- A Windows Application Control policy blocks the console-script `.exe` shims in
  `backend/.venv/Scripts` (pytest.exe, mypy.exe). Use `uv run python -m pytest` / `-m mypy`, never
  `uv run pytest`. The packages themselves import and run fine; only the shims are blocked.
- The same policy blocks the temporary interpreter uv builds the project with, so any `uv run`
  after a `pyproject.toml` change fails. Always `uv run --no-sync`. To add a dependency:
  `uv add --no-sync <pkg>`, then `uv sync --no-install-project --inexact --all-extras` (the project
  is already installed editable, so it never needs rebuilding).
- The Bash tool's sandbox blocks DNS. Network-touching commands (mvn, npm, pip, git ls-remote) need
  the sandbox off.
- Jenkins LTS baseline is pinned to 2.568.3. The report's Appendix E says 2.541.x and must be updated.
- Build order was Phase 0 → 2 → 1 → 3..8, because JenkinsRule needs no Docker. Phases 0-6 are done
  (Phase 6 merged as PR #11; hardened on `phase-6-hardening`, 2026-10-18 to 2026-10-22). Phase 7's
  tasks and gate are done on `phase-7-experiment` (draft PR #14, 2026-10-23); its full matrix
  needs a human.
- Docker here uses the containerd image store, so a container's `Image` field names the index its
  image arrived in. Compare a container with Compose's `com.docker.compose.image` label instead.
  Provenance attestations are off in `docker-compose.yml`, because they gave every build a new ID
  (D-070).

## Lessons (add one line whenever a mistake repeats)
- Pipeline queue items are placeholder tasks; resolve the job with getOwnerTask().
- The M2 job property field is `priority`; v2 renames it to `level` for @Symbol and keeps an XStream
  alias, so old config.xml still loads. Do not "fix" this back.
- Report Appendix C prints the pre-inheritance score (0.633); the effective score after group
  inheritance is 0.650. Assert both.
- Never hand a subprocess a minimal env. Dropping `SystemRoot` breaks DNS on Windows and reports
  itself as `getaddrinfo() thread failed to start`, which reads like a network outage. Inherit
  `os.environ` and overlay. This bit both validate_catalog.py and GitClient.
- A verify.py check must not depend on another check having run first. One passed only after a
  later check had triggered builds; after a controller restart it failed. Make checks set up
  the state they assert on.
- Never write escape sequences (`\n`, `\d`) through a bash heredoc into Python source: they
  arrive as real newlines. Use the Write or Edit tool, then `ast.parse` the file.
  This repeated on 2026-10-11 with a `python - <<'EOF'` rewrite script. Its `open(p, "w")` also
  wrote CRLF, because text mode does that on Windows. Never patch source files from a heredoc.
  The Write and Edit tools are not escape-proof either: on 2026-10-13 a backslash-u escape for
  U+2139, typed into a regex, arrived as the literal character, while `\b`, `\d` and `\n`
  survived. It happened again while recording this lesson. For non-ASCII in source, use a
  `"\N{NAME}"` constant, then grep the file for the raw character.
  Repeated on 2026-10-18: a hex escape for NUL in a regex, patched through a heredoc, landed as a
  real NUL byte. After any scripted edit, scan the file for bytes below 0x20 other than tab and
  newline. Repeated on 2026-10-21: `lineterminator="\n"`, patched through a heredoc, became a real
  newline inside the string. The byte scan cannot see that; `ast.parse` caught it. Use Edit.
- An Edit with an empty `new_string` also deletes the line break after the match: removing a
  trailing comment that way joined 25 lines (2026-10-23). To cut text out of a line, keep
  `new_string` non-empty, or use a bytes-in, bytes-out script file; then `ast.parse`.
- A Pipeline reports `building: false` and its result before `Finished: SUCCESS` is in the log.
  Wait on progressiveText's `X-More-Data`, never on `building`, before treating a log as whole
  (D-039).
- An empty Git branch spec means "any branch" to the Git plugin, and the build reports SUCCESS
  on whatever it picked. A revision must never reach Jenkins empty. Use `select_revision` (D-041).
- Git Bash rewrites any command argument that starts with `/` into a Windows path, a regex
  included. It broke a `docker exec` path (2026-10-13) and a `node -e` regex (2026-10-14). Put
  such arguments in a script file, or inside `sh -c '...'`.
- A frontend page test must never assume a page draws within a second. Pages load lazily, and under
  the gate's load a cold render took longer: it failed the sign-in tests (2026-10-18) and two page
  tests (2026-10-20). `src/test/setup.ts` waits 5 s and `vite.config.ts` allows 15 s a test.
- The backend's pytest `addopts` already has `-q`. A second one prints no summary line at all,
  which reads like no tests ran. It happened twice; never add `-q` to backend pytest commands.
