import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { bodyOf, DEVELOPER, json, noAnswer, type FakeBackend } from "@/test/backend";
import * as captured from "@/test/fixtures/pages";
import { renderRoutes } from "@/test/renderRoutes";
import { disposeSessions, signedIn } from "@/test/signedIn";

afterEach(disposeSessions);

/** The Admin endpoints as the real backend answered them, for the Admin who made the capture. */
function admin(backend: FakeBackend): FakeBackend {
  return backend
    .on("GET /api/admin/users", () => json(200, captured.users))
    .on("GET /api/admin/roles", () => json(200, captured.roles))
    .on("GET /api/admin/policy", () => json(200, captured.policy))
    .on("GET /api/admin/limits", () => json(200, captured.limits))
    .on("GET /api/admin/audit", () => json(200, captured.audit));
}

async function asAdmin() {
  const signed = await signedIn(captured.me);
  admin(signed.backend);
  const view = renderRoutes("/admin", signed.session, signed.backend);
  await screen.findByRole("table", { name: "Users" });
  return { ...signed, ...view };
}

const usersTable = () => screen.getByRole("table", { name: "Users" });
const userRow = (email: string) => {
  const row = within(usersTable())
    .getAllByRole("row")
    .find((each) => within(each).queryByRole("rowheader")?.textContent.startsWith(email));
  if (!row) {
    throw new Error(`no row for ${email}`);
  }
  return row;
};

describe("the admin page", () => {
  it("is closed to anyone but an Admin, and asks the backend for nothing", async () => {
    const { backend, session } = await signedIn(DEVELOPER);
    admin(backend);
    renderRoutes("/admin", session, backend);

    expect(await screen.findByText("Only Admins can use this page.")).toBeInTheDocument();
    expect(screen.getByText(/^Your role is Developer\. /)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Go to the Overview" })).toHaveAttribute("href", "/");
    expect(backend.requests.filter(({ url }) => url.includes("/api/admin/"))).toEqual([]);
  });

  it("lists the users, and offers no control over your own access", async () => {
    await asAdmin();

    expect(userRow("admin@example.com")).toHaveTextContent("admin@example.comyouAdminActive");
    expect(within(userRow("admin@example.com")).queryByRole("combobox")).toBeNull();
    expect(within(userRow("admin@example.com")).queryByRole("button")).toBeNull();

    expect(within(userRow("ops@example.com")).getByRole("combobox", { name: "Role of ops@example.com" })).toHaveValue(
      "DEVOPS",
    );
    expect(within(userRow("ops@example.com")).getByRole("button", { name: "Deactivate" })).toBeInTheDocument();
    expect(userRow("dev2@example.com")).toHaveTextContent("Deactivated");
    expect(within(userRow("dev2@example.com")).getByRole("button", { name: "Reactivate" })).toBeInTheDocument();
    expect(screen.getByText("You cannot change your own role or deactivate yourself. Another Admin can.")).toBeInTheDocument();
  });

  it("changes a role", async () => {
    const user = userEvent.setup();
    const { backend } = await asAdmin();
    const ops = captured.users.items.find(({ email }) => email === "ops@example.com");
    backend.on("PATCH /api/admin/users/:id", () => json(200, { ...ops, role: "DEVELOPER" }));

    await user.selectOptions(screen.getByRole("combobox", { name: "Role of ops@example.com" }), "DEVELOPER");

    expect(await screen.findByText("ops@example.com is now Developer")).toBeInTheDocument();
    const [request] = backend.calls("PATCH /api/admin/users/:id");
    expect(request?.url).toMatch(new RegExp(`/api/admin/users/${ops?.id ?? "missing"}$`));
    expect(await bodyOf(request)).toEqual({ role: "DEVELOPER" });
  });

  it("asks before deactivating someone, and says exactly what it does", async () => {
    const user = userEvent.setup();
    const { backend } = await asAdmin();
    backend.on("PATCH /api/admin/users/:id", () => json(200, captured.userUpdated.body));

    await user.click(within(userRow("ops@example.com")).getByRole("button", { name: "Deactivate" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Deactivate ops@example.com?" });
    expect(dialog).toHaveTextContent(
      "Their next request is refused, and they cannot sign in until an Admin reactivates them.",
    );
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(backend.calls("PATCH /api/admin/users/:id")).toHaveLength(0);

    await user.click(within(userRow("ops@example.com")).getByRole("button", { name: "Deactivate" }));
    await user.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Deactivate" }),
    );

    await waitFor(() => {
      expect(backend.calls("PATCH /api/admin/users/:id")).toHaveLength(1);
    });
    expect(await bodyOf(backend.calls("PATCH /api/admin/users/:id")[0])).toEqual({ active: false });
    // The answer is the user the backend changed: dev2, deactivated in the capture.
    expect(await screen.findByText("dev2@example.com was deactivated")).toBeInTheDocument();
  });

  it("says why a change was refused", async () => {
    const user = userEvent.setup();
    const { backend } = await asAdmin();
    backend.on("PATCH /api/admin/users/:id", () =>
      json(captured.userSelfDemote.status, captured.userSelfDemote.body),
    );

    await user.click(within(userRow("dev2@example.com")).getByRole("button", { name: "Reactivate" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The change was not made. You cannot remove your own administrator access. Ask another admin to do it.",
    );
  });

  it("adds a user, checking the password before asking", async () => {
    const user = userEvent.setup();
    const { backend } = await asAdmin();
    backend.on("POST /api/admin/users", () => json(201, { ...captured.userCreated.body, email: "new@example.com", role: "DEVOPS" }));
    const form = screen.getByRole("form", { name: "Add a user" });

    await user.type(within(form).getByLabelText("Email"), "new@example.com");
    await user.type(within(form).getByLabelText("First password"), "short");
    await user.click(within(form).getByRole("button", { name: "Add user" }));

    expect(await within(form).findByText("Choose a password of at least 12 characters.")).toBeInTheDocument();
    expect(backend.calls("POST /api/admin/users")).toHaveLength(0);

    await user.clear(within(form).getByLabelText("First password"));
    await user.type(within(form).getByLabelText("First password"), "a long enough password");
    await user.selectOptions(within(form).getByLabelText("Role"), "DEVOPS");
    await user.click(within(form).getByRole("button", { name: "Add user" }));

    expect(await screen.findByText("new@example.com was added as DevOps")).toBeInTheDocument();
    expect(await bodyOf(backend.calls("POST /api/admin/users")[0])).toEqual({
      email: "new@example.com",
      password: "a long enough password",
      role: "DEVOPS",
    });
    expect(within(form).getByLabelText("Email")).toHaveValue("");
  });

  it("puts the backend's refusal under the field it names", async () => {
    const user = userEvent.setup();
    const { backend } = await asAdmin();
    backend.on("POST /api/admin/users", () => json(captured.userDuplicate.status, captured.userDuplicate.body));
    const form = screen.getByRole("form", { name: "Add a user" });

    await user.type(within(form).getByLabelText("Email"), "dev2@example.com");
    await user.type(within(form).getByLabelText("First password"), "a long enough password");
    await user.click(within(form).getByRole("button", { name: "Add user" }));

    const email = within(form).getByLabelText("Email");
    expect(await within(form).findByText("A user with that email already exists.")).toBeInTheDocument();
    expect(email).toHaveAttribute("aria-invalid", "true");
  });

  it("shows the HIGH quota and the rules in force, and says they cannot be changed here", async () => {
    await asAdmin();

    const policy = await screen.findByRole("region", { name: "Policy" });
    const quota = await within(policy).findByText("HIGH urgency", { selector: "dt" });
    expect(quota.nextElementSibling).toHaveTextContent(
      "3 a day for each Developer, then MEDIUM",
    );
    expect(within(policy).getByText("Production deploys").nextElementSibling).toHaveTextContent("Refused");
    const rules = within(policy).getByRole("table", { name: "Rules in force, by role" });
    expect(within(rules).getAllByRole("rowheader").map((cell) => cell.textContent)).toEqual(
      captured.policy.rules.map(({ rule }) => rule),
    );
    expect(policy).toHaveTextContent("this page shows them and cannot change them.");
  });

  it("shows the rate limits the backend enforces", async () => {
    await asAdmin();

    const policy = await screen.findByRole("region", { name: "Policy" });
    const limits = await within(policy).findByRole("table", { name: "Rate limits" });
    const rows = within(limits).getAllByRole("row").slice(1).map((row) => row.textContent);
    expect(rows).toEqual([
      "sign-in, per address and account5 a minute",
      "sign-in, per address across accounts30 a minute",
      "session renewal, per address30 a minute",
      "every signed-in request, per user300 a minute",
      "assistant messages, generation and explanations, per user20 a minute",
    ]);
  });

  it("resets someone's password, checking it before asking, but never yours", async () => {
    const user = userEvent.setup();
    const { backend } = await asAdmin();
    backend.on("POST /api/admin/users/:id/password", () =>
      json(captured.passwordReset.status, captured.passwordReset.body),
    );
    expect(within(userRow("admin@example.com")).queryByRole("button", { name: "Reset password" })).toBeNull();

    await user.click(within(userRow("ops@example.com")).getByRole("button", { name: "Reset password" }));
    const dialog = await screen.findByRole("dialog", { name: "Reset the password of ops@example.com" });
    expect(dialog).toHaveTextContent("They are signed out everywhere at once");
    await user.type(within(dialog).getByLabelText("New password"), "short");
    await user.click(within(dialog).getByRole("button", { name: "Reset password" }));
    expect(await within(dialog).findByText("Choose a password of 12 to 256 characters.")).toBeInTheDocument();
    expect(backend.calls("POST /api/admin/users/:id/password")).toHaveLength(0);

    await user.clear(within(dialog).getByLabelText("New password"));
    await user.type(within(dialog).getByLabelText("New password"), "a long enough password");
    await user.click(within(dialog).getByRole("button", { name: "Reset password" }));

    expect(
      await screen.findByText("ops@example.com has a new password and was signed out everywhere"),
    ).toBeInTheDocument();
    expect(await bodyOf(backend.calls("POST /api/admin/users/:id/password")[0])).toEqual({
      password: "a long enough password",
    });
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull();
    });
  });

  it("says why a password was not reset", async () => {
    const user = userEvent.setup();
    const { backend } = await asAdmin();
    backend.on("POST /api/admin/users/:id/password", () =>
      json(captured.passwordTooShort.status, captured.passwordTooShort.body),
    );

    await user.click(within(userRow("ops@example.com")).getByRole("button", { name: "Reset password" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("New password"), "a long enough password");
    await user.click(within(dialog).getByRole("button", { name: "Reset password" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent("The password was not changed.");
  });

  it("shows the audit log a page at a time, newest first", async () => {
    await asAdmin();

    const log = await screen.findByRole("table", { name: "Audit log, newest first" });
    const rows = within(log).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(captured.audit.items.length);
    expect(rows[0]).toHaveTextContent("admin@example.comadmin.user.updateddev2@example.comactive: true to false");
    expect(screen.getByText("Entries 1 to 13 of 13")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Older" })).toHaveAttribute("aria-disabled", "true");
    expect(screen.getByRole("button", { name: "Newer" })).toHaveAttribute("aria-disabled", "true");
  });

  it("pages through a longer audit log", async () => {
    const user = userEvent.setup();
    const { backend, session } = await signedIn(captured.me);
    // Sixty entries, made from the captured thirteen, paged as the API pages them.
    const entries = Array.from({ length: 60 }, (_, index) => ({
      ...captured.audit.items[index % captured.audit.items.length],
      id: `entry-${String(index)}`,
    }));
    admin(backend).on("GET /api/admin/audit", (request) => {
      const params = new URL(request.url).searchParams;
      const offset = Number(params.get("offset") ?? "0");
      const limit = Number(params.get("limit") ?? "50");
      return json(200, { items: entries.slice(offset, offset + limit), total: 60, limit, offset });
    });
    renderRoutes("/admin", session, backend);

    expect(await screen.findByText("Entries 1 to 50 of 60")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Older" }));

    expect(await screen.findByText("Entries 51 to 60 of 60")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Older" })).toHaveAttribute("aria-disabled", "true");
    await user.click(screen.getByRole("button", { name: "Newer" }));
    expect(await screen.findByText("Entries 1 to 50 of 60")).toBeInTheDocument();
  });

  it("says what failed when the users cannot be loaded", async () => {
    const { backend, session } = await signedIn(captured.me);
    admin(backend).on("GET /api/admin/users", noAnswer);
    renderRoutes("/admin", session, backend);

    expect(await screen.findByText(/The users could not be loaded\./)).toBeInTheDocument();
  });
});
