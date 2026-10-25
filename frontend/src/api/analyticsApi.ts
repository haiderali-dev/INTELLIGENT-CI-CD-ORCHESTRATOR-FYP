/**
 * The Analytics page's requests: run statistics, computed from `job_runs` when asked, the
 * experiments the harness stores with their metrics, and the chatbot evaluation's report as
 * `python -m eval report` wrote it. Nothing here is an aggregate kept anywhere: the backend
 * returns null where nothing was measured, and the page shows it as not measured.
 */

import { api, type ApiClient } from "./client";
import { answer } from "./request";

export function analyticsApi(client: ApiClient = api) {
  return {
    runStats: () => answer(client.GET("/api/analytics/runs")),

    experiments: (limit: number) =>
      answer(client.GET("/api/analytics/experiments", { params: { query: { limit } } })),

    experiment: (id: string) =>
      answer(
        client.GET("/api/analytics/experiments/{experiment_id}", {
          params: { path: { experiment_id: id } },
        }),
      ),

    evaluation: () => answer(client.GET("/api/analytics/evaluation")),
  };
}

export type AnalyticsApi = ReturnType<typeof analyticsApi>;

/* What the client returns (D-059). */
type Returned<K extends keyof AnalyticsApi> = Awaited<ReturnType<AnalyticsApi[K]>>;
export type RunStats = Returned<"runStats">;
export type ExperimentPage = Returned<"experiments">;
export type Experiment = ExperimentPage["items"][number];
export type ExperimentDetail = Returned<"experiment">;
export type Metric = ExperimentDetail["metrics"][number];
export type Evaluation = Returned<"evaluation">;
export type EvaluationRow = Evaluation["comparison"][number];
export type EvaluationPlanRow = Evaluation["plans"][number];
export type EvaluationAblationRow = NonNullable<Evaluation["ablations"]>["rows"][number];
export type EvaluationEndToEndRow = Evaluation["e2e"][number];

export const analyticsKeys = {
  runStats: ["run-stats"] as const,
  experiments: ["experiments"] as const,
  experiment: (id: string) => ["experiment", id] as const,
  evaluation: ["evaluation"] as const,
};
