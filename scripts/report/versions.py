"""Regenerate the pin list in docs/versions.md from the files that set the pins, and print Appendix E.

    python scripts/report/versions.py              # rewrite the generated section of docs/versions.md
    python scripts/report/versions.py --check      # exit 1 if it is stale, or a table disagrees
    python scripts/report/versions.py --appendix-e # the report's Appendix E, from the same pins

BUILD_PROMPT 4.10: "regenerates docs/versions.md from pom.xml, pyproject.toml, package.json and
plugins.txt". It also reads `backend/uv.lock` (pyproject.toml states lower bounds, the lock the
versions installed), the Dockerfiles and Compose (the images), and the backend's settings (the model
chain).

What is generated, and what is not. Every pin is generated, into the section between the two
`versions.py` markers. What surrounds that section is written by hand and stays: where each version
was checked, when, and why some are deliberately behind the newest release (rule 1.4). Regenerating
that prose from build files is impossible. So `--check` also reads every hand-written table, and
fails when a version it states differs from the one the build uses: the prose cannot drift from the
pins either.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VERSIONS = REPO_ROOT / "docs" / "versions.md"
BEGIN = "<!-- versions.py: begin. Generated; edit the files named in each table, not this section. -->"
END = "<!-- versions.py: end -->"
POM_NS = {"m": "http://maven.apache.org/POM/4.0.0"}
_VERSION = re.compile(r"[0-9][0-9A-Za-z._+-]*")


@dataclass(frozen=True)
class Pin:
    area: str
    name: str
    version: str
    source: str


def _rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


# ---------------------------------------------------------------------------
# Reading the pins
# ---------------------------------------------------------------------------


def plugin_pins() -> list[Pin]:
    pom = REPO_ROOT / "plugin" / "pom.xml"
    root = ET.parse(pom).getroot()  # noqa: S314 - our own pom.xml, not untrusted input

    def text(path: str) -> str:
        node = root.find(path, POM_NS)
        return (node.text or "").strip() if node is not None else ""

    found = root.find("m:properties", POM_NS)
    properties = {
        child.tag.split("}")[1]: (child.text or "").strip()
        for child in (list(found) if found is not None else [])
        if isinstance(child.tag, str)
    }

    def resolve(value: str) -> str:
        for _ in range(5):
            value = re.sub(r"\$\{([^}]+)\}", lambda m: properties.get(m.group(1), m.group(0)), value)
        return value

    source = _rel(pom)
    pins = [
        Pin("Plugin", f"{text('m:groupId')}:{text('m:artifactId')}", text("m:version"), source),
        Pin(
            "Plugin",
            f"parent {text('m:parent/m:groupId')}:{text('m:parent/m:artifactId')}",
            text("m:parent/m:version"),
            source,
        ),
        Pin("Plugin", "jenkins.version", resolve(properties.get("jenkins.version", "")), source),
        Pin(
            "Plugin",
            "java.level",
            properties.get("java.level", "17 (unset here: the parent POM's default)"),
            source,
        ),
    ]
    for dependency in root.iterfind("m:dependencyManagement/m:dependencies/m:dependency", POM_NS):
        group = (dependency.findtext("m:groupId", "", POM_NS) or "").strip()
        if group == "io.jenkins.tools.bom":
            artifact = resolve((dependency.findtext("m:artifactId", "", POM_NS) or "").strip())
            version = (dependency.findtext("m:version", "", POM_NS) or "").strip()
            pins.append(Pin("Plugin", f"{group}:{artifact}", version, source))
    for plugin in root.iter(f"{{{POM_NS['m']}}}plugin"):
        group = (plugin.findtext("m:groupId", "", POM_NS) or "").strip()
        artifact = (plugin.findtext("m:artifactId", "", POM_NS) or "").strip()
        version = resolve((plugin.findtext("m:version", "", POM_NS) or "").strip())
        if group == "org.pitest" and version:
            pins.append(Pin("Plugin", f"{group}:{artifact}", version, source))
        for dependency in plugin.iterfind("m:dependencies/m:dependency", POM_NS):
            dep_group = (dependency.findtext("m:groupId", "", POM_NS) or "").strip()
            dep_version = resolve((dependency.findtext("m:version", "", POM_NS) or "").strip())
            if dep_group == "org.pitest" and dep_version:
                dep_artifact = (dependency.findtext("m:artifactId", "", POM_NS) or "").strip()
                pins.append(Pin("Plugin", f"{dep_group}:{dep_artifact}", dep_version, source))
    return pins


def controller_plugin_pins() -> list[Pin]:
    path = REPO_ROOT / "jenkins" / "controller" / "plugins.txt"
    pins = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if ":" in line:
            name, version = line.split(":", 1)
            pins.append(Pin("Controller plugins", name.strip(), version.strip(), _rel(path)))
    return pins


def image_pins() -> list[Pin]:
    """The system's images, and apart from them the sample services' own, which deploy builds."""
    files = [
        ("Images", REPO_ROOT / "jenkins" / "controller" / "Dockerfile"),
        ("Images", REPO_ROOT / "jenkins" / "agent" / "Dockerfile"),
        ("Images", REPO_ROOT / "backend" / "Dockerfile"),
        ("Images", REPO_ROOT / "frontend" / "Dockerfile"),
        *(
            ("Sample service images", path)
            for path in sorted((REPO_ROOT / "sample-services").glob("*/Dockerfile"))
        ),
    ]
    pins: list[Pin] = []
    seen: set[tuple[str, str, str]] = set()
    for area, path in files:
        for line in path.read_text(encoding="utf-8").splitlines():
            found = re.match(r"^FROM\s+(\S+?)(?:\s+AS\s+\S+)?\s*$", line.strip(), re.I)
            # An image a stage copies from, such as uv's: `COPY --from=ghcr.io/astral-sh/uv:0.12.20`.
            copied = re.match(r"^COPY\s+--from=(\S+/\S+)\s", line.strip(), re.I)
            reference = found.group(1) if found else copied.group(1) if copied else ""
            if ":" in reference:
                name, tag = reference.rsplit(":", 1)
                if (area, name, tag) not in seen:
                    seen.add((area, name, tag))
                    pins.append(Pin(area, name, tag, _rel(path)))
    compose = REPO_ROOT / "docker-compose.yml"
    for line in compose.read_text(encoding="utf-8").splitlines():
        found = re.match(r"^\s+image:\s*([^\s:]+):(\S+)\s*$", line)
        if found and ("Images", found.group(1), found.group(2)) not in seen:
            seen.add(("Images", found.group(1), found.group(2)))
            pins.append(Pin("Images", found.group(1), found.group(2), _rel(compose)))
    return pins


def _requirement_name(requirement: str) -> str:
    return re.split(r"[\[<>=!~; ]", requirement, maxsplit=1)[0].strip().lower()


def backend_pins() -> list[Pin]:
    pyproject = REPO_ROOT / "backend" / "pyproject.toml"
    lock = REPO_ROOT / "backend" / "uv.lock"
    project = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]
    locked = {
        package["name"].lower(): package["version"]
        for package in tomllib.loads(lock.read_text(encoding="utf-8"))["package"]
        if "version" in package
    }
    pins = [
        Pin("Backend", "Python", project.get("requires-python", ""), _rel(pyproject)),
    ]
    requirements = list(project.get("dependencies", []))
    for extra in project.get("optional-dependencies", {}).values():
        requirements.extend(extra)
    for requirement in requirements:
        name = _requirement_name(requirement)
        pins.append(
            Pin("Backend", name, locked.get(name, "not locked"), f"{_rel(pyproject)}, {_rel(lock)}")
        )
    return pins


def frontend_pins() -> list[Pin]:
    path = REPO_ROOT / "frontend" / "package.json"
    package = json.loads(path.read_text(encoding="utf-8"))
    pins = []
    for section in ("dependencies", "devDependencies"):
        for name, version in sorted(package.get(section, {}).items()):
            pins.append(Pin("Frontend", name, version, f"{_rel(path)} ({section})"))
    return pins


def model_pins() -> list[Pin]:
    path = REPO_ROOT / "backend" / "app" / "core" / "settings.py"
    found = re.search(r'llm_model_chain:\s*str\s*=\s*"([^"]+)"', path.read_text(encoding="utf-8"))
    chain = found.group(1) if found else "not found"
    return [Pin("LLM provider", "default model chain", chain, _rel(path))]


def all_pins() -> list[Pin]:
    return [
        *plugin_pins(),
        *controller_plugin_pins(),
        *image_pins(),
        *backend_pins(),
        *frontend_pins(),
        *model_pins(),
    ]


# ---------------------------------------------------------------------------
# The generated section
# ---------------------------------------------------------------------------


def generated_section(pins: list[Pin]) -> str:
    lines = [
        BEGIN,
        "",
        "## Every pin, as the build files state it",
        "",
        "Generated by `python scripts/report/versions.py` from the files named in each table. The",
        "sections above say where each version was checked, when, and why; this list is what the",
        "build uses, and `--check` fails if a table above disagrees with it.",
    ]
    areas: dict[str, list[Pin]] = {}
    for pin in pins:
        areas.setdefault(pin.area, []).append(pin)
    for area, members in areas.items():
        sources = sorted({pin.source for pin in members})
        lines += [
            "",
            f"### {area}",
            "",
            "From " + ", ".join(f"`{source}`" for source in sources) + ".",
            "",
            "| Component | Version |",
            "| --- | --- |",
        ]
        lines += [f"| `{pin.name}` | {pin.version} |" for pin in members]
    lines += ["", END, ""]
    return "\n".join(lines)


def rewrite(text: str, section: str) -> str:
    if BEGIN in text and END in text:
        head = text[: text.index(BEGIN)]
        tail = text[text.index(END) + len(END) :].lstrip("\n")
        return head + section + tail
    return text.rstrip("\n") + "\n\n" + section


# ---------------------------------------------------------------------------
# Checking the hand-written tables against the pins
# ---------------------------------------------------------------------------


def _hand_rows(text: str) -> Iterator[tuple[int, list[str], list[str]]]:
    """(line number, names, versions) for each hand-written table row naming a component."""
    hand = text.split(BEGIN)[0] if BEGIN in text else text
    for number, line in enumerate(hand.splitlines(), start=1):
        if not line.startswith("|") or line.startswith("| ---"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        names = re.findall(r"`([^`]+)`", cells[0])
        if not names:
            continue
        # Abbreviated names ("`@codemirror/state`, `/view`") take the first one's scope.
        scope = names[0].rsplit("/", 1)[0] if names[0].startswith("@") else ""
        names = [scope + name if name.startswith("/") and scope else name for name in names]
        # "8.3.4 (8.3.2 until 2026-10-22), 6.1.2": asides in brackets are history, not pins.
        versions = _VERSION.findall(re.sub(r"\([^)]*\)", "", cells[1].replace("*", "")))
        yield number, names, versions


def disagreements(text: str, pins: list[Pin]) -> list[str]:
    known = {pin.name.lower(): pin.version for pin in pins}
    problems = []
    for number, names, versions in _hand_rows(text):
        if not versions:
            continue
        if len(versions) == len(names):
            pairs = zip(names, versions, strict=True)
        elif len(versions) == 1:
            pairs = ((name, versions[0]) for name in names)
        else:
            continue
        for name, version in pairs:
            pinned = known.get(name.lower())
            leading = _VERSION.match(pinned) if pinned is not None else None
            if leading is None:
                continue
            if version != leading.group(0):
                problems.append(
                    f"docs/versions.md line {number}: {name} {version}, but the build pins {pinned}"
                )
    return problems


# ---------------------------------------------------------------------------
# Appendix E
# ---------------------------------------------------------------------------

APPENDIX_E = (
    ("Jenkins LTS", "Images", "jenkins/jenkins", "Controller, with the plugin installed"),
    ("Jenkins SSH agent", "Images", "jenkins/ssh-agent", "The two Linux build agents"),
    ("Plugin parent POM", "Plugin", "parent org.jenkins-ci.plugins:plugin", "Plugin build"),
    ("Python", "Images", "python", "Backend runtime"),
    ("FastAPI", "Backend", "fastapi", "Backend API"),
    ("SQLAlchemy", "Backend", "sqlalchemy", "Database access"),
    ("PostgreSQL", "Images", "postgres", "Database"),
    ("OpenAI Python SDK", "Backend", "openai", "Groq's OpenAI-compatible API"),
    ("Model chain", "LLM provider", "default model chain", "Intent parsing and planning"),
    ("React", "Frontend", "react", "Frontend"),
    ("TypeScript", "Frontend", "typescript", "Frontend language"),
    ("Vite", "Frontend", "vite", "Frontend build"),
    ("Tailwind CSS", "Frontend", "tailwindcss", "Styling"),
    ("Node.js", "Images", "node", "Frontend build image"),
    ("nginx (unprivileged)", "Images", "nginxinc/nginx-unprivileged", "Serves the frontend"),
)


def appendix_e(pins: list[Pin]) -> str:
    by_key = {(pin.area, pin.name): pin for pin in pins}
    lines = [
        "Table 13.3: Tools and versions (generated by scripts/report/versions.py)",
        "",
        "| Tool | Version | Purpose |",
        "| --- | --- | --- |",
    ]
    for label, area, name, purpose in APPENDIX_E:
        pin = by_key.get((area, name))
        lines.append(f"| {label} | {pin.version if pin else 'not pinned'} | {purpose} |")
    lines += [
        "",
        "Every version above is read from the build files at the commit the report describes. "
        "There is no Redis: live queue state comes from the plugin's API and the WebSocket hub.",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if stale or contradicted")
    parser.add_argument("--appendix-e", action="store_true", help="print the report's Appendix E")
    args = parser.parse_args(argv)
    pins = all_pins()
    if args.appendix_e:
        sys.stdout.write(appendix_e(pins))
        return 0
    text = VERSIONS.read_text(encoding="utf-8")
    regenerated = rewrite(text, generated_section(pins))
    problems = disagreements(regenerated, pins)
    if args.check:
        stale = regenerated != text
        for problem in problems:
            print(problem)
        if stale:
            print("docs/versions.md's generated section is out of date; run versions.py")
        print(f"{len(pins)} pins; {'stale' if stale else 'current'}; {len(problems)} disagreement(s)")
        return 1 if stale or problems else 0
    VERSIONS.write_text(regenerated, encoding="utf-8", newline="\n")
    print(f"wrote {VERSIONS.relative_to(REPO_ROOT)}: {len(pins)} pins")
    for problem in problems:
        print(f"  {problem}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
