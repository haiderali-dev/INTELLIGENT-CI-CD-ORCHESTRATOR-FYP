/**
 * The Service catalog page's requests. `catalog/services.yaml` is the source of truth (4.6.1): the
 * API reads it, lists live branches, and lets an Admin add a validated service or resync the file.
 */

import { api, type ApiClient } from "./client";
import { answer } from "./request";
import type { components } from "./schema";

export type NewCatalogService = components["schemas"]["CreateServiceRequest"];

export function catalogApi(client: ApiClient = api) {
  return {
    services: () => answer(client.GET("/api/services")),

    create: (service: NewCatalogService) => answer(client.POST("/api/services", { body: service })),

    /** Whether the repository answered, and its branches when it did. */
    branches: (service: string) =>
      answer(client.GET("/api/services/{name}/branches", { params: { path: { name: service } } })),

    resync: () => answer(client.POST("/api/services/resync")),
  };
}

export type CatalogApi = ReturnType<typeof catalogApi>;

/* What the client returns (D-059). */
type Returned<K extends keyof CatalogApi> = Awaited<ReturnType<CatalogApi[K]>>;
export type ServiceList = Returned<"services">;
export type CatalogService = ServiceList["items"][number];
export type Branches = Returned<"branches">;
export type Resync = Returned<"resync">;
