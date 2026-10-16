/**
 * The Admin page's requests. Every one needs the Admin role; the backend refuses anyone else with
 * FORBIDDEN, and writes an audit entry for every change.
 */

import { api, type ApiClient } from "./client";
import { answer } from "./request";
import type { components } from "./schema";

export type Role = components["schemas"]["Role"];
export type NewUser = components["schemas"]["CreateUserRequest"];
export type UserChange = components["schemas"]["UpdateUserRequest"];

export function adminApi(client: ApiClient = api) {
  return {
    users: (limit: number) =>
      answer(client.GET("/api/admin/users", { params: { query: { limit } } })),

    createUser: (user: NewUser) => answer(client.POST("/api/admin/users", { body: user })),

    updateUser: (id: string, change: UserChange) =>
      answer(
        client.PATCH("/api/admin/users/{user_id}", {
          params: { path: { user_id: id } },
          body: change,
        }),
      ),

    /** The roles, weakest first, as the guards treat them. */
    roles: () => answer(client.GET("/api/admin/roles")),

    policy: () => answer(client.GET("/api/admin/policy")),

    audit: (limit: number, offset: number) =>
      answer(client.GET("/api/admin/audit", { params: { query: { limit, offset } } })),
  };
}

export type AdminApi = ReturnType<typeof adminApi>;

/* What the client returns (D-059). */
type Returned<K extends keyof AdminApi> = Awaited<ReturnType<AdminApi[K]>>;
export type UserPage = Returned<"users">;
export type AdminUser = UserPage["items"][number];
export type Policy = Returned<"policy">;
export type AuditPage = Returned<"audit">;
export type AuditEntry = AuditPage["items"][number];

export const adminKeys = {
  users: ["admin-users"] as const,
  roles: ["admin-roles"] as const,
  policy: ["admin-policy"] as const,
  audits: ["admin-audit"] as const,
  audit: (offset: number) => ["admin-audit", offset] as const,
};
