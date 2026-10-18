import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { apiError, json, noAnswer, type FakeBackend } from "@/test/backend";
import { FakeSocket } from "@/test/fakeSocket";
import * as captured from "@/test/fixtures/pages";
import { currentPath, renderRoutes } from "@/test/renderRoutes";
import { disposeSessions, narrowScreen, signedIn } from "@/test/signedIn";

beforeEach(() => {
  FakeSocket.opened = [];
});
afterEach(disposeSessions);

const CARDS = [captured.chainFailed, captured.chainQueued, captured.chainPipelineRunning];
const FAILED_RUN = captured.runFailed.id;

/** Runs as the real backend answered them: three chains, their cards, two logs, one explanation. */
function runs(backend: FakeBackend): FakeBackend {
  return backend
    .on("GET /api/services", () => json(200, captured.services))
    .on("GET /api/chains", (request) => {
      // The backend's own filters (tests/test_api_gaps.py), applied to the captured chains.
      const query = new URL(request.url).searchParams;
      const service = query.get("service");
      const jobType = query.get("job_type");
      const status = query.get("status");
      const items = captured.chains.items.filter(
        (chain) =>
          (!service || chain.service === service) &&
          (!jobType || chain.job_type === jobType) &&
          (!status || chain.status === status),
      );
      return json(200, { ...captured.chains, items, total: items.length });
    })
    .on("GET /api/chains/:id", (request) => {
      const id = new URL(request.url).pathname.split("/")[3];
      const card = CARDS.find((each) => each.id === id);
      return card ? json(200, card) : apiError(404, "BAD_REQUEST", "No such chain.");
    })
    .on("GET /api/runs/:id/log", (request) => {
      const id = new URL(request.url).pathname.split("/")[3];
      if (id === FAILED_RUN) {
        return json(200, captured.logFailed);
      }
      const start = Number(new URL(request.url).searchParams.get("start") ?? "0");
      return json(200, start > 0 ? { ...captured.logRunning, text: "", next_offset: start } : captured.logRunning);
    })
    .on("POST /api/runs/:id/explain", () => json(200, captured.explainFailed.body));
}

const table = () => screen.getByRole("table", { name: "Runs, newest first" });
const rowNames = () =>
  within(table())
    .getAllByRole("rowheader")
    .map((cell) => cell.textContent);

describe("jobs and runs", () => {
  it("lists every run newest first, with its service, assistant, jobs, result and time", async () => {
    const { backend, session } = await signedIn();
    renderRoutes("/runs", session, runs(backend));

    await screen.findByRole("table", { name: "Runs, newest first" });
    expect(rowNames()).toEqual([
      "pl-payment-service-build-test-deploy-staging",
      "fs-auth-service-build",
      "fs-payment-service-build",
    ]);
    const cells = within(table())
      .getAllByRole("row")
      .slice(1)
      .map((row) => within(row).getAllByRole("cell").slice(1).map((cell) => cell.textContent));
    expect(cells).toEqual([
      ["payment-service", "Pipeline", "1 job", "Running", "Not finished"],
      ["auth-service", "Freestyle", "1 job", "Running", "Not finished"],
      ["payment-service", "Freestyle", "4 jobs", "Failed", "0s"],
    ]);
    expect(screen.getByText("3 runs, newest first.")).toBeInTheDocument();
  });

  it("filters by service, assistant and result in the API, and keeps them in the address", async () => {
    const user = userEvent.setup();
    const { backend, session } = await signedIn();
    const { router } = renderRoutes("/runs", session, runs(backend));
    await screen.findByRole("table", { name: "Runs, newest first" });

    await user.selectOptions(screen.getByLabelText("Assistant"), "freestyle");
    await waitFor(() => {
      expect(rowNames()).toEqual(["fs-auth-service-build", "fs-payment-service-build"]);
    });

    await user.selectOptions(screen.getByLabelText("Result"), "failed");
    await waitFor(() => {
      expect(rowNames()).toEqual(["fs-payment-service-build"]);
    });

    await user.selectOptions(await screen.findByLabelText("Service"), "auth-service");
    expect(await screen.findByText("No runs match these filters.")).toBeInTheDocument();
    expect(currentPath(router)).toBe("/runs?assistant=freestyle&result=failed&service=auth-service");
    expect(backend.calls("GET /api/chains").map((request) => new URL(request.url).search)).toContain(
      "?service=auth-service&job_type=FREESTYLE&status=FAILURE&limit=200",
    );

    await user.click(screen.getByRole("link", { name: "Clear the filters" }));
    expect(currentPath(router)).toBe("/runs");
    expect(await screen.findAllByRole("rowheader")).toHaveLength(3);
  });

  it("says when only the newest runs are shown", async () => {
    const { backend, session } = await signedIn();
    runs(backend).on("GET /api/chains", () => json(200, { ...captured.chains, total: 250 }));
    renderRoutes("/runs", session, backend);

    expect(await screen.findByText("The newest 3 of 250 runs.")).toBeInTheDocument();
  });

  it("invites a first run when there are none", async () => {
    const { backend, session } = await signedIn();
    runs(backend).on("GET /api/chains", () => json(200, captured.chainsEmpty));
    renderRoutes("/runs", session, backend);

    expect(await screen.findByText(/^No runs yet\./)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open the Pipeline Assistant" })).toHaveAttribute(
      "href",
      "/assistants/pipeline",
    );
  });

  it("says what failed, and loads again on request", async () => {
    const user = userEvent.setup();
    const { backend, session } = await signedIn();
    runs(backend).on("GET /api/chains", noAnswer);
    renderRoutes("/runs", session, backend);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The runs could not be loaded. The server did not answer.");
    runs(backend);
    await user.click(within(alert).getByRole("button", { name: "Try again" }));

    expect(await screen.findByRole("table", { name: "Runs, newest first" })).toBeInTheDocument();
  });

  it("opens a failed run: its stages, its jobs, the end of its log, and why it failed", async () => {
    const user = userEvent.setup();
    const { backend, session } = await signedIn();
    const { router } = renderRoutes("/runs", session, runs(backend));
    await screen.findByRole("table", { name: "Runs, newest first" });

    await user.click(screen.getByRole("link", { name: "fs-payment-service-build" }));

    expect(currentPath(router)).toBe(`/runs?chain=${captured.chainFailed.id}`);
    const heading = await screen.findByRole("heading", { level: 2, name: /^payment-service, started / });
    await waitFor(() => {
      expect(heading).toHaveFocus();
    });
    const card = screen.getByRole("region", { name: "Run of fs-payment-service-build" });
    expect(within(card).getByRole("list", { name: "Stages" })).toHaveTextContent(
      "fs-payment-service-build succeededfs-payment-service-test-unit failed",
    );
    const jobs = screen.getByRole("list", { name: "Jobs in this run" });
    expect(within(jobs).getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      "fs-payment-service-buildSucceeded#11sShow the log of fs-payment-service-build",
      "fs-payment-service-test-unitFailed#14sLog shown below",
      "fs-payment-service-test-integrationNot started",
      "fs-payment-service-deploy-stagingNot started",
    ]);

    // The failed run's log, read to its end: the last lines are how Jenkins ended it.
    const log = await screen.findByRole("region", { name: "Log of fs-payment-service-test-unit #1" });
    expect(await within(log).findByText(/Finished: FAILURE$/)).toBeInTheDocument();
    expect(within(log).getByText("57 lines.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Explain why fs-payment-service-test-unit failed" }));
    const why = await screen.findByRole("region", { name: "Why fs-payment-service-test-unit failed" });
    expect(why).toHaveTextContent(
      "1 of 8 tests failed: tests/test_unit.py::test_demo_failing_tests_fails_on_purpose.",
    );
    expect(why).toHaveTextContent("Unit tests stage. 1 failed and 7 passed.");
    expect(why).toHaveTextContent(
      "Never started because of it: fs-payment-service-test-integration, fs-payment-service-deploy-staging.",
    );
    expect(within(why).getByRole("list")).toHaveTextContent(
      "Fix the failing test or the code it checks, then rerun the tests.",
    );
    // As the backend reports it: in fake mode the provider still names the configured model.
    expect(why).toHaveTextContent(
      "Worded by the fake provider, openai/gpt-oss-120b. The facts and lines come from the log (57 lines).",
    );
    expect(within(why).getByLabelText("The log lines that show it")).toHaveTextContent(
      "41 E AssertionError: intentional failure",
    );
    expect(backend.calls("POST /api/runs/:id/explain")).toHaveLength(1);
  });

  it("shows another job's log when asked", async () => {
    const user = userEvent.setup();
    const { backend, session } = await signedIn();
    const build = captured.chainFailed.jobs[0]?.run?.id ?? "";
    runs(backend).on("GET /api/runs/:id/log", () =>
      json(200, { run_id: build, text: "Started fs-payment-service-build #1\nFinished: SUCCESS\n", next_offset: 52, more_data: false }),
    );
    const { router } = renderRoutes(`/runs?chain=${captured.chainFailed.id}`, session, backend);

    await user.click(await screen.findByRole("link", { name: "Show the log of fs-payment-service-build" }));

    expect(currentPath(router)).toBe(`/runs?chain=${captured.chainFailed.id}&run=${build}`);
    const log = await screen.findByRole("region", { name: "Log of fs-payment-service-build #1" });
    expect(await within(log).findByText(/Finished: SUCCESS$/)).toBeInTheDocument();
  });

  it("follows a building Pipeline's log from where it left off", async () => {
    const { backend, session } = await signedIn();
    renderRoutes(`/runs?chain=${captured.chainPipelineRunning.id}`, session, runs(backend));

    const log = await screen.findByRole("region", {
      name: "Log of pl-payment-service-build-test-deploy-staging #1",
    });
    expect(await within(log).findByText(/\[Pipeline\] \{ \(Checkout\)$/)).toBeInTheDocument();
    expect(within(log).getByText("4 lines. Still writing.")).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Stages" })).toHaveTextContent(
      "Checkout succeededBuild succeededUnit tests runningDeploy to staging not started",
    );

    await waitFor(() => {
      const starts = backend
        .calls("GET /api/runs/:id/log")
        .map((request) => new URL(request.url).searchParams.get("start"));
      expect(starts).toEqual(expect.arrayContaining(["0", String(captured.logRunning.next_offset)]));
    });
  });

  it("says why a log could not be read, and tries again", async () => {
    const user = userEvent.setup();
    const { backend, session } = await signedIn();
    runs(backend).on("GET /api/runs/:id/log", () =>
      apiError(409, "JENKINS_UNAVAILABLE", "The log could not be read from Jenkins just now."),
    );
    renderRoutes(`/runs?chain=${captured.chainFailed.id}`, session, backend);

    const log = await screen.findByRole("region", { name: "Log of fs-payment-service-test-unit #1" });
    expect(await within(log).findByRole("alert")).toHaveTextContent(
      "The log could not be read. The log could not be read from Jenkins just now.",
    );
    runs(backend);
    await user.click(within(log).getByRole("button", { name: "Try again" }));

    expect(await within(log).findByText(/Finished: FAILURE$/)).toBeInTheDocument();
  });

  it("says why a failure could not be explained", async () => {
    const user = userEvent.setup();
    const { backend, session } = await signedIn();
    runs(backend).on("POST /api/runs/:id/explain", () =>
      json(captured.explainNotFailed.status, captured.explainNotFailed.body),
    );
    renderRoutes(`/runs?chain=${captured.chainFailed.id}`, session, backend);

    await user.click(await screen.findByRole("button", { name: "Explain why fs-payment-service-test-unit failed" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The failure could not be explained. This run succeeded, so there is no failure to explain.",
    );
    expect(screen.getByRole("button", { name: "Explain why fs-payment-service-test-unit failed" })).toHaveTextContent(
      "Try again",
    );
  });

  it("follows the runs as events arrive", async () => {
    const { backend, session } = await signedIn();
    renderRoutes("/runs", session, runs(backend));
    await screen.findByRole("table", { name: "Runs, newest first" });
    const before = backend.calls("GET /api/chains").length;

    const socket = FakeSocket.latest();
    act(() => {
      socket?.accept();
      socket?.deliver({ type: "chain.finished", sentAt: "2026-10-16T10:00:00Z", data: {} });
    });

    await waitFor(() => {
      expect(backend.calls("GET /api/chains").length).toBeGreaterThan(before);
    });
  });

  it("stacks each run under 768 px, with labelled facts", async () => {
    narrowScreen();
    const { backend, session } = await signedIn();
    renderRoutes("/runs", session, runs(backend));

    const list = await screen.findByRole("list", { name: "Runs, newest first" });
    expect(screen.queryByRole("table")).toBeNull();
    const [first] = within(list).getAllByRole("listitem");
    if (!first) {
      throw new Error("no run");
    }
    expect(within(first).getByRole("link", { name: "pl-payment-service-build-test-deploy-staging" })).toBeInTheDocument();
    expect(within(first).getByText("Assistant").nextElementSibling).toHaveTextContent("Pipeline");
    expect(within(first).getByText("Result").nextElementSibling).toHaveTextContent("Running");
  });
});
