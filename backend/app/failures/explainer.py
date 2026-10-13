"""Turning an analysis into an explanation, and checking it before anyone reads it.

The model is asked for a summary, one to three evidence lines and up to three suggestions, through
a strict schema (4.5.1). Its answer is checked in code, and dropped if any check fails:

* **Every quoted line must be in the excerpt it was shown.** A quote that is not in the log means
  the model is describing something the log does not say, so one such quote drops the answer.
* **"No cause visible" is refused when the rules found one,** because the code's own evidence
  contradicts it.
* **Production is out of scope.** A summary that brings up production is dropped, whatever it
  quotes. This system deploys only to staging (4.5.5), and a log is written by whoever pushed the
  commit: a line asking the model to talk someone into a production deploy could otherwise be
  echoed with itself as the evidence. A genuine case ("production dependencies failed to
  install") loses only the model's wording, not the explanation.
* **No shell commands.** A suggestion that looks like a command is dropped; the model never
  writes commands, here as in generation.

A dropped answer, a model that cannot answer, and a log that cannot be read all lead to the
explanation code writes from the same analysis. The endpoint therefore always answers, and never
with a cause the log does not show.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

from app.ai.chain import CallRecord, ModelChain
from app.ai.prompting import PromptTemplate
from app.ai.providers.base import ChatMessage
from app.core.logging import get_logger
from app.failures.analysis import (
    GAP,
    PIPELINE,
    EvidenceLine,
    FailureAnalysis,
    FailureCategory,
    analyse,
)

logger = get_logger(__name__)

# Strict-mode JSON schema. Only the keywords the other schemas use (types, enum, required,
# additionalProperties): lengths and counts are enforced in code below, not left to the provider.
FAILURE_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["cause_found", "summary", "evidence", "suggestions"],
    "properties": {
        "cause_found": {"type": "boolean"},
        "summary": {"type": "string"},
        "evidence": {"type": "array", "items": {"type": "string"}},
        "suggestions": {"type": "array", "items": {"type": "string"}},
    },
}

MAX_SUMMARY_CHARS: Final = 800
MAX_QUOTES: Final = 3
# A shorter quote ("FAILED", "Error") proves nothing about which line was meant.
MIN_QUOTE_CHARS: Final = 8
MAX_SUGGESTIONS: Final = 3
MAX_SUGGESTION_CHARS: Final = 240

_PRODUCTION = re.compile(r"(?i)\bprod(?:uction)?\b")
_COMMAND_LIKE = re.compile(
    r"`|^\s*\$ |&&|\|\||\s\|\s|^\s*(?:sudo|rm|curl|wget|bash|sh|chmod|git|npm|npx|pip|python"
    r"|docker|kubectl|make)\s"
)


class Source(StrEnum):
    MODEL = "model"
    RULES = "rules"


@dataclass(frozen=True)
class FailureContext:
    """What the analysis cannot see in the log: which job this is and what its failure stopped."""

    job_name: str
    job_type: str
    result: str
    service: str | None = None
    not_started: tuple[str, ...] = ()


@dataclass(frozen=True)
class FailureExplanation:
    summary: str
    evidence: tuple[EvidenceLine, ...]
    suggestions: tuple[str, ...]
    cause_found: bool
    source: Source
    provider: str
    model: str | None
    ai_fallback: bool
    fallback_reasons: tuple[str, ...]
    prompt_version: str
    calls: tuple[CallRecord, ...] = ()
    # Why the model's answer was not used, when it gave one.
    rejected: str | None = None


@dataclass(frozen=True)
class _Accepted:
    summary: str
    evidence: tuple[EvidenceLine, ...]
    suggestions: tuple[str, ...]
    cause_found: bool


# ---------------------------------------------------------------------------
# What the model is told
# ---------------------------------------------------------------------------


def render_input(analysis: FailureAnalysis, context: FailureContext) -> str:
    """The user message: the job, the code's findings, then the excerpt fenced as data.

    Nothing in it changes between two runs of the same failure -- no build number, run id, time or
    duration -- so a recorded answer replays (T5.8) and a repeat costs no new prompt.
    """
    kind = "Pipeline job" if context.job_type == PIPELINE else "freestyle chain job"
    lines = [
        f"Job: {context.job_name} ({kind})",
        f"Service: {context.service or 'not known'}",
        f"Stage: {analysis.stage or 'not known'}",
        f"Result: {context.result}",
        "Found by code:",
        f"- category: {analysis.category.value}",
    ]
    if analysis.failed_tests:
        lines.append("- failing tests: " + "; ".join(analysis.failed_tests))
    if analysis.tests_failed is not None:
        counts = f"{analysis.tests_failed} failed"
        if analysis.tests_passed is not None:
            counts += f", {analysis.tests_passed} passed"
        lines.append(f"- test counts: {counts}")
    if analysis.exit_code is not None:
        lines.append(f"- exit code: {analysis.exit_code}")
    if context.not_started:
        lines.append("- did not start because of this failure: " + ", ".join(context.not_started))
    if analysis.skipped_stages:
        lines.append("- stages skipped after this failure: " + ", ".join(analysis.skipped_stages))
    lines.append("<log>")
    lines.extend(line.text for line in analysis.excerpt)
    lines.append("</log>")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Checking what the model said
# ---------------------------------------------------------------------------


def _squash(text: str) -> str:
    return " ".join(text.split())


def verify_quotes(
    quotes: object, analysis: FailureAnalysis
) -> tuple[tuple[EvidenceLine, ...], int]:
    """The quoted lines found in the excerpt, as evidence, and how many quotes were not found.

    A quote may be part of a line, and may differ from it in whitespace: models trim the
    indentation of a pytest ``E`` line, and that is not an invention. Anything else is.
    """
    if not isinstance(quotes, list):
        return (), 0
    shown = [(line.number, _squash(line.text)) for line in analysis.excerpt if line.number]
    found: list[EvidenceLine] = []
    missing = 0
    for quote in quotes:
        wanted = _squash(quote) if isinstance(quote, str) else ""
        number = next((n for n, text in shown if wanted in text), None)
        line = analysis.quoted(number) if len(wanted) >= MIN_QUOTE_CHARS and number else None
        if line is None:
            missing += 1
        elif line not in found:
            found.append(line)
    return tuple(sorted(found, key=lambda line: line.number)[:MAX_QUOTES]), missing


def clean_suggestions(items: object) -> tuple[str, ...]:
    """Suggestions in plain words: anything that looks like a command, or production, is dropped."""
    if not isinstance(items, list):
        return ()
    kept: list[str] = []
    for item in items:
        text = _squash(item) if isinstance(item, str) else ""
        if not text or len(text) > MAX_SUGGESTION_CHARS:
            continue
        if _COMMAND_LIKE.search(text) or _PRODUCTION.search(text):
            continue
        kept.append(text)
        if len(kept) == MAX_SUGGESTIONS:
            break
    return tuple(kept)


def check_answer(
    data: dict[str, Any], analysis: FailureAnalysis
) -> tuple[_Accepted | None, str | None]:
    """The model's answer if it survives every check, else why it did not."""
    cause_found = data.get("cause_found")
    summary = data.get("summary")
    if not isinstance(cause_found, bool) or not isinstance(summary, str):
        return None, "malformed_answer"
    summary = _squash(summary)
    if not summary or len(summary) > MAX_SUMMARY_CHARS:
        return None, "summary_out_of_bounds"

    evidence, missing = verify_quotes(data.get("evidence"), analysis)
    if missing:
        return None, "evidence_not_in_log"
    if cause_found and not evidence:
        return None, "cause_without_evidence"
    if not cause_found and analysis.cause_found:
        return None, "contradicts_the_log"
    if _PRODUCTION.search(summary):
        return None, "mentions_production"

    return (
        _Accepted(
            summary=summary,
            evidence=evidence,
            suggestions=clean_suggestions(data.get("suggestions")),
            cause_found=cause_found,
        ),
        None,
    )


# ---------------------------------------------------------------------------
# The explanation written by code
# ---------------------------------------------------------------------------

_SUMMARIES: Final[dict[FailureCategory, str]] = {
    FailureCategory.CHECKOUT: "Jenkins could not check out the source, so no build step ran.",
    FailureCategory.INFRASTRUCTURE: (
        "The failure came from the build agent or its environment, not from the code."
    ),
    FailureCategory.TIMEOUT: "The run was stopped at its time limit.",
    FailureCategory.LINT: "The lint step reported problems.",
    FailureCategory.SECURITY: "The security scan reported findings.",
    FailureCategory.SCRIPT: "A step's script could not be run.",
    FailureCategory.BUILD: "The build failed with an error.",
    FailureCategory.DEPLOY: "The deploy step failed after the stages before it had passed.",
    FailureCategory.UNKNOWN: "The log does not show why the step failed.",
}

_SUGGESTIONS: Final[dict[FailureCategory, str]] = {
    FailureCategory.CHECKOUT: (
        "Check that the branch or commit exists in the repository and has been pushed."
    ),
    FailureCategory.INFRASTRUCTURE: (
        "Ask an administrator to check the build agent, then rerun; the code may be fine."
    ),
    FailureCategory.TIMEOUT: "Look for a step that hangs or runs far longer than usual.",
    FailureCategory.TESTS: "Fix the failing test or the code it checks, then rerun the tests.",
    FailureCategory.LINT: "Fix the reported problems and push again.",
    FailureCategory.SECURITY: "Review the findings and update or replace the affected dependency.",
    FailureCategory.SCRIPT: (
        "Check that the script exists in the repository and is marked executable."
    ),
    FailureCategory.BUILD: "Fix the error quoted above and push again.",
    FailureCategory.DEPLOY: "Check the staging environment and the deploy output quoted above.",
    FailureCategory.UNKNOWN: "Open the full log from the run card to look for the cause.",
}

UNREADABLE_SUGGESTION: Final = "Rerun the job to get a fresh log."


def _join(names: tuple[str, ...]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _tests_sentence(analysis: FailureAnalysis) -> str:
    failed, passed = analysis.tests_failed, analysis.tests_passed
    if failed is not None and passed is not None:
        head = f"{failed} of {failed + passed} tests failed"
    elif failed is not None:
        head = f"{failed} test{'' if failed == 1 else 's'} failed"
    else:
        head = "Tests failed"
    if analysis.stage:
        head += f" in the {analysis.stage} stage"
    if analysis.failed_tests:
        more = len(analysis.failed_tests) - 1
        head += f": {analysis.failed_tests[0]}" + (f" and {more} more" if more else "")
    return head + "."


def rules_explanation(
    analysis: FailureAnalysis, context: FailureContext
) -> tuple[str, tuple[str, ...]]:
    """The summary and suggestions code writes from the analysis alone."""
    if not analysis.log_available:
        parts = [
            f"The log for this run cannot be read ({analysis.unavailable_reason}), so its cause "
            "cannot be shown."
        ]
        suggestions: tuple[str, ...] = (UNREADABLE_SUGGESTION,)
    else:
        if analysis.category is FailureCategory.TESTS:
            parts = [_tests_sentence(analysis)]
        else:
            parts = [_SUMMARIES[analysis.category]]
            if analysis.evidence:
                quote = analysis.evidence[0].text.strip()[:200]
                parts.append(
                    f'The log says: "{quote}"' + ("" if quote.endswith((".", "!", "?")) else ".")
                )
        suggestions = (_SUGGESTIONS[analysis.category],)
    if context.not_started:
        parts.append(
            f"Because {context.job_name} failed, {_join(context.not_started)} did not start."
        )
    if analysis.skipped_stages:
        parts.append(f"The stages after it did not run: {_join(analysis.skipped_stages)}.")
    return " ".join(parts), suggestions


def rules_answer(analysis: FailureAnalysis, context: FailureContext) -> dict[str, Any]:
    """The code's explanation in the schema's shape: the chain's last resort (``ModelChain``)."""
    summary, suggestions = rules_explanation(analysis, context)
    return {
        "cause_found": analysis.cause_found,
        "summary": summary,
        "evidence": [line.text for line in analysis.evidence[:MAX_QUOTES]],
        "suggestions": list(suggestions),
    }


# ---------------------------------------------------------------------------
# The explainer
# ---------------------------------------------------------------------------


class FailureExplainer:
    def __init__(self, chain: ModelChain, prompt: PromptTemplate) -> None:
        self._chain = chain
        self._prompt = prompt

    @property
    def prompt_version(self) -> str:
        return self._prompt.version

    @property
    def chain(self) -> ModelChain:
        return self._chain

    async def explain(
        self, analysis: FailureAnalysis, context: FailureContext
    ) -> FailureExplanation:
        if not analysis.log_available or not analysis.excerpt:
            # Nothing for a model to ground an answer in, so it is not asked.
            return self._from_rules(analysis, context, reasons=("no_log",))

        rendered = self._prompt.render(catalog="", role="")
        result = await self._chain.complete(
            schema=FAILURE_SCHEMA,
            system=rendered.system,
            messages=rendered.messages_for(render_input(analysis, context)),
            rules_fallback=lambda: rules_answer(analysis, context),
        )
        if result.parser != "llm":
            return self._from_rules(
                analysis, context, reasons=result.fallback_reasons, calls=result.calls
            )

        accepted, problem = check_answer(result.data, analysis)
        if accepted is None:
            logger.warning("failure_explanation_rejected", reason=problem, model=result.model)
            return self._from_rules(
                analysis,
                context,
                reasons=(*result.fallback_reasons, f"rejected: {problem}"),
                calls=result.calls,
                rejected=problem,
            )
        return FailureExplanation(
            summary=accepted.summary,
            evidence=accepted.evidence,
            suggestions=accepted.suggestions,
            cause_found=accepted.cause_found,
            source=Source.MODEL,
            provider=result.provider,
            model=result.model,
            ai_fallback=result.ai_fallback,
            fallback_reasons=result.fallback_reasons,
            prompt_version=self.prompt_version,
            calls=result.calls,
        )

    def _from_rules(
        self,
        analysis: FailureAnalysis,
        context: FailureContext,
        *,
        reasons: tuple[str, ...],
        calls: tuple[CallRecord, ...] = (),
        rejected: str | None = None,
    ) -> FailureExplanation:
        summary, suggestions = rules_explanation(analysis, context)
        return FailureExplanation(
            summary=summary,
            evidence=analysis.evidence,
            suggestions=suggestions,
            cause_found=analysis.cause_found,
            source=Source.RULES,
            provider="rules",
            model=None,
            # 4.7.4's fallback notice: shown whenever the model did not write what is shown.
            ai_fallback=True,
            fallback_reasons=reasons,
            prompt_version=self.prompt_version,
            calls=calls,
            rejected=rejected,
        )


# ---------------------------------------------------------------------------
# LLM_MODE=fake
# ---------------------------------------------------------------------------

_JOB_LINE = re.compile(r"^Job: (?P<name>\S+) \((?P<kind>[^)]*)\)$", re.M)


def fake_failure_responder(
    system: str, messages: list[ChatMessage], schema: dict[str, Any], model: str
) -> dict[str, Any]:
    """``LLM_MODE=fake``: the code's own explanation of the excerpt it was sent, as a model answer.

    Every quote is a line of that excerpt, so the answer passes the same checks a real one must.
    """
    text = messages[-1].content if messages else ""
    log = text.partition("<log>\n")[2].rpartition("\n</log>")[0]
    job = _JOB_LINE.search(text)
    job_type = PIPELINE if job and job.group("kind").startswith("Pipeline") else "FREESTYLE"
    lines = [line for line in log.split("\n") if line != GAP]
    analysis = analyse("\n".join(lines), job_type=job_type)
    context = FailureContext(
        job_name=job.group("name") if job else "the job", job_type=job_type, result="FAILURE"
    )
    return rules_answer(analysis, context)
