import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { json, noAnswer, type FakeBackend } from "@/test/backend";
import { FakeSocket } from "@/test/fakeSocket";
import { evaluation, evaluationUnavailable } from "@/test/fixtures/evaluation";
import * as captured from "@/test/fixtures/pages";
import { renderRoutes } from "@/test/renderRoutes";
import { disposeSessions, neverAnswers, signedIn } from "@/test/signedIn";

beforeEach(() => {
  FakeSocket.opened = [];
});
afterEach(disposeSessions);

function analytics(backend: FakeBackend, populated = true): FakeBackend {
  return backend
    .on("GET /api/analytics/runs", () => json(200, populated ? captured.runStats : captured.runStatsEmpty))
    .on("GET /api/analytics/experiments", () =>
      json(200, populated ? captured.experiments : captured.experimentsEmpty),
    )
    .on("GET /api/analytics/experiments/:id", () => json(200, captured.experimentDetail))
    .on("GET /api/analytics/evaluation", () =>
      json(200, populated ? evaluation : evaluationUnavailable),
    );
}

const runsSection = () => screen.getByRole("region", { name: "Runs" });
const figure = (term: string) =>
  within(runsSection()).getByText(term, { selector: "dt" }).parentElement;

describe("analytics", () => {
  it("counts the runs, and says not measured, never 0, where nothing was measured", async () => {
    const { backend, session } = await signedIn();
    renderRoutes("/analytics", session, analytics(backend));

    expect(await within(await screen.findByRole("region", { name: "Runs" })).findByText("50%")).toBeInTheDocument();
    expect(figure("Runs")).toHaveTextContent("Runs3");
    expect(figure("Running now")).toHaveTextContent("1");
    expect(figure("Succeeded")).toHaveTextContent("50%Of 2 finished runs.");
    // 2777.5 ms, the mean of the two finished runs.
    expect(figure("Mean duration")).toHaveTextContent("3s");
    expect(figure("Mean queue wait")).toHaveTextContent(
      "Not measuredNo run's time in the queue was measured.",
    );
    expect(figure("Longest queue wait")).toHaveTextContent("Not measured");
    expect(
      within(screen.getByRole("list", { name: "Runs by result" }))
        .getAllByRole("listitem")
        .map((item) => item.textContent),
    ).toEqual(["Succeeded1", "Failed1", "Running1"]);
  });

  it("invites a first run when there are none, and says the experiments have not run", async () => {
    const { backend, session } = await signedIn();
    renderRoutes("/analytics", session, analytics(backend, false));

    expect(await screen.findByText(/No run has been recorded yet\./)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open the Freestyle Assistant" })).toHaveAttribute(
      "href",
      "/assistants/freestyle",
    );
    expect(await screen.findByText(/No experiment results yet\./)).toHaveTextContent(
      '"M2 dispatcher v1"',
    );
    expect(screen.queryByText("Not measured")).toBeNull();
  });

  it("lists the experiment runs and shows a run's metrics when chosen", async () => {
    const user = userEvent.setup();
    const { backend, session } = await signedIn();
    const { router } = renderRoutes("/analytics", session, analytics(backend));

    const table = await screen.findByRole("table", { name: "Experiment runs, newest first" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows.map((row) => within(row).getAllByRole("cell").map((cell) => cell.textContent))).toEqual([
      ["optimized", "mixed-30", "1", "1", "Not recorded", "Not recorded"],
      ["baseline", "mixed-30", "1", "1", "Not recorded", "Not recorded"],
    ]);

    const [first] = within(table).getAllByRole("link", { name: "run-1" });
    if (!first) {
      throw new Error("no experiment link");
    }
    await user.click(first);

    expect(router.state.location.search).toBe(`?experiment=${captured.experiments.items[0]?.id ?? ""}`);
    const metrics = await screen.findByRole("table", { name: "Metrics of run-1, optimized" });
    expect(
      within(metrics)
        .getAllByRole("row")
        .slice(1)
        .map((row) => row.textContent),
    ).toEqual(["mean_waitHIGH12.5 s, sd 1.59"]);
  });

  it("says who wrote the evaluation's answers before any of its figures", async () => {
    const { backend, session } = await signedIn();
    renderRoutes("/analytics", session, analytics(backend));

    const section = await screen.findByRole("region", { name: "Chatbot evaluation" });
    const note = await within(section).findByRole("note");
    expect(note).toHaveTextContent("Who wrote the answers:");
    expect(note).toHaveTextContent("Claude Code");
    expect(note).toHaveTextContent("D-081");
    const table = within(section).getByRole("table", { name: "Parsers compared on the test split" });
    // The note comes first in the page's reading order, before the first figure.
    expect(note.compareDocumentPosition(table) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(section).getByText(/Reviewed by a person: 0\./)).toBeInTheDocument();
  });

  it("tables each parser on the test split, to one decimal, and not measured for no latency", async () => {
    const { backend, session } = await signedIn();
    renderRoutes("/analytics", session, analytics(backend));

    const table = await screen.findByRole("table", { name: "Parsers compared on the test split" });
    const [row] = within(table).getAllByRole("row").slice(1);
    if (!row) {
      throw new Error("no parser row");
    }
    expect(within(row).getByRole("rowheader")).toHaveTextContent("Rule baseline");
    expect(within(row).getAllByRole("cell").map((cell) => cell.textContent)).toEqual([
      "150",
      "83.3%",
      "72.7%",
      "85.3%",
      "80.6%, 87.9%",
      "100.0%",
      "0 ms, 0 ms",
      "0",
    ]);
  });

  it("says why the evaluation cannot be shown, rather than an empty table", async () => {
    const { backend, session } = await signedIn();
    renderRoutes("/analytics", session, analytics(backend, false));

    const section = await screen.findByRole("region", { name: "Chatbot evaluation" });
    expect(
      await within(section).findByText(/No evaluation report has been generated yet\./),
    ).toHaveTextContent("python -m eval report");
    expect(within(section).queryByRole("table")).toBeNull();
  });

  it("keeps rejected responses and failed live builds visible in the archived results", async () => {
    const { backend, session } = await signedIn();
    renderRoutes("/analytics", session, analytics(backend));

    const comparison = await screen.findByRole("table", {
      name: "Parsers compared on the test split",
    });
    const model = within(comparison).getByRole("row", { name: /openai\/gpt-oss-20b/ });
    expect(within(model).getByText("148, 2 unanswered")).toBeInTheDocument();
    expect(
      screen.getByText(/excluded from accuracy, clarification and refusal percentages/),
    ).toBeInTheDocument();

    const ablations = screen.getByRole("table", { name: "Ablations on the 75-item subset" });
    const noEnums = within(ablations).getByRole("row", { name: /No catalog enums/ });
    expect(within(noEnums).getByText("74, 1 unanswered")).toBeInTheDocument();

    const live = screen.getByRole("table", { name: "End-to-end success" });
    expect(within(live).getByText("18 of 20")).toBeInTheDocument();
    expect(within(live).getByText("2 did not run to success")).toBeInTheDocument();
  });

  it("says each part is loading, and what failed", async () => {
    const { backend, session } = await signedIn();
    backend
      .on("GET /api/analytics/runs", neverAnswers)
      .on("GET /api/analytics/experiments", noAnswer)
      .on("GET /api/analytics/evaluation", neverAnswers);
    renderRoutes("/analytics", session, backend);

    expect(await screen.findByText("Loading the run statistics")).toBeInTheDocument();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The experiments could not be loaded. The server did not answer.",
    );
  });

  it("counts again when a run starts or finishes", async () => {
    const { backend, session } = await signedIn();
    renderRoutes("/analytics", session, analytics(backend));
    await screen.findByText("50%");
    const before = backend.calls("GET /api/analytics/runs").length;

    const socket = FakeSocket.latest();
    act(() => {
      socket?.accept();
      socket?.deliver({ type: "run.finished", sentAt: "2026-10-16T10:00:00Z", data: {} });
    });

    await waitFor(() => {
      expect(backend.calls("GET /api/analytics/runs").length).toBeGreaterThan(before);
    });
  });
});
