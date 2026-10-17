import { zodResolver } from "@hookform/resolvers/zod";
import { CircleAlert, Eye, EyeOff, Info } from "lucide-react";
import { useState, type ReactNode } from "react";
import { useForm } from "react-hook-form";
import { Navigate, useSearchParams } from "react-router";
import { z } from "zod";

import { failureMessage, retryAfterSeconds, type Failure } from "@/api/errors";
import { PRODUCT_NAME } from "@/app/shell/nav";
import { ThemeSwitch } from "@/app/shell/ThemeSwitch";
import { safeNext } from "@/auth/next";
import { RestoringSession } from "@/auth/RestoringSession";
import type { SignedOutReason } from "@/auth/session";
import { useSession, useSessionClient } from "@/auth/sessionContext";
import { cn } from "@/lib/cn";

const EMAIL_MISSING = "Enter your email address.";
const EMAIL_MALFORMED = "Enter an email address in the form name@example.com.";
const PASSWORD_MISSING = "Enter your password.";
/** The backend's limit (app/api/auth.py, LoginRequest). */
const PASSWORD_MAX = 256;
const PASSWORD_TOO_LONG = `Enter a password of ${PASSWORD_MAX} characters or fewer.`;

const signInSchema = z.object({
  email: z.string().trim().min(1, EMAIL_MISSING).pipe(z.email(EMAIL_MALFORMED)),
  password: z.string().min(1, PASSWORD_MISSING).max(PASSWORD_MAX, PASSWORD_TOO_LONG),
});

type SignInInput = z.input<typeof signInSchema>;
type SignInValues = z.output<typeof signInSchema>;

/** Why the person is here, when they did not come on their own (4.7.3: no dead ends). */
const ARRIVAL: Record<SignedOutReason, string> = {
  "signed-out": "You signed out.",
  expired: "Your session ended. Sign in again to carry on where you were.",
  disabled: "This account is disabled. Ask an administrator to re-enable it.",
  unreachable:
    "The server did not answer, so your session could not be restored. Check that the backend is running, then sign in.",
};

/** What happened and what to do about it, for each way signing in can fail (4.7.5). */
function explain(failure: Failure): { message: string; next?: string } {
  if (failure.kind === "api") {
    switch (failure.error.code) {
      case "INVALID_CREDENTIALS":
        return {
          message: failure.error.message,
          next: "Check both and try again. Forgotten your password? Ask an administrator.",
        };
      case "RATE_LIMITED": {
        const seconds = retryAfterSeconds(failure);
        return {
          message: "Too many sign-in attempts from this computer.",
          next:
            seconds === null
              ? "Wait a minute, then try again."
              : `Wait ${seconds} ${seconds === 1 ? "second" : "seconds"}, then try again.`,
        };
      }
      default:
        return { message: failure.error.message };
    }
  }
  return { message: failureMessage(failure) };
}

export function SignInPage() {
  const state = useSession();
  const session = useSessionClient();
  const [params] = useSearchParams();
  const next = safeNext(params.get("next"));
  const [failure, setFailure] = useState<Failure | null>(null);
  const [showPassword, setShowPassword] = useState(false);

  const form = useForm<SignInInput, unknown, SignInValues>({
    resolver: zodResolver(signInSchema),
    defaultValues: { email: "", password: "" },
  });
  const { errors, isSubmitting } = form.formState;

  if (state.status === "signed-in") {
    return <Navigate to={next} replace />;
  }
  if (state.status === "restoring") {
    return <RestoringSession />;
  }

  const onSubmit = form.handleSubmit(async ({ email, password }) => {
    setFailure(null);
    const result = await session.signIn(email, password);
    if (result.ok) {
      return; // The session changes, and this page renders the redirect.
    }
    const { failure: reason } = result;
    if (reason.kind === "api" && reason.error.code === "VALIDATION_FAILED") {
      // The checks here match the backend's, except that its email check is stricter. Its
      // details name the fields it refused.
      const fields = reason.error.details.fields;
      const refused = typeof fields === "object" && fields !== null ? Object.keys(fields) : [];
      if (refused.includes("password") && !refused.includes("email")) {
        form.setError("password", { message: PASSWORD_TOO_LONG }, { shouldFocus: true });
      } else {
        form.setError("email", { message: EMAIL_MALFORMED }, { shouldFocus: true });
      }
      return;
    }
    setFailure(reason);
    if (reason.kind === "api" && reason.error.code === "INVALID_CREDENTIALS") {
      form.resetField("password");
      form.setFocus("password");
    }
  });

  const arrival = state.reason ? ARRIVAL[state.reason] : null;
  const problem = failure ? explain(failure) : null;

  return (
    <div className="flex min-h-dvh flex-col bg-ground text-ink">
      <title>{`Sign in - ${PRODUCT_NAME}`}</title>

      <main
        id="main"
        className="flex flex-1 items-start justify-center px-4 py-12 md:items-center"
      >
        <div className="w-full max-w-sm border border-rule bg-panel px-6 py-8">
          <p className="text-base font-semibold">{PRODUCT_NAME}</p>
          <h1 className="mt-6 text-xl font-semibold">Sign in</h1>
          <p className="mt-1 text-graphite">
            Use the email and password your administrator gave you.
          </p>

          {arrival && !problem ? (
            <Notice role="status" icon={<Info aria-hidden="true" className="size-4" />}>
              {arrival}
            </Notice>
          ) : null}

          {problem ? (
            <Notice role="alert" icon={<CircleAlert aria-hidden="true" className="size-4" />}>
              <span className="font-semibold">{problem.message}</span>
              {problem.next ? <span className="block">{problem.next}</span> : null}
            </Notice>
          ) : null}

          <form
            noValidate
            onSubmit={(event) => {
              if (isSubmitting) {
                event.preventDefault();
                return;
              }
              void onSubmit(event);
            }}
            className="mt-6 flex flex-col gap-5"
          >
            <Field id="email" label="Email" error={errors.email?.message}>
              {/* Signing in is the only thing to do on this page, so the cursor starts here. */}
              <input
                id="email"
                type="email"
                autoComplete="username"
                autoCapitalize="none"
                spellCheck={false}
                autoFocus
                aria-invalid={errors.email ? true : undefined}
                aria-describedby={errors.email ? "email-error" : undefined}
                className={inputClass(Boolean(errors.email))}
                {...form.register("email")}
              />
            </Field>

            <Field id="password" label="Password" error={errors.password?.message}>
              <div className="relative">
                <input
                  id="password"
                  type={showPassword ? "text" : "password"}
                  autoComplete="current-password"
                  aria-invalid={errors.password ? true : undefined}
                  aria-describedby={errors.password ? "password-error" : undefined}
                  className={cn(inputClass(Boolean(errors.password)), "pr-20")}
                  {...form.register("password")}
                />
                <button
                  type="button"
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  aria-controls="password"
                  aria-pressed={showPassword}
                  onClick={() => {
                    setShowPassword((shown) => !shown);
                  }}
                  className="absolute inset-y-0 right-0 inline-flex min-w-11 items-center justify-center gap-1 rounded-control px-3 text-sm"
                >
                  {showPassword ? (
                    <EyeOff aria-hidden="true" className="size-4" />
                  ) : (
                    <Eye aria-hidden="true" className="size-4" />
                  )}
                  {showPassword ? "Hide" : "Show"}
                </button>
              </div>
            </Field>

            <button
              type="submit"
              aria-disabled={isSubmitting}
              className="h-11 w-full rounded-control bg-ink px-4 text-base font-semibold text-panel aria-disabled:cursor-progress"
            >
              {isSubmitting ? "Signing in" : "Sign in"}
            </button>
          </form>

          <p className="mt-6 text-sm text-graphite">
            No account yet? Ask an administrator to create one.
          </p>
        </div>
      </main>

      <footer className="flex flex-wrap items-end justify-between gap-4 px-4 py-4">
        <p className="text-sm">
          <span className="text-graphite">Environment </span>
          <span className="font-semibold">Staging</span>
        </p>
        <ThemeSwitch />
      </footer>
    </div>
  );
}

function inputClass(invalid: boolean): string {
  return cn(
    "h-11 w-full rounded-control border bg-panel px-3 text-base text-ink",
    invalid ? "border-2 border-ink" : "border-graphite",
  );
}

/** A label above its control, and the error under it, tied to the control by id. */
function Field({
  id,
  label,
  error,
  children,
}: {
  id: string;
  label: string;
  error: string | undefined;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-sm font-semibold">
        {label}
      </label>
      {children}
      {error ? (
        <p id={`${id}-error`} className="flex items-start gap-1 text-sm">
          <CircleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
          {error}
        </p>
      ) : null}
    </div>
  );
}

/**
 * A message above the form. Ink, not red: DESIGN.md reserves the state colours for build states,
 * so the icon and the words carry it, as they do for every state.
 */
function Notice({
  role,
  icon,
  children,
}: {
  role: "status" | "alert";
  icon: ReactNode;
  children: ReactNode;
}) {
  return (
    <div role={role} className="mt-6 flex gap-2 border-l-4 border-ink bg-ground px-3 py-2 text-sm">
      <span className="mt-0.5 shrink-0">{icon}</span>
      <span>{children}</span>
    </div>
  );
}
