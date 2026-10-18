import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CircleAlert } from "lucide-react";
import { Dialog } from "radix-ui";
import { useId, useState } from "react";

import { adminApi, adminKeys } from "@/api/adminApi";
import { useApi } from "@/api/apiClientContext";
import { failureMessage } from "@/api/errors";
import { failureOf } from "@/api/request";
import { button } from "@/components/button";
import { useToast } from "@/components/toast/toastContext";
import { cn } from "@/lib/cn";

import { PASSWORD_MAX, PASSWORD_MIN } from "./NewUserForm";

/**
 * The way back for someone who forgot their password: the sign-in page tells them to ask an Admin.
 * The Admin chooses the new one and hands it over, as with a first password. Every session the old
 * one opened ends, so the dialog says that before anything changes.
 */
export function ResetPassword({ userId, email }: { userId: string; email: string }) {
  const api = useApi(adminApi);
  const queryClient = useQueryClient();
  const toast = useToast();
  const ids = useId();
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [tooShort, setTooShort] = useState(false);

  const reset = useMutation({
    mutationFn: () => api.resetPassword(userId, password),
    onSuccess: async () => {
      toast(`${email} has a new password and was signed out everywhere`);
      setOpen(false);
      setPassword("");
      await queryClient.invalidateQueries({ queryKey: adminKeys.audits });
    },
  });

  const submit = () => {
    if (reset.isPending) {
      return;
    }
    if (password.length < PASSWORD_MIN || password.length > PASSWORD_MAX) {
      setTooShort(true);
      return;
    }
    setTooShort(false);
    reset.mutate();
  };

  return (
    <Dialog.Root
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) {
          setPassword("");
          setTooShort(false);
          reset.reset();
        }
      }}
    >
      <Dialog.Trigger asChild>
        <button type="button" className={cn(button(), "h-8 px-3 text-sm max-md:h-11")}>
          Reset password
        </button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-ink/40" />
        <Dialog.Content className="fixed top-1/2 left-1/2 z-50 flex w-[32rem] max-w-[calc(100vw-2rem)] -translate-x-1/2 -translate-y-1/2 flex-col gap-4 rounded-float bg-panel p-6 text-ink shadow-float dark:border dark:border-rule">
          <Dialog.Title className="text-lg font-semibold">{`Reset the password of ${email}`}</Dialog.Title>
          <Dialog.Description className="max-w-[68ch]">
            They are signed out everywhere at once, and sign in again with the password you choose
            here. Give it to them yourself: nothing is emailed.
          </Dialog.Description>
          <form
            noValidate
            onSubmit={(event) => {
              event.preventDefault();
              submit();
            }}
            className="flex flex-col gap-4"
          >
            {reset.isError ? (
              <p role="alert" className="flex gap-2 border-l-4 border-ink bg-ground px-3 py-2 text-sm">
                <CircleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
                <span>{`The password was not changed. ${failureMessage(failureOf(reset.error))}`}</span>
              </p>
            ) : null}
            <div className="flex flex-col gap-1">
              <label htmlFor={`${ids}-password`} className="text-sm font-semibold">
                New password
              </label>
              <input
                id={`${ids}-password`}
                type="password"
                autoComplete="new-password"
                value={password}
                onChange={(event) => {
                  setPassword(event.target.value);
                }}
                aria-invalid={tooShort ? true : undefined}
                aria-describedby={`${ids}-hint${tooShort ? ` ${ids}-error` : ""}`}
                className={cn(
                  "h-11 w-full rounded-control border bg-panel px-3 text-base text-ink",
                  tooShort ? "border-2 border-ink" : "border-graphite",
                )}
              />
              <p id={`${ids}-hint`} className="text-sm text-graphite">
                {`At least ${String(PASSWORD_MIN)} characters.`}
              </p>
              {tooShort ? (
                <p id={`${ids}-error`} className="flex items-start gap-1 text-sm">
                  <CircleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
                  {`Choose a password of ${String(PASSWORD_MIN)} to ${String(PASSWORD_MAX)} characters.`}
                </p>
              ) : null}
            </div>
            <div className="flex flex-wrap justify-end gap-2">
              <Dialog.Close asChild>
                <button type="button" className={button()}>
                  Cancel
                </button>
              </Dialog.Close>
              <button
                type="submit"
                aria-disabled={reset.isPending}
                className={button({ variant: "primary" })}
              >
                {reset.isPending ? "Resetting" : "Reset password"}
              </button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
