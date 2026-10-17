import { describe, expect, it } from "vitest";

import type { Message } from "@/api/assistantApi";
import * as captured from "@/test/fixtures/captured";

import { previewSummary } from "./previewSummary";
import { runCardView } from "./runCardModel";
import { offsetOfPath, specProblems } from "./specProblems";
import { inThreadOrder } from "./threadOrder";

const SPEC = captured.freestylePipeline.spec_yaml;
const failed = (message: string) => [
  { name: "spec_schema", label: "Spec schema", status: "failed" as const, message, cause: "input" as const },
];

describe("spec problems", () => {
  it("puts the backend's schema error on the line it names", () => {
    // The captured error from an edited spec with version 9.
    expect(specProblems(SPEC, captured.invalidPipeline.validation?.checks ?? [])).toEqual([
      { line: 1, message: "version: Input should be 1" },
    ]);
  });

  it("follows a path into the stages, and puts a missing field on the stage it belongs to", () => {
    const lines = SPEC.split("\n");
    const lineOf = (text: string) => lines.findIndex((line) => line.includes(text)) + 1;

    expect(
      specProblems(SPEC, failed("stages.1.suite: Input should be a valid string; stages.3.timeout: Field required")),
    ).toEqual([
      { line: lineOf("suite: unit"), message: "stages.1.suite: Input should be a valid string" },
      { line: lineOf("name: Deploy to staging"), message: "stages.3.timeout: Field required" },
    ]);
  });

  it("uses YAML's own line number when the spec is not YAML at all", () => {
    const message =
      'the spec is not valid YAML: while parsing a block mapping\n  in "<unicode string>", line 1, column 1\nexpected <block end>, but found \'-\'\n  in "<unicode string>", line 4, column 1';

    expect(specProblems("a: 1\nb: 2\n-c\n- d\n", failed(message))).toEqual([{ line: 4, message }]);
  });

  it("lists a problem with no line without placing it", () => {
    expect(specProblems(SPEC, failed("the spec must be a YAML mapping"))).toEqual([
      { line: null, message: "the spec must be a YAML mapping" },
    ]);
    expect(specProblems(SPEC, failed("spec: Input should be a valid dictionary"))).toEqual([
      { line: null, message: "Input should be a valid dictionary" },
    ]);
  });

  it("says nothing when the spec passed, and leaves other checks to the checklist", () => {
    expect(specProblems(SPEC, captured.freestylePipeline.validation?.checks ?? [])).toEqual([]);
    expect(
      specProblems(SPEC, [
        { name: "catalog_and_git", label: "Catalog and Git", status: "failed", message: "No such suite.", cause: "plan" },
      ]),
    ).toEqual([]);
  });

  it("finds a path's offset, and the deepest part of it that exists", () => {
    const text = "version: 1\nstages:\n  - name: Build\n    template: build\n";
    expect(offsetOfPath(text, ["version"])).toBe(0);
    expect(text.slice(offsetOfPath(text, ["stages", 0, "template"]))).toMatch(/^template: build/);
    expect(text.slice(offsetOfPath(text, ["stages", 0, "nothing"]))).toMatch(/^name: Build/);
    expect(offsetOfPath(text, ["missing"])).toBe(0);
  });
});

describe("thread order", () => {
  const at = (id: string, role: "USER" | "ASSISTANT", time: string): Message => ({
    id,
    role,
    content: id,
    created_at: time,
    payload: null,
  });

  it("puts a message before its reply when both have the same time", () => {
    const ordered = inThreadOrder([
      at("question", "USER", "2026-10-16T10:00:00.100000"),
      at("reply", "ASSISTANT", "2026-10-16T10:00:00.200000"),
      at("help-reply", "ASSISTANT", "2026-10-16T10:00:01.000000"),
      at("help", "USER", "2026-10-16T10:00:01.000000"),
    ]);

    expect(ordered.map(({ id }) => id)).toEqual(["question", "reply", "help", "help-reply"]);
  });

  it("orders the captured conversation with every message before its reply", () => {
    const ordered = inThreadOrder(captured.conversationDetail.messages);

    expect(ordered.at(-2)?.content).toBe("/help");
    expect(ordered.at(-1)?.payload?.kind).toBe("help");
  });
});

describe("run card view", () => {
  it("shows a queued chain's place, score and the jobs still to run", () => {
    const view = runCardView(captured.queuedChain);

    expect(view.jobName).toBe("fs-payment-service-build");
    expect(view.queue).toMatchObject({ rank: 1, score: 0.671179, waitingReason: "Executor slot already in use" });
    expect(view.queue?.weights).toEqual({ urgency: 0.5, dependency: 0.3, executionTime: 0.2 });
    expect(view.stages.map(({ state }) => state)).toEqual(["queued", "not-built", "not-built", "not-built"]);
    expect(view.result).toBeNull();
  });

  it("shows a finished chain's result, its duration, and the failed run's Jenkins page", () => {
    const view = runCardView(captured.failedChain);

    expect(view.stages.map(({ name, state }) => `${name} ${state}`)).toEqual([
      "fs-payment-service-build succeeded",
      "fs-payment-service-test-unit failed",
      "fs-payment-service-test-integration not-built",
      "fs-payment-service-deploy-staging not-built",
    ]);
    expect(view.result).toEqual({ state: "failed", durationMs: 5555 });
    expect(view.jenkinsUrl).toBe("http://jenkins.test/job/fs-payment-service-test-unit/1/");
    expect(view.queue).toBeNull();
  });

  it("shows a Pipeline's stages, not its one job", () => {
    const view = runCardView({
      ...captured.failedChain,
      job_type: "PIPELINE",
      stages: [
        { name: "Build", status: "SUCCESS", duration_ms: 1200 },
        { name: "Unit tests", status: "FAILED", duration_ms: 3000 },
        { name: "Deploy", status: "NOT_EXECUTED", duration_ms: 0 },
      ],
    });

    expect(view.stages).toEqual([
      { name: "Build", state: "succeeded" },
      { name: "Unit tests", state: "failed" },
      { name: "Deploy", state: "not-built" },
    ]);
  });
});

describe("preview summary", () => {
  it("says in one line what the preview holds", () => {
    expect(previewSummary(null)).toBe("Preview: nothing generated yet");
    expect(previewSummary(captured.freestylePipeline)).toBe("Preview: 4 jobs, all checks pass");
    expect(previewSummary(captured.pipelinePipeline)).toBe("Preview: 1 job, all checks pass");
    expect(previewSummary(captured.invalidPipeline)).toBe("Preview: 1 check failed");
    expect(previewSummary({ ...captured.freestylePipeline, status: "APPROVED" })).toBe(
      "Preview: approved and started",
    );
  });
});
