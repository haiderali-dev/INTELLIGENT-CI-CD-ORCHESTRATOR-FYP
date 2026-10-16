import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CircleAlert } from "lucide-react";
import { useId, type ReactNode } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { adminApi, adminKeys, type Role } from "@/api/adminApi";
import { useApi } from "@/api/apiClientContext";
import { failureMessage, type Failure } from "@/api/errors";
import { failureOf } from "@/api/request";
import { ROLE_LABEL, roleLabel } from "@/auth/roles";
import { button } from "@/components/button";
import { useToast } from "@/components/toast/toastContext";
import { cn } from "@/lib/cn";

/** The backend's own limits (app/api/admin.py, CreateUserRequest). */
const PASSWORD_MIN = 12;
const PASSWORD_MAX = 256;

const newUserSchema = z.object({
  email: z
    .string()
    .trim()
    .min(1, "Enter their email address.")
    .pipe(z.email("Enter an email address in the form name@example.com.")),
  password: z
    .string()
    .min(PASSWORD_MIN, `Choose a password of at least ${String(PASSWORD_MIN)} characters.`)
    .max(PASSWORD_MAX, `Choose a password of ${String(PASSWORD_MAX)} characters or fewer.`),
  role: z.string().min(1),
});

type NewUserInput = z.input<typeof newUserSchema>;
type NewUserValues = z.output<typeof newUserSchema>;
type FieldName = keyof NewUserInput;

/** The fields a VALIDATION_FAILED answer names, so each message goes under its own field. */
function fieldErrors(failure: Failure): Partial<Record<FieldName, string>> {
  if (failure.kind !== "api") {
    return {};
  }
  const { code, message, details } = failure.error;
  if (code !== "VALIDATION_FAILED") {
    return {};
  }
  // A taken address comes back as a conflict naming the email.
  if ("email" in details && !("fields" in details)) {
    return { email: message };
  }
  const fields = details.fields;
  if (typeof fields !== "object" || fields === null) {
    return {};
  }
  const found: Partial<Record<FieldName, string>> = {};
  for (const name of ["email", "password", "role"] as const) {
    const text = (fields as Record<string, unknown>)[name];
    if (typeof text === "string") {
      found[name] = text;
    }
  }
  return found;
}

/**
 * Adds a user with a first password the Admin chooses and hands over. Nothing is emailed, and no
 * endpoint resets a password later, so the form says so.
 */
export function NewUserForm({ roles }: { roles: readonly string[] | null }) {
  const api = useApi(adminApi);
  const queryClient = useQueryClient();
  const toast = useToast();
  const ids = useId();
  const form = useForm<NewUserInput, unknown, NewUserValues>({
    resolver: zodResolver(newUserSchema),
    defaultValues: { email: "", password: "", role: "DEVELOPER" },
  });
  const { errors } = form.formState;

  const create = useMutation({
    mutationFn: (values: NewUserValues) =>
      api.createUser({ email: values.email, password: values.password, role: values.role as Role }),
    onSuccess: async (user) => {
      toast(`${user.email} was added as ${ROLE_LABEL[user.role]}`);
      form.reset();
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: adminKeys.users }),
        queryClient.invalidateQueries({ queryKey: adminKeys.audits }),
      ]);
    },
    onError: (error) => {
      for (const [name, message] of Object.entries(fieldErrors(failureOf(error)))) {
        form.setError(name as FieldName, { message });
      }
    },
  });

  const failure = create.isError ? failureOf(create.error) : null;
  const unplaced = failure && Object.keys(fieldErrors(failure)).length === 0 ? failure : null;

  return (
    <form
      noValidate
      aria-labelledby={`${ids}-title`}
      onSubmit={(event) => {
        if (create.isPending) {
          event.preventDefault();
          return;
        }
        void form.handleSubmit((values) => {
          create.mutate(values);
        })(event);
      }}
      className="mx-6 mt-2 flex max-w-[40rem] flex-col gap-4 border border-rule p-4"
    >
      <h3 id={`${ids}-title`} className="font-semibold">
        Add a user
      </h3>
      {unplaced ? (
        <p role="alert" className="flex gap-2 border-l-4 border-ink bg-ground px-3 py-2 text-sm">
          <CircleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
          <span>{`The user was not added. ${failureMessage(unplaced)}`}</span>
        </p>
      ) : null}
      <Field id={`${ids}-email`} label="Email" error={errors.email?.message}>
        <input
          id={`${ids}-email`}
          type="email"
          autoComplete="off"
          autoCapitalize="none"
          spellCheck={false}
          aria-invalid={errors.email ? true : undefined}
          aria-describedby={errors.email ? `${ids}-email-error` : undefined}
          className={inputClass(Boolean(errors.email))}
          {...form.register("email")}
        />
      </Field>
      <Field
        id={`${ids}-password`}
        label="First password"
        hint={`At least ${String(PASSWORD_MIN)} characters. Give it to them yourself: nothing is emailed, and it cannot be reset here later.`}
        error={errors.password?.message}
      >
        <input
          id={`${ids}-password`}
          type="password"
          autoComplete="new-password"
          aria-invalid={errors.password ? true : undefined}
          aria-describedby={`${ids}-password-hint${errors.password ? ` ${ids}-password-error` : ""}`}
          className={inputClass(Boolean(errors.password))}
          {...form.register("password")}
        />
      </Field>
      <Field id={`${ids}-role`} label="Role" error={errors.role?.message}>
        <select
          id={`${ids}-role`}
          className={cn(inputClass(false), "pr-2")}
          {...form.register("role")}
        >
          {(roles ?? ["DEVELOPER"]).map((role) => (
            <option key={role} value={role}>
              {roleLabel(role)}
            </option>
          ))}
        </select>
      </Field>
      <button
        type="submit"
        aria-disabled={create.isPending}
        className={cn(button({ variant: "primary" }), "self-start")}
      >
        {create.isPending ? "Adding" : "Add user"}
      </button>
    </form>
  );
}

function inputClass(invalid: boolean): string {
  return cn(
    "h-11 w-full rounded-control border bg-panel px-3 text-base text-ink",
    invalid ? "border-2 border-ink" : "border-graphite",
  );
}

/** A label above its control, a hint and the error under it, tied to it by id. */
function Field({
  id,
  label,
  hint,
  error,
  children,
}: {
  id: string;
  label: string;
  hint?: string;
  error: string | undefined;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-sm font-semibold">
        {label}
      </label>
      {children}
      {hint ? (
        <p id={`${id}-hint`} className="text-sm text-graphite">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={`${id}-error`} className="flex items-start gap-1 text-sm">
          <CircleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
          {error}
        </p>
      ) : null}
    </div>
  );
}
