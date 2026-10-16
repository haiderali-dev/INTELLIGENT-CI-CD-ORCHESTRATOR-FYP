/**
 * `GET /api/health`: the database, Jenkins and the AI provider, each with a status and a detail.
 * The AI provider's entry reports how the provider is configured, not whether it answers: the
 * backend never calls the model from a health check, so as not to spend the free tier's quota.
 */

import { api, type ApiClient } from "./client";
import { answer } from "./request";

export function systemApi(client: ApiClient = api) {
  return {
    health: () => answer(client.GET("/api/health")),
  };
}

export type SystemApi = ReturnType<typeof systemApi>;
export type Health = Awaited<ReturnType<SystemApi["health"]>>;
export type ComponentHealth = Health["components"][string];

export const systemKeys = {
  health: ["health"] as const,
};
