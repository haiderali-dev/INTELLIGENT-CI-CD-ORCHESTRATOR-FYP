import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { ADMIN, json, noAnswer, type FakeBackend } from "@/test/backend";
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
