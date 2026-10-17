import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, type ReactNode } from "react";
import { Link, useLocation, useSearchParams } from "react-router";

import { useApi } from "@/api/apiClientContext";
import { catalogApi } from "@/api/catalogApi";
import { PAGE_MAX, runsApi, runsKeys, type ChainSummary } from "@/api/runsApi";
import type { NavItem } from "@/app/shell/nav";
import { BuildStateLabel } from "@/components/BuildStateLabel";
import { DataTable, type Column } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { Empty, Loading, LoadFailed } from "@/components/PageStates";
import { formatDuration, formatWhen, parseApiTime } from "@/lib/format";
import { ChainDetail } from "@/runs/ChainDetail";
import {
  assistantOf,
  chainDurationMs,
  chainState,
  filterChains,
  isAssistantFilter,
  isResultFilter,
  RESULT_FILTERS,
} from "@/runs/runsModel";
import { keys } from "@/workspace/assistantApiContext";
import { useLiveEvent } from "@/ws/liveEventsContext";

/** Every event that moves a run on, so the list and the open run follow it. */
const RUN_EVENTS = [
  "run.queued",
  "run.started",
  "run.updated",
  "run.finished",
  "chain.updated",
  "chain.finished",
  "chain.stages",
] as const;

/**
 * Jobs and runs (4.7.3): every run the assistants started, by service, assistant and result, with
 * its stages and the end of its log. A run here is a chain: the jobs one approval or re-run
 * started, which is the only record that carries stages and the runs whose logs can be read
 * (D-061). The filters and the open run are in the address, so a reload or a shared link keeps
 * them.
 */
export function RunsPage({ item }: { item: Pick<NavItem, "label" | "description"> }) {
  const api = useApi(runsApi);
  const queryClient = useQueryClient();
  const location = useLocation();
  const [params, setParams] = useSearchParams();
  const service = params.get("service") || null;
  const assistantParam = params.get("assistant");
  const resultParam = params.get("result");
  const assistant = isAssistantFilter(assistantParam) ? assistantParam : null;
  const result = isResultFilter(resultParam) ? resultParam : null;
  const chainId = params.get("chain");
  const runId = params.get("run");

  const query = { ...(service ? { service } : {}), limit: PAGE_MAX };
  const chains = useQuery({ queryKey: runsKeys.chainList(query), queryFn: () => api.chains(query) });
  useLiveEvent(RUN_EVENTS, () => {
    void queryClient.invalidateQueries({ queryKey: runsKeys.chainLists });
    void queryClient.invalidateQueries({ queryKey: keys.chains });
  });

  /** This page's address with some parameters changed; null removes one. */
  const linkTo = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    for (const [name, value] of Object.entries(changes)) {
      if (value === null) {
        next.delete(name);
      } else {
        next.set(name, value);
      }
    }
    const search = next.toString();
    return search ? `${location.pathname}?${search}` : location.pathname;
  };
  const setFilter = (name: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) {
      next.set(name, value);
    } else {
      next.delete(name);
    }
    setParams(next, { replace: true });
  };

  const columns: Column<ChainSummary>[] = [
    {
      header: "Started",
      nowrap: true,
      cell: ({ started_at: started }) => formatWhen(parseApiTime(started)),
    },
    {
      header: "Run",
      rowHeader: true,
      nowrap: true,
      cell: (chain) => (
        <Link
          to={linkTo({ chain: chain.id, run: null })}
          replace
          aria-current={chain.id === chainId ? "true" : undefined}
          className="font-semibold underline underline-offset-4"
        >
          {chain.jobs[0] ?? chain.service}
        </Link>
      ),
    },
    { header: "Service", nowrap: true, cell: ({ service: name }) => name },
    { header: "Assistant", nowrap: true, cell: ({ job_type: type }) => assistantOf(type) },
    {
      header: "Jobs",
      align: "right",
      cell: ({ jobs }) => `${String(jobs.length)} ${jobs.length === 1 ? "job" : "jobs"}`,
    },
    {
      header: "Result",
      nowrap: true,
      cell: ({ status }) => {
        const { state, label } = chainState(status);
        return <BuildStateLabel state={state} {...(label ? { label } : {})} />;
      },
    },
    {
      header: "Start to finish",
      align: "right",
      nowrap: true,
      cell: (chain) => {
        const took = chainDurationMs(chain);
        return took === null ? "Not finished" : formatDuration(took);
      },
    },
  ];

  let body: ReactNode;
  if (chains.data) {
    const { items, total } = chains.data;
    const shown = filterChains(items, { assistant, result });
    const filtered = Boolean(service || assistant || result);
    if (items.length === 0 && !filtered) {
      body = (
        <Empty>
          <p>No runs yet. Approve a plan in either assistant, and its run appears here.</p>
          <p className="flex flex-wrap gap-x-6 gap-y-2">
            <Link to="/assistants/freestyle" className="font-semibold underline underline-offset-4">
              Open the Freestyle Assistant
            </Link>
            <Link to="/assistants/pipeline" className="font-semibold underline underline-offset-4">
              Open the Pipeline Assistant
            </Link>
          </p>
        </Empty>
      );
    } else if (shown.length === 0) {
      body = (
        <Empty>
          <p>No runs match these filters.</p>
          <p>
            <Link to={location.pathname} replace className="font-semibold underline underline-offset-4">
              Clear the filters
            </Link>
          </p>
        </Empty>
      );
    } else {
      body = (
        <>
          <p aria-live="polite" className="px-6 text-sm text-graphite tabular-nums">
            {total > items.length
              ? `${String(shown.length)} of the newest ${String(items.length)} runs, of ${String(total)} in all. The assistant and result filters look at these ${String(items.length)}.`
              : `${String(shown.length)} ${shown.length === 1 ? "run" : "runs"}, newest first.`}
          </p>
          <DataTable
            label="Runs, newest first"
            rows={shown}
            columns={columns}
            rowKey={({ id }) => id}
            selectedKey={chainId}
          />
        </>
      );
    }
  } else if (chains.isError) {
    body = (
      <LoadFailed
        what="The runs"
        error={chains.error}
        onRetry={() => {
          void chains.refetch();
        }}
      />
    );
  } else {
    body = <Loading>Loading the runs</Loading>;
  }

  return (
    <>
      <PageHeader title={item.label} description={item.description} />
      <Filters
        service={service}
        assistant={assistant}
        result={result}
        onChange={setFilter}
      />
      <div className="flex flex-col gap-3 py-5">{body}</div>
      {chainId ? <ChainDetail chainId={chainId} runId={runId} linkTo={linkTo} /> : null}
    </>
  );
}

function Filters({
  service,
  assistant,
  result,
  onChange,
}: {
  service: string | null;
  assistant: string | null;
  result: string | null;
  onChange: (name: string, value: string) => void;
}) {
  const api = useApi(catalogApi);
  const services = useQuery({ queryKey: keys.services, queryFn: () => api.services() });
  const ids = useId();
  const names = services.data?.items.map(({ name }) => name) ?? [];
  // A service named in the address stays choosable while the catalog loads, or if it left it.
  if (service && !names.includes(service)) {
    names.push(service);
  }

  return (
    <div role="group" aria-label="Filters" className="flex flex-wrap gap-x-6 gap-y-3 border-b border-rule px-6 py-3">
      <Select id={`${ids}-service`} label="Service" value={service ?? ""} onChange={(value) => {
        onChange("service", value);
      }}>
        <option value="">Any service</option>
        {names.map((name) => (
          <option key={name} value={name}>
            {name}
          </option>
        ))}
      </Select>
      <Select id={`${ids}-assistant`} label="Assistant" value={assistant ?? ""} onChange={(value) => {
        onChange("assistant", value);
      }}>
        <option value="">Either assistant</option>
        <option value="freestyle">Freestyle Assistant</option>
        <option value="pipeline">Pipeline Assistant</option>
      </Select>
      <Select id={`${ids}-result`} label="Result" value={result ?? ""} onChange={(value) => {
        onChange("result", value);
      }}>
        <option value="">Any result</option>
        {Object.entries(RESULT_FILTERS).map(([value, { label }]) => (
          <option key={value} value={value}>
            {label}
          </option>
        ))}
      </Select>
    </div>
  );
}

function Select({
  id,
  label,
  value,
  onChange,
  children,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-sm font-semibold">
        {label}
      </label>
      <select
        id={id}
        value={value}
        onChange={(event) => {
          onChange(event.target.value);
        }}
        className="h-10 min-w-48 rounded-control border border-graphite bg-panel px-2 text-base max-md:h-11"
      >
        {children}
      </select>
    </div>
  );
}
