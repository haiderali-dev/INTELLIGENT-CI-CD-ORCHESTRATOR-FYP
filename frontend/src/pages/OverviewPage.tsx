import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, CloudOff, PowerOff } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router";

import { useApi } from "@/api/apiClientContext";
import { failureMessage } from "@/api/errors";
import { queueApi } from "@/api/queueApi";
import { failureOf } from "@/api/request";
import { PAGE_MAX, runsApi, runsKeys, type ChainSummary, type Run } from "@/api/runsApi";
import { systemApi, systemKeys, type ComponentHealth } from "@/api/systemApi";
import type { NavItem } from "@/app/shell/nav";
import { useSignedInUser } from "@/auth/sessionContext";
import { stateFromResult } from "@/components/buildState";
import { BuildStateLabel } from "@/components/BuildStateLabel";
import { PageHeader } from "@/components/PageHeader";
import { Empty, Loading, LoadFailed, PageSection, StatusWord } from "@/components/PageStates";
import { ScoreBar } from "@/components/ScoreBar";
import { formatDuration, formatWhen, ordinal, parseApiTime } from "@/lib/format";
import { QUEUE_REFRESH_MS } from "@/pages/QueuePage";
import { queueKeys } from "@/queue/queueApiContext";
import { ExplainFailure } from "@/runs/ExplainFailure";
import { currentStep, finishedRuns } from "@/runs/runsModel";
import { keys } from "@/workspace/assistantApiContext";
import { useLiveEvent } from "@/ws/liveEventsContext";

/** How many finished runs "recent results" means. */
export const RECENT_RESULTS = 10;
/** Enough runs to find ten finished ones even with several still building. */
const RECENT_WINDOW = 50;

const LIVE_EVENTS = [
  "run.queued",
  "run.started",
  "run.updated",
  "run.finished",
  "chain.updated",
  "chain.finished",
  "chain.stages",
  "queue.changed",
] as const;

/**
 * The Overview (DESIGN.md section 4): one sheet led by the number of jobs waiting, then my active
 * runs with their score bars, then the latest results, so the room sees what is happening now
 * without opening another page. The AI provider's line says how it is configured.
 */
export function OverviewPage({ item }: { item: Pick<NavItem, "label" | "description"> }) {
  const runs = useApi(runsApi);
  const queueRequests = useApi(queueApi);
  const queryClient = useQueryClient();
  const me = useSignedInUser();

  const queue = useQuery({
    queryKey: queueKeys.queue,
    queryFn: () => queueRequests.queue(),
    refetchInterval: QUEUE_REFRESH_MS,
  });
  const activeQuery = { active: true, limit: PAGE_MAX };
  const active = useQuery({
    queryKey: runsKeys.chainList(activeQuery),
    queryFn: () => runs.chains(activeQuery),
  });
  const recentQuery = { limit: RECENT_WINDOW };
  const recent = useQuery({
    queryKey: runsKeys.runList(recentQuery),
    queryFn: () => runs.runs(recentQuery),
  });
  useLiveEvent(LIVE_EVENTS, () => {
    void queryClient.invalidateQueries({ queryKey: runsKeys.chainLists });
    void queryClient.invalidateQueries({ queryKey: runsKeys.runLists });
    void queryClient.invalidateQueries({ queryKey: keys.chains });
    void queryClient.invalidateQueries({ queryKey: queueKeys.queue });
  });

  // Mine: the API lists every active chain, and each says who started it.
  const mine = active.data?.items.filter(({ started_by: by }) => by === me?.id) ?? null;
  const finished = recent.data ? finishedRuns(recent.data.items, RECENT_RESULTS) : null;
  const failedCount = finished?.filter(({ result }) => result === "FAILURE").length ?? 0;

  return (
    <>
      <PageHeader title={item.label} description={item.description} aside={<ProviderStatus />} />

      <dl className="flex flex-wrap items-end gap-x-12 gap-y-4 border-b border-rule px-6 py-6">
        <Figure
          lead
          term={queue.data?.queue_length === 1 ? "job waiting" : "jobs waiting"}
          value={
            queue.data?.available
              ? String(queue.data.queue_length)
              : queue.data || queue.isError
                ? null
                : undefined
          }
          note={
            queue.data && !queue.data.available
              ? `The ranking is unavailable: ${queue.data.unavailable_reason ?? "the plugin did not answer"}.`
              : queue.isError
                ? failureMessage(failureOf(queue.error))
                : null
          }
        />
        <Figure
          term={mine?.length === 1 ? "my active run" : "my active runs"}
          value={mine ? String(mine.length) : active.isError ? null : undefined}
        />
        <Figure
          term={finished && finished.length === 0 ? "runs finished yet" : "runs failed"}
          value={
            finished
              ? finished.length === 0
                ? "None"
                : `${String(failedCount)} of the last ${String(finished.length)}`
              : recent.isError
                ? null
                : undefined
          }
        />
      </dl>

      <PageSection title="My active runs">
        {mine ? (
          mine.length === 0 ? (
            <Empty>
              <p>
                You have no runs in progress. Ask an assistant for a build, test or deploy to start
                one.
              </p>
              <p className="flex flex-wrap gap-x-6 gap-y-2">
                <Link to="/assistants/freestyle" className="font-semibold underline underline-offset-4">
                  Open the Freestyle Assistant
                </Link>
                <Link to="/assistants/pipeline" className="font-semibold underline underline-offset-4">
                  Open the Pipeline Assistant
                </Link>
              </p>
            </Empty>
          ) : (
            <ul aria-label="My active runs" className="flex flex-col">
              {mine.map((chain) => (
                <ActiveRun key={chain.id} chain={chain} />
              ))}
            </ul>
          )
        ) : active.isError ? (
          <LoadFailed
            what="Your active runs"
            error={active.error}
            onRetry={() => {
              void active.refetch();
            }}
          />
        ) : (
          <Loading>Loading your active runs</Loading>
        )}
      </PageSection>

      <PageSection title="Recent results" className="border-t border-rule">
        {finished ? (
          finished.length === 0 ? (
            <Empty>
              <p>No run has finished yet. Results appear here as runs end.</p>
            </Empty>
          ) : (
            <ul aria-label="Recent results" className="flex flex-col">
              {finished.map((run) => (
                <RecentResult key={run.id} run={run} />
              ))}
            </ul>
          )
        ) : recent.isError ? (
          <LoadFailed
            what="The recent results"
            error={recent.error}
            onRetry={() => {
              void recent.refetch();
            }}
          />
        ) : (
          <Loading>Loading the recent results</Loading>
        )}
      </PageSection>
    </>
  );
}

/**
 * A figure under its number. The lead one, jobs waiting, is the hero size (DESIGN.md section 3);
 * the others are a size down. `undefined` is still loading; null could not be known.
 */
function Figure({
  term,
  value,
  note = null,
  lead = false,
}: {
  term: string;
  value: string | null | undefined;
  note?: string | null;
  lead?: boolean;
}) {
  return (
    <div className="flex max-w-[40ch] flex-col">
      <dt className="order-2 text-graphite">{term}</dt>
      <dd
        className={
          value === undefined || value === null
            ? "order-1 text-xl font-semibold text-graphite"
            : lead
              ? "order-1 text-hero font-semibold"
              : "order-1 text-xl font-semibold tabular-nums"
        }
      >
        {value === undefined ? "Loading" : value === null ? "Unknown" : value}
      </dd>
      {note ? <dd className="order-3 text-sm text-graphite">{note}</dd> : null}
    </div>
  );
}

/** One of my running chains: where it waits, with its score bar, or what it is doing now. */
function ActiveRun({ chain }: { chain: ChainSummary }) {
  const api = useApi(runsApi);
  const card = useQuery({ queryKey: keys.chain(chain.id), queryFn: () => api.chain(chain.id) });
  const name = chain.jobs[0] ?? chain.service;

  let now: ReactNode;
  if (card.data?.queue) {
    const { queue } = card.data;
    now = (
      <>
        <span className="tabular-nums">{`${ordinal(queue.rank)} in queue`}</span>
        <ScoreBar score={queue.score} parts={queue.components} weights={queue.weights} />
      </>
    );
  } else if (card.data) {
    const step = currentStep(card.data);
    now = (
      <>
        <BuildStateLabel state={step.state} />
        <span className="text-graphite">{step.text}</span>
      </>
    );
  } else if (card.isError) {
    now = (
      <span className="text-graphite">{`Its run card could not be loaded. ${failureMessage(failureOf(card.error))}`}</span>
    );
  } else {
    now = <span className="text-graphite">Loading</span>;
  }

  return (
    <li className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-rule px-6 py-3 text-sm">
      <Link
        to={`/runs?chain=${encodeURIComponent(chain.id)}`}
        className="min-w-0 text-base font-semibold underline underline-offset-4"
      >
        {name}
      </Link>
      {now}
      <span className="text-graphite tabular-nums">{`Started ${formatWhen(parseApiTime(chain.started_at))}`}</span>
    </li>
  );
}

/** A finished run: its result as an icon and a word, how long it took, and when it ended. */
function RecentResult({ run }: { run: Run }) {
  const name = run.job_name ?? "A deleted job";
  return (
    <li className="flex flex-col gap-2 border-b border-rule px-6 py-3 text-sm">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        <BuildStateLabel state={stateFromResult(run.result)} className="font-semibold" />
        <span className="min-w-0 text-base">{`${name} #${String(run.build_number)}`}</span>
        {run.duration_ms === null ? null : (
          <span className="tabular-nums">{formatDuration(run.duration_ms)}</span>
        )}
        {run.finished_at ? (
          <span className="text-graphite tabular-nums">{formatWhen(parseApiTime(run.finished_at))}</span>
        ) : null}
      </div>
      {run.result === "FAILURE" ? <ExplainFailure runId={run.id} jobName={name} /> : null}
    </li>
  );
}

const PROVIDER_WORDS: Record<ComponentHealth["status"], { icon: typeof Bot; word: string; quiet: boolean }> = {
  up: { icon: Bot, word: "Live", quiet: false },
  degraded: { icon: Bot, word: "Degraded", quiet: true },
  disabled: { icon: PowerOff, word: "Off", quiet: true },
  down: { icon: CloudOff, word: "Down", quiet: true },
};

/**
 * The AI provider as the backend reports it. That report is its configuration, not a call to the
 * model, so it never claims the model is answering (backend app/api/health.py).
 */
function ProviderStatus() {
  const api = useApi(systemApi);
  const health = useQuery({ queryKey: systemKeys.health, queryFn: () => api.health() });
  const llm = health.data?.components.llm;

  return (
    <div aria-label="AI provider" role="group" className="flex max-w-[40ch] flex-col gap-0.5 text-sm">
      <span className="text-graphite">AI provider</span>
      {llm ? (
        <>
          <StatusWord {...PROVIDER_WORDS[llm.status]} />
          <span className="text-graphite">{llm.detail}</span>
        </>
      ) : health.isError ? (
        <>
          <span className="font-semibold">Unknown</span>
          <span className="text-graphite">{failureMessage(failureOf(health.error))}</span>
        </>
      ) : health.data ? (
        <span className="font-semibold">Not reported</span>
      ) : (
        <span className="text-graphite">Checking</span>
      )}
    </div>
  );
}
