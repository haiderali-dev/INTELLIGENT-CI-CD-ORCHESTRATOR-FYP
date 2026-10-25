import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { ADMIN, apiError, json, noAnswer, type FakeBackend } from "@/test/backend";
import * as captured from "@/test/fixtures/pages";
import { renderRoutes } from "@/test/renderRoutes";
import { disposeSessions, neverAnswers, signedIn } from "@/test/signedIn";

afterEach(disposeSessions);

/** The catalog as the real backend answered it: payment-service reachable, auth-service not. */
function catalog(backend: FakeBackend): FakeBackend {
  return backend
    .on("GET /api/services", () => json(200, captured.services))
    .on("GET /api/services/:name/branches", (request) =>
      new URL(request.url).pathname.includes("auth-service")
        ? json(200, captured.branchesAuthUnreachable)
        : json(200, captured.branchesPayment),
    );
}

const service = (name: string) => screen.getByRole("region", { name });
const fact = (region: HTMLElement, term: string) =>
  within(region).getByText(term, { selector: "dt" }).nextElementSibling;

describe("the service catalog", () => {
  it("shows each service's repository, branches, suites, environments and reachability", async () => {
    const { backend, session } = await signedIn();
    renderRoutes("/catalog", session, catalog(backend));

    expect(await screen.findByRole("heading", { level: 2, name: "payment-service" })).toBeInTheDocument();
    const payment = service("payment-service");
    expect(within(payment).getByRole("link", { name: /payment-service\.git, opens in a new tab$/ })).toHaveAttribute(
      "href",
      "https://github.com/haiderali-dev/payment-service.git",
    );
    expect(fact(payment, "Default branch")).toHaveTextContent("main");
    expect(fact(payment, "Agent label")).toHaveTextContent("linux");
    expect(fact(payment, "Test suites")).toHaveTextContent("unit, about 8s; integration, about 20s");
    expect(fact(payment, "Environments")).toHaveTextContent("Staging");
    expect(fact(payment, "Extra stages")).toHaveTextContent("Lint, Security scan");
    expect(await within(payment).findByText("Reachable")).toBeInTheDocument();
    expect(fact(payment, "Reachability")).toHaveTextContent("2 branches: demo/failing-tests, main (default)");

    const auth = service("auth-service");
    expect(await within(auth).findByText("Not reachable")).toBeInTheDocument();
    expect(fact(auth, "Reachability")).toHaveTextContent(
      "The repository could not be reached. The assistants offer only the default branch, main, until it answers.",
    );
  });

  it("says so while it loads, and when the catalog is empty", async () => {
    const { backend, session } = await signedIn();
    backend.on("GET /api/services", neverAnswers);
    renderRoutes("/catalog", session, backend);

    expect(await screen.findByText("Loading the service catalog")).toBeInTheDocument();

    const empty = await signedIn();
    empty.backend.on("GET /api/services", () => json(200, { ...captured.services, items: [] }));
    renderRoutes("/catalog", empty.session, empty.backend);

    expect(await screen.findByText(/The catalog has no services\./)).toBeInTheDocument();
  });

  it("says what failed, and loads again on request", async () => {
    const user = userEvent.setup();
    const { backend, session } = await signedIn();
    backend.on("GET /api/services", noAnswer);
    renderRoutes("/catalog", session, backend);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(
      "The service catalog could not be loaded. The server did not answer. Check that the backend is running, then try again.",
    );

    catalog(backend);
    await user.click(within(alert).getByRole("button", { name: "Try again" }));

    expect(await screen.findByRole("heading", { level: 2, name: "auth-service" })).toBeInTheDocument();
  });

  it("says why a repository was not checked when the request itself failed", async () => {
    const { backend, session } = await signedIn();
    catalog(backend).on("GET /api/services/:name/branches", noAnswer);
    renderRoutes("/catalog", session, backend);

    await screen.findByRole("heading", { level: 2, name: "payment-service" });
    expect(await within(service("payment-service")).findByText("Not checked.")).toBeInTheDocument();
  });

  it("offers the resync to an Admin only", async () => {
    const developer = await signedIn();
    const { unmount } = renderRoutes("/catalog", developer.session, catalog(developer.backend));
    await screen.findByRole("heading", { level: 2, name: "payment-service" });

    expect(screen.queryByRole("button", { name: "Resync the catalog" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Add Service" })).toBeNull();
    unmount();

    const user = userEvent.setup();
    const admin = await signedIn(ADMIN);
    catalog(admin.backend).on("POST /api/services/resync", () => json(200, captured.resync.body));
    renderRoutes("/catalog", admin.session, admin.backend);

    await user.click(await screen.findByRole("button", { name: "Resync the catalog" }));

    expect(await screen.findByText("Catalog resynced: 2 added, 0 updated")).toBeInTheDocument();
    expect(admin.backend.calls("POST /api/services/resync")).toHaveLength(1);
    // The catalog is read again after the resync.
    expect(admin.backend.calls("GET /api/services").length).toBeGreaterThanOrEqual(2);
  });

  it("says why a resync was refused", async () => {
    const user = userEvent.setup();
    const { backend, session } = await signedIn(ADMIN);
    catalog(backend).on("POST /api/services/resync", () =>
      json(captured.resyncForbidden.status, captured.resyncForbidden.body),
    );
    renderRoutes("/catalog", session, backend);

    await user.click(await screen.findByRole("button", { name: "Resync the catalog" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The resync did not finish. This action needs the ADMIN role. Yours is DEVELOPER.",
    );
  });
});

async function openAddService() {
  const user = userEvent.setup({ delay: null });
  const { backend, session } = await signedIn(ADMIN);
  renderRoutes("/catalog", session, catalog(backend));
  await screen.findByRole("heading", { name: "payment-service" });
  const trigger = screen.getByRole("button", { name: "Add Service" });
  await user.click(trigger);
  const dialog = screen.getByRole("dialog", { name: "Add Service" });
  return { user, backend, dialog, trigger };
}

async function fillService(user: ReturnType<typeof userEvent.setup>, name = "orders-service") {
  for (const [label, value] of [
    ["Service name", name],
    ["Repository URL", "https://github.com/team/orders-service.git"],
    ["Build command", "./scripts/build.sh"],
    ["Suite 1 command", "./scripts/test.sh unit"],
    ["Deploy command", "./deploy.sh staging"],
    ["Staging URL", "http://localhost:9003"],
  ] as const) {
    await user.type(screen.getByLabelText(label), value);
  }
}

describe("adding a service", () => {
  it("opens an accessible form and returns focus when cancelled without saving", async () => {
    const { user, backend, dialog, trigger } = await openAddService();
    expect(within(dialog).getByText(/Deployments are limited to staging/)).toBeInTheDocument();
    expect(within(dialog).getByLabelText("Service name")).toHaveFocus();
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(trigger).toHaveFocus();
    expect(backend.calls("POST /api/services")).toHaveLength(0);
  });

  it("validates required fields and command safety before sending anything", async () => {
    const { user, backend, dialog } = await openAddService();
    await user.click(within(dialog).getByRole("button", { name: "Add service" }));
    expect(await within(dialog).findByText("Enter an HTTPS or SSH clone URL ending in .git.")).toBeInTheDocument();
    expect(screen.getByLabelText("Service name")).toHaveAttribute("aria-invalid", "true");
    await fillService(user);
    await user.type(screen.getByLabelText("Build command"), "; injected");
    await user.click(within(dialog).getByRole("button", { name: "Add service" }));
    expect(await within(dialog).findByText(/Use a single command without shell operators/)).toBeInTheDocument();
    expect(backend.calls("POST /api/services")).toHaveLength(0);
  });

  it("adds multiple suites, saves the complete service and refreshes the catalog", async () => {
    const { user, backend, dialog } = await openAddService();
    const created = { ...captured.services.items[0], name: "orders-service", repo: "https://github.com/team/orders-service.git" };
    backend.on("POST /api/services", () => {
      backend.on("GET /api/services", () => json(200, { ...captured.services, items: [...captured.services.items, created] }));
      return json(201, created);
    });
    await fillService(user);
    await user.click(within(dialog).getByRole("button", { name: "Add test suite" }));
    await user.type(screen.getByLabelText("Suite 2 name"), "integration");
    await user.type(screen.getByLabelText("Suite 2 command"), "./scripts/test.sh integration");
    await user.type(screen.getByLabelText("Lint command"), "./scripts/lint.sh");
    await user.click(within(dialog).getByRole("button", { name: "Add service" }));
    expect(await screen.findByRole("heading", { name: "orders-service" })).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByText("orders-service was added to the catalog")).toBeInTheDocument();
    const requests = backend.calls("POST /api/services");
    expect(requests).toHaveLength(1);
    expect(await requests[0]?.json()).toEqual({
      name: "orders-service", repo: "https://github.com/team/orders-service.git", default_branch: "main",
      agent_label: "linux", build_command: "./scripts/build.sh",
      test_suites: [
        { name: "unit", command: "./scripts/test.sh unit", approx_seconds: 10 },
        { name: "integration", command: "./scripts/test.sh integration", approx_seconds: 10 },
      ],
      deploy: { staging: { command: "./deploy.sh staging", url: "http://localhost:9003" } },
      allowed_environments: ["staging"], extra_stages: { lint: "./scripts/lint.sh" },
    });
    expect(backend.calls("GET /api/services").length).toBeGreaterThanOrEqual(2);
  });

  it("retains the form and points to the field rejected by the server", async () => {
    const { user, backend, dialog } = await openAddService();
    backend.on("POST /api/services", () => apiError(409, "VALIDATION_FAILED", "That service already exists.", { fields: { name: "Choose a different service name." } }));
    await fillService(user);
    await user.click(within(dialog).getByRole("button", { name: "Add service" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("The service was not added. That service already exists.");
    expect(await within(dialog).findByText("Choose a different service name.")).toBeInTheDocument();
    expect(screen.getByLabelText("Service name")).toHaveValue("orders-service");
    expect(screen.getByLabelText("Repository URL")).toHaveValue("https://github.com/team/orders-service.git");
  });

  it("catches an existing name locally and allows removing extra suites", async () => {
    const { user, backend, dialog } = await openAddService();
    await fillService(user, "payment-service");
    await user.click(within(dialog).getByRole("button", { name: "Add test suite" }));
    await user.click(within(dialog).getByRole("button", { name: "Remove suite 2" }));
    expect(screen.queryByLabelText("Suite 2 name")).toBeNull();
    await user.click(within(dialog).getByRole("button", { name: "Add service" }));
    expect(await within(dialog).findByText("A service with this name already exists.")).toBeInTheDocument();
    expect(backend.calls("POST /api/services")).toHaveLength(0);
  });

  it("sends only once while saving and keeps the dialog open until it finishes", async () => {
    const { user, backend, dialog } = await openAddService();
    let finish: (response: Response) => void = () => undefined;
    backend.on("POST /api/services", () => new Promise<Response>((resolve) => { finish = resolve; }));
    await fillService(user);
    await user.click(within(dialog).getByRole("button", { name: "Add service" }));
    const saving = await within(dialog).findByRole("button", { name: "Adding service…" });
    expect(saving).toHaveAttribute("aria-disabled", "true");
    await user.click(saving);
    await user.keyboard("{Escape}");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(backend.calls("POST /api/services")).toHaveLength(1);
    finish(apiError(503, "VALIDATION_FAILED", "The catalog directory is not writable."));
    await waitFor(() => { expect(saving).toHaveTextContent("Add service"); });
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("not writable");
  });
});
