import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { useApi } from "@/api/apiClientContext";
import { failureMessage } from "@/api/errors";
import { failureOf } from "@/api/request";
import { runsApi, type RunFailure } from "@/api/runsApi";
import { button } from "@/components/button";
import { cn } from "@/lib/cn";

/**
 * Explain failure (T5.9): why a failed run failed, in plain words, with the log lines that show
 * it. Code finds the facts and the evidence; the model only words them, and says when rules did
 * instead. Asked for on request, because it spends the same quota as the assistants.
 */
export function ExplainFailure({ runId, jobName }: { runId: string; jobName: string }) {
  const api = useApi(runsApi);
  const [asked, setAsked] = useState(false);
  const failure = useQuery({
    queryKey: ["run-failure", runId],
    queryFn: () => api.explain(runId),
    enabled: asked,
    staleTime: Infinity,
    retry: false,
  });

  if (failure.data) {
    return <Explanation failure={failure.data} />;
  }
  return (
    <div className="flex flex-col gap-2">
      {failure.isError ? (
        <p role="alert" className="max-w-[68ch] text-sm">
          <span className="font-semibold">The failure could not be explained. </span>
          {failureMessage(failureOf(failure.error))}
        </p>
      ) : null}
      <button
        type="button"
        aria-disabled={failure.isFetching}
        aria-label={`Explain why ${jobName} failed`}
        onClick={() => {
          if (failure.isFetching) {
            return;
          }
          if (asked) {
            void failure.refetch();
          } else {
            setAsked(true);
          }
        }}
        className={cn(button(), "h-8 self-start px-3 text-sm max-md:h-11")}
      >
        {failure.isFetching ? "Reading the log" : failure.isError ? "Try again" : "Explain failure"}
      </button>
    </div>
  );
}

function Explanation({ failure }: { failure: RunFailure }) {
  const { explanation: words, facts, log } = failure;
  const stage = facts.stage ? `${facts.stage} stage. ` : "";
  return (
    <section
      aria-label={`Why ${failure.job_name} failed`}
      className="flex max-w-[80ch] flex-col gap-2 border-l-4 border-ink bg-ground px-4 py-3"
    >
      <p className="font-semibold">{words.summary}</p>
      <p className="text-sm">
        {stage}
        {facts.tests_failed === null || facts.tests_passed === null
          ? null
          : `${String(facts.tests_failed)} failed and ${String(facts.tests_passed)} passed. `}
        {failure.not_started.length > 0
          ? `Never started because of it: ${failure.not_started.join(", ")}.`
          : null}
      </p>
      {words.evidence.length > 0 ? (
        <pre
          aria-label="The log lines that show it"
          tabIndex={0}
          className="overflow-x-auto border border-rule bg-panel p-2 text-sm"
        >
          {words.evidence.map(({ line, text }) => `${String(line).padStart(4, " ")}  ${text}`).join("\n")}
        </pre>
      ) : null}
      {words.suggestions.length > 0 ? (
        <ul className="list-disc pl-5 text-sm">
          {words.suggestions.map((suggestion) => (
            <li key={suggestion}>{suggestion}</li>
          ))}
        </ul>
      ) : null}
      <p className="text-sm text-graphite">
        {words.source === "rules"
          ? `Worded by rules${words.fallback_reasons.length > 0 ? `, because ${words.fallback_reasons.join("; ")}` : ""}.`
          : `Worded by the ${words.provider} provider${words.model ? `, ${words.model}` : ""}.`}{" "}
        {`The facts and lines come from the log (${String(log.lines)} lines${log.truncated ? ", the end of it" : ""}${log.redactions > 0 ? `, ${String(log.redactions)} secrets masked` : ""}).`}
      </p>
    </section>
  );
}
