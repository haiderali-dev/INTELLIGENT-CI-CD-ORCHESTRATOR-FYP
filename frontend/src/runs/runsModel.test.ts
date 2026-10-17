import { describe, expect, it } from "vitest";

import * as captured from "@/test/fixtures/pages";

import {
  assistantOf,
  chainDurationMs,
  chainState,
  currentStep,
  filterChains,
  finishedRuns,
} from "./runsModel";
import { countLines, keepEnd, lastLines } from "./logModel";

const chains = captured.chains.items;

describe("the runs model", () => {
  it("reads a chain's status as a build state, naming the one Jenkins has no word for", () => {
    expect(chainState("RUNNING")).toEqual({ state: "running" });
    expect(chainState("SUCCESS")).toEqual({ state: "succeeded" });
    expect(chainState("FAILURE")).toEqual({ state: "failed" });
    expect(chainState("ABORTED")).toEqual({ state: "aborted" });
    expect(chainState("EXPIRED")).toEqual({ state: "aborted", label: "Expired" });
  });

  it("names the assistant from the job type", () => {
    expect(assistantOf("FREESTYLE")).toBe("Freestyle");
    expect(assistantOf("PIPELINE")).toBe("Pipeline");
    expect(assistantOf("MAVEN")).toBe("MAVEN");
  });

  it("applies the assistant and result filters the API does not take", () => {
    const names = (filter: Parameters<typeof filterChains>[1]) =>
      filterChains(chains, filter).map(({ jobs }) => jobs[0]);

    expect(names({ assistant: null, result: null })).toHaveLength(3);
    expect(names({ assistant: "pipeline", result: null })).toEqual([
      "pl-payment-service-build-test-deploy-staging",
    ]);
    expect(names({ assistant: "freestyle", result: "failed" })).toEqual(["fs-payment-service-build"]);
    expect(names({ assistant: "pipeline", result: "failed" })).toEqual([]);
    expect(names({ assistant: null, result: "running" })).toHaveLength(2);
  });

  it("times a finished chain, and not a running one", () => {
    const failed = chains.find(({ status }) => status === "FAILURE");
    const running = chains.find(({ status }) => status === "RUNNING");

    // 03:13:49.914273 to 03:13:50.107950 in the capture; a JavaScript date keeps milliseconds.
    expect(failed && chainDurationMs(failed)).toBe(193);
    expect(running && chainDurationMs(running)).toBeNull();
  });

  it("says what an active chain is doing: a Pipeline's stage, or the job under way", () => {
    expect(currentStep(captured.chainPipelineRunning)).toEqual({
      state: "running",
      text: "Unit tests stage",
    });
    expect(currentStep(captured.chainQueued)).toEqual({
      state: "queued",
      text: "fs-auth-service-build",
    });
    // Between jobs: the build passed and the tests have not been triggered yet.
    const between = {
      ...captured.chainFailed,
      status: "RUNNING" as const,
      jobs: captured.chainFailed.jobs.map((job, index) =>
        index === 0 ? job : { ...job, state: "not_started" as const, run: null },
      ),
    };
    expect(currentStep(between)).toEqual({
      state: "running",
      text: "Waiting to start fs-payment-service-test-unit",
    });
  });

  it("keeps the newest finished runs, leaving out those still building", () => {
    expect(finishedRuns(captured.runs.items, 10).map(({ job_name: name }) => name)).toEqual([
      "fs-payment-service-test-unit",
      "fs-payment-service-build",
    ]);
    expect(finishedRuns(captured.runs.items, 1)).toHaveLength(1);
  });
});

describe("the log tail", () => {
  it("counts a line once its newline has arrived", () => {
    expect(countLines("")).toBe(0);
    expect(countLines("one\ntwo\n")).toBe(2);
    expect(countLines("one\ntwo")).toBe(1);
  });

  it("keeps the end of a log with its newlines, so the next window joins it correctly", () => {
    expect(keepEnd("a\nb\nc\n", 2)).toBe("b\nc\n");
    expect(keepEnd("a\nb\nunfinished", 2)).toBe("b\nunfinished");
    expect(keepEnd("a\n", 5)).toBe("a\n");
    // The next window continues an unfinished line rather than starting a new one.
    expect(lastLines(keepEnd("a\nb\nhalf", 2) + " done\nnext\n", 2)).toBe("half done\nnext");
  });

  it("shows the last lines of the real failing log, ending where Jenkins ended it", () => {
    const shown = lastLines(captured.logFailed.text, 3);

    expect(shown.split("\n")).toEqual(["Build step 'Execute shell' marked build as failure", "Archiving artifacts", "Finished: FAILURE"]);
    expect(countLines(captured.logFailed.text)).toBe(57);
  });
});
