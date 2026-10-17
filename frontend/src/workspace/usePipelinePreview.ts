import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import type { Message, Pipeline } from "@/api/assistantApi";
import { failureOf } from "@/api/request";
import { failureMessage } from "@/api/errors";

import type { ApproveResult } from "./ApproveAndRun";
import type { AssistantKind } from "./assistants";
import { keys, useAssistantApi } from "./assistantApiContext";
import type { PreviewArtifact, PreviewPlan } from "./PreviewPanel";
import { previewSummary } from "./previewSummary";

interface Explanation {
  text: string | null;
  loading: boolean;
  error: string | null;
}

const NOT_EXPLAINED: Explanation = { text: null, loading: false, error: null };

/** The pipelines this conversation generated, oldest first: each "pipeline" reply names one. */
function pipelineIds(messages: readonly Message[]): string[] {
  return messages.flatMap(({ payload }) => (payload?.kind === "pipeline" ? [payload.pipeline_id] : []));
}

/** What a plan renders to: one config.xml per freestyle job, or the Pipeline's Jenkinsfile. The
 * previous plan's version of each is kept, to show what a regenerate changed. */
function artifacts(
  assistant: AssistantKind,
  pipeline: Pipeline,
  previous: Pipeline | null,
): PreviewArtifact[] {
  if (assistant === "pipeline") {
    const name = pipeline.jobs[0]?.name ?? "Jenkinsfile";
    return pipeline.jenkinsfile === null
      ? []
      : [{ name, text: pipeline.jenkinsfile, previous: previous?.jenkinsfile ?? null }];
  }
  return pipeline.jobs.map(({ name, config_xml: text }) => ({
    name,
    text,
    previous: previous?.jobs.find((job) => job.name === name)?.config_xml ?? null,
  }));
}

/**
 * The preview of the conversation's newest plan (4.7.4, 4.6.2 step 4), and the one-line summary
 * the bottom sheet's handle shows. An edited spec is held here, per plan, so closing a drawer
 * does not lose it.
 */
export function usePipelinePreview(
  assistant: AssistantKind,
  conversationId: string | null,
  messages: readonly Message[],
): { plan: PreviewPlan | null; summary: string } {
  const api = useAssistantApi();
  const queryClient = useQueryClient();
  const ids = pipelineIds(messages);
  const latestId = ids.at(-1) ?? null;
  const previousId = ids.at(-2) ?? null;

  const latest = useQuery({
    queryKey: keys.pipeline(latestId ?? "none"),
    queryFn: () => api.pipeline(latestId ?? ""),
    enabled: latestId !== null,
  });
  const before = useQuery({
    queryKey: keys.pipeline(previousId ?? "none"),
    queryFn: () => api.pipeline(previousId ?? ""),
    enabled: previousId !== null,
  });

  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [explanations, setExplanations] = useState<Record<string, Explanation>>({});
  // One key per plan: a retried approval of the same plan cannot start a second chain (4.6.4).
  const approvalKeys = useRef(new Map<string, string>());

  const refresh = async (pipeline: Pipeline) => {
    queryClient.setQueryData(keys.pipeline(pipeline.id), pipeline);
    if (conversationId) {
      await queryClient.invalidateQueries({ queryKey: keys.conversation(conversationId) });
    }
  };

  const regenerate = useMutation({
    mutationFn: ({ id, spec }: { id: string; spec: string | null }) => api.regenerate(id, spec),
    onSuccess: async (pipeline, { id }) => {
      // The edit became a plan of its own; the draft for the old one is done with.
      setDrafts((current) =>
        Object.fromEntries(Object.entries(current).filter(([planId]) => planId !== id)),
      );
      await refresh(pipeline);
    },
  });

  const pipeline = latest.data ?? null;
  if (!pipeline || !latestId) {
    return { plan: null, summary: previewSummary(null) };
  }
  // The diff is against the plan this one replaced, when both answer the same request.
  const previous =
    before.data && before.data.command_id === pipeline.command_id ? before.data : null;
  const draft = drafts[pipeline.id];
  const spec = draft ?? pipeline.spec_yaml;
  const checks = pipeline.validation?.checks ?? [];
  const explanation = explanations[pipeline.id] ?? NOT_EXPLAINED;

  const setExplanation = (id: string, next: Explanation) => {
    setExplanations((current) => ({ ...current, [id]: next }));
  };

  const plan: PreviewPlan = {
    spec: {
      yaml: spec,
      previous: draft === undefined ? (previous?.spec_yaml ?? null) : null,
      onChange: (yaml) => {
        setDrafts((current) => ({ ...current, [pipeline.id]: yaml }));
      },
      edited: draft !== undefined && draft !== pipeline.spec_yaml,
      onRegenerate: () => {
        regenerate.mutate({ id: pipeline.id, spec: draft ?? null });
      },
      regenerating: regenerate.isPending,
    },
    artifacts: artifacts(assistant, pipeline, previous),
    progress: pipeline.progress,
    checks,
    explanation: {
      ...explanation,
      onExplain: () => {
        const id = pipeline.id;
        setExplanation(id, { text: null, loading: true, error: null });
        api
          .explain(id, (text) => {
            setExplanation(id, { text, loading: true, error: null });
          })
          .then((text) => {
            setExplanation(id, { text, loading: false, error: null });
          })
          .catch((error: unknown) => {
            setExplanation(id, { text: null, loading: false, error: failureMessage(failureOf(error)) });
          });
      },
    },
    approval: {
      summary: pipeline.summary,
      ready: pipeline.status === "VALIDATED",
      approvedAt: pipeline.status === "APPROVED" ? (pipeline.approved_at ?? "") : null,
      onApprove: async (): Promise<ApproveResult> => {
        let key = approvalKeys.current.get(pipeline.id);
        if (!key) {
          key = crypto.randomUUID();
          approvalKeys.current.set(pipeline.id, key);
        }
        try {
          await api.approve(pipeline.id, key);
        } catch (error) {
          return { ok: false, failure: failureOf(error) };
        }
        await Promise.all([
          queryClient.invalidateQueries({ queryKey: keys.pipeline(pipeline.id) }),
          conversationId
            ? queryClient.invalidateQueries({ queryKey: keys.conversation(conversationId) })
            : Promise.resolve(),
        ]);
        return { ok: true };
      },
    },
  };
  return { plan, summary: previewSummary(pipeline) };
}
