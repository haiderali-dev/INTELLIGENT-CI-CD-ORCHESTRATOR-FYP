/**
 * The requests the assistant pages make (BUILD_PROMPT 4.4.4's Catalog, Assistants and Generation
 * groups), each typed by the generated schema. A failure is thrown as `ApiRequestError`
 * (`./request`).
 *
 * Every field the pages read is typed in the schema (D-058). The pipeline's `plan` and `approval`,
 * a job preview's `stage` and the approval response's `result` stay untyped, and nothing here
 * reads them (D-059).
 */

import { api, type ApiClient } from "./client";
import { answer, ApiRequestError } from "./request";
import type { components } from "./schema";

export type AssistantName = "freestyle" | "pipeline";
export type IntentEdit = components["schemas"]["IntentEdit"];

/*
 * The response types are what the client returns, not `components["schemas"][...]` directly.
 * openapi-fetch passes response data through `Readable<T>`, which rebuilds every object and drops
 * any property whose type is exactly `null`: `chain: null` on the "nothing to re-run" and
 * "nothing to cancel" replies. The two would then be different types under one name, and
 * TypeScript refuses to mix them. Nothing reads those two keys.
 */
type Returned<K extends keyof AssistantApi> = Awaited<ReturnType<AssistantApi[K]>>;
export type Conversation = Returned<"conversations">["items"][number];
export type ConversationDetail = Returned<"conversation">;
export type Message = ConversationDetail["messages"][number];
export type MessageExchange = Returned<"send">;
export type Command = Returned<"command">;
export type Pipeline = Returned<"pipeline">;
export type RunCardData = Returned<"chain">;
export type Service = Returned<"services">["items"][number];
export type BranchList = Returned<"branches">;

export function assistantApi(client: ApiClient = api) {
  return {
    services: () => answer(client.GET("/api/services")),

    branches: (service: string) =>
      answer(client.GET("/api/services/{name}/branches", { params: { path: { name: service } } })),

    conversations: (assistant: AssistantName) =>
      answer(client.GET("/api/conversations", { params: { query: { assistant, limit: 50 } } })),

    conversation: (id: string) =>
      answer(
        client.GET("/api/conversations/{conversation_id}", {
          params: { path: { conversation_id: id } },
        }),
      ),

    createConversation: (assistant: AssistantName) =>
      answer(
        client.POST("/api/assistants/{assistant}/conversations", {
          params: { path: { assistant } },
        }),
      ),

    send: (conversationId: string, text: string, signal?: AbortSignal) =>
      answer(
        client.POST("/api/conversations/{conversation_id}/messages", {
          params: { path: { conversation_id: conversationId } },
          body: { text },
          ...(signal ? { signal } : {}),
        }),
      ),

    command: (id: string) =>
      answer(client.GET("/api/commands/{command_id}", { params: { path: { command_id: id } } })),

    editIntent: (id: string, changes: IntentEdit) =>
      answer(
        client.PATCH("/api/commands/{command_id}/intent", {
          params: { path: { command_id: id } },
          body: changes,
        }),
      ),

    generate: (commandId: string) =>
      answer(
        client.POST("/api/commands/{command_id}/generate", {
          params: { path: { command_id: commandId } },
        }),
      ),

    pipeline: (id: string) =>
      answer(
        client.GET("/api/pipelines/{pipeline_id}", { params: { path: { pipeline_id: id } } }),
      ),

    regenerate: (id: string, specYaml: string | null) =>
      answer(
        client.POST("/api/pipelines/{pipeline_id}/regenerate", {
          params: { path: { pipeline_id: id } },
          body: specYaml === null ? null : { spec_yaml: specYaml },
        }),
      ),

    /** Approve and run. The key makes a repeat of the same approval start nothing new (4.6.4). */
    approve: (id: string, key: string) =>
      answer(
        client.POST("/api/pipelines/{pipeline_id}/approve", {
          params: { path: { pipeline_id: id }, header: { "Idempotency-Key": key } },
        }),
      ),

    chain: (id: string) =>
      answer(client.GET("/api/chains/{chain_id}", { params: { path: { chain_id: id } } })),

    /** The explanation, streamed as plain text: `onText` gets the whole text so far each time
     * more arrives. Resolves with the whole text. */
    explain: async (id: string, onText: (text: string) => void, signal?: AbortSignal) => {
      const stream = await answer(
        client.POST("/api/pipelines/{pipeline_id}/explain", {
          params: { path: { pipeline_id: id } },
          parseAs: "stream",
          ...(signal ? { signal } : {}),
        }),
      );
      if (!stream) {
        return "";
      }
      const reader = stream.pipeThrough(new TextDecoderStream()).getReader();
      let text = "";
      for (;;) {
        let chunk: ReadableStreamReadResult<string>;
        try {
          chunk = await reader.read();
        } catch (error) {
          if (error instanceof DOMException && error.name === "AbortError") {
            throw error;
          }
          throw new ApiRequestError({ kind: "unreachable" });
        }
        if (chunk.done) {
          return text;
        }
        text += chunk.value;
        onText(text);
      }
    },
  };
}

export type AssistantApi = ReturnType<typeof assistantApi>;
