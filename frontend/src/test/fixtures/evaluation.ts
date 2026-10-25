/**
 * Real responses from GET /api/analytics/evaluation, captured on 2026-10-25 from the backend in its
 * test configuration. The first serves eval/results/report.json as `python -m eval report` wrote it
 * after the rule baseline's runs and a 20-item gpt-oss-120b run on eval-v1; the second is the
 * answer when no report exists. Generated from the JSON by a script, not written by hand.
 */

import type { Evaluation } from "@/api/analyticsApi";

export const evaluation: Evaluation = {
  "available": true,
  "detail": null,
  "generated_at": "2026-10-25T00:02:44.875363Z",
  "provenance": {
    "labels": "machine",
    "statement": "Gold labels were written by Claude Code, an AI assistant, and checked against the dataset card's rules by code; no person has reviewed them (docs/decisions.md D-081). These figures measure agreement with those labels."
  },
  "dataset": {
    "name": "eval-v1",
    "items": 250,
    "sha256": "31559fed8225979eab3d7bf532b54062661056717c7936fffdaa15a390596428",
    "labels": "machine",
    "reviewed_by_a_person": 0,
    "decision": "D-081",
    "splits": {
      "dev": 100,
      "test": 150
    },
    "sources": [
      {
        "id": "authored",
        "name": "Written for this dataset by Claude Code",
        "licence": "the project's own"
      },
      {
        "id": "bp-4.6.5",
        "name": "BUILD_PROMPT.md 4.6.5, the commands version 1 must handle",
        "licence": "the project's own"
      },
      {
        "id": "phase-4-draft",
        "name": "eval/datasets/sample.jsonl, drafted in Phase 4",
        "licence": "the project's own"
      },
      {
        "id": "clinc150",
        "name": "CLINC150 (clinc/clinc_oos), out-of-scope queries, test split",
        "licence": "CC BY 3.0"
      },
      {
        "id": "deepset-pi",
        "name": "deepset/prompt-injections, label 1 (injection), train split",
        "licence": "Apache-2.0"
      },
      {
        "id": "deepset-pi+",
        "name": "deepset/prompt-injections payloads after an authored request",
        "licence": "Apache-2.0"
      }
    ]
  },
  "comparison": [
    {
      "run": "eval-v1-test__rules",
      "parser": "rules",
      "complete": true,
      "labels": "machine",
      "n": 150,
      "errors": 0,
      "action_accuracy": 0.8333,
      "exact_match": 0.7267,
      "behavior_accuracy": 0.8533,
      "clarification_precision": 0.8056,
      "clarification_recall": 0.8788,
      "refusal_rate": 1.0,
      "latency_p50_ms": 0,
      "latency_p95_ms": 0,
      "tokens_per_command": 0.0,
      "per_field_accuracy": {
        "action": 0.8333,
        "service": 0.9867,
        "branch": 0.9533,
        "commit": 0.9733,
        "environment": 0.9933,
        "test_suite": 0.96,
        "urgency": 0.9933,
        "extra_stages": 1.0,
        "justification": 1.0
      },
      "behavior_by_category": {
        "clear": 0.9,
        "paraphrase_typos": 0.6667,
        "missing_field": 0.913,
        "ambiguous": 0.8,
        "unsafe_out_of_scope": 1.0,
        "prompt_injection": 0.8571
      }
    }
  ],
  "plans": [],
  "ablations": null,
  "e2e": [],
  "runs": [
    {
      "run": "eval-v1-ablation__rules",
      "parser": "rules",
      "scope": "ablation",
      "configuration": "full",
      "labels": "machine",
      "for_reporting": true,
      "complete": true,
      "stopped_reason": null,
      "n": 75
    },
    {
      "run": "eval-v1-dev__rules",
      "parser": "rules",
      "scope": "dev",
      "configuration": "full",
      "labels": "machine",
      "for_reporting": true,
      "complete": true,
      "stopped_reason": null,
      "n": 100
    },
    {
      "run": "eval-v1-e2e__groq-openai-gpt-oss-120b",
      "parser": "groq:openai/gpt-oss-120b",
      "scope": "e2e",
      "configuration": "full",
      "labels": "machine",
      "for_reporting": true,
      "complete": true,
      "stopped_reason": null,
      "n": 20
    },
    {
      "run": "eval-v1-test__rules",
      "parser": "rules",
      "scope": "test",
      "configuration": "full",
      "labels": "machine",
      "for_reporting": true,
      "complete": true,
      "stopped_reason": null,
      "n": 150
    },
    {
      "run": "sample__rules",
      "parser": "rules",
      "scope": "all",
      "configuration": "full",
      "labels": null,
      "for_reporting": true,
      "complete": true,
      "stopped_reason": null,
      "n": 0
    },
    {
      "run": "smoke__rules",
      "parser": "rules",
      "scope": "all",
      "configuration": "full",
      "labels": null,
      "for_reporting": false,
      "complete": true,
      "stopped_reason": null,
      "n": 30
    }
  ]
};

export const evaluationUnavailable: Evaluation = {
  "available": false,
  "detail": "No evaluation report has been generated yet. Run `python -m eval report` after the evaluation runs.",
  "generated_at": null,
  "provenance": null,
  "dataset": null,
  "comparison": [],
  "plans": [],
  "ablations": null,
  "e2e": [],
  "runs": []
};
