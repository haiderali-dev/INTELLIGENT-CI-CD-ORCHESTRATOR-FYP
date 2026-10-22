import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Radio, RefreshCw } from "lucide-react";
import { useEffect, useId, useState } from "react";
import { Link } from "react-router";

import { failureMessage } from "@/api/errors";
import type { Queue } from "@/api/queueApi";
import { failureOf } from "@/api/request";
import type { NavItem } from "@/app/shell/nav";
import { button } from "@/components/button";
import { PageHeader } from "@/components/PageHeader";
import { cn } from "@/lib/cn";
import { formatTimeOfDay } from "@/lib/format";
import { MEDIUM_QUERY, useMediaQuery } from "@/lib/useMediaQuery";
import { queueKeys, useQueueApi } from "@/queue/queueApiContext";
import { optimizerStatus, ranked } from "@/queue/queueModel";
import { HeldItems, QueueRanking, UnscoredItems } from "@/queue/QueueRanking";
import { NumbersSwitch, ScoreKey } from "@/queue/ScoreKey";
import { ASSISTANTS } from "@/workspace/assistants";
import type { LiveStatus } from "@/ws/LiveEventsClient";
import { useLiveEvent, useLiveStatus } from "@/ws/liveEventsContext";

/**
 * How often the page asks again, besides on every queue and run event (D-060). The events cover
 * only the runs the backend tracks, and a wait, with its aging, grows while nothing happens.
 */
export const QUEUE_REFRESH_MS = 10_000;

/** A little longer than the bars' 240 ms growth, after which nothing grows again. */
const GROW_MS = 300;

/** Every event that can change the queue: a run entering it or leaving it, or a chain moving on. */
const QUEUE_EVENTS = ["queue.changed", "run.queued", "run.started", "run.finished"] as const;

const LIVE_WORDS: Record<LiveStatus, string> = {
  open: "Live",
  idle: "Connecting",
  connecting: "Connecting",
  reconnecting: "Reconnecting",
  "signed-out": "Not live",
};

/**
 * The Queue (4.7.3, DESIGN.md section 4): the plugin's live ranking, one row per waiting job, each
 * explaining its own rank with a score bar. It answers the room's question, "why is that job
 * first?", where it is asked.
 */
export function QueuePage({ item }: { item: Pick<NavItem, "label" | "description"> }) {
  const api = useQueueApi();
  const queryClient = useQueryClient();
  const queue = useQuery({
    queryKey: queueKeys.queue,
    queryFn: () => api.queue(),
    refetchInterval: QUEUE_REFRESH_MS,
  });
  useLiveEvent(QUEUE_EVENTS, () => {
    void queryClient.invalidateQueries({ queryKey: queueKeys.queue });
  });
  const [showNumbers, setShowNumbers] = useState(false);
  const wide = useMediaQuery(MEDIUM_QUERY, true);
  const grow = useGrowOnce(queue.data !== undefined);

  const { data } = queue;
  let body;
  if (!data) {
    body = queue.isError ? (
      <div role="alert" className="flex flex-col gap-3 px-6 py-6">
        <p className="max-w-[68ch]">
          <span className="font-semibold">The queue could not be loaded. </span>
          {failureMessage(failureOf(queue.error))}
        </p>
        <button
          type="button"
          onClick={() => {
            void queue.refetch();
          }}
          className={cn(button(), "self-start")}
        >
          Try again
        </button>
      </div>
    ) : (
      <p className="px-6 py-6 text-graphite">Loading the queue</p>
    );
  } else if (!data.available) {
    body = <Unavailable reason={data.unavailable_reason ?? null} />;
  } else {
    const items = ranked(data);
    body = (
      <>
        {queue.isRefetchError ? (
          <p role="status" className="border-b border-rule px-6 py-3">
            <span className="font-semibold">The queue could not be refreshed. </span>
            {`${failureMessage(failureOf(queue.error))} Showing the ranking from ${formatTimeOfDay(new Date(queue.dataUpdatedAt))}.`}
          </p>
        ) : null}
        {items.length > 0 ? (
          <>
            <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 border-b border-rule px-6 py-3">
              <ScoreKey />
              <NumbersSwitch checked={showNumbers} onCheckedChange={setShowNumbers} />
            </div>
            <QueueRanking
              wide={wide}
              items={items}
              weights={data.weights}
              showNumbers={showNumbers}
              grow={grow}
            />
          </>
        ) : data.unscored_items.length > 0 ? (
          <p className="px-6 pt-6">No waiting job has a score yet.</p>
        ) : data.held_items.length > 0 ? (
          <p className="px-6 pt-6">Nothing is ready to run: every queued job is held back.</p>
        ) : (
          <NothingWaiting />
        )}
        <UnscoredItems items={data.unscored_items} />
        <HeldItems items={data.held_items} />
      </>
    );
  }

  return (
    <>
      <PageHeader
        title={item.label}
        description={item.description}
        aside={<QueueStatus queue={data} />}
      />
      {body}
    </>
  );
}

/**
 * True while the first ranking appears: the bars grow once, then every later change jumps straight
 * to its new value (DESIGN.md section 6).
 */
function useGrowOnce(ready: boolean): boolean {
  const [grown, setGrown] = useState(false);
  useEffect(() => {
    if (!ready || grown) {
      return;
    }
    const timer = window.setTimeout(() => {
      setGrown(true);
    }, GROW_MS);
    return () => {
      window.clearTimeout(timer);
    };
  }, [ready, grown]);
  return ready && !grown;
}

/** "5 waiting", the optimizer's state, and whether the page is hearing live events. Health is a
 * word and an icon in Ink or Graphite, never a state colour (DESIGN.md section 2). */
function QueueStatus({ queue }: { queue: Queue | undefined }) {
  const live = useLiveStatus();
  const optimizer = queue ? optimizerStatus(queue) : null;
  const Icon = live === "open" ? Radio : RefreshCw;
  return (
    <ul aria-label="Queue status" className="flex flex-wrap items-center gap-x-6 gap-y-1 pt-1">
      {queue?.available ? (
        <li>
          <span className="font-semibold tabular-nums">{queue.queue_length}</span> waiting
        </li>
      ) : null}
      {queue?.available && queue.held_items.length > 0 ? (
        <li>
          <span className="font-semibold tabular-nums">{queue.held_items.length}</span> held back
        </li>
      ) : null}
      {optimizer ? <li>{optimizer}</li> : null}
      <li className={cn("inline-flex items-center gap-1.5", live !== "open" && "text-graphite")}>
        <Icon aria-hidden="true" className="size-4" />
        {LIVE_WORDS[live]}
      </li>
    </ul>
  );
}

/** DESIGN.md section 6: never an empty bar, but what happened instead. */
function Unavailable({ reason }: { reason: string | null }) {
  const headingId = useId();
  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-2 px-6 py-6">
      <h2 id={headingId} className="text-lg font-semibold">
        Ranking unavailable
      </h2>
      <p className="max-w-[68ch]">
        {reason
          ? `The backend could not read the queue optimizer plugin: ${reason}.`
          : "The backend could not read the queue optimizer plugin."}
      </p>
      <p className="max-w-[68ch] text-graphite">
        {`The ranking comes from the plugin, so there is nothing to rank until it answers. This page asks again every ${String(QUEUE_REFRESH_MS / 1000)} seconds.`}
      </p>
    </section>
  );
}

/** An empty queue invites the action that fills it (4.7.5). */
function NothingWaiting() {
  return (
    <div className="flex flex-col gap-4 px-6 py-6">
      <p className="max-w-[68ch]">
        Nothing is waiting for an executor. Ask an assistant for a build, and it is ranked here while
        it waits.
      </p>
      <div className="flex flex-wrap gap-3">
        {(["freestyle", "pipeline"] as const).map((kind) => (
          <Link key={kind} to={`/assistants/${kind}`} className={button()}>
            {`Ask the ${ASSISTANTS[kind].name}`}
          </Link>
        ))}
      </div>
    </div>
  );
}
