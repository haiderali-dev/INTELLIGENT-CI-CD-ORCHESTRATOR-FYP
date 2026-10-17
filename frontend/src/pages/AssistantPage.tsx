import { useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleAlert } from "lucide-react";
import { useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";

import type { ConversationDetail } from "@/api/assistantApi";
import { failureOf } from "@/api/request";
import { failureMessage } from "@/api/errors";
import { ASSISTANTS, type AssistantKind } from "@/workspace/assistants";
import { keys, useAssistantApi } from "@/workspace/assistantApiContext";
import { ChatList } from "@/workspace/ChatList";
import { Composer } from "@/workspace/Composer";
import { EmptyState } from "@/workspace/EmptyState";
import { PreviewPanel } from "@/workspace/PreviewPanel";
import { ReplyView } from "@/workspace/ReplyView";
import { MessageText, Thread, ThreadMessage } from "@/workspace/Thread";
import { inThreadOrder } from "@/workspace/threadOrder";
import { usePipelinePreview } from "@/workspace/usePipelinePreview";
import { WorkspaceLayout } from "@/workspace/WorkspaceLayout";
import { useLiveEvent } from "@/ws/liveEventsContext";

/** Events that can change a run card: the page refetches every card it shows when one arrives. */
const RUN_EVENTS = [
  "run.queued",
  "run.started",
  "run.updated",
  "run.finished",
  "chain.updated",
  "chain.stages",
  "chain.finished",
  "queue.changed",
] as const;

const NEW_CHAT = "new";

/**
 * An assistant's page (T6.5): the Freestyle Assistant and the Pipeline Assistant are this page
 * with their own identity, sidebar entry, header, empty state and preview (4.6, 4.7.4).
 *
 * The chat is in the address, `/assistants/<assistant>/<chat id>`, so it survives a reload. A new
 * chat is only created when its first message is sent, so an abandoned "New chat" leaves nothing
 * behind.
 */
export function AssistantPage({ assistant }: { assistant: AssistantKind }) {
  const api = useAssistantApi();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const { chatId } = useParams();
  const activeId = chatId ?? null;
  const base = `/assistants/${assistant}`;
  const { name } = ASSISTANTS[assistant];

  const services = useQuery({ queryKey: keys.services, queryFn: api.services, staleTime: 300_000 });
  const catalog = services.data?.items ?? [];
  const branchLists = useQueries({
    queries: catalog.map((service) => ({
      queryKey: keys.branches(service.name),
      queryFn: () => api.branches(service.name),
      staleTime: 60_000,
    })),
  });
  // Only lists Git could give; a service without one offers its default branch.
  const branches = Object.fromEntries(
    branchLists.flatMap(({ data }) => (data?.available ? [[data.service, data.branches]] : [])),
  );

  const chats = useQuery({
    queryKey: keys.conversations(assistant),
    queryFn: () => api.conversations(assistant),
  });
  const conversation = useQuery({
    queryKey: keys.conversation(activeId ?? NEW_CHAT),
    queryFn: () => api.conversation(activeId ?? ""),
    enabled: activeId !== null,
  });
  const messages = inThreadOrder(conversation.data?.messages ?? []);

  useLiveEvent(RUN_EVENTS, () => {
    void queryClient.invalidateQueries({ queryKey: keys.chains });
  });

  const preview = usePipelinePreview(assistant, activeId, messages);

  // The composer keeps a draft per chat.
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const draftFor = (id: string | null) => id ?? NEW_CHAT;
  const setDraft = (id: string | null, text: string) => {
    setDrafts((current) => ({ ...current, [draftFor(id)]: text }));
  };
  const [focusKey, setFocusKey] = useState(0);
  const [pending, setPending] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const inFlight = useRef<AbortController | null>(null);

  const send = async (text: string) => {
    if (pending !== null) {
      return;
    }
    setNotice(null);
    setPending(text);
    setDraft(activeId, "");
    const abort = new AbortController();
    inFlight.current = abort;
    let id = activeId;
    // A new chat is opened only once its first exchange is stored. Opening it as soon as it was
    // created let the chat's own load race the send: it read the chat empty, landed after the
    // reply, and the page showed an empty chat (caught by T6.8's flows, traced in T6.9).
    let created: string | null = null;
    try {
      if (id === null) {
        id = (await api.createConversation(assistant)).id;
        created = id;
      }
      const chat = id;
      const exchange = await api.send(chat, text, abort.signal);
      queryClient.setQueryData<ConversationDetail>(keys.conversation(chat), (current) =>
        current
          ? { ...current, messages: [...current.messages, exchange.user_message, exchange.assistant_message] }
          : current,
      );
      if (exchange.command) {
        queryClient.setQueryData(keys.command(exchange.command.id), exchange.command);
      }
      await Promise.all([
        created
          ? queryClient.query({ queryKey: keys.conversation(chat), queryFn: () => api.conversation(chat) })
          : queryClient.invalidateQueries({ queryKey: keys.conversation(chat) }),
        queryClient.invalidateQueries({ queryKey: keys.conversations(assistant) }),
      ]);
    } catch (error) {
      if (abort.signal.aborted) {
        setNotice(
          "Stopped waiting for the answer. If the assistant still finishes, its reply appears in this chat.",
        );
      } else {
        setNotice(`Your message was not sent. ${failureMessage(failureOf(error))}`);
        setDraft(id, text);
      }
      if (id !== null) {
        void queryClient.invalidateQueries({ queryKey: keys.conversation(id) });
      }
    } finally {
      // Stopped, failed or answered, a chat that was made is where the person now is.
      if (created !== null) {
        void navigate(`${base}/${created}`);
      }
      setPending(null);
      inFlight.current = null;
    }
  };

  const latestIndex = messages.length - 1;
  const showEmpty =
    pending === null && (activeId === null || (conversation.isSuccess && messages.length === 0));

  let thread;
  if (showEmpty) {
    thread = (
      <EmptyState
        assistant={assistant}
        services={catalog.map(({ name: service }) => service)}
        onExample={(command) => {
          setDraft(activeId, command);
          setFocusKey((key) => key + 1);
        }}
      />
    );
  } else if (activeId !== null && conversation.isError) {
    thread = (
      <div className="flex max-w-[68ch] flex-col gap-2">
        <p className="font-semibold">This chat could not be opened.</p>
        <p>{failureMessage(failureOf(conversation.error))}</p>
        <Link to={base} className="self-start font-semibold underline underline-offset-4">
          Start a new chat
        </Link>
      </div>
    );
  } else if (activeId !== null && conversation.isPending) {
    thread = <p className="text-graphite">Loading the chat</p>;
  } else {
    thread = (
      <Thread label={`Conversation with the ${name}`}>
        {messages.map((message, index) => (
          <ThreadMessage
            key={message.id}
            author={message.role === "USER" ? "user" : "assistant"}
            assistant={assistant}
          >
            {message.role === "USER" || activeId === null ? (
              <MessageText>{message.content}</MessageText>
            ) : (
              <ReplyView
                message={message}
                conversationId={activeId}
                services={catalog}
                branches={branches}
                latest={index === latestIndex && pending === null}
                sending={pending !== null}
                onSend={(answer) => {
                  void send(answer);
                }}
              />
            )}
          </ThreadMessage>
        ))}
        {pending !== null ? (
          <>
            <ThreadMessage author="user" assistant={assistant}>
              <MessageText>{pending}</MessageText>
            </ThreadMessage>
            <ThreadMessage author="assistant" assistant={assistant}>
              <p className="text-graphite">Working on it</p>
            </ThreadMessage>
          </>
        ) : null}
      </Thread>
    );
  }

  return (
    <WorkspaceLayout
      assistant={assistant}
      activeChatId={activeId}
      chats={
        chats.isPending ? (
          <p className="px-4 text-sm text-graphite">Loading your chats</p>
        ) : (
          <ChatList
            chats={chats.data?.items ?? []}
            activeId={activeId}
            onSelect={(id) => {
              void navigate(`${base}/${id}`);
            }}
            onNew={() => {
              void navigate(base);
            }}
          />
        )
      }
      thread={thread}
      composer={
        <div className="flex flex-col gap-2">
          {notice ? (
            <p role="alert" className="flex items-start gap-1.5 text-sm">
              <CircleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
              <span>{notice}</span>
            </p>
          ) : null}
          <Composer
            assistant={assistant}
            value={drafts[draftFor(activeId)] ?? ""}
            onChange={(text) => {
              setDraft(activeId, text);
            }}
            onSend={(text) => {
              void send(text);
            }}
            waiting={pending !== null}
            onStop={() => {
              inFlight.current?.abort();
            }}
            services={catalog.map(({ name: service }) => service)}
            focusKey={focusKey}
          />
        </div>
      }
      preview={<PreviewPanel assistant={assistant} plan={preview.plan} />}
      previewSummary={preview.summary}
    />
  );
}
