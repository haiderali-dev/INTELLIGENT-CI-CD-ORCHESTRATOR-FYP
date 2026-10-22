"""Rendered jobs are the reference exports with the workload's values, element for element."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import pytest

from experiment import templates, workload

REPO_ROOT = Path(__file__).resolve().parents[2]
REFERENCES = REPO_ROOT / "jenkins" / "reference-configs"
PROPERTY = "io.jenkins.plugins.queueoptimizer.property.JobPriorityProperty"


def shape(element: ET.Element) -> tuple[Any, ...]:
    """An element's tag, attributes and children's shapes: the structure, without the text."""
    return (element.tag, sorted(element.attrib.items()), [shape(child) for child in element])


def parse(xml: str) -> ET.Element:
    return ET.fromstring(xml.encode("utf-8"))  # noqa: S314 - our own rendered output


def pipeline_script(job: ET.Element) -> str:
    """A Pipeline job's Groovy, from its definition element."""
    definition = job.find("definition")
    assert definition is not None
    return definition.findtext("script") or ""


def reference(name: str) -> ET.Element:
    return ET.parse(REFERENCES / name).getroot()  # noqa: S314 - Jenkins' own export, in the repo


def test_a_freestyle_job_has_the_reference_exports_structure() -> None:
    fs30 = workload.load("freestyle-30")
    rendered = parse(templates.render(fs30, fs30.job("deploy-auth-service")))
    assert shape(rendered) == shape(reference("freestyle-downstream.config.xml"))


def test_a_pipeline_job_has_the_reference_structure_without_its_parameters() -> None:
    pl30 = workload.load("pipeline-30")
    rendered = parse(templates.render(pl30, pl30.job("deploy-auth-service")))
    expected = reference("pipeline-build-test-deploy.config.xml")
    properties = expected.find("properties")
    assert properties is not None
    parameters = properties.find("hudson.model.ParametersDefinitionProperty")
    assert parameters is not None
    properties.remove(parameters)
    assert shape(rendered) == shape(expected)


def test_a_freestyle_job_carries_its_band_upstreams_and_sleep() -> None:
    fs30 = workload.load("freestyle-30")
    job = parse(templates.render(fs30, fs30.job("deploy-auth-service")))
    assert job.findtext(f"properties/{PROPERTY}/level") == "HIGH"
    assert job.findtext(f"properties/{PROPERTY}/dependsOn") == "fs30-test-auth-service"
    assert job.findtext("builders/hudson.tasks.Shell/command") == "sleep 8"
    assert job.findtext("assignedNode") == "linux"


def test_several_upstreams_are_prefixed_and_comma_separated() -> None:
    fs30 = workload.load("freestyle-30")
    job = parse(templates.render(fs30, fs30.job("integration-test-suite")))
    assert job.findtext(f"properties/{PROPERTY}/dependsOn") == (
        "fs30-test-auth-service,fs30-test-payment-service,fs30-test-user-service"
    )


def test_a_pipeline_jobs_script_sleeps_on_linux_and_repeats_its_band_and_upstreams() -> None:
    pl30 = workload.load("pipeline-30")
    job = parse(templates.render(pl30, pl30.job("deploy-auth-service")))
    script = pipeline_script(job)
    assert "agent { label 'linux' }" in script
    assert "dynamicQueuePriority(level: 'HIGH', dependsOn: 'pl30-test-auth-service')" in script
    assert "sh 'sleep 8'" in script
    assert job.findtext("definition/sandbox") == "true"
    assert job.findtext(f"properties/{PROPERTY}/dependsOn") == "pl30-test-auth-service"


def test_the_script_is_escaped_for_xml_and_reads_back_unchanged() -> None:
    pl30 = workload.load("pipeline-30")
    xml = templates.render(pl30, pl30.job("lint-auth-service"))
    assert "&apos;linux&apos;" in xml
    assert "sh 'sleep 5'" in pipeline_script(parse(xml))


def test_the_description_marks_the_job_with_its_workload_and_digest() -> None:
    fs6 = workload.load("freestyle-6")
    job = parse(templates.render(fs6, fs6.job("build-auth-service")))
    text = job.findtext("description") or ""
    assert templates.marker(text) == ("freestyle-6", fs6.digest[:12])
    assert templates.marker("A job someone made by hand") is None


def test_the_rendered_job_drops_the_templates_explanatory_comment() -> None:
    fs6 = workload.load("freestyle-6")
    xml = templates.render(fs6, fs6.job("build-auth-service"))
    assert "<!--" not in xml
    assert xml.startswith('<?xml version="1.1" encoding="UTF-8"?>\n<project>')


@pytest.mark.parametrize("name", ["freestyle-30", "pipeline-30", "mixed-30", "freestyle-6"])
def test_every_job_of_every_workload_renders_to_well_formed_xml(name: str) -> None:
    loaded = workload.load(name)
    for spec in loaded.jobs:
        root = parse(templates.render(loaded, spec))
        assert root.tag == ("project" if spec.job_type == "freestyle" else "flow-definition")
