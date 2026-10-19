/**
 * Real responses from GET /api/queue, captured on 2026-10-16. Each ranking is one the live plugin
 * returned on jenkins-dev on 2026-10-15 (backend/tests/data/plugin/, recorded verbatim), passed
 * through the backend's own parser and endpoint. Generated from the JSON by a script, not written
 * by hand.
 *
 * Typed by what the client returns, so a backend change that alters the shape fails to compile
 * here first.
 *
 * `held_items` was added on 2026-10-20, when the backend began sending it: these rankings predate
 * the plugin's heldItems, so for them the backend sends an empty list, as written here.
 */

import type { Queue } from "@/api/queueApi";

/** Three waiting freestyle items, one HIGH and two MEDIUM, each waiting for an executor. */
export const threeWaiting: Queue = {
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
      "job_name": "it-revision-freestyle",
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
  "held_items": [],
  "unavailable_reason": null
};

/** A dependency group of two, the MEDIUM upstream inheriting its HIGH downstream's score, and three Pipeline items not yet scored. */
export const group: Queue = {
  "available": true,
  "optimizer_enabled": true,
  "queue_length": 8,
  "weights": {
    "urgency": 0.5,
    "dependency": 0.3,
    "executionTime": 0.2
  },
  "items": [
    {
      "rank": 1,
      "item_id": 1395,
      "job_name": "it-revision-upstream",
      "job_type": "FreeStyleProject",
      "level": "MEDIUM",
      "score": 0.979994,
      "components": {
        "urgency": 0.6,
        "dependency": 1,
        "execution_time": 1,
        "aging_bonus": 0,
        "base_score": 0.8,
        "own_score": 0.8
      },
      "estimate_seconds": 0.226,
      "wait_seconds": 6.642,
      "group_id": "it-revision-upstream",
      "topological_rank": 0,
      "blocked_reason": "Waiting for next available executor on \u2018linux\u2019",
      "unresolved_dependencies": []
    },
    {
      "rank": 2,
      "item_id": 1396,
      "job_name": "it-revision-freestyle",
      "job_type": "FreeStyleProject",
      "level": "HIGH",
      "score": 0.979994,
      "components": {
        "urgency": 1,
        "dependency": 1,
        "execution_time": 0.89997,
        "aging_bonus": 0,
        "base_score": 0.979994,
        "own_score": 0.979994
      },
      "estimate_seconds": 3.535,
      "wait_seconds": 6.624,
      "group_id": "it-revision-upstream",
      "topological_rank": 1,
      "blocked_reason": "Waiting for next available executor on \u2018linux\u2019",
      "unresolved_dependencies": []
    },
    {
      "rank": 3,
      "item_id": 1394,
      "job_name": "it-freestyle-create-trigger-read",
      "job_type": "FreeStyleProject",
      "level": "HIGH",
      "score": 0.697279,
      "components": {
        "urgency": 1,
        "dependency": 0,
        "execution_time": 0.986397,
        "aging_bonus": 0,
        "base_score": 0.697279,
        "own_score": 0.697279
      },
      "estimate_seconds": 0.676,
      "wait_seconds": 7.189,
      "group_id": "it-freestyle-create-trigger-read",
      "topological_rank": 0,
      "blocked_reason": "Waiting for next available executor on \u2018linux\u2019",
      "unresolved_dependencies": []
    },
    {
      "rank": 4,
      "item_id": 1393,
      "job_name": "it-revision-probe-freestyle",
      "job_type": "FreeStyleProject",
      "level": "MEDIUM",
      "score": 0.484655,
      "components": {
        "urgency": 0.6,
        "dependency": 0,
        "execution_time": 0.923277,
        "aging_bonus": 0,
        "base_score": 0.484655,
        "own_score": 0.484655
      },
      "estimate_seconds": 2.764,
      "wait_seconds": 7.207,
      "group_id": "it-revision-probe-freestyle",
      "topological_rank": 0,
      "blocked_reason": "Waiting for next available executor on \u2018linux\u2019",
      "unresolved_dependencies": []
    },
    {
      "rank": 5,
      "item_id": 1389,
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
      "estimate_seconds": 33.306,
      "wait_seconds": 7.289,
      "group_id": "it-failure-payment-service-test-unit",
      "topological_rank": 0,
      "blocked_reason": "Waiting for next available executor on \u2018linux\u2019",
      "unresolved_dependencies": []
    }
  ],
  "unscored_items": [
    {
      "item_id": 1390,
      "job_name": "it-pipeline-create-trigger-read",
      "reason": "not scored by the optimizer"
    },
    {
      "item_id": 1391,
      "job_name": "it-revision-pipeline",
      "reason": "not scored by the optimizer"
    },
    {
      "item_id": 1392,
      "job_name": "it-revision-probe-pipeline",
      "reason": "not scored by the optimizer"
    }
  ],
  "held_items": [],
  "unavailable_reason": null
};

/** One item that has waited five minutes, with its aging bonus. */
export const aged: Queue = {
  "available": true,
  "optimizer_enabled": true,
  "queue_length": 1,
  "weights": {
    "urgency": 0.5,
    "dependency": 0.3,
    "executionTime": 0.2
  },
  "items": [
    {
      "rank": 1,
      "item_id": 1376,
      "job_name": "it-failure-payment-service-test-unit",
      "job_type": "FreeStyleProject",
      "level": "MEDIUM",
      "score": 0.35,
      "components": {
        "urgency": 0.6,
        "dependency": 0,
        "execution_time": 0,
        "aging_bonus": 0.05,
        "base_score": 0.3,
        "own_score": 0.35
      },
      "estimate_seconds": 28.418,
      "wait_seconds": 300.755,
      "group_id": "it-failure-payment-service-test-unit",
      "topological_rank": 0,
      "blocked_reason": "Waiting for next available executor on \u2018linux\u2019",
      "unresolved_dependencies": []
    }
  ],
  "unscored_items": [],
  "held_items": [],
  "unavailable_reason": null
};

/** The three waiting items with the plugin's optimizerEnabled set to false. */
export const optimizerOff: Queue = {
  "available": true,
  "optimizer_enabled": false,
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
      "job_name": "it-revision-freestyle",
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
  "held_items": [],
  "unavailable_reason": null
};

/** Nothing waiting. */
export const empty: Queue = {
  "available": true,
  "optimizer_enabled": true,
  "queue_length": 0,
  "weights": {
    "urgency": 0.5,
    "dependency": 0.3,
    "executionTime": 0.2
  },
  "items": [],
  "unscored_items": [],
  "held_items": [],
  "unavailable_reason": null
};

/** The plugin cannot be read, with the real client's reason for a 404. */
export const unavailable: Queue = {
  "available": false,
  "optimizer_enabled": false,
  "queue_length": 0,
  "weights": {},
  "items": [],
  "unscored_items": [],
  "held_items": [],
  "unavailable_reason": "the plugin is not installed on this controller"
};

/** A job held for its upstream: the live recording of 2026-10-20 (ranking-held.json) through the
 * backend's parser and endpoint, captured the same day. Nothing is ranked; one job is held. */
export const heldForUpstream: Queue = {
  "available": true,
  "optimizer_enabled": true,
  "queue_length": 0,
  "weights": {
    "urgency": 0.5,
    "dependency": 0.3,
    "executionTime": 0.2
  },
  "items": [],
  "unscored_items": [],
  "held_items": [
    {
      "item_id": 1587,
      "job_name": "it-held-downstream",
      "level": "HIGH",
      "reason": "Waiting for upstream job 'it-held-upstream' (building) to finish.",
      "upstream": "it-held-upstream",
      "upstream_state": "building",
      "wait_seconds": 8.169
    }
  ],
  "unavailable_reason": null
};
