import type { Message, Service } from "@/api/assistantApi";
import { button } from "@/components/button";

import { FallbackNotice } from "./FallbackNotice";
import { IntentMessage } from "./IntentMessage";
import { LiveRunCard } from "./LiveRunCard";
import { MessageText } from "./Thread";

type Payload = NonNullable<Message["payload"]>;
type HelpCard = { title: string; lines: string[] };

/**
 * One assistant reply, drawn from its payload's kind (D-058). The message's words come first,
 * except where a card says the same thing better: a question is asked by the clarification, and
 * help is a list.
 */
export function ReplyView({
  message,
  conversationId,
  services,
  branches,
  latest,
  sending,
  onSend,
}: {
  message: Message;
  conversationId: string;
  services: readonly Service[];
  branches: Readonly<Record<string, readonly string[]>>;
  latest: boolean;
  sending: boolean;
  onSend: (text: string) => void;
}) {
  const { payload, content } = message;
  if (!payload) {
    return <MessageText>{content}</MessageText>;
  }

  switch (payload.kind) {
    case "intent":
    case "question":
      return (
        <>
          {payload.kind === "intent" ? <MessageText>{content}</MessageText> : null}
          <IntentMessage
            commandId={payload.command_id}
            reply={payload}
            conversationId={conversationId}
            services={services}
            branches={branches}
            latest={latest}
            sending={sending}
            onAnswer={onSend}
          />
        </>
      );

    case "refusal":
      return (
        <>
          <MessageText>{content}</MessageText>
          <CancelRunning payload={payload} disabled={!latest || sending} onSend={onSend} />
          <Fallback payload={payload} />
        </>
      );

    case "help":
      return <Help card={payload.help} fallback={content} />;

    case "status":
      return (
        <>
          <MessageText>{content}</MessageText>
          {payload.chain ? (
            <LiveRunCard chainId={payload.chain.id} snapshot={payload.chain} />
          ) : null}
          <Fallback payload={payload} />
        </>
      );

    case "run":
      return (
        <>
          <MessageText>{content}</MessageText>
          <LiveRunCard chainId={payload.chain_id} />
          <Fallback payload={payload} />
        </>
      );

    case "rerun":
    case "cancel":
    case "pipeline":
      return (
        <>
          <MessageText>{content}</MessageText>
          <Fallback payload={payload} />
        </>
      );
  }
}

function Fallback({ payload }: { payload: Payload }) {
  return "ai_fallback" in payload && payload.ai_fallback ? <FallbackNotice /> : null;
}

/** "Here is what I can do", as a title and a list. */
function Help({ card, fallback }: { card: HelpCard | null; fallback: string }) {
  if (!card) {
    return <MessageText>{fallback}</MessageText>;
  }
  return (
    <div className="flex flex-col gap-1">
      <p className="font-semibold">{card.title}</p>
      <ul className="flex list-disc flex-col gap-0.5 pl-5">
        {card.lines.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
    </div>
  );
}

/**
 * 4.5.5: an Admin may cancel the running chain and go ahead. The policy says when the offer stands;
 * the button asks the assistant to cancel, in words, as the person would.
 */
function CancelRunning({
  payload,
  disabled,
  onSend,
}: {
  payload: Extract<Payload, { kind: "refusal" }>;
  disabled: boolean;
  onSend: (text: string) => void;
}) {
  const service = payload.intent.service;
  if (!payload.policy?.can_cancel_running || !service) {
    return null;
  }
  const request = `Cancel the ${service} chain`;
  return (
    <button
      type="button"
      aria-disabled={disabled}
      onClick={() => {
        if (!disabled) {
          onSend(request);
        }
      }}
      className={button()}
    >
      {`Cancel the running ${service} chain`}
    </button>
  );
}
