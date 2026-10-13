"""The revision rule both assistants share (D-041), and the reference configs that carry it.

The rule, in order: a given commit is checked out exactly; otherwise the head of the given branch;
otherwise ``main``. A value that was given but is invalid is an error, never a fallback.

The second half reads the exported reference configs, because the Jinja2 templates derive from them
(rule 1.4). If an export ever drops the parameters or the rule, these fail before a template is
built on top of it. What Jenkins actually checks out is tested live in
``test_integration_revision.py``.
"""

from __future__ import annotations

import html
import re
from pathlib import Path
from xml.etree import ElementTree

import pytest

from app.generation.revision import (
    DEFAULT_BRANCH,
    Revision,
    RevisionError,
    RevisionSource,
    select_revision,
)
from app.services.git import REF_PATTERN

SHA = "3f9c2ab"
FULL_SHA = "da997c8be894b8058c9c88068295964b81f2d846"

REFERENCE_DIR = Path(__file__).resolve().parents[2] / "jenkins" / "reference-configs"


# ---------------------------------------------------------------------------
# The rule
# ---------------------------------------------------------------------------


def test_a_commit_wins_over_the_branch() -> None:
    revision = select_revision(FULL_SHA, "main")

    assert revision == Revision(RevisionSource.COMMIT, "main", FULL_SHA)
    assert revision.checkout == FULL_SHA
    assert revision.parameters() == {"BRANCH": "main", "COMMIT": FULL_SHA}


def test_a_commit_alone_belongs_to_the_default_branch() -> None:
    revision = select_revision(SHA, None)

    assert revision.source is RevisionSource.COMMIT
    assert revision.checkout == SHA
    assert revision.branch == DEFAULT_BRANCH


def test_without_a_commit_the_branch_head_is_checked_out() -> None:
    revision = select_revision(None, "feature/refund")

    assert revision == Revision(RevisionSource.BRANCH, "feature/refund")
    # A fully qualified ref: a branch name can never be read as a SHA or a tag, and a branch that
    # does not exist fails the checkout instead of matching something else.
    assert revision.checkout == "refs/heads/feature/refund"
    assert revision.parameters() == {
        "BRANCH": "feature/refund",
        "COMMIT": "refs/heads/feature/refund",
    }


def test_with_neither_the_head_of_main_is_checked_out() -> None:
    revision = select_revision(None, None)

    assert revision == Revision(RevisionSource.DEFAULT, "main")
    assert revision.checkout == "refs/heads/main"
    assert DEFAULT_BRANCH == "main"


@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
def test_a_blank_value_counts_as_not_given(blank: str) -> None:
    """Jenkins trims parameters. A blank COMMIT handed to the Git plugin is an empty branch spec,
    which it reads as "any branch": measured building demo/failing-tests (D-041)."""
    assert select_revision(blank, blank).source is RevisionSource.DEFAULT
    assert select_revision(blank, "develop").checkout == "refs/heads/develop"
    assert select_revision(SHA, blank).checkout == SHA


def test_values_are_trimmed_and_a_sha_is_lowercased() -> None:
    revision = select_revision("  3F9C2AB ", "  release/1.2 ")

    assert revision.commit == "3f9c2ab"
    assert revision.branch == "release/1.2"


def test_a_fully_qualified_branch_is_accepted_once() -> None:
    """A user may paste refs/heads/x. It must not become refs/heads/refs/heads/x."""
    assert select_revision(None, "refs/heads/develop").checkout == "refs/heads/develop"


def test_the_never_empty_guarantee() -> None:
    """Whatever comes in, what reaches Jenkins is never an empty spec."""
    for commit in (None, "", SHA):
        for branch in (None, "", "develop"):
            assert select_revision(commit, branch).checkout


# --- invalid values are errors, never a fallback -----------------------------------------------


@pytest.mark.parametrize(
    "commit",
    ["latest", "abc", "3f9c2a", "g3f9c2ab", "3f9c2ab;rm -rf /", FULL_SHA + "0", "main"],
)
def test_an_invalid_commit_is_an_error(commit: str) -> None:
    with pytest.raises(RevisionError) as raised:
        select_revision(commit, "main")

    assert raised.value.field == "commit"
    assert raised.value.value == commit


@pytest.mark.parametrize(
    "branch",
    ["-rf", "feature..x", "release/", "bad branch", "a;b", "$(id)", "x" * 256, "refs/heads/"],
)
def test_an_invalid_branch_is_an_error(branch: str) -> None:
    with pytest.raises(RevisionError) as raised:
        select_revision(None, branch)

    assert raised.value.field == "branch"


def test_a_valid_commit_does_not_excuse_an_invalid_branch() -> None:
    """The branch is still written into the job and shown, so it must be valid too."""
    with pytest.raises(RevisionError) as raised:
        select_revision(SHA, "bad branch")

    assert raised.value.field == "branch"


def test_an_invalid_commit_never_falls_back_to_the_branch() -> None:
    """Rule 4. The tempting bug: ignore a bad commit and build the branch head instead."""
    with pytest.raises(RevisionError):
        select_revision("not-a-sha", "main")


# ---------------------------------------------------------------------------
# Parity: the reference configs both job types are rendered from
# ---------------------------------------------------------------------------


def _parameters(config_xml: str) -> dict[str, tuple[str, str]]:
    """name -> (description, default) from a config.xml's ParametersDefinitionProperty."""
    body = config_xml.split("?>", 1)[1]
    root = ElementTree.fromstring(body)
    found: dict[str, tuple[str, str]] = {}
    for definition in root.iter("hudson.model.StringParameterDefinition"):
        name = definition.findtext("name") or ""
        found[name] = (
            definition.findtext("description") or "",
            definition.findtext("defaultValue") or "",
        )
        assert definition.findtext("trim") == "true", f"{name} must be trimmed, like the rule does"
    return found


@pytest.fixture(scope="module")
def freestyle_xml() -> str:
    return (REFERENCE_DIR / "freestyle-build-test-deploy.config.xml").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def pipeline_xml() -> str:
    return (REFERENCE_DIR / "pipeline-build-test-deploy.config.xml").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def jenkinsfile(pipeline_xml: str) -> str:
    root = ElementTree.fromstring(pipeline_xml.split("?>", 1)[1])
    definition = root.find("definition")
    assert definition is not None
    return html.unescape(definition.findtext("script") or "")


def test_both_job_types_declare_the_same_two_parameters(
    freestyle_xml: str, pipeline_xml: str
) -> None:
    freestyle = _parameters(freestyle_xml)
    pipeline = _parameters(pipeline_xml)

    assert set(freestyle) == set(pipeline) == {"BRANCH", "COMMIT"}
    for name in ("BRANCH", "COMMIT"):
        assert freestyle[name][0] == pipeline[name][0], f"{name} is described differently"


def test_the_pipeline_declares_its_parameters_in_config_xml(pipeline_xml: str) -> None:
    """D-034: otherwise a new job refuses parameters, and every regenerate wipes them."""
    assert "<properties/>" not in pipeline_xml
    assert "hudson.model.ParametersDefinitionProperty" in pipeline_xml


def test_the_jenkinsfile_parameters_match_config_xml(pipeline_xml: str, jenkinsfile: str) -> None:
    """If they differed, the first run would rewrite the job's parameters to the script's."""
    declared = {
        name: (description, default)
        for name, default, description in re.findall(
            r"string\(name: '(\w+)', defaultValue: '([^']*)', description: '([^']*)'\)", jenkinsfile
        )
    }

    assert declared == _parameters(pipeline_xml)


def test_freestyle_checks_out_commit_and_defaults_to_the_rule(freestyle_xml: str) -> None:
    """The Git plugin follows one variable, so COMMIT carries the revision the backend chose. Its
    default is the rule's third clause, never empty."""
    assert "<name>${COMMIT}</name>" in freestyle_xml
    assert _parameters(freestyle_xml)["COMMIT"][1] == select_revision(None, None).checkout
    assert _parameters(freestyle_xml)["BRANCH"][1] == DEFAULT_BRANCH


def test_the_pipeline_applies_the_same_rule_and_validation(jenkinsfile: str) -> None:
    """The Jenkinsfile holds a run started by hand to the rule, with the backend's own patterns."""
    assert "params.COMMIT ?: params.BRANCH" not in jenkinsfile, "the old rule had no main default"
    assert "commit ?: ('refs/heads/' + (branch ?: 'main'))" in jenkinsfile
    branch_pattern = REF_PATTERN.pattern.removeprefix("^").removesuffix("$")
    assert f"branch.matches('{branch_pattern}')" in jenkinsfile
    assert f"revision.matches('refs/heads/{branch_pattern}')" in jenkinsfile
    assert "revision.matches('[0-9a-fA-F]{7,40}')" in jenkinsfile
    assert "branches: [[name: revision]]" in jenkinsfile
    assert jenkinsfile.count("error(") == 2, "an invalid BRANCH and an invalid COMMIT both stop it"


def test_the_pipeline_default_leaves_the_rule_to_the_jenkinsfile(pipeline_xml: str) -> None:
    """COMMIT defaults to empty so that a run by hand with only BRANCH changed builds BRANCH."""
    assert _parameters(pipeline_xml)["COMMIT"][1] == ""
    assert _parameters(pipeline_xml)["BRANCH"][1] == DEFAULT_BRANCH
