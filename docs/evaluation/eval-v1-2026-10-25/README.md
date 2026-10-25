# Evaluation evidence, 25 October 2026

Gold labels were written by Claude Code and have not been reviewed by a person (D-081).
These results measure agreement with those labels.

- `dataset/`: the frozen dataset, source and cards.
- `runs/`: saved predictions, plans, metrics and the live end-to-end records, copied without
  changing their values. Older runs retain Windows path separators in their metadata.
- `report/`: JSON and markdown generated from `runs/` by `python -m eval report`.
- `diagnostics/`: Jenkins console output for the two failed end-to-end commands.
- `manifest.json`: SHA-256 hashes for the dataset, runs, reports and diagnostic evidence.
- `campaign/`: the resumable campaign runner, event log and every attempt's output.

All four parsers completed the test split. GPT-OSS-20B answered 148 items and rejected two;
the other parsers answered all 150. Accuracy and refusal denominators exclude parser errors,
which are recorded separately. The four primary-model ablation configurations each attempted
all 75 items. Removing enums and removing examples each produced one rejected response.
All three models completed the 74 generating test items' plans, using 20 distinct requests
per model. Identical requests share cached answers.

The live sample completed all 20 commands, with 18 successes. `ev1-c026` (freestyle) and
`ev1-c029` (Pipeline) failed the payment-service formatting check after successful generation.
Their logs identify two unformatted test files in the sample repository. The original failures
remain part of the measured result.

Additional development runs for GPT-OSS-120B and Qwen are incomplete because of quota; they
are visibly marked in the report and excluded from the test comparison. The saved campaign
can resume these runs without repeating completed items:

```powershell
& .venv-tools/Scripts/python.exe docs/evaluation/eval-v1-2026-10-25/campaign/eval_campaign.py --stop-on-quota
```

Omit `--stop-on-quota` to keep waiting for the provider's retry time. Exit status 0 means all
selected queues finished, 3 means quota deferred work, and 1 means a step or worker failed.
Failed steps remain eligible on the next invocation; successful steps are skipped. The runner
finds the checkout from its own location and uses the local `uv` or the one on `PATH`.

Regenerate the archived report and the chapter tables from the repository root:

```powershell
uv run --no-sync --project backend python -m eval report --results docs/evaluation/eval-v1-2026-10-25/runs --out .tmp/eval-report-rebuilt
uv run --no-sync --project backend python scripts/report/chapter_12.py --check
```

The archive is a snapshot; resuming a development run changes `eval/results/`, not these files.
Keep later evidence in a new dated archive and regenerate its report and manifest.
