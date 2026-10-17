import type { User } from "./session";

export type Role = User["role"];

/** Each role's name on screen, wherever a role is shown. */
export const ROLE_LABEL: Record<Role, string> = {
  DEVELOPER: "Developer",
  DEVOPS: "DevOps",
  ADMIN: "Admin",
};

/** A role the API names, in words; one this page does not know is shown as the API sent it. */
export function roleLabel(role: string): string {
  return (ROLE_LABEL as Readonly<Record<string, string | undefined>>)[role] ?? role;
}

/**
 * Whether to offer what only an Admin may do: the Admin page and the catalog resync, which the
 * backend refuses to anyone else with FORBIDDEN. This decides only what is offered; the backend
 * still decides what is allowed.
 */
export function isAdmin(user: Pick<User, "role"> | null): boolean {
  return user?.role === "ADMIN";
}
