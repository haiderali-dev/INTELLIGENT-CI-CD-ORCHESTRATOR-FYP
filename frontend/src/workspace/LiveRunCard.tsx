import { useQuery } from "@tanstack/react-query";

import type { RunCardData } from "@/api/assistantApi";
import { failureOf } from "@/api/request";
import { failureMessage } from "@/api/errors";

import { keys, useAssistantApi } from "./assistantApiContext";
import { RunCard } from "./RunCard";
import { runCardView } from "./runCardModel";

/**
 * A chain's run card, kept current. The page refetches every card when a run, chain or queue event
 * arrives (src/ws), so nothing here polls. A status reply's own copy of the card is shown until the
 * current one arrives.
 */
export function LiveRunCard({
  chainId,
  snapshot,
}: {
  chainId: string;
  snapshot?: RunCardData | null;
}) {
  const api = useAssistantApi();
  const card = useQuery({
    queryKey: keys.chain(chainId),
    queryFn: () => api.chain(chainId),
    ...(snapshot ? { placeholderData: snapshot } : {}),
  });

  if (card.data) {
    const view = runCardView(card.data);
    return (
      <RunCard
        jobName={view.jobName}
        queue={view.queue}
        stages={view.stages}
        result={view.result}
        jenkinsUrl={view.jenkinsUrl}
      />
    );
  }
  if (card.isError) {
    return (
      <p className="text-sm">
        <span className="font-semibold">The run card could not be loaded. </span>
        {failureMessage(failureOf(card.error))}
      </p>
    );
  }
  return <p className="text-sm text-graphite">Loading the run card</p>;
}
