"""T8.5: the demo script, step by step, with every model answer replayed from a fixture.

Marked ``e2e``: it runs on the Compose stack through T5.8's harness (``tests/e2e_support.py``).
The steps are read from ``docs/demo-script.md`` itself, so what the presenter reads and what this
checks cannot differ.

In replay mode, the default without a key and what ``verify.py`` pins, every parse and every plan
must come from a recorded fixture. That is the acceptance's "no internet access for the LLM".
Steps whose next action is to approve are approved and run on ``jenkins-dev``, because later steps
need their runs: the status of the last deploy, and the failed tests to rerun.
"""

from __future__ import annotations

import re
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from app.db.models import Role
from tests import e2e_support as e2e
from tests.e2e_support import Stack

pytestmark = pytest.mark.e2e

SCRIPT = Path(__file__).resolve().parents[2] / "docs" / "demo-script.md"
ROLES = {"Developer": Role.DEVELOPER, "DevOps": Role.DEVOPS, "Admin": Role.ADMIN}
ASSISTANTS = {"Freestyle": "freestyle", "Pipeline": "pipeline"}
ANSWERS = ("READY", "REFUSED", "STATUS", "RERUN")


@dataclass(frozen=True)
class Step:
    number: int
    role: Role
    assistant: str
    messages: tuple[str, ...]
    answer: str
    then: str

    @property
    def approve(self) -> bool:
        return self.answer == "READY" and "approve" in self.then.lower()

    @property
    def expected_result(self) -> str:
        return "FAILURE" if "fail" in self.then.lower() else "SUCCESS"


def script_steps() -> list[Step]:
    """The table under "## 3. The script", one Step a row."""
    text = SCRIPT.read_text(encoding="utf-8")
    section = text.split("## 3. The script", 1)[1].split("\n## ", 1)[0]
    steps = []
    for line in section.splitlines():
        if not re.match(r"^\|\s*\d+\s*\|", line):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        steps.append(
            Step(
                number=int(cells[0]),
                role=ROLES[cells[1]],
                assistant=ASSISTANTS[cells[2]],
                messages=tuple(re.findall(r"`([^`]+)`", cells[3])),
                answer=cells[4],
                then=cells[5],
            )
        )
    return steps


def test_the_script_is_well_formed() -> None:
    """Every row names an account, an assistant, its messages and an answer the test can check."""
    steps = script_steps()

    assert [step.number for step in steps] == list(range(1, len(steps) + 1))
    assert all(step.messages for step in steps)
    assert all(step.answer in ANSWERS for step in steps)
    assert {step.assistant for step in steps} == {"freestyle", "pipeline"}


@pytest.fixture(scope="session")
def e2e_database() -> None:
    env = e2e.read_env()
    if not env.get("JENKINS_TOKEN") or not env.get("POSTGRES_PASSWORD"):
        pytest.skip("the Compose stack's credentials are not in .env")
    try:
        e2e.recreate_database()
    except OSError as exc:
        pytest.skip(f"the stack's PostgreSQL is not reachable: {exc}")


@pytest.fixture
async def stack(e2e_database: None) -> AsyncGenerator[Stack]:
    async for running in e2e.stack():
        try:
            await running.jenkins.version()
        except Exception as exc:
            pytest.skip(f"jenkins-dev is not reachable: {exc}")
        yield running


def check_answer(step: Step, body: dict[str, Any]) -> None:
    command = body["command"]
    payload = body["assistant_message"].get("payload") or {}
    content = body["assistant_message"]["content"]
    if step.answer == "READY":
        assert command["disposition"] == "READY", f"step {step.number}: {content}"
    elif step.answer == "REFUSED":
        assert command["status"] == "REFUSED", f"step {step.number}: {content}"
    elif step.answer == "STATUS":
        assert payload.get("kind") == "status", f"step {step.number}: {content}"
    else:
        assert payload.get("kind") == "run", f"step {step.number}: {content}"


async def test_the_demo_script_runs_with_every_answer_replayed(stack: Stack) -> None:
    headers: dict[Role, dict[str, str]] = {}
    for step in script_steps():
        if step.role not in headers:
            headers[step.role] = await e2e.sign_in(stack, step.role)
        account = headers[step.role]
        chat = await e2e.new_chat(stack, account, step.assistant)
        body: dict[str, Any] = {}
        for message in step.messages:
            # In replay mode e2e.say fails the test when a parse did not come from a fixture.
            body = await e2e.say(stack, account, chat, message)
        check_answer(step, body)
        if not step.approve:
            continue

        pipeline = await e2e.generate(stack, account, body["command"]["id"])
        assert pipeline["status"] == "VALIDATED", f"step {step.number}: {pipeline['progress']}"
        approval = await e2e.approve(stack, account, pipeline["id"])
        card = await e2e.wait_for_chain(stack, account, approval["chain_id"])
        assert card["status"] == step.expected_result, f"step {step.number}: {card}"
        if step.expected_result == "FAILURE":
            # The script's "Explain failure", on the run card's failed run.
            explained = await stack.client.post(
                f"/api/runs/{card['failed_run_id']}/explain", headers=account
            )
            assert explained.status_code == 200, explained.text
