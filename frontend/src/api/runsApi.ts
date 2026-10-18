/**
 * The requests behind Jobs and runs and the Overview: the chains each approval or re-run started
 * (D-047) and their run cards, the runs Jenkins built, a run's log read in windows, and why a run
 * failed (T5.9). Every read is open to any signed-in user.
 */

import { api, type ApiClient } from "./client";
import { answer } from "./request";

/** The API's own filters, all of them applied by the backend to every chain. */
export interface ChainQuery {
  service?: string;
  active?: boolean;
  /** FREESTYLE or PIPELINE: which assistant started the chain. */
  jobType?: "FREESTYLE" | "PIPELINE";
  status?: "RUNNING" | "SUCCESS" | "FAILURE" | "ABORTED" | "EXPIRED";
  limit?: number;
}

export interface RunQuery {
  active?: boolean;
  limit?: number;
}

/** The most `GET /api/chains` and `GET /api/runs` return in one page (`MAX_PAGE_SIZE`). */
export const PAGE_MAX = 200;

export function runsApi(client: ApiClient = api) {
  return {
    chains: ({ service, active, jobType, status, limit }: ChainQuery = {}) =>
      answer(
        client.GET("/api/chains", {
          params: {
            query: {
              ...(service ? { service } : {}),
              ...(active ? { active } : {}),
              ...(jobType ? { job_type: jobType } : {}),
              ...(status ? { status } : {}),
              ...(limit ? { limit } : {}),
            },
          },
        }),
      ),

    chain: (id: string) =>
      answer(client.GET("/api/chains/{chain_id}", { params: { path: { chain_id: id } } })),

    runs: ({ active, limit }: RunQuery = {}) =>
      answer(
        client.GET("/api/runs", {
          params: { query: { ...(active ? { active } : {}), ...(limit ? { limit } : {}) } },
        }),
      ),

    /** One window of a run's console output, from a byte offset. */
    log: (runId: string, start: number) =>
      answer(
        client.GET("/api/runs/{run_id}/log", {
          params: { path: { run_id: runId }, query: { start } },
        }),
      ),

    explain: (runId: string) =>
      answer(client.POST("/api/runs/{run_id}/explain", { params: { path: { run_id: runId } } })),
  };
}

export type RunsApi = ReturnType<typeof runsApi>;

/* What the client returns, as for the assistant pages (D-059). */
type Returned<K extends keyof RunsApi> = Awaited<ReturnType<RunsApi[K]>>;
export type ChainPage = Returned<"chains">;
export type ChainSummary = ChainPage["items"][number];
export type ChainCard = Returned<"chain">;
export type RunPage = Returned<"runs">;
export type Run = RunPage["items"][number];
export type LogWindow = Returned<"log">;
export type RunFailure = Returned<"explain">;

export const runsKeys = {
  /** Distinct from the assistant pages' ["chain", id]: a list is not a card. */
  chainLists: ["chain-list"] as const,
  chainList: (query: ChainQuery) => ["chain-list", query] as const,
  runLists: ["run-list"] as const,
  runList: (query: RunQuery) => ["run-list", query] as const,
};
