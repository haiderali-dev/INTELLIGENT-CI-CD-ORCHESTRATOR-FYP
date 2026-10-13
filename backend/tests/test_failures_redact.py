"""T5.9: what a build log must not carry to the model provider or back to the browser."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from app.failures.redact import EMAIL_MASK, MASK, MAX_LINE_CHARS, TRUNCATED, redact

LOGS = Path(__file__).parent / "data" / "failure_logs"


@pytest.mark.parametrize(
    "secret",
    [
        "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8",  # GitHub
        "github_pat_" + "11ABCDEFG0123456789_abcdefghijklmnop",  # GitHub fine-grained
        "gsk_" + "abcdefghijklmnopqrstuvwxyz0123456789",  # Groq
        "sk-" + "proj-abcdefghijklmnopqrstuvwxyz012345",  # OpenAI-style
        "AKIA" + "ABCDEFGHIJKLMNOP",  # AWS access key id
        "xoxb-" + "123456789012-abcdefghijkl",  # Slack
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyIn0.c2lnbmF0dXJlLXZhbHVl",  # JWT
        "11" + "0123456789abcdef0123456789abcdef",  # Jenkins API token
    ],
)
def test_a_known_token_format_is_masked_wherever_it_appears(secret: str) -> None:
    redacted = redact(f"+ curl -s https://example.test/api?x={secret} -o out.json\n")

    assert secret not in redacted.text
    assert MASK in redacted.text
    assert redacted.count >= 1


def test_a_configured_secret_is_masked_by_value() -> None:
    redacted = redact(
        "connecting with test-token-value-123 to jenkins\n", known_secrets=["test-token-value-123"]
    )

    assert redacted.text == f"connecting with {MASK} to jenkins\n"
    assert redacted.count == 1


def test_a_short_configured_secret_is_not_searched_for() -> None:
    """A four-letter "secret" would mask every word that contains it."""
    redacted = redact("the build failed\n", known_secrets=["fail"])

    assert redacted.text == "the build failed\n"


def test_credentials_in_a_clone_url_are_masked() -> None:
    redacted = redact(
        "Fetching upstream changes from https://bot:hunter2hunter2@github.com/org/repo.git\n"
    )

    assert "hunter2" not in redacted.text
    assert f"https://{MASK}@github.com/org/repo.git" in redacted.text


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("Authorization: Bearer abc.def.ghijklmnop", f"Authorization: Bearer {MASK}"),
        ("authorization=Basic dXNlcjpwYXNz", f"authorization=Basic {MASK}"),
        ("> GET / with Bearer abcdefghijklmnop", f"> GET / with Bearer {MASK}"),
        ("+ export DB_PASSWORD=hunter2hunter2", f"+ export DB_PASSWORD={MASK}"),
        ("api_key: 'abcdefghi'", f"api_key: {MASK}"),
        ('client_secret="s3cr3t value"', f"client_secret={MASK}"),
        ("Author: Jane Doe <jane.doe@example.com>", f"Author: Jane Doe <{EMAIL_MASK}>"),
        # Credentials on a command line, the commonest way a build prints one by accident.
        (
            "+ curl -u bot:hunter2hunter2 https://x.test/api",
            f"+ curl -u bot:{MASK} https://x.test/api",
        ),
        (
            "+ curl --user=bot:s3cretvalue https://x.test",
            f"+ curl --user=bot:{MASK} https://x.test",
        ),
        (
            "+ docker login --password s3cretvalue --username bot",
            f"+ docker login --password {MASK} --username bot",
        ),
        ("+ tool --api-key abcdef123456 run", f"+ tool --api-key {MASK} run"),
    ],
)
def test_secret_shaped_values_are_masked(line: str, expected: str) -> None:
    assert redact(line).text == expected


@pytest.mark.parametrize(
    "line",
    [
        "E       assert token == expected_token",  # a comparison, not an assignment
        "+ PWD=/home/jenkins/agent/workspace/fs-payment-service-build",  # the working directory
        "No credentials specified",
        "Cloning repository https://github.com/haiderali-dev/payment-service.git",
        "Fetching upstream changes from git@github.com:org/repo.git",  # an SSH remote, not a person
        "added react@18.3.1 and lodash@4.17.21",  # package pins, not addresses
        "+ git push -u origin main",  # -u without a user:secret pair
        "+ sort -u names.txt",
        "+ docker login --password-stdin --username bot",  # the flag, with no value on the line
        "✔ login issues a token (854.48993ms)",
        "Checking out Revision da997c8be894b8058c9c88068295964b81f2d846",  # a SHA is not a secret
    ],
)
def test_ordinary_log_lines_are_left_alone(line: str) -> None:
    redacted = redact(line)

    assert redacted.text == line
    assert redacted.count == 0


@pytest.mark.parametrize("name", sorted(path.name for path in LOGS.glob("*.log")))
def test_the_captured_logs_pass_through_unchanged(name: str) -> None:
    """Real jenkins-dev logs hold no secrets, so redaction must not change a character of them."""
    text = (LOGS / name).read_text(encoding="utf-8")

    redacted = redact(text)

    assert redacted.text == text
    assert redacted.count == 0


def test_a_private_key_is_masked_without_moving_any_line() -> None:
    text = (
        "before\n-----BEGIN RSA PRIVATE KEY-----\nMIIEow\nIBAAKC\n-----END RSA PRIVATE KEY-----\n"
        "after\n"
    )

    redacted = redact(text)

    lines = redacted.text.split("\n")
    assert len(lines) == len(text.split("\n")), "line numbers still point at the same lines"
    assert lines[0] == "before"
    assert lines[5] == "after"
    assert "MIIEow" not in redacted.text
    assert all(line == MASK for line in lines[1:5])


def test_redaction_never_changes_the_number_of_lines() -> None:
    text = "a=1\npassword: x1y2z3\n\nhttps://u:p4ssword@host/x\ntoken=abc\n"

    assert redact(text).text.count("\n") == text.count("\n")


def test_a_very_long_line_is_cut() -> None:
    redacted = redact("x" * (MAX_LINE_CHARS * 3))

    assert redacted.text == "x" * MAX_LINE_CHARS + TRUNCATED


def test_a_token_straddling_the_cut_is_masked_whole() -> None:
    """Token formats are matched before lines are cut, so no prefix is left behind."""
    token = "ghp_" + "Z" * 40
    line = "y" * (MAX_LINE_CHARS - 11) + "=" + token  # the cut falls inside the token

    redacted = redact(line)

    assert "ghp_" not in redacted.text


def test_a_hostile_log_is_redacted_in_linear_time() -> None:
    """The log is written by whoever pushed the commit: a pathological line must not stall a request.

    Long runs of word characters split by dots and dashes are what make an unbounded pattern
    backtrack; this is a megabyte of them, on many lines and on one.
    """
    hostile_line = "a.b-c" * 400  # many word boundaries, no separator to end a match
    text = "\n".join([hostile_line] * 500) + "\n" + "token" + "a.b-" * 250_000

    started = time.perf_counter()
    redact(text)
    elapsed = time.perf_counter() - started

    assert elapsed < 5.0, f"took {elapsed:.1f}s"
