"""``RuleBasedParser``: the parser that always answers.

BUILD_PROMPT 4.5.1: ``ModelChain`` walks the models "then the rule parser". 4.9 also makes it the
evaluation's baseline. Those two roles pull in different directions, and the design follows the
first: it has to give a usable answer to any message with no network, so it is built to be safe
rather than clever.

Safe means it errs towards null. Every field it is not sure of stays null, which produces one
clarifying question (4.5.3 step 4) -- a better outcome than a confident wrong service. Its
confidence is capped below what a model typically reports, so code downstream can always tell a
rules answer apart.

It follows the rules Appendix E gives the model, wherever a rule can be expressed in code:

* quoted text, code spans and commit messages are data -- they are removed before any keyword is
  looked for, so "deploy to production" inside a commit message cannot set the environment;
* production is parsed faithfully and never rewritten to staging;
* nothing outside the catalog is ever produced -- a service the catalog lacks becomes null;
* an action word with nothing else recognisable is still that action, with null fields. Only a
  message with no action word at all is UNSUPPORTED, because a false UNSUPPORTED is a dead end
  while a null field is one question.

It never sees a model's answer and never calls anything, so it cannot be prompt-injected: an
instruction to "ignore your rules" is just more words that match no keyword.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from typing import Final

from app.ai.intent import Action, ExtraStage, Intent, TargetEnvironment, Urgency
from app.services.catalog import Catalog

# Rules never claim to be as sure as a model, so an answer can always be traced to its source.
MAX_CONFIDENCE: Final = 0.85

# Close enough to count as a typo of a catalog name. High, because a wrong service is worse than a
# question: "payment-servce" should match, "pay" should not.
TYPO_CUTOFF: Final = 0.85

# Quoted strings, `code`, ```blocks``` and "commit message: ..." tails are data (Appendix E).
# Single quotes are deliberately not treated as quotes: apostrophes ("auth-service's build",
# "don't") are far commoner, and stripping between two of them would delete the service name.
_QUOTED = re.compile(
    r'```.*?```|`[^`]*`|"[^"]*"|“[^”]*”'
    r"|\b(?:commit\s+(?:message|msg)|message\s+said|log\s+says?)\s*[:=]?\s*.*$",
    re.S | re.I,
)

_SHA = re.compile(r"\b[0-9a-f]{7,40}\b")
_BRANCH = re.compile(
    r"\b(?:from|on|off|of|at|against|using)\s+(?:the\s+)?(?:branch\s+)?"
    r"(?P<ref>[A-Za-z0-9][A-Za-z0-9._/-]*[A-Za-z0-9])\b",
    re.I,
)
_BRANCH_EXPLICIT = re.compile(r"\bbranch\s+(?P<ref>[A-Za-z0-9][A-Za-z0-9._/-]*[A-Za-z0-9])", re.I)

# Words that follow "from"/"on" without being branches.
_NOT_BRANCHES: Final = frozenset(
    {
        "staging",
        "stage",
        "production",
        "prod",
        "the",
        "it",
        "this",
        "that",
        "commit",
        "latest",
        "head",
        "my",
        "a",
        "an",
        "jenkins",
        "agent",
        "linux",
        "priority",
        "high",
        "low",
        "medium",
        "tests",
        "test",
    }
)

_HIGH = re.compile(
    r"\b(?:urgent(?:ly)?|asap|hot\s*fix|hotfix|blocking|blocker|critical|emergency"
    r"|high[\s-]priority|production\s+issue|right\s+now|immediately)\b",
    re.I,
)
_LOW = re.compile(
    r"\b(?:whenever|no\s+rush|low[\s-]priority|not\s+urgent|when\s+you\s+(?:can|get\s+a\s+chance))\b",
    re.I,
)
_MEDIUM = re.compile(r"\b(?:medium|normal)[\s-]priority\b", re.I)

# Words that mark a clause as a reason. Problem words only: domain words such as "payment" or
# "login" would also match the clause that *is* the request.
_REASON_WORDS = re.compile(
    r"\b(?:bug|bugs|broken|down|failing|fails|failed|outage|blocking|blocker|blocked|issue|issues"
    r"|incident|crash(?:ing|es)?|errors?|regression|customers?|users?|release|demo|deadline"
    r"|hot\s*fix|fix(?:es)?|security|vulnerability|cve|because|since)\b",
    re.I,
)
# A clause made only of urgency markers is not a reason.
_URGENCY_ONLY = re.compile(
    r"^(?:\s|urgent(?:ly)?|asap|high[\s-]priority|critical|emergency|right\s+now|immediately"
    r"|please|now)+$",
    re.I,
)
_CLAUSE_SPLIT = re.compile(r"[,;:]|\s+-{1,2}\s+")

_ACTIONS: Final[tuple[tuple[Action, re.Pattern[str]], ...]] = (
    # Order matters: the composite request has to win over its parts, and the run-level verbs over
    # the generic ones ("rerun the tests" is RERUN, not TEST).
    (
        Action.BUILD_TEST_DEPLOY,
        re.compile(
            r"\b(?:build,?\s+test,?\s+(?:and\s+)?(?:deploy|ship|release)"
            r"|build\s+and\s+test\s+(?:\S+\s+)?(?:and\s+|then\s+)?(?:deploy|ship|release)"
            r"|full\s+pipeline|end[\s-]to[\s-]end\s+pipeline|whole\s+pipeline)\b",
            re.I,
        ),
    ),
    (Action.CANCEL, re.compile(r"\b(?:cancel|abort|stop|kill|halt)\b", re.I)),
    (
        Action.RERUN,
        re.compile(r"\b(?:re-?run|retry|re-?trigger|run\s+(?:it\s+)?again|redo)\b", re.I),
    ),
    (
        Action.STATUS,
        re.compile(
            r"\b(?:status|state\s+of|how\s+(?:did|is|are|was)|did\s+.*\b(?:pass|fail|succeed|finish)"
            r"|progress|what\s+happened)\b",
            re.I,
        ),
    ),
    (
        Action.DEPLOY,
        re.compile(r"\b(?:deploy|ship|release|roll\s*out|promote|push\s+(?:\S+\s+)?to)\b", re.I),
    ),
    (Action.TEST, re.compile(r"\b(?:tests?|testing|test\s+suite)\b", re.I)),
    # Not "make": "make sure to ..." and "make a coffee" are not builds.
    (Action.BUILD, re.compile(r"\b(?:build|compile|re-?build|package)\b", re.I)),
)

_EXTRA_STAGES: Final[tuple[tuple[ExtraStage, re.Pattern[str]], ...]] = (
    (ExtraStage.LINT, re.compile(r"\blint(?:ing|er)?\b", re.I)),
    (ExtraStage.SECURITY_SCAN, re.compile(r"\bsecurity[\s_-]?scan(?:ning)?\b|\bsast\b", re.I)),
    (ExtraStage.SMOKE_TEST, re.compile(r"\bsmoke[\s_-]?tests?\b", re.I)),
)

_RUN_SUITE_ACTIONS: Final = frozenset({Action.TEST, Action.RERUN, Action.BUILD_TEST_DEPLOY})
_NO_STAGE_ACTIONS: Final = frozenset({Action.STATUS, Action.CANCEL, Action.UNSUPPORTED})


@dataclass(frozen=True)
class RuleParse:
    """The intent, plus which words drove it, for the evaluation's error analysis."""

    intent: Intent
    matched: tuple[str, ...]


class RuleBasedParser:
    def __init__(self, catalog: Catalog) -> None:
        self._catalog = catalog

    def parse(self, text: str) -> RuleParse:
        matched: list[str] = []
        # Data, not instruction: quoted text and commit messages never reach a keyword.
        working = _QUOTED.sub(" ", text)
        lowered = working.lower()

        action = self._action(working, matched)
        service = self._service(lowered, matched)
        environment = self._environment(lowered, matched)
        commit = self._commit(working, lowered, matched)
        branch = self._branch(working, matched)
        suite = self._suite(lowered, service, action, matched)
        urgency = self._urgency(working, matched)
        justification = self._justification(working, urgency)
        stages = list(self._extra_stages(working, action, matched))

        # In a full pipeline, "integration tests" is an extra stage; in a TEST it is the suite.
        if action is Action.BUILD_TEST_DEPLOY and re.search(r"\bintegration\s+tests?\b", lowered):
            stages.append(ExtraStage.INTEGRATION_TESTS)

        intent = Intent(
            action=action,
            service=service,
            branch=branch,
            commit=commit,
            environment=environment,
            test_suite=suite,
            urgency=urgency,
            extra_stages=tuple(dict.fromkeys(stages)),
            justification=justification,
            confidence=self._confidence(action, service, environment, suite),
        )
        return RuleParse(intent=intent, matched=tuple(matched))

    def parse_intent(self, text: str) -> Intent:
        return self.parse(text).intent

    # --- Fields -----------------------------------------------------------

    @staticmethod
    def _action(text: str, matched: list[str]) -> Action:
        for action, pattern in _ACTIONS:
            found = pattern.search(text)
            if found:
                matched.append(f"action:{found.group(0)}")
                return action
        return Action.UNSUPPORTED

    def _service(self, lowered: str, matched: list[str]) -> str | None:
        names = sorted(self._catalog.service_names(), key=len, reverse=True)
        for name in names:
            if re.search(rf"\b{re.escape(name)}\b", lowered):
                matched.append(f"service:{name}")
                return name
        # "payment" for "payment-service": the catalog's naming convention makes the stem
        # unambiguous as long as exactly one service has it.
        for name in names:
            stem = name.removesuffix("-service")
            unique = sum(1 for other in names if other.startswith(stem)) == 1
            if stem != name and unique and re.search(rf"\b{re.escape(stem)}\b", lowered):
                matched.append(f"service:{stem}~{name}")
                return name
        # Typos: only a close match to a service-looking token.
        for token in re.findall(r"\b[a-z][a-z0-9-]{3,}\b", lowered):
            close: list[str] = difflib.get_close_matches(token, names, n=1, cutoff=TYPO_CUTOFF)
            if close:
                matched.append(f"service:{token}~{close[0]}")
                return close[0]
        return None

    @staticmethod
    def _environment(lowered: str, matched: list[str]) -> TargetEnvironment | None:
        # Production first and faithfully: never rewritten to staging (Appendix E). "live" is
        # deliberately absent: "the live logs" is not a production deploy.
        if re.search(r"\b(?:production|prod)\b", lowered):
            matched.append("environment:production")
            return TargetEnvironment.PRODUCTION
        if re.search(r"\b(?:staging|stage|stg)\b", lowered):
            matched.append("environment:staging")
            return TargetEnvironment.STAGING
        return None

    @staticmethod
    def _commit(text: str, lowered: str, matched: list[str]) -> str | None:
        if re.search(r"\blatest\s+commit\b|\bhead\s+of\b|\bmost\s+recent\s+commit\b", lowered):
            matched.append("commit:latest")
            return "latest"
        for found in _SHA.finditer(text):
            value = found.group(0)
            # Both digits and letters: a run of only one is too likely to be a number or a word.
            if re.search(r"[0-9]", value) and re.search(r"[a-f]", value):
                matched.append(f"commit:{value}")
                return value
        return None

    def _branch(self, text: str, matched: list[str]) -> str | None:
        services = set(self._catalog.service_names())
        explicit = _BRANCH_EXPLICIT.search(text)
        candidates = ([explicit] if explicit else []) + list(_BRANCH.finditer(text))
        for found in candidates:
            ref = found.group("ref")
            lowered = ref.lower()
            if lowered in _NOT_BRANCHES or ref in services or lowered.endswith("-service"):
                continue
            if _SHA.fullmatch(ref):
                continue
            matched.append(f"branch:{ref}")
            return ref
        return None

    def _suite(
        self, lowered: str, service: str | None, action: Action, matched: list[str]
    ) -> str | None:
        if action not in _RUN_SUITE_ACTIONS:
            return None
        if service is not None:
            entry = self._catalog.get(service)
            suites = [suite.name for suite in entry.test_suites] if entry else []
        else:
            suites = list(self._catalog.suite_names())
        for name in sorted(suites, key=len, reverse=True):
            if re.search(rf"\b{re.escape(name)}\b", lowered):
                matched.append(f"suite:{name}")
                return name
        return None

    @staticmethod
    def _urgency(text: str, matched: list[str]) -> Urgency | None:
        if _LOW.search(text):
            matched.append("urgency:LOW")
            return Urgency.LOW
        if _HIGH.search(text):
            matched.append("urgency:HIGH")
            return Urgency.HIGH
        if _MEDIUM.search(text):
            matched.append("urgency:MEDIUM")
            return Urgency.MEDIUM
        return None

    def _justification(self, text: str, urgency: Urgency | None) -> str | None:
        """The user's own reason, only when they asked for HIGH.

        Appendix E: copy it "in their words". So this returns the whole clause that carries the
        reason -- "hotfix for login bug", not a trimmed "login bug" -- and skips the clause that is
        the request itself (it names a service) and clauses made only of urgency markers.
        """
        if urgency is not Urgency.HIGH:
            return None
        services = self._catalog.service_names()
        for clause in _CLAUSE_SPLIT.split(text):
            candidate = clause.strip(" .!?")
            if not candidate or _URGENCY_ONLY.match(candidate):
                continue
            if any(name in candidate.lower() for name in services):
                continue
            if _REASON_WORDS.search(candidate):
                return candidate
        return None

    @staticmethod
    def _extra_stages(text: str, action: Action, matched: list[str]) -> tuple[ExtraStage, ...]:
        if action in _NO_STAGE_ACTIONS:
            return ()
        stages: list[ExtraStage] = []
        for stage, pattern in _EXTRA_STAGES:
            if pattern.search(text):
                matched.append(f"stage:{stage.value}")
                stages.append(stage)
        return tuple(stages)

    @staticmethod
    def _confidence(
        action: Action,
        service: str | None,
        environment: TargetEnvironment | None,
        suite: str | None,
    ) -> float:
        if action is Action.UNSUPPORTED:
            return 0.6
        score = 0.45
        if service is not None:
            score += 0.25
        if environment is not None or action in (Action.BUILD, Action.STATUS, Action.CANCEL):
            score += 0.1
        if suite is not None:
            score += 0.05
        return round(min(MAX_CONFIDENCE, score), 2)
