import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleAlert } from "lucide-react";

import { failureMessage } from "@/api/errors";
import { failureOf, type Command, type Service } from "@/api/assistantApi";
import type { components } from "@/api/schema";

import { keys, useAssistantApi } from "./assistantApiContext";
import { Clarification } from "./Clarification";
import { FallbackNotice } from "./FallbackNotice";
import { GENERATING_ACTIONS, intentFields } from "./intent";
import { IntentCard } from "./IntentCard";

type IntentRecord = components["schemas"]["IntentRecord"];

/**
 * What the assistant understood, as it stands now. The reply's record is how it was when the
 * reply was written; an edit changes the command's record and can change what comes next, such as
 * a question when HIGH needs a reason. So the card reads the command, and the reply's copy fills in
 * until it arrives.
 */
export function IntentMessage({
  commandId,
  reply,
  conversationId,
  services,
  branches,
  latest,
  sending,
  onAnswer,
}: {
  commandId: string;
  reply: IntentRecord;
  conversationId: string;
  services: readonly Service[];
  branches: Readonly<Record<string, readonly string[]>>;
  /** Only the newest message's question can still be answered. */
  latest: boolean;
  sending: boolean;
  onAnswer: (answer: string) => void;
}) {
  const api = useAssistantApi();
  const queryClient = useQueryClient();
  const command = useQuery({ queryKey: keys.command(commandId), queryFn: () => api.command(commandId) });
  const record = command.data?.record ?? reply;

  const generate = useMutation({
    mutationFn: () => api.generate(commandId),
    onSuccess: async (pipeline) => {
      queryClient.setQueryData(keys.pipeline(pipeline.id), pipeline);
      await queryClient.invalidateQueries({ queryKey: keys.conversation(conversationId) });
    },
  });

  const edit = useMutation({
    mutationFn: (changes: Parameters<typeof api.editIntent>[1]) => api.editIntent(commandId, changes),
    onSuccess: (updated: Command) => {
      queryClient.setQueryData(keys.command(commandId), updated);
    },
  });

  const { disposition, intent, policy, question } = record;
  const failure = generate.error ?? edit.error;

  return (
    <div className="flex flex-col gap-3">
      {disposition === "READY" && GENERATING_ACTIONS.has(intent.action) ? (
        <IntentCard
          intent={intentFields(record)}
          services={services}
          branches={branches}
          generating={generate.isPending}
          onGenerate={() => {
            generate.mutate();
          }}
          onEdit={async (changes) => {
            await edit.mutateAsync(changes).catch(() => undefined);
          }}
        />
      ) : null}

      {(disposition === "NEEDS_CLARIFICATION" || disposition === "NEEDS_JUSTIFICATION") && question ? (
        <Clarification
          question={question.question}
          options={question.options}
          onAnswer={onAnswer}
          disabled={!latest || sending}
        />
      ) : null}

      {/* A downgrade, such as HIGH to MEDIUM when the day's quota is spent, or a refusal after an
          edit: the policy's own sentences. */}
      {policy && policy.outcome !== "ALLOW" && disposition !== "NEEDS_JUSTIFICATION" ? (
        <ul className="flex flex-col gap-1 text-sm">
          {policy.reasons.map(({ code, message }) => (
            <li key={`${code} ${message}`}>{message}</li>
          ))}
        </ul>
      ) : null}

      {failure ? (
        <p role="alert" className="flex items-start gap-1.5 text-sm">
          <CircleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
          <span>{failureMessage(failureOf(failure))}</span>
        </p>
      ) : null}

      {record.ai_fallback ? <FallbackNotice /> : null}
    </div>
  );
}
