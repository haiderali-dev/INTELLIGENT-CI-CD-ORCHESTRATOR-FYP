import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { REFRESH_TOKEN_KEY, type Session } from "@/auth/session";
import {
  apiError,
  authBackend,
  DEVELOPER,
  makeSession,
  noAnswer,
  PASSWORD,
  signedInSession,
  type FakeBackend,
} from "@/test/backend";
import { currentPath, renderRoutes } from "@/test/renderRoutes";

const sessions: Session[] = [];

function track(session: Session): Session {
  sessions.push(session);
  return session;
}

afterEach(() => {
  for (const session of sessions.splice(0)) {
    session.dispose();
  }
});

function signInAt(path: string, backend: FakeBackend = authBackend()) {
  const session = track(makeSession(backend));
  return { backend, session, ...renderRoutes(path, session) };
}

const email = () => screen.getByLabelText("Email");
const password = () => screen.getByLabelText("Password");
const signInButton = () => screen.getByRole("button", { name: "Sign in" });

async function fillAndSubmit(user: ReturnType<typeof userEvent.setup>, address: string, secret: string) {
  if (address) {
    await user.type(email(), address);
  }
  if (secret) {
    await user.type(password(), secret);
  }
  await user.click(signInButton());
}

describe("sign in", () => {
  it("asks for the email and password in plain words, with the cursor in the email field", () => {
    signInAt("/sign-in");

    expect(screen.getByRole("heading", { level: 1, name: "Sign in" })).toBeInTheDocument();
    expect(email()).toHaveFocus();
    expect(email()).toHaveAttribute("autocomplete", "username");
    expect(password()).toHaveAttribute("autocomplete", "current-password");
    expect(screen.getByText("No account yet? Ask an administrator to create one.")).toBeInTheDocument();
    expect(screen.getByText("Staging")).toBeInTheDocument();
  });

  it("names each missing field, and sends nothing", async () => {
    const user = userEvent.setup();
    const { backend } = signInAt("/sign-in");

    await user.click(signInButton());

    expect(await screen.findByText("Enter your email address.")).toBeInTheDocument();
    expect(screen.getByText("Enter your password.")).toBeInTheDocument();
    expect(email()).toHaveAttribute("aria-invalid", "true");
    expect(email()).toHaveAccessibleDescription("Enter your email address.");
    expect(email()).toHaveFocus();
    expect(backend.requests).toHaveLength(0);
  });

  it("says what an email address should look like", async () => {
    const user = userEvent.setup();
    signInAt("/sign-in");

    await fillAndSubmit(user, "dev", PASSWORD);

    expect(
      await screen.findByText("Enter an email address in the form name@example.com."),
    ).toBeInTheDocument();
  });

  it("names a password longer than the backend accepts", async () => {
    const user = userEvent.setup();
    const { backend } = signInAt("/sign-in");
    await user.type(email(), DEVELOPER.email);
    await user.click(password());
    await user.paste("x".repeat(257));

    await user.click(signInButton());

    expect(
      await screen.findByText("Enter a password of 256 characters or fewer."),
    ).toBeInTheDocument();
    expect(backend.requests).toHaveLength(0);
  });

  it("points at the email field when the backend refuses its format", async () => {
    const user = userEvent.setup();
    signInAt(
      "/sign-in",
      authBackend().on("POST /api/auth/login", () =>
        apiError(422, "VALIDATION_FAILED", "Some fields need attention.", {
          fields: { email: "value is not a valid email address" },
        }),
      ),
    );

    await fillAndSubmit(user, "dev@example.test", PASSWORD);

    expect(
      await screen.findByText("Enter an email address in the form name@example.com."),
    ).toBeInTheDocument();
    expect(email()).toHaveFocus();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("says the email or password is wrong, keeps the email and clears the password", async () => {
    const user = userEvent.setup();
    signInAt(
      "/sign-in",
      authBackend().on("POST /api/auth/login", () =>
        apiError(401, "INVALID_CREDENTIALS", "That email or password is not correct."),
      ),
    );

    await fillAndSubmit(user, DEVELOPER.email, "not the password");

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("That email or password is not correct.");
    expect(alert).toHaveTextContent(
      "Check both and try again. Forgotten your password? Ask an administrator.",
    );
    expect(email()).toHaveValue(DEVELOPER.email);
    expect(password()).toHaveValue("");
    expect(password()).toHaveFocus();
  });

  it("says when the account is disabled, and who can fix it", async () => {
    const user = userEvent.setup();
    signInAt(
      "/sign-in",
      authBackend().on("POST /api/auth/login", () =>
        apiError(
          401,
          "ACCOUNT_DISABLED",
          "This account is disabled. Ask an administrator to re-enable it.",
        ),
      ),
    );

    await fillAndSubmit(user, DEVELOPER.email, PASSWORD);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This account is disabled. Ask an administrator to re-enable it.",
    );
  });

  it("says how long to wait after too many attempts", async () => {
    const user = userEvent.setup();
    signInAt(
      "/sign-in",
      authBackend().on("POST /api/auth/login", () =>
        apiError(429, "RATE_LIMITED", "Too many requests.", {
          retry_after_seconds: 42,
          limit: "login",
        }),
      ),
    );

    await fillAndSubmit(user, DEVELOPER.email, PASSWORD);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Too many sign-in attempts from this computer.");
    expect(alert).toHaveTextContent("Wait 42 seconds, then try again.");
  });

  it("says when the server did not answer, and what to check", async () => {
    const user = userEvent.setup();
    signInAt("/sign-in", authBackend().on("POST /api/auth/login", noAnswer));

    await fillAndSubmit(user, DEVELOPER.email, PASSWORD);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The server did not answer. Check that the backend is running, then try again.",
    );
    expect(email()).toHaveValue(DEVELOPER.email);
    expect(password()).toHaveValue(PASSWORD);
  });

  it("shows and hides the password on request", async () => {
    const user = userEvent.setup();
    signInAt("/sign-in");
    await user.type(password(), PASSWORD);

    await user.click(screen.getByRole("button", { name: "Show password" }));

    expect(password()).toHaveAttribute("type", "text");
    expect(screen.getByRole("button", { name: "Hide password" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    await user.click(screen.getByRole("button", { name: "Hide password" }));
    expect(password()).toHaveAttribute("type", "password");
  });
});

describe("arriving at and leaving sign in", () => {
  it("sends a visitor with no session to sign in, then on to the page they asked for", async () => {
    const user = userEvent.setup();
    const { router } = signInAt("/queue?view=all");

    expect(currentPath(router)).toBe("/sign-in?next=%2Fqueue%3Fview%3Dall");

    await fillAndSubmit(user, DEVELOPER.email, PASSWORD);

    expect(await screen.findByRole("heading", { level: 1, name: "Queue" })).toBeInTheDocument();
    expect(currentPath(router)).toBe("/queue?view=all");
  });

  it("never follows a next address off this site", async () => {
    const user = userEvent.setup();
    const { router } = signInAt("/sign-in?next=%2F%2Felsewhere.example%2Fqueue");

    await fillAndSubmit(user, DEVELOPER.email, PASSWORD);

    expect(await screen.findByRole("heading", { level: 1, name: "Overview" })).toBeInTheDocument();
    expect(currentPath(router)).toBe("/");
  });

  it("skips the form for someone already signed in", async () => {
    const { session } = await signedInSession();
    track(session);

    const { router } = renderRoutes("/sign-in?next=%2Fanalytics", session);

    expect(await screen.findByRole("heading", { level: 1, name: "Analytics" })).toBeInTheDocument();
    expect(currentPath(router)).toBe("/analytics");
  });

  it("restores the session after a reload without showing the form", async () => {
    window.sessionStorage.setItem(REFRESH_TOKEN_KEY, "refresh-from-before");
    const { router } = signInAt("/runs");

    expect(screen.getByRole("status")).toHaveTextContent("Restoring your session");
    expect(
      await screen.findByRole("heading", { level: 1, name: "Jobs and runs" }),
    ).toBeInTheDocument();
    expect(currentPath(router)).toBe("/runs");
  });

  it("says the session ended when a stored one is refused, and returns there afterwards", async () => {
    const user = userEvent.setup();
    window.sessionStorage.setItem(REFRESH_TOKEN_KEY, "revoked");
    const backend = authBackend().on("POST /api/auth/refresh", () =>
      apiError(401, "TOKEN_INVALID", "This session has been signed out. Please sign in again."),
    );
    const { router } = signInAt("/catalog", backend);

    const notice = await screen.findByText(
      "Your session ended. Sign in again to carry on where you were.",
    );
    expect(notice.closest("[role=status]")).not.toBeNull();
    expect(currentPath(router)).toBe("/sign-in?next=%2Fcatalog");

    await fillAndSubmit(user, DEVELOPER.email, PASSWORD);
    expect(
      await screen.findByRole("heading", { level: 1, name: "Service catalog" }),
    ).toBeInTheDocument();
  });

  it("says when the server could not be reached to restore the session", async () => {
    window.sessionStorage.setItem(REFRESH_TOKEN_KEY, "still-good");
    signInAt("/", authBackend().on("POST /api/auth/refresh", noAnswer));

    expect(
      await screen.findByText(/The server did not answer, so your session could not be restored/),
    ).toBeInTheDocument();
  });
});
