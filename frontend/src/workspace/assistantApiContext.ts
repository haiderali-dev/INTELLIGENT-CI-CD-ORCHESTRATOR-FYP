import { createContext, useContext } from "react";

import { assistantApi, type AssistantApi } from "@/api/assistantApi";

const defaultApi = assistantApi();

/** The requests the assistant pages make. The app uses the real client; a test can supply one
 * over a fake backend. */
export const AssistantApiContext = createContext<AssistantApi>(defaultApi);

export function useAssistantApi(): AssistantApi {
  return useContext(AssistantApiContext);
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
