import { useApi } from "@/api/apiClientContext";
import { assistantApi, type AssistantApi } from "@/api/assistantApi";

/** The requests the assistant pages make, over the client in context (src/api/apiClientContext). */
export function useAssistantApi(): AssistantApi {
  return useApi(assistantApi);
}

/** React Query keys, one place, so a mutation invalidates exactly what it changed. */
export const keys = {
  services: ["services"] as const,
  branches: (service: string) => ["branches", service] as const,
  conversations: (assistant: string) => ["conversations", assistant] as const,
  conversation: (id: string) => ["conversation", id] as const,
  command: (id: string) => ["command", id] as const,
  pipeline: (id: string) => ["pipeline", id] as const,
  chains: ["chain"] as const,
  chain: (id: string) => ["chain", id] as const,
};
