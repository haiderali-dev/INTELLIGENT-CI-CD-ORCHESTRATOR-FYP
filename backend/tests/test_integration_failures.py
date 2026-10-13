"""T5.9 against a live ``jenkins-dev``: a real failing test job, its real log, the real analysis.

Marked ``integration``:

    uv run python -m pytest -m integration tests/test_integration_failures.py

The generator's payment-service test job runs twice on ``demo/failing-tests``, under an ``it-``
name (the bot cannot delete jobs, so integration tests recreate theirs: D-033). Both runs fail on
the branch's intentional assertion. The analysis must:

* recognise the failure, name the test and count the results, with every quoted line numbered as
  Jenkins numbers it;
* give the two runs the same excerpt -- the property a recorded model answer depends on to replay
  (T5.8), shown here on two real logs rather than on one edited by hand;
* hold up under the explainer's checks with an answer that quotes the real log.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path

import pytest

from app.ai.intent import Action, Intent, Urgency
from app.ai.providers.base import ChatMessage
from app.core.settings import Environment, Settings
from app.failures.analysis import FailureAnalysis, FailureCategory, analyse
from app.failures.explainer import (
    FAILURE_SCHEMA,
    FailureContext,
    check_answer,
    fake_failure_responder,
    render_input,
)
from app.generation.revision import select_revision
from app.generation.spec import Assistant
from app.services.catalog import Catalog
from app.services.jenkins import HttpJenkinsClient, JenkinsError
from tests.test_integration_generation import generated
from tests.test_integration_jenkins import (
    read_env,
    recreate,
    wait_for_build,
    wait_for_complete_log,
    wait_for_finish,
)

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]
JOB = "it-failure-payment-service-test-unit"
FAILING_TEST = "tests/test_unit.py::test_demo_failing_tests_fails_on_purpose"


@pytest.fixture(scope="module")
def live_settings() -> Settings:
    env = read_env()
    if not env.get("JENKINS_USER") or not env.get("JENKINS_TOKEN"):
        pytest.skip("JENKINS_USER and JENKINS_TOKEN are not configured; see .env.example")
    return Settings(
        environment=Environment.TEST,
        database_url="sqlite+aiosqlite:///:memory:",
        jenkins_url=env.get("JENKINS_URL_HOST", "http://localhost:8087"),
        jenkins_user=env["JENKINS_USER"],
        jenkins_token=env["JENKINS_TOKEN"],
    )


@pytest.fixture
async def jenkins(live_settings: Settings) -> AsyncGenerator[HttpJenkinsClient]:
    client = HttpJenkinsClient(live_settings)
    try:
        await client.version()
    except JenkinsError as exc:
        await client.aclose()
        pytest.skip(f"jenkins-dev is not reachable: {exc}")
    yield client
    await client.aclose()


async def run_on_the_failing_branch(jenkins: HttpJenkinsClient) -> tuple[int, str, str]:
    """One build of ``JOB`` on demo/failing-tests: its number, result and whole log."""
    revision = select_revision(None, "demo/failing-tests")
    queue_item = await jenkins.trigger(JOB, revision.parameters())
    number = await wait_for_build(jenkins, JOB, queue_item)
    result = await wait_for_finish(jenkins, JOB, number)
    return number, result, await wait_for_complete_log(jenkins, JOB, number)


async def test_a_real_failing_test_job_is_explained_from_its_real_log(
    jenkins: HttpJenkinsClient, live_settings: Settings
) -> None:
    catalog = Catalog(REPO_ROOT / "catalog" / "services.yaml")
    service = catalog.require("payment-service")
    intent = Intent(
        action=Action.TEST, service=service.name, test_suite="unit", urgency=Urgency.MEDIUM
    )
    _, artifact = generated(catalog, service, intent, Assistant.FREESTYLE)
    # Build, then the test job, which builds again in its own workspace before testing (D-043).
    job = artifact.jobs[-1]
    assert job.stage is not None and job.stage.template == "test"
    await recreate(jenkins, JOB, job.config_xml)

    analyses: list[FailureAnalysis] = []
    for _ in range(2):
        number, result, text = await run_on_the_failing_branch(jenkins)
        assert result == "FAILURE", f"{JOB}#{number}: the branch's test should fail"
        analysis = analyse(
            text,
            job_type="FREESTYLE",
            stage=job.stage.name,
            stage_template=job.stage.template,
            known_secrets=(live_settings.jenkins_token,),
        )
        assert analysis.category is FailureCategory.TESTS
        assert analysis.failed_tests == (FAILING_TEST,)
        assert (analysis.tests_failed, analysis.tests_passed) == (1, 7)
        assert analysis.log_complete
        printed = text.split("\n")
        for line in analysis.evidence:
            assert printed[line.number - 1].rstrip() == line.text, f"{JOB}#{number}"
        assert live_settings.jenkins_token not in repr(analysis)
        analyses.append(analysis)

    first, second = analyses
    context = FailureContext(
        job_name=JOB, job_type="FREESTYLE", result="FAILURE", service=service.name
    )
    assert render_input(first, context) == render_input(second, context), (
        "two runs of the same failure must be the same prompt, or a recording never replays"
    )

    message = ChatMessage(role="user", content=render_input(first, context))
    data = fake_failure_responder("", [message], FAILURE_SCHEMA, "fake")
    accepted, problem = check_answer(data, first)
    assert accepted is not None, problem
