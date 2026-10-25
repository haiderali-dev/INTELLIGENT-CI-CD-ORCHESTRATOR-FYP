# Chatbot evaluation

**Provenance.** Gold labels were written by Claude Code, an AI assistant, and checked against the dataset card's rules by code; no person has reviewed them (docs/decisions.md D-081). These figures measure agreement with those labels.

Dataset `eval-v1`: 250 items, 100 development and 150 test, sha256 `31559fed8225`; reviewed by a person: 0.

## Comparison on the test split

| Parser | n | Errors | Action | Exact match | Behaviour | Clarify P / R | Refusal | Latency p50 / p95 (ms) | Tokens/cmd |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| rules | 150 | 0 | 83.3% | 72.7% | 85.3% | 80.6% / 87.9% | 100.0% | 0 / 0 | 0 |
| groq:openai/gpt-oss-120b | 150 | 0 | 98.7% | 90.7% | 96.0% | 88.6% / 93.9% | 100.0% | 349 / 948 | 1796.7 |
| groq:openai/gpt-oss-20b | 148 | 2 | 93.2% | 81.8% | 91.2% | 85.7% / 72.7% | 100.0% | 469 / 873 | 1789.8 |
| groq:qwen/qwen3.8-27b | 150 | 0 | 91.3% | 64.7% | 94.0% | 90.3% / 84.9% | 100.0% | 678 / 1624 | 1618.3 |

Per-field accuracy, on each parser's own answer:

| Parser | action | service | branch | commit | environment | test_suite | urgency | extra_stages | justification |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| rules | 83.3% | 98.7% | 95.3% | 97.3% | 99.3% | 96.0% | 99.3% | 100.0% | 100.0% |
| groq:openai/gpt-oss-120b | 98.7% | 97.3% | 99.3% | 100.0% | 100.0% | 98.0% | 100.0% | 98.7% | 98.0% |
| groq:openai/gpt-oss-20b | 93.2% | 98.0% | 99.3% | 99.3% | 94.6% | 96.6% | 98.7% | 99.3% | 98.0% |
| groq:qwen/qwen3.8-27b | 91.3% | 98.0% | 82.7% | 95.3% | 98.7% | 96.7% | 98.0% | 98.0% | 100.0% |

Behaviour accuracy by category:

| Parser | clear | paraphrase_typos | missing_field | ambiguous | unsafe_out_of_scope | prompt_injection |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| rules | 90.0% | 66.7% | 91.3% | 80.0% | 100.0% | 85.7% |
| groq:openai/gpt-oss-120b | 98.3% | 90.0% | 95.7% | 93.3% | 100.0% | 100.0% |
| groq:openai/gpt-oss-20b | 94.8% | 96.7% | 73.9% | 80.0% | 100.0% | 100.0% |
| groq:qwen/qwen3.8-27b | 96.7% | 96.7% | 87.0% | 86.7% | 100.0% | 85.7% |

## Plan validity before and after repair

Each model plans every test item whose gold behaviour is to generate jobs, from the gold intent after the validator, so a parse error cannot cost the plan.

| Parser | Plannable items | Planned by the model | Valid before repair | Valid after repair | Repaired | Still invalid | Distinct requests | Tokens/plan |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| groq:openai/gpt-oss-120b | 74 | 74 | 100.0% | 100.0% | 0 | 0 | 20 | 1695.5 |
| groq:openai/gpt-oss-20b | 74 | 74 | 87.8% | 100.0% | 9 | 0 | 20 | 1880.5 |
| groq:qwen/qwen3.8-27b | 74 | 74 | 100.0% | 100.0% | 0 | 0 | 20 | 1616.3 |

## Ablations

On the 75-item stratified subset of the test split, with `groq:openai/gpt-oss-120b`.

| Configuration | n | Errors | Action | Exact match | Behaviour | Clarify P / R | Refusal | Tokens/cmd | Plans valid first / after repair |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| the full configuration | 75 | 0 | 97.3% | 92.0% | 96.0% | 89.5% / 94.4% | 100.0% | 1795.7 | 100.0% / 100.0% |
| no catalog enums | 74 | 1 | 98.7% | 94.6% | 97.3% | 89.5% / 100.0% | 100.0% | 1776.7 | 100.0% / 100.0% |
| no few-shot examples | 74 | 1 | 98.7% | 83.8% | 97.3% | 89.5% / 100.0% | 100.0% | 1006.9 | 100.0% / 100.0% |
| no repair loop | 75 | 0 | 97.3% | 92.0% | 96.0% | 89.5% / 94.4% | 100.0% | 1795.7 | 100.0% / 100.0% |

The rule baseline on the same 75 items: action 82.7%, behaviour 84.0%.

## Every reportable run

| Run | Parser | n | Action | Exact match | Behaviour | Clarify P / R | Refusal | Latency p50 / p95 (ms) | Tokens/cmd |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| eval-v1-ablation__groq-openai-gpt-oss-120b | groq:openai/gpt-oss-120b | 75 | 97.3% | 92.0% | 96.0% | 89.5% / 94.4% | 100.0% | n/a / n/a | 1795.7 |
| eval-v1-ablation__groq-openai-gpt-oss-120b__no-enums | groq:openai/gpt-oss-120b | 74 | 98.7% | 94.6% | 97.3% | 89.5% / 100.0% | 100.0% | 870 / 1862 | 1776.7 |
| eval-v1-ablation__groq-openai-gpt-oss-120b__no-examples | groq:openai/gpt-oss-120b | 74 | 98.7% | 83.8% | 97.3% | 89.5% / 100.0% | 100.0% | 816 / 1501 | 1006.9 |
| eval-v1-ablation__groq-openai-gpt-oss-120b__no-repair | groq:openai/gpt-oss-120b | 75 | 97.3% | 92.0% | 96.0% | 89.5% / 94.4% | 100.0% | n/a / n/a | 1795.7 |
| eval-v1-ablation__rules | rules | 75 | 82.7% | 73.3% | 84.0% | 80.0% / 88.9% | 100.0% | 0 / 0 | 0 |
| eval-v1-dev__groq-openai-gpt-oss-120b (incomplete) | groq:openai/gpt-oss-120b | 4 | 50.0% | 50.0% | 75.0% | 100.0% / 66.7% | n/a | 676 / 2099 | 1791.5 |
| eval-v1-dev__groq-openai-gpt-oss-20b | groq:openai/gpt-oss-20b | 100 | 97.0% | 78.0% | 89.0% | 88.2% / 68.2% | 92.3% | 679 / 1552 | 1787.7 |
| eval-v1-dev__groq-qwen-qwen3.8-27b (incomplete) | groq:qwen/qwen3.8-27b | 27 | 92.6% | 77.8% | 96.3% | 90.0% / 100.0% | n/a | 871 / 1452 | 1566.9 |
| eval-v1-dev__rules | rules | 100 | 87.0% | 76.0% | 84.0% | 79.2% / 86.4% | 76.9% | 0 / 1 | 0 |
| eval-v1-e2e__groq-openai-gpt-oss-120b | groq:openai/gpt-oss-120b | 20 | 100.0% | 95.0% | 100.0% | n/a / n/a | n/a | 411 / 801 | 1794.8 |
| eval-v1-test__groq-openai-gpt-oss-120b | groq:openai/gpt-oss-120b | 150 | 98.7% | 90.7% | 96.0% | 88.6% / 93.9% | 100.0% | 349 / 948 | 1796.7 |
| eval-v1-test__groq-openai-gpt-oss-20b | groq:openai/gpt-oss-20b | 148 | 93.2% | 81.8% | 91.2% | 85.7% / 72.7% | 100.0% | 469 / 873 | 1789.8 |
| eval-v1-test__groq-qwen-qwen3.8-27b | groq:qwen/qwen3.8-27b | 150 | 91.3% | 64.7% | 94.0% | 90.3% / 84.9% | 100.0% | 678 / 1624 | 1618.3 |
| eval-v1-test__rules | rules | 150 | 83.3% | 72.7% | 85.3% | 80.6% / 87.9% | 100.0% | 0 / 0 | 0 |

Field comparison: `extra_stages` as a set; `justification` leniently (both absent, or one contains the other). Action and field scores use each parser's own answer. Items with a parser error are counted in Errors and excluded from accuracy, clarification and refusal denominators. Latency is the answering model call's own time; answers served from a cache are left out of it.

## End to end against jenkins-dev

Each command through the real stack: understood, planned, generated as asked, run to SUCCESS on the agents, and, for a deploy, answering on staging.

| Model | Commands | Succeeded | Success | Failed at | Freestyle | Pipeline |
| --- | ---: | ---: | ---: | --- | ---: | ---: |
| openai/gpt-oss-120b | 20 of 20 | 18 | 90.0% | ran 2 | 9 of 10 | 9 of 10 |
