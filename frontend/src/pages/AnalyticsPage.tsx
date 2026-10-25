import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Link, useSearchParams } from "react-router";

import {
  analyticsApi,
  analyticsKeys,
  type Experiment,
  type Metric,
  type RunStats,
} from "@/api/analyticsApi";
import { useApi } from "@/api/apiClientContext";
import type { NavItem } from "@/app/shell/nav";
import { stateFromResult } from "@/components/buildState";
import { BuildStateLabel } from "@/components/BuildStateLabel";
import { DataTable, type Column } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { Empty, Loading, LoadFailed, PageSection } from "@/components/PageStates";
import { formatDuration, formatPercent, formatWhen, parseApiTime } from "@/lib/format";
import { ChatbotEvaluation } from "@/pages/ChatbotEvaluation";
import { useLiveEvent } from "@/ws/liveEventsContext";

/** The most experiments listed at once; the API's own page size. */
export const EXPERIMENT_LIMIT = 50;

/** Results in the order a reader scans them: what worked, then what did not, then the rest. */
const RESULT_ORDER = ["SUCCESS", "UNSTABLE", "FAILURE", "ABORTED", "NOT_BUILT", "RUNNING"];

const NOT_MEASURED = "Not measured";

/**
 * Analytics (4.7.3): run statistics computed from every run when asked, the experiments as the
 * harness stores them, and the chatbot evaluation. Nothing is invented: where the backend measured
 * nothing it says null, and the page says "Not measured", never 0 (backend app/api/analytics.py).
 */
export function AnalyticsPage({ item }: { item: Pick<NavItem, "label" | "description"> }) {
  const queryClient = useQueryClient();
  useLiveEvent(["run.started", "run.finished"], () => {
    void queryClient.invalidateQueries({ queryKey: analyticsKeys.runStats });
  });

  return (
    <>
      <PageHeader title={item.label} description={item.description} />
      <RunStatistics />
      <Experiments />
      <ChatbotEvaluation />
    </>
  );
}

function RunStatistics() {
  const api = useApi(analyticsApi);
  const stats = useQuery({ queryKey: analyticsKeys.runStats, queryFn: () => api.runStats() });

  let body: ReactNode;
  if (stats.data) {
    body =
      stats.data.total_runs === 0 ? (
        <Empty>
          <p>
            No run has been recorded yet. Approve a plan in either assistant, and every run it
            starts is counted here.
          </p>
          <p>
            <Link to="/assistants/freestyle" className="font-semibold underline underline-offset-4">
              Open the Freestyle Assistant
            </Link>
          </p>
        </Empty>
      ) : (
        <StatsFigures stats={stats.data} />
      );
  } else if (stats.isError) {
    body = (
      <LoadFailed
        what="The run statistics"
        error={stats.error}
        onRetry={() => {
          void stats.refetch();
        }}
      />
    );
  } else {
    body = <Loading>Loading the run statistics</Loading>;
  }

  return (
    <PageSection title="Runs">
      <p className="max-w-[68ch] px-6 text-graphite">
        Every run the orchestrator started, counted now from the runs themselves.
      </p>
      {body}
    </PageSection>
  );
}

function StatsFigures({ stats }: { stats: RunStats }) {
  const settled = stats.total_runs - stats.running;
  const results = Object.entries(stats.by_result).sort(
    ([a], [b]) => rank(a) - rank(b) || a.localeCompare(b),
  );
  return (
    <div className="flex flex-col gap-5 px-6">
      <dl className="grid grid-cols-[repeat(auto-fill,minmax(12rem,1fr))] gap-x-6 gap-y-4">
        <Figure term="Runs" value={String(stats.total_runs)} />
        <Figure term="Running now" value={String(stats.running)} />
        <Figure
          term="Succeeded"
          value={stats.success_rate === null ? NOT_MEASURED : formatPercent(stats.success_rate)}
          note={
            stats.success_rate === null
              ? "No run has finished yet."
              : `Of ${String(settled)} finished ${settled === 1 ? "run" : "runs"}.`
          }
        />
        <Figure
          term="Mean duration"
          value={
            stats.mean_duration_ms === null ? NOT_MEASURED : formatDuration(stats.mean_duration_ms)
          }
          note={stats.mean_duration_ms === null ? "No finished run has a duration yet." : null}
        />
        <Figure
          term="Mean queue wait"
          value={
            stats.mean_queue_wait_ms === null
              ? NOT_MEASURED
              : formatDuration(stats.mean_queue_wait_ms)
          }
          note={
            stats.runs_with_queue_wait === 0
              ? "No run's time in the queue was measured."
              : `Over ${String(stats.runs_with_queue_wait)} ${stats.runs_with_queue_wait === 1 ? "run" : "runs"} with a measured wait.`
          }
        />
        <Figure
          term="Longest queue wait"
          value={
            stats.max_queue_wait_ms === null ? NOT_MEASURED : formatDuration(stats.max_queue_wait_ms)
          }
        />
      </dl>
      <div className="flex flex-col gap-2">
        <h3 className="font-semibold">By result</h3>
        <ul aria-label="Runs by result" className="flex flex-wrap gap-x-6 gap-y-2">
          {results.map(([result, count]) => (
            <li key={result} className="flex items-center gap-2">
              <BuildStateLabel state={stateFromResult(result)} />
              <span className="font-semibold tabular-nums">{count}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function rank(result: string): number {
  const index = RESULT_ORDER.indexOf(result);
  return index === -1 ? RESULT_ORDER.length : index;
}

/** A figure: the number large and semibold, what it counts above it (DESIGN.md section 3). */
function Figure({ term, value, note = null }: { term: string; value: string; note?: string | null }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-sm text-graphite">{term}</dt>
      <dd className="text-xl font-semibold tabular-nums">{value}</dd>
      {note ? <dd className="text-sm text-graphite">{note}</dd> : null}
    </div>
  );
}

function Experiments() {
  const api = useApi(analyticsApi);
  const [params] = useSearchParams();
  const selected = params.get("experiment");
  const experiments = useQuery({
    queryKey: analyticsKeys.experiments,
    queryFn: () => api.experiments(EXPERIMENT_LIMIT),
  });

  let body: ReactNode;
  if (experiments.data) {
    const { items, total } = experiments.data;
    body =
      items.length === 0 ? (
        <Empty>
          <p>
            No experiment results yet. They appear here when the experiment harness records a run.
            The Milestone 2 results are imported as a series of their own, "M2 dispatcher v1", and
            are never mixed into the new ones.
          </p>
        </Empty>
      ) : (
        <>
          {total > items.length ? (
            <p className="px-6 text-sm text-graphite">
              {`The newest ${String(items.length)} of ${String(total)} experiment runs.`}
            </p>
          ) : null}
          <DataTable
            label="Experiment runs, newest first"
            rows={items}
            columns={EXPERIMENT_COLUMNS}
            rowKey={({ id }) => id}
            selectedKey={selected}
          />
          {selected ? <ExperimentMetrics id={selected} /> : null}
        </>
      );
  } else if (experiments.isError) {
    body = (
      <LoadFailed
        what="The experiments"
        error={experiments.error}
        onRetry={() => {
          void experiments.refetch();
        }}
      />
    );
  } else {
    body = <Loading>Loading the experiments</Loading>;
  }

  return (
    <PageSection title="Experiments" className="border-t border-rule">
      <p className="max-w-[68ch] px-6 text-graphite">
        Each run of the experiment harness, with the metrics it stored. Choose a run to see them.
      </p>
      {body}
    </PageSection>
  );
}

const EXPERIMENT_COLUMNS: readonly Column<Experiment>[] = [
  {
    header: "Series",
    rowHeader: true,
    nowrap: true,
    cell: ({ id, label }) => (
      <Link
        to={`?experiment=${encodeURIComponent(id)}`}
        replace
        className="font-semibold underline underline-offset-4"
      >
        {label}
      </Link>
    ),
  },
  { header: "Arm", cell: ({ mode }) => mode, nowrap: true },
  { header: "Workload", cell: ({ workload }) => workload, nowrap: true },
  { header: "Executors", cell: ({ executors }) => executors, align: "right" },
  { header: "Repetition", cell: ({ repetition }) => repetition, align: "right" },
  {
    header: "Finished",
    nowrap: true,
    cell: ({ finished_at: finished }) =>
      finished ? formatWhen(parseApiTime(finished)) : "Not recorded",
  },
  {
    header: "Versions",
    cell: ({ plugin_version: plugin, jenkins_version: jenkins }) =>
      plugin || jenkins
        ? [plugin ? `plugin ${plugin}` : null, jenkins ? `Jenkins ${jenkins}` : null]
            .filter(Boolean)
            .join(", ")
        : "Not recorded",
  },
];

const METRIC_COLUMNS: readonly Column<Metric>[] = [
  { header: "Metric", rowHeader: true, nowrap: true, cell: ({ name }) => name },
  { header: "Band", cell: ({ band }) => band, nowrap: true },
  {
    header: "Value",
    align: "right",
    nowrap: true,
    cell: ({ value, std_dev: deviation, unit }) =>
      deviation === null ? `${String(value)} ${unit}` : `${String(value)} ${unit}, sd ${String(deviation)}`,
  },
  { header: "Sample size", align: "right", cell: ({ sample_size: size }) => size },
];

function ExperimentMetrics({ id }: { id: string }) {
  const api = useApi(analyticsApi);
  const detail = useQuery({ queryKey: analyticsKeys.experiment(id), queryFn: () => api.experiment(id) });

  let body: ReactNode;
  if (detail.data) {
    body =
      detail.data.metrics.length === 0 ? (
        <Empty>
          <p>The harness stored no metrics for this run.</p>
        </Empty>
      ) : (
        <DataTable
          label={`Metrics of ${detail.data.label}, ${detail.data.mode}`}
          rows={detail.data.metrics}
          columns={METRIC_COLUMNS}
          rowKey={({ name, band }) => `${name}/${band}`}
        />
      );
  } else if (detail.isError) {
    body = (
      <LoadFailed
        what="This run's metrics"
        error={detail.error}
        onRetry={() => {
          void detail.refetch();
        }}
      />
    );
  } else {
    body = <Loading>Loading the metrics</Loading>;
  }

  return (
    <div className="flex flex-col gap-3 pt-3">
      <h3 className="px-6 font-semibold">
        {detail.data ? `Metrics: ${detail.data.label}, ${detail.data.mode}, ${detail.data.workload}` : "Metrics"}
      </h3>
      {body}
    </div>
  );
}
