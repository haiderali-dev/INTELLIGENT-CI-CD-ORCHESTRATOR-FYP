"""What a failed build's log shows, worked out by code.

4.5.3 step 3, "Code decides, never the model", applied to failures: the category, the failing
tests, the evidence lines and the stages that never ran all come from here. The model is only asked
to put them into words, and every line it quotes is checked against this module's excerpt before
it is shown (``app.failures.explainer``).

The rules match the formats this stack really produces, taken from logs captured on jenkins-dev
(``docs/evidence/2026-10-11-demo-failing-tests/``): pytest and Node's test runner in the sample
services, a Git checkout that found no revision, a script that was not executable, and an agent that
could not reach Docker. A few common formats beyond those (Jest, Mocha, Maven Surefire, Go, TAP,
ruff, ESLint, Bandit, npm audit) are matched too, because the catalog can name other services.

The excerpt is what the model sees. It is normalised -- durations, temporary script names, build
numbers, clock times and full SHAs replaced by placeholders -- for two reasons. Those values say
nothing about why a build failed, and they change on every run. With them in, the same failure
would be a new prompt each time, so a recorded answer could never be replayed (T5.8's replay
fixtures) and every repeat would be paid for again.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from app.failures.redact import redact


class FailureCategory(StrEnum):
    CHECKOUT = "checkout_error"
    INFRASTRUCTURE = "infrastructure"
    TIMEOUT = "timeout"
    TESTS = "test_failure"
    LINT = "lint_failure"
    SECURITY = "security_findings"
    SCRIPT = "script_error"
    BUILD = "build_error"
    DEPLOY = "deploy_error"
    UNKNOWN = "unknown"


# A failure is explained by the end of its log. A longer log is analysed from this many characters
# before its end, with line numbers still counted from the real start.
MAX_LOG_CHARS: Final = 1_000_000

# The excerpt: the failing step or stage, plus notable lines from elsewhere, within a budget that
# leaves room in Groq's 8,000 tokens a minute for the rest of the prompt (4.5.1).
MAX_SECTION_LINES: Final = 100
SECTION_HEAD_LINES: Final = 15
MAX_SIGNAL_LINES: Final = 8
MAX_EXCERPT_CHARS: Final = 7000
MAX_EXCERPT_LINE_CHARS: Final = 300
FALLBACK_TAIL_LINES: Final = 40
GAP: Final = "[... lines omitted ...]"

MAX_EVIDENCE: Final = 5
MAX_FAILED_TESTS: Final = 10
# What a quoted line is cut to in a response.
MAX_SHOWN_LINE_CHARS: Final = 500

PIPELINE: Final = "PIPELINE"


@dataclass(frozen=True)
class EvidenceLine:
    """A line of the log, by its 1-based number in Jenkins's whole log: as printed, but redacted."""

    number: int
    text: str


@dataclass(frozen=True)
class ExcerptLine:
    """One line the model is shown. ``number`` is None for an omission marker.

    ``text`` is normalised; ``original`` is the redacted line as printed, which is what the user
    sees when this line is quoted.
    """

    number: int | None
    text: str
    original: str


@dataclass(frozen=True)
class FailureAnalysis:
    category: FailureCategory
    stage: str | None
    evidence: tuple[EvidenceLine, ...]
    failed_tests: tuple[str, ...]
    tests_failed: int | None
    tests_passed: int | None
    exit_code: int | None
    skipped_stages: tuple[str, ...]
    excerpt: tuple[ExcerptLine, ...]
    log_available: bool
    log_complete: bool
    lines: int
    truncated: bool
    redactions: int
    unavailable_reason: str | None = None

    @property
    def cause_found(self) -> bool:
        return self.log_available and self.category is not FailureCategory.UNKNOWN

    def quoted(self, number: int) -> EvidenceLine | None:
        """The excerpt's line ``number`` as evidence, if the model was shown it."""
        for line in self.excerpt:
            if line.number == number:
                return EvidenceLine(number=number, text=line.original)
        return None


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Rule:
    category: FailureCategory
    pattern: re.Pattern[str]
    # True: the cause can be anywhere in the log (a checkout runs before any step). False: only
    # the failing step or stage counts, so a test that prints "SyntaxError" while passing does not
    # turn a failed deploy into a build error.
    whole_log: bool


# Two characters test runners print that look like plain ASCII ones, named so neither is mistaken
# for an "i" or a ">": Node's runner starts its summary lines with the first, Jest separates a
# suite from its test with the second.
_INFO: Final = "\N{INFORMATION SOURCE}"
_ARROW: Final = "\N{SINGLE RIGHT-POINTING ANGLE QUOTATION MARK}"

# In order: the first rule that matches decides. Causes that stop everything come first, so a
# checkout error is not reported as the test failure it prevented from ever running.
_RULES: Final = (
    # The agent's own faults first. A clone that failed because the agent could not reach the
    # network says nothing about the branch, and "check the branch was pushed" would send the
    # developer the wrong way -- found on jenkins-dev, where Docker Desktop's DNS drops a lookup now
    # and then (tests/data/failure_logs/payment-service-test-unit-dns.log).
    _Rule(
        FailureCategory.INFRASTRUCTURE,
        re.compile(
            r"There are no nodes with the label"
            r"|Agent went offline|ChannelClosedException|Cannot contact \S+: java\."
            r"|No space left on device"
            r"|Cannot connect to the Docker daemon"
            r"|permission denied while trying to connect to the [Dd]ocker"
            r"|java\.lang\.OutOfMemoryError"
            r"|^Killed$"
            r"|Could not resolve host|Could not resolve hostname"
            r"|Temporary failure in name resolution|Name or service not known"
            r"|Network is unreachable|Failed to connect to \S+ port \d+"
        ),
        whole_log=True,
    ),
    _Rule(
        FailureCategory.CHECKOUT,
        re.compile(
            r"Couldn't find any revision to build"
            r"|^ERROR: Error (?:cloning|fetching) remote repo"
            r"|hudson\.plugins\.git\.GitException"
            r"|^fatal: (?:repository|could not read|unable to access|couldn't find remote ref"
            r"|reference is not a tree)"
            r"|^ERROR: Checkout failed"
        ),
        whole_log=True,
    ),
    _Rule(
        FailureCategory.TIMEOUT,
        re.compile(
            r"Build timed out|Timeout has been exceeded|Cancelling nested steps due to timeout"
        ),
        whole_log=True,
    ),
    _Rule(
        FailureCategory.TESTS,
        re.compile(
            r"^FAILED \S"  # pytest's short summary
            r"|^=+ .*\b\d+ failed\b"  # pytest's summary line
            r"|^\d+ failed\b"  # pytest -q's summary line
            rf"|^{_INFO} fail [1-9]"  # node --test
            r"|^✖ failing tests:"  # node --test
            r"|^✖ .+ \(\d+(?:\.\d+)?ms\)$"  # node --test, one failed test
            r"|^Tests:\s+\d+ failed"  # Jest
            r"|^\s*\d+ failing\b"  # Mocha
            r"|Tests run: \d+, Failures: [1-9]"  # Maven Surefire
            r"|There are test failures"  # Maven Surefire
            r"|^--- FAIL: "  # go test
            r"|^not ok \d+"  # TAP
        ),
        whole_log=False,
    ),
    _Rule(
        FailureCategory.LINT,
        re.compile(r"^Found \d+ errors?\b|✖ \d+ problems?\b|^\S+:\d+:\d+: [A-Z]{1,4}\d{1,4}\b"),
        whole_log=False,
    ),
    _Rule(
        FailureCategory.SECURITY,
        re.compile(
            r"Issue: \[B\d+"  # Bandit
            r"|found \d+ (?:\w+ (?:severity )?)?vulnerabilit"  # npm audit
            r"|Found \d+ known vulnerabilit"  # pip-audit
        ),
        whole_log=False,
    ),
    _Rule(
        FailureCategory.SCRIPT,
        re.compile(
            r": Permission denied$|: not found$|command not found$|: No such file or directory$"
        ),
        whole_log=False,
    ),
    _Rule(
        FailureCategory.BUILD,
        re.compile(
            r"SyntaxError|ModuleNotFoundError|ImportError"
            r"|^npm ERR!|^error TS\d+|COMPILATION ERROR|BUILD FAILURE"
            r"|^error(?:\[\w+\])?: "
        ),
        whole_log=False,
    ),
)

# Lines that explain a test failure without being the summary: pytest's "E" lines, assertion
# messages, Jest's expected and received values.
_TEST_DETAIL = re.compile(r"^E {2,}\S|AssertionError|^\s+(?:Expected|Received):")

_FAILED_TEST_NAMES: Final = (
    re.compile(r"^FAILED (?P<name>\S+)"),  # pytest
    re.compile(r"^✖ (?P<name>.+?) \(\d+(?:\.\d+)?ms\)$"),  # node --test
    re.compile(rf"^\s*● (?P<name>.+ {_ARROW} .+)$"),  # Jest
    re.compile(r"^--- FAIL: (?P<name>\S+)"),  # go test
    re.compile(r"^not ok \d+ (?:- )?(?P<name>.+)$"),  # TAP
)

_PYTEST_COUNTS = re.compile(r"^(?:=+ )?(?P<failed>\d+) failed(?:, (?P<passed>\d+) passed)?")
_JEST_COUNTS = re.compile(r"^Tests:\s+(?P<failed>\d+) failed(?:, (?P<passed>\d+) passed)?")
_NODE_FAIL = re.compile(rf"^{_INFO} fail (?P<count>\d+)$")
_NODE_PASS = re.compile(rf"^{_INFO} pass (?P<count>\d+)$")
_MOCHA_FAILING = re.compile(r"^\s*(?P<count>\d+) failing\b")
_MOCHA_PASSING = re.compile(r"^\s*(?P<count>\d+) passing\b")

_EXIT_CODE = re.compile(
    r"(?i)(?:script returned exit code|exited with code|exit (?:code|status)) (\d+)"
)

# Where the failure is. A freestyle step starts with "[job] $ /bin/sh -xe /tmp/jenkinsN.sh"; a
# Pipeline stage with "[Pipeline] { (Name)".
_SHELL_STEP = re.compile(r"^\[[^\]\n]{1,200}\] \$ ")
_STAGE_START = re.compile(r"^\[Pipeline\] \{ \((?P<name>[^\n]{1,200})\)$")
_PIPELINE_LINE = re.compile(r"^\[Pipeline\] ")
_SKIPPED_STAGE = re.compile(
    r'^Stage "(?P<name>[^"\n]{1,200})" skipped due to earlier failure\(s\)$'
)

# A frame of a Node or Java stack trace: "    at Test.run (node:internal/...)".
_STACK_FRAME = re.compile(r"^\s+at \S")
STACK_FRAMES_KEPT: Final = 3

# Worth showing the model even outside the failing step.
_SIGNAL = re.compile(
    r"^(?:ERROR|FATAL):|Exception\b|^Caused by:|skipped due to earlier failure"
    r"|Couldn't find any revision|[Pp]ermission denied|No space left on device|timed out"
)

# Jenkins's own closing lines, which say that a step failed but never why.
_BOILERPLATE = re.compile(
    r"^(?:Finished: \w+$|Build step '.+' marked build as failure$|Archiving artifacts$"
    r"|\[Pipeline\] |\[WS-CLEANUP\] |Recording test results$|Notifying upstream projects"
    r"|Triggering a new build of |ERROR: script returned exit code \d+$)"
)

# Colour codes, and the hidden console notes Jenkins wraps in ESC[8m ... ESC[0m. Neither crosses a
# line end, so removing them never moves a line number.
_ANSI = re.compile(r"\x1b\[8mha:[^\x1b\n]*\x1b\[0m|\x1b\[[0-9;?]*[ -/]*[@-~]")

# Timestamper's prefix on each line of a Pipeline's step output, "[2026-10-13T06:28:51.225Z] ", or
# "[06:28:51] " in its short form. Stripped before anything reads a line: the rules are anchored at
# the start of a line, and the time changes on every run.
_TIMESTAMP = re.compile(r"^\[(?:\d{4}-\d{2}-\d{2}T)?\d{2}:\d{2}:\d{2}(?:[.,]\d{1,9})?Z?\] ?", re.M)

# The excerpt is fenced in <log> ... </log>. A build that prints the fence itself could close it
# early and pass what follows off as facts, so inside the excerpt the fence is defused.
_FENCE = re.compile(r"(?i)<(/?)log>")

# Replaced before the model sees a line. See the module docstring.
_VOLATILE: Final = (
    # A pattern over log text, not a file this code opens.
    (re.compile(r"/tmp/jenkins\d+\.sh"), "/tmp/jenkins<n>.sh"),  # noqa: S108
    (re.compile(r"\bduration_ms \d+(?:\.\d+)?"), "duration_ms <duration>"),
    (
        re.compile(r"(?<![\w.])\d+(?:\.\d+)? ?(?:ms|s|sec|secs|seconds|min|mins|minutes)\b"),
        "<duration>",
    ),
    (
        re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?"),
        "<time>",
    ),
    (re.compile(r"\b\d{2}:\d{2}:\d{2}(?:[.,]\d+)?\b"), "<time>"),
    (re.compile(r"\bbuild number \d+\b"), "build number <n>"),
    (re.compile(r"(?<![\w&])#\d+\b"), "#<n>"),
    (re.compile(r"\b(?:[0-9a-f]{64}|[0-9a-f]{40})\b"), "<sha>"),
)


def normalise(line: str) -> str:
    """A log line as the model sees it: volatile values replaced and the excerpt's fence defused."""
    for pattern, placeholder in _VOLATILE:
        line = pattern.sub(placeholder, line)
    return _FENCE.sub(r"<\1log_>", line)


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


def analyse(
    log: str,
    *,
    job_type: str,
    stage: str | None = None,
    stage_template: str | None = None,
    known_secrets: Iterable[str] = (),
    complete: bool = True,
    first_line: int = 1,
) -> FailureAnalysis:
    """Work out what ``log`` shows about why its build failed.

    ``stage`` is the failed stage's name (a freestyle chain job's stage, or the stage the Pipeline
    stage view reports as failed) and ``stage_template`` its template, when they are known.
    ``complete`` is False when Jenkins was still writing the log. ``first_line`` is the number, in
    Jenkins's whole log, of ``log``'s first line: more than 1 when only the end was read
    (``JenkinsClient.console_tail``).
    """
    text, first_number, truncated = _tail(log)
    first_number += first_line - 1
    truncated = truncated or first_line > 1
    # Console notes and colour first: a Pipeline line can start with a hidden note, then a time.
    text = _TIMESTAMP.sub("", _ANSI.sub("", text.replace("\r\n", "\n")))
    redacted = redact(text, known_secrets)
    # What a terminal would show for a line rewritten with carriage returns: its last state.
    lines = [line.rsplit("\r", 1)[-1] for line in redacted.text.split("\n")]
    if lines and lines[-1] == "":
        lines.pop()

    section = _section(lines, job_type=job_type, stage=stage)
    category, evidence_indexes = _classify(lines, section, stage_template)
    signals = _signals(lines, section)
    excerpt = _excerpt(lines, first_number, section, signals)

    return FailureAnalysis(
        category=category,
        stage=stage,
        evidence=tuple(
            EvidenceLine(number=first_number + i, text=_shown(lines[i])) for i in evidence_indexes
        ),
        failed_tests=_failed_tests(lines, section),
        tests_failed=_count(lines, section, failed=True),
        tests_passed=_count(lines, section, failed=False),
        exit_code=_exit_code(lines),
        skipped_stages=tuple(
            dict.fromkeys(
                match.group("name") for line in lines if (match := _SKIPPED_STAGE.match(line))
            )
        ),
        excerpt=excerpt,
        log_available=True,
        log_complete=complete,
        lines=first_number - 1 + len(lines),
        truncated=truncated,
        redactions=redacted.count,
    )


def unavailable(reason: str, *, stage: str | None = None) -> FailureAnalysis:
    """The analysis of a run whose log cannot be read: no cause, and no evidence to show."""
    return FailureAnalysis(
        category=FailureCategory.UNKNOWN,
        stage=stage,
        evidence=(),
        failed_tests=(),
        tests_failed=None,
        tests_passed=None,
        exit_code=None,
        skipped_stages=(),
        excerpt=(),
        log_available=False,
        log_complete=False,
        lines=0,
        truncated=False,
        redactions=0,
        unavailable_reason=reason,
    )


def _tail(log: str) -> tuple[str, int, bool]:
    """The part of ``log`` to analyse, the line number it starts at, and whether it was cut."""
    if len(log) <= MAX_LOG_CHARS:
        return log, 1, False
    cut = log.find("\n", len(log) - MAX_LOG_CHARS)
    start = len(log) - MAX_LOG_CHARS if cut < 0 else cut + 1
    return log[start:], log.count("\n", 0, start) + 1, True


def _section(lines: Sequence[str], *, job_type: str, stage: str | None) -> range:
    """The failing step or stage, as a range of line indexes."""
    count = len(lines)
    if job_type == PIPELINE:
        if stage is not None:
            for start in range(count - 1, -1, -1):
                match = _STAGE_START.match(lines[start])
                if match and match.group("name") == stage:
                    end = next(
                        (i for i in range(start + 1, count) if _STAGE_START.match(lines[i])), count
                    )
                    return range(start, end)
    else:
        # A failed shell step stops a freestyle build, so the failing step is the last one.
        for start in range(count - 1, -1, -1):
            if _SHELL_STEP.match(lines[start]):
                return range(start, count)
    return range(max(0, count - FALLBACK_TAIL_LINES), count)


def _classify(
    lines: Sequence[str], section: range, stage_template: str | None
) -> tuple[FailureCategory, list[int]]:
    """The category and the lines that show it. No match is UNKNOWN, never a guess."""
    for rule in _RULES:
        scope: Iterable[int] = range(len(lines)) if rule.whole_log else section
        matched = _distinct(lines, [i for i in scope if rule.pattern.search(lines[i])])
        if not matched:
            continue
        if rule.category is FailureCategory.TESTS:
            details = _distinct(lines, [i for i in section if _TEST_DETAIL.search(lines[i])])[:2]
            matched = _distinct(
                lines, sorted(set(matched[: MAX_EVIDENCE - len(details)]) | set(details))
            )
        return rule.category, matched[:MAX_EVIDENCE]

    # Nothing recognisable. A failed deploy is still a deploy failure: the stages before it passed,
    # so whatever went wrong went wrong there. Anything else is unknown, with the step's last lines
    # as the evidence rather than a cause the log does not state.
    last_lines = [i for i in section if lines[i].strip() and not _BOILERPLATE.match(lines[i])][-3:]
    if stage_template == "deploy":
        return FailureCategory.DEPLOY, last_lines
    return FailureCategory.UNKNOWN, last_lines


def _distinct(lines: Sequence[str], indexes: Iterable[int]) -> list[int]:
    """The first of each run of identical lines: Node's runner prints a failed test twice."""
    seen: set[str] = set()
    kept = []
    for i in indexes:
        if lines[i].strip() not in seen:
            seen.add(lines[i].strip())
            kept.append(i)
    return kept


def _signals(lines: Sequence[str], section: range) -> list[int]:
    found = [i for i in range(len(lines)) if i not in section and _SIGNAL.search(lines[i])]
    return found[-MAX_SIGNAL_LINES:]


def _is_noise(line: str) -> bool:
    return bool(_PIPELINE_LINE.match(line)) and not _STAGE_START.match(line)


def _without_deep_frames(lines: Sequence[str], indexes: list[int]) -> list[int]:
    """Each stack trace cut to its first frames: the rest rarely say why, and cost the budget."""
    kept = []
    run = 0
    for i in indexes:
        run = run + 1 if _STACK_FRAME.match(lines[i]) else 0
        if run <= STACK_FRAMES_KEPT:
            kept.append(i)
    return kept


def _excerpt(
    lines: Sequence[str], first_number: int, section: range, signals: list[int]
) -> tuple[ExcerptLine, ...]:
    kept = _without_deep_frames(lines, [i for i in section if not _is_noise(lines[i])])
    if len(kept) > MAX_SECTION_LINES:
        kept = kept[:SECTION_HEAD_LINES] + kept[-(MAX_SECTION_LINES - SECTION_HEAD_LINES) :]
    chosen = sorted(set(kept) | set(signals))

    shown = {i: _clip(normalise(lines[i]).rstrip(), MAX_EXCERPT_LINE_CHARS) for i in chosen}
    # Over budget, the earliest lines go first: the failure is at the end of a step.
    while len(chosen) > 1 and sum(len(shown[i]) + 1 for i in chosen) > MAX_EXCERPT_CHARS:
        chosen.pop(0)

    excerpt: list[ExcerptLine] = []
    previous = -1
    for index in chosen:
        if any(not _is_noise(lines[i]) for i in range(previous + 1, index)):
            excerpt.append(ExcerptLine(number=None, text=GAP, original=GAP))
        excerpt.append(
            ExcerptLine(
                number=first_number + index, text=shown[index], original=_shown(lines[index])
            )
        )
        previous = index
    return tuple(excerpt)


def _failed_tests(lines: Sequence[str], section: range) -> tuple[str, ...]:
    names: dict[str, None] = {}
    for i in section:
        for pattern in _FAILED_TEST_NAMES:
            match = pattern.match(lines[i])
            if match:
                names[_clip(match.group("name").strip(), 200)] = None
                break
    return tuple(names)[:MAX_FAILED_TESTS]


def _count(lines: Sequence[str], section: range, *, failed: bool) -> int | None:
    """The number of failed (or passed) tests the runner reported, if it reported one."""
    for i in reversed(section):
        line = lines[i]
        for summary in (_PYTEST_COUNTS, _JEST_COUNTS):
            match = summary.match(line)
            if match:
                value = match.group("failed" if failed else "passed")
                return int(value) if value is not None else (None if failed else 0)
        single = (_NODE_FAIL, _MOCHA_FAILING) if failed else (_NODE_PASS, _MOCHA_PASSING)
        for pattern in single:
            match = pattern.match(line)
            if match:
                return int(match.group("count"))
    return None


def _exit_code(lines: Sequence[str]) -> int | None:
    for line in reversed(lines):
        match = _EXIT_CODE.search(line)
        if match:
            return int(match.group(1))
    return None


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _shown(line: str) -> str:
    return _clip(line.rstrip(), MAX_SHOWN_LINE_CHARS)
