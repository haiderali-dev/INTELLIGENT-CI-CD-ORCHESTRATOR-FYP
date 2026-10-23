"""An in-memory controller with the methods the harness calls, and a clock the tests control.

A small discrete-event simulation: jobs created from the harness's own ``config.xml``, a queue,
N executors, builds that take their job's sleep, and the plugin's four event kinds as the plugin
records them. The observe-only and stock arms dispatch in arrival order with no gate; the
optimized arm dispatches by band, holding a job while an upstream is queued or building, as the
dependency gate does. A Pipeline leaves the queue as a flyweight, then queues one node block.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

from experiment.harness import arm_of

LEVEL_RANK = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
PROPERTY = "io.jenkins.plugins.queueoptimizer.property.JobPriorityProperty"


class FakeClock:
    """Milliseconds that move only when the harness sleeps."""

    def __init__(self, start_ms: int = 1_700_000_000_000) -> None:
        self.ms = start_ms

    def now_ms(self) -> int:
        return self.ms

    def monotonic(self) -> float:
        return self.ms / 1000

    def sleep(self, seconds: float) -> None:
        self.ms += int(seconds * 1000)


def configuration(arm: str) -> dict[str, Any]:
    return {
        "optimizerEnabled": arm != "observe-only",
        "agingBonusPerInterval": 0.0 if arm == "aging-off" else 0.05,
        "agingCap": 0.0 if arm == "aging-off" else 0.15,
        "weightUrgency": 0.5,
    }


class FakeController:
    """One controller. ``arm`` is observe-only, optimized, aging-off or stock."""

    def __init__(self, clock: FakeClock, executors: int = 1, arm: str = "optimized") -> None:
        self.clock = clock
        self.base_url = "http://fake-controller"
        self.executor_count = executors
        self.arm = arm
        self.jobs_: dict[str, dict[str, Any]] = {}
        self.queue: list[dict[str, Any]] = []
        self.running: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self.next_item = 1
        self.sim_ms = clock.now_ms()
        self.deleted: list[str] = []
        self.stuck = False

    # -- the controller ------------------------------------------------------------------------

    def jenkins_version(self) -> str:
        return "2.568.3"

    def executors(self) -> dict[str, int]:
        return {"agent": self.executor_count}

    def busy(self) -> tuple[int, int]:
        self._advance()
        return (len(self.running) + (1 if self.stuck else 0), len(self.queue))

    def dynamic_queue(self) -> dict[str, Any] | None:
        return None if self.arm == "stock" else {"configuration": configuration(self.arm)}

    def health(self) -> dict[str, Any] | None:
        if self.arm == "stock":
            return None
        return {
            "lastSortDurationMillis": 0.25 + 0.05 * (len(self.events) % 3),
            "heapSize": len(self.queue),
            "cacheHitRate": 0.5,
            "droppedMetricCount": 0,
            "pluginVersion": "2.0.0-SNAPSHOT",
            "pluginBuild": "f" * 40,
        }

    def recent_events(self, limit: int = 500) -> list[dict[str, Any]]:
        self._advance()
        return [] if self.arm == "stock" else list(self.events[-limit:])

    # -- jobs ------------------------------------------------------------------------------------

    def jobs(self) -> dict[str, str]:
        return {name: job["description"] for name, job in self.jobs_.items()}

    def create_job(self, name: str, config_xml: str) -> None:
        assert name not in self.jobs_, f"{name} exists"
        root = ET.fromstring(config_xml.encode("utf-8"))  # noqa: S314 - the harness's own XML
        if root.tag == "project":
            command = root.findtext("builders/hudson.tasks.Shell/command") or ""
            seconds, job_type = int(command.split()[-1]), "freestyle"
        else:
            definition = root.find("definition")
            script = (definition.findtext("script") if definition is not None else None) or ""
            seconds = int(script.split("sh 'sleep ")[1].split("'")[0])
            job_type = "pipeline"
        depends = root.findtext(f"properties/{PROPERTY}/dependsOn") or ""
        self.jobs_[name] = {
            "description": root.findtext("description") or "",
            "level": root.findtext(f"properties/{PROPERTY}/level"),
            "depends": [d for d in depends.split(",") if d],
            "seconds": seconds,
            "type": job_type,
            "builds": [],
        }

    def delete_job(self, name: str) -> None:
        del self.jobs_[name]
        self.deleted.append(name)

    def trigger(self, name: str) -> int:
        self._advance()
        item: dict[str, Any] = {"id": self._item(), "job": name, "entered": self.clock.now_ms()}
        self.queue.append(item)
        self._event("QUEUE_ENTERED", item["entered"], item["id"], name, item["entered"])
        return int(item["id"])

    def last_builds(self) -> dict[str, tuple[int, bool]]:
        self._advance()
        latest = {}
        for name, job in self.jobs_.items():
            running = [b for b in self.running if b["job"] == name]
            if running:
                latest[name] = (running[0]["number"], True)
            else:
                latest[name] = (len(job["builds"]), False)
        return latest

    def build(self, name: str, number: int) -> dict[str, Any]:
        return dict(self.jobs_[name]["builds"][number - 1])

    # -- the simulation --------------------------------------------------------------------------

    def _item(self) -> int:
        self.next_item += 1
        return self.next_item

    def _event(self, kind: str, at: int, item: int, job: str, since: int, **fields: Any) -> None:
        event = {
            "kind": kind,
            "timestamp": at,
            "itemId": item,
            "jobName": job,
            "inQueueSince": since,
            "isNodeBlock": False,
            "consumesExecutor": True,
            "cancelled": False,
            "optimizerEnabled": self.arm != "observe-only",
        }
        event.update(fields)
        self.events.append(event)

    def _advance(self) -> None:
        target = self.clock.now_ms()
        while True:
            self._start_eligible(self.sim_ms)
            ends = [b["end"] for b in self.running]
            if not ends or min(ends) > target:
                break
            self.sim_ms = min(ends)
            for build in [b for b in self.running if b["end"] == self.sim_ms]:
                self._finish(build)
        self.sim_ms = max(self.sim_ms, target)
        self._start_eligible(self.sim_ms)

    def _start_eligible(self, at: int) -> None:
        ordered = list(self.queue)
        gate = self.arm in ("optimized", "aging-off")
        if gate:
            ordered.sort(
                key=lambda item: (LEVEL_RANK[self.jobs_[item["job"]]["level"]], item["id"])
            )
        for item in ordered:
            if len(self.running) >= self.executor_count:
                return
            job = self.jobs_[item["job"]]
            busy = {i["job"] for i in self.queue} | {b["job"] for b in self.running}
            if gate and any(up in busy for up in job["depends"]):
                continue
            self.queue.remove(item)
            self._start(item, job, at)

    def _start(self, item: dict[str, Any], job: dict[str, Any], at: int) -> None:
        name, number = item["job"], len(job["builds"]) + 1
        flyweight = job["type"] == "pipeline"
        self._event(
            "QUEUE_LEFT",
            at,
            item["id"],
            name,
            item["entered"],
            waitMillis=at - item["entered"],
            consumesExecutor=not flyweight,
        )
        self._build_event("BUILD_STARTED", at, name, number, at)
        if flyweight:
            node = self._item()
            self._event("QUEUE_ENTERED", at, node, name, at, isNodeBlock=True)
            self._event("QUEUE_LEFT", at, node, name, at, isNodeBlock=True, waitMillis=0)
        self.running.append(
            {
                "job": name,
                "number": number,
                "start": at,
                "end": at + job["seconds"] * 1000 + 100,
                "queueId": item["id"],
            }
        )

    def _finish(self, build: dict[str, Any]) -> None:
        self.running.remove(build)
        name = build["job"]
        duration = build["end"] - build["start"]
        self.jobs_[name]["builds"].append(
            {
                "number": build["number"],
                "timestamp": build["start"],
                "duration": duration,
                "result": "SUCCESS",
                "building": False,
                "queueId": build["queueId"],
            }
        )
        self._build_event(
            "BUILD_COMPLETED", build["end"], name, build["number"], build["start"], duration
        )

    def _build_event(
        self, kind: str, at: int, job: str, number: int, start: int, duration: int | None = None
    ) -> None:
        """A build event as RunMetricsRecorder writes it: no queue fields."""
        event: dict[str, Any] = {
            "kind": kind,
            "timestamp": at,
            "jobName": job,
            "buildNumber": number,
            "startTimeMillis": start,
            "optimizerEnabled": self.arm != "observe-only",
        }
        if duration is not None:
            event.update(durationMillis=duration, result="SUCCESS")
        self.events.append(event)


__all__ = ["FakeClock", "FakeController", "arm_of"]
