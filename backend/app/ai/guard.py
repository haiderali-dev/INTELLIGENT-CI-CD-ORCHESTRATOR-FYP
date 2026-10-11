"""The message guard: BUILD_PROMPT 4.5.3 step 1.

"Reject messages over 1,000 characters; strip control characters."

Control characters here means Unicode categories ``Cc`` and ``Cf``, not just ASCII. ``Cf`` holds the
zero-width and bidirectional-override characters, which can make a message *display* differently
from what it *says* -- the "Trojan Source" trick. A message that reads "deploy to staging" on screen
but carries hidden text the model sees is exactly the gap between what a reviewer approves and what
gets parsed, so those characters are removed before anything else looks at the text. Newlines and
tabs are kept: they are ordinary whitespace in a multi-line message.

The guard also *flags* likely prompt-injection phrasing. It does not block on it -- a refusal
belongs to the policy layer, and "ignore my last message" is an innocent sentence -- but 4.6.5
requires such attempts to be logged, and that has to hold even when the injected instruction does
not happen to target production.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Final

from app.core.errors import ApiError, ErrorCode

MAX_MESSAGE_CHARS: Final = 1000

_KEPT_CONTROLS: Final = frozenset({"\n", "\t"})

_INJECTION = re.compile(
    r"\b(?:ignore|disregard|forget|override)\s+(?:all\s+|any\s+|your\s+|the\s+|my\s+|previous\s+"
    r"|prior\s+|above\s+|earlier\s+)*(?:instructions?|rules?|prompts?|guidelines|policies|policy)\b"
    r"|\byou\s+are\s+now\b"
    r"|\b(?:system|developer)\s+(?:prompt|mode|message)\b"
    r"|\bjailbreak\b"
    r"|\bact\s+as\s+(?:an?\s+)?(?:admin|administrator|root|superuser)\b"
    r"|\bno\s+restrictions\b",
    re.I,
)


@dataclass(frozen=True)
class GuardResult:
    text: str
    removed_characters: int
    injection_suspected: bool


class MessageTooLongError(ApiError):
    def __init__(self, length: int) -> None:
        super().__init__(
            ErrorCode.MESSAGE_TOO_LONG,
            f"Messages are limited to {MAX_MESSAGE_CHARS} characters; this one has {length}. "
            "Describe the request in a sentence or two.",
            status_code=400,
            details={"limit": MAX_MESSAGE_CHARS, "length": length},
        )


def strip_controls(text: str) -> tuple[str, int]:
    """Remove Unicode control and format characters, keeping newlines and tabs."""
    kept = [
        char
        for char in text
        if char in _KEPT_CONTROLS or unicodedata.category(char) not in ("Cc", "Cf")
    ]
    return "".join(kept), len(text) - len(kept)


def guard_message(text: str) -> GuardResult:
    """Clean a message and decide whether it may be parsed.

    The length limit is applied *after* stripping, so a message padded with invisible characters
    is measured by what it actually says -- and before anything is sent to a model, so an
    oversized message costs no quota.
    """
    cleaned, removed = strip_controls(text)
    cleaned = cleaned.strip()
    if len(cleaned) > MAX_MESSAGE_CHARS:
        raise MessageTooLongError(len(cleaned))
    if not cleaned:
        raise ApiError(ErrorCode.BAD_REQUEST, "The message is empty.", status_code=400, details={})
    return GuardResult(
        text=cleaned,
        removed_characters=removed,
        injection_suspected=bool(_INJECTION.search(cleaned)),
    )
