/**
 * Real responses from the backend, captured on 2026-10-16 by driving it in fake mode (LLM_MODE=fake)
 * against the fake Jenkins: a build, test and deploy of payment-service through the Freestyle
 * Assistant (edited to LOW, generated, regenerated, approved, queued, then its unit tests failing),
 * a question, a refusal, /help, a status, and a build, test and deploy of auth-service through the
 * Pipeline Assistant. Generated from the JSON by a script, not written by hand.
 *
 * Each is typed by what the client returns for it, so a backend change that alters a shape fails to
 * compile here before it can make these tests describe an API that no longer exists.
 */

import type { AssistantApi } from "@/api/assistantApi";

type Returned<K extends keyof AssistantApi> = Awaited<ReturnType<AssistantApi[K]>>;

export const services: Returned<"services"> = {
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

export const paymentBranches: Returned<"branches"> = {
  "service": "payment-service",
  "default_branch": "main",
  "branches": [
    "demo/failing-tests",
    "main"
  ],
  "available": true,
  "unavailable_reason": null
};

export const freestyleChats: Returned<"conversations"> = {
  "items": [
    {
      "id": "6009220952004710abb8ae8eb2da497e",
      "assistant": "freestyle",
      "title": "Build, test and deploy payment-service to staging",
      "created_at": "2026-10-15T18:56:22.496503"
    }
  ],
  "total": 1,
  "limit": 50,
  "offset": 0
};

export const createdChat: Returned<"createConversation"> = {
  "id": "6009220952004710abb8ae8eb2da497e",
  "assistant": "freestyle",
  "title": "New chat",
  "created_at": "2026-10-15T18:56:22.496503Z"
};

export const intentExchange: Returned<"send"> = {
  "conversation": {
    "id": "6009220952004710abb8ae8eb2da497e",
    "assistant": "freestyle",
    "title": "Build, test and deploy payment-service to staging",
    "created_at": "2026-10-15T18:56:22.496503"
  },
  "user_message": {
    "id": "9ff6ee84a29a47fe878664b14cd4c97e",
    "role": "USER",
    "content": "Build, test and deploy payment-service to staging",
    "payload": null,
    "created_at": "2026-10-15T18:56:22.512684Z"
  },
  "assistant_message": {
    "id": "b699d6ad7e2746ddb9c9eafc51ce16e1",
    "role": "ASSISTANT",
    "content": "Ready to generate: build, test and deploy payment-service to staging on main.",
    "payload": {
      "intent": {
        "action": "BUILD_TEST_DEPLOY",
        "service": "payment-service",
        "branch": null,
        "commit": null,
        "environment": "staging",
        "test_suite": null,
        "urgency": null,
        "extra_stages": [],
        "justification": null,
        "confidence": 0.8
      },
      "model_intent": {
        "action": "BUILD_TEST_DEPLOY",
        "service": "payment-service",
        "branch": null,
        "commit": null,
        "environment": "staging",
        "test_suite": null,
        "urgency": null,
        "extra_stages": [],
        "justification": null,
        "confidence": 0.8
      },
      "disposition": "READY",
      "behavior": "GENERATE",
      "ai_fallback": false,
      "fallback_reasons": [],
      "cached": false,
      "prompt_version": "intent_v1@9457338e",
      "notes": [],
      "warnings": [],
      "question": null,
      "help": null,
      "policy": {
        "outcome": "ALLOW",
        "reasons": [],
        "flags": [],
        "can_cancel_running": false
      },
      "resolved": {
        "branch": "main",
        "commit": null
      },
      "injection_suspected": false,
      "command_id": "6362e96e74954d52b720a78be39c6b13",
      "kind": "intent"
    },
    "created_at": "2026-10-15T18:56:22.512684Z"
  },
  "command": {
    "id": "6362e96e74954d52b720a78be39c6b13",
    "status": "PARSED",
    "disposition": "READY",
    "raw_text": "Build, test and deploy payment-service to staging",
    "parser": "LLM",
    "model": "openai/gpt-oss-120b",
    "confidence": 0.8,
    "clarification_rounds": 0,
    "record": {
      "intent": {
        "action": "BUILD_TEST_DEPLOY",
        "service": "payment-service",
        "branch": null,
        "commit": null,
        "environment": "staging",
        "test_suite": null,
        "urgency": null,
        "extra_stages": [],
        "justification": null,
        "confidence": 0.8
      },
      "model_intent": {
        "action": "BUILD_TEST_DEPLOY",
        "service": "payment-service",
        "branch": null,
        "commit": null,
        "environment": "staging",
        "test_suite": null,
        "urgency": null,
        "extra_stages": [],
        "justification": null,
        "confidence": 0.8
      },
      "disposition": "READY",
      "behavior": "GENERATE",
      "ai_fallback": false,
      "fallback_reasons": [],
      "cached": false,
      "prompt_version": "intent_v1@9457338e",
      "notes": [],
      "warnings": [],
      "question": null,
      "help": null,
      "policy": {
        "outcome": "ALLOW",
        "reasons": [],
        "flags": [],
        "can_cancel_running": false
      },
      "resolved": {
        "branch": "main",
        "commit": null
      },
      "injection_suspected": false
    },
    "created_at": "2026-10-15T18:56:22.512684Z"
  }
};

export const questionExchange: Returned<"send"> = {
  "conversation": {
    "id": "6009220952004710abb8ae8eb2da497e",
    "assistant": "freestyle",
    "title": "Build, test and deploy payment-service to staging",
    "created_at": "2026-10-15T18:56:22.496503"
  },
  "user_message": {
    "id": "03f4bcf47777473295fdf1171946588d",
    "role": "USER",
    "content": "run the tests",
    "payload": null,
    "created_at": "2026-10-15T18:56:22.686637Z"
  },
  "assistant_message": {
    "id": "c06562462fda4cebbb4f7c6451b9e1fa",
    "role": "ASSISTANT",
    "content": "Which service should I test?",
    "payload": {
      "intent": {
        "action": "TEST",
        "service": null,
        "branch": null,
        "commit": null,
        "environment": null,
        "test_suite": null,
        "urgency": null,
        "extra_stages": [],
        "justification": null,
        "confidence": 0.45
      },
      "model_intent": {
        "action": "TEST",
        "service": null,
        "branch": null,
        "commit": null,
        "environment": null,
        "test_suite": null,
        "urgency": null,
        "extra_stages": [],
        "justification": null,
        "confidence": 0.45
      },
      "disposition": "NEEDS_CLARIFICATION",
      "behavior": "CLARIFY",
      "ai_fallback": false,
      "fallback_reasons": [],
      "cached": false,
      "prompt_version": "intent_v1@9457338e",
      "notes": [],
      "warnings": [],
      "question": {
        "field": "service",
        "question": "Which service should I test?",
        "options": [
          "auth-service",
          "payment-service"
        ],
        "free_text": false
      },
      "help": null,
      "policy": {
        "outcome": "ALLOW",
        "reasons": [],
        "flags": [],
        "can_cancel_running": false
      },
      "resolved": {
        "branch": null,
        "commit": null
      },
      "injection_suspected": false,
      "command_id": "ff351c73b2e545328620e53da2cddf08",
      "kind": "question"
    },
    "created_at": "2026-10-15T18:56:22.692744Z"
  },
  "command": {
    "id": "ff351c73b2e545328620e53da2cddf08",
    "status": "NEEDS_CLARIFICATION",
    "disposition": "NEEDS_CLARIFICATION",
    "raw_text": "run the tests",
    "parser": "LLM",
    "model": "openai/gpt-oss-120b",
    "confidence": 0.45,
    "clarification_rounds": 0,
    "record": {
      "intent": {
        "action": "TEST",
        "service": null,
        "branch": null,
        "commit": null,
        "environment": null,
        "test_suite": null,
        "urgency": null,
        "extra_stages": [],
        "justification": null,
        "confidence": 0.45
      },
      "model_intent": {
        "action": "TEST",
        "service": null,
        "branch": null,
        "commit": null,
        "environment": null,
        "test_suite": null,
        "urgency": null,
        "extra_stages": [],
        "justification": null,
        "confidence": 0.45
      },
      "disposition": "NEEDS_CLARIFICATION",
      "behavior": "CLARIFY",
      "ai_fallback": false,
      "fallback_reasons": [],
      "cached": false,
      "prompt_version": "intent_v1@9457338e",
      "notes": [],
      "warnings": [],
      "question": {
        "field": "service",
        "question": "Which service should I test?",
        "options": [
          "auth-service",
          "payment-service"
        ],
        "free_text": false
      },
      "help": null,
      "policy": {
        "outcome": "ALLOW",
        "reasons": [],
        "flags": [],
        "can_cancel_running": false
      },
      "resolved": {
        "branch": null,
        "commit": null
      },
      "injection_suspected": false
    },
    "created_at": "2026-10-15T18:56:22.691728Z"
  }
};

export const refusalExchange: Returned<"send"> = {
  "conversation": {
    "id": "6009220952004710abb8ae8eb2da497e",
    "assistant": "freestyle",
    "title": "Build, test and deploy payment-service to staging",
    "created_at": "2026-10-15T18:56:22.496503"
  },
  "user_message": {
    "id": "8bc94454ab0b4b9791367db983b6114a",
    "role": "USER",
    "content": "Deploy payment-service to production",
    "payload": null,
    "created_at": "2026-10-15T18:56:22.697717Z"
  },
  "assistant_message": {
    "id": "01c3129e7a204597a5107c7e902008f6",
    "role": "ASSISTANT",
    "content": "This project deploys to staging only. Production deployment is disabled for every role, including administrators.",
    "payload": {
      "intent": {
        "action": "DEPLOY",
        "service": "Deploy payment-service to production",
        "branch": null,
        "commit": null,
        "environment": "production",
        "test_suite": null,
        "urgency": null,
        "extra_stages": [],
        "justification": null,
        "confidence": 0.8
      },
      "model_intent": {
        "action": "DEPLOY",
        "service": "payment-service",
        "branch": null,
        "commit": null,
        "environment": "production",
        "test_suite": null,
        "urgency": null,
        "extra_stages": [],
        "justification": null,
        "confidence": 0.8
      },
      "disposition": "REFUSED",
      "behavior": "REFUSE",
      "ai_fallback": false,
      "fallback_reasons": [],
      "cached": false,
      "prompt_version": "intent_v1@9457338e",
      "notes": [],
      "warnings": [],
      "question": null,
      "help": null,
      "policy": {
        "outcome": "REFUSE",
        "reasons": [
          {
            "code": "PRODUCTION_REFUSED",
            "message": "This project deploys to staging only. Production deployment is disabled for every role, including administrators."
          }
        ],
        "flags": [],
        "can_cancel_running": false
      },
      "resolved": {
        "branch": null,
        "commit": null
      },
      "injection_suspected": false,
      "command_id": "e195096a7dff4cfeb2e4c7d5ee1a70bd",
      "kind": "refusal",
      "error": null
    },
    "created_at": "2026-10-15T18:56:22.704921Z"
  },
  "command": {
    "id": "e195096a7dff4cfeb2e4c7d5ee1a70bd",
    "status": "REFUSED",
    "disposition": "REFUSED",
    "raw_text": "run the tests (service Deploy payment-service to production)",
    "parser": "LLM",
    "model": "openai/gpt-oss-120b",
    "confidence": 0.8,
    "clarification_rounds": 1,
    "record": {
      "intent": {
        "action": "DEPLOY",
        "service": "Deploy payment-service to production",
        "branch": null,
        "commit": null,
        "environment": "production",
        "test_suite": null,
        "urgency": null,
        "extra_stages": [],
        "justification": null,
        "confidence": 0.8
      },
      "model_intent": {
        "action": "DEPLOY",
        "service": "payment-service",
        "branch": null,
        "commit": null,
        "environment": "production",
        "test_suite": null,
        "urgency": null,
        "extra_stages": [],
        "justification": null,
        "confidence": 0.8
      },
      "disposition": "REFUSED",
      "behavior": "REFUSE",
      "ai_fallback": false,
      "fallback_reasons": [],
      "cached": false,
      "prompt_version": "intent_v1@9457338e",
      "notes": [],
      "warnings": [],
      "question": null,
      "help": null,
      "policy": {
        "outcome": "REFUSE",
        "reasons": [
          {
            "code": "PRODUCTION_REFUSED",
            "message": "This project deploys to staging only. Production deployment is disabled for every role, including administrators."
          }
        ],
        "flags": [],
        "can_cancel_running": false
      },
      "resolved": {
        "branch": null,
        "commit": null
      },
      "injection_suspected": false
    },
    "created_at": "2026-10-15T18:56:22.704921Z"
  }
};

export const helpExchange: Returned<"send"> = {
  "conversation": {
    "id": "6009220952004710abb8ae8eb2da497e",
    "assistant": "freestyle",
    "title": "Build, test and deploy payment-service to staging",
    "created_at": "2026-10-15T18:56:22.496503"
  },
  "user_message": {
    "id": "e50ca6ef310446ca90e3d2a52aea680b",
    "role": "USER",
    "content": "/help",
    "payload": null,
    "created_at": "2026-10-15T18:56:22.713405Z"
  },
  "assistant_message": {
    "id": "b166f510cade4064800cfbb8cb59d0f6",
    "role": "ASSISTANT",
    "content": "Here is what I can do\nBuild <service> from <branch>\nRun the <suite> tests for <service>\nDeploy <service> to staging\nBuild, test and deploy <service> to staging\nWhat's the status of <service>?\nRerun or cancel the <service> build\nServices: auth-service, payment-service\nDeployments go to staging only.",
    "payload": {
      "kind": "help",
      "help": {
        "title": "Here is what I can do",
        "lines": [
          "Build <service> from <branch>",
          "Run the <suite> tests for <service>",
          "Deploy <service> to staging",
          "Build, test and deploy <service> to staging",
          "What's the status of <service>?",
          "Rerun or cancel the <service> build",
          "Services: auth-service, payment-service",
          "Deployments go to staging only."
        ]
      }
    },
    "created_at": "2026-10-15T18:56:22.713405Z"
  },
  "command": null
};

export const statusExchange: Returned<"send"> = {
  "conversation": {
    "id": "6009220952004710abb8ae8eb2da497e",
    "assistant": "freestyle",
    "title": "Build, test and deploy payment-service to staging",
    "created_at": "2026-10-15T18:56:22.496503"
  },
  "user_message": {
    "id": "7642e96027a944538cc08705fe5e358d",
    "role": "USER",
    "content": "What's the status of my last deploy?",
    "payload": null,
    "created_at": "2026-10-15T18:56:22.668958Z"
  },
  "assistant_message": {
    "id": "88c95f83076445438519f736e9259c83",
    "role": "ASSISTANT",
    "content": "The payment-service chain is running; its first job has not started yet.",
    "payload": {
      "intent": {
        "action": "STATUS",
        "service": null,
        "branch": null,
        "commit": null,
        "environment": null,
        "test_suite": null,
        "urgency": null,
        "extra_stages": [],
        "justification": null,
        "confidence": 0.55
      },
      "model_intent": {
        "action": "STATUS",
        "service": null,
        "branch": null,
        "commit": null,
        "environment": null,
        "test_suite": null,
        "urgency": null,
        "extra_stages": [],
        "justification": null,
        "confidence": 0.55
      },
      "disposition": "READY",
      "behavior": "GENERATE",
      "ai_fallback": false,
      "fallback_reasons": [],
      "cached": false,
      "prompt_version": "intent_v1@9457338e",
      "notes": [],
      "warnings": [],
      "question": null,
      "help": null,
      "policy": {
        "outcome": "ALLOW",
        "reasons": [],
        "flags": [],
        "can_cancel_running": false
      },
      "resolved": {
        "branch": null,
        "commit": null
      },
      "injection_suspected": false,
      "command_id": "bf0f05c690e8405e9d4c8f9ee10a4667",
      "kind": "status",
      "chain": {
        "id": "984c52f6e9ec4e768afd809cf73a8810",
        "pipeline_id": "c9fdc9416646438f82506178f5bc4f70",
        "service": "payment-service",
        "job_type": "FREESTYLE",
        "status": "RUNNING",
        "position": 0,
        "parameters": {
          "BRANCH": "main",
          "COMMIT": "refs/heads/main"
        },
        "started_at": "2026-10-15T18:56:22.629507+00:00",
        "finished_at": null,
        "lock_expires_at": "2026-10-15T19:26:22.629507+00:00",
        "duration_ms": null,
        "jobs": [
          {
            "name": "fs-payment-service-build",
            "position": 0,
            "state": "queued",
            "run": null
          },
          {
            "name": "fs-payment-service-test-unit",
            "position": 1,
            "state": "waiting",
            "run": null
          },
          {
            "name": "fs-payment-service-test-integration",
            "position": 2,
            "state": "waiting",
            "run": null
          },
          {
            "name": "fs-payment-service-deploy-staging",
            "position": 3,
            "state": "waiting",
            "run": null
          }
        ],
        "stages": [],
        "queue": {
          "job": "fs-payment-service-build",
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
      }
    },
    "created_at": "2026-10-15T18:56:22.677191Z"
  },
  "command": {
    "id": "bf0f05c690e8405e9d4c8f9ee10a4667",
    "status": "PARSED",
    "disposition": "READY",
    "raw_text": "What's the status of my last deploy?",
    "parser": "LLM",
    "model": "openai/gpt-oss-120b",
    "confidence": 0.55,
    "clarification_rounds": 0,
    "record": {
      "intent": {
        "action": "STATUS",
        "service": null,
        "branch": null,
        "commit": null,
        "environment": null,
        "test_suite": null,
        "urgency": null,
        "extra_stages": [],
        "justification": null,
        "confidence": 0.55
      },
      "model_intent": {
        "action": "STATUS",
        "service": null,
        "branch": null,
        "commit": null,
        "environment": null,
        "test_suite": null,
        "urgency": null,
        "extra_stages": [],
        "justification": null,
        "confidence": 0.55
      },
      "disposition": "READY",
      "behavior": "GENERATE",
      "ai_fallback": false,
      "fallback_reasons": [],
      "cached": false,
      "prompt_version": "intent_v1@9457338e",
      "notes": [],
      "warnings": [],
      "question": null,
      "help": null,
      "policy": {
        "outcome": "ALLOW",
        "reasons": [],
        "flags": [],
        "can_cancel_running": false
      },
      "resolved": {
        "branch": null,
        "commit": null
      },
      "injection_suspected": false
    },
    "created_at": "2026-10-15T18:56:22.674182Z"
  }
};

export const pipelineIntentExchange: Returned<"send"> = {
  "conversation": {
    "id": "86407eb3cf074248b728036a4b2a3bf3",
    "assistant": "pipeline",
    "title": "Build, test and deploy the latest commit of auth-service to ",
    "created_at": "2026-10-15T18:56:22.736148"
  },
  "user_message": {
    "id": "1d325c9dfe744fccbc1ecbf796ff0552",
    "role": "USER",
    "content": "Build, test and deploy the latest commit of auth-service to staging",
    "payload": null,
    "created_at": "2026-10-15T18:56:22.737830Z"
  },
  "assistant_message": {
    "id": "3566c51f62014305b8b3e9f8669ed06a",
    "role": "ASSISTANT",
    "content": "Ready to generate: build, test and deploy auth-service to staging on main at 3f786850e387.",
    "payload": {
      "intent": {
        "action": "BUILD_TEST_DEPLOY",
        "service": "auth-service",
        "branch": null,
        "commit": "latest",
        "environment": "staging",
        "test_suite": null,
        "urgency": null,
        "extra_stages": [],
        "justification": null,
        "confidence": 0.8
      },
      "model_intent": {
        "action": "BUILD_TEST_DEPLOY",
        "service": "auth-service",
        "branch": null,
        "commit": "latest",
        "environment": "staging",
        "test_suite": null,
        "urgency": null,
        "extra_stages": [],
        "justification": null,
        "confidence": 0.8
      },
      "disposition": "READY",
      "behavior": "GENERATE",
      "ai_fallback": false,
      "fallback_reasons": [],
      "cached": false,
      "prompt_version": "intent_v1@9457338e",
      "notes": [],
      "warnings": [],
      "question": null,
      "help": null,
      "policy": {
        "outcome": "ALLOW",
        "reasons": [],
        "flags": [],
        "can_cancel_running": false
      },
      "resolved": {
        "branch": "main",
        "commit": "3f786850e387550fdab836ed7e6dc881de23001b"
      },
      "injection_suspected": false,
      "command_id": "e36e7663e2a04c49b711de79d4f5773c",
      "kind": "intent"
    },
    "created_at": "2026-10-15T18:56:22.754994Z"
  },
  "command": {
    "id": "e36e7663e2a04c49b711de79d4f5773c",
    "status": "PARSED",
    "disposition": "READY",
    "raw_text": "Build, test and deploy the latest commit of auth-service to staging",
    "parser": "LLM",
    "model": "openai/gpt-oss-120b",
    "confidence": 0.8,
    "clarification_rounds": 0,
    "record": {
      "intent": {
        "action": "BUILD_TEST_DEPLOY",
        "service": "auth-service",
        "branch": null,
        "commit": "latest",
        "environment": "staging",
        "test_suite": null,
        "urgency": null,
        "extra_stages": [],
        "justification": null,
        "confidence": 0.8
      },
      "model_intent": {
        "action": "BUILD_TEST_DEPLOY",
        "service": "auth-service",
        "branch": null,
        "commit": "latest",
        "environment": "staging",
        "test_suite": null,
        "urgency": null,
        "extra_stages": [],
        "justification": null,
        "confidence": 0.8
      },
      "disposition": "READY",
      "behavior": "GENERATE",
      "ai_fallback": false,
      "fallback_reasons": [],
      "cached": false,
      "prompt_version": "intent_v1@9457338e",
      "notes": [],
      "warnings": [],
      "question": null,
      "help": null,
      "policy": {
        "outcome": "ALLOW",
        "reasons": [],
        "flags": [],
        "can_cancel_running": false
      },
      "resolved": {
        "branch": "main",
        "commit": "3f786850e387550fdab836ed7e6dc881de23001b"
      },
      "injection_suspected": false
    },
    "created_at": "2026-10-15T18:56:22.752356Z"
  }
};

export const command: Returned<"command"> = {
  "id": "6362e96e74954d52b720a78be39c6b13",
  "status": "PARSED",
  "disposition": "READY",
  "raw_text": "Build, test and deploy payment-service to staging",
  "parser": "LLM",
  "model": "openai/gpt-oss-120b",
  "confidence": 0.8,
  "clarification_rounds": 0,
  "record": {
    "intent": {
      "action": "BUILD_TEST_DEPLOY",
      "service": "payment-service",
      "branch": null,
      "commit": null,
      "environment": "staging",
      "test_suite": null,
      "urgency": "LOW",
      "extra_stages": [],
      "justification": null,
      "confidence": 0.8
    },
    "model_intent": {
      "action": "BUILD_TEST_DEPLOY",
      "service": "payment-service",
      "branch": null,
      "commit": null,
      "environment": "staging",
      "test_suite": null,
      "urgency": null,
      "extra_stages": [],
      "justification": null,
      "confidence": 0.8
    },
    "disposition": "READY",
    "behavior": "GENERATE",
    "ai_fallback": false,
    "fallback_reasons": [],
    "cached": false,
    "prompt_version": "intent_v1@9457338e",
    "notes": [
      "intent edited by the user"
    ],
    "warnings": [],
    "question": null,
    "help": null,
    "policy": {
      "outcome": "ALLOW",
      "reasons": [],
      "flags": [],
      "can_cancel_running": false
    },
    "resolved": {
      "branch": "main",
      "commit": null
    },
    "injection_suspected": false
  },
  "created_at": "2026-10-15T18:56:22.512684"
};

export const editedCommand: Returned<"editIntent"> = {
  "id": "6362e96e74954d52b720a78be39c6b13",
  "status": "PARSED",
  "disposition": "READY",
  "raw_text": "Build, test and deploy payment-service to staging",
  "parser": "LLM",
  "model": "openai/gpt-oss-120b",
  "confidence": 0.8,
  "clarification_rounds": 0,
  "record": {
    "intent": {
      "action": "BUILD_TEST_DEPLOY",
      "service": "payment-service",
      "branch": null,
      "commit": null,
      "environment": "staging",
      "test_suite": null,
      "urgency": "LOW",
      "extra_stages": [],
      "justification": null,
      "confidence": 0.8
    },
    "model_intent": {
      "action": "BUILD_TEST_DEPLOY",
      "service": "payment-service",
      "branch": null,
      "commit": null,
      "environment": "staging",
      "test_suite": null,
      "urgency": null,
      "extra_stages": [],
      "justification": null,
      "confidence": 0.8
    },
    "disposition": "READY",
    "behavior": "GENERATE",
    "ai_fallback": false,
    "fallback_reasons": [],
    "cached": false,
    "prompt_version": "intent_v1@9457338e",
    "notes": [
      "intent edited by the user"
    ],
    "warnings": [],
    "question": null,
    "help": null,
    "policy": {
      "outcome": "ALLOW",
      "reasons": [],
      "flags": [],
      "can_cancel_running": false
    },
    "resolved": {
      "branch": "main",
      "commit": null
    },
    "injection_suspected": false
  },
  "created_at": "2026-10-15T18:56:22.512684"
};

export const freestylePipeline: Returned<"pipeline"> = {
  "id": "6ef12879262e482eb620f1990859a6aa",
  "command_id": "6362e96e74954d52b720a78be39c6b13",
  "conversation_id": "6009220952004710abb8ae8eb2da497e",
  "assistant": "freestyle",
  "job_type": "FREESTYLE",
  "status": "VALIDATED",
  "spec_yaml": "version: 1\nassistant: freestyle\nservice: payment-service\nrepo: https://github.com/haiderali-dev/payment-service.git\nbranch: main\nagent_label: linux\npriority: LOW\nstages:\n  - name: Build\n    template: build\n  - name: Unit tests\n    template: test\n    suite: unit\n  - name: Integration tests\n    template: test\n    suite: integration\n  - name: Deploy to staging\n    template: deploy\n    environment: staging\n",
  "jobs": [
    {
      "name": "fs-payment-service-build",
      "position": 0,
      "stage": {
        "name": "Build",
        "template": "build",
        "suite": null,
        "environment": null
      },
      "commands": [
        "./scripts/build.sh"
      ],
      "depends_on": "",
      "triggers": "fs-payment-service-test-unit",
      "config_xml": "<?xml version=\"1.1\" encoding=\"UTF-8\"?>\n<project>\n  <description>Generated by the Freestyle Assistant: Build for payment-service, job 1 of 4 in its chain.</description>\n  <keepDependencies>false</keepDependencies>\n  <properties>\n    <io.jenkins.plugins.queueoptimizer.property.JobPriorityProperty plugin=\"dynamic-queue-optimizer@2.0.0-SNAPSHOT\">\n      <level>LOW</level>\n      <dependsOn></dependsOn>\n    </io.jenkins.plugins.queueoptimizer.property.JobPriorityProperty>\n    <hudson.model.ParametersDefinitionProperty>\n      <parameterDefinitions>\n        <hudson.model.StringParameterDefinition>\n          <name>BRANCH</name>\n          <description>Branch the revision belongs to</description>\n          <defaultValue>main</defaultValue>\n          <trim>true</trim>\n        </hudson.model.StringParameterDefinition>\n        <hudson.model.StringParameterDefinition>\n          <name>COMMIT</name>\n          <description>Revision to check out: a commit SHA, or refs/heads/BRANCH</description>\n          <defaultValue>refs/heads/main</defaultValue>\n          <trim>true</trim>\n        </hudson.model.StringParameterDefinition>\n      </parameterDefinitions>\n    </hudson.model.ParametersDefinitionProperty>\n    <jenkins.model.BuildDiscarderProperty>\n      <strategy class=\"hudson.tasks.LogRotator\">\n        <daysToKeep>-1</daysToKeep>\n        <numToKeep>30</numToKeep>\n        <artifactDaysToKeep>-1</artifactDaysToKeep>\n        <artifactNumToKeep>-1</artifactNumToKeep>\n        <removeLastBuild>false</removeLastBuild>\n      </strategy>\n    </jenkins.model.BuildDiscarderProperty>\n  </properties>\n  <scm class=\"hudson.plugins.git.GitSCM\" plugin=\"git@5.10.1\">\n    <configVersion>2</configVersion>\n    <userRemoteConfigs>\n      <hudson.plugins.git.UserRemoteConfig>\n        <url>https://github.com/haiderali-dev/payment-service.git</url>\n      </hudson.plugins.git.UserRemoteConfig>\n    </userRemoteConfigs>\n    <branches>\n      <hudson.plugins.git.BranchSpec>\n        <name>${COMMIT}</name>\n      </hudson.plugins.git.BranchSpec>\n    </branches>\n    <doGenerateSubmoduleConfigurations>false</doGenerateSubmoduleConfigurations>\n    <submoduleCfg class=\"empty-list\"/>\n    <extensions/>\n  </scm>\n  <assignedNode>linux</assignedNode>\n  <canRoam>false</canRoam>\n  <disabled>false</disabled>\n  <blockBuildWhenDownstreamBuilding>false</blockBuildWhenDownstreamBuilding>\n  <blockBuildWhenUpstreamBuilding>false</blockBuildWhenUpstreamBuilding>\n  <triggers/>\n  <concurrentBuild>false</concurrentBuild>\n  <builders>\n    <hudson.tasks.Shell>\n      <command>./scripts/build.sh</command>\n      <configuredLocalRules/>\n    </hudson.tasks.Shell>\n  </builders>\n  <publishers>\n    <hudson.tasks.ArtifactArchiver>\n      <artifacts>**/*.log</artifacts>\n      <allowEmptyArchive>true</allowEmptyArchive>\n      <onlyIfSuccessful>false</onlyIfSuccessful>\n      <fingerprint>false</fingerprint>\n      <defaultExcludes>true</defaultExcludes>\n      <caseSensitive>true</caseSensitive>\n      <followSymlinks>false</followSymlinks>\n    </hudson.tasks.ArtifactArchiver>\n    <hudson.tasks.BuildTrigger>\n      <childProjects>fs-payment-service-test-unit</childProjects>\n      <threshold>\n        <name>SUCCESS</name>\n        <ordinal>0</ordinal>\n        <color>BLUE</color>\n        <completeBuild>true</completeBuild>\n      </threshold>\n    </hudson.tasks.BuildTrigger>\n  </publishers>\n  <buildWrappers>\n    <hudson.plugins.timestamper.TimestamperBuildWrapper plugin=\"timestamper@1.30\"/>\n    <hudson.plugins.ws__cleanup.PreBuildCleanup plugin=\"ws-cleanup@0.49\">\n      <deleteDirs>false</deleteDirs>\n      <cleanupParameter></cleanupParameter>\n      <externalDelete></externalDelete>\n      <disableDeferredWipeout>false</disableDeferredWipeout>\n    </hudson.plugins.ws__cleanup.PreBuildCleanup>\n  </buildWrappers>\n</project>\n"
    },
    {
      "name": "fs-payment-service-test-unit",
      "position": 1,
      "stage": {
        "name": "Unit tests",
        "template": "test",
        "suite": "unit",
        "environment": null
      },
      "commands": [
        "./scripts/build.sh",
        "./scripts/test.sh unit"
      ],
      "depends_on": "fs-payment-service-build",
      "triggers": "fs-payment-service-test-integration",
      "config_xml": "<?xml version=\"1.1\" encoding=\"UTF-8\"?>\n<project>\n  <description>Generated by the Freestyle Assistant: Unit tests for payment-service, job 2 of 4 in its chain.</description>\n  <keepDependencies>false</keepDependencies>\n  <properties>\n    <io.jenkins.plugins.queueoptimizer.property.JobPriorityProperty plugin=\"dynamic-queue-optimizer@2.0.0-SNAPSHOT\">\n      <level>LOW</level>\n      <dependsOn>fs-payment-service-build</dependsOn>\n    </io.jenkins.plugins.queueoptimizer.property.JobPriorityProperty>\n    <hudson.model.ParametersDefinitionProperty>\n      <parameterDefinitions>\n        <hudson.model.StringParameterDefinition>\n          <name>BRANCH</name>\n          <description>Branch the revision belongs to</description>\n          <defaultValue>main</defaultValue>\n          <trim>true</trim>\n        </hudson.model.StringParameterDefinition>\n        <hudson.model.StringParameterDefinition>\n          <name>COMMIT</name>\n          <description>Revision to check out: a commit SHA, or refs/heads/BRANCH</description>\n          <defaultValue>refs/heads/main</defaultValue>\n          <trim>true</trim>\n        </hudson.model.StringParameterDefinition>\n      </parameterDefinitions>\n    </hudson.model.ParametersDefinitionProperty>\n    <jenkins.model.BuildDiscarderProperty>\n      <strategy class=\"hudson.tasks.LogRotator\">\n        <daysToKeep>-1</daysToKeep>\n        <numToKeep>30</numToKeep>\n        <artifactDaysToKeep>-1</artifactDaysToKeep>\n        <artifactNumToKeep>-1</artifactNumToKeep>\n        <removeLastBuild>false</removeLastBuild>\n      </strategy>\n    </jenkins.model.BuildDiscarderProperty>\n  </properties>\n  <scm class=\"hudson.plugins.git.GitSCM\" plugin=\"git@5.10.1\">\n    <configVersion>2</configVersion>\n    <userRemoteConfigs>\n      <hudson.plugins.git.UserRemoteConfig>\n        <url>https://github.com/haiderali-dev/payment-service.git</url>\n      </hudson.plugins.git.UserRemoteConfig>\n    </userRemoteConfigs>\n    <branches>\n      <hudson.plugins.git.BranchSpec>\n        <name>${COMMIT}</name>\n      </hudson.plugins.git.BranchSpec>\n    </branches>\n    <doGenerateSubmoduleConfigurations>false</doGenerateSubmoduleConfigurations>\n    <submoduleCfg class=\"empty-list\"/>\n    <extensions/>\n  </scm>\n  <assignedNode>linux</assignedNode>\n  <canRoam>false</canRoam>\n  <disabled>false</disabled>\n  <blockBuildWhenDownstreamBuilding>false</blockBuildWhenDownstreamBuilding>\n  <blockBuildWhenUpstreamBuilding>false</blockBuildWhenUpstreamBuilding>\n  <triggers/>\n  <concurrentBuild>false</concurrentBuild>\n  <builders>\n    <hudson.tasks.Shell>\n      <command>./scripts/build.sh</command>\n      <configuredLocalRules/>\n    </hudson.tasks.Shell>\n    <hudson.tasks.Shell>\n      <command>./scripts/test.sh unit</command>\n      <configuredLocalRules/>\n    </hudson.tasks.Shell>\n  </builders>\n  <publishers>\n    <hudson.tasks.ArtifactArchiver>\n      <artifacts>**/*.log</artifacts>\n      <allowEmptyArchive>true</allowEmptyArchive>\n      <onlyIfSuccessful>false</onlyIfSuccessful>\n      <fingerprint>false</fingerprint>\n      <defaultExcludes>true</defaultExcludes>\n      <caseSensitive>true</caseSensitive>\n      <followSymlinks>false</followSymlinks>\n    </hudson.tasks.ArtifactArchiver>\n    <hudson.tasks.BuildTrigger>\n      <childProjects>fs-payment-service-test-integration</childProjects>\n      <threshold>\n        <name>SUCCESS</name>\n        <ordinal>0</ordinal>\n        <color>BLUE</color>\n        <completeBuild>true</completeBuild>\n      </threshold>\n    </hudson.tasks.BuildTrigger>\n  </publishers>\n  <buildWrappers>\n    <hudson.plugins.timestamper.TimestamperBuildWrapper plugin=\"timestamper@1.30\"/>\n    <hudson.plugins.ws__cleanup.PreBuildCleanup plugin=\"ws-cleanup@0.49\">\n      <deleteDirs>false</deleteDirs>\n      <cleanupParameter></cleanupParameter>\n      <externalDelete></externalDelete>\n      <disableDeferredWipeout>false</disableDeferredWipeout>\n    </hudson.plugins.ws__cleanup.PreBuildCleanup>\n  </buildWrappers>\n</project>\n"
    },
    {
      "name": "fs-payment-service-test-integration",
      "position": 2,
      "stage": {
        "name": "Integration tests",
        "template": "test",
        "suite": "integration",
        "environment": null
      },
      "commands": [
        "./scripts/build.sh",
        "./scripts/test.sh integration"
      ],
      "depends_on": "fs-payment-service-test-unit",
      "triggers": "fs-payment-service-deploy-staging",
      "config_xml": "<?xml version=\"1.1\" encoding=\"UTF-8\"?>\n<project>\n  <description>Generated by the Freestyle Assistant: Integration tests for payment-service, job 3 of 4 in its chain.</description>\n  <keepDependencies>false</keepDependencies>\n  <properties>\n    <io.jenkins.plugins.queueoptimizer.property.JobPriorityProperty plugin=\"dynamic-queue-optimizer@2.0.0-SNAPSHOT\">\n      <level>LOW</level>\n      <dependsOn>fs-payment-service-test-unit</dependsOn>\n    </io.jenkins.plugins.queueoptimizer.property.JobPriorityProperty>\n    <hudson.model.ParametersDefinitionProperty>\n      <parameterDefinitions>\n        <hudson.model.StringParameterDefinition>\n          <name>BRANCH</name>\n          <description>Branch the revision belongs to</description>\n          <defaultValue>main</defaultValue>\n          <trim>true</trim>\n        </hudson.model.StringParameterDefinition>\n        <hudson.model.StringParameterDefinition>\n          <name>COMMIT</name>\n          <description>Revision to check out: a commit SHA, or refs/heads/BRANCH</description>\n          <defaultValue>refs/heads/main</defaultValue>\n          <trim>true</trim>\n        </hudson.model.StringParameterDefinition>\n      </parameterDefinitions>\n    </hudson.model.ParametersDefinitionProperty>\n    <jenkins.model.BuildDiscarderProperty>\n      <strategy class=\"hudson.tasks.LogRotator\">\n        <daysToKeep>-1</daysToKeep>\n        <numToKeep>30</numToKeep>\n        <artifactDaysToKeep>-1</artifactDaysToKeep>\n        <artifactNumToKeep>-1</artifactNumToKeep>\n        <removeLastBuild>false</removeLastBuild>\n      </strategy>\n    </jenkins.model.BuildDiscarderProperty>\n  </properties>\n  <scm class=\"hudson.plugins.git.GitSCM\" plugin=\"git@5.10.1\">\n    <configVersion>2</configVersion>\n    <userRemoteConfigs>\n      <hudson.plugins.git.UserRemoteConfig>\n        <url>https://github.com/haiderali-dev/payment-service.git</url>\n      </hudson.plugins.git.UserRemoteConfig>\n    </userRemoteConfigs>\n    <branches>\n      <hudson.plugins.git.BranchSpec>\n        <name>${COMMIT}</name>\n      </hudson.plugins.git.BranchSpec>\n    </branches>\n    <doGenerateSubmoduleConfigurations>false</doGenerateSubmoduleConfigurations>\n    <submoduleCfg class=\"empty-list\"/>\n    <extensions/>\n  </scm>\n  <assignedNode>linux</assignedNode>\n  <canRoam>false</canRoam>\n  <disabled>false</disabled>\n  <blockBuildWhenDownstreamBuilding>false</blockBuildWhenDownstreamBuilding>\n  <blockBuildWhenUpstreamBuilding>false</blockBuildWhenUpstreamBuilding>\n  <triggers/>\n  <concurrentBuild>false</concurrentBuild>\n  <builders>\n    <hudson.tasks.Shell>\n      <command>./scripts/build.sh</command>\n      <configuredLocalRules/>\n    </hudson.tasks.Shell>\n    <hudson.tasks.Shell>\n      <command>./scripts/test.sh integration</command>\n      <configuredLocalRules/>\n    </hudson.tasks.Shell>\n  </builders>\n  <publishers>\n    <hudson.tasks.ArtifactArchiver>\n      <artifacts>**/*.log</artifacts>\n      <allowEmptyArchive>true</allowEmptyArchive>\n      <onlyIfSuccessful>false</onlyIfSuccessful>\n      <fingerprint>false</fingerprint>\n      <defaultExcludes>true</defaultExcludes>\n      <caseSensitive>true</caseSensitive>\n      <followSymlinks>false</followSymlinks>\n    </hudson.tasks.ArtifactArchiver>\n    <hudson.tasks.BuildTrigger>\n      <childProjects>fs-payment-service-deploy-staging</childProjects>\n      <threshold>\n        <name>SUCCESS</name>\n        <ordinal>0</ordinal>\n        <color>BLUE</color>\n        <completeBuild>true</completeBuild>\n      </threshold>\n    </hudson.tasks.BuildTrigger>\n  </publishers>\n  <buildWrappers>\n    <hudson.plugins.timestamper.TimestamperBuildWrapper plugin=\"timestamper@1.30\"/>\n    <hudson.plugins.ws__cleanup.PreBuildCleanup plugin=\"ws-cleanup@0.49\">\n      <deleteDirs>false</deleteDirs>\n      <cleanupParameter></cleanupParameter>\n      <externalDelete></externalDelete>\n      <disableDeferredWipeout>false</disableDeferredWipeout>\n    </hudson.plugins.ws__cleanup.PreBuildCleanup>\n  </buildWrappers>\n</project>\n"
    },
    {
      "name": "fs-payment-service-deploy-staging",
      "position": 3,
      "stage": {
        "name": "Deploy to staging",
        "template": "deploy",
        "suite": null,
        "environment": "staging"
      },
      "commands": [
        "./deploy.sh staging"
      ],
      "depends_on": "fs-payment-service-test-integration",
      "triggers": null,
      "config_xml": "<?xml version=\"1.1\" encoding=\"UTF-8\"?>\n<project>\n  <description>Generated by the Freestyle Assistant: Deploy to staging for payment-service, job 4 of 4 in its chain.</description>\n  <keepDependencies>false</keepDependencies>\n  <properties>\n    <io.jenkins.plugins.queueoptimizer.property.JobPriorityProperty plugin=\"dynamic-queue-optimizer@2.0.0-SNAPSHOT\">\n      <level>LOW</level>\n      <dependsOn>fs-payment-service-test-integration</dependsOn>\n    </io.jenkins.plugins.queueoptimizer.property.JobPriorityProperty>\n    <hudson.model.ParametersDefinitionProperty>\n      <parameterDefinitions>\n        <hudson.model.StringParameterDefinition>\n          <name>BRANCH</name>\n          <description>Branch the revision belongs to</description>\n          <defaultValue>main</defaultValue>\n          <trim>true</trim>\n        </hudson.model.StringParameterDefinition>\n        <hudson.model.StringParameterDefinition>\n          <name>COMMIT</name>\n          <description>Revision to check out: a commit SHA, or refs/heads/BRANCH</description>\n          <defaultValue>refs/heads/main</defaultValue>\n          <trim>true</trim>\n        </hudson.model.StringParameterDefinition>\n      </parameterDefinitions>\n    </hudson.model.ParametersDefinitionProperty>\n    <jenkins.model.BuildDiscarderProperty>\n      <strategy class=\"hudson.tasks.LogRotator\">\n        <daysToKeep>-1</daysToKeep>\n        <numToKeep>30</numToKeep>\n        <artifactDaysToKeep>-1</artifactDaysToKeep>\n        <artifactNumToKeep>-1</artifactNumToKeep>\n        <removeLastBuild>false</removeLastBuild>\n      </strategy>\n    </jenkins.model.BuildDiscarderProperty>\n  </properties>\n  <scm class=\"hudson.plugins.git.GitSCM\" plugin=\"git@5.10.1\">\n    <configVersion>2</configVersion>\n    <userRemoteConfigs>\n      <hudson.plugins.git.UserRemoteConfig>\n        <url>https://github.com/haiderali-dev/payment-service.git</url>\n      </hudson.plugins.git.UserRemoteConfig>\n    </userRemoteConfigs>\n    <branches>\n      <hudson.plugins.git.BranchSpec>\n        <name>${COMMIT}</name>\n      </hudson.plugins.git.BranchSpec>\n    </branches>\n    <doGenerateSubmoduleConfigurations>false</doGenerateSubmoduleConfigurations>\n    <submoduleCfg class=\"empty-list\"/>\n    <extensions/>\n  </scm>\n  <assignedNode>linux</assignedNode>\n  <canRoam>false</canRoam>\n  <disabled>false</disabled>\n  <blockBuildWhenDownstreamBuilding>false</blockBuildWhenDownstreamBuilding>\n  <blockBuildWhenUpstreamBuilding>false</blockBuildWhenUpstreamBuilding>\n  <triggers/>\n  <concurrentBuild>false</concurrentBuild>\n  <builders>\n    <hudson.tasks.Shell>\n      <command>./deploy.sh staging</command>\n      <configuredLocalRules/>\n    </hudson.tasks.Shell>\n  </builders>\n  <publishers>\n    <hudson.tasks.ArtifactArchiver>\n      <artifacts>**/*.log</artifacts>\n      <allowEmptyArchive>true</allowEmptyArchive>\n      <onlyIfSuccessful>false</onlyIfSuccessful>\n      <fingerprint>false</fingerprint>\n      <defaultExcludes>true</defaultExcludes>\n      <caseSensitive>true</caseSensitive>\n      <followSymlinks>false</followSymlinks>\n    </hudson.tasks.ArtifactArchiver>\n  </publishers>\n  <buildWrappers>\n    <hudson.plugins.timestamper.TimestamperBuildWrapper plugin=\"timestamper@1.30\"/>\n    <hudson.plugins.ws__cleanup.PreBuildCleanup plugin=\"ws-cleanup@0.49\">\n      <deleteDirs>false</deleteDirs>\n      <cleanupParameter></cleanupParameter>\n      <externalDelete></externalDelete>\n      <disableDeferredWipeout>false</disableDeferredWipeout>\n    </hudson.plugins.ws__cleanup.PreBuildCleanup>\n  </buildWrappers>\n</project>\n"
    }
  ],
  "jenkinsfile": null,
  "parameters": {
    "BRANCH": "main",
    "COMMIT": "refs/heads/main"
  },
  "progress": [
    {
      "step": "Understood",
      "ok": true,
      "detail": "build, test and deploy payment-service to staging, LOW priority"
    },
    {
      "step": "Planned",
      "ok": true,
      "detail": "model openai/gpt-oss-120b, 0 repair(s)"
    },
    {
      "step": "Rendered",
      "ok": true,
      "detail": "4 job(s)"
    },
    {
      "step": "Validated",
      "ok": true,
      "detail": "all checks passed"
    }
  ],
  "validation": {
    "ok": true,
    "checks": [
      {
        "name": "spec_schema",
        "label": "Spec schema",
        "status": "passed",
        "message": "",
        "cause": null
      },
      {
        "name": "catalog_and_git",
        "label": "Service, branch, commit and suites",
        "status": "passed",
        "message": "all found in the catalog and the repository",
        "cause": null
      },
      {
        "name": "environment",
        "label": "Environment allowed",
        "status": "passed",
        "message": "staging only",
        "cause": null
      },
      {
        "name": "stage_order",
        "label": "Stage order",
        "status": "passed",
        "message": "build -> test -> test -> deploy",
        "cause": null
      },
      {
        "name": "metacharacters",
        "label": "No shell metacharacters",
        "status": "passed",
        "message": "none found",
        "cause": null
      },
      {
        "name": "artifact",
        "label": "XML well-formed",
        "status": "passed",
        "message": "well-formed",
        "cause": null
      },
      {
        "name": "job_names",
        "label": "Job names",
        "status": "passed",
        "message": "fs-payment-service-build, fs-payment-service-test-unit, fs-payment-service-test-integration, fs-payment-service-deploy-staging",
        "cause": null
      },
      {
        "name": "no_production",
        "label": "No production anywhere",
        "status": "passed",
        "message": "staging only",
        "cause": null
      }
    ]
  },
  "plan": {
    "source": "model",
    "provider": "fake",
    "model": "openai/gpt-oss-120b",
    "ai_fallback": false,
    "fallback_reasons": [],
    "prompt_version": "planner_v1@9b25deca",
    "repairs": 0,
    "valid_before_repair": true,
    "valid_after_repair": true,
    "attempts": [
      {
        "number": 0,
        "source": "model",
        "provider": "fake",
        "model": "openai/gpt-oss-120b",
        "valid": true,
        "issues": [],
        "answer": {
          "stages": [
            {
              "name": "Build",
              "template": "build",
              "suite": null,
              "environment": null
            },
            {
              "name": "Unit tests",
              "template": "test",
              "suite": "unit",
              "environment": null
            },
            {
              "name": "Integration tests",
              "template": "test",
              "suite": "integration",
              "environment": null
            },
            {
              "name": "Deploy to staging",
              "template": "deploy",
              "suite": null,
              "environment": "staging"
            }
          ]
        }
      }
    ],
    "warnings": []
  },
  "summary": "Creates 4 jobs and starts fs-payment-service-build on main at LOW priority",
  "attempts": 1,
  "approved_by": null,
  "approved_at": null,
  "approval": null,
  "created_at": "2026-10-15T18:56:22.573307Z"
};

export const invalidPipeline: Returned<"pipeline"> = {
  "id": "251c9e4d514e4725925e62f033b94253",
  "command_id": "6362e96e74954d52b720a78be39c6b13",
  "conversation_id": "6009220952004710abb8ae8eb2da497e",
  "assistant": "freestyle",
  "job_type": "FREESTYLE",
  "status": "INVALID",
  "spec_yaml": "version: 9\nassistant: freestyle\nservice: payment-service\nrepo: https://github.com/haiderali-dev/payment-service.git\nbranch: main\nagent_label: linux\npriority: LOW\nstages:\n  - name: Build\n    template: build\n  - name: Unit tests\n    template: test\n    suite: unit\n  - name: Integration tests\n    template: test\n    suite: integration\n  - name: Deploy to staging\n    template: deploy\n    environment: staging\n",
  "jobs": [],
  "jenkinsfile": null,
  "parameters": {},
  "progress": [
    {
      "step": "Understood",
      "ok": true,
      "detail": "build, test and deploy payment-service to staging, LOW priority"
    },
    {
      "step": "Planned",
      "ok": false,
      "detail": "Spec schema: version: Input should be 1"
    }
  ],
  "validation": {
    "ok": false,
    "checks": [
      {
        "name": "spec_schema",
        "label": "Spec schema",
        "status": "failed",
        "message": "version: Input should be 1",
        "cause": "input"
      }
    ]
  },
  "plan": null,
  "summary": null,
  "attempts": 1,
  "approved_by": null,
  "approved_at": null,
  "approval": null,
  "created_at": "2026-10-15T18:56:22.606542Z"
};

export const pipelinePipeline: Returned<"pipeline"> = {
  "id": "752a5f36e6784025a7132c88a876aeee",
  "command_id": "e36e7663e2a04c49b711de79d4f5773c",
  "conversation_id": "86407eb3cf074248b728036a4b2a3bf3",
  "assistant": "pipeline",
  "job_type": "PIPELINE",
  "status": "VALIDATED",
  "spec_yaml": "version: 1\nassistant: pipeline\nservice: auth-service\nrepo: https://github.com/haiderali-dev/auth-service.git\nbranch: main\ncommit: 3f786850e387550fdab836ed7e6dc881de23001b\nagent_label: linux\npriority: MEDIUM\nstages:\n  - name: Build\n    template: build\n  - name: Unit tests\n    template: test\n    suite: unit\n  - name: Deploy to staging\n    template: deploy\n    environment: staging\n",
  "jobs": [
    {
      "name": "pl-auth-service-build-test-deploy-staging",
      "position": 0,
      "stage": null,
      "commands": [
        "./scripts/build.sh",
        "./scripts/test.sh unit",
        "./deploy.sh staging"
      ],
      "depends_on": "",
      "triggers": null,
      "config_xml": "<?xml version=\"1.1\" encoding=\"UTF-8\"?>\n<flow-definition plugin=\"workflow-job@1602.v2a_70b_80a_2396\">\n  <description>Generated by the Pipeline Assistant: Build, Unit tests, Deploy to staging for auth-service.</description>\n  <keepDependencies>false</keepDependencies>\n  <properties>\n    <io.jenkins.plugins.queueoptimizer.property.JobPriorityProperty plugin=\"dynamic-queue-optimizer@2.0.0-SNAPSHOT\">\n      <level>MEDIUM</level>\n      <dependsOn></dependsOn>\n    </io.jenkins.plugins.queueoptimizer.property.JobPriorityProperty>\n    <hudson.model.ParametersDefinitionProperty>\n      <parameterDefinitions>\n        <hudson.model.StringParameterDefinition>\n          <name>BRANCH</name>\n          <description>Branch the revision belongs to</description>\n          <defaultValue>main</defaultValue>\n          <trim>true</trim>\n        </hudson.model.StringParameterDefinition>\n        <hudson.model.StringParameterDefinition>\n          <name>COMMIT</name>\n          <description>Revision to check out: a commit SHA, or refs/heads/BRANCH</description>\n          <defaultValue></defaultValue>\n          <trim>true</trim>\n        </hudson.model.StringParameterDefinition>\n      </parameterDefinitions>\n    </hudson.model.ParametersDefinitionProperty>\n  </properties>\n  <definition class=\"org.jenkinsci.plugins.workflow.cps.CpsFlowDefinition\" plugin=\"workflow-cps@4383.v04fa_a_3d67b_d9\">\n    <script>pipeline {\n    agent { label &#39;linux&#39; }\n    options {\n        dynamicQueuePriority(level: &#39;MEDIUM&#39;)\n        timestamps()\n        buildDiscarder(logRotator(numToKeepStr: &#39;30&#39;))\n        timeout(time: 30, unit: &#39;MINUTES&#39;)\n    }\n    parameters {\n        string(name: &#39;BRANCH&#39;, defaultValue: &#39;main&#39;, description: &#39;Branch the revision belongs to&#39;)\n        string(name: &#39;COMMIT&#39;, defaultValue: &#39;&#39;, description: &#39;Revision to check out: a commit SHA, or refs/heads/BRANCH&#39;)\n    }\n    stages {\n        stage(&#39;Checkout&#39;) {\n            steps {\n                script {\n                    // D-041: COMMIT wins, else the head of BRANCH, else main. A given value that is\n                    // not valid stops the build; it never falls back. Never an empty spec: the Git\n                    // plugin reads one as &#34;any branch&#34;.\n                    def commit = (params.COMMIT ?: &#39;&#39;).trim()\n                    def branch = (params.BRANCH ?: &#39;&#39;).trim()\n                    if (branch.startsWith(&#39;refs/heads/&#39;)) {\n                        branch = branch.substring(&#39;refs/heads/&#39;.length())\n                    }\n                    if (branch &amp;&amp; !(branch.matches(&#39;[A-Za-z0-9][A-Za-z0-9._/-]{0,254}&#39;) &amp;&amp; !branch.contains(&#39;..&#39;) &amp;&amp; !branch.endsWith(&#39;/&#39;))) {\n                        error(&#34;BRANCH &#39;${branch}&#39; is not a branch name that can be used&#34;)\n                    }\n                    def revision = commit ?: (&#39;refs/heads/&#39; + (branch ?: &#39;main&#39;))\n                    def isCommit = revision.matches(&#39;[0-9a-fA-F]{7,40}&#39;)\n                    def isBranchRef = revision.matches(&#39;refs/heads/[A-Za-z0-9][A-Za-z0-9._/-]{0,254}&#39;) &amp;&amp; !revision.contains(&#39;..&#39;) &amp;&amp; !revision.endsWith(&#39;/&#39;)\n                    if (!isCommit &amp;&amp; !isBranchRef) {\n                        error(&#34;COMMIT &#39;${commit}&#39; is not a commit SHA or refs/heads/&lt;branch&gt;&#34;)\n                    }\n                    checkout([$class: &#39;GitSCM&#39;,\n                              branches: [[name: revision]],\n                              userRemoteConfigs: [[url: &#39;https://github.com/haiderali-dev/auth-service.git&#39;]]])\n                }\n            }\n        }\n        stage(&#39;Build&#39;) {\n            steps { sh &#39;./scripts/build.sh&#39; }\n        }\n        stage(&#39;Unit tests&#39;) {\n            steps { sh &#39;./scripts/test.sh unit&#39; }\n        }\n        stage(&#39;Deploy to staging&#39;) {\n            steps { sh &#39;./deploy.sh staging&#39; }\n        }\n    }\n    post {\n        always { cleanWs() }\n    }\n}\n</script>\n    <sandbox>true</sandbox>\n  </definition>\n  <triggers/>\n  <disabled>false</disabled>\n</flow-definition>\n"
    }
  ],
  "jenkinsfile": "pipeline {\n    agent { label 'linux' }\n    options {\n        dynamicQueuePriority(level: 'MEDIUM')\n        timestamps()\n        buildDiscarder(logRotator(numToKeepStr: '30'))\n        timeout(time: 30, unit: 'MINUTES')\n    }\n    parameters {\n        string(name: 'BRANCH', defaultValue: 'main', description: 'Branch the revision belongs to')\n        string(name: 'COMMIT', defaultValue: '', description: 'Revision to check out: a commit SHA, or refs/heads/BRANCH')\n    }\n    stages {\n        stage('Checkout') {\n            steps {\n                script {\n                    // D-041: COMMIT wins, else the head of BRANCH, else main. A given value that is\n                    // not valid stops the build; it never falls back. Never an empty spec: the Git\n                    // plugin reads one as \"any branch\".\n                    def commit = (params.COMMIT ?: '').trim()\n                    def branch = (params.BRANCH ?: '').trim()\n                    if (branch.startsWith('refs/heads/')) {\n                        branch = branch.substring('refs/heads/'.length())\n                    }\n                    if (branch && !(branch.matches('[A-Za-z0-9][A-Za-z0-9._/-]{0,254}') && !branch.contains('..') && !branch.endsWith('/'))) {\n                        error(\"BRANCH '${branch}' is not a branch name that can be used\")\n                    }\n                    def revision = commit ?: ('refs/heads/' + (branch ?: 'main'))\n                    def isCommit = revision.matches('[0-9a-fA-F]{7,40}')\n                    def isBranchRef = revision.matches('refs/heads/[A-Za-z0-9][A-Za-z0-9._/-]{0,254}') && !revision.contains('..') && !revision.endsWith('/')\n                    if (!isCommit && !isBranchRef) {\n                        error(\"COMMIT '${commit}' is not a commit SHA or refs/heads/<branch>\")\n                    }\n                    checkout([$class: 'GitSCM',\n                              branches: [[name: revision]],\n                              userRemoteConfigs: [[url: 'https://github.com/haiderali-dev/auth-service.git']]])\n                }\n            }\n        }\n        stage('Build') {\n            steps { sh './scripts/build.sh' }\n        }\n        stage('Unit tests') {\n            steps { sh './scripts/test.sh unit' }\n        }\n        stage('Deploy to staging') {\n            steps { sh './deploy.sh staging' }\n        }\n    }\n    post {\n        always { cleanWs() }\n    }\n}\n",
  "parameters": {
    "BRANCH": "main",
    "COMMIT": "3f786850e387550fdab836ed7e6dc881de23001b"
  },
  "progress": [
    {
      "step": "Understood",
      "ok": true,
      "detail": "build, test and deploy auth-service to staging at latest"
    },
    {
      "step": "Planned",
      "ok": true,
      "detail": "model openai/gpt-oss-120b, 0 repair(s)"
    },
    {
      "step": "Rendered",
      "ok": true,
      "detail": "1 job(s)"
    },
    {
      "step": "Validated",
      "ok": true,
      "detail": "all checks passed"
    }
  ],
  "validation": {
    "ok": true,
    "checks": [
      {
        "name": "spec_schema",
        "label": "Spec schema",
        "status": "passed",
        "message": "",
        "cause": null
      },
      {
        "name": "catalog_and_git",
        "label": "Service, branch, commit and suites",
        "status": "passed",
        "message": "all found in the catalog and the repository",
        "cause": null
      },
      {
        "name": "environment",
        "label": "Environment allowed",
        "status": "passed",
        "message": "staging only",
        "cause": null
      },
      {
        "name": "stage_order",
        "label": "Stage order",
        "status": "passed",
        "message": "build -> test -> deploy",
        "cause": null
      },
      {
        "name": "metacharacters",
        "label": "No shell metacharacters",
        "status": "passed",
        "message": "none found",
        "cause": null
      },
      {
        "name": "artifact",
        "label": "Declarative linter",
        "status": "passed",
        "message": "Jenkinsfile successfully validated",
        "cause": null
      },
      {
        "name": "job_names",
        "label": "Job names",
        "status": "passed",
        "message": "pl-auth-service-build-test-deploy-staging",
        "cause": null
      },
      {
        "name": "no_production",
        "label": "No production anywhere",
        "status": "passed",
        "message": "staging only",
        "cause": null
      }
    ]
  },
  "plan": {
    "source": "model",
    "provider": "fake",
    "model": "openai/gpt-oss-120b",
    "ai_fallback": false,
    "fallback_reasons": [],
    "prompt_version": "planner_v1@9b25deca",
    "repairs": 0,
    "valid_before_repair": true,
    "valid_after_repair": true,
    "attempts": [
      {
        "number": 0,
        "source": "model",
        "provider": "fake",
        "model": "openai/gpt-oss-120b",
        "valid": true,
        "issues": [],
        "answer": {
          "stages": [
            {
              "name": "Build",
              "template": "build",
              "suite": null,
              "environment": null
            },
            {
              "name": "Unit tests",
              "template": "test",
              "suite": "unit",
              "environment": null
            },
            {
              "name": "Deploy to staging",
              "template": "deploy",
              "suite": null,
              "environment": "staging"
            }
          ]
        }
      }
    ],
    "warnings": []
  },
  "summary": "Creates 1 job and starts pl-auth-service-build-test-deploy-staging on main at 3f78685 at MEDIUM priority",
  "attempts": 1,
  "approved_by": null,
  "approved_at": null,
  "approval": null,
  "created_at": "2026-10-15T18:56:22.767942Z"
};

export const approval: Returned<"approve"> = {
  "pipeline_id": "c9fdc9416646438f82506178f5bc4f70",
  "status": "APPROVED",
  "replayed": false,
  "result": {
    "chain_id": "984c52f6e9ec4e768afd809cf73a8810",
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
      "COMMIT": "refs/heads/main"
    },
    "priority": "LOW",
    "approved_at": "2026-10-15T18:56:22.629507+00:00"
  }
};

export const queuedChain: Returned<"chain"> = {
  "id": "984c52f6e9ec4e768afd809cf73a8810",
  "pipeline_id": "c9fdc9416646438f82506178f5bc4f70",
  "service": "payment-service",
  "job_type": "FREESTYLE",
  "status": "RUNNING",
  "position": 0,
  "parameters": {
    "BRANCH": "main",
    "COMMIT": "refs/heads/main"
  },
  "started_at": "2026-10-15T18:56:22.629507+00:00",
  "finished_at": null,
  "lock_expires_at": "2026-10-15T19:26:22.629507+00:00",
  "duration_ms": null,
  "jobs": [
    {
      "name": "fs-payment-service-build",
      "position": 0,
      "state": "queued",
      "run": null
    },
    {
      "name": "fs-payment-service-test-unit",
      "position": 1,
      "state": "waiting",
      "run": null
    },
    {
      "name": "fs-payment-service-test-integration",
      "position": 2,
      "state": "waiting",
      "run": null
    },
    {
      "name": "fs-payment-service-deploy-staging",
      "position": 3,
      "state": "waiting",
      "run": null
    }
  ],
  "stages": [],
  "queue": {
    "job": "fs-payment-service-build",
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

export const failedChain: Returned<"chain"> = {
  "id": "984c52f6e9ec4e768afd809cf73a8810",
  "pipeline_id": "c9fdc9416646438f82506178f5bc4f70",
  "service": "payment-service",
  "job_type": "FREESTYLE",
  "status": "FAILURE",
  "position": 1,
  "parameters": {
    "BRANCH": "main",
    "COMMIT": "refs/heads/main"
  },
  "started_at": "2026-10-15T18:56:22.629507+00:00",
  "finished_at": "2026-10-15T18:56:22.793701+00:00",
  "lock_expires_at": "2026-10-15T19:26:22.629507+00:00",
  "duration_ms": 5555,
  "jobs": [
    {
      "name": "fs-payment-service-build",
      "position": 0,
      "state": "success",
      "run": {
        "id": "87d5a676d6b842fca669f94ceff01910",
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
        "id": "f4dfb8eae63348b6ab46907206e424c5",
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
  "failed_run_id": "f4dfb8eae63348b6ab46907206e424c5"
};

export const conversationDetail: Returned<"conversation"> = {
  "id": "6009220952004710abb8ae8eb2da497e",
  "assistant": "freestyle",
  "title": "Build, test and deploy payment-service to staging",
  "created_at": "2026-10-15T18:56:22.496503",
  "messages": [
    {
      "id": "9ff6ee84a29a47fe878664b14cd4c97e",
      "role": "USER",
      "content": "Build, test and deploy payment-service to staging",
      "payload": null,
      "created_at": "2026-10-15T18:56:22.512684"
    },
    {
      "id": "b699d6ad7e2746ddb9c9eafc51ce16e1",
      "role": "ASSISTANT",
      "content": "Ready to generate: build, test and deploy payment-service to staging on main.",
      "payload": {
        "intent": {
          "action": "BUILD_TEST_DEPLOY",
          "service": "payment-service",
          "branch": null,
          "commit": null,
          "environment": "staging",
          "test_suite": null,
          "urgency": null,
          "extra_stages": [],
          "justification": null,
          "confidence": 0.8
        },
        "model_intent": {
          "action": "BUILD_TEST_DEPLOY",
          "service": "payment-service",
          "branch": null,
          "commit": null,
          "environment": "staging",
          "test_suite": null,
          "urgency": null,
          "extra_stages": [],
          "justification": null,
          "confidence": 0.8
        },
        "disposition": "READY",
        "behavior": "GENERATE",
        "ai_fallback": false,
        "fallback_reasons": [],
        "cached": false,
        "prompt_version": "intent_v1@9457338e",
        "notes": [],
        "warnings": [],
        "question": null,
        "help": null,
        "policy": {
          "outcome": "ALLOW",
          "reasons": [],
          "flags": [],
          "can_cancel_running": false
        },
        "resolved": {
          "branch": "main",
          "commit": null
        },
        "injection_suspected": false,
        "command_id": "6362e96e74954d52b720a78be39c6b13",
        "kind": "intent"
      },
      "created_at": "2026-10-15T18:56:22.512684"
    },
    {
      "id": "f42de704d68b4226881b607fb057d8cd",
      "role": "ASSISTANT",
      "content": "Generated and validated: Creates 4 jobs and starts fs-payment-service-build on main at LOW priority",
      "payload": {
        "kind": "pipeline",
        "pipeline_id": "6ef12879262e482eb620f1990859a6aa",
        "status": "VALIDATED"
      },
      "created_at": "2026-10-15T18:56:22.574425"
    },
    {
      "id": "d05d9392b4ff43298ff12f64501ff21f",
      "role": "ASSISTANT",
      "content": "Generated and validated: Creates 4 jobs and starts fs-payment-service-build on main at LOW priority",
      "payload": {
        "kind": "pipeline",
        "pipeline_id": "4c413fb8f3ed4166a46b44dbf82643ae",
        "status": "VALIDATED"
      },
      "created_at": "2026-10-15T18:56:22.597668"
    },
    {
      "id": "1fa8bef4932a4e979d95905d53a1bc7f",
      "role": "ASSISTANT",
      "content": "The plan did not pass validation. The checklist shows what to fix.",
      "payload": {
        "kind": "pipeline",
        "pipeline_id": "251c9e4d514e4725925e62f033b94253",
        "status": "INVALID"
      },
      "created_at": "2026-10-15T18:56:22.606542"
    },
    {
      "id": "9a278eb6095f432e9e2cd4d6057a8b4a",
      "role": "ASSISTANT",
      "content": "Generated and validated: Creates 4 jobs and starts fs-payment-service-build on main at LOW priority",
      "payload": {
        "kind": "pipeline",
        "pipeline_id": "c9fdc9416646438f82506178f5bc4f70",
        "status": "VALIDATED"
      },
      "created_at": "2026-10-15T18:56:22.613453"
    },
    {
      "id": "429972b7b428464aa0f60558513fbfe4",
      "role": "ASSISTANT",
      "content": "Run started: fs-payment-service-build is queued.",
      "payload": {
        "kind": "run",
        "pipeline_id": "c9fdc9416646438f82506178f5bc4f70",
        "chain_id": "984c52f6e9ec4e768afd809cf73a8810",
        "first_job": "fs-payment-service-build",
        "queue_item_id": 1,
        "jobs": [
          "fs-payment-service-build",
          "fs-payment-service-test-unit",
          "fs-payment-service-test-integration",
          "fs-payment-service-deploy-staging"
        ],
        "parameters": {
          "BRANCH": "main",
          "COMMIT": "refs/heads/main"
        },
        "priority": "LOW",
        "approved_at": "2026-10-15T18:56:22.629507+00:00"
      },
      "created_at": "2026-10-15T18:56:22.641774"
    },
    {
      "id": "7642e96027a944538cc08705fe5e358d",
      "role": "USER",
      "content": "What's the status of my last deploy?",
      "payload": null,
      "created_at": "2026-10-15T18:56:22.668958"
    },
    {
      "id": "88c95f83076445438519f736e9259c83",
      "role": "ASSISTANT",
      "content": "The payment-service chain is running; its first job has not started yet.",
      "payload": {
        "intent": {
          "action": "STATUS",
          "service": null,
          "branch": null,
          "commit": null,
          "environment": null,
          "test_suite": null,
          "urgency": null,
          "extra_stages": [],
          "justification": null,
          "confidence": 0.55
        },
        "model_intent": {
          "action": "STATUS",
          "service": null,
          "branch": null,
          "commit": null,
          "environment": null,
          "test_suite": null,
          "urgency": null,
          "extra_stages": [],
          "justification": null,
          "confidence": 0.55
        },
        "disposition": "READY",
        "behavior": "GENERATE",
        "ai_fallback": false,
        "fallback_reasons": [],
        "cached": false,
        "prompt_version": "intent_v1@9457338e",
        "notes": [],
        "warnings": [],
        "question": null,
        "help": null,
        "policy": {
          "outcome": "ALLOW",
          "reasons": [],
          "flags": [],
          "can_cancel_running": false
        },
        "resolved": {
          "branch": null,
          "commit": null
        },
        "injection_suspected": false,
        "command_id": "bf0f05c690e8405e9d4c8f9ee10a4667",
        "kind": "status",
        "chain": {
          "id": "984c52f6e9ec4e768afd809cf73a8810",
          "pipeline_id": "c9fdc9416646438f82506178f5bc4f70",
          "service": "payment-service",
          "job_type": "FREESTYLE",
          "status": "RUNNING",
          "position": 0,
          "parameters": {
            "BRANCH": "main",
            "COMMIT": "refs/heads/main"
          },
          "started_at": "2026-10-15T18:56:22.629507+00:00",
          "finished_at": null,
          "lock_expires_at": "2026-10-15T19:26:22.629507+00:00",
          "duration_ms": null,
          "jobs": [
            {
              "name": "fs-payment-service-build",
              "position": 0,
              "state": "queued",
              "run": null
            },
            {
              "name": "fs-payment-service-test-unit",
              "position": 1,
              "state": "waiting",
              "run": null
            },
            {
              "name": "fs-payment-service-test-integration",
              "position": 2,
              "state": "waiting",
              "run": null
            },
            {
              "name": "fs-payment-service-deploy-staging",
              "position": 3,
              "state": "waiting",
              "run": null
            }
          ],
          "stages": [],
          "queue": {
            "job": "fs-payment-service-build",
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
        }
      },
      "created_at": "2026-10-15T18:56:22.677191"
    },
    {
      "id": "03f4bcf47777473295fdf1171946588d",
      "role": "USER",
      "content": "run the tests",
      "payload": null,
      "created_at": "2026-10-15T18:56:22.686637"
    },
    {
      "id": "c06562462fda4cebbb4f7c6451b9e1fa",
      "role": "ASSISTANT",
      "content": "Which service should I test?",
      "payload": {
        "intent": {
          "action": "TEST",
          "service": null,
          "branch": null,
          "commit": null,
          "environment": null,
          "test_suite": null,
          "urgency": null,
          "extra_stages": [],
          "justification": null,
          "confidence": 0.45
        },
        "model_intent": {
          "action": "TEST",
          "service": null,
          "branch": null,
          "commit": null,
          "environment": null,
          "test_suite": null,
          "urgency": null,
          "extra_stages": [],
          "justification": null,
          "confidence": 0.45
        },
        "disposition": "NEEDS_CLARIFICATION",
        "behavior": "CLARIFY",
        "ai_fallback": false,
        "fallback_reasons": [],
        "cached": false,
        "prompt_version": "intent_v1@9457338e",
        "notes": [],
        "warnings": [],
        "question": {
          "field": "service",
          "question": "Which service should I test?",
          "options": [
            "auth-service",
            "payment-service"
          ],
          "free_text": false
        },
        "help": null,
        "policy": {
          "outcome": "ALLOW",
          "reasons": [],
          "flags": [],
          "can_cancel_running": false
        },
        "resolved": {
          "branch": null,
          "commit": null
        },
        "injection_suspected": false,
        "command_id": "ff351c73b2e545328620e53da2cddf08",
        "kind": "question"
      },
      "created_at": "2026-10-15T18:56:22.692744"
    },
    {
      "id": "8bc94454ab0b4b9791367db983b6114a",
      "role": "USER",
      "content": "Deploy payment-service to production",
      "payload": null,
      "created_at": "2026-10-15T18:56:22.697717"
    },
    {
      "id": "01c3129e7a204597a5107c7e902008f6",
      "role": "ASSISTANT",
      "content": "This project deploys to staging only. Production deployment is disabled for every role, including administrators.",
      "payload": {
        "intent": {
          "action": "DEPLOY",
          "service": "Deploy payment-service to production",
          "branch": null,
          "commit": null,
          "environment": "production",
          "test_suite": null,
          "urgency": null,
          "extra_stages": [],
          "justification": null,
          "confidence": 0.8
        },
        "model_intent": {
          "action": "DEPLOY",
          "service": "payment-service",
          "branch": null,
          "commit": null,
          "environment": "production",
          "test_suite": null,
          "urgency": null,
          "extra_stages": [],
          "justification": null,
          "confidence": 0.8
        },
        "disposition": "REFUSED",
        "behavior": "REFUSE",
        "ai_fallback": false,
        "fallback_reasons": [],
        "cached": false,
        "prompt_version": "intent_v1@9457338e",
        "notes": [],
        "warnings": [],
        "question": null,
        "help": null,
        "policy": {
          "outcome": "REFUSE",
          "reasons": [
            {
              "code": "PRODUCTION_REFUSED",
              "message": "This project deploys to staging only. Production deployment is disabled for every role, including administrators."
            }
          ],
          "flags": [],
          "can_cancel_running": false
        },
        "resolved": {
          "branch": null,
          "commit": null
        },
        "injection_suspected": false,
        "command_id": "e195096a7dff4cfeb2e4c7d5ee1a70bd",
        "kind": "refusal",
        "error": null
      },
      "created_at": "2026-10-15T18:56:22.704921"
    },
    {
      "id": "b166f510cade4064800cfbb8cb59d0f6",
      "role": "ASSISTANT",
      "content": "Here is what I can do\nBuild <service> from <branch>\nRun the <suite> tests for <service>\nDeploy <service> to staging\nBuild, test and deploy <service> to staging\nWhat's the status of <service>?\nRerun or cancel the <service> build\nServices: auth-service, payment-service\nDeployments go to staging only.",
      "payload": {
        "kind": "help",
        "help": {
          "title": "Here is what I can do",
          "lines": [
            "Build <service> from <branch>",
            "Run the <suite> tests for <service>",
            "Deploy <service> to staging",
            "Build, test and deploy <service> to staging",
            "What's the status of <service>?",
            "Rerun or cancel the <service> build",
            "Services: auth-service, payment-service",
            "Deployments go to staging only."
          ]
        }
      },
      "created_at": "2026-10-15T18:56:22.713405"
    },
    {
      "id": "e50ca6ef310446ca90e3d2a52aea680b",
      "role": "USER",
      "content": "/help",
      "payload": null,
      "created_at": "2026-10-15T18:56:22.713405"
    }
  ]
};

/** POST /api/pipelines/{id}/explain, streamed as plain text (fake mode explains in code). */
export const explanation = "This creates a chain of 4 freestyle job(s) for payment-service on main at LOW priority. First fs-payment-service-build runs ./scripts/build.sh. If that succeeds, fs-payment-service-test-unit runs ./scripts/build.sh then ./scripts/test.sh unit. If that succeeds, fs-payment-service-test-integration runs ./scripts/build.sh then ./scripts/test.sh integration. If that succeeds, fs-payment-service-deploy-staging runs ./deploy.sh staging. A failed job stops the chain, so nothing after it runs.";
