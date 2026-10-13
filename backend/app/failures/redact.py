"""What a build log must not carry to the model provider or back to the browser.

Explaining a failure sends an excerpt of a build log to Groq, a third party, and returns quoted
lines to the user. A log holds whatever the build printed, and builds print secrets by accident:
a ``set -x`` trace of an ``export``, a clone URL with a token in it, a failed HTTP call that dumps
its ``Authorization`` header. Jenkins masks the credentials it binds itself, and nothing else.

``redact`` runs before anything else reads the text. The rules analysis, the model and the
response all work from its output, so no later step can leak what it removed. It errs towards
removing: a hidden value costs a little diagnosis, and a leaked one cannot be taken back.

Two properties are kept deliberately:

* **One line in, one line out.** Line numbers in an explanation point at the same lines in
  Jenkins's own log, so a multi-line private key is masked line by line.
* **Linear time.** The log is written by whoever pushed the commit, so a pathological line must
  not stall the endpoint. Lines are capped at ``MAX_LINE_CHARS``, every unbounded run in a pattern
  is either led by a literal or bounded, and the costlier patterns only see lines that contain
  their keyword.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Final

MASK: Final = "****"
EMAIL_MASK: Final = "<email>"

# A configured secret shorter than this is not searched for: it would match all over a log.
MIN_KNOWN_SECRET: Final = 8

# Longer lines are cut. Nothing that long is read by a person or quoted in an explanation, and the
# cap is what keeps every pattern below cheap on a hostile log.
MAX_LINE_CHARS: Final = 2000
TRUNCATED: Final = " [line truncated]"

# A private key block, masked line by line so the line count does not change.
_PEM = re.compile(
    r"-----BEGIN (?P<kind>[A-Z ]{0,40}PRIVATE KEY)-----.*?(?:-----END (?P=kind)-----|\Z)", re.S
)

# Token formats that are secrets wherever they appear. Each alternative starts with a literal, so
# the scan is linear.
_TOKENS = re.compile(
    r"\b(?:"
    r"gh[pousr]_[A-Za-z0-9]{20,}"  # GitHub tokens
    r"|github_pat_[A-Za-z0-9_]{20,}"  # GitHub fine-grained tokens
    r"|gsk_[A-Za-z0-9]{20,}"  # Groq keys
    r"|sk-[A-Za-z0-9_-]{20,}"  # OpenAI-style keys
    r"|(?:AKIA|ASIA)[0-9A-Z]{16}"  # AWS access key ids
    r"|xox[abprs]-[A-Za-z0-9-]{10,}"  # Slack tokens
    r"|eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"  # JWTs
    r"|11[0-9a-f]{32}"  # Jenkins API tokens: 34 hex digits starting 11
    r")\b"
)

# scheme://user:password@host -- the form a token takes in a clone URL.
_URL_CREDENTIALS = re.compile(
    r"(?P<scheme>\b[A-Za-z][A-Za-z0-9+.-]{0,15}://)[^/\s:@]{1,256}:[^/\s@]{1,256}@"
)

# "Authorization: Bearer abc", "authorization=Basic abc", and a bare "Bearer abc".
_AUTH_HEADER = re.compile(
    r"(?i)(?P<head>\bauthorization[ \t]*[:=][ \t]*)(?:(?P<kind>bearer|basic|token)[ \t]+)?[^\s,;]+"
)
_BEARER = re.compile(r"(?i)\b(?P<kind>bearer)[ \t]+(?!\*{4})[A-Za-z0-9._~+/=-]{8,}")

# NAME=value and name: value where the name says it is a secret. "==" and "::" are comparisons
# and paths, not assignments, so `assert token == expected` keeps its meaning. PWD is left alone:
# in a shell trace it is the working directory, not a password.
_ASSIGNMENT = re.compile(
    r"(?i)(?P<name>\b[A-Za-z0-9_.-]{0,40}(?:password|passwd|secret|token|api[_-]?key"
    r"|access[_-]?key|private[_-]?key|credentials?)[A-Za-z0-9_.-]{0,40})"
    r"(?P<sep>[ \t]*(?:=(?!=)|:(?![:/]))[ \t]*)"
    r"(?!\*{4})(?P<value>\"[^\"\n]{0,512}\"|'[^'\n]{0,512}'|[^\s\"']+)"
)
_ASSIGNMENT_HINTS: Final = ("pass", "secret", "token", "key", "credential")

# Personal data rather than a credential, but it has no place in a third party's prompt either.
# git@host is an SSH remote, not a person, and the alphabetic last label keeps a package pin such
# as react@18.3.1 out.
_EMAIL = re.compile(
    r"\b(?!git@)[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63})*\.[A-Za-z]{2,24}\b"
)

Replacement = str | Callable[[re.Match[str]], str]


@dataclass(frozen=True)
class Redacted:
    text: str
    count: int


def redact(text: str, known_secrets: Iterable[str] = ()) -> Redacted:
    """``text`` with secrets masked, and how many values were masked."""
    count = 0

    def apply(pattern: re.Pattern[str], replacement: Replacement, value: str) -> str:
        nonlocal count
        result, found = pattern.subn(replacement, value)
        count += found
        return result

    # The configured secrets first, longest first, so one that contains another is masked whole.
    secrets = sorted(
        {s for s in known_secrets if len(s) >= MIN_KNOWN_SECRET}, key=len, reverse=True
    )
    for secret in secrets:
        found = text.count(secret)
        if found:
            text = text.replace(secret, MASK)
            count += found

    # Whole-text patterns, before any line is cut: a token straddling the cut would otherwise leave
    # its first characters behind.
    text = apply(_PEM, _mask_lines, text)
    text = apply(_TOKENS, MASK, text)

    lines = []
    for line in text.split("\n"):
        if len(line) > MAX_LINE_CHARS:
            line = line[:MAX_LINE_CHARS] + TRUNCATED
        lower = line.lower()
        if "://" in line:
            line = apply(_URL_CREDENTIALS, _mask_url, line)
        if "authorization" in lower:
            line = apply(_AUTH_HEADER, _mask_header, line)
        if "bearer" in lower:
            line = apply(_BEARER, lambda m: f"{m.group('kind')} {MASK}", line)
        if any(hint in lower for hint in _ASSIGNMENT_HINTS):
            line = apply(_ASSIGNMENT, lambda m: f"{m.group('name')}{m.group('sep')}{MASK}", line)
        if "@" in line:
            line = apply(_EMAIL, EMAIL_MASK, line)
        lines.append(line)
    return Redacted(text="\n".join(lines), count=count)


def _mask_lines(match: re.Match[str]) -> str:
    return "\n".join(MASK for _ in match.group(0).split("\n"))


def _mask_url(match: re.Match[str]) -> str:
    return f"{match.group('scheme')}{MASK}@"


def _mask_header(match: re.Match[str]) -> str:
    kind = match.group("kind")
    return f"{match.group('head')}{kind + ' ' if kind else ''}{MASK}"
