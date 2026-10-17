import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { DEVELOPER, json, noAnswer, type FakeBackend } from "@/test/backend";
import { FakeSocket } from "@/test/fakeSocket";
import * as captured from "@/test/fixtures/pages";
import * as queues from "@/test/fixtures/queue";
import { renderRoutes } from "@/test/renderRoutes";
import { disposeSessions, neverAnswers, signedIn } from "@/test/signedIn";

beforeEach(() => {
  FakeSocket.opened = [];
});
afterEach(disposeSessions);

const CARDS = [captured.chainFailed, captured.chainQueued, captured.chainPipelineRunning];

/** The overview's sources as the real backend answered them, for the Admin who started the runs. */
function overview(backend: FakeBackend): FakeBackend {
  return backend
    .on("GET /api/queue", () => json(200, captured.queue))
    .on("GET /api/chains", () => json(200, captured.chainsActive))
    .on("GET /api/chains/:id", (request) => {
      const id = new URL(request.url).pathname.split("/")[3];
      return json(200, CARDS.find((card) => card.id === id) ?? captured.chainFailed);
    })
    .on("GET /api/runs", () => json(200, captured.runs))
    .on("GET /api/health", () => json(200, captured.healthFake))
    .on("POST /api/runs/:id/explain", () => json(200, captured.explainFailed.body));
}

const figure = (term: string) => screen.getByText(term, { selector: "dt" }).parentElement;

describe("the overview", () => {
  it("leads with the jobs waiting, then my active runs and how many recent runs failed", async () => {
    const { backend, session } = await signedIn(captured.me);
    renderRoutes("/", session, overview(backend));

    await waitFor(() => {
      expect(figure("jobs waiting")).toHaveTextContent("jobs waiting3");
    });
    expect(screen.getByText("3", { selector: "dd" })).toHaveClass("text-hero");
    await waitFor(() => {
      expect(figure("my active runs")).toHaveTextContent("my active runs2");
    });
    expect(figure("runs failed")).toHaveTextContent("runs failed1 of the last 2");
  });

  it("says how the AI provider is configured, never that it is answering", async () => {
    const { backend, session } = await signedIn(captured.me);
    const { unmount } = renderRoutes("/", session, overview(backend));
    const provider = await screen.findByRole("group", { name: "AI provider" });
    expect(await within(provider).findByText("Off")).toBeInTheDocument();
    expect(provider).toHaveTextContent("AI providerOfffake provider; no network calls");
    unmount();

    for (const [health, words] of [
      [captured.healthLive, "AI providerLivelive; chain openai/gpt-oss-120b -> openai/gpt-oss-20b"],
      [captured.healthLiveNoKey.body, "AI providerDownRuntimeError: LLM_MODE=live but GROQ_API_KEY is empty"],
    ] as const) {
      const signed = await signedIn(captured.me);
      overview(signed.backend).on("GET /api/health", () => json(200, health));
      const view = renderRoutes("/", signed.session, signed.backend);
      const group = await screen.findByRole("group", { name: "AI provider" });
      await waitFor(() => {
        expect(group).toHaveTextContent(words);
      });
      view.unmount();
    }
  });

  it("shows where each of my runs waits, with its score bar, or what it is doing", async () => {
    const { backend, session } = await signedIn(captured.me);
    renderRoutes("/", session, overview(backend));

    const mine = await screen.findByRole("list", { name: "My active runs" });
    const [pipeline, queued] = within(mine).getAllByRole("listitem");
    expect(pipeline && within(pipeline).getByRole("link", { name: "pl-payment-service-build-test-deploy-staging" })).toHaveAttribute(
      "href",
      `/runs?chain=${captured.chainPipelineRunning.id}`,
    );
    expect(pipeline && (await within(pipeline).findByText("Unit tests stage"))).toBeInTheDocument();
    expect(queued && (await within(queued).findByText("1st in queue"))).toBeInTheDocument();
    expect(
      queued &&
        within(queued).getByRole("img", {
          name: "Score 0.671: urgency 0.500, dependency 0.000, execution time 0.171, aging 0.000.",
        }),
    ).toBeInTheDocument();
  });

  it("lists only the runs I started", async () => {
    const { backend, session } = await signedIn(DEVELOPER);
    renderRoutes("/", session, overview(backend));

    expect(await screen.findByText(/^You have no runs in progress\./)).toBeInTheDocument();
    expect(figure("my active runs")).toHaveTextContent("my active runs0");
    expect(backend.calls("GET /api/chains/:id")).toHaveLength(0);
  });

  it("lists the latest results, and explains a failure on request", async () => {
    const user = userEvent.setup();
    const { backend, session } = await signedIn(captured.me);
    renderRoutes("/", session, overview(backend));

    const results = await screen.findByRole("list", { name: "Recent results" });
    const [failed, passed] = within(results).getAllByRole("listitem");
    expect(failed).toHaveTextContent(/^Failedfs-payment-service-test-unit #14s/);
    expect(passed).toHaveTextContent(/^Succeededfs-payment-service-build #11s/);
    expect(passed && within(passed).queryByRole("button")).toBeNull();

    await user.click(
      within(failed as HTMLElement).getByRole("button", {
        name: "Explain why fs-payment-service-test-unit failed",
      }),
    );

    expect(
      await screen.findByRole("region", { name: "Why fs-payment-service-test-unit failed" }),
    ).toHaveTextContent("1 of 8 tests failed");
  });

  it("says why the jobs waiting are unknown when the ranking is unavailable", async () => {
    const { backend, session } = await signedIn(captured.me);
    overview(backend).on("GET /api/queue", () => json(200, queues.unavailable));
    renderRoutes("/", session, backend);

    await waitFor(() => {
      expect(figure("jobs waiting")).toHaveTextContent(
        "jobs waitingUnknownThe ranking is unavailable: the plugin is not installed on this controller.",
      );
    });
  });

  it("invites a first run when nothing has run, and says nothing has finished", async () => {
    const { backend, session } = await signedIn(captured.me);
    overview(backend)
      .on("GET /api/chains", () => json(200, captured.chainsEmpty))
      .on("GET /api/runs", () => json(200, captured.runsEmpty));
    renderRoutes("/", session, backend);

    expect(await screen.findByText(/^No run has finished yet\./)).toBeInTheDocument();
    expect(figure("runs finished yet")).toHaveTextContent("runs finished yetNone");
    expect(screen.getByRole("link", { name: "Open the Freestyle Assistant" })).toBeInTheDocument();
  });

  it("says what is loading, and what failed", async () => {
    const { backend, session } = await signedIn(captured.me);
    overview(backend).on("GET /api/chains", neverAnswers).on("GET /api/runs", noAnswer);
    renderRoutes("/", session, backend);

    expect(await screen.findByText("Loading your active runs")).toBeInTheDocument();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The recent results could not be loaded. The server did not answer.",
    );
    expect(figure("runs failed")).toHaveTextContent("Unknown");
  });

  it("follows runs and the queue as events arrive", async () => {
    const { backend, session } = await signedIn(captured.me);
    renderRoutes("/", session, overview(backend));
    await screen.findByRole("list", { name: "Recent results" });
    const runs = backend.calls("GET /api/runs").length;
    const queue = backend.calls("GET /api/queue").length;

    const socket = FakeSocket.latest();
    act(() => {
      socket?.accept();
      socket?.deliver({ type: "run.finished", sentAt: "2026-10-16T10:00:00Z", data: {} });
    });

    await waitFor(() => {
      expect(backend.calls("GET /api/runs").length).toBeGreaterThan(runs);
      expect(backend.calls("GET /api/queue").length).toBeGreaterThan(queue);
    });
  });
});
