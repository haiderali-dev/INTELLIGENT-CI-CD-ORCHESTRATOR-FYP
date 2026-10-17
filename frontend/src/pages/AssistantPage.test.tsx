import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";

import type { ConversationDetail, Message } from "@/api/assistantApi";
import type { Session } from "@/auth/session";
import { apiError, bodyOf, json, signedInSession, type FakeBackend } from "@/test/backend";
import { FakeSocket } from "@/test/fakeSocket";
import * as captured from "@/test/fixtures/captured";
import { currentPath, renderRoutes } from "@/test/renderRoutes";

const CHAT = captured.createdChat.id;
const messages = captured.conversationDetail.messages;
const byKind = (kind: string) => messages.filter((message) => message.payload?.kind === kind);

/** The conversation's messages up to and including the one with `id`. */
function messagesThrough(id: string): Message[] {
  const end = messages.findIndex((message) => message.id === id);
  return messages.slice(0, end + 1);
}

const sessions: Session[] = [];

beforeAll(async () => {
  // The preview loads CodeMirror lazily; loading it once keeps the tests from racing it.
  await import("@/components/code/CodeView");
});

beforeEach(() => {
  FakeSocket.opened = [];
});

afterEach(() => {
  for (const session of sessions.splice(0)) {
    session.dispose();
  }
});

/**
 * A signed-in backend that answers like the real one, from responses captured from it. The chat is
 * a store: a sent message and its reply are added to it, so a refetch returns what the real backend
 * would by then.
 */
async function backendWith(chat: Message[] | null) {
  const { backend, session } = await signedInSession();
  sessions.push(session);
  const store: ConversationDetail = { ...captured.conversationDetail, messages: chat ?? [] };
  backend
    .on("GET /api/services", () => json(200, captured.services))
    .on("GET /api/services/:name/branches", (request) => {
      const name = new URL(request.url).pathname.split("/")[3] ?? "";
      return json(200, { ...captured.paymentBranches, service: name });
    })
    .on("GET /api/conversations", () =>
      json(200, chat ? captured.freestyleChats : { items: [], total: 0, limit: 50, offset: 0 }),
    )
    .on("POST /api/assistants/:assistant/conversations", () => json(201, captured.createdChat))
    .on("GET /api/conversations/:id", () => json(200, store))
    .on("GET /api/commands/:id", () => json(200, captured.command))
    .on("GET /api/pipelines/:id", (request) => {
      const id = new URL(request.url).pathname.split("/")[3];
      const found = [
        captured.freestylePipeline,
        captured.invalidPipeline,
        captured.pipelinePipeline,
      ].find((pipeline) => pipeline.id === id);
      return found ? json(200, found) : json(200, { ...captured.freestylePipeline, id });
    })
    .on("GET /api/chains/:id", () => json(200, captured.queuedChain));
  return { backend, session, store };
}

function renderPage(path: string, backend: FakeBackend, session: Session) {
  return renderRoutes(path, session, backend);
}

const composer = () => screen.getByRole("textbox", { name: /^Message the / });

// The whole app, signed in, per test, and the first of them also starts it cold: 1.3 to 1.9 s on an
// idle machine, and past the default 5 s limit while the Phase 6 gate's Jenkins builds load it. The
// limit is about the machine, not the page, so it is wider here; every assertion is unchanged.
describe("an assistant page", { timeout: 15_000 }, () => {
  it("opens a new chat only once its first exchange is stored, so it never loads it empty", async () => {
    // T6.8's flows caught the page showing a new chat empty: it was opened when created, its own
    // load raced the send, read it empty and landed after the reply. Here the send takes a while,
    // and no load of the chat may start before it has finished.
    const user = userEvent.setup({ delay: null });
    const { backend, session, store } = await backendWith(null);
    let stored = false;
    const loadsBeforeStored: boolean[] = [];
    backend
      .on("POST /api/conversations/:id/messages", async () => {
        // Long enough for the router to have opened the chat, had it been opened on creation: at
        // 50 ms the old order was not caught here, at 400 ms it was.
        await new Promise((resolve) => setTimeout(resolve, 400));
        store.messages = [captured.intentExchange.user_message, captured.intentExchange.assistant_message];
        stored = true;
        return json(201, captured.intentExchange);
      })
      .on("GET /api/conversations/:id", () => {
        loadsBeforeStored.push(!stored);
        return json(200, store);
      });
    const { router } = renderPage("/assistants/freestyle", backend, session);
    await screen.findByText("Services it knows:");

    await user.type(composer(), "Build, test and deploy payment-service to staging{Enter}");

    expect(await screen.findByRole("region", { name: "Intent" })).toBeInTheDocument();
    expect(currentPath(router)).toBe(`/assistants/freestyle/${CHAT}`);
    expect(loadsBeforeStored.length).toBeGreaterThan(0);
    expect(loadsBeforeStored).not.toContain(true);
  });

  it("invites a first request, and makes the chat only when one is sent", async () => {
    // Every key is still pressed, without a timer between them: typing fifty of them with one
    // took this test past its 5 s limit under load, twice, during the Phase 6 gate.
    const user = userEvent.setup({ delay: null });
    const { backend, session, store } = await backendWith(null);
    backend.on("POST /api/conversations/:id/messages", () => {
      store.messages = [
        captured.intentExchange.user_message,
        captured.intentExchange.assistant_message,
      ];
      return json(201, captured.intentExchange);
    });
    const { router } = renderPage("/assistants/freestyle", backend, session);

    expect(await screen.findByText("Services it knows:")).toBeInTheDocument();
    expect(await screen.findByText("payment-service, auth-service")).toBeInTheDocument();
    expect(backend.calls("POST /api/assistants/:assistant/conversations")).toHaveLength(0);

    await user.type(composer(), "Build, test and deploy payment-service to staging{Enter}");

    const card = await screen.findByRole("region", { name: "Intent" });
    expect(within(card).getAllByRole("definition").map((value) => value.textContent)).toEqual([
      "payment-service",
      // Not named in the request: the branch the backend resolved in Git.
      "main",
      "staging",
      "Not set",
    ]);
    expect(
      screen.getByText("Ready to generate: build, test and deploy payment-service to staging on main."),
    ).toBeInTheDocument();
    expect(currentPath(router)).toBe(`/assistants/freestyle/${CHAT}`);
    expect(backend.calls("POST /api/assistants/:assistant/conversations")).toHaveLength(1);
    expect(await bodyOf(backend.calls("POST /api/conversations/:id/messages")[0])).toEqual({
      text: "Build, test and deploy payment-service to staging",
    });
  });

  it("fills the composer with an example command, ready to send", async () => {
    const user = userEvent.setup();
    const { backend, session } = await backendWith(null);
    renderPage("/assistants/freestyle", backend, session);

    await user.click(await screen.findByRole("button", { name: "Build payment-service from main" }));

    expect(composer()).toHaveValue("Build payment-service from main");
    expect(composer()).toHaveFocus();
    expect(backend.calls("POST /api/conversations/:id/messages")).toHaveLength(0);
  });

  it("shows the thread in order, a message before its reply even at the same moment", async () => {
    const { backend, session } = await backendWith(messages);
    renderPage(`/assistants/freestyle/${CHAT}`, backend, session);

    const thread = await screen.findByRole("list", { name: "Conversation with the Freestyle Assistant" });
    // The thread's own messages, not the lists inside them.
    const items = [...thread.children] as HTMLElement[];
    expect(items).toHaveLength(messages.length);
    // The captured /help pair shares one timestamp, and the backend sent the reply first.
    const last = items.slice(-2).map((item) => item.firstElementChild?.textContent);
    expect(last).toEqual(["You", "Freestyle Assistant"]);
    expect(within(items.at(-1) as HTMLElement).getByText("Here is what I can do")).toBeInTheDocument();
  });

  it("edits the intent, and the card shows the change", async () => {
    const user = userEvent.setup();
    const { backend, session } = await backendWith(messagesThrough(byKind("intent")[0]?.id ?? ""));
    // The command as the reply left it; the captured `command` is from after the edit.
    let current = captured.intentExchange.command;
    backend
      .on("GET /api/commands/:id", () => json(200, current))
      .on("PATCH /api/commands/:id/intent", () => {
        current = captured.editedCommand;
        return json(200, current);
      });
    renderPage(`/assistants/freestyle/${CHAT}`, backend, session);

    const card = await screen.findByRole("region", { name: "Intent" });
    await user.click(within(card).getByRole("button", { name: "Edit" }));
    await user.selectOptions(within(card).getByLabelText("Urgency"), "LOW");
    await user.click(within(card).getByRole("button", { name: "Save changes" }));

    expect(await bodyOf(backend.calls("PATCH /api/commands/:id/intent")[0])).toEqual({ urgency: "LOW" });
    expect(await within(card).findByText("LOW")).toBeInTheDocument();
  });

  it("generates, and the preview shows the spec, each job's config.xml and the checks", async () => {
    const user = userEvent.setup();
    const intentOnly = messagesThrough(byKind("intent")[0]?.id ?? "");
    const { backend, session, store } = await backendWith(intentOnly);
    backend.on("POST /api/commands/:id/generate", () => {
      store.messages = messagesThrough(byKind("pipeline")[0]?.id ?? "");
      return json(201, captured.freestylePipeline);
    });
    renderPage(`/assistants/freestyle/${CHAT}`, backend, session);

    await user.click(await screen.findByRole("button", { name: "Generate" }));

    const preview = await screen.findByRole("complementary", { name: "Preview" });
    expect(await within(preview).findByRole("textbox", { name: "Spec" })).toHaveTextContent(
      "service: payment-service",
    );
    await user.click(within(preview).getByRole("tab", { name: "Config" }));
    expect(
      await within(preview).findByRole("textbox", { name: "config.xml for fs-payment-service-build" }),
    ).toBeInTheDocument();
    expect(within(preview).getAllByRole("option").map((option) => option.textContent)).toEqual([
      "fs-payment-service-build",
      "fs-payment-service-test-unit",
      "fs-payment-service-test-integration",
      "fs-payment-service-deploy-staging",
    ]);
    await user.click(within(preview).getByRole("tab", { name: "Checks" }));
    expect(within(preview).getByText("Validated", { selector: "[aria-live]" })).toBeInTheDocument();
    expect(
      within(preview).getByText("Creates 4 jobs and starts fs-payment-service-build on main at LOW priority"),
    ).toBeInTheDocument();
  });

  it("approves with one idempotency key, says Run started, and follows the run", async () => {
    const user = userEvent.setup();
    const { backend, session, store } = await backendWith(messagesThrough(byKind("pipeline")[0]?.id ?? ""));
    backend.on("POST /api/pipelines/:id/approve", () => {
      store.messages = messagesThrough(byKind("run")[0]?.id ?? "");
      return json(200, captured.approval);
    });
    renderPage(`/assistants/freestyle/${CHAT}`, backend, session);

    const preview = await screen.findByRole("complementary", { name: "Preview" });
    await user.click(await within(preview).findByRole("button", { name: "Approve and run" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Approve and run" });
    expect(dialog).toHaveAccessibleDescription(
      "Creates 4 jobs and starts fs-payment-service-build on main at LOW priority",
    );
    await user.click(within(dialog).getByRole("button", { name: "Approve and run" }));

    expect(await screen.findByText("Run started")).toBeInTheDocument();
    const [approve] = backend.calls("POST /api/pipelines/:id/approve");
    expect(approve?.headers.get("Idempotency-Key")).toMatch(/^[0-9a-f-]{36}$/);
    const card = await screen.findByRole("region", { name: "Run of fs-payment-service-build" });
    expect(within(card).getByText("1st in queue")).toBeInTheDocument();
    expect(within(card).getByRole("img", { name: /^Score 0\.671/ })).toBeInTheDocument();
    expect(within(card).getByText("Executor slot already in use")).toBeInTheDocument();
  });

  it("refreshes the run card when the run changes", async () => {
    const { backend, session } = await backendWith(messagesThrough(byKind("run")[0]?.id ?? ""));
    renderPage(`/assistants/freestyle/${CHAT}`, backend, session);
    await screen.findByRole("region", { name: "Run of fs-payment-service-build" });
    const before = backend.calls("GET /api/chains/:id").length;
    backend.on("GET /api/chains/:id", () => json(200, captured.failedChain));

    const socket = FakeSocket.latest();
    act(() => {
      socket?.accept();
      socket?.deliver({ type: "chain.updated", sentAt: "2026-10-16T10:00:00Z", data: {} });
    });

    await waitFor(() => {
      expect(backend.calls("GET /api/chains/:id").length).toBeGreaterThan(before);
    });
    const card = await screen.findByRole("region", { name: "Run of fs-payment-service-build" });
    expect(await within(card).findByText("fs-payment-service-test-unit failed")).toBeInTheDocument();
    expect(within(card).getByRole("link", { name: "Open in Jenkins, opens in a new tab" })).toHaveAttribute(
      "href",
      "http://jenkins.test/job/fs-payment-service-test-unit/1/",
    );
  });

  it("puts an edited spec's error on its line", async () => {
    const invalid = byKind("pipeline").find(
      (message) => message.payload?.kind === "pipeline" && message.payload.pipeline_id === captured.invalidPipeline.id,
    );
    const { backend, session } = await backendWith(messagesThrough(invalid?.id ?? ""));
    renderPage(`/assistants/freestyle/${CHAT}`, backend, session);

    const preview = await screen.findByRole("complementary", { name: "Preview" });
    const problems = await within(preview).findByRole("list", { name: "Problems in Spec" });
    expect(problems).toHaveTextContent("Line 1 version: Input should be 1");
    expect(within(preview).getByText("Available once every check passes.")).toBeInTheDocument();
  });

  it("asks its question with answers to click, and sends the one chosen", async () => {
    const user = userEvent.setup();
    const question = byKind("question")[0];
    const { backend, session } = await backendWith(messagesThrough(question?.id ?? ""));
    const questionCommand = captured.questionExchange.command;
    backend
      .on("GET /api/commands/:id", (request) =>
        json(
          200,
          request.url.endsWith(`/${questionCommand?.id ?? ""}`) ? questionCommand : captured.command,
        ),
      )
      .on("POST /api/conversations/:id/messages", () => json(201, captured.intentExchange));
    renderPage(`/assistants/freestyle/${CHAT}`, backend, session);

    expect(await screen.findByText("Which service should I test?")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "payment-service" }));

    await waitFor(() => {
      expect(backend.calls("POST /api/conversations/:id/messages")).toHaveLength(1);
    });
    expect(await bodyOf(backend.calls("POST /api/conversations/:id/messages")[0])).toEqual({
      text: "payment-service",
    });
  });

  it("explains the plan as the words arrive", async () => {
    const user = userEvent.setup();
    const { backend, session } = await backendWith(messagesThrough(byKind("pipeline")[0]?.id ?? ""));
    backend.on(
      "POST /api/pipelines/:id/explain",
      () => new Response(captured.explanation, { headers: { "Content-Type": "text/plain" } }),
    );
    renderPage(`/assistants/freestyle/${CHAT}`, backend, session);

    const preview = await screen.findByRole("complementary", { name: "Preview" });
    await user.click(await within(preview).findByRole("tab", { name: "Explanation" }));
    await user.click(within(preview).getByRole("button", { name: "Explain this plan" }));

    expect(
      await within(preview).findByText(/^This creates a chain of 4 freestyle job\(s\) for payment-service/),
    ).toBeInTheDocument();
  });

  it("keeps a message that was not sent, and says why", async () => {
    const user = userEvent.setup();
    const { backend, session } = await backendWith(messagesThrough(byKind("intent")[0]?.id ?? ""));
    backend.on("POST /api/conversations/:id/messages", () =>
      apiError(429, "RATE_LIMITED", "Too many messages. Wait 12 seconds, then try again.", {
        retry_after_seconds: 12,
      }),
    );
    renderPage(`/assistants/freestyle/${CHAT}`, backend, session);

    await screen.findByRole("region", { name: "Intent" });
    await user.type(composer(), "Deploy auth-service to staging{Enter}");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Your message was not sent. Too many messages. Wait 12 seconds, then try again.",
    );
    expect(composer()).toHaveValue("Deploy auth-service to staging");
  });

  it("stops waiting on request, and says what that means", async () => {
    const user = userEvent.setup();
    const { backend, session } = await backendWith(messagesThrough(byKind("intent")[0]?.id ?? ""));
    backend.on(
      "POST /api/conversations/:id/messages",
      (request) =>
        new Promise<Response>((_, reject) => {
          request.signal.addEventListener("abort", () => {
            reject(new DOMException("The operation was aborted.", "AbortError"));
          });
        }),
    );
    renderPage(`/assistants/freestyle/${CHAT}`, backend, session);

    await screen.findByRole("region", { name: "Intent" });
    await user.type(composer(), "Deploy auth-service to staging{Enter}");
    expect(await screen.findByText("Working on it")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Stop" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Stopped waiting for the answer.");
    expect(screen.queryByText("Working on it")).toBeNull();
    expect(screen.getByRole("button", { name: "Send" })).toBeInTheDocument();
  });

  it("is the Pipeline Assistant on its own page, previewing the Jenkinsfile", async () => {
    const { backend, session } = await backendWith(null);
    const pipelineChat: ConversationDetail = {
      ...captured.conversationDetail,
      id: captured.pipelineIntentExchange.conversation.id,
      assistant: "pipeline",
      messages: [
        captured.pipelineIntentExchange.user_message,
        captured.pipelineIntentExchange.assistant_message,
        {
          id: "pipeline-reply",
          role: "ASSISTANT",
          content: `Generated and validated: ${captured.pipelinePipeline.summary ?? ""}`,
          created_at: "2026-10-16T10:00:00",
          payload: { kind: "pipeline", pipeline_id: captured.pipelinePipeline.id, status: "VALIDATED" },
        },
      ],
    };
    backend
      .on("GET /api/conversations/:id", () => json(200, pipelineChat))
      .on("GET /api/commands/:id", () => json(200, captured.pipelineIntentExchange.command));
    const user = userEvent.setup();
    renderPage(`/assistants/pipeline/${pipelineChat.id}`, backend, session);

    expect(await screen.findByRole("heading", { level: 1, name: "Pipeline Assistant" })).toBeInTheDocument();
    expect(composer()).toHaveAttribute("placeholder", "Message the Pipeline Assistant");
    const preview = await screen.findByRole("complementary", { name: "Preview" });
    await user.click(await within(preview).findByRole("tab", { name: "Jenkinsfile" }));
    expect(
      await within(preview).findByRole("textbox", {
        name: "Jenkinsfile for pl-auth-service-build-test-deploy-staging",
      }),
    ).toHaveTextContent("pipeline");
  });

  it("says when a chat cannot be opened, with the way to a new one", async () => {
    const { backend, session } = await backendWith(null);
    backend.on("GET /api/conversations/:id", () =>
      apiError(404, "CONVERSATION_NOT_FOUND", "No such conversation."),
    );
    renderPage("/assistants/freestyle/not-a-chat", backend, session);

    expect(await screen.findByText("This chat could not be opened.")).toBeInTheDocument();
    expect(screen.getByText("No such conversation.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Start a new chat" })).toHaveAttribute(
      "href",
      "/assistants/freestyle",
    );
  });
});
