"""Render a workload's jobs as ``config.xml``, from templates derived from Jenkins' own exports.

The files in ``templates/`` are ``jenkins/reference-configs/`` with placeholders: rule 1.4 says a
Jenkins XML template is derived from an export, never written from memory. Every value is escaped
for XML here, and the templates' explanatory comment is dropped from the rendered job.
"""

from __future__ import annotations

import re
import string
from pathlib import Path
from typing import Final
from xml.sax.saxutils import escape

from experiment.workload import JobSpec, Workload

TEMPLATES_DIR: Final = Path(__file__).resolve().parent / "templates"
#: Every harness job's description starts with this, so ``setup`` can tell its own jobs apart and
#: see whether a job was made from the workload as it is now.
MARKER: Final = "Experiment v2 job"
_MARKED: Final = re.compile(
    r"^Experiment v2 job, workload (?P<workload>[\w.-]+) \(digest (?P<digest>[0-9a-f]{12})\)"
)
_ENTITIES: Final = {"'": "&apos;", '"': "&quot;"}
#: The reference Pipeline's declarative form, cut to one node block that sleeps.
_PIPELINE_SCRIPT: Final = string.Template(
    """pipeline {
    agent { label 'linux' }
    options {
        dynamicQueuePriority(level: '${level}', dependsOn: '${depends_on}')
    }
    stages {
        stage('Work') {
            steps { sh 'sleep ${seconds}' }
        }
    }
}
"""
)


def description(workload: Workload, spec: JobSpec) -> str:
    """The job's description: the marker, then what the job is, for a person reading Jenkins."""
    return (
        f"{MARKER}, workload {workload.name} (digest {workload.digest[:12]}): {spec.level}, sleeps "
        f"{spec.seconds} s. Created by python -m experiment setup; --recreate replaces it."
    )


def marker(text: str) -> tuple[str, str] | None:
    """The (workload, digest) a harness job was made from, or None for any other job."""
    match = _MARKED.match(text)
    return (match.group("workload"), match.group("digest")) if match else None


def render(workload: Workload, spec: JobSpec) -> str:
    """The job's ``config.xml``, ready for ``createItem``."""
    depends_on = ",".join(workload.jenkins_name(upstream) for upstream in spec.depends_on)
    values = {
        "description": description(workload, spec),
        "level": spec.level,
        "depends_on": depends_on,
        "seconds": str(spec.seconds),
    }
    if spec.job_type == "pipeline":
        values["script"] = _PIPELINE_SCRIPT.substitute(
            level=spec.level, depends_on=depends_on, seconds=spec.seconds
        )
    escaped = {key: escape(value, _ENTITIES) for key, value in values.items()}
    return _template(spec.job_type).substitute(escaped)


def _template(job_type: str) -> string.Template:
    text = (TEMPLATES_DIR / f"{job_type}.config.xml").read_text(encoding="utf-8")
    # The comment explains the derivation to a reader of the repository; Jenkins would not keep it.
    text = re.sub(r"<!--.*?-->\s*", "", text, count=1, flags=re.DOTALL)
    return string.Template(text)
