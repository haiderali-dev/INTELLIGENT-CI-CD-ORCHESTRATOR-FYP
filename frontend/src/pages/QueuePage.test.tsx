import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Queue, QueueItem } from "@/api/queueApi";
import type { Session } from "@/auth/session";
import { json, noAnswer, signedInSession, type FakeBackend } from "@/test/backend";
import { FakeSocket } from "@/test/fakeSocket";
import * as captured from "@/test/fixtures/queue";
import { renderRoutes } from "@/test/renderRoutes";

import { QUEUE_REFRESH_MS } from "./QueuePage";

const RANKING = "Waiting jobs, ranked by score, highest first";
const SENT_AT = "2026-10-16T10:00:00Z";

const sessions: Session[] = [];

beforeEach(() => {
  FakeSocket.opened = [];
});

afterEach(() => {
  for (const session of sessions.splice(0)) {
    session.dispose();
  }
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

/** A signed-in backend whose `GET /api/queue` answers with a response captured from the real one. */
async function backendServing(queue: Queue) {
  const { backend, session } = await signedInSession();
  sessions.push(session);
  backend.on("GET /api/queue", () => json(200, queue));
  return { backend, session };
}

function renderQueue(backend: FakeBackend, session: Session) {
  return renderRoutes("/queue", session, backend);
}

const table = () => screen.getByRole("table", { name: RANKING });
/** The ranked rows, without the header row. */
const rows = () => within(table()).getAllByRole("row").slice(1);
const row = (index: number) => {
  const found = rows()[index];
  if (!found) {
    throw new Error(`no row ${String(index)}`);
  }
  return found;
};
const cells = (index: number) => within(row(index)).getAllByRole("cell");
const status = () => screen.getByRole("list", { name: "Queue status" });

function item(queue: Queue, index: number): QueueItem {
  const found = queue.items[index];
  if (!found) {
    throw new Error(`the fixture has no item ${String(index)}`);
  }
  return found;
}

/** The server's side of the socket: accept, say hello, then send `events`. */
function serverSends(...events: { type: string; data?: Record<string, unknown> }[]) {
  const socket = FakeSocket.latest();
  act(() => {
    socket?.accept();
    socket?.deliver({ type: "hello", sentAt: SENT_AT, data: { heartbeatSeconds: 25 } });
    for (const { type, data = {} } of events) {
      socket?.deliver({ type, sentAt: SENT_AT, data });
    }
  });
}

/** A screen narrower than 768 px: every media query in the app answers no. */
function narrowScreen() {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    addListener: () => undefined,
    removeListener: () => undefined,
    dispatchEvent: () => false,
  }));
}

describe("the queue page", () => {
  it("ranks each waiting job and explains its score with its bar", async () => {
    const { backend, session } = await backendServing(captured.group);
    renderQueue(backend, session);

    expect(await screen.findByRole("heading", { level: 1, name: "Queue" })).toBeInTheDocument();
    await screen.findByRole("table", { name: RANKING });
    expect(rows()).toHaveLength(5);
    expect(
      within(table())
        .getAllByRole("columnheader")
        .map((header) => header.textContent),
    ).toEqual(["Rank", "Job", "Type", "Urgency", "Score", "Estimate", "Wait", "Blocked reason"]);

    // Rank 1 is the MEDIUM upstream, which inherits its HIGH downstream's 0.980 (Appendix C's case).
    expect(within(row(0)).getByRole("rowheader")).toHaveTextContent("it-revision-upstream");
    expect(cells(0).map((cell) => cell.textContent)).toEqual(
      expect.arrayContaining(["1", "Freestyle", "MEDIUM", "Under 1s", "6s"]),
    );
    expect(
      within(row(0)).getByRole("img", {
        name: "Score 0.980, inherited from its group. Own score 0.800: urgency 0.300, dependency 0.300, execution time 0.200, aging 0.000.",
      }),
    ).toBeInTheDocument();
    expect(within(row(0)).getByText("inherited")).toBeInTheDocument();
    expect(row(0)).toHaveTextContent(item(captured.group, 0).blocked_reason ?? "missing");

    expect(within(row(1)).getByRole("rowheader")).toHaveTextContent("it-revision-freestyle");
    expect(within(row(1)).queryByText("inherited")).toBeNull();
    expect(within(row(4)).getByRole("rowheader")).toHaveTextContent(
      "it-failure-payment-service-test-unit",
    );
    expect(cells(4).map((cell) => cell.textContent)).toEqual(
      expect.arrayContaining(["5", "33s"]),
    );

    expect(status()).toHaveTextContent("8 waiting");
    expect(within(status()).getByText("Optimizer on")).toBeInTheDocument();
  });

  it("lists queued work the optimizer has not scored, which the waiting count includes", async () => {
    const { backend, session } = await backendServing(captured.group);
    renderQueue(backend, session);

    const section = await screen.findByRole("region", { name: "Waiting without a score" });
    for (const name of [
      "it-pipeline-create-trigger-read",
      "it-revision-pipeline",
      "it-revision-probe-pipeline",
    ]) {
      expect(within(section).getByText(name)).toBeInTheDocument();
    }
    expect(within(section).getAllByText("Not scored by the optimizer")).toHaveLength(3);
    // Five ranked and three unscored: the plugin's queueLength of 8.
    expect(status()).toHaveTextContent("8 waiting");
  });

  it("lists a job held for its upstream, naming the job it waits for", async () => {
    const { backend, session } = await backendServing(captured.heldForUpstream);
    renderQueue(backend, session);

    const section = await screen.findByRole("region", { name: "Held back" });
    const entry = within(section).getByRole("listitem");
    expect(entry).toHaveTextContent("it-held-downstream");
    expect(entry).toHaveTextContent("HIGH");
    expect(entry).toHaveTextContent("Waits for it-held-upstream, which is building");
    expect(screen.getByText("Nothing is ready to run: every queued job is held back.")).toBeInTheDocument();
    expect(screen.queryByRole("table", { name: RANKING })).toBeNull();
    expect(status()).toHaveTextContent("0 waiting");
    expect(status()).toHaveTextContent("1 held back");
  });

  it("puts a HIGH job above lower urgency, in the plugin's rank order", async () => {
    const reversed = { ...captured.threeWaiting, items: [...captured.threeWaiting.items].reverse() };
    const { backend, session } = await backendServing(reversed);
    renderQueue(backend, session);

    await screen.findByRole("table", { name: RANKING });
    expect(rows().map((each) => within(each).getByRole("rowheader").textContent)).toEqual([
      "it-revision-freestyle",
      "it-revision-probe-freestyle",
      "it-failure-payment-service-test-unit",
    ]);
    expect(cells(0)).toEqual(expect.arrayContaining([expect.objectContaining({ textContent: "HIGH" })]));
  });

  it("adds each bar's four contributions as columns when asked", async () => {
    const user = userEvent.setup();
    const { backend, session } = await backendServing(captured.group);
    renderQueue(backend, session);
    const toggle = await screen.findByRole("switch", { name: "Show the numbers" });
    expect(toggle).not.toBeChecked();

    await user.click(toggle);

    expect(toggle).toBeChecked();
    expect(
      within(table())
        .getAllByRole("columnheader")
        .map((header) => header.textContent),
    ).toEqual([
      "Rank",
      "Job",
      "Type",
      "Urgency",
      "Score",
      "From urgency",
      "From dependency",
      "From execution time",
      "From aging",
      "Estimate",
      "Wait",
      "Blocked reason",
    ]);
    // it-revision-freestyle: 0.5 x 1.0, 0.3 x 1.0, 0.2 x 0.89997 and no aging, from the plugin's
    // own weights and factors.
    expect(cells(1).slice(4, 8).map((cell) => cell.textContent)).toEqual([
      "0.500",
      "0.300",
      "0.180",
      "0.000",
    ]);
  });

  it("follows queue events, and only the first load grows the bars", async () => {
    const { backend, session } = await backendServing(captured.threeWaiting);
    const { container } = renderQueue(backend, session);
    await screen.findByRole("table", { name: RANKING });
    expect(container.querySelectorAll("[data-grow]")).toHaveLength(3);
    await waitFor(() => {
      expect(container.querySelectorAll("[data-grow]")).toHaveLength(0);
    });
    expect(within(status()).getByText("Connecting")).toBeInTheDocument();

    backend.on("GET /api/queue", () => json(200, captured.aged));
    serverSends({ type: "queue.changed", data: { resolved: 1, advanced: 0 } });

    await waitFor(() => {
      expect(rows()).toHaveLength(1);
    });
    expect(within(row(0)).getByRole("rowheader")).toHaveTextContent(
      "it-failure-payment-service-test-unit",
    );
    expect(
      within(row(0)).getByRole("img", {
        name: "Score 0.350: urgency 0.300, dependency 0.000, execution time 0.000, aging 0.050.",
      }),
    ).toBeInTheDocument();
    expect(cells(0).map((cell) => cell.textContent)).toEqual(expect.arrayContaining(["5m"]));
    // A live update jumps straight to the new value.
    expect(container.querySelectorAll("[data-grow]")).toHaveLength(0);
    expect(within(status()).getByText("Live")).toBeInTheDocument();
  });

  it("asks again on every event that moves a run in or out of the queue", async () => {
    const { backend, session } = await backendServing(captured.threeWaiting);
    renderQueue(backend, session);
    await screen.findByRole("table", { name: RANKING });
    serverSends();

    for (const type of ["run.queued", "run.started", "run.finished", "queue.changed"]) {
      const before = backend.calls("GET /api/queue").length;
      serverSends({ type });
      await waitFor(() => {
        expect(backend.calls("GET /api/queue").length).toBeGreaterThan(before);
      });
    }
  });

  it("asks again every 10 seconds, because waits and aging grow between events", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { backend, session } = await backendServing(captured.threeWaiting);
    renderQueue(backend, session);
    await screen.findByRole("table", { name: RANKING });
    const before = backend.calls("GET /api/queue").length;

    await act(async () => {
      await vi.advanceTimersByTimeAsync(QUEUE_REFRESH_MS);
    });

    await waitFor(() => {
      expect(backend.calls("GET /api/queue").length).toBe(before + 1);
    });
  });

  it("says the ranking is unavailable and why, instead of drawing empty bars", async () => {
    const { backend, session } = await backendServing(captured.unavailable);
    renderQueue(backend, session);

    expect(await screen.findByRole("heading", { name: "Ranking unavailable" })).toBeInTheDocument();
    expect(
      screen.getByText(
        "The backend could not read the queue optimizer plugin: the plugin is not installed on this controller.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText(/This page asks again every 10 seconds\.$/)).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.queryByRole("img")).toBeNull();
    // Nothing is known about the queue, so the header claims nothing about it.
    expect(status()).not.toHaveTextContent("waiting");
    expect(status()).not.toHaveTextContent("Optimizer");
  });

  it("says when the optimizer is off, and still shows the scores", async () => {
    const { backend, session } = await backendServing(captured.optimizerOff);
    renderQueue(backend, session);

    expect(
      await within(await screen.findByRole("list", { name: "Queue status" })).findByText(
        "Optimizer off: Jenkins' own order",
      ),
    ).toBeInTheDocument();
    await screen.findByRole("table", { name: RANKING });
    expect(within(table()).getAllByRole("img")).toHaveLength(3);
  });

  it("invites a build when nothing is waiting", async () => {
    const { backend, session } = await backendServing(captured.empty);
    renderQueue(backend, session);

    expect(
      await screen.findByText(
        "Nothing is waiting for an executor. Ask an assistant for a build, and it is ranked here while it waits.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ask the Freestyle Assistant" })).toHaveAttribute(
      "href",
      "/assistants/freestyle",
    );
    expect(screen.getByRole("link", { name: "Ask the Pipeline Assistant" })).toHaveAttribute(
      "href",
      "/assistants/pipeline",
    );
    expect(status()).toHaveTextContent("0 waiting");
    expect(screen.queryByRole("switch")).toBeNull();
  });

  it("says what failed when the queue cannot be loaded, and tries again on request", async () => {
    const user = userEvent.setup();
    const { backend, session } = await backendServing(captured.threeWaiting);
    backend.on("GET /api/queue", noAnswer);
    renderQueue(backend, session);

    const message = await screen.findByText(/The queue could not be loaded\./);
    const alert = message.closest('[role="alert"]');
    expect(alert).toHaveTextContent(
      "The queue could not be loaded. The server did not answer. Check that the backend is running, then try again.",
    );

    backend.on("GET /api/queue", () => json(200, captured.threeWaiting));
    await user.click(within(alert as HTMLElement).getByRole("button", { name: "Try again" }));

    expect(await screen.findByRole("table", { name: RANKING })).toBeInTheDocument();
  });

  it("keeps the last ranking when a refresh fails, and says from when", async () => {
    const { backend, session } = await backendServing(captured.threeWaiting);
    renderQueue(backend, session);
    await screen.findByRole("table", { name: RANKING });

    backend.on("GET /api/queue", noAnswer);
    serverSends({ type: "queue.changed" });

    const notice = await screen.findByRole("status");
    expect(notice).toHaveTextContent(
      /^The queue could not be refreshed\. The server did not answer\. Check that the backend is running, then try again\. Showing the ranking from \d\d:\d\d:\d\d\.$/,
    );
    expect(rows()).toHaveLength(3);
  });

  it("stacks each job under 768 px, with its bar on its own line and labelled facts", async () => {
    narrowScreen();
    const { backend, session } = await backendServing(captured.group);
    renderQueue(backend, session);

    const list = await screen.findByRole("list", { name: RANKING });
    expect(screen.queryByRole("table")).toBeNull();
    const [first] = within(list).getAllByRole("listitem");
    if (!first) {
      throw new Error("no ranked item");
    }
    expect(first).toHaveTextContent(/^1it-revision-upstream/);
    expect(within(first).getByRole("img", { name: /^Score 0\.980, inherited/ })).toBeInTheDocument();
    for (const [label, value] of [
      ["Type", "Freestyle"],
      ["Urgency", "MEDIUM"],
      ["Estimate", "Under 1s"],
      ["Wait", "6s"],
    ] as const) {
      expect(within(first).getByText(label).nextElementSibling).toHaveTextContent(value);
    }
  });

  it("names an upstream job that Jenkins does not have, under the job that names it", async () => {
    // The group's fourth item, as it would read had its job declared a dependency on a job that
    // was since deleted: DependencyGate.unresolvedUpstream reports it, and never waits on it.
    const missing = {
      ...captured.group,
      items: captured.group.items.map((each) =>
        each.rank === 4 ? { ...each, unresolved_dependencies: ["fs-gone-build"] } : each,
      ),
    };
    const { backend, session } = await backendServing(missing);
    renderQueue(backend, session);

    await screen.findByRole("table", { name: RANKING });
    expect(within(row(3)).getByRole("rowheader")).toHaveTextContent(
      "it-revision-probe-freestyleUpstream job not found: fs-gone-build",
    );
    expect(within(row(2)).getByRole("rowheader")).not.toHaveTextContent("not found");
  });
});
