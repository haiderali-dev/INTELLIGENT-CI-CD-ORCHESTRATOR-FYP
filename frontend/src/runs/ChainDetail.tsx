import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { Link } from "react-router";

import { useApi } from "@/api/apiClientContext";
import { runsApi } from "@/api/runsApi";
import { BuildStateLabel } from "@/components/BuildStateLabel";
import { Loading, LoadFailed } from "@/components/PageStates";
import { formatDuration, formatWhen, parseApiTime } from "@/lib/format";
import { keys } from "@/workspace/assistantApiContext";
import { RunCard } from "@/workspace/RunCard";
import { jobState, runCardView } from "@/workspace/runCardModel";

import { ExplainFailure } from "./ExplainFailure";
import { LogTail } from "./LogTail";

/**
 * One chain in full: its run card (queue position, stages, result and a Jenkins link), each job's
 * run, the log of the run chosen, and Explain failure when a job failed. Focus moves here when a
 * run is chosen from the list, so the change is seen and heard.
 */
export function ChainDetail({
  chainId,
  runId,
  linkTo,
}: {
  chainId: string;
  /** The run whose log is shown; by default the one that failed, or else the last that ran. */
  runId: string | null;
  /** The address for this page with other `params` set, keeping the filters. */
  linkTo: (params: Record<string, string | null>) => string;
}) {
  const api = useApi(runsApi);
  const card = useQuery({ queryKey: keys.chain(chainId), queryFn: () => api.chain(chainId) });
  const heading = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    heading.current?.focus();
  }, [chainId]);

  // Named by its service and start, apart from the run card inside, which is named by its job.
  const title = card.data
    ? card.data.started_at
      ? `${card.data.service}, started ${formatWhen(parseApiTime(card.data.started_at))}`
      : `${card.data.service}, not started`
    : "The chosen run";
  let body;
  if (card.data) {
    const view = runCardView(card.data);
    const runs = card.data.jobs.flatMap((job) => (job.run ? [{ job, run: job.run }] : []));
    const chosen =
      runs.find(({ run }) => run.id === runId) ??
      runs.find(({ run }) => run.id === card.data.failed_run_id) ??
      runs.at(-1) ??
      null;
    const failed = runs.find(({ run }) => run.id === card.data.failed_run_id) ?? null;

    body = (
      <div className="flex flex-col gap-5 px-6">
        <RunCard
          jobName={view.jobName}
          queue={view.queue}
          stages={view.stages}
          result={view.result}
          jenkinsUrl={view.jenkinsUrl}
        />
        {failed ? <ExplainFailure runId={failed.run.id} jobName={failed.job.name} /> : null}
        <div className="flex flex-col gap-2">
          <h3 className="font-semibold">Jobs</h3>
          <ul aria-label="Jobs in this run" className="flex flex-col">
            {card.data.jobs.map((job) => (
              <li
                key={job.name}
                className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-rule py-2 text-sm"
              >
                <span className="min-w-0 font-semibold">{job.name}</span>
                {/* A job the chain never reached is "Not started", as the run card says it; "Not
                    built" is Jenkins' word for a build it skipped. One name per thing (principle 4). */}
                <BuildStateLabel
                  state={jobState(job.state)}
                  {...(job.state === "not_started" || job.state === "waiting"
                    ? { label: "Not started" }
                    : {})}
                />
                {job.run ? (
                  <>
                    <span className="tabular-nums">{`#${String(job.run.build_number)}`}</span>
                    {job.run.duration_ms === null || job.run.result === "RUNNING" ? null : (
                      <span className="tabular-nums">{formatDuration(job.run.duration_ms)}</span>
                    )}
                    {chosen?.run.id === job.run.id ? (
                      <span className="text-graphite">Log shown below</span>
                    ) : (
                      <Link
                        to={linkTo({ run: job.run.id })}
                        replace
                        className="font-semibold underline underline-offset-4"
                      >
                        {`Show the log of ${job.name}`}
                      </Link>
                    )}
                  </>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
        {chosen ? (
          <LogTail
            key={chosen.run.id}
            runId={chosen.run.id}
            jobName={chosen.job.name}
            buildNumber={chosen.run.build_number}
            url={chosen.run.url}
          />
        ) : (
          <p className="text-sm text-graphite">No job has started yet, so there is no log.</p>
        )}
      </div>
    );
  } else if (card.isError) {
    body = (
      <LoadFailed
        what="This run"
        error={card.error}
        onRetry={() => {
          void card.refetch();
        }}
      />
    );
  } else {
    body = <Loading>Loading the run</Loading>;
  }

  return (
    <section aria-labelledby={`chain-${chainId}`} className="flex flex-col gap-3 border-t border-rule py-5">
      <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2 px-6">
        <h2 id={`chain-${chainId}`} ref={heading} tabIndex={-1} className="text-lg font-semibold">
          {title}
        </h2>
        <Link
          to={linkTo({ chain: null, run: null })}
          replace
          className="font-semibold underline underline-offset-4"
        >
          Close
        </Link>
      </div>
      {body}
    </section>
  );
}
