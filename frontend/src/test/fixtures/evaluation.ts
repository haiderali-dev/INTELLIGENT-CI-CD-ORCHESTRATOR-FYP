/**
 * Evaluation payload generated on 2026-10-25 from the archived report and validated against the
 * backend's EvaluationResponse schema. It includes all four test comparisons, all ablations and
 * the real 20-command end-to-end result. The second payload is the answer when no report exists.
 */

import type { Evaluation } from "@/api/analyticsApi";

export const evaluation: Evaluation = {
  "available": true,
  "detail": null,
  "generated_at": "2026-10-25T15:31:29.703270Z",
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
      "refusal_rate": 1,
      "latency_p50_ms": 0,
      "latency_p95_ms": 0,
      "tokens_per_command": 0,
      "per_field_accuracy": {
        "action": 0.8333,
        "service": 0.9867,
        "branch": 0.9533,
        "commit": 0.9733,
        "environment": 0.9933,
        "test_suite": 0.96,
        "urgency": 0.9933,
        "extra_stages": 1,
        "justification": 1
      },
      "behavior_by_category": {
        "clear": 0.9,
        "paraphrase_typos": 0.6667,
        "missing_field": 0.913,
        "ambiguous": 0.8,
        "unsafe_out_of_scope": 1,
        "prompt_injection": 0.8571
      }
    },
    {
      "run": "eval-v1-test__groq-openai-gpt-oss-120b",
      "parser": "groq:openai/gpt-oss-120b",
      "complete": true,
      "labels": "machine",
      "n": 150,
      "errors": 0,
      "action_accuracy": 0.9867,
      "exact_match": 0.9067,
      "behavior_accuracy": 0.96,
      "clarification_precision": 0.8857,
      "clarification_recall": 0.9394,
      "refusal_rate": 1,
      "latency_p50_ms": 349,
      "latency_p95_ms": 948,
      "tokens_per_command": 1796.7,
      "per_field_accuracy": {
        "action": 0.9867,
        "service": 0.9733,
        "branch": 0.9933,
        "commit": 1,
        "environment": 1,
        "test_suite": 0.98,
        "urgency": 1,
        "extra_stages": 0.9867,
        "justification": 0.98
      },
      "behavior_by_category": {
        "clear": 0.9833,
        "paraphrase_typos": 0.9,
        "missing_field": 0.9565,
        "ambiguous": 0.9333,
        "unsafe_out_of_scope": 1,
        "prompt_injection": 1
      }
    },
    {
      "run": "eval-v1-test__groq-openai-gpt-oss-20b",
      "parser": "groq:openai/gpt-oss-20b",
      "complete": true,
      "labels": "machine",
      "n": 148,
      "errors": 2,
      "action_accuracy": 0.9324,
      "exact_match": 0.8176,
      "behavior_accuracy": 0.9122,
      "clarification_precision": 0.8571,
      "clarification_recall": 0.7273,
      "refusal_rate": 1,
      "latency_p50_ms": 469,
      "latency_p95_ms": 873,
      "tokens_per_command": 1789.8,
      "per_field_accuracy": {
        "action": 0.9324,
        "service": 0.9797,
        "branch": 0.9932,
        "commit": 0.9932,
        "environment": 0.9459,
        "test_suite": 0.9662,
        "urgency": 0.9865,
        "extra_stages": 0.9932,
        "justification": 0.9797
      },
      "behavior_by_category": {
        "clear": 0.9483,
        "paraphrase_typos": 0.9667,
        "missing_field": 0.7391,
        "ambiguous": 0.8,
        "unsafe_out_of_scope": 1,
        "prompt_injection": 1
      }
    },
    {
      "run": "eval-v1-test__groq-qwen-qwen3.8-27b",
      "parser": "groq:qwen/qwen3.8-27b",
      "complete": true,
      "labels": "machine",
      "n": 150,
      "errors": 0,
      "action_accuracy": 0.9133,
      "exact_match": 0.6467,
      "behavior_accuracy": 0.94,
      "clarification_precision": 0.9032,
      "clarification_recall": 0.8485,
      "refusal_rate": 1,
      "latency_p50_ms": 678,
      "latency_p95_ms": 1624,
      "tokens_per_command": 1618.3,
      "per_field_accuracy": {
        "action": 0.9133,
        "service": 0.98,
        "branch": 0.8267,
        "commit": 0.9533,
        "environment": 0.9867,
        "test_suite": 0.9667,
        "urgency": 0.98,
        "extra_stages": 0.98,
        "justification": 1
      },
      "behavior_by_category": {
        "clear": 0.9667,
        "paraphrase_typos": 0.9667,
        "missing_field": 0.8696,
        "ambiguous": 0.8667,
        "unsafe_out_of_scope": 1,
        "prompt_injection": 0.8571
      }
    }
  ],
  "plans": [
    {
      "run": "eval-v1-test__groq-openai-gpt-oss-120b",
      "parser": "groq:openai/gpt-oss-120b",
      "max_repairs": 2,
      "plannable_items": 74,
      "n": 74,
      "valid_before_repair": 1,
      "valid_after_repair": 1,
      "repaired": 0,
      "still_invalid": 0,
      "no_model_plan": 0,
      "errors": 0,
      "distinct_requests": 20,
      "tokens_per_plan": 1695.5
    },
    {
      "run": "eval-v1-test__groq-openai-gpt-oss-20b",
      "parser": "groq:openai/gpt-oss-20b",
      "max_repairs": 2,
      "plannable_items": 74,
      "n": 74,
      "valid_before_repair": 0.8784,
      "valid_after_repair": 1,
      "repaired": 9,
      "still_invalid": 0,
      "no_model_plan": 0,
      "errors": 0,
      "distinct_requests": 20,
      "tokens_per_plan": 1880.5
    },
    {
      "run": "eval-v1-test__groq-qwen-qwen3.8-27b",
      "parser": "groq:qwen/qwen3.8-27b",
      "max_repairs": 2,
      "plannable_items": 74,
      "n": 74,
      "valid_before_repair": 1,
      "valid_after_repair": 1,
      "repaired": 0,
      "still_invalid": 0,
      "no_model_plan": 0,
      "errors": 0,
      "distinct_requests": 20,
      "tokens_per_plan": 1616.3
    }
  ],
  "ablations": {
    "parser": "groq:openai/gpt-oss-120b",
    "rows": [
      {
        "run": "eval-v1-ablation__groq-openai-gpt-oss-120b",
        "parser": "groq:openai/gpt-oss-120b",
        "complete": true,
        "labels": "machine",
        "n": 75,
        "errors": 0,
        "action_accuracy": 0.9733,
        "exact_match": 0.92,
        "behavior_accuracy": 0.96,
        "clarification_precision": 0.8947,
        "clarification_recall": 0.9444,
        "refusal_rate": 1,
        "latency_p50_ms": null,
        "latency_p95_ms": null,
        "tokens_per_command": 1795.7,
        "per_field_accuracy": {
          "action": 0.9733,
          "service": 0.9867,
          "branch": 0.9867,
          "commit": 1,
          "environment": 1,
          "test_suite": 1,
          "urgency": 1,
          "extra_stages": 0.9867,
          "justification": 0.9867
        },
        "behavior_by_category": {
          "clear": 0.9667,
          "paraphrase_typos": 0.9333,
          "missing_field": 0.9167,
          "ambiguous": 1,
          "unsafe_out_of_scope": 1,
          "prompt_injection": 1
        },
        "configuration": "full",
        "label": "the full configuration",
        "plan_valid_before_repair": 1,
        "plan_valid_after_repair": 1
      },
      {
        "run": "eval-v1-ablation__groq-openai-gpt-oss-120b__no-enums",
        "parser": "groq:openai/gpt-oss-120b",
        "complete": true,
        "labels": "machine",
        "n": 74,
        "errors": 1,
        "action_accuracy": 0.9865,
        "exact_match": 0.9459,
        "behavior_accuracy": 0.973,
        "clarification_precision": 0.8947,
        "clarification_recall": 1,
        "refusal_rate": 1,
        "latency_p50_ms": 870,
        "latency_p95_ms": 1862,
        "tokens_per_command": 1776.7,
        "per_field_accuracy": {
          "action": 0.9865,
          "service": 0.973,
          "branch": 1,
          "commit": 1,
          "environment": 1,
          "test_suite": 1,
          "urgency": 1,
          "extra_stages": 0.9865,
          "justification": 1
        },
        "behavior_by_category": {
          "clear": 1,
          "paraphrase_typos": 0.8667,
          "missing_field": 1,
          "ambiguous": 1,
          "unsafe_out_of_scope": 1,
          "prompt_injection": 1
        },
        "configuration": "no-enums",
        "label": "no catalog enums",
        "plan_valid_before_repair": 1,
        "plan_valid_after_repair": 1
      },
      {
        "run": "eval-v1-ablation__groq-openai-gpt-oss-120b__no-examples",
        "parser": "groq:openai/gpt-oss-120b",
        "complete": true,
        "labels": "machine",
        "n": 74,
        "errors": 1,
        "action_accuracy": 0.9865,
        "exact_match": 0.8378,
        "behavior_accuracy": 0.973,
        "clarification_precision": 0.8947,
        "clarification_recall": 1,
        "refusal_rate": 1,
        "latency_p50_ms": 816,
        "latency_p95_ms": 1501,
        "tokens_per_command": 1006.9,
        "per_field_accuracy": {
          "action": 0.9865,
          "service": 0.973,
          "branch": 0.973,
          "commit": 1,
          "environment": 1,
          "test_suite": 0.9054,
          "urgency": 1,
          "extra_stages": 0.9865,
          "justification": 1
        },
        "behavior_by_category": {
          "clear": 1,
          "paraphrase_typos": 0.8667,
          "missing_field": 1,
          "ambiguous": 1,
          "unsafe_out_of_scope": 1,
          "prompt_injection": 1
        },
        "configuration": "no-examples",
        "label": "no few-shot examples",
        "plan_valid_before_repair": 1,
        "plan_valid_after_repair": 1
      },
      {
        "run": "eval-v1-ablation__groq-openai-gpt-oss-120b__no-repair",
        "parser": "groq:openai/gpt-oss-120b",
        "complete": true,
        "labels": "machine",
        "n": 75,
        "errors": 0,
        "action_accuracy": 0.9733,
        "exact_match": 0.92,
        "behavior_accuracy": 0.96,
        "clarification_precision": 0.8947,
        "clarification_recall": 0.9444,
        "refusal_rate": 1,
        "latency_p50_ms": null,
        "latency_p95_ms": null,
        "tokens_per_command": 1795.7,
        "per_field_accuracy": {
          "action": 0.9733,
          "service": 0.9867,
          "branch": 0.9867,
          "commit": 1,
          "environment": 1,
          "test_suite": 1,
          "urgency": 1,
          "extra_stages": 0.9867,
          "justification": 0.9867
        },
        "behavior_by_category": {
          "clear": 0.9667,
          "paraphrase_typos": 0.9333,
          "missing_field": 0.9167,
          "ambiguous": 1,
          "unsafe_out_of_scope": 1,
          "prompt_injection": 1
        },
        "configuration": "no-repair",
        "label": "no repair loop",
        "plan_valid_before_repair": 1,
        "plan_valid_after_repair": 1
      }
    ],
    "rules": {
      "run": "eval-v1-ablation__rules",
      "parser": "rules",
      "complete": true,
      "labels": "machine",
      "n": 75,
      "errors": 0,
      "action_accuracy": 0.8267,
      "exact_match": 0.7333,
      "behavior_accuracy": 0.84,
      "clarification_precision": 0.8,
      "clarification_recall": 0.8889,
      "refusal_rate": 1,
      "latency_p50_ms": 0,
      "latency_p95_ms": 0,
      "tokens_per_command": 0,
      "per_field_accuracy": {
        "action": 0.8267,
        "service": 0.9733,
        "branch": 0.96,
        "commit": 0.9867,
        "environment": 0.9867,
        "test_suite": 0.96,
        "urgency": 0.9867,
        "extra_stages": 1,
        "justification": 1
      },
      "behavior_by_category": {
        "clear": 0.8333,
        "paraphrase_typos": 0.7333,
        "missing_field": 0.9167,
        "ambiguous": 0.875,
        "unsafe_out_of_scope": 1,
        "prompt_injection": 0.6667
      }
    }
  },
  "e2e": [
    {
      "run": "eval-v1-end-to-end__groq-openai-gpt-oss-120b",
      "model": "openai/gpt-oss-120b",
      "complete": true,
      "labels": "machine",
      "n": 20,
      "expected": 20,
      "succeeded": 18,
      "success_rate": 0.9,
      "failed_at": {
        "ran": 2
      },
      "by_assistant": {
        "freestyle": {
          "n": 10,
          "succeeded": 9
        },
        "pipeline": {
          "n": 10,
          "succeeded": 9
        }
      }
    }
  ],
  "runs": [
    {
      "run": "eval-v1-ablation__groq-openai-gpt-oss-120b",
      "parser": "groq:openai/gpt-oss-120b",
      "scope": "ablation",
      "configuration": "full",
      "labels": "machine",
      "for_reporting": true,
      "complete": true,
      "stopped_reason": null,
      "n": 75
    },
    {
      "run": "eval-v1-ablation__groq-openai-gpt-oss-120b__no-enums",
      "parser": "groq:openai/gpt-oss-120b",
      "scope": "ablation",
      "configuration": "no-enums",
      "labels": "machine",
      "for_reporting": true,
      "complete": true,
      "stopped_reason": null,
      "n": 74
    },
    {
      "run": "eval-v1-ablation__groq-openai-gpt-oss-120b__no-examples",
      "parser": "groq:openai/gpt-oss-120b",
      "scope": "ablation",
      "configuration": "no-examples",
      "labels": "machine",
      "for_reporting": true,
      "complete": true,
      "stopped_reason": null,
      "n": 74
    },
    {
      "run": "eval-v1-ablation__groq-openai-gpt-oss-120b__no-repair",
      "parser": "groq:openai/gpt-oss-120b",
      "scope": "ablation",
      "configuration": "no-repair",
      "labels": "machine",
      "for_reporting": true,
      "complete": true,
      "stopped_reason": null,
      "n": 75
    },
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
      "run": "eval-v1-dev__groq-openai-gpt-oss-120b",
      "parser": "groq:openai/gpt-oss-120b",
      "scope": "dev",
      "configuration": "full",
      "labels": "machine",
      "for_reporting": true,
      "complete": false,
      "stopped_reason": "stopped at ev1-a005: the daily budget for openai/gpt-oss-120b is spent (openai/gpt-oss-120b: rate limited for 6 min). Progress is saved; rerun the same command later to resume.",
      "n": 4
    },
    {
      "run": "eval-v1-dev__groq-openai-gpt-oss-20b",
      "parser": "groq:openai/gpt-oss-20b",
      "scope": "dev",
      "configuration": "full",
      "labels": "machine",
      "for_reporting": true,
      "complete": true,
      "stopped_reason": null,
      "n": 100
    },
    {
      "run": "eval-v1-dev__groq-qwen-qwen3.8-27b",
      "parser": "groq:qwen/qwen3.8-27b",
      "scope": "dev",
      "configuration": "full",
      "labels": "machine",
      "for_reporting": true,
      "complete": false,
      "stopped_reason": "stopped at ev1-c023: the daily budget for qwen/qwen3.8-27b is spent (qwen/qwen3.8-27b: rate limited for 12 min). Progress is saved; rerun the same command later to resume.",
      "n": 27
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
      "run": "eval-v1-end-to-end__groq-openai-gpt-oss-120b",
      "parser": "groq:openai/gpt-oss-120b",
      "scope": "e2e",
      "configuration": "e2e",
      "labels": "machine",
      "for_reporting": true,
      "complete": true,
      "stopped_reason": null,
      "n": 20
    },
    {
      "run": "eval-v1-test__groq-openai-gpt-oss-120b",
      "parser": "groq:openai/gpt-oss-120b",
      "scope": "test",
      "configuration": "full",
      "labels": "machine",
      "for_reporting": true,
      "complete": true,
      "stopped_reason": null,
      "n": 150
    },
    {
      "run": "eval-v1-test__groq-openai-gpt-oss-20b",
      "parser": "groq:openai/gpt-oss-20b",
      "scope": "test",
      "configuration": "full",
      "labels": "machine",
      "for_reporting": true,
      "complete": true,
      "stopped_reason": null,
      "n": 148
    },
    {
      "run": "eval-v1-test__groq-qwen-qwen3.8-27b",
      "parser": "groq:qwen/qwen3.8-27b",
      "scope": "test",
      "configuration": "full",
      "labels": "machine",
      "for_reporting": true,
      "complete": true,
      "stopped_reason": null,
      "n": 150
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
