/**
 * Real responses from the backend, captured on 2026-10-16 by driving it in its test configuration
 * (LLM_MODE=fake, the fake Jenkins and Git, SQLite): an Admin approves a freestyle chain whose unit
 * tests fail with the real jenkins-dev log (backend/tests/data/failure_logs), a second chain left
 * queued and a Pipeline left building; creates, changes and is refused users; reads the catalog,
 * health and analytics. Generated from the JSON by a script, not written by hand.
 *
 * SQLite drops time zones, so most timestamps here have none; PostgreSQL's have one. Both are UTC.
 */

import type { AdminUser, AuditPage, Policy, RateLimit, UserPage } from "@/api/adminApi";
import type { ExperimentDetail, ExperimentPage, RunStats } from "@/api/analyticsApi";
import type { Branches, Resync, ServiceList } from "@/api/catalogApi";
import type { ApiErrorBody } from "@/api/client";
import type { Queue } from "@/api/queueApi";
import type { ChainCard, ChainPage, LogWindow, Run, RunFailure, RunPage } from "@/api/runsApi";
import type { components } from "@/api/schema";
import type { Health } from "@/api/systemApi";

type User = components["schemas"]["UserResponse"];
type ApiError = { error: ApiErrorBody };
/** An answer with its HTTP status, for those that are not a plain 200. */
export interface Answered<T> {
  status: number;
  body: T;
}

/** The signed-in Admin who started every chain below. */
export const me: User = {
  "id": "40358f97ce83440ebd3267b6cdd24216",
  "email": "admin@example.com",
  "role": "ADMIN",
  "active": true
};

/** No chain has run yet. */
export const chainsEmpty: ChainPage = {
  "items": [],
  "total": 0,
  "limit": 50,
  "offset": 0
};

/** Three chains: a Pipeline building, a freestyle chain queued, and a freestyle chain whose unit tests failed. */
export const chains: ChainPage = {
  "items": [
    {
      "id": "1e18b7e9b3c342889564407ef2e56d3e",
      "pipeline_id": "298eea9af22441c1a810fe2068090912",
      "service": "payment-service",
      "job_type": "PIPELINE",
      "status": "RUNNING",
      "jobs": [
        "pl-payment-service-build-test-deploy-staging"
      ],
      "position": 0,
      "started_by": "40358f97ce83440ebd3267b6cdd24216",
      "started_at": "2026-10-16T03:13:50.574908",
      "finished_at": null
    },
    {
      "id": "4b786a2b2ad743b19f1801cb4e9807c8",
      "pipeline_id": "9871ff6c6b454518860c7a4723b44de4",
      "service": "auth-service",
      "job_type": "FREESTYLE",
      "status": "RUNNING",
      "jobs": [
        "fs-auth-service-build"
      ],
      "position": 0,
      "started_by": "40358f97ce83440ebd3267b6cdd24216",
      "started_at": "2026-10-16T03:13:50.336294",
      "finished_at": null
    },
    {
      "id": "3e443f6652614a1ca77155dc007264c0",
      "pipeline_id": "6d1f2731cf784a9287a07e09059ee2a9",
      "service": "payment-service",
      "job_type": "FREESTYLE",
      "status": "FAILURE",
      "jobs": [
        "fs-payment-service-build",
        "fs-payment-service-test-unit",
        "fs-payment-service-test-integration",
        "fs-payment-service-deploy-staging"
      ],
      "position": 1,
      "started_by": "40358f97ce83440ebd3267b6cdd24216",
      "started_at": "2026-10-16T03:13:49.914273",
      "finished_at": "2026-10-16T03:13:50.107950"
    }
  ],
  "total": 3,
  "limit": 50,
  "offset": 0
};

/** The two chains still running. */
export const chainsActive: ChainPage = {
  "items": [
    {
      "id": "1e18b7e9b3c342889564407ef2e56d3e",
      "pipeline_id": "298eea9af22441c1a810fe2068090912",
      "service": "payment-service",
      "job_type": "PIPELINE",
      "status": "RUNNING",
      "jobs": [
        "pl-payment-service-build-test-deploy-staging"
      ],
      "position": 0,
      "started_by": "40358f97ce83440ebd3267b6cdd24216",
      "started_at": "2026-10-16T03:13:50.574908",
      "finished_at": null
    },
    {
      "id": "4b786a2b2ad743b19f1801cb4e9807c8",
      "pipeline_id": "9871ff6c6b454518860c7a4723b44de4",
      "service": "auth-service",
      "job_type": "FREESTYLE",
      "status": "RUNNING",
      "jobs": [
        "fs-auth-service-build"
      ],
      "position": 0,
      "started_by": "40358f97ce83440ebd3267b6cdd24216",
      "started_at": "2026-10-16T03:13:50.336294",
      "finished_at": null
    }
  ],
  "total": 2,
  "limit": 50,
  "offset": 0
};

/** The failed freestyle chain's run card: build passed, unit tests failed, two jobs never started. */
export const chainFailed: ChainCard = {
  "id": "3e443f6652614a1ca77155dc007264c0",
  "pipeline_id": "6d1f2731cf784a9287a07e09059ee2a9",
  "service": "payment-service",
  "job_type": "FREESTYLE",
  "status": "FAILURE",
  "position": 1,
  "parameters": {
    "BRANCH": "main",
    "COMMIT": "3f786850e387550fdab836ed7e6dc881de23001b"
  },
  "started_at": "2026-10-16T03:13:49.914273+00:00",
  "finished_at": "2026-10-16T03:13:50.107950+00:00",
  "lock_expires_at": "2026-10-16T03:43:49.914273+00:00",
  "duration_ms": 5555,
  "jobs": [
    {
      "name": "fs-payment-service-build",
      "position": 0,
      "state": "success",
      "run": {
        "id": "2899f920d1c44cc29dcc19453cd1fe5b",
        "build_number": 1,
        "result": "SUCCESS",
        "started_at": null,
        "finished_at": null,
        "duration_ms": 1234,
        "queue_wait_ms": null,
        "url": "http://jenkins.test/job/fs-payment-service-build/1/"
      }
    },
    {
      "name": "fs-payment-service-test-unit",
      "position": 1,
      "state": "failure",
      "run": {
        "id": "ad1ea2f7abdc430f9a7d2dc510484b13",
        "build_number": 1,
        "result": "FAILURE",
        "started_at": "2023-11-14T22:13:20+00:00",
        "finished_at": "2023-11-14T22:13:24.321000+00:00",
        "duration_ms": 4321,
        "queue_wait_ms": null,
        "url": "http://jenkins.test/job/fs-payment-service-test-unit/1/"
      }
    },
    {
      "name": "fs-payment-service-test-integration",
      "position": 2,
      "state": "not_started",
      "run": null
    },
    {
      "name": "fs-payment-service-deploy-staging",
      "position": 3,
      "state": "not_started",
      "run": null
    }
  ],
  "stages": [],
  "queue": null,
  "failed_run_id": "ad1ea2f7abdc430f9a7d2dc510484b13"
};

/** auth-service's chain, first in the plugin's ranking (the T6.6 recording). */
export const chainQueued: ChainCard = {
  "id": "4b786a2b2ad743b19f1801cb4e9807c8",
  "pipeline_id": "9871ff6c6b454518860c7a4723b44de4",
  "service": "auth-service",
  "job_type": "FREESTYLE",
  "status": "RUNNING",
  "position": 0,
  "parameters": {
    "BRANCH": "main",
    "COMMIT": "refs/heads/main"
  },
  "started_at": "2026-10-16T03:13:50.336294+00:00",
  "finished_at": null,
  "lock_expires_at": "2026-10-16T03:43:50.336294+00:00",
  "duration_ms": null,
  "jobs": [
    {
      "name": "fs-auth-service-build",
      "position": 0,
      "state": "queued",
      "run": null
    }
  ],
  "stages": [],
  "queue": {
    "job": "fs-auth-service-build",
    "rank": 1,
    "score": 0.671179,
    "level": "HIGH",
    "components": {
      "urgency": 1,
      "dependency": 0,
      "execution_time": 0.855893,
      "aging_bonus": 0,
      "base_score": 0.671179,
      "own_score": 0.671179
    },
    "weights": {
      "urgency": 0.5,
      "dependency": 0.3,
      "executionTime": 0.2
    },
    "waiting_reason": "Executor slot already in use",
    "wait_seconds": 6.182
  },
  "failed_run_id": null
};

/** The Pipeline chain, in its Unit tests stage. */
export const chainPipelineRunning: ChainCard = {
  "id": "1e18b7e9b3c342889564407ef2e56d3e",
  "pipeline_id": "298eea9af22441c1a810fe2068090912",
  "service": "payment-service",
  "job_type": "PIPELINE",
  "status": "RUNNING",
  "position": 0,
  "parameters": {
    "BRANCH": "main",
    "COMMIT": "3f786850e387550fdab836ed7e6dc881de23001b"
  },
  "started_at": "2026-10-16T03:13:50.574908+00:00",
  "finished_at": null,
  "lock_expires_at": "2026-10-16T03:43:50.574908+00:00",
  "duration_ms": null,
  "jobs": [
    {
      "name": "pl-payment-service-build-test-deploy-staging",
      "position": 0,
      "state": "running",
      "run": {
        "id": "3bd32a1b70b64fc895366e0061a98dfe",
        "build_number": 1,
        "result": "RUNNING",
        "started_at": null,
        "finished_at": null,
        "duration_ms": null,
        "queue_wait_ms": null,
        "url": "http://jenkins.test/job/pl-payment-service-build-test-deploy-staging/1/"
      }
    }
  ],
  "stages": [
    {
      "name": "Checkout",
      "status": "SUCCESS",
      "duration_ms": 2210
    },
    {
      "name": "Build",
      "status": "SUCCESS",
      "duration_ms": 5130
    },
    {
      "name": "Unit tests",
      "status": "IN_PROGRESS",
      "duration_ms": 1840
    },
    {
      "name": "Deploy to staging",
      "status": "NOT_EXECUTED",
      "duration_ms": 0
    }
  ],
  "queue": null,
  "failed_run_id": null
};

/** No run yet. */
export const runsEmpty: RunPage = {
  "items": [],
  "total": 0,
  "limit": 50,
  "offset": 0
};

/** Three runs: the Pipeline building, the failed unit tests, and the build that passed. */
export const runs: RunPage = {
  "items": [
    {
      "id": "3bd32a1b70b64fc895366e0061a98dfe",
      "job_id": "d464117294264531bc08cd9e600aca13",
      "job_name": "pl-payment-service-build-test-deploy-staging",
      "build_number": 1,
      "result": "RUNNING",
      "queue_entered_at": null,
      "started_at": null,
      "finished_at": null,
      "duration_ms": null,
      "queue_wait_ms": null,
      "queue_item_id": 3
    },
    {
      "id": "ad1ea2f7abdc430f9a7d2dc510484b13",
      "job_id": "59767edfb3da46f0a8cf1072d0e1a3ff",
      "job_name": "fs-payment-service-test-unit",
      "build_number": 1,
      "result": "FAILURE",
      "queue_entered_at": null,
      "started_at": "2023-11-14T22:13:20",
      "finished_at": "2023-11-14T22:13:24.321000",
      "duration_ms": 4321,
      "queue_wait_ms": null,
      "queue_item_id": null
    },
    {
      "id": "2899f920d1c44cc29dcc19453cd1fe5b",
      "job_id": "7588fb315fda4587835e531911f13675",
      "job_name": "fs-payment-service-build",
      "build_number": 1,
      "result": "SUCCESS",
      "queue_entered_at": null,
      "started_at": null,
      "finished_at": null,
      "duration_ms": 1234,
      "queue_wait_ms": null,
      "queue_item_id": 1
    }
  ],
  "total": 3,
  "limit": 50,
  "offset": 0
};

/** The one run still building. */
export const runsActive: RunPage = {
  "items": [
    {
      "id": "3bd32a1b70b64fc895366e0061a98dfe",
      "job_id": "d464117294264531bc08cd9e600aca13",
      "job_name": "pl-payment-service-build-test-deploy-staging",
      "build_number": 1,
      "result": "RUNNING",
      "queue_entered_at": null,
      "started_at": null,
      "finished_at": null,
      "duration_ms": null,
      "queue_wait_ms": null,
      "queue_item_id": 3
    }
  ],
  "total": 1,
  "limit": 50,
  "offset": 0
};

/** The failed unit tests run. */
export const runFailed: Run = {
  "id": "ad1ea2f7abdc430f9a7d2dc510484b13",
  "job_id": "59767edfb3da46f0a8cf1072d0e1a3ff",
  "job_name": "fs-payment-service-test-unit",
  "build_number": 1,
  "result": "FAILURE",
  "queue_entered_at": null,
  "started_at": "2023-11-14T22:13:20",
  "finished_at": "2023-11-14T22:13:24.321000",
  "duration_ms": 4321,
  "queue_wait_ms": null,
  "queue_item_id": null
};

/** Its log: the real jenkins-dev console output of the intentional failing test. */
export const logFailed: LogWindow = {
  "run_id": "ad1ea2f7abdc430f9a7d2dc510484b13",
  "text": "Started by upstream project \"fs-payment-service-build\" build number 8\noriginally caused by:\n Started by user Orchestrator Backend\nRunning as SYSTEM\nBuilding remotely on agent-1 (linux) in workspace /home/jenkins/agent/workspace/fs-payment-service-test-unit\n[WS-CLEANUP] Deleting project workspace...\n[WS-CLEANUP] Deferred wipeout is used...\n[WS-CLEANUP] Done\nThe recommended git tool is: NONE\nNo credentials specified\nCloning the remote Git repository\nCloning repository https://github.com/haiderali-dev/payment-service.git\n > git init /home/jenkins/agent/workspace/fs-payment-service-test-unit # timeout=10\nFetching upstream changes from https://github.com/haiderali-dev/payment-service.git\n > git --version # timeout=10\n > git --version # 'git version 2.47.3'\n > git fetch --tags --force --progress -- https://github.com/haiderali-dev/payment-service.git +refs/heads/*:refs/remotes/origin/* # timeout=10\n > git config remote.origin.url https://github.com/haiderali-dev/payment-service.git # timeout=10\n > git config --add remote.origin.fetch +refs/heads/*:refs/remotes/origin/* # timeout=10\nAvoid second fetch\n > git rev-parse refs/remotes/origin/demo/failing-tests^{commit} # timeout=10\n > git rev-parse demo/failing-tests^{commit} # timeout=10\nChecking out Revision da997c8be894b8058c9c88068295964b81f2d846 (refs/remotes/origin/demo/failing-tests)\n > git config core.sparsecheckout # timeout=10\n > git checkout -f da997c8be894b8058c9c88068295964b81f2d846 # timeout=10\nCommit message: \"fix(deploy): probe /health on a configurable host\"\n > git rev-list --no-walk 2b4e68697b5b70aef9d8f063014e0b232fe2ee97 # timeout=10\n[fs-payment-service-test-unit] $ /bin/sh -xe /tmp/jenkins13280069482653602588.sh\n+ ./scripts/build.sh\n[build] payment-service\n[build] ok\n[fs-payment-service-test-unit] $ /bin/sh -xe /tmp/jenkins5920194377541800702.sh\n+ ./scripts/test.sh unit\n[test] unit suite (about 8s)\n.......F                                                                 [100%]\n=================================== FAILURES ===================================\n___________________ test_demo_failing_tests_fails_on_purpose ___________________\n\n    def test_demo_failing_tests_fails_on_purpose() -> None:\n>       assert 1 + 1 == 3, \"intentional failure: the deploy job must never start after this\"\nE       AssertionError: intentional failure: the deploy job must never start after this\nE       assert (1 + 1) == 3\n\ntests/test_unit.py:75: AssertionError\n=============================== warnings summary ===============================\n.venv/lib/python3.13/site-packages/fastapi/testclient.py:1\n  /home/jenkins/agent/workspace/fs-payment-service-test-unit/.venv/lib/python3.13/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.\n    from starlette.testclient import TestClient as TestClient  # noqa\n\n-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html\n=========================== short test summary info ============================\nFAILED tests/test_unit.py::test_demo_failing_tests_fails_on_purpose - AssertionError: intentional failure: the deploy job must never start after this\nassert (1 + 1) == 3\n1 failed, 7 passed, 1 warning in 7.80s\nBuild step 'Execute shell' marked build as failure\nArchiving artifacts\nFinished: FAILURE\n",
  "next_offset": 3337,
  "more_data": false
};

/** The building Pipeline's log so far, with more to come. */
export const logRunning: LogWindow = {
  "run_id": "3bd32a1b70b64fc895366e0061a98dfe",
  "text": "Started by user orchestrator-bot\n[Pipeline] Start of Pipeline\n[Pipeline] stage\n[Pipeline] { (Checkout)\n",
  "next_offset": 103,
  "more_data": true
};

/** Why the unit tests failed, as the fake model words it from the facts code found. */
export const explainFailed: Answered<RunFailure> = {
  "status": 200,
  "body": {
    "run_id": "ad1ea2f7abdc430f9a7d2dc510484b13",
    "job_name": "fs-payment-service-test-unit",
    "job_type": "FREESTYLE",
    "build_number": 1,
    "result": "FAILURE",
    "url": "http://jenkins.test/job/fs-payment-service-test-unit/1/",
    "chain_id": "3e443f6652614a1ca77155dc007264c0",
    "not_started": [
      "fs-payment-service-test-integration",
      "fs-payment-service-deploy-staging"
    ],
    "facts": {
      "category": "test_failure",
      "stage": "Unit tests",
      "failed_tests": [
        "tests/test_unit.py::test_demo_failing_tests_fails_on_purpose"
      ],
      "tests_failed": 1,
      "tests_passed": 7,
      "exit_code": null,
      "skipped_stages": [],
      "evidence": [
        {
          "line": 41,
          "text": "E       AssertionError: intentional failure: the deploy job must never start after this"
        },
        {
          "line": 42,
          "text": "E       assert (1 + 1) == 3"
        },
        {
          "line": 52,
          "text": "FAILED tests/test_unit.py::test_demo_failing_tests_fails_on_purpose - AssertionError: intentional failure: the deploy job must never start after this"
        },
        {
          "line": 54,
          "text": "1 failed, 7 passed, 1 warning in 7.80s"
        }
      ]
    },
    "explanation": {
      "summary": "1 of 8 tests failed: tests/test_unit.py::test_demo_failing_tests_fails_on_purpose.",
      "cause_found": true,
      "evidence": [
        {
          "line": 41,
          "text": "E       AssertionError: intentional failure: the deploy job must never start after this"
        },
        {
          "line": 42,
          "text": "E       assert (1 + 1) == 3"
        },
        {
          "line": 52,
          "text": "FAILED tests/test_unit.py::test_demo_failing_tests_fails_on_purpose - AssertionError: intentional failure: the deploy job must never start after this"
        }
      ],
      "suggestions": [
        "Fix the failing test or the code it checks, then rerun the tests."
      ],
      "source": "model",
      "provider": "fake",
      "model": "openai/gpt-oss-120b",
      "ai_fallback": false,
      "fallback_reasons": [],
      "prompt_version": "failure_v1@90d06fc6"
    },
    "log": {
      "available": true,
      "complete": true,
      "lines": 57,
      "truncated": false,
      "redactions": 0,
      "unavailable_reason": null
    }
  }
};

/** Asking why a run that succeeded failed. */
export const explainNotFailed: Answered<ApiError> = {
  "status": 409,
  "body": {
    "error": {
      "code": "RUN_NOT_FAILED",
      "message": "This run succeeded, so there is no failure to explain.",
      "details": {
        "run_id": "2899f920d1c44cc29dcc19453cd1fe5b",
        "result": "SUCCESS"
      }
    }
  }
};

/** Statistics over no runs: nulls, never zeros. */
export const runStatsEmpty: RunStats = {
  "total_runs": 0,
  "by_result": {},
  "running": 0,
  "mean_duration_ms": null,
  "mean_queue_wait_ms": null,
  "max_queue_wait_ms": null,
  "runs_with_queue_wait": 0,
  "success_rate": null
};

/** Statistics over the three runs. */
export const runStats: RunStats = {
  "total_runs": 3,
  "by_result": {
    "FAILURE": 1,
    "RUNNING": 1,
    "SUCCESS": 1
  },
  "running": 1,
  "mean_duration_ms": 2777.5,
  "mean_queue_wait_ms": null,
  "max_queue_wait_ms": null,
  "runs_with_queue_wait": 0,
  "success_rate": 0.5
};

/** No experiment stored, as before Phase 7. */
export const experimentsEmpty: ExperimentPage = {
  "items": [],
  "total": 0,
  "limit": 50,
  "offset": 0
};

/** Two rows inserted by the capture, shaped like backend/tests/test_routers.py's: not results. */
export const experiments: ExperimentPage = {
  "items": [
    {
      "id": "dbcb82f253da4be1aafb831f2930686e",
      "label": "run-1",
      "mode": "optimized",
      "workload": "mixed-30",
      "executors": 1,
      "repetition": 1,
      "plugin_version": null,
      "jenkins_version": null,
      "workload_hash": null,
      "configuration": {},
      "started_at": null,
      "finished_at": null,
      "created_at": "2026-10-16T03:13:51.965514"
    },
    {
      "id": "bbbb02406f3e4888a9d97264f1423004",
      "label": "run-1",
      "mode": "baseline",
      "workload": "mixed-30",
      "executors": 1,
      "repetition": 1,
      "plugin_version": null,
      "jenkins_version": null,
      "workload_hash": null,
      "configuration": {},
      "started_at": null,
      "finished_at": null,
      "created_at": "2026-10-16T03:13:51.954366"
    }
  ],
  "total": 2,
  "limit": 50,
  "offset": 0
};

/** The first of them with its one metric. */
export const experimentDetail: ExperimentDetail = {
  "id": "dbcb82f253da4be1aafb831f2930686e",
  "label": "run-1",
  "mode": "optimized",
  "workload": "mixed-30",
  "executors": 1,
  "repetition": 1,
  "plugin_version": null,
  "jenkins_version": null,
  "workload_hash": null,
  "configuration": {},
  "started_at": null,
  "finished_at": null,
  "created_at": "2026-10-16T03:13:51.965514",
  "metrics": [
    {
      "name": "mean_wait",
      "band": "HIGH",
      "value": 12.5,
      "unit": "s",
      "std_dev": 1.5,
      "sample_size": 9
    }
  ]
};

/** The Admin, a deactivated Developer and a DevOps user. */
export const users: UserPage = {
  "items": [
    {
      "id": "40358f97ce83440ebd3267b6cdd24216",
      "email": "admin@example.com",
      "role": "ADMIN",
      "active": true,
      "created_at": "2026-10-16T03:13:49.323386"
    },
    {
      "id": "2c0eaa1eff2a40f29dc9dea3e983948e",
      "email": "dev2@example.com",
      "role": "DEVELOPER",
      "active": false,
      "created_at": "2026-10-16T03:13:51.047233"
    },
    {
      "id": "3fe658d6b5c044c58cd7dd4b35ea5329",
      "email": "ops@example.com",
      "role": "DEVOPS",
      "active": true,
      "created_at": "2026-10-16T03:13:51.201981"
    }
  ],
  "total": 3,
  "limit": 50,
  "offset": 0
};

/** Creating dev2@example.com. */
export const userCreated: Answered<AdminUser> = {
  "status": 201,
  "body": {
    "id": "2c0eaa1eff2a40f29dc9dea3e983948e",
    "email": "dev2@example.com",
    "role": "DEVELOPER",
    "active": true,
    "created_at": "2026-10-16T03:13:51.047233Z"
  }
};

/** Deactivating dev2@example.com. */
export const userUpdated: Answered<AdminUser> = {
  "status": 200,
  "body": {
    "id": "2c0eaa1eff2a40f29dc9dea3e983948e",
    "email": "dev2@example.com",
    "role": "DEVELOPER",
    "active": false,
    "created_at": "2026-10-16T03:13:51.047233"
  }
};

/** Creating dev2@example.com again. */
export const userDuplicate: Answered<ApiError> = {
  "status": 409,
  "body": {
    "error": {
      "code": "VALIDATION_FAILED",
      "message": "A user with that email already exists.",
      "details": {
        "email": "dev2@example.com"
      }
    }
  }
};

/** Creating a user with a five-character password. */
export const userShortPassword: Answered<ApiError> = {
  "status": 422,
  "body": {
    "error": {
      "code": "VALIDATION_FAILED",
      "message": "Some fields need attention.",
      "details": {
        "fields": {
          "password": "String should have at least 12 characters"
        }
      }
    }
  }
};

/** The Admin demoting themselves. */
export const userSelfDemote: Answered<ApiError> = {
  "status": 409,
  "body": {
    "error": {
      "code": "VALIDATION_FAILED",
      "message": "You cannot remove your own administrator access. Ask another admin to do it.",
      "details": {
        "user_id": "40358f97ce83440ebd3267b6cdd24216"
      }
    }
  }
};

/** A Developer asking for the users. */
export const forbidden: Answered<ApiError> = {
  "status": 403,
  "body": {
    "error": {
      "code": "FORBIDDEN",
      "message": "This action needs the ADMIN role. Yours is DEVELOPER.",
      "details": {
        "required_role": "ADMIN",
        "actual_role": "DEVELOPER"
      }
    }
  }
};

/** A Developer asking for a resync. */
export const resyncForbidden: Answered<ApiError> = {
  "status": 403,
  "body": {
    "error": {
      "code": "FORBIDDEN",
      "message": "This action needs the ADMIN role. Yours is DEVELOPER.",
      "details": {
        "required_role": "ADMIN",
        "actual_role": "DEVELOPER"
      }
    }
  }
};

/** The roles, weakest first. */
export const roles: string[] = [
  "DEVELOPER",
  "DEVOPS",
  "ADMIN"
];

/** 4.5.5's rules and the configured HIGH quota. */
export const policy: Policy = {
  "high_urgency_daily_quota": 3,
  "production_enabled": false,
  "rules": [
    {
      "rule": "Deploy to staging",
      "developer": "Allowed",
      "devops": "Allowed",
      "admin": "Allowed"
    },
    {
      "rule": "Deploy to production",
      "developer": "Refused",
      "devops": "Refused",
      "admin": "Refused (disabled for this project)"
    },
    {
      "rule": "HIGH urgency",
      "developer": "Needs a justification; quota per day, then downgraded to MEDIUM",
      "devops": "Allowed",
      "admin": "Allowed"
    },
    {
      "rule": "Custom shell steps",
      "developer": "Refused",
      "devops": "Allowed, flagged in the preview",
      "admin": "Allowed, flagged in the preview"
    },
    {
      "rule": "New request while the same service's chain is running",
      "developer": "Refused, with the running chain linked",
      "devops": "Same",
      "admin": "May cancel the running chain first"
    }
  ],
  "editable": false
};

/** What the capture did, newest first. */
export const audit: AuditPage = {
  "items": [
    {
      "id": "805fef4056374536838ba3604db94b18",
      "actor_id": "40358f97ce83440ebd3267b6cdd24216",
      "actor_email": "admin@example.com",
      "action": "admin.user.updated",
      "target": "dev2@example.com",
      "details": {
        "active": {
          "from": true,
          "to": false
        }
      },
      "created_at": "2026-10-16T03:13:51.256868"
    },
    {
      "id": "f4762c66125349e6b0c63680e1c7dcb1",
      "actor_id": "40358f97ce83440ebd3267b6cdd24216",
      "actor_email": "admin@example.com",
      "action": "admin.user.created",
      "target": "ops@example.com",
      "details": {
        "role": "DEVOPS"
      },
      "created_at": "2026-10-16T03:13:51.215222"
    },
    {
      "id": "a46d88780b6a4873a4630249b1a82049",
      "actor_id": "40358f97ce83440ebd3267b6cdd24216",
      "actor_email": "admin@example.com",
      "action": "admin.user.created",
      "target": "dev2@example.com",
      "details": {
        "role": "DEVELOPER"
      },
      "created_at": "2026-10-16T03:13:51.050134"
    },
    {
      "id": "6edbd268fdfd4833ac6d721e4c21cdcb",
      "actor_id": "40358f97ce83440ebd3267b6cdd24216",
      "actor_email": "admin@example.com",
      "action": "job.saved",
      "target": "pl-payment-service-build-test-deploy-staging",
      "details": {
        "pipeline_id": "298eea9af22441c1a810fe2068090912",
        "position": 0
      },
      "created_at": "2026-10-16T03:13:50.587316"
    },
    {
      "id": "dd574f68eb7e476fa0062498201d93c8",
      "actor_id": "40358f97ce83440ebd3267b6cdd24216",
      "actor_email": "admin@example.com",
      "action": "pipeline.approved",
      "target": "pipeline:298eea9af22441c1a810fe2068090912",
      "details": {
        "command_id": "6815ad38aa0540858295edac28927908",
        "chain_id": "1e18b7e9b3c342889564407ef2e56d3e",
        "jobs": [
          "pl-payment-service-build-test-deploy-staging"
        ],
        "first_job": "pl-payment-service-build-test-deploy-staging",
        "queue_item_id": 3,
        "parameters": {
          "BRANCH": "main",
          "COMMIT": "3f786850e387550fdab836ed7e6dc881de23001b"
        },
        "priority": "MEDIUM",
        "approved_at": "2026-10-16T03:13:50.574908+00:00"
      },
      "created_at": "2026-10-16T03:13:50.587316"
    },
    {
      "id": "bab4f68b8c1a4e73b079a23e07782c37",
      "actor_id": "40358f97ce83440ebd3267b6cdd24216",
      "actor_email": "admin@example.com",
      "action": "job.saved",
      "target": "fs-auth-service-build",
      "details": {
        "pipeline_id": "9871ff6c6b454518860c7a4723b44de4",
        "position": 0
      },
      "created_at": "2026-10-16T03:13:50.359821"
    },
    {
      "id": "05b86f65f0e24d8a9464e3a7f839a95b",
      "actor_id": "40358f97ce83440ebd3267b6cdd24216",
      "actor_email": "admin@example.com",
      "action": "pipeline.approved",
      "target": "pipeline:9871ff6c6b454518860c7a4723b44de4",
      "details": {
        "command_id": "1bf37ca144b541dfb119ad07d7a7fa79",
        "chain_id": "4b786a2b2ad743b19f1801cb4e9807c8",
        "jobs": [
          "fs-auth-service-build"
        ],
        "first_job": "fs-auth-service-build",
        "queue_item_id": 2,
        "parameters": {
          "BRANCH": "main",
          "COMMIT": "refs/heads/main"
        },
        "priority": "MEDIUM",
        "approved_at": "2026-10-16T03:13:50.343971+00:00"
      },
      "created_at": "2026-10-16T03:13:50.359821"
    },
    {
      "id": "9ed18e0f67604ed8bb5b5673173b62c1",
      "actor_id": "40358f97ce83440ebd3267b6cdd24216",
      "actor_email": "admin@example.com",
      "action": "job.saved",
      "target": "fs-payment-service-deploy-staging",
      "details": {
        "pipeline_id": "6d1f2731cf784a9287a07e09059ee2a9",
        "position": 3
      },
      "created_at": "2026-10-16T03:13:49.938497"
    },
    {
      "id": "434cf6c8152046fa9da6559092622dcf",
      "actor_id": "40358f97ce83440ebd3267b6cdd24216",
      "actor_email": "admin@example.com",
      "action": "job.saved",
      "target": "fs-payment-service-test-integration",
      "details": {
        "pipeline_id": "6d1f2731cf784a9287a07e09059ee2a9",
        "position": 2
      },
      "created_at": "2026-10-16T03:13:49.938497"
    },
    {
      "id": "5d23674eff3a490aa71cc420f6fa01ab",
      "actor_id": "40358f97ce83440ebd3267b6cdd24216",
      "actor_email": "admin@example.com",
      "action": "job.saved",
      "target": "fs-payment-service-test-unit",
      "details": {
        "pipeline_id": "6d1f2731cf784a9287a07e09059ee2a9",
        "position": 1
      },
      "created_at": "2026-10-16T03:13:49.938497"
    },
    {
      "id": "c93cbc53d7794aa2aaca5b3111e7bd62",
      "actor_id": "40358f97ce83440ebd3267b6cdd24216",
      "actor_email": "admin@example.com",
      "action": "job.saved",
      "target": "fs-payment-service-build",
      "details": {
        "pipeline_id": "6d1f2731cf784a9287a07e09059ee2a9",
        "position": 0
      },
      "created_at": "2026-10-16T03:13:49.938497"
    },
    {
      "id": "d3f6afe8c8d54eb7bd0d9a8e0e053ccc",
      "actor_id": "40358f97ce83440ebd3267b6cdd24216",
      "actor_email": "admin@example.com",
      "action": "pipeline.approved",
      "target": "pipeline:6d1f2731cf784a9287a07e09059ee2a9",
      "details": {
        "command_id": "b1b3060a62e04fc68de27da1b877813a",
        "chain_id": "3e443f6652614a1ca77155dc007264c0",
        "jobs": [
          "fs-payment-service-build",
          "fs-payment-service-test-unit",
          "fs-payment-service-test-integration",
          "fs-payment-service-deploy-staging"
        ],
        "first_job": "fs-payment-service-build",
        "queue_item_id": 1,
        "parameters": {
          "BRANCH": "main",
          "COMMIT": "3f786850e387550fdab836ed7e6dc881de23001b"
        },
        "priority": "MEDIUM",
        "approved_at": "2026-10-16T03:13:49.921300+00:00"
      },
      "created_at": "2026-10-16T03:13:49.938497"
    },
    {
      "id": "c7f0d7759d094421b78ad7b6f40f073a",
      "actor_id": "40358f97ce83440ebd3267b6cdd24216",
      "actor_email": "admin@example.com",
      "action": "auth.login",
      "target": "admin@example.com",
      "details": {
        "client": "127.0.0.1"
      },
      "created_at": "2026-10-16T03:13:49.498666"
    }
  ],
  "total": 13,
  "limit": 50,
  "offset": 0
};

/** The repository's catalog. */
export const services: ServiceList = {
  "items": [
    {
      "name": "payment-service",
      "repo": "https://github.com/haiderali-dev/payment-service.git",
      "default_branch": "main",
      "agent_label": "linux",
      "test_suites": [
        {
          "name": "unit",
          "approx_seconds": 8
        },
        {
          "name": "integration",
          "approx_seconds": 20
        }
      ],
      "allowed_environments": [
        "staging"
      ],
      "extra_stages": [
        "lint",
        "security_scan"
      ]
    },
    {
      "name": "auth-service",
      "repo": "https://github.com/haiderali-dev/auth-service.git",
      "default_branch": "main",
      "agent_label": "linux",
      "test_suites": [
        {
          "name": "unit",
          "approx_seconds": 6
        }
      ],
      "allowed_environments": [
        "staging"
      ],
      "extra_stages": [
        "lint"
      ]
    }
  ],
  "suite_names": [
    "integration",
    "unit"
  ],
  "environments": [
    "staging"
  ],
  "extra_stages": [
    "lint",
    "security_scan"
  ]
};

/** payment-service's branches, from the fake Git remote. */
export const branchesPayment: Branches = {
  "service": "payment-service",
  "default_branch": "main",
  "branches": [
    "demo/failing-tests",
    "main"
  ],
  "available": true,
  "unavailable_reason": null
};

/** auth-service's repository not answering. */
export const branchesAuthUnreachable: Branches = {
  "service": "auth-service",
  "default_branch": "main",
  "branches": [],
  "available": false,
  "unavailable_reason": "The repository could not be reached."
};

/** An Admin's resync of the catalog file. */
export const resync: Answered<Resync> = {
  "status": 200,
  "body": {
    "created": 2,
    "updated": 0
  }
};

/** Fake LLM mode: the provider is disabled. */
export const healthFake: Health = {
  "status": "up",
  "version": "0.1.0",
  "environment": "test",
  "components": {
    "database": {
      "status": "up",
      "detail": "reachable",
      "latency_ms": 1
    },
    "jenkins": {
      "status": "up",
      "detail": "Jenkins 2.568.3",
      "latency_ms": 0
    },
    "llm": {
      "status": "disabled",
      "detail": "fake provider; no network calls",
      "latency_ms": 0
    }
  }
};

/** Live mode with a key: the configured model chain. */
export const healthLive: Health = {
  "status": "up",
  "version": "0.1.0",
  "environment": "test",
  "components": {
    "database": {
      "status": "up",
      "detail": "reachable",
      "latency_ms": 1
    },
    "jenkins": {
      "status": "up",
      "detail": "Jenkins 2.568.3",
      "latency_ms": 0
    },
    "llm": {
      "status": "up",
      "detail": "live; chain openai/gpt-oss-120b -> openai/gpt-oss-20b",
      "latency_ms": 0
    }
  }
};

/** Live mode without a key: the provider is down. Recaptured on 2026-10-18: the detail no longer
 * carries the exception's type (security review, finding 10). */
export const healthLiveNoKey: Answered<Health> = {
  "status": 200,
  "body": {
    "status": "up",
    "version": "0.1.0",
    "environment": "test",
    "components": {
      "database": {
        "status": "up",
        "detail": "reachable",
        "latency_ms": 0,
        "last_outcome": null,
        "last_call_at": null
      },
      "jenkins": {
        "status": "up",
        "detail": "Jenkins 2.568.3",
        "latency_ms": 0,
        "last_outcome": null,
        "last_call_at": null
      },
      "llm": {
        "status": "down",
        "detail": "LLM_MODE=live but GROQ_API_KEY is empty",
        "latency_ms": 0,
        "last_outcome": null,
        "last_call_at": null
      }
    }
  }
};

/** Live mode, the latest model call answered (captured 2026-10-18; found in T6.7). */
export const healthLiveAnswered: Answered<Health> = {
  "status": 200,
  "body": {
    "status": "up",
    "version": "0.1.0",
    "environment": "test",
    "components": {
      "database": {
        "status": "up",
        "detail": "reachable",
        "latency_ms": 0,
        "last_outcome": null,
        "last_call_at": null
      },
      "jenkins": {
        "status": "up",
        "detail": "Jenkins 2.568.3",
        "latency_ms": 0,
        "last_outcome": null,
        "last_call_at": null
      },
      "llm": {
        "status": "up",
        "detail": "live; chain openai/gpt-oss-120b -> openai/gpt-oss-20b",
        "latency_ms": 0,
        "last_outcome": "ok",
        "last_call_at": "2026-10-18T18:17:32.826037"
      }
    }
  }
};

/** Live mode, the latest model call was rate limited, so the provider is degraded. */
export const healthLiveFailed: Answered<Health> = {
  "status": 200,
  "body": {
    "status": "up",
    "version": "0.1.0",
    "environment": "test",
    "components": {
      "database": {
        "status": "up",
        "detail": "reachable",
        "latency_ms": 0,
        "last_outcome": null,
        "last_call_at": null
      },
      "jenkins": {
        "status": "up",
        "detail": "Jenkins 2.568.3",
        "latency_ms": 0,
        "last_outcome": null,
        "last_call_at": null
      },
      "llm": {
        "status": "degraded",
        "detail": "live; chain openai/gpt-oss-120b -> openai/gpt-oss-20b",
        "latency_ms": 0,
        "last_outcome": "rate_limited",
        "last_call_at": "2026-10-18T18:17:33.268698"
      }
    }
  }
};

/** The queue the queued chain waits in. */
export const queue: Queue = {
  "available": true,
  "optimizer_enabled": true,
  "queue_length": 3,
  "weights": {
    "urgency": 0.5,
    "dependency": 0.3,
    "executionTime": 0.2
  },
  "items": [
    {
      "rank": 1,
      "item_id": 1370,
      "job_name": "fs-auth-service-build",
      "job_type": "FreeStyleProject",
      "level": "HIGH",
      "score": 0.671179,
      "components": {
        "urgency": 1,
        "dependency": 0,
        "execution_time": 0.855893,
        "aging_bonus": 0,
        "base_score": 0.671179,
        "own_score": 0.671179
      },
      "estimate_seconds": 3.605,
      "wait_seconds": 6.182,
      "group_id": "it-revision-freestyle",
      "topological_rank": 0,
      "blocked_reason": "Executor slot already in use",
      "unresolved_dependencies": []
    },
    {
      "rank": 2,
      "item_id": 1369,
      "job_name": "it-revision-probe-freestyle",
      "job_type": "FreeStyleProject",
      "level": "MEDIUM",
      "score": 0.477962,
      "components": {
        "urgency": 0.6,
        "dependency": 0,
        "execution_time": 0.889811,
        "aging_bonus": 0,
        "base_score": 0.477962,
        "own_score": 0.477962
      },
      "estimate_seconds": 2.853,
      "wait_seconds": 6.204,
      "group_id": "it-revision-probe-freestyle",
      "topological_rank": 0,
      "blocked_reason": "Executor slot already in use",
      "unresolved_dependencies": []
    },
    {
      "rank": 3,
      "item_id": 1365,
      "job_name": "it-failure-payment-service-test-unit",
      "job_type": "FreeStyleProject",
      "level": "MEDIUM",
      "score": 0.3,
      "components": {
        "urgency": 0.6,
        "dependency": 0,
        "execution_time": 0,
        "aging_bonus": 0,
        "base_score": 0.3,
        "own_score": 0.3
      },
      "estimate_seconds": 22.581,
      "wait_seconds": 6.296,
      "group_id": "it-failure-payment-service-test-unit",
      "topological_rank": 0,
      "blocked_reason": "Executor slot already in use",
      "unresolved_dependencies": []
    }
  ],
  "unscored_items": [],
  "unavailable_reason": null
};

// Captured on 2026-10-18 the same way, after the hardening added an Admin's password reset and
// the rate limits for the Admin page.
export const limits: RateLimit[] = [
  {
    "name": "login",
    "capacity": 5,
    "per_seconds": 60.0,
    "applies_to": "sign-in, per address and account"
  },
  {
    "name": "login-address",
    "capacity": 30,
    "per_seconds": 60.0,
    "applies_to": "sign-in, per address across accounts"
  },
  {
    "name": "refresh",
    "capacity": 30,
    "per_seconds": 60.0,
    "applies_to": "session renewal, per address"
  },
  {
    "name": "api",
    "capacity": 300,
    "per_seconds": 60.0,
    "applies_to": "every signed-in request, per user"
  },
  {
    "name": "assistant",
    "capacity": 20,
    "per_seconds": 60.0,
    "applies_to": "assistant messages, generation and explanations, per user"
  }
];

export const passwordReset: Answered<AdminUser> = {
  "status": 200,
  "body": {
    "id": "006ef6e6927a4cbd8a63a3289c89bbad",
    "email": "dev@example.com",
    "role": "DEVELOPER",
    "active": true,
    "created_at": "2026-10-18T18:14:16.472126"
  }
};

export const passwordTooShort: Answered<ApiError> = {
  "status": 422,
  "body": {
    "error": {
      "code": "VALIDATION_FAILED",
      "message": "Some fields need attention.",
      "details": {
        "fields": {
          "password": "String should have at least 12 characters"
        }
      }
    }
  }
};
