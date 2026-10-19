# Plugin responses for the plugin-client tests

Each file is a response recorded verbatim from `GET /dynamic-queue/api/json` on the live
jenkins-dev on 2026-10-15. No field was changed.

**How they were recorded.** Through the backend container's own HTTP client, with the bot account's
settings. The plugin never renders a credential: `ApiJsonIT.tokenIsNeverExposed` holds that, and the
configuration block carries only the metrics URL and whether a metrics token is set.

**How each was made.** By queueing more builds than jenkins-dev has executors (two agents with two
each), then polling until the waiting items showed what the file is for. Every job used is an
`it-*` integration-test job with no deploy step.

| File | How it was made | What it shows |
| --- | --- | --- |
| `ranking-three-waiting.json` | Eight builds queued at once | Three waiting freestyle items, one HIGH and two MEDIUM. Their estimates come from build history (3.6 s, 2.9 s and 22.6 s), and the longest scores 0 for execution time. |
| `ranking-aged.json` | One build queued with a 300-second quiet period, and the executors filled as it ended | Aging: after 300.8 s in the queue, 0.05 is added to a base of 0.300, for an own score of 0.350. |
| `ranking-group.json` | The executors filled, then `it-revision-upstream` and its downstream `it-revision-freestyle` queued together | A dependency group of two: dependency 1.0 for both, topological ranks 0 and 1. The MEDIUM upstream inherits its HIGH downstream's 0.979994 over its own 0.800. Three Pipeline items the optimizer had not yet scored are listed under `unscoredItems` and counted in `queueLength`. |

`ranking-held.json` was recorded the same way on 2026-10-20, after the plugin gained `heldItems`
and jenkins-dev was rebuilt with it. Two `it-*` jobs were derived from
`jenkins/reference-configs/freestyle-downstream.config.xml`. `it-held-upstream` (MEDIUM) runs
`sleep 25`, and `it-held-downstream` (HIGH) declares it in `dependsOn` and runs
`echo downstream`. The upstream was queued, then the downstream 3 seconds later, and the
endpoint was polled until the downstream showed as held. Both then finished with SUCCESS, the
downstream after the upstream. The bot account may not delete jobs, so both remain on jenkins-dev.

| File | How it was made | What it shows |
| --- | --- | --- |
| `ranking-held.json` | The pair above | Nothing ranked, and one held item: `it-held-downstream`, HIGH, held because `it-held-upstream` is `building`, after 8.169 s. |

**Why recorded and not written.** The ranking parser used to be tested against a fixture written
from 4.3.10's prose, with flat `urgencyFactor`, `agingBonus` and `estimateSeconds`. Those are the
names of the plugin's metric events (`QueueMetricsRecorder`), not of this endpoint, which nests the
factors under `components` and gives `estimateMillis`. The parser passed its tests while reading
every live factor as 0. The health endpoint's `droppedMetricCount` went the same way first.

Jenkins writes its blocked reasons with typographic quotes (`'linux'` in U+2018 and U+2019). The
files keep them as JSON `\u` escapes, so they stay ASCII.
