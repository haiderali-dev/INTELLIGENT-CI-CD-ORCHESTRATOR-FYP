"""4.9's end-to-end success on a 20-command sample, run against ``jenkins-dev``.

``python -m eval e2e --parser groq:<model>`` sends each item of the dataset's end-to-end sample
(``e2e: true``) through the real stack, exactly as T5.8's end-to-end suite does, because it *is*
that suite's stack (``backend/tests/e2e_support.py``): the FastAPI app with every router,
PostgreSQL in a database of its own, ``jenkins-dev`` with its agents and the plugin, GitHub, the
run tracker and the staging deploys. Only the model is chosen here: one model, no fallback, its
answers cached by prompt hash and paced like every other run of this harness. An answer to a
prompt the main run already asked is replayed from that cache: the same model's answer to the
same prompt, not a second sample of it.

A command succeeds end to end when all of these hold, checked in this order, and the first that
fails is recorded as where it failed:

1. **understood**: the pipeline decided to generate (the item's gold behaviour);
2. **planned**: a plan was generated and passed every validation check;
3. **as asked**: the spec has the gold intent's service, branch, stages and priority;
4. **ran**: the approved chain finished, every job SUCCESS;
5. **deployed**: for a deploy, the staging service answers its health check.

The items are run one at a time, each in a new conversation as a user of its own role, so no
item's history or chain lock can touch the next.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import yaml

from app.ai.providers import GroqProvider, LLMProvider, ReplayProvider
from app.ai.quota import QuotaTracker
from app.db.models import Role
from eval.dataset import Item, load_dataset
from eval.runner import (
    CACHE_DIR,
    REPO_ROOT,
    RESULTS_DIR,
    UNREACHABLE,
    CachedLiveProvider,
    quota_stop,
)

BACKEND: Final = REPO_ROOT / "backend"

# A deploy's staging service, from the host (catalog/services.yaml's deploy URLs).
HEALTH_PATH: Final = "/health"
DEFAULT_BRANCH: Final = "main"


@dataclass(frozen=True)
class E2EConfig:
    parser: str  # "groq:<model>", or "replay" for answers already in the cache only
    dataset: Path
    fresh: bool = False

    @property
    def model(self) -> str:
        if self.parser.startswith("groq:"):
            return self.parser.split(":", 1)[1]
        return "openai/gpt-oss-120b"

    @property
    def out_dir(self) -> Path:
        # Not "-e2e": that is the parse-only run over the same sample (`--subset e2e`).
        slug = re.sub(r"[^A-Za-z0-9.]+", "-", self.parser).strip("-")
        return RESULTS_DIR / f"{self.dataset.stem}-end-to-end__{slug}"


def expected_templates(gold: dict[str, Any]) -> set[str]:
    """The stage templates the request needs, from 4.6.2 and D-042: build first when needed."""
    action = gold["action"]
    return {
        "BUILD": {"build"},
        "TEST": {"build", "test"},
        "DEPLOY": {"deploy"},
        "BUILD_TEST_DEPLOY": {"build", "test", "deploy"},
    }[action]


def spec_matches(gold: dict[str, Any], spec: dict[str, Any], configured: set[str]) -> list[str]:
    """How the generated spec differs from what the gold intent asked for. Empty when it does not.

    ``configured`` is the service's catalog extra stages: one it does not configure is dropped by
    the validator with a warning (D-042), so it is not expected here.
    """
    problems: list[str] = []
    if spec.get("service") != gold.get("service"):
        problems.append(f"service {spec.get('service')!r}, asked {gold.get('service')!r}")
    branch = gold.get("branch") or DEFAULT_BRANCH
    if spec.get("branch") != branch:
        problems.append(f"branch {spec.get('branch')!r}, asked {branch!r}")
    stages = spec.get("stages") or []
    templates = {str(stage.get("template")) for stage in stages}
    missing = expected_templates(gold) - templates
    if missing:
        problems.append(f"no {', '.join(sorted(missing))} stage")
    if "deploy" not in expected_templates(gold) and "deploy" in templates:
        problems.append("a deploy stage nobody asked for")
    suite = gold.get("test_suite")
    if suite and not any(stage.get("suite") == suite for stage in stages):
        problems.append(f"no {suite} test stage")
    for extra in set(gold.get("extra_stages", [])) & configured:
        if extra not in templates:
            problems.append(f"no {extra} stage")
    for stage in stages:
        if stage.get("environment") not in (None, "staging"):
            problems.append(f"a stage targets {stage.get('environment')!r}")
    priority = gold.get("urgency") or "MEDIUM"
    if spec.get("priority") != priority:
        problems.append(f"priority {spec.get('priority')!r}, asked {priority!r}")
    return problems


def _support() -> Any:
    """``tests.e2e_support``, from the backend's test tree, imported on first use."""
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    from tests import e2e_support

    return e2e_support


class ModelSilentError(RuntimeError):
    """The model did not answer, most likely for quota. Not the system's failure: the item is
    left unrecorded, and a rerun resumes from it."""


async def run_item(stack: Any, support: Any, item: Item, configured: set[str]) -> dict[str, Any]:
    """One command, end to end. Raises only ``ModelSilentError``; every failure of the system
    under test is recorded, with the step it happened in."""
    started = time.monotonic()
    record: dict[str, Any] = {
        "item_id": item.id,
        "text": item.text,
        "role": item.role,
        "assistant": item.assistant,
        "action": item.gold_intent["action"],
        "success": False,
        "failed_at": None,
        "reason": None,
    }
    step = "understood"

    def fail(reason: str) -> dict[str, Any]:
        record.update(failed_at=step, reason=reason[:500])
        record["seconds"] = round(time.monotonic() - started, 1)
        return record

    try:
        headers = await support.sign_in(stack, Role(item.role))
        chat = await support.new_chat(stack, headers, item.assistant or "freestyle")
        response = await stack.client.post(
            f"/api/conversations/{chat}/messages", headers=headers, json={"text": item.text}
        )
        if response.status_code != 201:
            return fail(f"HTTP {response.status_code}: {response.text[:300]}")
        command = response.json()["command"]
        if command is None:
            return fail("no command was recorded for the message")
        if command.get("parser") == "RULES":
            raise ModelSilentError("the rule parser answered the message")
        record.update(
            disposition=command["disposition"],
            parser=command.get("parser"),
            model=command.get("model"),
            intent=(command.get("record") or {}).get("intent"),
        )
        if command["disposition"] != "READY":
            return fail(f"the pipeline answered {command['disposition']}")

        step = "planned"
        generated = await stack.client.post(
            f"/api/commands/{command['id']}/generate", headers=headers
        )
        if generated.status_code != 201:
            return fail(f"HTTP {generated.status_code}: {generated.text[:300]}")
        pipeline = generated.json()
        plan = pipeline.get("plan") or {}
        silent = quota_stop(plan.get("fallback_reasons") or [])
        if plan.get("source") == "default" and silent is not None:
            raise ModelSilentError(silent)
        record.update(
            pipeline_status=pipeline["status"],
            plan_source=plan.get("source"),
            plan_valid_before_repair=plan.get("valid_before_repair"),
            plan_repairs=plan.get("repairs"),
            jobs=[job["name"] for job in pipeline["jobs"]],
        )
        if pipeline["status"] != "VALIDATED":
            return fail(f"the pipeline is {pipeline['status']}")

        step = "as asked"
        spec = yaml.safe_load(pipeline["spec_yaml"]) or {}
        record["spec"] = {
            "service": spec.get("service"),
            "branch": spec.get("branch"),
            "priority": spec.get("priority"),
            "stages": [stage.get("template") for stage in spec.get("stages") or []],
        }
        problems = spec_matches(item.gold_intent, spec, configured)
        if problems:
            return fail("; ".join(problems))

        step = "ran"
        approved = await stack.client.post(
            f"/api/pipelines/{pipeline['id']}/approve",
            headers={**headers, "Idempotency-Key": f"eval-e2e-{pipeline['id']}"},
        )
        if approved.status_code != 200:
            return fail(f"approval: HTTP {approved.status_code}: {approved.text[:300]}")
        chain_id = approved.json()["result"]["chain_id"]
        card = await support.wait_for_chain(stack, headers, chain_id)
        record["chain_status"] = card["status"]
        record["job_results"] = [
            (job.get("run") or {}).get("result") for job in card.get("jobs") or []
        ]
        if card["status"] != "SUCCESS":
            return fail(f"the chain ended {card['status']}")

        if "deploy" in expected_templates(item.gold_intent):
            step = "deployed"
            service = str(item.gold_intent["service"])
            health = await asyncio.to_thread(support.service_url, service, HEALTH_PATH)
            record["health_status"] = health.status_code
            if health.status_code != 200:
                return fail(f"{service} answered HTTP {health.status_code}")
    except ModelSilentError:
        raise
    except Exception as exc:  # recorded, never hidden: the run goes on to the next item
        return fail(f"{type(exc).__name__}: {exc}")

    record["success"] = True
    record["seconds"] = round(time.monotonic() - started, 1)
    return record


def _load(path: Path) -> dict[str, dict[str, Any]]:
    done: dict[str, dict[str, Any]] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                raw = json.loads(line)
                done[raw["item_id"]] = raw
    return done


def summarise(records: list[dict[str, Any]], expected: int) -> dict[str, Any]:
    """Success over the commands run, and where each failure happened."""
    succeeded = sum(record["success"] for record in records)
    failures: dict[str, int] = {}
    for record in records:
        if not record["success"]:
            failures[record["failed_at"]] = failures.get(record["failed_at"], 0) + 1
    by_assistant: dict[str, dict[str, int]] = {}
    for record in records:
        cell = by_assistant.setdefault(str(record["assistant"]), {"n": 0, "succeeded": 0})
        cell["n"] += 1
        cell["succeeded"] += int(record["success"])
    return {
        "n": len(records),
        "expected": expected,
        "succeeded": succeeded,
        "success_rate": round(succeeded / len(records), 4) if records else None,
        "failed_at": dict(sorted(failures.items())),
        "by_assistant": dict(sorted(by_assistant.items())),
        "seconds_median": sorted(r["seconds"] for r in records)[len(records) // 2]
        if records
        else None,
    }


def _provider(config: E2EConfig, groq_key: str | None) -> LLMProvider:
    if config.parser == "replay":
        return ReplayProvider(CACHE_DIR)
    if not config.parser.startswith("groq:"):
        raise SystemExit(f"e2e needs groq:<model> or replay, not {config.parser!r}")
    if not groq_key:
        raise SystemExit(f"{config.parser} needs GROQ_API_KEY in the environment or .env")
    return CachedLiveProvider(GroqProvider(groq_key), CACHE_DIR)


async def run_e2e(config: E2EConfig, *, groq_key: str | None) -> dict[str, Any]:
    dataset = load_dataset(config.dataset)
    items = [item for item in dataset.items if item.e2e]
    config.out_dir.mkdir(parents=True, exist_ok=True)
    records_path = config.out_dir / "e2e.jsonl"
    if config.fresh and records_path.exists():
        records_path.unlink()
    done = _load(records_path)

    support = _support()
    # A database of its own, fresh: the chain locks and HIGH quotas of an earlier run are gone.
    await asyncio.to_thread(support.recreate_database)
    provider = _provider(config, groq_key)
    catalog_extras = _catalog_extras()
    stopped: str | None = None
    async for stack in support.stack(
        provider,
        mode="eval",
        models=config.model,
        quota=QuotaTracker({config.model: UNREACHABLE}),
    ):
        with records_path.open("a", encoding="utf-8") as sink:
            for item in items:
                if item.id in done:
                    continue
                service = str(item.gold_intent.get("service"))
                try:
                    record = await run_item(
                        stack, support, item, catalog_extras.get(service, set())
                    )
                except ModelSilentError as exc:
                    stopped = (
                        f"stopped at {item.id}: the model did not answer ({exc}). Progress is "
                        "saved; rerun the same command later to resume."
                    )
                    break
                done[item.id] = record
                sink.write(json.dumps(record) + "\n")
                sink.flush()

    records = [done[item.id] for item in items if item.id in done]
    report: dict[str, Any] = {
        "run": {
            "kind": "e2e",
            "parser": config.parser,
            "model": config.model,
            "dataset": config.dataset.relative_to(REPO_ROOT).as_posix(),
            "finished_at": datetime.now(UTC).isoformat(),
            "complete": stopped is None and len(records) == len(items),
            "stopped_reason": stopped,
            "labels": "machine" if dataset.machine_labelled else "human",
            "for_reporting": True,
        },
        "summary": summarise(records, len(items)),
        "path": (config.out_dir / "metrics.json").relative_to(REPO_ROOT).as_posix(),
    }
    (config.out_dir / "metrics.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    return report


def _catalog_extras() -> dict[str, set[str]]:
    raw = yaml.safe_load((REPO_ROOT / "catalog" / "services.yaml").read_text(encoding="utf-8"))
    return {
        service["name"]: set((service.get("extra_stages") or {}).keys())
        for service in raw["services"]
    }
