import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertDialog } from "radix-ui";
import { useState, type ReactNode } from "react";

import { adminApi, adminKeys, type AdminUser, type Role, type UserChange } from "@/api/adminApi";
import { useApi } from "@/api/apiClientContext";
import { failureMessage } from "@/api/errors";
import { failureOf } from "@/api/request";
import { ROLE_LABEL, roleLabel } from "@/auth/roles";
import { button } from "@/components/button";
import { DataTable, type Column } from "@/components/DataTable";
import { Loading, LoadFailed, PageSection } from "@/components/PageStates";
import { useToast } from "@/components/toast/toastContext";
import { cn } from "@/lib/cn";
import { formatWhen, parseApiTime } from "@/lib/format";

import { NewUserForm } from "./NewUserForm";

/** Every user fits in one page of the API's largest size; the page says so if one day they do not. */
export const USER_LIMIT = 200;

/**
 * Users and roles (4.7.3). An Admin changes a role, deactivates or reactivates someone, or adds a
 * user. Their own role and status are not offered: the backend refuses them, so that the last Admin
 * cannot lock everyone out.
 */
export function UsersSection({ me }: { me: string }) {
  const api = useApi(adminApi);
  const queryClient = useQueryClient();
  const toast = useToast();
  const users = useQuery({ queryKey: adminKeys.users, queryFn: () => api.users(USER_LIMIT) });
  const roles = useQuery({ queryKey: adminKeys.roles, queryFn: () => api.roles() });

  const change = useMutation({
    mutationFn: ({ user, update }: { user: AdminUser; update: UserChange }) =>
      api.updateUser(user.id, update),
    onSuccess: async (updated, { user }) => {
      toast(
        updated.active !== user.active
          ? `${updated.email} was ${updated.active ? "reactivated" : "deactivated"}`
          : `${updated.email} is now ${ROLE_LABEL[updated.role]}`,
      );
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: adminKeys.users }),
        queryClient.invalidateQueries({ queryKey: adminKeys.audits }),
      ]);
    },
  });

  const columns: Column<AdminUser>[] = [
    {
      header: "Email",
      rowHeader: true,
      nowrap: true,
      cell: ({ id, email }) => (
        <span className="inline-flex items-baseline gap-2">
          <span className="font-semibold">{email}</span>
          {id === me ? <span className="text-graphite">you</span> : null}
        </span>
      ),
    },
    {
      header: "Role",
      nowrap: true,
      cell: (user) =>
        user.id === me || !roles.data ? (
          ROLE_LABEL[user.role]
        ) : (
          <select
            aria-label={`Role of ${user.email}`}
            value={user.role}
            disabled={change.isPending}
            onChange={(event) => {
              change.mutate({ user, update: { role: event.target.value as Role } });
            }}
            className="h-9 rounded-control border border-graphite bg-panel px-2 text-sm max-md:h-11"
          >
            {roles.data.map((role) => (
              <option key={role} value={role}>
                {roleLabel(role)}
              </option>
            ))}
          </select>
        ),
    },
    {
      header: "Status",
      nowrap: true,
      cell: (user) => (
        <span className="inline-flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className={cn(!user.active && "text-graphite")}>
            {user.active ? "Active" : "Deactivated"}
          </span>
          {user.id === me ? null : user.active ? (
            <Deactivate
              email={user.email}
              pending={change.isPending}
              onConfirm={() => {
                change.mutate({ user, update: { active: false } });
              }}
            />
          ) : (
            <button
              type="button"
              aria-disabled={change.isPending}
              onClick={() => {
                if (!change.isPending) {
                  change.mutate({ user, update: { active: true } });
                }
              }}
              className={cn(button(), "h-8 px-3 text-sm max-md:h-11")}
            >
              Reactivate
            </button>
          )}
        </span>
      ),
    },
    {
      header: "Added",
      nowrap: true,
      cell: ({ created_at: created }) => formatWhen(parseApiTime(created)),
    },
  ];

  let body: ReactNode;
  if (users.data) {
    const { items, total } = users.data;
    body = (
      <>
        {change.isError ? (
          <p role="alert" className="max-w-[68ch] px-6">
            <span className="font-semibold">The change was not made. </span>
            {failureMessage(failureOf(change.error))}
          </p>
        ) : null}
        {total > items.length ? (
          <p className="px-6 text-sm text-graphite">
            {`The first ${String(items.length)} of ${String(total)} users.`}
          </p>
        ) : null}
        <DataTable label="Users" rows={items} columns={columns} rowKey={({ id }) => id} />
        <p className="max-w-[68ch] px-6 text-sm text-graphite">
          You cannot change your own role or deactivate yourself. Another Admin can.
        </p>
      </>
    );
  } else if (users.isError) {
    body = (
      <LoadFailed
        what="The users"
        error={users.error}
        onRetry={() => {
          void users.refetch();
        }}
      />
    );
  } else {
    body = <Loading>Loading the users</Loading>;
  }

  return (
    <PageSection title="Users and roles">
      {body}
      <NewUserForm roles={roles.data ?? null} />
    </PageSection>
  );
}

/** Deactivating someone takes away their access, so it asks first and says exactly what happens. */
function Deactivate({
  email,
  pending,
  onConfirm,
}: {
  email: string;
  pending: boolean;
  onConfirm: () => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <AlertDialog.Root open={open} onOpenChange={setOpen}>
      <AlertDialog.Trigger asChild>
        <button
          type="button"
          aria-disabled={pending}
          className={cn(button(), "h-8 px-3 text-sm max-md:h-11")}
        >
          Deactivate
        </button>
      </AlertDialog.Trigger>
      <AlertDialog.Portal>
        <AlertDialog.Overlay className="fixed inset-0 z-40 bg-ink/40" />
        <AlertDialog.Content className="fixed top-1/2 left-1/2 z-50 flex w-[32rem] max-w-[calc(100vw-2rem)] -translate-x-1/2 -translate-y-1/2 flex-col gap-4 rounded-float bg-panel p-6 text-ink shadow-float dark:border dark:border-rule">
          <AlertDialog.Title className="text-lg font-semibold">{`Deactivate ${email}?`}</AlertDialog.Title>
          <AlertDialog.Description className="max-w-[68ch]">
            Their next request is refused, and they cannot sign in until an Admin reactivates them.
            Their chats, runs and audit entries stay.
          </AlertDialog.Description>
          <div className="flex flex-wrap justify-end gap-2">
            <AlertDialog.Cancel asChild>
              <button type="button" className={button()}>
                Cancel
              </button>
            </AlertDialog.Cancel>
            <AlertDialog.Action asChild>
              <button type="button" onClick={onConfirm} className={button({ variant: "primary" })}>
                Deactivate
              </button>
            </AlertDialog.Action>
          </div>
        </AlertDialog.Content>
      </AlertDialog.Portal>
    </AlertDialog.Root>
  );
}
